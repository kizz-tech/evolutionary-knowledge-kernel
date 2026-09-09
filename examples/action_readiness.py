"""Resettable local illustration; no models, external sensors or action effects."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

from ekk.application.beliefs import (Condition, Observation, ObservationRequest,
                                     RequirementSet, assess_action)


def demonstrate():
    now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    context = {'blocked': False, 'manifest': {'realm_id': 'synthetic', 'snapshot': 'fixture-v1'}}
    required = RequirementSet('change-contract', 1, 'prepare-change', 'env:local', 'env-v1',
        'complete', (
            Condition('ci', 'repo:local', 'commit-B', 'ci_passed', observation_requests=('check-ci',)),
            Condition('schema', 'env:local', 'env-v1', 'schema_at_least_184',
                      observation_requests=('read-schema',)),
        ))
    versions = {'repo:local': 'commit-B', 'env:local': 'env-v1'}
    requests = (
        ObservationRequest('check-ci', 'repo:local', 'commit-B', 'ci_passed', True, 'one local fixture read'),
        ObservationRequest('read-schema', 'env:local', 'env-v1', 'schema_at_least_184', True, 'one local fixture read'),
    )

    def observation(key, target, version, proposition, value):
        payload = json.dumps([target, version, proposition, value]).encode()
        return Observation(key, 'fixture-sensor', '1', target, version, proposition,
                           value, 'observed', now, 'sha256:' + hashlib.sha256(payload).hexdigest())

    ci = observation('ci-B', 'repo:local', 'commit-B', 'ci_passed', True)
    schema = observation('schema-184', 'env:local', 'env-v1', 'schema_at_least_184', True)
    receipt = observation('request-accepted', 'env:local', 'env-v1', 'deployment_request_accepted', True)
    cases = {}

    def check(name, observations, expected, **overrides):
        inputs = dict(context=context, target_versions=versions, assessed_at=now, requests=requests)
        inputs.update(overrides)
        result = assess_action(required, observations, **inputs)
        assert result['state'] == expected, (name, result)
        assert result['execution'] == 'not_performed' and result['outcome'] == 'not_observed'
        cases[name] = {'state': result['state'],
                       'next_observations': [r['id'] for r in result['observation_requests']],
                       'execution': result['execution'], 'outcome': result['outcome']}

    check('matching_current_evidence', (ci, schema), 'requirements_met')
    check('old_commit_ci', (observation('ci-A', 'repo:local', 'commit-A', 'ci_passed', True), schema), 'needs_observation')
    check('wrong_environment', (ci, observation('schema-other', 'env:other', 'env-v1', 'schema_at_least_184', True)), 'needs_observation')
    check('receipt_without_schema_observation', (ci, receipt), 'needs_observation')
    check('prerequisite_observed_false', (ci, observation('schema-183', 'env:local', 'env-v1', 'schema_at_least_184', False)), 'requirements_not_met')
    check('expired_handoff_inputs', (ci, schema), 'needs_observation', assessed_at=now + timedelta(minutes=6))
    check('unavailable_sensor', (ci,), 'indeterminate', requests=())
    check('world_version_changed', (ci, schema), 'indeterminate',
          target_versions={**versions, 'env:local': 'env-v2'})
    check('accepted_context_hold', (ci, schema), 'indeterminate', context={**context, 'blocked': True})
    return {'schema': 'ekk.action-readiness-demo/0.1', 'cases': cases,
            'mechanism_demonstration': True, 'comparative_study': 'not_run',
            'limitation': 'Known synthetic requirements and interpreted sensor inputs; no autonomous observation choice or measured agent benefit.'}


if __name__ == '__main__':
    print(json.dumps(demonstrate(), indent=2))
