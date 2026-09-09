"""Legacy annotations stay readable without becoming structured review evidence."""
import unittest

import test_architecture_application as fixtures
from ekk.model import digest, validate_envelope


class ObservationCompatibilityTests(unittest.TestCase):
    setUp = fixtures.ApplicationTests.setUp
    meta = fixtures.ApplicationTests.meta
    add = fixtures.ApplicationTests.add
    source = fixtures.ApplicationTests.source
    decision = fixtures.ApplicationTests.decision

    def test_published_legacy_annotation_preserves_bytes_and_allows_next_write(self):
        metadata = self.meta('legacy-observation', 'observation', observation={
            'observed_at': '2026-09-07', 'confidence': 'site_claim_only'})
        raw = self.codec.encode(metadata, 'An attributed observation, not a measured result.')
        # Publish the old-format fixture below the new validator, as an earlier
        # writer did. The application must read it without rewriting history.
        files = dict(self.store.snapshot()['files'])
        files['records/legacy.md'] = raw
        self.store = type(self.store)(self.store.path.parent / 'legacy', self.store.runtime_dir.parent / 'legacy-runtime')
        self.store.initialize(files)
        self.app.store = self.store
        self.assertTrue(self.app.doctor()['ok'])
        realm = self.codec.load_yaml(files['.ekk/realm.yaml'])['id']
        ref = {'realm': realm, 'id': metadata['id'], 'revision': 1, 'digest': 'sha256:' + digest(raw)}
        self.assertEqual(self.app.fetch_record(['scope'], ref)['raw_markdown'].encode(), raw)
        self.add(self.meta('next-record'), 'Ordinary work continues.')
        self.app.fetch_record(['scope'], ref)
        self.assertEqual(self.store.snapshot()['files']['records/legacy.md'], raw)
        revised = self.codec.encode({**metadata, 'revision': 2}, 'Explicit later revision.')
        self.app.apply(self.app.propose({'records/legacy.md': revised}), idempotency_key='revise')
        historical = self.app.fetch_record(['scope'], ref)
        self.assertTrue(historical['historical'])
        self.assertEqual(historical['raw_markdown'].encode(), raw)
        self.assertTrue(self.app.doctor()['ok'])

    def test_legacy_annotation_does_not_fill_observation_gap(self):
        policy = self.decision(review={'triggers': [{
            'detector': 'observation_gap', 'aspects': ['quality'], 'max_age_days': 2}]})
        self.add(policy, accept=['decision'])
        self.add(self.meta('legacy-observation', 'observation', basis=policy['basis'],
                           observation={'observed_at': '2026-09-07', 'confidence': 'high'}))
        reasons = self.app.review(['scope'])['candidates'][0]['reasons']
        self.assertIn('unobserved aspects: quality', reasons)

    def test_partial_structured_observations_remain_invalid(self):
        profiles = [
            {'subject': 'scope'},
            {'aspects': ['quality'], 'observed_at': '2026-09-07T10:00:00Z'},
            {'subject': 'scope', 'aspects': ['quality'], 'observed_at': '2026-09-07'},
            {'subject': 'scope', 'aspects': [], 'observed_at': '2026-09-07T10:00:00Z'},
            {'subject': None, 'observed_at': '2026-09-07'},
            'not an object',
        ]
        for profile in profiles:
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                validate_envelope(self.meta('invalid-observation', 'observation', observation=profile))

    def test_structured_subject_must_still_resolve(self):
        with self.assertRaisesRegex(ValueError, 'observation subject must resolve'):
            self.add(self.meta('unresolved-observation', 'observation', observation={
                'subject': 'missing-subject', 'aspects': ['quality'],
                'observed_at': '2026-09-07T10:00:00Z'}))
