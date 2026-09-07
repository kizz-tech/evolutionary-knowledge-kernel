import fcntl
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ekk.kernel import Kernel, KernelError
from ekk.cli import resolve_root

class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()/'knowledge';self.k=Kernel(self.root);self.k.init()
        self.source=Path(self.temp.name)/'source.txt';self.source.write_text('original')
    def tearDown(self):self.temp.cleanup()
    def test_lock_blocks_second_writer(self):
        with self.k._lock():
            with self.assertRaises(KernelError):Kernel(self.root).observe(self.source,'s',['x'],'human:test')
        self.assertEqual(self.k.check()['records'],0)
    def test_source_directory_symlink_rejected(self):
        (self.root/'sources/assets').rmdir();(self.root/'sources/assets').symlink_to(self.source.parent,target_is_directory=True)
        with self.assertRaises(KernelError):self.k.observe(self.source,'s',['x'],'human:test')
    def test_cli_does_not_resolve_away_symlink(self):
        link=self.root.parent/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(KernelError):Kernel(resolve_root(str(link)))
    def test_atomic_publish_failure_does_not_create_descriptor(self):
        with patch('ekk.kernel.os.link',side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):self.k.observe(self.source,'s',['x'],'human:test')
        self.assertEqual(self.k.check()['records'],0)
        self.assertFalse(list(self.root.rglob('.ekk-tmp-*')))
    def test_failed_descriptor_leaves_only_recoverable_orphan_blob(self):
        original=self.k._append
        with patch.object(self.k,'_append',side_effect=OSError('injected after source')):
            with self.assertRaises(OSError):self.k.observe(self.source,'s',['x'],'human:test')
        self.assertEqual(self.k.check()['records'],0)
        self.assertEqual(len(list((self.root/'sources/assets').iterdir())),1)
        self.k.observe(self.source,'s',['x'],'human:test')
        self.assertEqual(self.k.check()['records'],1)
    def test_path_traversal_rejected(self):
        with self.assertRaises(KernelError):self.k._path('../outside')
    def test_external_reference_is_not_claimed_verified(self):
        result=self.k.reference('https://example.invalid/a','revision-1','f'*64,'external',['x'],'human:test')
        self.assertEqual(self.k.check()['reference_sources_not_remotely_verified'],[result['id']])
    def test_core_has_no_adapter_imports(self):
        import ast
        import ekk.semantics as core
        tree=ast.parse(Path(core.__file__).read_text())
        imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        self.assertFalse(imports & {'os','pathlib','yaml','subprocess','kernel','cli'})
