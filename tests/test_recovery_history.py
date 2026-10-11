"""History verification scales with unique bytes without skipping old evidence."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.contained_store import ContainedGitStore
from ekk.adapters.git_store import GitStore
from ekk.adapters.host_identity import SCRUB_VARIABLES
from ekk.model import DirtyWorkingTree, RecoveryConflict


class RecoveryHistoryTests(unittest.TestCase):
    def test_recovery_reads_unique_history_bytes_and_current_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = GitStore(root/'realm', root/'runtime')
            files = {f'{n}.bin': str(n).encode()+b'x'*8192 for n in range(64)}
            base = store.initialize(files)['revision']
            for n in range(8):
                base = store.apply({f'change-{n}.txt': str(n).encode()}, base=base,
                    idempotency_key=str(n), principal='owner', policy_digest='a'*64)['revision']
            transferred = 0
            original = store._git
            def measured(*args, **kwargs):
                nonlocal transferred
                result = original(*args, **kwargs)
                if args[:2] == ('cat-file', '--batch'):
                    transferred += len(result.stdout)
                return result
            with patch.object(store, '_git', side_effect=measured):
                self.assertEqual([], store.recover())
            # Historical bytes plus the current projection and small journals;
            # rereading before+after for all9 commits exceeds this bound by6x.
            self.assertLess(transferred, 3*sum(map(len, files.values())))
            self.assertEqual(base, store.snapshot()['revision'])
            (store.path/'0.bin').write_bytes(b'external edit')
            with self.assertRaises(DirtyWorkingTree): store.recover()

    def test_deleted_contained_baseline_blob_is_still_read_and_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); repo = root/'repo'; realm = repo/'knowledge'
            realm.mkdir(parents=True)
            def git(*args):
                return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True).stdout
            git('init', '--quiet', '--initial-branch=main')
            git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@localhost')
            (realm/'historical.bin').write_bytes(b'deleted baseline evidence\x00\xff')
            (realm/'current.txt').write_bytes(b'current')
            git('add', '.'); git('commit', '--quiet', '-m', 'Baseline')
            base = git('rev-parse', 'HEAD').decode().strip()
            oid = git('rev-parse', base+':knowledge/historical.bin').decode().strip()
            store = ContainedGitStore(realm, repo, 'refs/heads/main', root/'runtime')
            receipt = store.apply({'historical.bin': None}, base=base,
                idempotency_key='delete', principal='owner', policy_digest='a'*64)
            self.assertEqual([], store.recover())
            object_file = repo/'.git/objects'/oid[:2]/oid[2:]
            original = object_file.read_bytes()
            before = {p.name: p.read_bytes() for p in (root/'runtime/journals').glob('*.json')}
            for corruption in ('missing', 'corrupt'):
                with self.subTest(corruption=corruption):
                    if corruption == 'missing': object_file.unlink()
                    else: object_file.write_bytes(b'corrupt loose object')
                    try:
                        # The missing object is historical-only, absent at head.
                        self.assertEqual({'current.txt': b'current'}, store.snapshot()['files'])
                        with self.assertRaises(RecoveryConflict): store.recover()
                        self.assertEqual(receipt['revision'], git('rev-parse', 'HEAD').decode().strip())
                        self.assertEqual(before, {p.name: p.read_bytes() for p in (root/'runtime/journals').glob('*.json')})
                    finally:
                        object_file.write_bytes(original)
            self.assertEqual([], store.recover())


class ScheduledAuditTests(unittest.TestCase):
    """Who runs the full audit that ordinary writes skip."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.realm = self.root/'realm'
        env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root/'data'), 'EKK_CONFIG_HOME': str(self.root/'config'),
                                      'EKK_CACHE_HOME': str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        for name in SCRUB_VARIABLES: os.environ.pop(name, None)
        from ekk.adapters.command_line import main, service
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(['init', '--root', str(self.realm), '--title', 'Example']))
        self.app = service(self.realm)
        self.scope = self.app.codec.load_yaml(self.app.store.snapshot()['files']['.ekk/realm.yaml'])['default_context']

    def call(self, entry, arguments, body=None):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), patch('sys.stdin', io.StringIO(json.dumps(body))):
            code = entry(arguments + (['--stdin'] if body is not None else []))
        return code, output.getvalue(), error.getvalue()

    def age_checkpoint(self, days):
        path = self.app.store.runtime_dir/'verified-operations.json'
        checkpoint = json.loads(path.read_text())
        checkpoint['audited_at'] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        path.write_text(json.dumps(checkpoint))

    def test_background_publisher_runs_a_due_audit_and_keeps_the_queue_when_it_fails(self):
        from ekk.adapters import activity_cli
        from ekk.adapters.command_line import main
        route = ['--root', str(self.realm), '--scope', self.scope]
        with patch('ekk.adapters.activity_cli.start_worker', return_value={'started': False}):
            code, output, _ = self.call(main, ['retain', *route, '--title', 'Result'], {'body': 'Local result.'})
        self.assertEqual(0, code, output)
        key = json.loads(output)['key']
        store = self.app.store
        drain = lambda *flags: self.call(lambda argv: activity_cli.main('queue', argv), ['drain', *flags, *route])
        state = lambda result: {row['key']: row['state'] for row in json.loads(result)['operations']}[key]
        orphan = store.operations_ref + 'a'*64
        store._git('update-ref', orphan, store.snapshot()['revision'])
        self.assertFalse(store.audit_due())
        self.age_checkpoint(8)
        self.assertTrue(store.audit_due())
        # Due and failing: one line in the worker log, every waiting request marked so that
        # the agent's status check shows it, nothing published, the checkpoint gone.
        code, output, error = drain('--background')
        self.assertEqual(0, code, error)
        self.assertEqual(('failed', 'recovery_required'), (json.loads(output)['store_audit']['state'], json.loads(output)['store_audit']['error']))
        self.assertEqual('needs_attention', state(output))
        row = next(row for row in json.loads(output)['operations'] if row['key'] == key)
        self.assertEqual('recovery_required', row['error']['code'])
        logged = [line for line in error.splitlines() if 'store_audit' in line]  # other lines are lock warnings under load
        self.assertEqual(1, len(logged))
        self.assertEqual('failed', json.loads(logged[0])['store_audit'])
        self.assertFalse((store.runtime_dir/'verified-operations.json').exists())
        # Once the store passes and the request is retried, the next drain publishes it.
        store._git('update-ref', '-d', orphan)
        self.call(lambda argv: activity_cli.main('queue', argv), ['retry', '--no-start', *route, '--key', key])
        code, output, error = drain('--background')
        self.assertEqual((0, ''), (code, error))
        self.assertEqual({'state': 'passed'}, json.loads(output)['store_audit'])
        self.assertEqual('read_back_and_discoverable', state(output))
        self.assertFalse(store.audit_due())
        # Not due: no audit. Due in the foreground: the caller is not made to wait for one.
        with patch.object(GitStore, 'recover', autospec=True, side_effect=GitStore.recover) as audit:
            self.assertNotIn('store_audit', json.loads(drain('--background')[1]))
            self.age_checkpoint(8)
            self.assertNotIn('store_audit', json.loads(drain()[1]))
            self.assertEqual(0, audit.call_count)
        self.assertTrue(store.audit_due())

    def test_installer_warm_audits_and_indexes_every_profile_store_with_the_active_release(self):
        import importlib.util
        import sys
        import yaml
        from ekk.adapters.history_index import HistoryIndex
        spec = importlib.util.spec_from_file_location('ekk_local_install', Path(__file__).resolve().parent.parent/'tools/local_install.py')
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        # A stand-in release: its interpreter is this one with the sources under test.
        release = self.root/'release'; (release/'venv/bin').mkdir(parents=True)
        python = release/'venv/bin/python'
        python.write_text('#!/bin/sh\n# drops the isolation flags so the tested sources are importable\nshift 2\n'
                          f'PYTHONPATH={shlex.quote(os.pathsep.join(sys.path))} exec {shlex.quote(sys.executable)} -B "$@"\n')
        python.chmod(0o755)
        (release/'original-packs').mkdir()
        profiles = self.root/'config/profiles'; profiles.mkdir(parents=True)
        realm_id = self.app.initial_realm_id
        (profiles/'personal.yaml').write_text(yaml.safe_dump({'schema': 'ekk.profile/0.1', 'uid': os.getuid(), 'realms': {
            'main': {'path': str(self.realm), 'id': realm_id}, 'gone': {'path': str(self.root/'absent'), 'id': 'realm:gone'}}}))
        (profiles/'second.yaml').write_text(yaml.safe_dump({'schema': 'ekk.profile/0.1', 'uid': os.getuid(), 'realms': {
            'same': {'path': str(self.realm), 'id': realm_id}}}))
        self.age_checkpoint(8)
        self.assertTrue(self.app.store.audit_due())
        output = io.StringIO()
        with patch.object(installer, 'current', return_value=release), contextlib.redirect_stdout(output), \
                self.assertRaises(SystemExit) as stopped:
            installer.main(['warm'])
        output = output.getvalue()
        self.assertEqual(1, stopped.exception.code)
        rows = {row['store']: row for row in map(json.loads, output.splitlines())}
        # One line per store; the missing store does not stop the others.
        self.assertEqual({str(self.realm), str(self.root/'absent')}, set(rows))
        self.assertEqual(2, len(output.splitlines()))
        warmed = rows[str(self.realm)]
        self.assertEqual(('ok', 'ok', 1, 0), (warmed['audit'], warmed['index'], warmed['commits'], warmed['unloadable_commits']))
        self.assertIn('audit_s', warmed); self.assertIn('index_s', warmed)
        self.assertNotEqual('ok', rows[str(self.root/'absent')]['audit'])
        self.assertFalse((self.root/'absent').exists())
        self.assertFalse(self.app.store.audit_due())
        # The index of the only commit is now stored for later processes.
        head = self.app.store.snapshot()['revision']
        from ekk.adapters.local_profile import cache_home
        import hashlib
        index = HistoryIndex(cache_home()/'history'/hashlib.sha256(realm_id.encode()).hexdigest())
        self.assertIsNotNone(index.delta(head, None, False))


if __name__ == '__main__': unittest.main()
