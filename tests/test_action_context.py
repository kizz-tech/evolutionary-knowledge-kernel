"""Action sufficiency includes governing closure without optional reading."""
import json
import unittest

import test_architecture_application as fixtures
from ekk.application import RealmService


class ActionContextTests(unittest.TestCase):
    setUp = fixtures.ApplicationTests.setUp
    meta = fixtures.ApplicationTests.meta
    add = fixtures.ApplicationTests.add
    source = fixtures.ApplicationTests.source
    decision = fixtures.ApplicationTests.decision

    def exact(self, key):
        row = self.app._load(self.store.snapshot())[-1][key]
        return {'realm': self.app._realm_id, 'id': key, 'revision': row['metadata']['revision'],
                'digest': 'sha256:' + row['digest']}

    def action(self, **options):
        return self.app.context(['scope'], selection='action_requirements', **options)

    def test_optional_overflow_does_not_omit_a_nonmandatory_governing_decision(self):
        decision = self.decision('choice'); decision['kind'] = 'decision'
        self.add(decision, 'The applicable commitment.', accept=['choice'])
        self.add(self.meta('large-unrelated-note'), 'Unrelated reading. ' * 2000)
        discovery = self.app.context(['scope'])
        self.assertTrue(discovery['manifest']['incomplete'])
        result = self.action()
        self.assertFalse(result['blocked'])
        self.assertFalse(result['manifest']['incomplete'])
        self.assertTrue(result['manifest']['projection']['complete'])
        self.assertNotIn('large-unrelated-note', json.dumps(result))
        choice = next(row for row in result['records'] if row['id'] == 'choice')
        self.assertTrue(choice['governs'])
        self.assertTrue(choice['mandatory'])
        self.assertFalse(choice['metadata'].get('mandatory', False))
        self.assertIn(decision['basis'][0]['id'], {row['id'] for row in result['records']})

    def test_required_budget_overflow_is_all_or_none(self):
        self.add(self.decision(), 'Mandatory content.', accept=['decision'])
        result = self.action(budget=100)
        self.assertTrue(result['blocked'])
        self.assertTrue(result['manifest']['incomplete'])
        self.assertFalse(result['manifest']['projection']['complete'])
        self.assertEqual(result['records'], [])
        self.assertEqual(result['manifest']['used_bytes'], 0)

    def test_accepted_hold_and_exact_resolution_keep_conflict_semantics(self):
        self.add(self.decision('choice'), accept=['choice'])
        choice = self.exact('choice')
        hold = self.meta('hold', 'decision', basis=[choice], conflicts=[choice],
                         commitment={'expectation': 'Pause for review'})
        self.add(hold, accept=['hold'])
        blocked = self.action()
        self.assertTrue(blocked['blocked'])
        self.assertEqual(blocked['conflicts'], [['choice', 'hold']])
        resolution = self.meta('resolution', 'decision', basis=[choice], supersedes=[self.exact('hold')],
                               commitment={'expectation': 'Review completed'})
        self.add(resolution, accept=['resolution'])
        resolved = self.action()
        self.assertFalse(resolved['blocked'])
        self.assertEqual(resolved['conflicts'], [])
        historical = next(row for row in resolved['records'] if row['id'] == 'hold')
        self.assertFalse(historical['governs'])

    def test_exact_historical_ground_keeps_its_own_dependency_bytes(self):
        self.add(self.meta('basis'), 'Original basis.')
        basis = self.exact('basis')
        self.add(self.meta('ground', basis=[basis]), 'Original ground.')
        ground = self.exact('ground')
        self.add({**self.meta('ground', basis=[basis]), 'revision': 2}, 'Later ground.')
        result = self.action(focus=[ground])
        self.assertTrue(result['manifest']['projection']['complete'])
        selected = {row['id']: row for row in result['records']}
        self.assertEqual(selected['ground']['body'], 'Original ground.')
        self.assertEqual(selected['basis']['body'], 'Original basis.')
        self.assertEqual(result['manifest']['forced_refs'], [ground])
        self.assertFalse(selected['ground']['governs'])

    def test_foreign_or_mismatched_exact_ground_never_becomes_ready(self):
        self.add(self.meta('ground'), 'Scoped material.')
        exact = self.exact('ground')
        for changed in ({**exact, 'realm': 'foreign-realm'}, {**exact, 'digest': 'sha256:' + '0' * 64},
                        {**exact, 'revision': 900}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.action(focus=[changed])

    def test_unreadable_governing_basis_blocks_without_disclosure(self):
        private = self.meta('private', 'context'); private['scope'] = ['private']; self.add(private)
        secret = self.meta('secret-basis'); secret['scope'] = ['private']; self.add(secret, 'hidden substance')
        choice = self.meta('hidden-choice', 'decision', basis=[self.exact('secret-basis')])
        self.add(choice, 'hidden choice', accept=['hidden-choice'])
        snapshot = self.store.snapshot()
        policy = self.codec.load_yaml(snapshot['files']['.ekk/governance.yaml']); policy['version'] += 1
        policy['grants'].append({'principal': 'reader', 'actions': ['read'], 'scopes': ['scope']})
        self.app.configure({'.ekk/governance.yaml': self.codec.dump_yaml(policy)},
                           base=snapshot['revision'], idempotency_key='limited-reader')
        reader = RealmService(self.store, 'reader', codec=self.codec)
        result = reader.context(['scope'], selection='action_requirements')
        self.assertTrue(result['blocked'])
        self.assertFalse(result['manifest']['projection']['complete'])
        for value in ('secret-basis', 'hidden-choice', 'hidden substance', 'hidden choice'):
            self.assertNotIn(value, json.dumps(result))

    def test_explicit_ground_outside_scope_is_denied(self):
        other = self.meta('other', 'context'); other['scope'] = ['other']; self.add(other)
        ground = self.meta('outside-ground'); ground['scope'] = ['other']; self.add(ground)
        with self.assertRaises(PermissionError):
            self.action(focus=[self.exact('outside-ground')])

    def test_discovery_default_and_explicit_mode_are_identical(self):
        self.add(self.meta('ordinary-note'), 'Ordinary reading.')
        self.assertEqual(self.app.context(['scope']), self.app.context(['scope'], selection='discovery'))
        with self.assertRaises(ValueError):
            self.action(task='ignored query')
        with self.assertRaises(ValueError):
            self.app.context(['scope'], selection='unsupported')


if __name__ == '__main__':
    unittest.main()
