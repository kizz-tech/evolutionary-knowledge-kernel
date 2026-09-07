import tempfile
import unittest
from pathlib import Path
from ekk.kernel import Kernel, KernelError
from ekk.compatibility import inventory, snapshot, restore

class CompatibilityTests(unittest.TestCase):
    def test_full_restore_and_unresolved_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve(); k=Kernel(p/'base'); k.init()
            (p/'a.md').write_text('original'); k.observe(p/'a.md','a',['fixture:a'],'fixture')
            self.assertEqual(inventory(k.root)['scopes'][0]['classification'],'unresolved')
            snapshot(k.root,p/'backup')
            (p/'b.md').write_text('later'); k.observe(p/'b.md','b',['fixture:b'],'fixture')
            result=restore(p/'backup',p/'restored')
            self.assertEqual(result['check']['records'],1)
            self.assertEqual(k.check()['records'],2)
            with self.assertRaises(KernelError):restore(p/'backup',k.root)
            (p/'backup/base/README.md').write_text('tampered')
            with self.assertRaises(KernelError):restore(p/'backup',p/'tampered')

if __name__=='__main__':unittest.main()
