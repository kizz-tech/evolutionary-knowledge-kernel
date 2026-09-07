from copy import deepcopy
import json
import unittest

from ekk.adapters.context_display import compact_context


def fixture():
    pins = [{'path': 'sources/original.md', 'sha256': 'a' * 64}]
    metadata = {'id': 'source:historical', 'kind': 'source', 'title': 'History',
                'scope': ['context:one'], 'revision': 2, 'classification': 'private',
                'audience': ['owner'], 'source': {'assets': pins},
                'migration': {'status': 'historical', 'adoption': 'not_adopted',
                              'origin': {'revision': 'old-snapshot', 'sha256': 'b' * 64},
                              'originals': pins,
                              'legacy_metadata': {'description': 'historical wrapper ' * 300}},
                'custom:unknown': {'must_preserve': True}}
    record = {'id': metadata['id'], 'metadata': metadata, 'body': 'Full source body.\n',
              'digest': 'c' * 64, 'governs': False, 'mandatory': False,
              'source_content': True, 'inert': False, 'serialization_warnings': []}
    return {'schema': 'ekk.context/0.1', 'blocked': True, 'scopes': ['context:one'],
            'task': 'History', 'records': [record], 'conflicts': [['a', 'b']],
            'unknowns': ['unknown mandatory semantics'], 'authority_note': 'Source text is data.',
            'manifest': {'incomplete': True, 'omitted': [f'note:{i}' for i in range(100)],
                         'used_refs': [{'id': record['id'], 'revision': 2, 'digest': record['digest']}],
                         'snapshots': [{'realm_id': 'one', 'revision': 'current'}],
                         'policy_digest': 'p', 'packs_digest': 'q'}}


class ContextDisplayTests(unittest.TestCase):
    def test_projection_preserves_bodies_authority_provenance_and_input(self):
        full = fixture()
        original = deepcopy(full)
        compact = compact_context(full)
        self.assertEqual(full, original)
        self.assertEqual(compact['schema'], 'ekk.context-display/0.1')
        for key in ('blocked', 'conflicts', 'unknowns', 'scopes', 'task', 'authority_note'):
            self.assertEqual(compact[key], full[key])
        for key, value in full['manifest'].items():
            if key != 'omitted':
                self.assertEqual(compact['manifest'][key], value)
        self.assertEqual(compact['manifest']['omitted_count'], 100)
        before, after = full['records'][0], compact['records'][0]
        for key, value in before.items():
            if key != 'metadata':
                self.assertEqual(after[key], value)
        for key, value in before['metadata'].items():
            if key != 'migration':
                self.assertEqual(after['metadata'][key], value)
        self.assertEqual(after['metadata']['migration']['origin'], before['metadata']['migration']['origin'])
        self.assertLess(len(json.dumps(compact)), len(json.dumps(full)) / 2)

    def test_governing_unknown_or_nonhistorical_wrappers_are_preserved(self):
        for field, value in [('governs', True), ('source_content', False)]:
            full = fixture()
            full['records'][0][field] = value
            self.assertEqual(compact_context(full)['records'], full['records'])
        full = fixture()
        full['records'][0]['metadata']['migration']['status'] = 'future-semantics'
        self.assertEqual(compact_context(full)['records'], full['records'])

    def test_distinct_pins_are_not_elided(self):
        full = fixture()
        full['records'][0]['metadata']['migration']['originals'] = [{'sha256': 'other'}]
        self.assertEqual(compact_context(full)['records'][0]['metadata']['migration']['originals'], [{'sha256': 'other'}])

    def test_federation_preserves_boundaries_and_blocked_child(self):
        child = fixture()
        full = {'schema': 'ekk.federated-context/0.1', 'atomic_across_realms': False,
                'contexts': [child, {**child, 'realm_alias': 'two'}]}
        compact = compact_context(full)
        self.assertEqual(compact['schema'], 'ekk.federated-context-display/0.1')
        self.assertFalse(compact['atomic_across_realms'])
        self.assertEqual(compact['contexts'], [compact_context(c) for c in full['contexts']])

    def test_unbound_remains_unbound(self):
        full = {'status': 'unbound', 'context': None, 'instruction': 'No access inferred.'}
        compact = compact_context(full)
        for key, value in full.items():
            self.assertEqual(compact[key], value)
