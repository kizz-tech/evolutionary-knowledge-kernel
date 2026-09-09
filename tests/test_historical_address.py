"""Historical lookup cannot become an owner or exact-fragment shortcut."""
import base64
import json
from pathlib import Path
import tempfile
import unittest

from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.application.historical_address import historical_path
from ekk.model import digest


class HistoricalAddressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.codec = MarkdownCodec()
        self.store = GitStore(root/'realm', root/'runtime')
        self.app = RealmService(self.store, 'owner', codec=self.codec)
        self.app.init('Synthetic', realm_id='realm:archive', context_id='scope')
        self.number = 0

    def apply(self, proposal):
        self.number += 1
        return self.app.apply(proposal, idempotency_key='test-'+str(self.number))

    def source(self, body=b'# Header\r\nExact original. ^block\r\n', scope='scope'):
        proposal = self.app.capture(body, title='Archive', scope=[scope], filename='original.md')
        self.apply(proposal)
        raw = next(base64.b64decode(value) for path, value in proposal['changes'].items()
                   if path.startswith('records/') and path.endswith('.md'))
        m = self.codec.decode(raw)['metadata']
        return {'realm': 'realm:archive', 'id': m['id'], 'revision': 1, 'digest': 'sha256:'+digest(raw)}

    def maprow(self, ref, path='folder/original.md', legacy_id='same-id'):
        read = self.app.read_source(['scope','private'], ref) if self.has_private else self.app.read_source(['scope'], ref)
        return {'address_schema': 'ekk.historical-address-row/0.1', 'realm_id': ref['realm'],
                'origin': {'namespace': 'archive', 'path': path, 'id': legacy_id,
                           'sha256': read['asset']['sha256']},
                'target_ids': [ref['id']], 'native_reference': ref,
                'asset_index': 0, 'asset_path': read['asset']['path']}

    has_private = False

    def mapping(self, rows):
        return self.app.retain_migration_evidence(rows, migration_id='addresses-v1',
                    target_realm='realm:archive', idempotency_key='mapping')

    def resolve(self, app=None, **kwargs):
        return (app or self.app).resolve_historical(['scope'], migration_id='addresses-v1',
                                                    origin='archive', **kwargs)

    def test_exact_owner_map_relative_path_and_hash_disambiguation(self):
        first, second = self.source(), self.source(b'Another source.')
        rows = [self.maprow(first), self.maprow(second, path='other.md')]
        self.mapping(rows)
        before = self.store.snapshot()['revision']
        ambiguous = self.resolve(legacy_id='same-id')
        self.assertEqual('ambiguous', ambiguous['object_state'])
        self.assertEqual(2, len(ambiguous['candidates']))
        selected = self.resolve(path='../folder/original.md', containing_path='folder/note.md', selector='#Header')
        self.assertEqual('found', selected['object_state'])
        self.assertEqual(first, selected['candidates'][0]['reference'])
        self.assertEqual('#Header', selected['candidates'][0]['selector'])
        self.assertEqual('found', self.resolve(legacy_id='same-id', source_sha256=rows[1]['origin']['sha256'])['object_state'])
        self.assertEqual('unavailable', self.resolve(path='Folder/original.md')['object_state'])
        self.assertEqual(before, self.store.snapshot()['revision'])

    def test_hidden_candidate_has_no_existence_title_or_hash_oracle(self):
        m = dict(schema='ekk.record/0.1', id='private', title='Private', kind='context',
                 scope=['private'], revision=1, created_at='2026-09-09T00:00:00Z',
                 created_by='owner', context={'purpose':'Private'})
        self.apply(self.app.propose({'contexts/private.md': self.codec.encode(m)}))
        self.has_private = True
        visible, hidden = self.source(), self.source(b'Hidden bytes.', scope='private')
        self.mapping([self.maprow(visible), self.maprow(hidden, 'hidden.md')])
        reader = RealmService(self.store, 'owner', codec=self.codec, allowed_scopes=['scope'])
        result = self.resolve(reader, legacy_id='same-id')
        self.assertEqual('found', result['object_state'])
        self.assertEqual(visible, result['candidates'][0]['reference'])
        self.assertNotIn(hidden['id'], json.dumps(result))
        absent = self.resolve(reader, path='absent.md')
        denied = self.resolve(reader, path='hidden.md')
        self.assertEqual(absent, denied)

    def test_selectors_distinguish_found_object_from_fragment_and_paginate_bytes(self):
        raw = b'# Header\r\nExact original. ^block\r\n'
        ref = self.source(raw)
        for selector in ['#Header', '#^block', 'renderer:unknown']:
            result = self.app.read_source(['scope'], ref, selector=selector)
            self.assertEqual('found', result['object_state'])
            self.assertEqual('unsupported', result['selection']['state'])
            self.assertEqual('', result['base64'])
            self.assertTrue(result['incomplete'])
        part = self.app.read_source(['scope'], ref, selector='bytes:10:24', limit=5)
        self.assertEqual(raw[10:15], base64.b64decode(part['base64']))
        self.assertEqual(5, part['next_offset'])
        tail = self.app.read_source(['scope'], ref, selector='bytes:10:24', offset=5)
        self.assertEqual(raw[15:24], base64.b64decode(tail['base64']))
        self.assertFalse(tail['incomplete'])
        self.assertEqual('unavailable', self.app.read_source(['scope'], ref, selector='bytes:0:999')['selection']['state'])
        self.assertEqual(raw, base64.b64decode(self.app.read_source(['scope'], ref)['base64']))

    def test_relation_selector_is_preserved_and_path_cannot_escape_origin(self):
        self.assertEqual('#^block', self.app._relation_ref({'rel':'links_to','target':'target','selector':'#^block'})['selector'])
        for path in ['../../outside', '/old/absolute', 'folder/../../../escape', 'bad\\path']:
            with self.assertRaises(ValueError): historical_path(path, 'folder/note.md')

    def test_wrong_realm_or_corrupt_map_never_resolves(self):
        ref = self.source()
        row = self.maprow(ref)
        row['native_reference'] = {**ref, 'realm':'realm:elsewhere'}
        self.mapping([row])
        self.assertEqual('unavailable', self.resolve(path='folder/original.md')['object_state'])
        original = self.store.snapshot
        def corrupted(*args, **kwargs):
            snap = original(*args, **kwargs)
            return {**snap, 'files': {**snap['files'], 'migrations/addresses-v1/mapping.jsonl': b'{}\n'}}
        from unittest.mock import patch
        with patch.object(self.store, 'snapshot', side_effect=corrupted):
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                self.resolve(path='folder/original.md')

    def test_relation_selector_does_not_invalidate_prior_acceptance_receipt(self):
        grounds = self.source()
        def decision(key, **extra):
            m = dict(schema='ekk.record/0.1', id=key, title=key, kind='decision', scope=['scope'],
                     revision=1, created_at='2026-09-09T00:00:00Z', created_by='owner', basis=[grounds], **extra)
            self.apply(self.app.propose({'records/'+key+'.md':self.codec.encode(m)}))
            self.number += 1
            self.app.apply(self.app.propose({}), idempotency_key='accept-'+str(self.number), accept=[key])
        decision('prior')
        original = self.app._relation_ref
        from unittest.mock import patch
        def legacy(relation):
            return {key:value for key,value in original(relation).items() if key!='selector'}
        with patch.object(self.app, '_relation_ref', side_effect=legacy):
            decision('replacement', relations=[{'rel':'supersedes','target':'prior','revision':1,'selector':'#section'}])
        before = self.store.snapshot()
        receipts = {p:raw for p,raw in before['files'].items() if p.startswith('governance/receipts/')}
        context = self.app.context(['scope'])
        self.assertFalse(context['blocked'])
        self.assertEqual(['replacement'], [r['id'] for r in context['records'] if r['governs']])
        self.assertIn('#section', [ref.get('selector') for ref in self.app._refs(self.app._load(before)[-1]['replacement']['metadata'])])
        self.assertEqual(receipts, {p:raw for p,raw in self.store.snapshot()['files'].items() if p.startswith('governance/receipts/')})
        # Direct supersedes selectors already existed in old receipts; keep them.
        direct = {'supersedes':[{'id':'prior','selector':'#old-direct'}]}
        self.assertEqual(direct['supersedes'], self.app._receipt_supersedes(direct))


if __name__ == '__main__': unittest.main()
