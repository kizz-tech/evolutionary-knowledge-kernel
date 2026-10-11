"""One host identity: which host, profile, session and journal caller a process or hook payload names."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters import host_identity
from ekk.adapters.host_identity import SCRUB_VARIABLES, hook_identity, resolve, transcript_home


class HostIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()  # the registry is never read through a symlinked path
        self.config = self.root / 'config'; self.config.mkdir(mode=0o700)
        env = patch.dict(os.environ, {'EKK_CONFIG_HOME': str(self.config), 'EKK_DATA_HOME': str(self.root / 'data')})
        env.start(); self.addCleanup(env.stop)
        (self.root / 'fleet.json').write_text(json.dumps({'schema_version': 'lifeos.codex-profile-fleet/1',
                                                          'profiles': {'main': {'home': str(self.root / '.codex')},
                                                                       'team': {'home': str(self.root / '.codex-team')}}}))

    def register(self, **extra):
        path = self.config / 'callers.yaml'
        path.write_text(json.dumps({'schema': 'ekk.callers/0.1', 'codex_profile_fleet': str(self.root / 'fleet.json'),
                                    'environments': {'claude-code': {'CLAUDECODE': '1'}}, **extra}))
        path.chmod(0o600)

    def test_the_hook_reads_the_payload_first_and_never_the_registry(self):
        codex, claude = str(self.root / '.codex-team/sessions/r.jsonl'), str(self.root / '.claude/projects/p/s.jsonl')
        both = {'CODEX_HOME': str(self.root / '.codex-team'), 'CLAUDECODE': '1', 'CODEX_THREAD_ID': 'thread', 'CLAUDE_CODE_SESSION_ID': 'claude'}
        cases = [({'transcript_path': claude}, both, ('claude-code', None, 'claude')),
                 ({'transcript_path': codex}, {'CLAUDECODE': '1'}, ('codex', None, None)),
                 ({'turn_id': 't1'}, {'CLAUDECODE': '1', 'CODEX_THREAD_ID': 'thread'}, ('codex', None, 'thread')),
                 ({}, both, ('codex', str(self.root / '.codex-team'), 'thread')),  # a Codex process started from Claude Code
                 ({}, {'CLAUDECODE': '1'}, ('claude-code', None, None)),
                 ({'session_id': 'payload'}, {'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'variable'}, ('claude-code', None, 'payload')),
                 ({}, {'CLAUDECODE': '0', 'CLAUDE_CODE_SESSION_ID': 'variable'}, ('unknown', None, None))]
        for payload, environment, expected in cases:
            self.assertEqual(expected, hook_identity(payload, environment), (payload, environment))
        self.register(sessions={'claude-code': ['OTHER']})  # the hook path never reads it
        self.assertEqual(('claude-code', None, 'claude'), hook_identity({}, {'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'claude'}))
        self.assertEqual((str(self.root / '.codex-team'), None), (transcript_home(codex), transcript_home(claude)))

    def test_the_profile_is_the_fleet_key_never_a_directory_name(self):
        self.register()
        self.assertEqual(('codex', 'team', 'thread', 'team'),
                         resolve({'CODEX_HOME': str(self.root / '.codex-team'), 'CODEX_THREAD_ID': 'thread', 'CLAUDECODE': '1'}))
        self.assertEqual(('codex', 'main', None, 'main'), resolve({'CODEX_HOME': str(self.root / '.codex')}))
        self.assertEqual(('codex', None, None, None), resolve({'CODEX_HOME': str(self.root / '.codex-unregistered')}))
        self.assertEqual(('claude-code', None, 's', 'claude-code'), resolve({'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 's'}))
        (self.config / 'callers.yaml').unlink()
        # Without a registry the built-in marker names the host, and nothing is a registered caller.
        self.assertEqual(('claude-code', None, 's', None), resolve({'CLAUDECODE': '1', 'CLAUDE_SESSION_ID': 's'}))
        self.assertEqual(('codex', None, None, None), resolve({'CODEX_HOME': str(self.root / '.codex')}))
        self.assertEqual(('unknown', None, None, None), resolve({}))

    def test_registered_environments_name_a_host_and_several_stay_unknown(self):
        self.register(environments={'claude-code': {'CLAUDECODE': '1'}, 'other-agent': {'OTHER_AGENT': '1'}})
        self.assertEqual(('other-agent', None, None, 'other-agent'), resolve({'OTHER_AGENT': '1'}))
        self.assertEqual(('unknown', None, None, None), resolve({'OTHER_AGENT': '1', 'CLAUDECODE': '1'}))
        self.register(environments={'other-agent': {'OTHER_AGENT': '1'}})
        self.assertEqual(('claude-code', None, None, None), resolve({'CLAUDECODE': '1'}))  # built-in, not a registered caller

    def test_session_variables_are_declared_bounded_and_overridable(self):
        self.register()
        self.assertEqual('a' * 256, resolve({'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'a' * 256}).session)
        self.assertIsNone(resolve({'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'a' * 257}).session)  # absent, never cut
        self.assertEqual('new', resolve({'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'new', 'CLAUDE_SESSION_ID': 'old'}).session)
        never = {'CLAUDECODE': '1', 'CLAUDE_CODE_HOST_SESSION_ID': 'local_x', 'CLAUDE_CODE_CHILD_SESSION': '1'}
        self.assertIsNone(resolve(never).session)
        self.register(sessions={'claude-code': ['RENAMED_SESSION']})
        self.assertEqual('r', resolve({'CLAUDECODE': '1', 'RENAMED_SESSION': 'r', 'CLAUDE_CODE_SESSION_ID': 's'}).session)
        self.assertEqual('t', resolve({'CODEX_HOME': str(self.root / '.codex'), 'CODEX_THREAD_ID': 't'}).session)  # other hosts keep theirs
        for malformed in ('RENAMED_SESSION', ['bad name'], [], ['CLAUDE_CODE_HOST_SESSION_ID'], [1]):
            self.register(sessions={'claude-code': malformed})
            identity = resolve({'CLAUDECODE': '1', 'RENAMED_SESSION': 'r', 'CLAUDE_CODE_SESSION_ID': 's', 'CLAUDE_CODE_HOST_SESSION_ID': 'h'})
            self.assertEqual(('claude-code', None, 'claude-code'), (identity.host, identity.session, identity.caller), malformed)
            self.assertEqual('t', resolve({'CODEX_HOME': str(self.root / '.codex'), 'CODEX_THREAD_ID': 't'}).session)
        self.register(sessions=['CLAUDE_CODE_SESSION_ID'])  # not a map: no host has a session
        self.assertEqual((None, None), (resolve({'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 's'}).session,
                                        resolve({'CODEX_HOME': str(self.root / '.codex'), 'CODEX_THREAD_ID': 't'}).session))

    def test_an_unreadable_registry_never_fails_the_caller_but_fails_strict_resolution(self):
        for document in ('null\n', json.dumps({'schema': 'ekk.callers/0.1', 'environments': {'claude-code': {}}})):
            (self.config / 'callers.yaml').write_text(document); (self.config / 'callers.yaml').chmod(0o600)
            self.assertEqual(('claude-code', None, 's', None), resolve({'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 's'}))
            with self.assertRaises(ValueError):
                resolve({'CLAUDECODE': '1'}, strict=True)
        self.register(); (self.root / 'fleet.json').write_text(json.dumps({'schema_version': 'other'}))
        self.assertEqual(('codex', None, None, None), resolve({'CODEX_HOME': str(self.root / '.codex')}))
        with self.assertRaises(ValueError):
            resolve({'CODEX_HOME': str(self.root / '.codex')}, strict=True)
        self.assertEqual(None, host_identity.profile_lookup()(str(self.root / '.codex')))

    def test_scrubbed_variables_cover_markers_sessions_and_the_unread_ones(self):
        self.assertEqual(('CODEX_HOME', 'CLAUDECODE', 'CODEX_THREAD_ID', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_SESSION_ID',
                          'CLAUDE_CODE_HOST_SESSION_ID', 'CLAUDE_CODE_CHILD_SESSION'), SCRUB_VARIABLES)


if __name__ == '__main__':
    unittest.main()
