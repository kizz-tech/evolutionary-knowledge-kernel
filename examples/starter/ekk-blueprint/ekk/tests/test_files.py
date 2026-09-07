"""Проверки внешних инвариантов файлового профиля на синтетическом realm."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest

import yaml

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ekk_validator', BASE / 'tools/validate.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class FileContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'realm'
        shutil.copytree(BASE / 'knowledge', self.root)

    def result(self):
        return validator.validate_realm(self.root)

    def edit(self, relative, fn):
        path = self.root / relative
        lines = path.read_text().splitlines()
        end = lines.index('---', 1)
        data = yaml.safe_load('\n'.join(lines[1:end]))
        fn(data)
        path.write_text('---\n' + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
                        + '---\n' + '\n'.join(lines[end + 1:]) + '\n')

    def add_receipt(self):
        path = self.root / 'records/decision-example.md'
        record = validator.parse_record(path)
        receipt = {'schema':'ekk.receipt/0.1', 'id':'example-receipt',
                   'record_id':record['id'], 'record_revision':record['revision'],
                   'record_sha256':validator.sha256(path),
                   'actor':'principal:example-owner', 'adopted_at':'2026-09-07T01:00:00Z',
                   'governance_sha256':validator.sha256(self.root/'.ekk/governance.yaml')}
        dest=self.root/'governance/receipts/example.json'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(receipt))
        return path, dest

    def test_valid_example_does_not_claim_security(self):
        r = self.result()
        self.assertTrue(r['structural_valid'], r)
        self.assertEqual(r['source_bytes_verified'], 1)
        self.assertIn('authority', r['guarantees_not_verified'])
        self.assertIn('confidentiality', r['guarantees_not_verified'])

    def test_duplicate_identity_is_rejected(self):
        shutil.copy(self.root/'records/source-example.md', self.root/'records/copy.md')
        self.assertFalse(self.result()['structural_valid'])

    def test_unknown_scope_is_rejected(self):
        self.edit('records/observation-example.md', lambda d: d.update(scope=['missing-context']))
        self.assertFalse(self.result()['structural_valid'])

    def test_dangling_local_link_is_rejected(self):
        self.edit('records/observation-example.md', lambda d: d['relations'][0].update(target='missing-record'))
        self.assertFalse(self.result()['structural_valid'])

    def test_external_link_is_not_silently_fetched_or_declared_verified(self):
        self.edit('records/observation-example.md', lambda d: d['relations'][0].update(realm='other-realm',target='other-record'))
        r = self.result()
        self.assertTrue(r['structural_valid'], r)
        self.assertTrue(any('внешняя ссылка' in w for w in r['warnings']))

    def test_changed_source_bytes_are_rejected(self):
        asset=next((self.root/'sources').rglob('original.txt'))
        asset.write_text('changed')
        self.assertFalse(self.result()['structural_valid'])

    def test_source_path_traversal_is_rejected(self):
        self.edit('records/source-example.md', lambda d: d['source']['assets'][0].update(path='../secret.txt'))
        self.assertFalse(self.result()['structural_valid'])

    def test_source_symlink_is_rejected(self):
        asset=next((self.root/'sources').rglob('original.txt'))
        outside=Path(self.tmp.name)/'outside.txt'
        outside.write_bytes(asset.read_bytes())
        asset.unlink()
        asset.symlink_to(outside)
        self.assertFalse(self.result()['structural_valid'])

    def test_duplicate_yaml_keys_are_rejected(self):
        path=self.root/'records/observation-example.md'
        text=path.read_text().replace('kind: observation', 'kind: observation\nkind: decision')
        path.write_text(text)
        self.assertFalse(self.result()['structural_valid'])

    def test_yaml_aliases_are_rejected(self):
        with self.assertRaises(validator.InvalidDocument):
            validator.parse_yaml('a: &a [1, 2]\nb: *a\n')

    def test_unknown_kind_is_retained_as_non_executable_document(self):
        self.edit('records/observation-example.md', lambda d: d.update(kind='domain.custom'))
        r=self.result()
        self.assertTrue(r['structural_valid'], r)
        self.assertTrue(any('Неизвестный kind' in w for w in r['warnings']))

    def test_current_adoption_is_bound_to_exact_bytes(self):
        self.add_receipt()
        r=self.result()
        self.assertTrue(r['structural_valid'], r)
        self.assertEqual(r['current_receipt_content_bindings_verified'],1)
        self.assertIn('authority',r['guarantees_not_verified'])

    def test_altered_adopted_bytes_do_not_keep_receipt(self):
        path,_=self.add_receipt()
        path.write_text(path.read_text()+'\nChanged content.\n')
        self.assertFalse(self.result()['structural_valid'])

    def test_historical_receipt_requires_version_store_not_fake_validation(self):
        self.add_receipt()
        self.edit('records/decision-example.md', lambda d: d.update(revision=2))
        r=self.result()
        self.assertTrue(r['structural_valid'],r)
        self.assertTrue(any('исторический receipt' in w for w in r['warnings']))
        self.assertEqual(r['current_receipt_content_bindings_verified'],0)

    def test_unsupported_schema_is_rejected(self):
        self.edit('records/observation-example.md', lambda d: d.update(schema='ekk.record/99'))
        self.assertFalse(self.result()['structural_valid'])

    def test_invalid_timestamp_is_rejected(self):
        self.edit('records/observation-example.md', lambda d: d.update(created_at='yesterday'))
        self.assertFalse(self.result()['structural_valid'])

    def test_manifest_cannot_escape_root(self):
        path=self.root/'.ekk/realm.yaml'
        data=yaml.safe_load(path.read_text())
        data['storage']['record_roots']=['../outside']
        path.write_text(yaml.safe_dump(data))
        self.assertFalse(self.result()['structural_valid'])

    def test_workspace_binding_matches_proposed_schema(self):
        path=BASE/'tests/fixtures/workspace.yaml'
        self.assertEqual(validator.schema_errors('workspace',yaml.safe_load(path.read_text())),[])


if __name__ == '__main__':
    unittest.main()
