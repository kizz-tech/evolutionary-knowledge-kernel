from copy import deepcopy
import json
import unittest

from ekk.adapters.context_display import brief_context, compact_context


def row(key, body, *, kind='note', selection='ranked', discovery=None, **flags):
    metadata = {'id': key, 'kind': kind, 'title': key.title(), 'scope': ['context:one'], 'revision': 1,
                'created_at': '2026-09-20T10:00:00Z'}
    record = {'id': key, 'metadata': metadata, 'body': body, 'digest': key[0] * 64,
              'governs': False, 'mandatory': False, 'source_content': kind == 'source', 'inert': False,
              'serialization_warnings': [], 'selection': selection, **flags}
    if discovery:
        record['discovery'] = discovery
    return record


def fixture():
    records = [
        row('rule', 'Exact restriction that must stay whole. ' * 40, kind='policy', selection='required',
            governs=True, mandatory=True),
        row('match', 'Payout minimum is 3000 RUB.\n\n' + 'Long outcome. ' * 200, kind='outcome', grounds=1,
            discovery={'score': 3.2, 'matched_terms': ['payout'], 'excerpt': 'outcome. Long outcome.'}),
        row('ground', 'Ground of the match.', selection='dependency'),
        row('capture', '', kind='source', discovery={'score': 1.0, 'matched_terms': ['x'], 'excerpt': None}),
    ]
    return context(records, omitted=['note:a', 'note:b'])


def context(records, *, omitted=(), **fields):
    return {'schema': 'ekk.context/0.1', 'blocked': False, 'scopes': ['context:one'], 'task': 'payout',
            'records': records, 'conflicts': [], 'unknowns': [], 'warnings': [],
            'insights': {'incomplete': False},
            'manifest': {'realm_id': 'realm:one', 'incomplete': bool(omitted), 'omitted': list(omitted),
                         'snapshots': [{'realm_id': 'realm:one', 'revision': 'current'}]}, **fields}


class ContextDisplayTests(unittest.TestCase):
    def test_agent_view_keeps_required_reading_and_summarizes_the_rest(self):
        full = fixture()
        original = deepcopy(full)
        view = brief_context(full)
        self.assertEqual(full, original)
        self.assertEqual(view['schema'], 'ekk.context-brief/0.3')
        self.assertEqual(view['required_reading'][0]['body'], full['records'][0]['body'])
        # A ground of an optional item is counted on that item, not listed.
        self.assertEqual([item['ref']['id'] for item in view['items']], ['match'])
        match = view['items'][0]
        self.assertEqual((match['summary'], match['why'], match['grounds']),
                         ('Payout minimum is 3000 RUB.', 'matches: payout', 1))
        self.assertEqual(match['ref'], {'realm': 'realm:one', 'id': 'match', 'revision': 1, 'digest': 'sha256:' + 'm' * 64})
        # The source without readable text adds only a title, so it is counted, not shown.
        self.assertEqual(view['omitted_count'], 3)
        self.assertEqual(view['incomplete_reasons'], ['optional_reading_left_out'])
        self.assertEqual(view['next'], ['ekk fetch --id ID', 'ekk read-source --id ID',
                                        'omit --brief for the full projection'])
        self.assertFalse({'authority', 'budget_note', 'read_more'} & set(view))
        self.assertEqual(compact_context(full), view)

    def test_display_target_bounds_optional_items_only(self):
        view = brief_context(fixture(), budget=100)
        self.assertEqual(view['required_reading'][0]['body'], fixture()['records'][0]['body'])
        self.assertEqual(view['items'], [])
        self.assertEqual(view['omitted_count'], 4)
        self.assertLess(len(json.dumps(brief_context(fixture()), ensure_ascii=False)),
                        len(json.dumps(fixture(), ensure_ascii=False)))

    def test_pinned_rows_stay_listed_by_title(self):
        view = brief_context(context([row('pinned', 'Pinned body.', selection='required', grounds=2)]))
        self.assertEqual(view['items'], [{'title': 'Pinned', 'kind': 'note', 'date': '2026-09-20', 'id': 'pinned',
                                          'why': 'pinned for this workspace or a ground of a governing record'}])

    def test_summary_is_the_first_prose_paragraph_of_the_record(self):
        body = ('---\ntitle: Imported decision\nstatus: accepted\n---\n\n# Decision 12\n\n## Context\n\n'
                '- [x] checklist first\n\n```\ncode sample\n```\n\nPartner payouts\nstart at 3000 RUB.\n\n'
                'A later paragraph.')
        listed = '# Steps\n\n- first step\n- second step\n'
        long_body = 'First sentence is here. ' + 'Filler sentence number two goes on. ' * 30
        records = [row('a', body, discovery={'matched_terms': ['later'], 'excerpt': 'A later paragraph.'}),
                   row('b', listed), row('c', long_body), row('d', long_body),
                   row('e', 'x' * 900),
                   row('f', '', kind='source', discovery={'matched_terms': ['needle'], 'excerpt': 'asset needle text'})]
        items = {item['ref']['id']: item for item in brief_context(context(records), budget=100000)['items']}
        self.assertEqual(items['a']['summary'], 'Partner payouts start at 3000 RUB.')
        self.assertEqual(items['b']['summary'], '- first step - second step')
        # The first two ranked items may use 600 characters, later ones 400.
        for key, limit in (('c', 400), ('d', 400), ('e', 400)):
            self.assertLessEqual(len(items[key]['summary']), limit)
        self.assertTrue(items['c']['summary'].endswith('goes on.'))
        self.assertGreater(len(items['c']['summary']), 300)
        self.assertTrue(items['e']['summary'].endswith('…'))
        self.assertEqual(items['f']['summary'], 'asset needle text')
        first = brief_context(context([row('c', long_body)]))['items'][0]['summary']
        self.assertTrue(400 < len(first) <= 600 and first.endswith('goes on.'))

    def test_reason_names_at_most_four_matched_terms(self):
        terms = ['payout', 'minimum', 'partner', 'tariff', 'plan', 'limit']
        view = brief_context(context([row('a', 'Body.', discovery={'matched_terms': terms, 'excerpt': 'Body.'})]))
        self.assertEqual(view['items'][0]['why'], 'matches: payout, minimum, partner, tariff')

    def test_items_carry_supersession_tier_and_preference(self):
        ref = lambda key: {'id': key, 'title': key.title(), 'revision': 1, 'digest': 'sha256:' + key[0] * 64}
        head = row('head', 'Use plan B.', replaces=[ref('old'), ref('older'), ref('p'), ref('q')],
                   discovery={'score': 1.0, 'matched_terms': [], 'excerpt': None})
        head['metadata']['preference'] = {'area': 'billing'}
        old = row('old', 'Use plan A.', selection='related', superseded_by=[ref('head')], tier='archive')
        successor = row('next', 'Use plan C.', selection='successor', replaces=[ref('old')])
        items = {item['ref']['id']: item for item in brief_context(context([head, old, successor]))['items']}
        self.assertEqual(items['head']['kind'], 'preference')
        self.assertEqual(items['head']['why'], 'current version of matching material')
        self.assertEqual(items['head']['replaces'], [{'id': 'old', 'title': 'Old'}, {'id': 'older', 'title': 'Older'},
                                                     {'id': 'p', 'title': 'P'}])
        self.assertEqual(items['old']['superseded_by'], [{'id': 'head', 'title': 'Head'}])
        self.assertEqual(items['old']['tier'], 'archive')
        self.assertNotIn('tier', items['head'])
        self.assertEqual(items['next']['why'], 'replaces selected material')

    def test_a_replacement_claim_is_worded_as_a_claim_and_grounds_are_addressable(self):
        ref = lambda key: {'id': key, 'title': key.title(), 'revision': 1, 'digest': 'sha256:' + key[0] * 64}
        claimant = row('claimant', 'Proceed freely.', claims_to_replace=[ref('rule')],
                       discovery={'score': 0.0, 'matched_terms': [], 'excerpt': None})
        matching = row('matching', 'Payout is free.', claims_to_replace=[ref('rule')], grounds=4,
                       ground_refs=[ref('g'), ref('h'), ref('i')],
                       discovery={'score': 1.0, 'matched_terms': ['payout'], 'excerpt': None})
        target = row('target', 'Accepted note.', replacement_claimed_by=[ref('claimant')])
        late = row('late', 'Later match.', discovery={'score': 0.5, 'matched_terms': ['payout'], 'excerpt': None})
        view = brief_context(context([late, claimant, matching, target]))
        # No special group: a claimant keeps its place in relevance order.
        self.assertEqual(['late', 'claimant', 'matching', 'target'], [item['ref']['id'] for item in view['items']])
        items = {item['ref']['id']: item for item in view['items']}
        self.assertEqual('unaccepted record that claims to replace an accepted one', items['claimant']['why'])
        self.assertEqual('matches: payout', items['matching']['why'])
        self.assertEqual([{'id': 'rule', 'title': 'Rule'}], items['claimant']['claims_to_replace'])
        self.assertEqual([{'id': 'claimant', 'title': 'Claimant'}], items['target']['replacement_claimed_by'])
        self.assertEqual((4, [{'id': 'g', 'title': 'G'}, {'id': 'h', 'title': 'H'}, {'id': 'i', 'title': 'I'}]),
                         (items['matching']['grounds'], items['matching']['ground_refs']))

    def test_incomplete_reports_required_gaps_only(self):
        optional = brief_context(fixture())
        self.assertFalse(optional['incomplete'])
        self.assertEqual((optional['incomplete_reasons'], optional['omitted_count']), (['optional_reading_left_out'], 3))
        display_only = brief_context(context([row('a', 'One.'), row('b', 'Two.')]), budget=1)
        self.assertEqual((display_only['incomplete'], display_only['incomplete_reasons'], display_only['omitted_count']),
                         (False, ['optional_reading_left_out'], 2))
        for change, reason in (({'blocked': True}, 'blocked'), ({'unknowns': ['gap']}, 'unknowns'),
                               ({'warnings': ['unpinned']}, 'reading_warnings'),
                               ({'insights': {'incomplete': True}}, 'challenges_not_shown'),
                               ({'insights': {'incomplete': True, 'relations_incomplete': True}}, 'challenges_not_shown')):
            with self.subTest(reason=reason):
                view = brief_context({**fixture(), **change})
                self.assertTrue(view['incomplete'])
                self.assertEqual(view['incomplete_reasons'], [reason, 'optional_reading_left_out'])
        # Statement summaries cut by the insight budget hide no challenge.
        summaries = brief_context({**fixture(), 'insights': {'incomplete': True, 'relations_incomplete': False}})
        self.assertEqual((False, ['optional_reading_left_out']), (summaries['incomplete'], summaries['incomplete_reasons']))
        # A governing record left out by the record budget is a required gap, named for fetching.
        base = fixture()
        for entries in ([{'id': 'decision:a', 'title': 'Decision A'}], ['decision:a']):
            dropped = brief_context({**base, 'manifest': {**base['manifest'], 'omitted_governing': entries}})
            self.assertEqual((True, ['governing_left_out', 'optional_reading_left_out']),
                             (dropped['incomplete'], dropped['incomplete_reasons']))
            self.assertEqual([{'id': 'decision:a', 'title': entries[0]['title'] if isinstance(entries[0], dict) else ''}],
                             dropped['governing_left_out'])
        self.assertNotIn('governing_left_out', brief_context(base))

    def test_federation_and_unbound(self):
        child = fixture()
        full = {'schema': 'ekk.federated-context/0.1', 'atomic_across_realms': False, 'contexts': [child, child]}
        view = compact_context(full)
        self.assertEqual(view['schema'], 'ekk.federated-brief/0.2')
        self.assertFalse(view['atomic_across_realms'])
        self.assertEqual(view['contexts'], [brief_context(child), brief_context(child)])
        unbound = {'status': 'unbound', 'context': None, 'instruction': 'No access inferred.'}
        self.assertEqual(compact_context(unbound), unbound)


if __name__ == '__main__':
    unittest.main()
