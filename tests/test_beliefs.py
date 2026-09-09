import ast
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from ekk.application import beliefs
from ekk.application.beliefs import (Condition, Observation, ObservationRequest,
                                     RequirementSet, assess_action)


class BeliefReadinessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        self.condition = Condition('schema', 'env:local', 'v1', 'schema_ready',
                                   max_age_seconds=60, observation_requests=('read-schema',))
        self.requirements = RequirementSet('requirements', 1, 'change', 'env:local', 'v1',
                                           'complete', (self.condition,))
        self.observation = Observation('sensor-result', 'schema-sensor', '2', 'env:local', 'v1',
            'schema_ready', True, 'observed', self.now, 'sha256:' + 'a' * 64)
        self.request = ObservationRequest('read-schema', 'env:local', 'v1', 'schema_ready', True, 'one read')
        self.context = {'blocked': False, 'manifest': {'realm_id': 'synthetic', 'snapshot': 'snapshot-1'}}

    def assess(self, observations=None, **changes):
        options = dict(context=self.context, target_versions={'env:local': 'v1'},
                       assessed_at=self.now, requests=(self.request,))
        requirements = changes.pop('requirements', self.requirements)
        options.update(changes)
        return assess_action(requirements, (self.observation,) if observations is None else observations, **options)

    def test_projection_is_deterministic_and_never_an_execution_or_outcome(self):
        context = copy.deepcopy(self.context)
        a = self.assess(context=context)
        self.assertEqual(a, self.assess(context=context))
        self.assertEqual(a['state'], 'requirements_met')
        self.assertEqual(a['authority_effect'], 'none')
        self.assertEqual(a['execution'], 'not_performed')
        self.assertEqual(a['outcome'], 'not_observed')
        self.assertEqual(a['snapshot_semantics'], 'historical_projection')
        json.dumps(a, allow_nan=False)
        a['inputs']['context_manifest']['snapshot'] = 'modified-output'
        self.assertEqual(context, self.context)

    def test_incomplete_unknown_and_empty_requirements_cannot_be_vacuously_ready(self):
        variants = [replace(self.requirements, completeness=x) for x in ('unknown', 'incomplete')]
        variants.append(replace(self.requirements, conditions=()))
        for requirements in variants:
            with self.subTest(requirements=requirements):
                self.assertEqual(self.assess(requirements=requirements)['state'], 'indeterminate')

    def test_caller_mutation_cannot_change_the_inputs_after_their_digest_is_computed(self):
        context = copy.deepcopy(self.context)
        versions = {'env:local': 'v1'}
        original_digest = beliefs._digest

        def concurrent_caller_change(value):
            computed = original_digest(value)
            if 'requirements' in value:
                context['blocked'] = True
                context['manifest']['snapshot'] = 'later-snapshot'
                versions['env:local'] = 'v2'
            return computed

        with patch.object(beliefs, '_digest', side_effect=concurrent_caller_change):
            result = self.assess(context=context, target_versions=versions)
        self.assertTrue(context['blocked'])
        self.assertEqual(versions['env:local'], 'v2')
        self.assertEqual(result['state'], 'requirements_met')
        self.assertFalse(result['inputs']['context_blocked'])
        self.assertEqual(result['inputs']['context_manifest']['snapshot'], 'snapshot-1')
        self.assertEqual(result['inputs']['target_versions'], {'env:local': 'v1'})
        self.assertEqual(result['input_digest'], original_digest(result['inputs']))

    def test_explicit_context_block_and_current_version_mismatch_remain_restrictions(self):
        for changes in [dict(context={**self.context, 'blocked': True}),
                        dict(target_versions={}), dict(target_versions={'env:local': 'v2'})]:
            result = self.assess(**changes)
            self.assertEqual(result['state'], 'indeterminate')
            self.assertEqual(result['observation_requests'], [])

    def test_known_incomplete_context_cannot_be_cleared_by_matching_observations(self):
        context = {**self.context, 'manifest': {**self.context['manifest'], 'incomplete': True}}
        result = self.assess(context=context)
        self.assertEqual(result['state'], 'indeterminate')
        self.assertIn('context_incomplete', result['reasons'])
        self.assertEqual(result['observation_requests'], [])
        self.assertFalse(result['inputs']['context_blocked'])

    def test_wrong_target_version_time_mode_and_invalidation_do_not_satisfy_requirement(self):
        variants = [replace(self.observation, target='env:other'),
                    replace(self.observation, version='v0'),
                    replace(self.observation, observed_at=self.now - timedelta(seconds=61)),
                    replace(self.observation, observed_at=self.now + timedelta(seconds=1)),
                    replace(self.observation, mode='inferred'),
                    replace(self.observation, mode='assumed'),
                    replace(self.observation, status='unavailable'),
                    replace(self.observation, value=None)]
        for observation in variants:
            with self.subTest(observation=observation):
                result = self.assess((observation,))
                self.assertEqual(result['state'], 'needs_observation')
        self.assertEqual(self.assess(invalidated_observations=('sensor-result',))['state'], 'needs_observation')

    def test_false_prerequisite_is_not_unknown_and_does_not_trigger_blind_reobservation(self):
        result = self.assess((replace(self.observation, value=False),))
        self.assertEqual(result['state'], 'requirements_not_met')
        self.assertEqual(result['conditions'][0]['state'], 'refuted')
        self.assertEqual(result['observation_requests'], [])

    def test_incomplete_assessment_keeps_known_failure_visible(self):
        context = {**self.context, 'manifest': {**self.context['manifest'], 'incomplete': True}}
        result = self.assess((replace(self.observation, value=False),), context=context)
        self.assertEqual(result['state'], 'indeterminate')
        self.assertIn('context_incomplete', result['reasons'])
        self.assertEqual(result['conditions'][0]['state'], 'refuted')
        self.assertEqual(result['observation_requests'], [])

    def test_conflict_and_alternatives_are_not_resolved_by_order_or_recency(self):
        counter = replace(self.observation, id='counter', value=False, observed_at=self.now - timedelta(seconds=1))
        for observations in [(self.observation, counter), (counter, self.observation),
                             (replace(self.observation, alternatives=('sensor may read a replica',)),)]:
            result = self.assess(observations)
            self.assertEqual(result['conditions'][0]['state'], 'conflicted')
            self.assertNotEqual(result['state'], 'requirements_met')

    def test_domain_can_allow_inference_but_uncertainty_is_not_a_confidence_override(self):
        requirements = replace(self.requirements, conditions=(replace(self.condition, modes=('inferred',)),))
        self.assertEqual(self.assess((replace(self.observation, mode='inferred'),), requirements=requirements)['state'], 'requirements_met')
        uncertain = replace(self.observation, mode='inferred', alternatives=('other current state remains possible',))
        self.assertNotEqual(self.assess((uncertain,), requirements=requirements)['state'], 'requirements_met')

    def test_only_explicit_matching_host_requests_are_returned(self):
        variants = [(), (replace(self.request, id='invented'),),
                    (replace(self.request, target='env:other'),),
                    (replace(self.request, version='v2'),),
                    (replace(self.request, proposition='other_fact'),),
                    (replace(self.request, available=False),)]
        for requests in variants:
            self.assertEqual(self.assess((), requests=requests)['state'], 'indeterminate')
        result = self.assess(())
        self.assertEqual([r['id'] for r in result['observation_requests']], ['read-schema'])
        self.assertEqual(result['authority_effect'], 'none')

    def test_receipt_does_not_establish_world_outcome_or_unrelated_condition(self):
        receipt = replace(self.observation, proposition='deployment_request_accepted')
        result = self.assess((receipt,))
        self.assertEqual(result['state'], 'needs_observation')
        self.assertEqual(result['outcome'], 'not_observed')
        irrelevant = replace(self.observation, id='irrelevant', proposition='unrelated', value=None)
        self.assertEqual(self.assess((self.observation, irrelevant))['state'], 'requirements_met')

    def test_handoff_requires_new_assessment_and_does_not_refresh_observation_time(self):
        first = self.assess()
        later = self.assess(assessed_at=self.now + timedelta(seconds=61))
        self.assertEqual(first['state'], 'requirements_met')
        self.assertEqual(later['state'], 'needs_observation')
        self.assertNotEqual(first['input_digest'], later['input_digest'])
        self.assertEqual(first['inputs']['observations'], later['inputs']['observations'])
        self.assertNotEqual(first['requirement_set_digest'], self.assess(
            requirements=replace(self.requirements, revision=2))['requirement_set_digest'])

    def test_dst_fold_cannot_make_a_stale_or_future_observation_current(self):
        zone = ZoneInfo('America/New_York')
        requirements = replace(self.requirements,
                               conditions=(replace(self.condition, max_age_seconds=3600),))
        cases = [
            (datetime(2026, 11, 1, 1, 5, tzinfo=zone, fold=0),
             datetime(2026, 11, 1, 1, 55, tzinfo=zone, fold=1), 'stale'),
            (datetime(2026, 11, 1, 1, 5, tzinfo=zone, fold=1),
             datetime(2026, 11, 1, 1, 55, tzinfo=zone, fold=0), 'future_observation'),
        ]
        for observed_at, assessed_at, reason in cases:
            with self.subTest(reason=reason):
                result = self.assess((replace(self.observation, observed_at=observed_at),),
                                     assessed_at=assessed_at, requirements=requirements)
                self.assertEqual(result['state'], 'needs_observation')
                self.assertIn(reason, result['conditions'][0]['excluded_observations'][0]['reasons'])

    def test_invalid_contracts_fail_before_assessment(self):
        cases = [dict(assessed_at=self.now.replace(tzinfo=None)), dict(context={'manifest': {}}),
                 dict(requirements=replace(self.requirements, revision=True)),
                 dict(requirements=replace(self.requirements, conditions=(self.condition, self.condition))),
                 dict(requirements=replace(self.requirements, conditions=(replace(self.condition, max_age_seconds=float('nan')),))),
                 dict(requirements=replace(self.requirements, conditions=(replace(self.condition, modes=()),))),
                 dict(requirements=replace(self.requirements, conditions=(replace(self.condition, expected=1),)))]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.assess(**options)
        for observation in [replace(self.observation, evidence_digest='unverified'),
                            replace(self.observation, value=1)]:
            with self.assertRaises(ValueError):
                self.assess((observation,))
        with self.assertRaises(ValueError):
            self.assess((self.observation, self.observation))

    def test_application_boundary_has_no_io_adapter_or_implicit_clock(self):
        source = inspect.getsource(beliefs)
        tree = ast.parse(source)
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertLessEqual(imported, {'copy', 'dataclasses', 'datetime', 'hashlib', 'json', 'math'})
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(c.func, ast.Attribute) and c.func.attr in ('now', 'utcnow') for c in calls))


if __name__ == '__main__':
    unittest.main()
