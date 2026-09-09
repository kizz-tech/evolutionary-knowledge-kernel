"""Preparation fails closed when source, translation or review inputs drift."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ekk.reference_export as exporter

SPEC = importlib.util.spec_from_file_location(
    'prepare_release', Path(__file__).resolve().parents[1] / 'tools/prepare_release.py')
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class PrepareReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.raw = {'docs/guide.ru.md': 'Original English guide.\n'.encode(),
                    'example.py': b"value = 'original'\n",
                    'examples/starter/ekk-blueprint/MANIFEST.sha256.json': b'{}\n',
                    'archive/runtime-0.4/MANIFEST.sha256.json': b'{"files": []}\n'}
        self.english = dict(self.raw)
        self.english['docs/guide.md'] = self.english.pop('docs/guide.ru.md')
        self.english['translation-manifest.json'] = release.encoded({
            'schema': 'ekk.translation-provenance/0.1', 'files': [{
                'original_path': 'docs/guide.ru.md',
                'original_sha256': release.sha(self.raw['docs/guide.ru.md']),
                'path': 'docs/guide.md', 'sha256': release.sha(self.english['docs/guide.md'])}]})
        self.write_tree('source', self.raw)
        self.write_tree('raw', self.raw)
        self.write_tree('english', self.english)
        self.plan = {'schema': release.SCHEMA, 'version': '0.7.0', 'source': 'source',
                     'output': 'result', 'prior_raw': self.receipt('raw', self.raw),
                     'prior_english': self.receipt('english', self.english),
                     'path_mappings': {'docs/guide.ru.md': 'docs/guide.md'},
                     'extra_files': {'tests/test_public_english.py': self.pin('english-test.py', b'"""English check."""\n')},
                     'translations': {}, 'replacements': [], 'synthetic_assets': [],
                     'manifests': {'examples/starter/ekk-blueprint/MANIFEST.sha256.json': 'map',
                                   'archive/runtime-0.4/MANIFEST.sha256.json': 'rows'}}
        self.addCleanup(patch.stopall)
        patch.object(exporter, 'FILES', tuple(self.raw)).start()
        patch.object(release, 'load_exporter', return_value=exporter).start()

    def write_tree(self, name, files):
        for key, value in files.items():
            path = self.root / name / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)

    def pin(self, name, data):
        (self.root / name).write_bytes(data)
        return {'path': name, 'sha256': release.sha(data)}

    def receipt(self, root, files):
        data = release.encoded({'schema': 'ekk.reference-export/2',
                               'files': {name: release.sha(data) for name, data in files.items()}})
        return {'root': root, 'receipt': self.pin(root + '.json', data)}

    def run_plan(self):
        path = self.root / 'plan.json'
        path.write_bytes(release.encoded(self.plan))
        return release.prepare(path)

    def test_reuse_original_preservation_and_reproducible_receipt(self):
        first = self.run_plan()
        self.assertFalse(first['published'])
        self.assertEqual((self.root / 'result/originals/docs/guide.ru.md').read_bytes(), self.raw['docs/guide.ru.md'])
        self.assertIn('release-edition.json', first['export']['files'])
        self.assertEqual(first['files'][0]['methods'], ['reused_verified_english'])
        self.assertFalse((self.root / 'result/candidate').exists())
        self.plan['output'] = 'second'
        second = self.run_plan()
        self.assertEqual(first['export'], second['export'])

    def test_changed_english_stays_current_and_unicode_values_are_preserved(self):
        (self.root / 'source/docs/guide.ru.md').write_text('New English guide.\n')
        original = "value = '\u043f\u0440\u0438\u0432\u0435\u0442'\n"
        (self.root / 'source/example.py').write_text(original)
        self.run_plan()
        self.assertEqual((self.root / 'result/source-export/docs/guide.md').read_text(), 'New English guide.\n')
        actual = (self.root / 'result/source-export/example.py').read_text()
        self.assertEqual(release.ast.dump(release.ast.parse(actual)), release.ast.dump(release.ast.parse(original)))
        self.assertIsNone(release.CYRILLIC.search(actual))

    def test_changed_non_english_requires_exact_translation_input(self):
        original = '\u041d\u043e\u0432\u044b\u0439 \u0442\u0435\u043a\u0441\u0442'.encode()
        (self.root / 'source/docs/guide.ru.md').write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'explicit translation'):
            self.run_plan()
        self.assertFalse((self.root / 'result').exists())
        self.assertFalse(list(self.root.glob('.ekk-prepare-*')))
        self.plan['translations'] = {'docs/guide.ru.md': {
            'original_sha256': release.sha(original), 'input': self.pin('translation.md', b'New text.\n')}}
        self.run_plan()
        self.assertEqual((self.root / 'result/source-export/docs/guide.md').read_bytes(), b'New text.\n')

    def test_python_comments_cannot_be_escaped_as_if_they_were_literals(self):
        (self.root / 'source/example.py').write_text('# \u0442\u0435\u043a\u0441\u0442\nvalue = 1\n')
        # Comments are prose even though the AST ignores them.
        with self.assertRaisesRegex(ValueError, 'explicit translation'):
            self.run_plan()

    def test_snapshot_tampering_and_replacement_drift_fail(self):
        (self.root / 'raw/example.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Snapshot hash mismatch'):
            self.run_plan()
        (self.root / 'raw/example.py').write_bytes(self.raw['example.py'])
        self.plan['replacements'] = [{'path': 'example.py', 'old': 'missing', 'new': 'x', 'count': 1}]
        with self.assertRaisesRegex(ValueError, 'Replacement count mismatch'):
            self.run_plan()
        self.assertFalse((self.root / 'result').exists())

    def test_translation_provenance_and_output_boundary_fail_closed(self):
        del self.english['translation-manifest.json']
        self.english['translation-manifest.json'] = release.encoded({
            'schema': 'ekk.translation-provenance/0.1', 'files': []})
        self.write_tree('english', self.english)
        self.plan['prior_english'] = self.receipt('english', self.english)
        with self.assertRaisesRegex(ValueError, 'lacks provenance'):
            self.run_plan()
        self.plan['output'] = 'source/result'
        with self.assertRaisesRegex(ValueError, 'outside all input trees'):
            self.run_plan()


if __name__ == '__main__':
    unittest.main()
