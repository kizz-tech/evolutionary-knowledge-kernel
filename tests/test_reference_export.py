"""Release boundary checks without publishing or reading active knowledge stores."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ekk.reference_export import FILES, prepare


class ReferenceExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repository = Path(__file__).resolve().parents[1]

    def test_reproducible_complete_source_and_exact_starter_bytes(self):
        first = self.root / 'first'
        second = self.root / 'second'
        receipt = prepare(self.repository, first)
        self.assertEqual(receipt, prepare(self.repository, second))
        self.assertFalse(receipt['published'])
        self.assertTrue(receipt['license_selected'])
        self.assertEqual(receipt['license'], 'Apache-2.0')
        for required in ('src/ekk/assets.py', 'src/ekk/application/service.py',
                         'src/ekk/adapters/contained_store.py',
                         'src/ekk/adapters/context_display.py',
                         'docs/quickstart.md', 'examples/quickstart.py', 'LICENSE',
                         'spec/schemas/record.schema.json', 'packs/base/pack.yaml'):
            self.assertIn(required, receipt['files'])
        self.assertFalse(any(name.startswith(('knowledge/', '.git/', '.ekk/'))
                             for name in receipt['files']))
        for name, digest in receipt['files'].items():
            self.assertEqual(hashlib.sha256((first / name).read_bytes()).hexdigest(), digest)
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        self.assertEqual((first / 'export-manifest.json').read_bytes(),
                         (second / 'export-manifest.json').read_bytes())

    def test_all_runtime_modules_are_explicitly_reviewed_for_export(self):
        runtime = {str(p.relative_to(self.repository))
                   for p in (self.repository / 'src/ekk').rglob('*.py')}
        self.assertFalse(runtime - set(FILES), 'Review new runtime modules before release')

    def test_unreviewed_files_are_not_discovered(self):
        source = self.root / 'source'
        prepare(self.repository, source)
        (source / 'src/ekk/unreviewed.py').write_text('private = True\n')
        (source / 'knowledge').mkdir()
        (source / 'knowledge/private.md').write_text('private knowledge')
        receipt = prepare(source, self.root / 'result')
        self.assertNotIn('src/ekk/unreviewed.py', receipt['files'])
        self.assertFalse((self.root / 'result/knowledge').exists())

    def test_linked_parent_and_missing_source_fail_without_partial_export(self):
        source = self.root / 'source'
        prepare(self.repository, source)
        original = source / 'packs/base'
        moved = self.root / 'moved-pack'
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked'):
            prepare(source, self.root / 'result')
        self.assertFalse((self.root / 'result').exists())
        self.assertFalse(list(self.root.glob('.ekk-export-*')))

    def test_private_marker_and_existing_destination_are_rejected(self):
        source = self.root / 'source'
        prepare(self.repository, source)
        (source / 'README.md').write_bytes(b'/' + b'Users/example/private')
        with self.assertRaisesRegex(ValueError, 'Private material'):
            prepare(source, self.root / 'result')
        self.assertFalse((self.root / 'result').exists())
        with self.assertRaisesRegex(ValueError, 'new export location'):
            prepare(self.repository, source)


if __name__ == '__main__':
    unittest.main()
