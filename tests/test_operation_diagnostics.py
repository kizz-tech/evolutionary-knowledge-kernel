"""Host attribution and owning publication/transport observation boundaries."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.command_line import dispatch, parser, service
from ekk.adapters.host_identity import SCRUB_VARIABLES
from ekk.adapters import operation_journal
from ekk.adapters.operation_diagnostics import journal, observed_call, trusted_caller
from ekk.adapters.operation_journal import OperationJournal
from ekk.model import Conflict

# The legacy journal reader of 0.10.0 (operation_journal.py at c1b132a) and of the 0.8.0 gateway counts a row with
# any other key or error code as damage and then refuses every later begin. Frozen literals, never imported.
JOURNAL_0_10_0 = {
    'ERROR_CODES': frozenset({'access_denied', 'recovery_required', 'stale_snapshot', 'source_unavailable',
                              'unsupported_capability', 'unresolved_binding', 'invalid_format', 'cancelled',
                              'internal_error', 'dirty_working_tree', 'idempotency_conflict', 'lock_busy'}),
    '_RECORD_KEYS': frozenset({'schema', 'attempt_id', 'logical_id', 'parent_attempt_id', 'operation', 'realm_digest',
                               'principal_digest', 'keyed', 'caller_profile', 'caller_provenance', 'started_at', 'finished_at',
                               'duration_ms', 'result', 'replayed', 'mutated', 'failure_stage', 'attempted_base',
                               'current_snapshot', 'final_snapshot', 'clock_regressed'}),
    '_OPTIONAL_RECORD_KEYS': frozenset({'runtime_version', 'error_code'}),
}


class DiagnosticIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root/'data'),
            'EKK_CONFIG_HOME': str(self.root/'config'), 'EKK_CACHE_HOME': str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        # The suite itself runs inside coding agents; attribution must not depend on that.
        for name in SCRUB_VARIABLES: os.environ.pop(name, None)
        self.config = self.root/'config'; self.config.mkdir(mode=0o700)

    def call(self, op, request=None, *, render=None, **options):
        args = [op, '--root', str(self.root/'realm')]
        if op != 'init': args += ['--scope', 'scope']
        return dispatch(parser().parse_args(args), request or {}, render=render)

    def rows(self):
        path = self.root/'data/operations/operations.jsonl'
        return [row for row in map(json.loads, path.read_text().splitlines()) if 'attempt_id' in row]

    def test_four_registered_caller_environments_and_unknown_are_distinct(self):
        names = ['alpha', 'beta', 'gamma', 'delta']
        fleet = {'schema_version':'lifeos.codex-profile-fleet/1',
                 'profiles': {name:{'home':str(self.root/name)} for name in names}}
        (self.root/'fleet.json').write_text(json.dumps(fleet))
        config = {'schema':'ekk.callers/0.1', 'codex_profile_fleet': str(self.root/'fleet.json'),
                  'adapters':['private-gateway']}
        path = self.config/'callers.yaml'; path.write_text(json.dumps(config)); path.chmod(0o600)
        for name in names:
            with patch.dict(os.environ, {'CODEX_HOME':str(self.root/name), 'EKK_PROFILE':'unrelated-role'}):
                self.assertEqual(name, trusted_caller().profile)
                observed_call('context', lambda:{'ok':True})
        with patch.dict(os.environ, {'CODEX_HOME':str(self.root/'unregistered')}):
            self.assertIsNone(trusted_caller())
            observed_call('context', lambda:{'ok':True})
        self.assertEqual(set(names+['unknown']), {row['caller_profile'] for row in self.rows()})
        self.assertEqual('private-gateway', trusted_caller('private-gateway').profile)
        self.assertIsNone(trusted_caller('alpha'))
        self.assertNotIn(str(self.root), json.dumps(self.rows()))

    def test_registered_environment_markers_attribute_other_coding_agents(self):
        fleet = {'schema_version':'lifeos.codex-profile-fleet/1', 'profiles': {'alpha':{'home':str(self.root/'alpha')}}}
        (self.root/'fleet.json').write_text(json.dumps(fleet))
        config = {'schema':'ekk.callers/0.1', 'codex_profile_fleet': str(self.root/'fleet.json'),
                  'adapters':['private-gateway'],
                  'environments':{'claude-code':{'CLAUDECODE':'1'}, 'other-agent':{'OTHER_AGENT':'1'}}}
        path = self.config/'callers.yaml'; path.write_text(json.dumps(config)); path.chmod(0o600)
        with patch.dict(os.environ, {'CLAUDECODE':'1'}):
            self.assertEqual('claude-code', trusted_caller().profile)
            observed_call('context', lambda:{'ok':True})
            # A Codex process keeps the Codex rule, registered or not.
            with patch.dict(os.environ, {'CODEX_HOME':str(self.root/'alpha')}):
                self.assertEqual('alpha', trusted_caller().profile)
            with patch.dict(os.environ, {'CODEX_HOME':str(self.root/'unregistered')}):
                self.assertIsNone(trusted_caller())
            with patch.dict(os.environ, {'OTHER_AGENT':'1'}):
                self.assertIsNone(trusted_caller())
        with patch.dict(os.environ, {'CLAUDECODE':'0'}):
            self.assertIsNone(trusted_caller())
        self.assertIsNone(trusted_caller('claude-code'))
        self.assertEqual([('claude-code', 'host_registry')],
                         [(row['caller_profile'], row['caller_provenance']) for row in self.rows()])
        for bad in ({'claude-code':{}}, {'claude-code':{'CLAUDE CODE':'1'}}, {'claude-code':{'CLAUDECODE':1}},
                    {'unknown':{'CLAUDECODE':'1'}}, ['claude-code']):
            path.write_text(json.dumps({**config, 'environments':bad}))
            with self.assertRaises(ValueError): trusted_caller()

    def test_a_malformed_sessions_override_never_drops_a_journal_row(self):
        fleet = {'schema_version':'lifeos.codex-profile-fleet/1', 'profiles': {'alpha':{'home':str(self.root/'alpha')}}}
        (self.root/'fleet.json').write_text(json.dumps(fleet))
        path = self.config/'callers.yaml'
        for sessions in ('CODEX_THREAD_ID', {'codex':'CODEX_THREAD_ID'}, {'codex':['bad name']}, {'claude-code':[None]}):
            path.write_text(json.dumps({'schema':'ekk.callers/0.1', 'codex_profile_fleet': str(self.root/'fleet.json'),
                                        'environments':{'claude-code':{'CLAUDECODE':'1'}}, 'sessions':sessions})); path.chmod(0o600)
            with patch.dict(os.environ, {'CODEX_HOME':str(self.root/'alpha'), 'CODEX_THREAD_ID':'thread'}):
                self.assertNotIn('warnings', observed_call('context', lambda:{'ok':True}))
            with patch.dict(os.environ, {'CLAUDECODE':'1', 'CLAUDE_CODE_SESSION_ID':'claude'}):
                self.assertNotIn('warnings', observed_call('context', lambda:{'ok':True}))
        self.assertEqual(['alpha', 'claude-code'] * 4, [row['caller_profile'] for row in self.rows()])

    def test_rows_this_runtime_writes_pass_the_0_10_0_journal_reader(self):
        fleet = {'schema_version':'lifeos.codex-profile-fleet/1', 'profiles': {'alpha':{'home':str(self.root/'alpha')}}}
        (self.root/'fleet.json').write_text(json.dumps(fleet))
        path = self.config/'callers.yaml'
        path.write_text(json.dumps({'schema':'ekk.callers/0.1', 'codex_profile_fleet': str(self.root/'fleet.json'),
                                    'adapters':['private-gateway'], 'environments':{'claude-code':{'CLAUDECODE':'1'}},
                                    'sessions':{'claude-code':['CLAUDE_CODE_SESSION_ID']}})); path.chmod(0o600)
        with patch.dict(os.environ, {'CODEX_HOME':str(self.root/'alpha'), 'CLAUDECODE':'1', 'CODEX_THREAD_ID':'thread'}):
            self.call('init', {'context_id':'scope'})
        with patch.dict(os.environ, {'CLAUDECODE':'1', 'CLAUDE_CODE_SESSION_ID':'claude'}):
            with self.assertRaises(ValueError): self.call('capture', {'body':'', 'title':''})
            self.call('context')
        observed_call('context', lambda:{'ok':True}, caller=trusted_caller('private-gateway'))
        self.call('decide', {'title':'Use exact IDs', 'body':'Exact IDs only.', 'stated_by':'agent'})
        rows = self.rows()
        self.assertEqual({'alpha', 'claude-code', 'private-gateway', 'unknown'}, {row['caller_profile'] for row in rows})
        self.assertIn('invalid_format', {row['error_code'] for row in rows})
        with patch.multiple(operation_journal, **JOURNAL_0_10_0):
            for row in rows:
                OperationJournal._validate_record(row)
            self.assertIsNotNone(journal().begin('context', principal='local:uid:0'))

    def test_a_cli_request_error_keeps_the_0_10_0_journal_readable(self):
        import contextlib, io
        from ekk.adapters.command_line import main
        from ekk.adapters.operation_diagnostics import legacy_failure
        self.call('init', {'context_id':'scope'})
        error = io.StringIO()
        with contextlib.redirect_stderr(error), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(2, main(['fetch','--root',str(self.root/'realm'),'--scope','scope','--id','nothing-has-this-id']))
        self.assertEqual(('invalid_request', 'unknown_id'), tuple(json.loads(error.getvalue())[k] for k in ('error', 'refusal')))  # what the agent sees
        [row] = [row for row in self.rows() if row['result'] == 'error']
        self.assertEqual(('invalid_format', 'request'), (row['error_code'], row['failure_stage']))  # what older readers accept
        with patch.multiple(operation_journal, **JOURNAL_0_10_0):
            report = journal().report()
            self.assertEqual((True, 0), (report['coverage']['metadata_integrity_verified'], report['coverage']['damaged_records']))
            self.assertNotIn('damaged_metadata', report['coverage']['limitations'])
            self.assertIsNotNone(journal().begin('context', principal='local:uid:0'))
        # The retention-pending path forwards a code it did not choose: the same mapping applies.
        self.assertEqual([('invalid_format', 'request'), ('source_unavailable', 'response')],
                         [legacy_failure(code, 'response') for code in ('invalid_request', 'source_unavailable')])

    def test_bad_caller_configuration_warns_without_preventing_domain_work(self):
        path = self.config/'callers.yaml'; path.write_text('null\n'); path.chmod(0o600)
        calls = []
        result = observed_call('context', lambda: calls.append(True) or {'result':'known'})
        self.assertEqual([True], calls)
        self.assertEqual('known', result['result'])
        self.assertTrue(result['warnings'])
        path.write_text(json.dumps({'schema':'ekk.callers/0.1','adapters':'secret-profile'}))
        with self.assertRaises(ValueError): trusted_caller('secret')

    def test_init_apply_accept_and_replay_have_owning_mutation_evidence(self):
        self.call('init', {'context_id':'scope'})
        app = service(self.root/'realm')
        context_raw = app.store.snapshot()['files']['contexts/scope.md']
        basis = {'id':'scope','revision':1,'digest':'sha256:'+__import__('hashlib').sha256(context_raw).hexdigest()}
        metadata = app._meta('decision', 'Check bytes', ['scope'], basis=[basis], commitment={'expectation':'Exact bytes'})
        raw = app.codec.encode(metadata)
        proposal = app.propose({'records/decision.md': raw})
        request = {'proposal':proposal, 'idempotency_key':'apply'}
        receipt = self.call('apply', request)
        self.assertEqual(receipt, self.call('apply', request))
        ref = {'realm':app.initial_realm_id, 'id':metadata['id'], 'revision':1,
               'digest':'sha256:'+__import__('hashlib').sha256(raw).hexdigest()}
        accepted = self.call('accept', {'references':[ref], 'expected_snapshot':receipt['revision'],
                                      'idempotency_key':'accept'})
        self.assertEqual('published', accepted['state'])
        rows = self.rows()
        self.assertEqual([True,True,False,True], [row['mutated'] for row in rows])
        self.assertEqual([False,False,True,False], [row['replayed'] for row in rows])

    def test_request_route_and_response_failures_keep_observed_stage(self):
        self.call('init', {'context_id':'scope'})
        capture = parser().parse_args(['capture','--root',str(self.root/'realm'),'--scope','scope','--wait'])
        with self.assertRaises(ValueError): dispatch(capture, {'body':'secret request text','title':''})  # rejected before the store
        args = parser().parse_args(['context','--profile','absent','--realm','absent'])
        with self.assertRaises(ValueError): dispatch(args, {})
        app = service(self.root/'realm')
        proposal = app.capture(b'original',title='Source',scope=['scope'])
        def lost(_): raise OSError('synthetic response unavailable')
        with self.assertRaises(OSError):
            self.call('apply', {'proposal':proposal,'idempotency_key':'published'}, render=lost)
        failures = [row for row in self.rows() if row['result']=='error']
        self.assertEqual(['request','routing','response'], [row['failure_stage'] for row in failures])
        self.assertTrue(failures[-1]['mutated'])
        self.assertNotIn('secret request text', json.dumps(self.rows()))
        self.assertNotIn('synthetic response unavailable', json.dumps(self.rows()))

    def test_diagnostic_completion_failure_never_repeats_domain_callback(self):
        calls=[]
        with patch.object(OperationJournal,'finish',side_effect=OSError('metadata offline')):
            result=observed_call('apply',lambda:calls.append(True) or {'state':'published','revision':'a'*40})
        self.assertEqual([True], calls)
        self.assertEqual('published', result['state'])
        self.assertTrue(result['warnings'])

    def test_recovery_of_other_key_is_separate_from_failed_or_successful_caller(self):
        self.call('init', {'context_id':'scope'})
        store = service(self.root/'realm').store
        for stage, succeeds in [('prepared', False), ('published', True)]:
            before = store.snapshot()['revision']
            key_a, key_b = 'a-'+stage, 'b-'+stage
            def crash(current):
                if current == stage: raise OSError('interrupted publication')
            with patch.object(store, '_checkpoint', side_effect=crash):
                with self.assertRaises(OSError):
                    observed_call('apply', lambda:store.apply({key_a+'.txt':b'a'}, base=before,
                        idempotency_key=key_a, principal='tester', policy_digest='a'*64), key=key_a)
            base_b = store.snapshot()['revision'] if succeeds else before
            prior = {row['attempt_id'] for row in self.rows()}
            def apply_b():
                return store.apply({key_b+'.txt':b'b'}, base=base_b,
                    idempotency_key=key_b, principal='tester', policy_digest='a'*64)
            if succeeds:
                receipt = observed_call('apply', apply_b, key=key_b)
            else:
                with self.assertRaises(Conflict): observed_call('apply', apply_b, key=key_b)
            new = [row for row in self.rows() if row['attempt_id'] not in prior]
            self.assertEqual(2, len(new))
            caller = next(row for row in new if row['operation'] == 'apply')
            recovery = next(row for row in new if row['operation'] == 'recover')
            self.assertEqual('apply', caller['operation'])
            self.assertEqual('recover', recovery['operation'])
            self.assertEqual(succeeds, caller['mutated'])
            self.assertFalse(caller['replayed'])
            if not succeeds: self.assertIsNone(caller['final_snapshot'])
            self.assertEqual(not succeeds, recovery['mutated'])
            self.assertEqual(succeeds, recovery['replayed'])

    def test_same_key_recovery_preserves_owning_publication(self):
        self.call('init', {'context_id':'scope'})
        store = service(self.root/'realm').store
        base = store.snapshot()['revision']
        def write():
            return store.apply({'own.txt':b'a'}, base=base, idempotency_key='same',
                principal='tester', policy_digest='a'*64)
        def crash(stage):
            if stage == 'prepared': raise OSError('interrupted')
        with patch.object(store, '_checkpoint', side_effect=crash):
            with self.assertRaises(OSError): observed_call('apply', write, key='same')
        observed_call('apply', write, key='same')
        row = self.rows()[-1]
        self.assertTrue(row['mutated'])
        self.assertFalse(row['replayed'])
        self.assertNotIn('recover', [item['operation'] for item in self.rows()])

    def test_early_branches_do_not_mislabel_route_and_store_errors_as_request(self):
        self.call('init', {'context_id':'scope'})
        with self.assertRaises(Conflict): self.call('init', {'context_id':'scope'})
        for argv in [
            ['enter','--personal','--profile','absent','--cwd',str(self.root/'unbound')],
            ['init','--workspace','--realm','absent','--scope','scope','--profile','absent'],
            ['backup','--profile','absent','--realm','absent','--destination',str(self.root/'backup')],
            ['restore','--profile','absent','--realm','absent','--destination',str(self.root/'copy')],
        ]:
            with self.assertRaises((ValueError, PermissionError)):
                dispatch(parser().parse_args(argv), {})
        failures = [row for row in self.rows() if row['result'] in {'error','conflict'}]
        self.assertEqual(['store','routing','routing','routing','routing'],
                         [row['failure_stage'] for row in failures])


if __name__=='__main__': unittest.main()
