"""A real bound CLI route, fallible report bytes and commit-specific readiness."""
import copy
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters import coding_assessment as adapter
from ekk.adapters.command_line import dispatch, main, parser, service


class CodingAssessmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        environment = {k: v for k, v in os.environ.items() if not k.startswith(('EKK_', 'GIT_'))}
        environment.update(EKK_CONFIG_HOME=str(self.root / 'config'),
            EKK_DATA_HOME=str(self.root / 'data'), EKK_CACHE_HOME=str(self.root / 'cache'))
        env = patch.dict(os.environ, environment, clear=True)
        env.start(); self.addCleanup(env.stop)
        self.workspace = self.root / 'workspace'; self.workspace.mkdir()
        self.app = service(self.root / 'realm')
        self.app.init(title='Synthetic project', realm_id=self.app.initial_realm_id, context_id='context:test')
        profiles = self.root / 'config/profiles'; profiles.mkdir(parents=True)
        profile = {'schema': 'ekk.profile/0.1', 'uid': os.getuid(),
                   'realms': {'project': {'id': self.app.initial_realm_id, 'path': str(self.root / 'realm')}}}
        (profiles / 'test.yaml').write_text(json.dumps(profile))
        self.control = self.workspace / '.ekk/workspace.yaml'; self.control.parent.mkdir()
        self.document = {'schema': 'ekk.workspace/0.1', 'workspace_id': 'workspace:test', 'profile': 'test',
            'bindings': [{'realm_alias': 'project', 'realm_id': self.app.initial_realm_id, 'contexts': ['context:test']}],
            'evidence_checks': [{'id': 'unit', 'path': '.reports/unit.json'}]}
        self.control.write_text(json.dumps(self.document))
        (self.workspace / '.gitignore').write_text('.reports/\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic tester')
        self.git('config', 'user.email', 'tester@example.invalid')
        self.git('add', '.'); self.git('commit', '-qm', 'Synthetic initial commit')
        self.head = self.git('rev-parse', 'HEAD')
        self.report = self.workspace / '.reports/unit.json'; self.report.parent.mkdir()
        self.request = {'schema': adapter.REQUEST_SCHEMA, 'action_id': 'review-selected-commit',
                        'expected_head': self.head, 'completeness': 'complete', 'checks': ['unit']}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.workspace), *args], text=True).strip()

    def report_bytes(self, **changes):
        return json.dumps({'schema': adapter.REPORT_SCHEMA, 'workspace_id': 'workspace:test',
            'check_id': 'unit', 'tested_commit': self.head,
            'observed_at': datetime.now(timezone.utc).isoformat(), 'status': 'passed', **changes}).encode()

    def write_report(self, **changes):
        self.report.write_bytes(self.report_bytes(**changes))

    def call(self, request=None, *options):
        stdout, stderr = StringIO(), StringIO()
        with patch('sys.stdin', StringIO(json.dumps(self.request if request is None else request))), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(['assess', '--cwd', str(self.workspace), '--stdin', *options])
        return code, json.loads(stdout.getvalue() or stderr.getvalue()), stderr.getvalue()

    def test_real_commit_change_requires_new_report_and_old_view_stays_historical(self):
        code, absent, _ = self.call()
        self.assertEqual((code, absent['state']), (1, 'needs_observation'))
        self.assertEqual([r['id'] for r in absent['observation_requests']], ['unit'])
        self.write_report()
        code, prior, _ = self.call()
        self.assertEqual((code, prior['state']), (0, 'requirements_met'))
        self.assertEqual(prior['inputs']['observations'][0]['evidence_digest'],
                         'sha256:' + hashlib.sha256(self.report.read_bytes()).hexdigest())
        (self.workspace / 'change.txt').write_text('a changed committed target')
        self.git('add', 'change.txt'); self.git('commit', '-qm', 'Change target')
        self.assertEqual(self.call()[1]['state'], 'indeterminate')
        self.head = self.git('rev-parse', 'HEAD'); self.request['expected_head'] = self.head
        self.assertEqual(self.call()[1]['state'], 'needs_observation')
        self.write_report()
        code, current, _ = self.call()
        self.assertEqual((code, current['state']), (0, 'requirements_met'))
        self.assertNotEqual(prior['assessment_digest'], current['assessment_digest'])
        self.assertNotEqual(prior['inputs']['observations'][0]['id'], current['inputs']['observations'][0]['id'])
        self.assertNotEqual(prior['inputs']['requirements']['id'], current['inputs']['requirements']['id'])
        self.assertEqual(prior['snapshot_semantics'], 'historical_projection')
        self.assertNotEqual(prior['inputs']['requirements']['action_version'], self.head)
        for result in (prior, current):
            self.assertEqual(result['authority_effect'], 'none')
            self.assertEqual(result['execution'], 'not_performed')
            self.assertEqual(result['outcome'], 'not_observed')

    def test_failed_unknown_expired_and_future_reports_are_distinct(self):
        for fields, expected in [({'status': 'failed'}, 'requirements_not_met'),
                ({'status': 'unknown'}, 'needs_observation'),
                ({'observed_at': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}, 'needs_observation'),
                ({'observed_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, 'needs_observation')]:
            with self.subTest(fields=fields):
                self.write_report(**fields)
                code, result, _ = self.call()
                self.assertEqual((code, result['state']), (1, expected))

    def test_reports_cannot_supply_semantics_or_cross_workspace_identity(self):
        malformed = [self.report_bytes(workspace_id='workspace:other'), self.report_bytes(check_id='other'),
            self.report_bytes(sensor='trusted'), self.report_bytes(status=True),
            self.report_bytes(tested_commit='HEAD'), self.report_bytes(observed_at='2026-09-09T12:00:00'),
            self.report_bytes().replace(b'"status": "passed"', b'"status":"failed","status":"passed"'),
            self.report_bytes().replace(b'"status": "passed"', b'"status":NaN')]
        for raw in malformed:
            with self.subTest(raw=raw):
                self.report.write_bytes(raw)
                observation, evidence = adapter._report(self.workspace, '.reports/unit.json',
                    'workspace:test', 'unit', 'configured_check:unit:report_declares_passed')
                self.assertIsNone(observation)
                self.assertEqual(evidence['status'], 'unavailable_or_invalid')

    def test_report_reader_is_bounded_and_rejects_symlink_directory_and_fifo(self):
        secret = self.root / 'private'; secret.write_bytes(b'private contents')
        self.report.symlink_to(secret)
        for kind in ('symlink', 'large', 'directory', 'fifo'):
            if kind != 'symlink':
                self.report.unlink() if not self.report.is_dir() else self.report.rmdir()
                if kind == 'large': self.report.write_bytes(b'x' * (adapter.MAX_REPORT_BYTES + 1))
                elif kind == 'directory': self.report.mkdir()
                else: os.mkfifo(self.report)
            observation, evidence = adapter._report(self.workspace, '.reports/unit.json', 'workspace:test', 'unit', 'p')
            self.assertIsNone(observation)
            self.assertNotIn('private contents', json.dumps(evidence))

    def test_supplied_context_commands_and_unconfigured_ids_are_rejected(self):
        for change in ({'context': {'blocked': False}}, {'checks': []}, {'checks': ['unit', 'unit']},
                {'checks': ['../../private']}, {'command': 'do not execute'}, {'expected_head': 'HEAD'},
                {'max_age_seconds': -1}, {'schema': 'unknown'}):
            with self.subTest(change=change):
                code, result, _ = self.call({**self.request, **change})
                self.assertEqual(code, 2)
                self.assertIn('error', result)

    def test_large_finite_integer_age_and_nested_operation_have_defined_transport_results(self):
        self.write_report()
        self.assertEqual(self.call({**self.request, 'max_age_seconds': 10**400})[0], 0)
        for outer in ({'request_id': 'mismatch'}, {'operation': 'assess'}):
            code, result, _ = self.call({**outer, 'payload': {**self.request, 'operation': 'retain'}})
            self.assertEqual(code, 2)
            self.assertEqual(result['status'], 'error')

    def test_directory_swap_to_symlink_cannot_redirect_report_open(self):
        outside = self.root / 'outside'; outside.mkdir()
        (outside / 'unit.json').write_bytes(self.report_bytes())
        open_file = os.open
        def swap(component, flags, *args, **kwargs):
            if component == '.reports':
                self.report.parent.rename(self.workspace / '.original-reports')
                self.report.parent.symlink_to(outside)
            return open_file(component, flags, *args, **kwargs)
        with patch.object(adapter.os, 'open', side_effect=swap):
            observation, evidence = adapter._report(self.workspace, '.reports/unit.json',
                'workspace:test', 'unit', 'configured_check:unit:report_declares_passed')
        self.assertIsNone(observation)
        self.assertIsNone(evidence['sha256'])

    def test_changed_context_publication_invalidates_report_assessment(self):
        self.write_report()
        context = self.app.context(['context:test'], selection='action_requirements')
        with patch('ekk.adapters.command_line.service') as factory:
            factory.return_value.context.return_value = context
            factory.return_value.publication_revision.return_value = 'later-publication'
            code, result, _ = self.call()
        self.assertEqual((code, result['state']), (1, 'indeterminate'))
        self.assertIn('context_changed_during_assessment', result['reasons'])

    def test_overrides_are_rejected_before_diagnostic_root_probe(self):
        for option in ('--root', '--realm'):
            with patch('ekk.adapters.command_line._routes') as route_probe:
                code, _, _ = self.call(None, option, str(self.root / 'unrelated'))
            self.assertEqual(code, 2)
            route_probe.assert_not_called()

    def test_scope_and_profile_denial_do_not_read_reports_or_fallback(self):
        for options in [('--scope', 'context:other'), ('--profile', 'absent')]:
            with patch.object(adapter, '_report') as report:
                code, _, _ = self.call(None, *options)
                self.assertEqual(code, 2)
                report.assert_not_called()
        with patch.object(adapter.LocalProfile, 'home', side_effect=AssertionError('No personal fallback')):
            self.assertEqual(self.call(None, '--cwd', str(self.root / 'unbound'))[0], 2)

    def test_blocked_and_incomplete_context_cannot_be_cleared_by_report(self):
        self.write_report()
        original = self.app.context(['context:test'], selection='action_requirements')
        for reason in ('context_blocked', 'context_incomplete'):
            context = copy.deepcopy(original)
            if reason == 'context_blocked': context['blocked'] = True
            else: context['manifest']['incomplete'] = True
            with patch('ekk.application.service.RealmService.context', return_value=context):
                code, result, _ = self.call()
            self.assertEqual((code, result['state']), (1, 'indeterminate'))
            self.assertIn(reason, result['reasons'])
            self.assertEqual(result['observation_requests'], [])

    def test_git_change_ending_at_expected_head_is_still_indeterminate(self):
        self.write_report()
        with patch.object(adapter, '_head', side_effect=[{'status': 'available', 'commit': 'a' * 40},
                                                       {'status': 'available', 'commit': self.head}]):
            code, result, _ = self.call()
        self.assertEqual((code, result['state']), (1, 'indeterminate'))
        self.assertIn('git_changed_during_assessment', result['reasons'])

    def test_binding_change_during_report_read_invalidates_assessment(self):
        self.write_report()
        read = adapter._report
        def change_binding(*args):
            result = read(*args)
            self.control.write_text(self.control.read_text() + '\n')
            return result
        with patch.object(adapter, '_report', side_effect=change_binding):
            code, result, _ = self.call()
        self.assertEqual((code, result['state']), (1, 'indeterminate'))
        self.assertIn('binding_changed_during_assessment', result['reasons'])

    def test_git_sensor_ignores_inherited_routing_and_assesses_only_committed_object(self):
        self.write_report()
        with patch.dict(os.environ, {'GIT_DIR': str(self.root / 'absent'), 'GIT_WORK_TREE': str(self.root)}):
            self.assertEqual(adapter._head(self.workspace)['commit'], self.head)
        (self.workspace / 'uncommitted.txt').write_text('not part of the selected commit')
        code, result, _ = self.call()
        self.assertEqual(code, 0)
        self.assertEqual(result['host_observation']['target_semantics'], 'committed_git_object_only')
        child = self.workspace / 'child'; child.mkdir()
        self.assertEqual(adapter._head(child)['reason'], 'binding_is_not_git_root')

    def test_envelope_exit_and_diagnostics_keep_read_only_semantics(self):
        self.write_report()
        common = {'request_id': 'assessment-1', 'operation': 'assess', 'payload': self.request}
        code, result, stderr = self.call(common)
        self.assertEqual((code, result['status']), (0, 'completed'))
        self.assertTrue(result['snapshot'])
        self.assertFalse(result['incomplete'])
        self.assertFalse(stderr)
        rows = [json.loads(line) for line in (self.root / 'data/operations/operations.jsonl').read_text().splitlines()]
        attempts = [row for row in rows if row.get('operation') == 'assess' and 'result' in row]
        self.assertEqual(len(attempts), 1)
        self.assertFalse(attempts[0]['mutated'])
        self.assertEqual(attempts[0]['result'], 'completed')
        self.assertNotIn('review-selected-commit', json.dumps(rows))
        self.report.unlink()
        code, result, _ = self.call(common)
        self.assertEqual((code, result['status']), (1, 'blocked'))
        self.assertEqual(result['data']['state'], 'needs_observation')

    def preset(self, **changes):
        definition = {'id': 'review', 'checks': ['unit'], 'grounds': [],
                      'completeness': 'complete', 'max_age_seconds': 300, **changes}
        self.document['assessment_actions'] = [definition]
        self.control.write_text(json.dumps(self.document))
        return definition

    def named_call(self, *options):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(['assess', '--cwd', str(self.workspace), '--action', 'review', *options])
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_named_action_uses_first_observation_and_compact_keeps_evidence(self):
        self.preset(); self.write_report()
        code, result = self.named_call()
        self.assertEqual((code, result['state']), (0, 'requirements_met'))
        self.assertEqual(result['inputs']['requirements']['action_version'], self.head)
        self.assertEqual(result['host_observation']['target_selection'], 'freshly_observed_default')
        self.assertEqual(result['host_observation']['requirements_source'], 'workspace_owner_named_action')
        before = copy.deepcopy(result)
        compact = adapter.compact_assessment(result)
        self.assertEqual(result, before)
        for key in ('state', 'reasons', 'blocked', 'input_digest', 'assessment_digest', 'observation_requests'):
            self.assertEqual(compact[key], result[key])
        self.assertEqual(compact['working_tree'], 'not_assessed')
        self.assertEqual(compact['target_semantics'], 'committed_git_object_only')
        self.assertFalse(compact['producer_authenticated'])
        code, displayed = self.named_call('--compact')
        self.assertEqual((code, displayed['checks'][0]['state']), (0, 'supported'))
        self.assertNotIn('inputs', displayed)

    def test_named_action_cannot_mix_json_or_weaken_owner_requirements(self):
        self.preset(); self.write_report()
        self.assertEqual(self.call(None, '--action', 'review')[0], 2)
        self.assertEqual(self.call(None, '--expected-head', self.head)[0], 2)
        valid = {**self.request, 'action_id': 'review'}
        self.assertEqual(self.call(valid)[0], 0)
        for change in ({'action_id': 'other'}, {'completeness': 'unknown'}, {'max_age_seconds': 3600},
                       {'checks': ['other']}, {'grounds': []}):
            with self.subTest(change=change):
                self.assertEqual(self.call({**valid, **change})[0], 2)

    def test_invalid_presets_fail_before_report_reads(self):
        valid = self.preset()
        invalid = [{**valid, 'command': ['do-not-execute']}, {**valid, 'checks': []},
                   {**valid, 'checks': ['unit', 'unit']}, {**valid, 'checks': ['other']},
                   {**valid, 'grounds': [{'realm': 'foreign', 'id': 'ground', 'revision': 1, 'digest': 'a' * 64}]},
                   {**valid, 'grounds': [{'id': 'not-exact'}]}, {**valid, 'max_age_seconds': -1}]
        for definition in invalid:
            with self.subTest(definition=definition):
                self.document['assessment_actions'] = [definition]
                self.control.write_text(json.dumps(self.document))
                with patch.object(adapter, '_report') as read:
                    self.assertEqual(self.named_call()[0], 2)
                    read.assert_not_called()
        self.document['assessment_actions'] = [valid, valid]
        self.control.write_text(json.dumps(self.document))
        self.assertEqual(self.named_call()[0], 2)

    def test_named_default_head_race_and_explicit_mismatch_are_rejected(self):
        self.preset(); self.write_report()
        with patch.object(adapter, '_head', side_effect=[{'status': 'available', 'commit': self.head},
                {'status': 'available', 'commit': 'a' * 40}]):
            code, result = self.named_call()
        self.assertEqual((code, result['state']), (1, 'indeterminate'))
        self.assertIn('git_changed_during_assessment', result['reasons'])
        code, result = self.named_call('--expected-head', 'a' * 40)
        self.assertEqual((code, result['state']), (1, 'indeterminate'))
        self.assertEqual(self.named_call('--expected-head', 'HEAD')[0], 2)

    def test_named_grounds_and_working_entries_are_required_once(self):
        reference = {'realm': self.app.initial_realm_id, 'id': 'context:test', 'revision': 1}
        raw = self.app._load(self.app.store.snapshot())[-1]['context:test']
        reference['digest'] = 'sha256:' + raw['digest']
        self.document['bindings'][0]['working_entries'] = [reference]
        self.preset(grounds=[reference]); self.write_report()
        code, result = self.named_call()
        self.assertEqual(code, 0)
        self.assertEqual(result['manifest']['forced_refs'], [reference])
        self.assertEqual(sum(row['id'] == 'context:test' for row in result['manifest']['used_refs']), 1)
        self.assertEqual(self.named_call('--budget', '1')[1]['state'], 'indeterminate')
        self.preset(grounds=[{**reference, 'digest': 'sha256:' + '0' * 64}])
        self.assertEqual(self.named_call()[0], 2)

    def test_report_failure_reasons_distinguish_repair_steps(self):
        _, absent, _ = self.call()
        self.assertEqual(absent['host_observation']['reports'][0]['reason'], 'missing_file')
        self.report.write_text('{invalid')
        _, malformed, _ = self.call()
        self.assertEqual(malformed['host_observation']['reports'][0]['reason'], 'invalid_json')
        self.write_report(workspace_id='workspace:other')
        _, foreign, _ = self.call()
        self.assertEqual(foreign['host_observation']['reports'][0]['reason'], 'wrong_workspace_or_check')
        self.write_report(observed_at='invalid')
        _, timestamp, _ = self.call()
        self.assertEqual(timestamp['host_observation']['reports'][0]['reason'], 'invalid_timestamp')

    def test_discovery_context_cannot_masquerade_as_action_sufficiency(self):
        self.write_report()
        discovery = self.app.context(['context:test'])
        with patch('ekk.application.service.RealmService.context', return_value=discovery):
            self.assertEqual(self.call()[0], 2)
        action = self.app.context(['context:test'], selection='action_requirements')
        action['manifest']['projection']['complete'] = False
        with patch('ekk.application.service.RealmService.context', return_value=action):
            self.assertEqual(self.call()[0], 2)


if __name__ == '__main__':
    unittest.main()
