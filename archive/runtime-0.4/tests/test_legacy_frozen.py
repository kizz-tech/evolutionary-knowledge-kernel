"""Legacy readers stay frozen; the adapter baseline adds only retirement denial.

The 0.4 cutover explicitly disables writes to owner-retired roots. Historical
reader hashes remain unchanged; adapter behavior is covered by the denial test.
"""
from pathlib import Path
import hashlib
import unittest
import ekk
HASHES = {'kernel': '7cbf246b02edef5664a0d3eb265f5698742a8228e327ec7469faa0fdb93f921d', 'semantics': '7b09da7fac849c9b9a9b20d67e7ff136b5fdd10b0bda5c04218b618b30f26c21', 'semantics_v1': 'c6c6d5f08b8ec8aeaf99c0201ec8b29406530225f1f035a0a4dc3658bfd06c17', 'integration': '6782fc03a36dc4dbdb1fc617d0615d5a6590cfb6021cf962274b2b1614bf3492'}
class FrozenLegacyTests(unittest.TestCase):
    def test_legacy_readers_and_administrative_adapter_unchanged(self):
        for name, expected in HASHES.items():
            self.assertEqual(hashlib.sha256((Path(ekk.__file__).parent/(name+'.py')).read_bytes()).hexdigest(),expected,name)

    def test_retired_root_rejects_library_writes_but_remains_readable(self):
        import tempfile
        from ekk.kernel import Kernel,KernelError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()/'legacy';kernel=Kernel(root);kernel.init()
            before=(root/'kernel.yaml').read_bytes()
            (root/'.ekk-retired.json').write_text('{"status":"retired"}')
            self.assertEqual(kernel.check()['status'],'valid')
            with self.assertRaisesRegex(KernelError,'Retired'):
                kernel._write('kernel.yaml',b'changed',replace=True)
            self.assertEqual((root/'kernel.yaml').read_bytes(),before)
            with self.assertRaisesRegex(KernelError,'Retired'):kernel._require_writable()
