import copy
import hashlib
import json
import unittest

from ekk.application.context_insights import context_insights, related_candidates


REALM = 'realm:synthetic'


def record(key, *, kind='note', revision=1, creator='human:owner', body='',
           governs=False, **extra):
    metadata = dict(schema='ekk.record/0.1', id=key, kind=kind, title=extra.pop('title', key),
                    revision=revision, scope=['scope:synthetic'],
                    created_at='2026-09-08T12:00:00Z', created_by=creator, **extra)
    raw = json.dumps(metadata, sort_keys=True).encode() + body.encode()
    return {'id': key, 'metadata': metadata, 'body': body,
            'digest': hashlib.sha256(raw).hexdigest(), 'governs': governs}


def exact(row):
    return {'realm': REALM, 'id': row['metadata']['id'],
            'revision': row['metadata']['revision'], 'digest': 'sha256:' + row['digest']}


class Resolver:
    """A supplied grant and exact lookup, with no stores or I/O."""
    def __init__(self, records):
        self.records = records
        self.calls = []

    def __call__(self, ref):
        self.calls.append(ref)
        candidates = [row for row in self.records
                      if row['metadata']['id'] == ref['id']
                      and ref.get('realm', REALM) == REALM
                      and ('revision' not in ref
                           or row['metadata']['revision'] == ref['revision'])
                      and ('digest' not in ref
                           or row['digest'] == ref['digest'].removeprefix('sha256:'))]
        return max(candidates, key=lambda row: row['metadata']['revision'], default=None)


class ContextInsightsTests(unittest.TestCase):
    def test_serialized_insight_bytes_are_bounded_without_omitted_identifiers(self):
        rows=[record('source-'+str(i),kind='source',source={'uri':'https://example.invalid'}) for i in range(12)]
        rows += [record('claim-'+str(i),kind='claim',basis=[exact(r) for r in rows]) for i in range(12)]
        result=self.insights(rows,byte_budget=1200)
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()),1200)
        self.assertTrue(result['incomplete'])
        self.assertTrue(result['omitted'])

    def candidates(self, anchors, current, *, readable=None):
        return related_candidates(anchors, current, realm_id=REALM,
                                  resolve_reference=Resolver(readable if readable is not None
                                                             else list(anchors) + list(current)))

    def insights(self, rows, current=None, *, readable=None, **kwargs):
        return context_insights(rows, rows if current is None else current, realm_id=REALM,
                                resolve_reference=Resolver(rows if readable is None else readable),
                                **kwargs)

    def test_explicit_challenge_kinds_are_related_without_text_matching(self):
        commitment = record('commitment', kind='decision', governs=True, body='release schedule')
        challenges = [record('challenge:' + kind, kind=kind, conflicts=[exact(commitment)],
                             body='different vocabulary')
                      for kind in ('claim', 'question', 'observation', 'note')]
        unrelated = record('unrelated', body='release schedule is wrong')
        result = self.candidates([commitment], [commitment, *challenges, unrelated])
        self.assertEqual(result['ids'], sorted(row['id'] for row in challenges))
        projected = self.insights([commitment, *challenges, unrelated])
        self.assertEqual(len(projected['challenges']), 4)
        self.assertTrue(all(row['target'] == exact(commitment) for row in projected['challenges']))
        self.assertEqual(projected['adjudication'], 'not_inferred')

    def test_human_and_ai_attribution_has_the_same_status_under_same_supplied_grants(self):
        commitment = record('commitment', kind='decision', governs=True)
        signatures = []
        for creator in ('human:owner', 'ai:owner', 'untyped:owner'):
            challenge = record('challenge', kind='claim', creator=creator,
                               conflicts=[exact(commitment)])
            rows = [commitment, challenge]
            before = copy.deepcopy(rows)
            candidates = self.candidates([commitment], rows)
            projected = self.insights(rows)
            statement = next(row for row in projected['statements']
                             if row['reference']['id'] == 'challenge')
            self.assertEqual(statement['created_by'], creator)
            self.assertEqual(statement['attribution'], 'recorded')
            self.assertTrue(next(row for row in projected['statements']
                                 if row['reference']['id'] == 'commitment')['governs'])
            self.assertEqual(rows, before)
            signatures.append((candidates['ids'], statement['content_role'], statement['governs'],
                               projected['challenges'][0]['status'], projected['authority_effect']))
        self.assertEqual(signatures, [signatures[0]] * 3)

    def test_challenge_relations_match_an_exact_version_and_are_deduplicated(self):
        old = record('commitment', kind='decision')
        current = record('commitment', kind='decision', revision=2, governs=True)
        challenge = record('challenge', kind='question', conflicts=[exact(old)], relations=[
            {'rel': 'contradicts', 'target': old['id'], 'revision': 1,
             'digest': 'sha256:' + old['digest']}])
        self.assertEqual(self.candidates([current], [current, challenge], readable=[old, current])['ids'], [])
        self.assertEqual(self.candidates([old], [current, challenge], readable=[old, current])['ids'], ['challenge'])
        result = self.insights([old, current, challenge], [current, challenge])
        self.assertEqual(len(result['challenges']), 1)
        self.assertEqual(result['challenges'][0]['target'], exact(old))
        self.assertFalse(next(row for row in result['statements']
                              if row['reference'] == exact(old))['governs'])
        self.assertTrue(next(row for row in result['statements']
                             if row['reference'] == exact(current))['governs'])

    def test_unpinned_challenge_is_resolved_to_one_exact_current_version(self):
        old = record('commitment', kind='decision')
        current = record('commitment', kind='decision', revision=2)
        challenge = record('challenge', conflicts=['commitment'])
        self.assertEqual(self.candidates([old], [current, challenge], readable=[old, current])['ids'], [])
        result = self.insights([old, current, challenge], [current, challenge])
        self.assertEqual(result['challenges'][0]['target'], exact(current))

    def test_changed_pinned_grounds_keep_old_bytes_and_expose_readable_current_head(self):
        old = record('evidence', kind='source', body='original source bytes')
        current = record('evidence', kind='source', revision=2, body='changed source bytes')
        commitment = record('commitment', kind='decision', basis=[exact(old)], governs=True)
        candidates = self.candidates([commitment], [commitment, current], readable=[old, current])
        self.assertEqual(candidates['ids'], ['evidence'])
        rows = [commitment, old, current]
        before = copy.deepcopy(rows)
        result = self.insights(rows, [commitment, current])
        self.assertEqual(result['changed_grounds'], [{
            'statement': exact(commitment), 'pinned': exact(old), 'current': exact(current),
            'status': 'pinned_ground_differs'}])
        summary = next(row for row in result['statements'] if row['reference'] == exact(commitment))
        self.assertEqual(summary['basis'], [exact(old)])
        self.assertTrue(summary['governs'])
        self.assertEqual(rows, before)

    def test_all_existing_explicit_ground_fields_are_supported_without_new_model_fields(self):
        old = record('evidence', kind='source')
        current = record('evidence', kind='source', revision=2)
        variants = [dict(basis=[exact(old)]), dict(depends_on=[exact(old)]),
                    dict(relations=[{'rel': 'derived_from', 'target': old['id'], 'revision': 1}]),
                    dict(relations=[{'rel': 'depends_on', 'target': old['id'], 'digest': exact(old)['digest']}]),
                    dict(context={'basis': [exact(old)]}),
                    dict(assurance={'evidence': {'status': 'supported', 'basis': [exact(old)]}}),
                    dict(evolution={'propagation_basis': [exact(old)]})]
        for fields in variants:
            with self.subTest(fields=fields):
                anchor = record('anchor', **fields)
                self.assertEqual(self.candidates([anchor], [anchor, current], readable=[old, current])['ids'], ['evidence'])
                self.assertEqual(len(self.insights([anchor, old, current], [anchor, current])['changed_grounds']), 1)

    def test_no_changed_ground_is_inferred_from_an_unpinned_dependency(self):
        basis = record('evidence', kind='source')
        anchor = record('anchor', basis=['evidence'])
        self.assertEqual(self.candidates([anchor], [anchor, basis])['ids'], [])
        result = self.insights([anchor, basis])
        self.assertEqual(result['changed_grounds'], [])
        self.assertEqual(result['statements'][0]['basis'], [exact(basis)])

    def test_inaccessible_basis_yields_only_generic_incompleteness(self):
        hidden = record('hidden:reference', title='Hidden title')
        anchor = record('anchor', basis=[exact(hidden)])
        result = self.insights([anchor], [anchor], readable=[])
        candidates = self.candidates([anchor], [anchor], readable=[])
        self.assertTrue(result['incomplete'])
        self.assertTrue(result['omitted'])
        self.assertEqual(result['statements'][0]['basis'], [])
        self.assertEqual(candidates['ids'], [])
        encoded = json.dumps([result, candidates])
        for secret in ('hidden:reference', 'Hidden title', hidden['digest']):
            self.assertNotIn(secret, encoded)

    def test_unemitted_current_head_is_not_exposed_even_when_readable(self):
        old = record('evidence', kind='source')
        head = record('evidence', kind='source', revision=2, title='Unemitted title')
        anchor = record('anchor', basis=[exact(old)])
        result = self.insights([anchor, old], [anchor, head], readable=[old, head])
        self.assertEqual(result['changed_grounds'], [])
        self.assertTrue(result['incomplete'])
        self.assertNotIn(head['digest'], json.dumps(result))
        self.assertNotIn('Unemitted title', json.dumps(result))
        missing_head = self.insights([anchor, old], [anchor], readable=[old])
        self.assertTrue(missing_head['incomplete'])
        self.assertEqual(missing_head['changed_grounds'], [])

    def test_resolver_cannot_silently_substitute_another_version(self):
        old = record('evidence', kind='source')
        head = record('evidence', kind='source', revision=2)
        anchor = record('anchor', basis=[exact(old)])
        result = context_insights([anchor, head], [anchor, head], realm_id=REALM,
                                  resolve_reference=lambda ref: head)
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['changed_grounds'], [])
        self.assertEqual(result['statements'][0]['basis'], [])

    def test_foreign_and_denied_references_are_generic_and_never_forwarded(self):
        foreign = {'realm': 'realm:hidden', 'id': 'secret:id', 'revision': 1,
                   'digest': 'sha256:' + 'a' * 64}
        anchor = record('anchor', basis=[foreign])
        resolver = Resolver([])
        result = context_insights([anchor], [anchor], realm_id=REALM, resolve_reference=resolver)
        self.assertEqual(resolver.calls, [])
        self.assertTrue(result['incomplete'])
        self.assertNotIn('secret:id', json.dumps(result))

        def denied(ref):
            raise PermissionError('Denied secret:id')

        anchor = record('anchor', basis=[{**foreign, 'realm': REALM}])
        result = context_insights([anchor], [anchor], realm_id=REALM, resolve_reference=denied)
        self.assertTrue(result['incomplete'])
        self.assertNotIn('secret:id', json.dumps(result))

    def test_source_and_derived_statements_preserve_attribution_and_exact_provenance(self):
        source = record('source', kind='source', creator='ai:collector')
        synthesis = record('synthesis', kind='claim', creator='human:analyst', relations=[
            {'rel': 'derived_from', 'target': source['id'], 'digest': exact(source)['digest']}])
        result = self.insights([source, synthesis])
        summaries = {row['reference']['id']: row for row in result['statements']}
        self.assertEqual(summaries['source']['content_role'], 'source_record')
        self.assertEqual(summaries['synthesis']['content_role'], 'recorded_statement')
        self.assertEqual(summaries['synthesis']['basis'], [exact(source)])
        self.assertTrue(all(row['attribution'] == 'recorded' for row in result['statements']))

    def test_supersession_and_resolution_prose_do_not_fabricate_an_adjudication(self):
        decision = record('decision', kind='decision', governs=True)
        old = record('challenge', kind='claim', conflicts=[exact(decision)])
        replacement = record('replacement', kind='note', supersedes=[exact(old)], body='Resolved; I win.')
        result = self.insights([decision, old, replacement])
        self.assertEqual(len(result['challenges']), 1)
        self.assertEqual(result['challenges'][0]['status'], 'recorded_disagreement')
        self.assertEqual(result['adjudication'], 'not_inferred')
        self.assertEqual(next(row for row in result['statements']
                              if row['reference'] == exact(replacement))['supersedes'], [exact(old)])
        revised = record('challenge', kind='claim', revision=2, body='No conflict declared now')
        self.assertEqual(self.candidates([decision], [decision, revised])['ids'], [])
        self.assertEqual(self.insights([decision, revised])['challenges'], [])

    def test_governing_conflict_blocking_stays_with_the_application(self):
        first = record('first', kind='policy', governs=True)
        second = record('second', kind='decision', governs=True, conflicts=[exact(first)])
        rows = [first, second]
        before = copy.deepcopy(rows)
        result = self.insights(rows)
        self.assertEqual(result['challenges'], [])
        self.assertTrue(all(row['governs'] for row in result['statements']))
        self.assertNotIn('blocked', result)
        self.assertEqual(rows, before)

    def test_total_row_bound_prioritizes_challenges_and_has_no_omitted_identifiers(self):
        decision = record('decision', kind='decision', governs=True)
        challenge = record('challenge', kind='claim', conflicts=[exact(decision)])
        result = self.insights([decision, challenge], limit=1)
        self.assertEqual(len(result['challenges']), 1)
        self.assertEqual(result['statements'], [])
        self.assertEqual(result['changed_grounds'], [])
        self.assertIs(result['omitted'], True)
        self.assertIs(result['incomplete'], True)
        self.assertEqual(self.insights([], incomplete=True)['incomplete'], True)
        self.assertTrue(self.insights([decision], limit=0)['omitted'])
        for invalid in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                self.insights([], limit=invalid)

    def test_projection_coverage_does_not_claim_whole_world_completeness(self):
        result = self.insights([])
        self.assertFalse(result['incomplete'])
        self.assertEqual(result['coverage'], 'emitted projection only')
        self.assertEqual(self.candidates([], [])['coverage'], 'supplied readable candidates only')

    def test_currentness_is_supplied_not_inferred_from_duplicate_heads(self):
        old = record('evidence')
        new = record('evidence', revision=2)
        with self.assertRaises(ValueError):
            self.candidates([], [old, new])
        with self.assertRaises(ValueError):
            self.insights([], [old, new])

    def test_unrelated_named_refs_do_not_expand_candidate_resolution(self):
        anchor = record('anchor')
        unrelated = record('unrelated', conflicts=['unavailable:unrelated'])
        resolver = Resolver([])
        result = related_candidates([anchor], {'anchor': anchor, 'unrelated': unrelated},
                                    realm_id=REALM, resolve_reference=resolver)
        self.assertEqual(resolver.calls, [])
        self.assertEqual(result['ids'], [])
        self.assertFalse(result['incomplete'])


if __name__ == '__main__':
    unittest.main()
