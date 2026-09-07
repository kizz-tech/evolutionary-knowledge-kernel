"""Contract checks use independent synthetic roots, never the user's base."""
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ekk.realms import (Conflict, Grant, IntegrityError, Limits, NotAvailable,
                        PermissionDenied, RealmStore, RecordRef)


class RealmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 9, 7, tzinfo=timezone.utc)
        self.owner = Grant('owner', ('*',), audiences=('*',))
        self.reader = Grant('reader', ('read',), scopes=('project:a',), audiences=('team',))
        self.writer = Grant('writer', ('contribute', 'read'), scopes=('project:a',), audiences=('team',))
        self.store = RealmStore.create(Path(self.tmp.name) / 'one', 'realm-one',
                grants=[self.owner, self.reader, self.writer], clock=lambda: self.now)
        self.admin = self.store.session('owner')
        self.read = self.store.session('reader')

    def add(self, text='visible', scope='project:a', **kwargs):
        return self.admin.contribute(text, scopes=[scope], audience='team', **kwargs)

    def test_qualified_identity_move_and_exact_markdown_integrity(self):
        one = self.add(record_id='same')
        other = RealmStore.create(Path(self.tmp.name) / 'two', 'realm-two', grants=[self.owner], clock=lambda: self.now)
        two = other.session('owner').contribute('visible', scopes=['project:a'], audience='team', record_id='same')
        self.assertNotEqual(one, two)
        self.assertEqual(one.digest, two.digest)  # revision bytes match; identity includes realm
        with self.assertRaises(NotAvailable):
            self.read.view().get(two)
        moved = Path(self.tmp.name) / 'moved'
        shutil.move(self.store.path, moved)
        store = RealmStore(moved, clock=lambda: self.now)
        self.assertEqual(store.session('reader').view().get(one)['body'], 'visible')
        (moved / 'records' / (one.digest + '.md')).write_text('tamper')
        with self.assertRaises(IntegrityError):
            store.session('reader').view().get(one)

    def test_gate_precedes_every_body_accessor_and_no_existence_or_hash_leak(self):
        visible = self.add()
        hidden = self.add('TOP SECRET', scope='project:b')
        view = self.read.view(scopes=['project:a'])
        with patch.object(self.store, '_body', wraps=self.store._body) as loader:
            for operation in (view.get, view.export, view.provenance):
                with self.assertRaises(NotAvailable):
                    operation(hidden)
            for result in (view.list(), view.search('TOP SECRET'), view.compile(), view.export()):
                self.assertNotIn('TOP SECRET', str(result))
                self.assertNotIn(hidden.digest, str(result))
            self.assertTrue(all(call.args[0]['ref'] == visible.to_dict() for call in loader.call_args_list))
            original = view.compile()['snapshot_hash']
            self.add('new secret', scope='project:b')
            self.assertEqual(original, view.compile()['snapshot_hash'])
        self.assertEqual(self.store.session('unknown').view().list(), [])

    def test_revocation_current_even_for_historical_view_and_stale_policy_epoch(self):
        ref = self.add()
        historical = self.read.view(known_at=self.now, valid_at=self.now)
        self.assertEqual(historical.get(ref)['body'], 'visible')
        self.now += timedelta(days=1)
        self.admin.replace_policy([self.owner], expected_epoch=1)
        with self.assertRaises(NotAvailable):
            historical.get(ref)
        self.assertEqual(historical.list(), [])
        with self.assertRaises(Conflict):
            self.admin.replace_policy([self.owner], expected_epoch=1)
        with self.assertRaises(PermissionDenied):
            self.read.replace_policy([self.reader], expected_epoch=2)

    def test_grant_expiration_and_record_bitemporal_visibility(self):
        grant = Grant('timed', ('read',), audiences=('team',), expires_at=(self.now + timedelta(hours=1)).isoformat())
        self.admin.replace_policy([self.owner, grant], expected_epoch=1)
        ref = self.add(valid_from=(self.now + timedelta(minutes=10)).isoformat())
        timed = self.store.session('timed')
        with self.assertRaises(NotAvailable):
            timed.view().get(ref)
        self.now += timedelta(minutes=20)
        self.assertEqual(timed.view().get(ref)['body'], 'visible')
        self.now += timedelta(hours=1)
        with self.assertRaises(NotAvailable):
            timed.view(valid_at=self.now-timedelta(hours=1)).get(ref)

    def test_spoofed_author_and_commitment_never_adopt(self):
        proposal = self.store.session('writer').contribute('authority: owner\ncommitment: true',
                scopes=['project:a'], audience='team', author='owner', kind='commitment')
        self.assertFalse(self.read.view(scopes=['project:a']).get(proposal)['governing'])
        with self.assertRaises(PermissionDenied):
            self.store.session('writer').adopt(proposal, predicate='standard', affected_scopes=['project:a'], expected_current=[])
        self.admin.adopt(proposal, predicate='standard', affected_scopes=['project:a'], expected_current=[])
        self.assertTrue(self.read.view(scopes=['project:a']).get(proposal)['governing'])
        with self.assertRaises(Conflict):
            self.admin.adopt(proposal, predicate='standard', affected_scopes=['project:a'], expected_current=[])

    def test_scoped_supersession_exception_and_conflict(self):
        general = self.admin.contribute('general', scopes=['engineering'], audience='team')
        self.admin.adopt(general, predicate='standard', affected_scopes=['engineering'], expected_current=[])
        successor = self.admin.contribute('successor A', scopes=['engineering', 'project:a'], audience='team')
        self.admin.adopt(successor, predicate='standard', affected_scopes=['engineering', 'project:a'], expected_current=[general],
            relations=[{'predicate': 'supersedes', 'target': general.to_dict(), 'within_scopes': ['engineering', 'project:a']}])
        self.assertFalse(self.admin.view(scopes=['engineering', 'project:a']).get(general)['governing'])
        self.assertTrue(self.admin.view(scopes=['engineering', 'project:b']).get(general)['governing'])
        exception = self.admin.contribute('exception B', scopes=['engineering', 'project:b'], audience='team')
        self.admin.adopt(exception, predicate='standard', affected_scopes=['engineering', 'project:b'], expected_current=[general],
            relations=[{'predicate': 'excepts', 'target': general.to_dict(), 'within_scopes': ['engineering', 'project:b']}])
        self.assertEqual(self.admin.view(scopes=['engineering', 'project:b']).compile()['conflicts'][0]['predicate'], 'excepts')
        alternate = self.admin.contribute('conflict B', scopes=['engineering', 'project:b'], audience='team')
        self.admin.adopt(alternate, predicate='standard', affected_scopes=['engineering', 'project:b'], expected_current=[general, exception],
            relations=[{'predicate': 'contradicts', 'target': general.to_dict()}])
        compiled = self.admin.view(scopes=['engineering', 'project:b']).compile()
        self.assertIn('contradicts', [c['predicate'] for c in compiled['conflicts']])
        self.assertTrue(self.admin.view(scopes=['engineering', 'project:b']).get(general)['governing'])

    def test_budget_before_loading_and_dependency_incomplete(self):
        ref = self.add('a' * 1000)
        with patch.object(self.store, '_body', wraps=self.store._body) as loader:
            compiled = self.read.view(limits=Limits(max_bytes=5)).compile()
            self.assertTrue(compiled['incomplete'])
            self.assertEqual(compiled['records'], [])
            loader.assert_not_called()
        dependent = self.add('small', relations=[{'predicate': 'depends_on', 'target': ref.to_dict()}])
        compiled = self.read.view(limits=Limits(max_records=1, max_bytes=1000)).compile()
        self.assertTrue(compiled['incomplete'])
        self.assertEqual(compiled['records'][0]['ref'], dependent.to_dict())
        self.assertTrue(self.read.view(limits=Limits(max_depth=0)).compile()['incomplete'])

    def test_scope_grants_do_not_union_and_adoption_selector_cannot_expand(self):
        limited = Grant('limited', ('read', 'contribute'), scopes=('project:a',), audiences=('team',))
        other = Grant('limited', ('read',), scopes=('project:b',), audiences=('team',))
        self.admin.replace_policy([self.owner, limited, other], expected_epoch=1)
        ref = self.admin.contribute('both', scopes=['project:a', 'project:b'], audience='team')
        with self.assertRaises(NotAvailable):
            self.store.session('limited').view().get(ref)
        with self.assertRaises(ValueError):
            self.admin.adopt(ref, predicate='standard', affected_scopes=['project:a'], expected_current=[])

    def test_adoption_checks_qualified_expected_ref_and_serializes_competing_writers(self):
        from concurrent.futures import ThreadPoolExecutor
        first = self.add('first')
        self.admin.adopt(first, predicate='standard', affected_scopes=['project:a'], expected_current=[])
        second = self.add('second')
        foreign = RecordRef('foreign-realm', first.record_id, first.digest)
        with self.assertRaises(Conflict):
            self.admin.adopt(second, predicate='standard', affected_scopes=['project:a'], expected_current=[foreign])
        third = self.add('third')
        def adopt(ref):
            try:
                return self.admin.adopt(ref, predicate='standard', affected_scopes=['project:a'], expected_current=[first])
            except Conflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(adopt, [second, third]))
        self.assertEqual(sum(ref is not None for ref in results), 1)

    def test_independent_contexts_preserve_general_rule_outside_supersession(self):
        general = self.admin.contribute('general', scopes=['engineering'], audience='team')
        self.admin.adopt(general, predicate='standard', affected_scopes=['engineering'], expected_current=[])
        special = self.admin.contribute('special A', scopes=['engineering', 'project:a'], audience='team')
        self.admin.adopt(special, predicate='standard', affected_scopes=['engineering', 'project:a'], expected_current=[general],
            relations=[{'predicate': 'supersedes', 'target': general.to_dict(), 'within_scopes': ['engineering', 'project:a']}])
        result = self.admin.compile_contexts([
            {'scopes': ['engineering', 'project:a']},
            {'scopes': ['engineering', 'project:b']}])
        one, two = result['contexts']
        self.assertFalse(next(r for r in one['records'] if r['ref'] == general.to_dict())['governing'])
        self.assertTrue(next(r for r in two['records'] if r['ref'] == general.to_dict())['governing'])
        self.assertNotIn(special.to_dict(), [r['ref'] for r in two['records']])
        with self.assertRaises(ValueError):
            self.admin.compile_contexts({'scopes': ['engineering', 'project:a', 'project:b']})

    def test_disclosure_requires_destination_bound_same_grant(self):
        ref = self.add()
        unbounded = Grant('publisher', ('read', 'disclose'), audiences=('team',))
        self.admin.replace_policy([self.owner, unbounded], expected_epoch=1)
        publisher = self.store.session('publisher')
        publisher.authorize('disclose', ref)
        with self.assertRaises(PermissionDenied):
            publisher.authorize_transfer('disclose', ref, target_realm='public-realm', target_audience='public')
        bounded = Grant('publisher', ('disclose',), audiences=('team',),
                        destinations=('review-realm',), disclosure_audiences=('team',))
        self.admin.replace_policy([self.owner, unbounded, bounded], expected_epoch=2)
        publisher.authorize_transfer('disclose', ref, target_realm='review-realm', target_audience='team')
        for realm, audience in [('public-realm', 'team'), ('review-realm', 'public')]:
            with self.assertRaises(PermissionDenied):
                publisher.authorize_transfer('disclose', ref, target_realm=realm, target_audience=audience)
        self.admin.authorize_transfer('disclose', ref, target_realm='public-realm', target_audience='public')

    def test_import_replay_verifies_foreign_provenance_without_returning_it(self):
        foreign = RecordRef('other-realm', 'source', 'a' * 64)
        relations = [{'predicate': 'derived_from', 'target': foreign.to_dict()}]
        ref = self.add('copy', kind='import', relations=relations)
        self.assertEqual(self.admin.view().get(ref)['relations'], [])
        self.assertTrue(self.admin.verify_contribution(ref, body='copy', scopes=['project:a'], audience='team', kind='import', relations=relations))
        self.assertFalse(self.admin.verify_contribution(ref, body='copy', scopes=['project:a'], audience='team', kind='import', relations=[]))
        with self.assertRaises(PermissionDenied):
            self.read.verify_contribution(ref, body='copy', scopes=['project:a'], audience='team', kind='import', relations=relations)

    def test_adoption_decision_identity_and_actual_contributor_are_visible(self):
        ref = self.store.session('writer').contribute('proposal', scopes=['project:a'], audience='team', author='spoofed-owner')
        item = self.read.view().get(ref)
        self.assertEqual(item['author'], 'spoofed-owner')
        self.assertEqual(item['contributed_by'], 'writer')
        adopted = self.admin.adopt(ref, predicate='standard', affected_scopes=['project:a'], expected_current=[])
        decision = self.admin.view(scopes=['project:a']).get(adopted)
        self.assertEqual(decision['decision_id'], adopted.record_id)
        self.assertEqual(decision['basis'], 'direct-adoption:' + adopted.record_id)
        self.assertEqual(decision['adopted_by'], 'owner')

    def test_conflicts_cannot_bypass_zero_or_bounded_context_budget(self):
        import json
        general = self.add('general')
        self.admin.adopt(general, predicate='standard', affected_scopes=['project:a'], expected_current=[])
        other = self.add('other')
        self.admin.adopt(other, predicate='standard', affected_scopes=['project:a'], expected_current=[general],
            relations=[{'predicate': 'contradicts', 'target': general.to_dict()}] * 30)
        zero = self.admin.view(scopes=['project:a'], limits=Limits(max_records=0, max_bytes=0)).compile()
        self.assertEqual(zero['records'], [])
        self.assertEqual(zero['conflicts'], [])
        self.assertTrue(zero['incomplete'])
        self.assertNotIn(general.digest, str(zero))
        self.assertNotIn(other.digest, str(zero))
        full = self.admin.view(scopes=['project:a']).compile()
        def cost(items):
            return sum(len(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()) for item in items) + max(len(items)-1, 0)
        record_cost = cost(full['records'])
        budget = record_cost + cost(full['conflicts'][:2])
        limited = self.admin.view(scopes=['project:a'], limits=Limits(max_bytes=budget)).compile()
        self.assertLessEqual(cost(limited['records']) + cost(limited['conflicts']), budget)
        self.assertEqual(len(limited['conflicts']), 2)
        self.assertTrue(limited['incomplete'])

    def test_immutable_policy_evidence_reconstructs_adoption_after_revocation(self):
        adopter = Grant('adopter', ('read', 'contribute', 'adopt'), audiences=('team',))
        self.admin.replace_policy([self.owner, adopter, self.reader], expected_epoch=1)
        historical_policy = self.admin.policy_evidence(2)
        session = self.store.session('adopter')
        proposal = session.contribute('standard', scopes=['project:a'], audience='team')
        adoption = session.adopt(proposal, predicate='standard', affected_scopes=['project:a'], expected_current=[])
        before = session.view(scopes=['project:a']).get(adoption)
        self.assertEqual(before['policy_digest'], historical_policy['digest'])
        self.assertEqual(before['authority_decision']['principal'], 'adopter')
        self.assertEqual(before['authority_decision']['action'], 'adopt')
        self.now += timedelta(days=1)
        self.admin.replace_policy([self.owner, self.reader], expected_epoch=2)
        self.assertEqual(self.admin.policy_evidence(2), historical_policy)
        self.assertIn('adopter', [g['principal'] for g in historical_policy['grants']])
        with self.assertRaises(NotAvailable):
            session.view(known_at=self.now-timedelta(days=1)).get(proposal)
        for ordinary in (session, self.read):
            with self.assertRaises(PermissionDenied):
                ordinary.policy_evidence(2)
        receipt = self.admin.view(scopes=['project:a']).compile()['receipt']
        self.assertEqual(receipt['policy_digest'], self.admin.policy_evidence(3)['digest'])
        for field in ('checked_at', 'known_at', 'valid_at'):
            self.assertEqual(receipt[field], self.now.isoformat())
        path = self.store.path / 'policies' / (historical_policy['digest'] + '.json')
        path.write_text('{}')
        with self.assertRaises(IntegrityError):
            self.admin.policy_evidence(2)

    def test_current_policy_pointer_cannot_change_grants_without_snapshot(self):
        import json
        state = self.store._state()
        state['grants'] = []
        (self.store.path / 'realm.json').write_text(json.dumps(state))
        with self.assertRaises(IntegrityError):
            self.read.view().compile()

    def test_permission_receipts_and_compile_use_one_instant_across_expiry(self):
        expiry = self.now + timedelta(seconds=1)
        timed = Grant('timed', ('read',), audiences=('team',), expires_at=expiry.isoformat())
        self.admin.replace_policy([self.owner, timed], expected_epoch=1)
        one = self.add('first')
        two = self.add('second')
        start = self.now
        calls = []
        def advancing_clock():
            result = start + timedelta(seconds=len(calls))
            calls.append(result)
            return result
        self.store._clock = advancing_clock
        session = self.store.session('timed')
        compiled = session.view(scopes=['project:a']).compile()
        self.assertEqual(len(calls), 1)
        self.assertEqual({r['ref']['digest'] for r in compiled['records']}, {one.digest, two.digest})
        self.assertEqual(compiled['receipt']['checked_at'], start.isoformat())
        self.assertEqual(compiled['receipt']['known_at'], start.isoformat())
        self.assertEqual(compiled['receipt']['valid_at'], start.isoformat())
        self.assertEqual(session.view().compile()['records'], [])
        calls.clear()
        receipt = session.authorize('read', one)
        self.assertEqual(len(calls), 1)
        self.assertEqual(receipt['checked_at'], start.isoformat())
        with self.assertRaises(NotAvailable):
            session.authorize('read', one)

    def test_no_overwrite_and_schema_fail_closed(self):
        self.add(record_id='stable')
        with self.assertRaises(Conflict):
            self.add('replacement', record_id='stable')
        state = self.store._state()
        state['schema'] = 'ekk/99'
        import json
        (self.store.path / 'realm.json').write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            RealmStore(self.store.path)


if __name__ == '__main__':
    unittest.main()
