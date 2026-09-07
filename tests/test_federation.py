import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.federation import Federation, TransferError, digest
from ekk.realms import RealmStore, Grant, PermissionDenied, RecordRef


class FederationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.source_store = RealmStore.create(self.path / 'source', 'realm-source', grants=[
            Grant('owner', ('*',), audiences=('*',)),
            Grant('locator', ('reference',), audiences=('*',),
                  destinations=('realm-target',), disclosure_audiences=('private',)),
            Grant('reader', ('read', 'reference'), audiences=('*',),
                  destinations=('realm-target',), disclosure_audiences=('private',)),
            Grant('copier', ('read', 'copy'), audiences=('*',),
                  destinations=('realm-target',), disclosure_audiences=('private',)),
            Grant('limited-discloser', ('read', 'disclose'), audiences=('private',),
                  destinations=('realm-target',), disclosure_audiences=('private',)),
            Grant('source-only-discloser', ('read', 'disclose'), audiences=('private',)),
            Grant('relabeler', ('read', 'copy'), audiences=('private',),
                  destinations=('realm-target',), disclosure_audiences=('public',)),
            Grant('relabeler', ('disclose',), audiences=('private',),
                  destinations=('realm-target',), disclosure_audiences=('private',)),
        ])
        self.target_store = RealmStore.create(self.path / 'target', 'realm-target', grants=[
            Grant('owner', ('*',), audiences=('*',)),
            Grant('reader', ('read',), audiences=('*',)),
            Grant('other-contributor', ('read', 'contribute'), audiences=('*',)),
        ])
        self.source = self.source_store.session('owner')
        self.target = self.target_store.session('owner')
        self.ref = self.source.contribute('private source body', scopes=['topic:a'])
        self.transport = Federation(self.path / 'receipts', clock=lambda: self.now)

    def prepare(self, op='import', **kwargs):
        return self.transport.prepare('operation-1', op, self.source, self.target,
                                      self.ref, scopes=['topic:a'], **kwargs)

    def test_reference_requires_no_body_access_and_discloses_only_locator(self):
        locator = self.source_store.session('locator')
        with patch.object(locator, 'view', side_effect=AssertionError('body accessed')):
            self.transport.prepare('ref', 'reference', locator, self.target, self.ref)
            self.transport.accept('ref', locator, self.target)
            self.assertEqual(self.transport.resolve('ref', locator, self.target),
                             {'ref': self.ref.to_dict()})
        with self.assertRaises(PermissionDenied):
            locator.view().get(self.ref)
        self.assertEqual(self.target.view().list(), [])
        self.assertNotIn('private source body', (self.path / 'receipts').joinpath(digest('ref') + '.json').read_text())

    def test_projection_is_fresh_expiring_and_offline_fails_closed(self):
        self.prepare('projection', expires_at=self.now + timedelta(minutes=1))
        self.transport.accept('operation-1', self.source, self.target)
        self.assertEqual(self.transport.resolve('operation-1', self.source, self.target)['body'],
                         'private source body')
        with self.assertRaises(PermissionDenied):
            self.transport.resolve('operation-1', None, self.target)
        self.now += timedelta(minutes=2)
        with self.assertRaises(PermissionDenied):
            self.transport.resolve('operation-1', self.source, self.target)
        self.assertNotIn('private source body', json.dumps(self.transport.receipt('operation-1')))

    def test_offline_store_does_not_disclose_path_in_failure(self):
        self.prepare('projection', expires_at=self.now + timedelta(minutes=1))
        self.transport.accept('operation-1', self.source, self.target)
        self.source_store.path.rename(self.path / 'offline')
        with self.assertRaisesRegex(PermissionDenied, '^transfer unavailable$'):
            self.transport.resolve('operation-1', self.source, self.target)

    def test_current_rights_rechecked_even_for_historical_projection(self):
        self.prepare('projection', expires_at=self.now + timedelta(minutes=1))
        self.transport.accept('operation-1', self.source, self.target)
        with patch.object(self.source, 'authorize', side_effect=PermissionDenied('revoked')):
            with self.assertRaises(PermissionDenied):
                self.transport.resolve('operation-1', self.source, self.target,
                                       known_at='2020-01-01T00:00:00Z')

    def test_real_policy_revocation_invalidates_existing_projection(self):
        self.prepare('projection', expires_at=self.now + timedelta(minutes=1))
        self.transport.accept('operation-1', self.source, self.target)
        self.source.replace_policy([], expected_epoch=self.source.policy_epoch)
        with self.assertRaises(PermissionDenied):
            self.transport.resolve('operation-1', self.source, self.target,
                                   known_at='2020-01-01T00:00:00Z')
        with self.assertRaises(PermissionDenied):
            self.transport.accept('operation-1', self.source, self.target)

    def test_target_acceptance_revoked_between_prepare_and_accept(self):
        self.prepare()
        self.target.replace_policy([Grant('owner', ('read', 'contribute'), audiences=('*',))],
                                   expected_epoch=self.target.policy_epoch)
        with self.assertRaises(PermissionDenied):
            self.transport.accept('operation-1', self.source, self.target)
        self.assertEqual(self.target.view().list(), [])

    def test_copy_is_distinct_from_read_and_accept(self):
        with self.assertRaises(PermissionDenied):
            self.transport.prepare('denied', 'import', self.source_store.session('reader'),
                                   self.target, self.ref)
        with self.assertRaises(PermissionDenied):
            self.transport.prepare('denied', 'import', self.source,
                                   self.target_store.session('reader'), self.ref)

    def test_import_is_new_non_governing_with_private_origin_receipt(self):
        self.prepare()
        result = self.transport.accept('operation-1', self.source, self.target)
        imported = self.target.view().get(RecordRef.from_dict(result['ref']))
        self.assertEqual(imported['body'], 'private source body')
        self.assertFalse(imported['governing'])
        self.assertNotEqual(result['ref'], self.ref.to_dict())
        self.assertEqual(self.transport.receipt('operation-1')['source_ref'], self.ref.to_dict())
        self.assertEqual(self.transport.accept('operation-1', self.source, self.target), result)
        self.assertEqual(len(self.target.view().list()), 1)

    def test_interrupted_receipt_write_recovers_without_duplicate(self):
        self.prepare()
        save = self.transport._save
        def interrupted(receipt):
            if receipt['state'] == 'accepted':
                raise OSError('simulated interruption after target write')
            return save(receipt)
        with patch.object(self.transport, '_save', side_effect=interrupted):
            with self.assertRaises(PermissionDenied):
                self.transport.accept('operation-1', self.source, self.target)
        result = self.transport.accept('operation-1', self.source, self.target)
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(len(self.target.view().list()), 1)

    def test_import_withdrawal_marks_review_without_recalling_local_copy(self):
        self.prepare()
        result = self.transport.accept('operation-1', self.source, self.target)
        review = self.transport.reconsider('operation-1', None, self.target)
        self.assertTrue(review['reconsider'])
        self.assertNotIn('source_ref', review)
        self.assertEqual(self.target.view().get(result['ref'])['body'], 'private source body')

    def test_operation_id_cannot_be_rebound(self):
        self.prepare()
        with self.assertRaises(TransferError):
            self.transport.prepare('operation-1', 'import', self.source, self.target,
                                   self.ref, scopes=['different'])

    def test_unreviewed_or_changed_derivation_rejected(self):
        with self.assertRaises(TransferError):
            self.prepare('derive', audience='public', body='private source body')
        self.prepare('derive', audience='public', body='approved abstract',
                     approved_digest=digest('approved abstract'))
        with self.assertRaises(TransferError):
            self.transport.accept('operation-1', self.source, self.target,
                                  prepared_body='private source body')
        self.assertEqual(self.target.view().list(), [])
        self.assertEqual(self.transport.receipt('operation-1')['state'], 'failed')

    def test_derivation_has_no_private_lineage_and_is_not_external_publication(self):
        self.prepare('derive', audience='public', body='approved abstract',
                     approved_digest=digest('approved abstract'))
        result = self.transport.accept('operation-1', self.source, self.target)
        exported = self.target.view().get(RecordRef.from_dict(result['ref']))
        self.assertEqual(exported['body'], 'approved abstract')
        self.assertEqual(exported['relations'], [])
        self.assertNotIn(self.ref.record_id, json.dumps(exported))
        self.assertNotIn('published', json.dumps(result))
        self.assertNotIn('source_ref', result)
        self.assertFalse(exported['governing'])

    def test_source_read_and_copy_do_not_authorize_disclosure(self):
        with self.assertRaises(PermissionDenied):
            self.transport.prepare('derive-denied', 'derive', self.source_store.session('copier'),
                                   self.target, self.ref, audience='public', body='abstract',
                                   approved_digest=digest('abstract'))

    def test_copy_cannot_silently_relabel_private_as_public(self):
        with self.assertRaises(PermissionDenied):
            self.transport.prepare('copy-public', 'import', self.source_store.session('copier'),
                                   self.target, self.ref, audience='public')
        self.assertEqual(self.target.view().list(), [])

    def test_disclosure_source_permission_does_not_authorize_public_destination(self):
        for principal in ('limited-discloser', 'source-only-discloser'):
            with self.subTest(principal=principal), self.assertRaises(PermissionDenied):
                self.transport.prepare(principal, 'derive', self.source_store.session(principal),
                                       self.target, self.ref, audience='public', body='reviewed',
                                       approved_digest=digest('reviewed'))

    def test_import_relabel_needs_destination_aware_disclosure_too(self):
        with self.assertRaises(PermissionDenied):
            self.transport.prepare('relabel', 'import', self.source_store.session('relabeler'),
                                   self.target, self.ref, audience='public')

    def test_destination_disclosure_rechecked_after_review(self):
        self.prepare('derive', audience='public', body='reviewed',
                     approved_digest=digest('reviewed'))
        self.source.replace_policy([
            Grant('owner', ('read', 'disclose'), audiences=('private',),
                  destinations=('realm-target',), disclosure_audiences=('private',))
        ], expected_epoch=self.source.policy_epoch)
        with self.assertRaises(PermissionDenied):
            self.transport.accept('operation-1', self.source, self.target)
        self.assertEqual(self.target.view().list(), [])

    def test_disclosure_destination_realm_is_enforced(self):
        other = RealmStore.create(self.path / 'other', 'realm-other', grants=[
            Grant('owner', ('*',), audiences=('*',))]).session('owner')
        with self.assertRaises(PermissionDenied):
            self.transport.prepare('wrong-realm', 'derive',
                                   self.source_store.session('limited-discloser'), other,
                                   self.ref, body='reviewed', approved_digest=digest('reviewed'))

    def test_reconsider_by_different_reader_does_not_modify_receipt(self):
        self.prepare()
        self.transport.accept('operation-1', self.source, self.target)
        before = self.transport.receipt('operation-1')
        with self.assertRaises(PermissionDenied):
            self.transport.reconsider('operation-1', self.source,
                                      self.target_store.session('reader'))
        self.assertEqual(before, self.transport.receipt('operation-1'))

    def test_receipt_flushes_file_and_directory(self):
        import os
        import stat
        original = os.fsync
        kinds = []
        def capture(fd):
            kinds.append(stat.S_ISDIR(os.fstat(fd).st_mode))
            return original(fd)
        with patch('ekk.federation.os.fsync', side_effect=capture):
            self.prepare()
        self.assertEqual(kinds, [False, True])

    def test_interrupted_recovery_rejects_missing_origin_relation(self):
        self.prepare()
        prepared = self.transport.receipt('operation-1')
        self.target.contribute('private source body', scopes=['topic:a'],
                               record_id=prepared['target_record_id'], kind='import', relations=[])
        with self.assertRaises(TransferError):
            self.transport.accept('operation-1', self.source, self.target)
        self.assertEqual(self.transport.receipt('operation-1')['state'], 'failed')

    def test_recovery_rejects_other_contributor_even_with_spoofed_author(self):
        self.prepare()
        prepared = self.transport.receipt('operation-1')
        other = self.target_store.session('other-contributor')
        other.contribute('private source body', scopes=['topic:a'],
                         record_id=prepared['target_record_id'], kind='import', author='owner',
                         relations=[{'predicate': 'derived_from', 'target': self.ref.to_dict()}])
        with self.assertRaises(TransferError):
            self.transport.accept('operation-1', self.source, self.target)
        self.assertEqual(self.transport.receipt('operation-1')['state'], 'failed')

    def test_changed_bytes_rejected_even_after_acceptance(self):
        self.prepare('derive', body='approved', approved_digest=digest('approved'))
        self.transport.accept('operation-1', self.source, self.target)
        with self.assertRaises(TransferError):
            self.transport.accept('operation-1', self.source, self.target,
                                  prepared_body='replacement')


if __name__ == '__main__':
    unittest.main()
