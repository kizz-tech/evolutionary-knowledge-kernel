"""History verification scales with unique bytes without skipping old evidence."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.contained_store import ContainedGitStore
from ekk.adapters.git_store import GitStore
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


if __name__ == '__main__': unittest.main()
