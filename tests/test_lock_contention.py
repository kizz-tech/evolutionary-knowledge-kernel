"""Real process contention must preserve exact requests and publication evidence."""
from contextlib import contextmanager, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from ekk.adapters.command_line import main, service
from ekk.adapters.contained_store import ContainedGitStore
from ekk.adapters.file_lock import LockBusy
from ekk.adapters.operation_diagnostics import observed_call
from ekk.adapters.retention import retain_once
from ekk.model import Conflict


@contextmanager
def held_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    script = """import fcntl,sys
with open(sys.argv[1], 'a+b') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    print('ready', flush=True)
    sys.stdin.buffer.read(1)
"""
    child = subprocess.Popen([sys.executable, '-c', script, str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if not select.select([child.stdout], [], [], 5)[0]:
            raise AssertionError('Disposable lock holder did not start')
        if child.stdout.readline() != b'ready\n':
            raise AssertionError('Disposable lock holder failed')
        yield
    finally:
        try:
            child.communicate(b'x', timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()


class LockContentionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root/'data'),
            'EKK_CONFIG_HOME': str(self.root/'config'), 'EKK_CACHE_HOME': str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        limits = patch.multiple('ekk.adapters.file_lock', LOCK_WAIT_SECONDS=0.1,
                                DIAGNOSTIC_LOCK_WAIT_SECONDS=0.05)
        limits.start(); self.addCleanup(limits.stop)
        self.app = service(self.root/'realm')
        self.app.init('Test', realm_id=self.app.initial_realm_id, context_id='scope')
        self.writer = self.root/'realm/.git/ekk-writer.lock'

    def retain(self):
        return retain_once(self.app, [{'data': b'original\r\n\x00\xff', 'filename': 'source.bin'}],
            title='Result', body='Verified local result.', scopes=['scope'], key='same-request')

    def request_path(self):
        identity = {'realm_id': self.app.initial_realm_id, 'principal': self.app.principal,
                    'key': 'same-request'}
        name = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return self.root/'data/capture-requests'/(name+'.json')

    def test_writer_busy_preserves_prepared_request_and_same_key_replays(self):
        before = self.app.store.snapshot()
        refs = self.app.store._git('for-each-ref').stdout
        with held_lock(self.writer):
            inode = self.writer.stat().st_ino
            for attempt in range(2):
                started = time.monotonic()
                with self.assertRaises(LockBusy) as caught:
                    self.retain()
                self.assertLess(time.monotonic()-started, 5)
                self.assertEqual('writer', caught.exception.lock_kind)
                self.assertNotIsInstance(caught.exception, Conflict)
                row = self.request_path().read_bytes()
                if attempt == 0: frozen = row
                self.assertEqual(frozen, row)
            self.assertEqual(before, self.app.store.snapshot())
            self.assertEqual(refs, self.app.store._git('for-each-ref').stdout)
            self.assertEqual(inode, self.writer.stat().st_ino)
        receipt = self.retain()
        self.assertEqual('read_back_and_discoverable', receipt['retention']['state'])
        self.assertEqual(receipt, self.retain())
        self.assertEqual(json.loads(frozen)['proposal']['changes'],
                         json.loads(self.request_path().read_text())['proposal']['changes'])
        self.assertEqual(3, self.app.doctor()['records'])
        rows = [json.loads(line) for line in (self.root/'data/operations/operations.jsonl').read_text().splitlines()]
        busy = [row for row in rows if row.get('error_code') == 'lock_busy']
        self.assertEqual(2, len(busy))
        self.assertTrue(all(not row['mutated'] for row in busy))

    def test_request_lock_busy_preserves_confirmed_request_and_receipt(self):
        receipt = self.retain()
        path = self.request_path(); frozen = path.read_bytes()
        lock = path.with_suffix('.lock')
        with held_lock(lock), patch.object(self.app, 'retain') as build:
            inode = lock.stat().st_ino
            started = time.monotonic()
            with self.assertRaises(LockBusy) as caught:
                self.retain()
            self.assertLess(time.monotonic()-started, 5)
            self.assertEqual('retention_request', caught.exception.lock_kind)
            build.assert_not_called()
            self.assertEqual(frozen, path.read_bytes())
            self.assertEqual(inode, lock.stat().st_ino)
            self.assertEqual(receipt['revision'], self.app.store.snapshot()['revision'])
        self.assertEqual(receipt, self.retain())

    def test_diagnostic_contention_warns_and_publishes_once(self):
        lock = self.root/'data/operations/.lock'
        observed_call('context', lambda: {'ok': True})
        before = (lock.parent/'operations.jsonl').read_bytes()
        with held_lock(lock):
            started = time.monotonic()
            receipt = self.retain()
            self.assertLess(time.monotonic()-started, 5)
            self.assertEqual('read_back_and_discoverable', receipt['retention']['state'])
            self.assertTrue(receipt['warnings'])
            self.assertEqual(before, (lock.parent/'operations.jsonl').read_bytes())
        self.assertEqual(receipt['revision'], self.retain()['revision'])
        self.assertEqual(3, self.app.doctor()['records'])

    def test_cli_returns_structured_retryable_busy_with_bounded_wait(self):
        request = self.root/'request.json'
        request.write_text(json.dumps({'operation': 'retain', 'request_id': 'same-request',
            'title': 'Result', 'body': 'Local result.', 'scopes': ['scope']}))
        error = io.StringIO()
        observed_call('context', lambda: {'ok': True})
        with held_lock(self.writer), held_lock(self.root/'data/operations/.lock'), redirect_stderr(error):
            code = main(['retain', '--wait', '--root', str(self.root/'realm'), '--json', str(request)])
        result = json.loads(error.getvalue())
        self.assertEqual(2, code)
        self.assertEqual('error', result['status'])
        self.assertEqual('lock_busy', result['data']['error'])
        self.assertTrue(result['data']['retryable'])
        self.assertTrue(result['data']['warnings'])
        self.assertEqual('writer', result['data']['lock_kind'])
        self.assertGreaterEqual(result['data']['waited_ms'], 90)
        self.assertLess(result['data']['waited_ms'], 2000)

    def test_contained_writer_busy_preserves_outer_code_and_retries(self):
        repo = self.root/'project'; realm = repo/'knowledge'; realm.mkdir(parents=True)
        def git(*args):
            return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True).stdout
        git('init', '--quiet', '--initial-branch=main')
        git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@localhost')
        (repo/'code.py').write_bytes(b'original code\n'); (realm/'note.md').write_bytes(b'one')
        git('add', '.'); git('commit', '--quiet', '-m', 'Reviewed baseline')
        base = git('rev-parse', 'HEAD').decode().strip()
        store = ContainedGitStore(realm, repo, 'refs/heads/main', self.root/'contained-runtime')
        kwargs = {'base': base, 'idempotency_key': 'change', 'principal': 'owner', 'policy_digest': 'a'*64}
        lock = repo/'.git/ekk-writer.lock'
        with held_lock(lock):
            inode = lock.stat().st_ino; refs = git('for-each-ref')
            started = time.monotonic()
            with self.assertRaises(LockBusy): store.apply({'note.md': b'two'}, **kwargs)
            self.assertLess(time.monotonic()-started, 5)
            self.assertEqual(refs, git('for-each-ref'))
            self.assertEqual(inode, lock.stat().st_ino)
            self.assertEqual(b'one', (realm/'note.md').read_bytes())
            self.assertEqual(b'original code\n', (repo/'code.py').read_bytes())
        receipt = store.apply({'note.md': b'two'}, **kwargs)
        self.assertEqual(receipt, store.apply({'note.md': b'two'}, **kwargs))
        self.assertEqual(b'original code\n', (repo/'code.py').read_bytes())


if __name__ == '__main__': unittest.main()
