"""Release boundary checks without publishing or reading active knowledge stores."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.reference_export import FILES, inventory, prepare
import ekk.reference_export as reference_export


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
                         'src/ekk/adapters/file_lock.py',
                         'tests/test_lock_contention.py', 'tests/test_recovery_history.py',
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

    def test_all_tests_are_included_or_have_a_reviewed_reason(self):
        tests = {p.relative_to(self.repository).as_posix()
                 for p in (self.repository / 'tests').rglob('test_*.py')}
        exclusions = reference_export.REVIEWED_TEST_EXCLUSIONS
        self.assertFalse(tests - set(inventory(self.repository)) - set(exclusions))
        self.assertTrue(all(isinstance(reason, str) and reason.strip()
                            for reason in exclusions.values()))
        self.assertIn('tests/test_observation_compatibility.py', FILES)

    def test_unreviewed_test_blocks_export_until_explicit_review(self):
        source = self.root / 'source'
        prepare(self.repository, source)
        name = 'tests/test_new_behavior.py'
        (source / name).write_text('private = True\n')
        with self.assertRaisesRegex(ValueError, 'Unreviewed export test coverage'):
            prepare(source, self.root / 'result')
        self.assertFalse((self.root / 'result').exists())
        with patch.object(reference_export, 'REVIEWED_TEST_EXCLUSIONS',
                          {name: 'Private adapter fixture; behavior is covered by public tests.'}):
            receipt = prepare(source, self.root / 'reviewed')
        self.assertNotIn(name, receipt['files'])
        self.assertIn(name, receipt['reviewed_test_exclusions'])
        with patch.object(reference_export, 'REVIEWED_TEST_EXCLUSIONS', {name: ''}):
            with self.assertRaisesRegex(ValueError, 'test coverage'):
                prepare(source, self.root / 'invalid')

    def test_edition_declaration_cannot_expand_export_boundary(self):
        source = self.root / 'source'
        prepare(self.repository, source)
        edition = {'schema': 'ekk.release-edition/1', 'language': 'en',
                   'path_mappings': {}, 'extra_files': ['knowledge/private.md']}
        (source / 'release-edition.json').write_text(json.dumps(edition))
        with self.assertRaisesRegex(ValueError, 'Unreviewed edition extra'):
            prepare(source, self.root / 'result')
        edition['extra_files'] = []
        edition['path_mappings'] = {'README.md': '../private.md'}
        (source / 'release-edition.json').write_text(json.dumps(edition))
        with self.assertRaisesRegex(ValueError, 'path mapping'):
            prepare(source, self.root / 'result')

    def test_edition_maps_paths_without_rewriting_exporter(self):
        source = self.root / 'source'
        prepare(self.repository, source)
        mappings = {name: name.replace('.ru.md', '.md') for name in FILES if '.ru.md' in name}
        for name, target in mappings.items():
            if (source / name).exists():
                (source / name).rename(source / target)
        edition = {'schema': 'ekk.release-edition/1', 'language': 'en',
                   'path_mappings': mappings,
                   'extra_files': [name for name in reference_export.EDITION_EXTRAS
                                   if (source / name).is_file()]}
        (source / 'release-edition.json').write_text(json.dumps(edition))
        receipt = prepare(source, self.root / 'result')
        self.assertIn('docs/architecture.md', receipt['files'])
        self.assertNotIn('docs/architecture.ru.md', receipt['files'])
        self.assertEqual((source / 'src/ekk/reference_export.py').read_bytes(),
                         (self.root / 'result/src/ekk/reference_export.py').read_bytes())

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
