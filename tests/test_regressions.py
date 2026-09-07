import threading
import time
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from ekk.kernel import Kernel, KernelError

JAN = '2026-01-01T00:00:00Z'
FEB = '2026-02-01T00:00:00Z'
MAR = '2026-03-01T00:00:00Z'
APR = '2026-04-01T00:00:00Z'


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.k = Kernel(self.base / 'kernel')
        self.k.init()
        self.source_file = self.base / 'source.txt'
        self.source_file.write_text('Human source')
        self.source = self.k.observe(self.source_file, 'Source', ['a'], 'human')

    def commitment(self, id='commitment', **extra):
        metadata = dict(id=id, title=id, kind='commitment', scopes=['a'], author='human',
                        sources=[self.source['id']], commitment={key: 'Explicit ' + key for key in
                        ('authority', 'rationale', 'effect', 'expectation', 'verification', 'revisit', 'rollback')})
        metadata.update(extra)
        return self.k.add(metadata, 'Original body\n')

    def test_body_mutation_detected(self):
        self.commitment()
        path = self.k.root / self.k.get('commitment')['path']
        path.write_text(path.read_text().replace('Original body', 'Altered body'))
        with self.assertRaises(KernelError):
            self.k.check()

    def test_valid_metadata_mutation_detected(self):
        self.commitment()
        path = self.k.root / self.k.get('commitment')['path']
        path.write_text(path.read_text().replace('author: human', 'author: impostor'))
        with self.assertRaises(KernelError):
            self.k.check()

    def test_reference_fingerprint_requires_lowercase_hex(self):
        for fingerprint in ('Z' * 64, 'A' * 64, '0' * 63):
            with self.subTest(fingerprint=fingerprint), self.assertRaises(KernelError):
                self.k.reference('https://example.test/document', 'immutable-v1', fingerprint, 'Reference', ['a'], 'human')

    def test_pending_action_blocks_duplicate_effect_and_completed_can_repeat(self):
        self.commitment()
        failures = []
        outputs = []
        # Pause immediately after the durable intent is published but after its lock
        # has been released: the spawned command waits for an explicit release file.
        command = [sys.executable, '-c',
                   "from pathlib import Path; import time; Path('entered').touch(); "
                   "\nwhile not Path('release').exists(): time.sleep(.01)\n"
                   "with Path('effects').open('a') as f: f.write('effect\\n')"]
        verifier = [sys.executable, '-c', "from pathlib import Path; assert Path('effects').exists()"]
        def run_first():
            try:
                outputs.append(self.k.run('commitment', ['a'], command, verifier, self.base, 'test', 'remove effects'))
            except BaseException as exc:
                failures.append(exc)
        thread = threading.Thread(target=run_first)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not (self.base / 'entered').exists() and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue((self.base / 'entered').exists(), repr(failures))
            with self.assertRaises(KernelError):
                self.k.run('commitment', ['a'],
                           [sys.executable, '-c', "from pathlib import Path; Path('duplicate').touch()"],
                           verifier, self.base, 'test', 'remove duplicate')
            self.assertFalse((self.base / 'duplicate').exists())
        finally:
            (self.base / 'release').touch()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(outputs[0]['verdict'], 'met')
        self.assertEqual((self.base / 'effects').read_text().splitlines(), ['effect'])
        repeated = self.k.run('commitment', ['a'], command, verifier, self.base, 'test repeat', 'remove effects')
        self.assertEqual(repeated['verdict'], 'met')
        self.assertEqual((self.base / 'effects').read_text().splitlines(), ['effect', 'effect'])

    def test_expired_replaced_commitment_not_reconsidered(self):
        with patch('ekk.kernel.now', return_value=JAN):
            # Fresh historical source avoids asserting a source known in the future.
            self.source = self.k.observe(self.source_file, 'Historical source', ['a'], 'human')
            self.commitment('old', valid_until=MAR)
        with patch('ekk.kernel.now', return_value=FEB):
            self.commitment('new', relations=[{'predicate': 'supersedes', 'target': 'old'}])
        result = self.k.evolve(['a'], at=APR, known_at=APR)
        self.assertFalse(any(c['commitment'] == 'old' for c in result['candidates']))

    def test_init_recovers_empty_assets_before_config(self):
        root = self.base / 'interrupted'
        (root / 'sources' / 'assets').mkdir(parents=True)
        for folder in ('records', 'protocols', 'views', '.obsidian'):
            (root / folder).mkdir()
        (root / '.obsidian' / 'unrelated.json').write_text('{}')
        kernel = Kernel(root)
        kernel.init()
        self.assertEqual(kernel.check()['status'], 'valid')
        self.assertEqual((root / '.obsidian' / 'unrelated.json').read_text(), '{}')

    def test_init_does_not_adopt_preexisting_assets(self):
        root = self.base / 'unowned'
        (root / 'sources' / 'assets').mkdir(parents=True)
        artifact = root / 'sources' / 'assets' / 'external'
        artifact.write_bytes(b'preserve')
        with self.assertRaises(KernelError):
            Kernel(root).init()
        self.assertEqual(artifact.read_bytes(), b'preserve')
