"""A host provider changes payload location, never realm-owned exact pack pins."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from ekk.assets import pack_directory
from ekk.adapters.command_line import service
from ekk.adapters.packs import PackDirectory


class PackProviderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        clean = {k: v for k, v in os.environ.items() if not k.startswith('EKK_')}
        clean.update(EKK_DATA_HOME=str(self.root/'data'))
        env = patch.dict(os.environ, clean, clear=True)
        env.start(); self.addCleanup(env.stop)
        self.bundled = pack_directory()
        self.provider = self.root/'preserved-packs'
        shutil.copytree(self.bundled, self.provider)

    def test_default_and_explicit_canonical_provider(self):
        self.assertEqual(self.bundled, pack_directory())
        with patch.dict(os.environ, EKK_PACK_DIRECTORY=str(self.provider)):
            self.assertEqual(self.provider, pack_directory())
        self.assertEqual(self.bundled, pack_directory())

    def test_invalid_override_never_falls_back(self):
        leaf = self.root/'regular'; leaf.write_text('not a directory')
        link = self.root/'linked'; link.symlink_to(self.provider, target_is_directory=True)
        for value in ('', 'relative', str(self.root/'missing'), str(leaf), str(link)):
            with self.subTest(value=value), patch.dict(os.environ, EKK_PACK_DIRECTORY=value):
                with self.assertRaisesRegex(ValueError, 'EKK_PACK_DIRECTORY') as error:
                    pack_directory()
                self.assertNotIn(str(self.root), str(error.exception))

    def test_existing_lock_keeps_exact_version_and_digest(self):
        manifest = self.provider/'base/pack.yaml'
        text = manifest.read_text().replace('version: 0.1.0-design', 'version: 0.1.0-alternate')
        manifest.write_text(text)
        with patch.dict(os.environ, EKK_PACK_DIRECTORY=str(self.provider)):
            alternate = PackDirectory(pack_directory())
            app = service(self.root/'realm')
            app.init('Synthetic preserved provider', realm_id=app.initial_realm_id,
                     context_id='scope', packs=[alternate.pin('ekk/base')])
            lock = (self.root/'realm/.ekk/packs.lock.yaml').read_bytes()
            self.assertTrue(app.doctor()['ok'])
        self.assertFalse(service(self.root/'realm').doctor()['ok'])
        with patch.dict(os.environ, EKK_PACK_DIRECTORY=str(self.provider)):
            self.assertTrue(service(self.root/'realm').doctor()['ok'])
        self.assertEqual(lock, (self.root/'realm/.ekk/packs.lock.yaml').read_bytes())
        original = service(self.root/'original')
        original.init('Bundled provider', realm_id=original.initial_realm_id,
                      context_id='scope', packs=[PackDirectory(self.bundled).pin('ekk/base')])
        with patch.dict(os.environ, EKK_PACK_DIRECTORY=str(self.provider)):
            self.assertFalse(service(self.root/'original').doctor()['ok'])

    def test_changed_added_deleted_payload_cannot_satisfy_existing_lock(self):
        with patch.dict(os.environ, EKK_PACK_DIRECTORY=str(self.provider)):
            app = service(self.root/'realm')
            app.init('Exact pins', realm_id=app.initial_realm_id, context_id='scope',
                     packs=[PackDirectory(pack_directory()).pin('ekk/base')])
            payload = self.provider/'base/METHOD.md'; original = payload.read_bytes()
            for mutation in ('change', 'add', 'delete'):
                with self.subTest(mutation=mutation):
                    if mutation == 'change': payload.write_bytes(original+b'\nchanged')
                    elif mutation == 'add': (self.provider/'base/extra.txt').write_text('extra')
                    else: payload.unlink()
                    self.assertFalse(service(self.root/'realm').doctor()['ok'])
                    payload.write_bytes(original)
                    (self.provider/'base/extra.txt').unlink(missing_ok=True)
                    self.assertTrue(service(self.root/'realm').doctor()['ok'])


if __name__ == '__main__': unittest.main()
