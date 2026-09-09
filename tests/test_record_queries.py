"""Canonical query and exact-acceptance contracts used by CLI and private MCP."""
import base64
from pathlib import Path
import tempfile
import unittest

from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.model import Conflict, digest


class RecordQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = GitStore(root / 'realm', root / 'runtime')
        self.codec = MarkdownCodec()
        self.app = RealmService(self.store, 'owner', lambda: '2026-09-08T00:00:00Z', codec=self.codec)
        self.app.init('Synthetic', realm_id='realm:test', context_id='scope')

    def add(self, key, body='', *, revision=1, scopes=None, **extra):
        metadata = {'schema': 'ekk.record/0.1', 'id': key, 'kind': 'note', 'title': key,
                    'scope': scopes or ['scope'], 'revision': revision,
                    'created_at': '2026-09-08T00:00:00Z', 'created_by': 'owner', **extra}
        raw = self.codec.encode(metadata, body)
        self.app.apply(self.app.propose({f'records/{key}.md': raw}),
                       idempotency_key=key + str(revision))
        return {'realm': 'realm:test', 'id': key, 'revision': revision, 'digest': 'sha256:' + digest(raw)}

    def source(self, content=b'exact source\r\n', filename='original.txt'):
        proposal = self.app.capture(content, title='Source', scope=['scope'], filename=filename)
        self.app.apply(proposal, idempotency_key='capture-source')
        return next(hit['reference'] for hit in self.app.search_records(['scope'])['results'] if hit['kind'] == 'source')

    def other_context(self):
        return self.add('other', scopes=['other'], kind='context', context={'purpose': 'Other'})

    def test_search_owns_source_text_and_pins_pagination(self):
        source = self.source('\u0410\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u0443\u0440\u0430 \u0438 \u043d\u0435\u043f\u0440\u0435\u0440\u044b\u0432\u043d\u043e\u0441\u0442\u044c\r\n'.encode())
        result = self.app.search_records(['scope'], query='\u0430\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u0443\u0440\u0430 \u043d\u0435\u043f\u0440\u0435\u0440\u044b\u0432\u043d\u043e\u0441\u0442\u044c')
        self.assertEqual(result['results'][0]['reference'], source)
        self.assertTrue(result['results'][0]['matched_asset'].endswith('original.txt'))
        self.add('another', '\u0410\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u0443\u0440\u0430')
        first = self.app.search_records(['scope'], limit=1)
        second = self.app.search_records(['scope'], limit=1, offset=first['next_offset'],
                                         expected_snapshot=first['snapshot'])
        self.assertNotEqual(first['results'][0]['reference'], second['results'][0]['reference'])
        self.add('change')
        with self.assertRaises(Conflict):
            self.app.search_records(['scope'], offset=1, expected_snapshot=first['snapshot'])
        with self.assertRaises(ValueError):
            self.app.search_records(['scope'], offset=1)

    def test_exact_historical_fetch_and_current_permission(self):
        previous = self.add('versioned', 'old bytes')
        current = self.add('versioned', 'new bytes', revision=2)
        old = self.app.fetch_record(['scope'], previous)
        self.assertTrue(old['historical'])
        self.assertEqual(old['body'], 'old bytes')
        self.assertIn('old bytes', old['raw_markdown'])
        self.assertEqual(self.app.fetch_record(['scope'], current)['body'], 'new bytes')
        denied = RealmService(self.store, 'stranger', codec=self.codec, allowed_scopes=['scope'])
        with self.assertRaises(PermissionError):
            denied.fetch_record(['scope'], previous)
        with self.assertRaises(PermissionError):
            self.app.fetch_record(['scope'], {**previous, 'realm': 'realm:other'})
        with self.assertRaises(ValueError):
            self.app.fetch_record(['scope'], {**previous, 'digest': 'sha256:' + '0' * 64})

    def test_out_of_scope_dependencies_do_not_leak_in_search_or_fetch(self):
        self.other_context()
        secret = self.add('private', 'hidden bytes', scopes=['other'])
        public = self.add('public', 'visible-looking bytes', depends_on=[secret])
        limited = RealmService(self.store, 'owner', codec=self.codec, allowed_scopes=['scope'])
        self.assertEqual(limited.search_records(['scope'], query='visible-looking')['results'], [])
        with self.assertRaises(PermissionError):
            limited.fetch_record(['scope'], public)
        self.assertEqual([row['id'] for row in limited.list_contexts(['scope'])['contexts']], ['scope'])
        with self.assertRaises(PermissionError):
            limited.list_contexts(['other'])

    def test_source_bytes_survive_historical_deletion_and_are_chunked_exactly(self):
        content = b'\x00\xff exact\r\n bytes'
        ref = self.source(content, 'original.bin')
        row = self.app.fetch_record(['scope'], ref)
        asset = row['metadata']['source']['assets'][0]['path']
        self.app.apply(self.app.propose({row['path']: None, asset: None}), idempotency_key='remove-source')
        parts = []
        offset = 0
        while True:
            chunk = self.app.read_source(['scope'], ref, offset=offset, limit=3)
            parts.append(base64.b64decode(chunk['base64']))
            if chunk['next_offset'] is None:
                break
            offset = chunk['next_offset']
        self.assertEqual(b''.join(parts), content)
        self.assertNotEqual(chunk['snapshot'], chunk['record_snapshot'])
        with self.assertRaises(ValueError):
            self.app.read_source(['scope'], ref, asset_index=1)
        with self.assertRaises(ValueError):
            self.app.read_source(['scope'], ref, offset=len(content) + 1)

    def test_search_bounds_are_explicit_and_boolean_numbers_are_rejected(self):
        self.source(b'first words ' + b'x' * 100 + b' beyond', 'original.txt')
        result = self.app.search_records(['scope'], query='beyond', source_byte_limit=16)
        self.assertEqual(result['results'], [])
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['source_search']['omitted_or_partial_assets'], 1)
        for values in ({'limit': True}, {'offset': True}, {'source_byte_limit': True}, {'limit': 101}):
            with self.assertRaises(ValueError):
                self.app.search_records(['scope'], **values)

    def test_acceptance_is_exact_separate_and_retryable(self):
        source = self.source()
        decision = self.add('decision', kind='decision', basis=[source],
                            commitment={'expectation': 'Preserve exact evidence'})
        before = self.app.context(['scope'])
        self.assertFalse(next(row for row in before['records'] if row['id'] == 'decision')['governs'])
        base = before['manifest']['snapshots'][0]['revision']
        receipt = self.app.accept_records(['scope'], [decision], expected_snapshot=base, idempotency_key='accept-one')
        retry = self.app.accept_records(['scope'], [decision], expected_snapshot=base, idempotency_key='accept-one')
        self.assertEqual(receipt, retry)
        after = self.app.context(['scope'])
        self.assertTrue(next(row for row in after['records'] if row['id'] == 'decision')['governs'])
        with self.assertRaises(ValueError):
            self.app.accept_records(['scope'], [{**decision, 'digest': 'sha256:' + '0' * 64}],
                                    expected_snapshot=base, idempotency_key='accept-one')

    def test_acceptance_reference_must_match_explicit_base(self):
        source = self.source()
        old = self.add('decision', kind='decision', basis=[source], commitment={'expectation': 'First'})
        base = self.store.snapshot()['revision']
        new = self.add('decision', revision=2, kind='decision', basis=[source], commitment={'expectation': 'Second'})
        with self.assertRaises(ValueError):
            self.app.accept_records(['scope'], [new], expected_snapshot=base, idempotency_key='wrong-base')
        with self.assertRaises(Conflict):
            self.app.accept_records(['scope'], [old], expected_snapshot=base, idempotency_key='stale-base')


if __name__ == '__main__':
    unittest.main()
