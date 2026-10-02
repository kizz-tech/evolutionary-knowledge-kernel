"""Synthetic application contracts for revisable, actor-neutral work context."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import ekk
from ekk.adapters.context_display import brief_context
from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.application import discovery
from ekk.application.discovery import RecordRanker
from ekk.application.workspace import WorkspaceService, work_view
from ekk.model import digest


REALM = 'realm:continuity'
NOW = '2026-09-08T12:00:00Z'


class ContextContinuityTests(unittest.TestCase):
    def test_source_ranking_reads_a_bounded_lead_of_each_asset(self):
        self.source(b'x'*300+b' needle',title='Source descriptor')
        with patch('ekk.application.discovery.ENTRY_SOURCE_LEAD_CHARS',128):
            result=self.app.context(['scope'],task='needle')
        coverage=result['manifest']['source_search']
        self.assertEqual(('bm25',128,1),(coverage['method'],coverage['source_lead_chars'],coverage['partial_assets']))
        self.assertEqual([],result['records'])
        # Lead-limited discovery is declared coverage, not an incomplete projection.
        self.assertFalse(result['manifest']['incomplete'])
        found=self.app.context(['scope'],task='needle')
        self.assertEqual(['Source descriptor'],[row['metadata']['title'] for row in found['records']])
        self.assertEqual(['needle'],found['records'][0]['discovery']['matched_terms'])
        self.assertIn('needle',found['records'][0]['discovery']['excerpt'])

    def test_entry_ranking_prefers_a_focused_record_over_long_generic_text(self):
        focused=self.add('payout-rule','Partner payout minimum is 3000 RUB for every partner.',title='Partner payout minimum')
        self.add('generic',' '.join(['backend platform contract help across ui and the']*400)+' partner',title='Platform notes')
        self.add('unrelated','Avatar rendering queue.',title='Avatar queue')
        context=self.app.context(['scope'],task='Raise partner payout minimum across backend contract and platform UI')
        self.assertEqual(focused['id'],context['records'][0]['id'])
        self.assertNotIn('unrelated',[row['id'] for row in context['records']])
        row=self.row(context,focused)
        self.assertEqual('ranked',row['selection'])
        self.assertTrue({'partner','payout','minimum'}<={*row['discovery']['matched_terms']})
        self.assertIn('3000',row['discovery']['excerpt'])

    def test_entry_ranking_ignores_stop_words_and_matches_inflected_forms(self):
        self.add('stop-words',' '.join(['\u0438 \u0432 \u043d\u0430 the and of to']*50),title='Common words only')
        target=self.add('tariff','\u0421\u043c\u0435\u043d\u0430 \u0442\u0430\u0440\u0438\u0444\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u044f\u0435\u0442 \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u044b\u0439 \u043f\u043b\u0430\u043d.',title='\u0421\u043c\u0435\u043d\u0430 \u0442\u0430\u0440\u0438\u0444\u0430')
        context=self.app.context(['scope'],task='\u0418\u0441\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0441\u043c\u0435\u043d\u0443 \u0442\u0430\u0440\u0438\u0444\u043e\u0432 \u0438 the plan')
        self.assertEqual([target['id']],[row['id'] for row in context['records']])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = GitStore(self.root / 'realm', self.root / 'runtime')
        self.codec = MarkdownCodec()
        self.app = self.actor('owner')
        self.app.init('Synthetic continuity', realm_id=REALM, context_id='scope')
        self.sequence = 0

    def operation(self, prefix):
        self.sequence += 1
        return prefix + '-' + str(self.sequence)

    def actor(self, principal, **kwargs):
        return RealmService(self.store, principal, lambda: NOW, codec=self.codec, **kwargs)

    def grant(self, *grants):
        snapshot = self.store.snapshot()
        policy = self.codec.load_yaml(snapshot['files']['.ekk/governance.yaml'])
        policy['version'] += 1
        policy['grants'].extend(grants)
        self.app.configure({'.ekk/governance.yaml': self.codec.dump_yaml(policy)},
                           base=snapshot['revision'], idempotency_key=self.operation('grant'))

    def add(self, key, body='', *, app=None, revision=1, scopes=None, **extra):
        app = app or self.app
        metadata = {'schema': 'ekk.record/0.1', 'id': key, 'kind': 'note', 'title': key,
                    'scope': scopes or ['scope'], 'revision': revision,
                    'created_at': NOW, 'created_by': app.principal, **extra}
        raw = self.codec.encode(metadata, body)
        app.apply(app.propose({f'records/{key}.md': raw}),
                  idempotency_key=self.operation('record'))
        return {'realm': REALM, 'id': key, 'revision': revision, 'digest': 'sha256:' + digest(raw)}

    def source(self, raw=b'Original evidence.\r\n', *, app=None, title='Source', scopes=None,
               filename='original.txt'):
        app = app or self.app
        proposal = app.capture(raw, title=title, scope=scopes or ['scope'], filename=filename)
        descriptors = []
        for path, encoded in proposal['changes'].items():
            if path.startswith('records/') and path.endswith('.md'):
                descriptor = base64.b64decode(encoded)
                metadata = self.codec.decode(descriptor)['metadata']
                descriptors.append({'realm': REALM, 'id': metadata['id'],
                                    'revision': metadata['revision'],
                                    'digest': 'sha256:' + digest(descriptor)})
        self.assertEqual(len(descriptors), 1)
        app.apply(proposal, idempotency_key=self.operation('source'))
        return descriptors[0]

    def accept(self, reference, *, app=None):
        app = app or self.app
        return app.accept_records(['scope'], [reference],
                                  expected_snapshot=self.store.snapshot()['revision'],
                                  idempotency_key=self.operation('accept'))

    def commitment(self, source=None):
        source = source or self.source()
        reference = self.add('commitment', 'Proceed under the stated conditions.',
                             kind='decision', mandatory=True, basis=[source],
                             commitment={'expectation': 'Preserve the recorded conditions'})
        self.accept(reference)
        return reference

    @staticmethod
    def exact(reference):
        return {'id': reference['id'], 'title': reference['id'], 'revision': reference['revision'],
                'digest': reference['digest']}

    @staticmethod
    def row(context, reference):
        return next(row for row in context['records'] if row['id'] == reference['id']
                    and row['metadata']['revision'] == reference['revision']
                    and 'sha256:' + row['digest'] == reference['digest'])

    def workspace(self, app):
        return WorkspaceService(lambda: [{'realm_id': REALM, 'realm_alias': 'synthetic',
                                          'owner_projection': 'shared', 'scopes': ['scope'],
                                          'context': app.context}])

    def test_equal_human_and_ai_grants_do_not_turn_sources_or_claims_into_truth(self):
        principals = ('human:reviewer', 'ai:reviewer')
        self.grant(*[{'principal': principal, 'actions': ['read', 'write', 'accept'],
                      'scopes': ['scope']} for principal in principals])
        pairs, choices = [], []
        for index, principal in enumerate(principals):
            actor = self.actor(principal, allowed_scopes=['scope'])
            original = self.source(b'The witness may be mistaken.\r\n', app=actor)
            claim = self.add('interpretation-' + str(index), 'A fallible interpretation.',
                             app=actor, kind='claim', basis=[original])
            pairs.append((principal, original, claim))
            before = self.store.snapshot()['revision']
            for reference in (original, claim):
                with self.assertRaises(ValueError):
                    self.accept(reference, app=actor)
                self.assertEqual(self.store.snapshot()['revision'], before)
            choice = self.add('choice-' + str(index), 'Apply the explicitly scoped decision.',
                              app=actor, kind='decision', basis=[claim])
            self.accept(choice, app=actor)
            choices.append(choice)
        context = self.app.context(['scope'])
        signatures = []
        for principal, original, claim in pairs:
            summaries = []
            for reference in (original, claim):
                row = self.row(context, reference)
                statement = next(item for item in context['insights']['statements']
                                 if item['reference'] == reference)
                self.assertEqual(row['metadata']['created_by'], principal)
                self.assertEqual(statement['created_by'], principal)
                self.assertFalse(row['governs'])
                summaries.append((statement['kind'], statement['content_role'],
                                  statement['attribution'], statement['governs']))
            signatures.append(summaries)
        self.assertEqual(signatures[0], signatures[1])
        self.assertEqual(context['insights']['authority_effect'], 'none')
        self.assertCountEqual([item['reference'] for item in work_view(context)['accepted_commitments']], choices)
        self.assertTrue(all(self.row(context, choice)['governs'] for choice in choices))

    def test_superseding_an_erroneous_reading_preserves_source_and_prior_assertion(self):
        original_bytes = b'\xef\xbb\xbfOne timeout was observed.\r\nNo universal conclusion.\r\n'
        original = self.source(original_bytes)
        wrong = self.add('wrong-reading', 'Every operation fails.', kind='claim', basis=[original])
        previous = self.app.fetch_record(['scope'], wrong)['raw_markdown']
        corrected = self.add('corrected-reading', 'Only one timeout is documented.', kind='claim',
                             basis=[original], supersedes=[wrong])
        context = self.app.context(['scope'], task='corrected-reading')
        self.assertFalse(context['blocked'])
        # Current first: the replaced reading is named by exact reference, not emitted.
        self.assertNotIn(wrong['id'], [row['id'] for row in context['records']])
        self.assertEqual(self.row(context, corrected)['body'], 'Only one timeout is documented.')
        self.assertEqual(self.row(context, corrected)['replaces'], [self.exact(wrong)])
        self.assertFalse(context['manifest']['incomplete'])
        summary = next(item for item in context['insights']['statements']
                       if item['reference'] == corrected)
        self.assertEqual(summary['supersedes'], [wrong])
        self.assertEqual(summary['basis'], [original])
        self.assertEqual(context['insights']['adjudication'], 'not_inferred')
        self.assertEqual(self.app.fetch_record(['scope'], wrong)['raw_markdown'], previous)
        source_read = self.app.read_source(['scope'], original)
        self.assertEqual(base64.b64decode(source_read['base64']), original_bytes)
        asset_path = source_read['asset']['path']
        self.assertEqual(self.store.snapshot()['files'][asset_path], original_bytes)

    def test_conflicting_readings_without_supersession_are_both_emitted(self):
        original = self.source()
        first = self.add('first-reading', 'Every operation fails.', kind='claim', basis=[original])
        second = self.add('second-reading', 'Only one operation fails.', kind='claim', basis=[original],
                          conflicts=[first])
        context = self.app.context(['scope'], task='operation fails reading')
        for reference in (first, second):
            self.assertFalse({'replaces', 'superseded_by'} & set(self.row(context, reference)))
        self.assertEqual(context['insights']['adjudication'], 'not_inferred')

    def test_entry_shows_the_head_of_a_supersession_chain(self):
        first = self.add('limit-one', 'Zebra quota is ten.')
        second = self.add('limit-two', 'Quota is twenty.', supersedes=[first])
        third = self.add('limit-three', 'The threshold is thirty.', supersedes=[second])
        context = self.app.context(['scope'], task='zebra')
        self.assertEqual([third['id']], [row['id'] for row in context['records']])
        row = context['records'][0]
        self.assertEqual(('ranked', [self.exact(second)]), (row['selection'], row['replaces']))
        self.assertNotIn('superseded_by', row)
        # The head takes the best score of its chain; it has no matching word of its own.
        self.assertGreater(row['discovery']['score'], 0)
        self.assertEqual([], row['discovery']['matched_terms'])
        self.assertEqual(([], False), (context['warnings'], context['manifest']['incomplete']))
        self.assertIn('current_first', context['manifest']['ranking'])
        everything = self.app.context(['scope'])
        self.assertEqual([third['id'], 'scope'], sorted(row['id'] for row in everything['records']))
        brief = brief_context(context)
        self.assertEqual('current version of matching material', brief['items'][0]['why'])
        self.assertEqual([{'id': second['id'], 'title': second['id']}], brief['items'][0]['replaces'])

    def test_a_fork_gives_every_head_and_self_revision_replaces_nothing(self):
        origin = self.add('fork-origin', 'Zebra quota is ten.')
        self.add('fork-left', 'Left reading.', supersedes=[origin])
        self.add('fork-right', 'Right reading.', supersedes=[origin])
        revised = self.add('revised', 'Zebra first.')
        self.add('revised', 'Zebra second.', revision=2, supersedes=[revised])
        context = self.app.context(['scope'], task='zebra')
        rows = {row['id']: row for row in context['records']}
        self.assertEqual({'fork-left', 'fork-right', 'revised'}, set(rows))
        self.assertEqual(3, len(context['records']))
        self.assertEqual([self.exact(origin)], rows['fork-left']['replaces'])
        self.assertEqual([self.exact(origin)], rows['fork-right']['replaces'])
        self.assertEqual(2, rows['revised']['metadata']['revision'])
        self.assertFalse({'replaces', 'superseded_by'} & set(rows['revised']))

    def test_supersession_pinned_to_an_earlier_revision_replaces_nothing(self):
        old = self.add('moving', 'Zebra one.')
        self.add('pinned-successor', 'Zebra successor.', supersedes=[old])
        self.add('moving', 'Zebra two.', revision=2)
        context = self.app.context(['scope'], task='zebra')
        rows = {row['id']: row for row in context['records']}
        self.assertEqual({'moving', 'pinned-successor'}, set(rows))
        self.assertEqual('Zebra two.', rows['moving']['body'])
        self.assertNotIn('superseded_by', rows['moving'])
        self.assertNotIn('replaces', rows['pinned-successor'])

    def test_successor_outside_the_projection_is_a_warning_not_a_disclosure(self):
        self.add('other-scope', kind='context', scopes=['other-scope'], context={'purpose': 'Other synthetic context'})
        shown = self.add('shown', 'Zebra quota is ten.')
        hidden = self.add('hidden-successor', 'Confidential replacement.', scopes=['other-scope'], supersedes=[shown])
        context = self.app.context(['scope'], task='zebra')
        self.assertEqual([shown['id']], [row['id'] for row in context['records']])
        self.assertEqual(['selected material has a successor outside the requested or authorized projection'],
                         context['warnings'])
        self.assertEqual(([], False), (context['unknowns'], context['blocked']))
        self.assertNotIn('superseded_by', context['records'][0])
        rendered = json.dumps(context)
        for value in ('hidden-successor', 'Confidential replacement.', hidden['digest'].removeprefix('sha256:')):
            self.assertNotIn(value, rendered)
        both = self.app.context(['scope', 'other-scope'], task='zebra')
        self.assertEqual([hidden['id']], [row['id'] for row in both['records']])
        self.assertEqual([], both['warnings'])

    def test_focus_on_a_replaced_record_brings_its_head(self):
        old = self.add('old-choice', 'Use the first plan.')
        new = self.add('new-choice', 'Use the second plan.', supersedes=[old])
        context = self.app.context(['scope'], task='unmatchedintention', focus=[old])
        self.assertEqual(('required', [self.exact(new)]),
                         (self.row(context, old)['selection'], self.row(context, old)['superseded_by']))
        self.assertEqual(('successor', [self.exact(old)]),
                         (self.row(context, new)['selection'], self.row(context, new)['replaces']))
        self.assertEqual([], context['warnings'])
        items = brief_context(context)['items']
        self.assertEqual([('replaces selected material', None),
                          ('pinned for this workspace or a ground of a governing record',
                           [{'id': new['id'], 'title': new['id']}])],
                         [(item['why'], item.get('superseded_by')) for item in items])
        tight = self.app.context(['scope'], task='unmatchedintention', focus=[old],
                                 budget=len(self.store.snapshot()['files']['records/old-choice.md']))
        self.assertEqual([old['id']], [row['id'] for row in tight['records']])
        self.assertEqual(['selected material is superseded; its successor did not fit the byte budget'], tight['warnings'])
        self.assertEqual(([], False), (tight['unknowns'], tight['blocked']))

    def test_archive_is_a_prior_on_the_plain_score_not_a_tier(self):
        self.add('imported', 'Zebra crossing rule.', migration={'origin': {'path': 'legacy/zebra.md'}})
        self.add('derived-history', 'Zebra crossing history.', adoption='not_adopted')
        self.add('current-strong', 'Zebra crossing decision.')
        self.add('current-weak', 'Zebra aside.')
        scores = {'imported': 10.0, 'derived-history': 4.0, 'current-strong': 3.0, 'current-weak': 2.0}
        with patch('ekk.application.discovery.RecordRanker.scores', return_value=dict(scores)):
            context = self.app.context(['scope'], task='zebra crossing')
        # The floor is a quarter of the best plain score; archive scores are halved for ordering only,
        # so a dominant imported match still leads and a weaker one follows current material.
        self.assertEqual(['imported', 'current-strong', 'derived-history'], [row['id'] for row in context['records']])
        self.assertEqual(['archive', None, 'archive'], [row.get('tier') for row in context['records']])
        self.assertEqual([(5.0, 10.0), (3.0, None), (2.0, 4.0)],
                         [(row['discovery']['score'], row['discovery'].get('plain_score')) for row in context['records']])
        ranking = context['manifest']['ranking']
        self.assertEqual((0.25, 'best plain score', {'owner_preference': 1.5, 'archive': 0.5}, 'orders optional reading only'),
                         (ranking['relative_score_floor'], ranking['floor_basis'], ranking['priors'], ranking['effect']))
        self.assertNotIn('boosts', ranking)
        self.assertEqual([{'id': key, 'title': key, 'kind': 'note', 'revision': 1} for key in ('imported', 'derived-history', 'current-strong')],
                         [{k: v for k, v in row.items() if k != 'digest'} for row in ranking['plain_order']])
        self.assertTrue(all(row['digest'].startswith('sha256:') for row in ranking['plain_order']))  # exact, for later advice
        self.assertEqual(['archive', None, 'archive'], [item.get('tier') for item in brief_context(context)['items']])
        bare = self.app.context(['scope'])
        self.assertEqual([], bare['manifest']['ranking']['plain_order'])
        # Without a task every relevance is zero: current material still precedes archive.
        self.assertEqual([None, None, 'archive', 'archive'], [row.get('tier') for row in bare['records'] if row['id'] != 'scope'])

    def test_owner_preference_prior_orders_entry_but_not_the_floor_or_plain_order(self):
        self.add('owner-rule', 'Zebra habit.', preference={'schema': 'ekk.preference/0.1', 'area': 'style', 'stated_by': 'owner'})
        self.add('agent-guess', 'Zebra guess.', preference={'schema': 'ekk.preference/0.1', 'area': 'style', 'stated_by': 'agent'})
        self.add('relayed-rule', 'Zebra relayed.', preference={'schema': 'ekk.preference/0.1', 'area': 'style', 'stated_by': 'owner_relayed'})
        self.add('plain-note', 'Zebra note.')
        self.add('faint', 'Zebra aside.', preference={'schema': 'ekk.preference/0.1', 'area': 'style', 'stated_by': 'owner'})
        self.add('old-view', 'Zebra old.')
        self.add('new-view', 'Current.', supersedes=[{'id': 'old-view'}])
        scores = {'owner-rule': 4.0, 'agent-guess': 4.5, 'relayed-rule': 3.2, 'plain-note': 5.0, 'faint': 1.2, 'old-view': 8.0}
        with patch('ekk.application.discovery.RecordRanker.scores', return_value=dict(scores)):
            context = self.app.context(['scope'], task='zebra')
        # 1.2 * 1.5 would pass a floor of 2.0, but the floor reads the plain score. The owner's words count,
        # whether from the review page or relayed by an agent; an agent's own reading gets no prior. The head
        # of a chain takes the plain score of the record it replaces.
        self.assertEqual([('new-view', 8.0), ('owner-rule', 6.0), ('plain-note', 5.0), ('relayed-rule', 4.8), ('agent-guess', 4.5)],
                         [(row['id'], row['discovery']['score']) for row in context['records']])
        self.assertEqual([0.0, 4.0, None, 3.2, None], [row['discovery'].get('plain_score') for row in context['records']])
        self.assertEqual([('old-view', 'note'), ('plain-note', 'note'), ('agent-guess', 'preference'), ('owner-rule', 'preference'), ('relayed-rule', 'preference')],
                         [(item['id'], item['kind']) for item in context['manifest']['ranking']['plain_order']])

    def test_a_governing_record_is_selected_before_optional_reading_or_named_as_left_out(self):
        rule = self.add('accepted-rule', 'Ledger entries stay immutable. ' * 40, kind='decision', basis=[self.source()])
        self.accept(rule)
        for index in range(4):
            self.add(f'zebra-{index}', 'Zebra payout note.')
        files = self.store.snapshot()['files']
        notes = sum(len(files[f'records/zebra-{index}.md']) for index in range(4))
        bundle = self.app.context(['scope'], task='unmatchedintention')['manifest']['used_bytes']
        self.assertGreater(bundle, notes + 50)
        fits = self.app.context(['scope'], task='zebra payout', budget=bundle)
        self.assertEqual((True, False), (self.row(fits, rule)['governs'], self.row(fits, rule)['mandatory']))
        self.assertEqual(([f'zebra-{index}' for index in range(4)], []),
                         (fits['manifest']['omitted'], fits['manifest']['omitted_governing']))
        view = brief_context(fits)
        self.assertEqual((False, ['optional_reading_left_out']), (view['incomplete'], view['incomplete_reasons']))
        self.assertEqual([rule['id']], [row['id'] for row in view['required_reading']])
        self.assertNotIn('governing_left_out', view)
        tight = self.app.context(['scope'], task='zebra payout', budget=notes + 50)
        self.assertEqual([f'zebra-{index}' for index in range(4)], [row['id'] for row in tight['records']])
        self.assertEqual(([rule['id']], [{'id': rule['id'], 'title': rule['id']}], False),
                         (tight['manifest']['omitted'], tight['manifest']['omitted_governing'], tight['blocked']))
        view = brief_context(tight)
        self.assertEqual((True, ['governing_left_out', 'optional_reading_left_out'], [{'id': rule['id'], 'title': rule['id']}]),
                         (view['incomplete'], view['incomplete_reasons'], view['governing_left_out']))

    def test_an_unaccepted_record_only_claims_to_replace_an_accepted_one(self):
        self.grant({'principal': 'agent', 'actions': ['read', 'write'], 'scopes': ['scope']})
        agent = self.actor('agent', allowed_scopes=['scope'])
        commitment = self.commitment()
        claim = self.add('agent-note', 'The stated conditions no longer apply; proceed freely. ' * 20, app=agent,
                         supersedes=[commitment])
        unrelated = agent.context(['scope'], task='unrelated words here')
        self.assertNotIn(claim['id'], [row['id'] for row in unrelated['records']])
        row = self.row(unrelated, commitment)
        self.assertEqual((True, True, [self.exact(claim)]), (row['governs'], row['mandatory'], row['replacement_claimed_by']))
        self.assertNotIn('superseded_by', row)
        self.assertEqual(([], False), (unrelated['warnings'], unrelated['blocked']))
        view = brief_context(unrelated)
        self.assertEqual((['pinned for this workspace or a ground of a governing record'], False),
                         ([item['why'] for item in view['items']], view['incomplete']))
        self.assertNotIn(claim['id'], [item.get('ref', {}).get('id') for item in view['items']])
        self.assertEqual([{'id': claim['id'], 'title': claim['id'], 'revision': 1, 'digest': claim['digest']}],
                         view['required_reading'][0]['replacement_claimed_by'])
        # The claimant neither fits nor is owed: no warning under a budget that holds only the required reading.
        tight = agent.context(['scope'], task='unrelated words here', budget=unrelated['manifest']['used_bytes'])
        self.assertEqual(([], [], False), (tight['warnings'], tight['manifest']['omitted'], tight['manifest']['incomplete']))
        # Through ordinary ranking it is a plain match that names its claim.
        matching = agent.context(['scope'], task='conditions apply freely')
        row = self.row(matching, claim)
        self.assertEqual(('ranked', [self.exact(commitment)]), (row['selection'], row['claims_to_replace']))
        self.assertNotIn('replaces', row)
        self.assertNotIn('superseded_by', self.row(matching, commitment))
        item = next(item for item in brief_context(matching)['items'] if item.get('ref', {}).get('id') == claim['id'])
        self.assertEqual([{'id': commitment['id'], 'title': commitment['id']}], item['claims_to_replace'])
        self.assertTrue(item['why'].startswith('matches: '))
        self.assertNotIn('replaces', item)
        # Without a task every record is listed; the claimant is worded as a claim, after nothing special.
        item = next(item for item in brief_context(agent.context(['scope']))['items'] if item.get('ref', {}).get('id') == claim['id'])
        self.assertEqual('unaccepted record that claims to replace an accepted one', item['why'])

    def test_statement_summaries_cut_by_the_insight_budget_are_not_a_required_gap(self):
        self.app.apply(self.app.propose({f'records/zebra-{index:02}.md': self.codec.encode(
            {'schema': 'ekk.record/0.1', 'id': f'zebra-{index:02}', 'kind': 'note', 'title': f'zebra-{index:02}',
             'scope': ['scope'], 'revision': 1, 'created_at': NOW, 'created_by': 'owner'}, 'Zebra note.')
            for index in range(40)}), idempotency_key=self.operation('record'))
        context = self.app.context(['scope'], task='zebra', budget=64000)
        insights = context['insights']
        self.assertEqual((40, []), (len(context['records']), context['manifest']['omitted']))
        self.assertLess(len(insights['statements']), 40)
        self.assertEqual((True, False), (insights['incomplete'], insights['relations_incomplete']))
        self.assertLessEqual(len(json.dumps(insights, ensure_ascii=False, separators=(',', ':')).encode()), insights['byte_budget'])
        view = brief_context(context)
        self.assertFalse(view['incomplete'])
        self.assertNotIn('challenges_not_shown', view['incomplete_reasons'])

    def test_a_ground_of_an_earlier_item_is_not_listed_again(self):
        original = self.source(b'Zebra evidence text.\r\n', title='Zebra evidence')
        finding = self.add('zebra-finding', 'Zebra finding.', kind='claim', basis=[original])
        for scores, selections in (({finding['id']: 4.0, original['id']: 5.0}, ['ranked', 'ranked']),
                                   ({finding['id']: 5.0, original['id']: 4.0}, ['ranked', 'dependency'])):
            with patch('ekk.application.discovery.RecordRanker.scores', return_value=dict(scores)):
                context = self.app.context(['scope'], task='zebra')
            self.assertEqual(2, len(context['records']))
            self.assertEqual(selections, [self.row(context, ref)['selection'] for ref in (finding, original)])
            self.assertEqual(1, self.row(context, finding)['grounds'])
            self.assertEqual([{'id': original['id'], 'title': 'Zebra evidence', 'revision': original['revision'],
                               'digest': original['digest']}], self.row(context, finding)['ground_refs'])
            self.assertNotIn('grounds', self.row(context, original))
            self.assertNotIn('ground_refs', self.row(context, original))
        # The agent view counts the ground on the finding and names it by reference instead of listing it.
        self.assertEqual([(finding['id'], 1, [{'id': original['id'], 'title': 'Zebra evidence'}])],
                         [(item['ref']['id'], item['grounds'], item['ground_refs']) for item in brief_context(context)['items']])

    def test_task_term_weights_reach_entry_ranking(self):
        class Terms:
            def weight(self, stem):
                return 0.05 if stem == 'fix' else 1.0
        self.add('fix-log', 'Fix fix fix.')
        self.add('other-log', 'Avatar queue.')
        self.add('payout-rule', 'Payout minimum.')
        self.add('payout-note', 'Payout payout aside.')
        plain = self.app.context(['scope'], task='fix payout')
        self.assertFalse(plain['manifest']['source_search']['query_weights_applied'])
        self.assertEqual('fix-log', plain['records'][0]['id'])
        weighted = self.actor('owner', task_terms=Terms()).context(['scope'], task='fix payout')
        self.assertTrue(weighted['manifest']['source_search']['query_weights_applied'])
        self.assertNotIn('fix-log', [row['id'] for row in weighted['records'][:2]])

    def test_unrelated_words_do_not_hide_explicit_dissent_or_revoke_commitment(self):
        commitment = self.commitment()
        dissent = self.add('counterstatement', 'Zirconium luminescence.', kind='claim', relations=[
            {'rel': 'contradicts', 'target': commitment['id'],
             'revision': commitment['revision'], 'digest': commitment['digest']}])
        before = self.store.snapshot()['revision']
        context = self.app.context(['scope'], task='unmatchedintention')
        self.assertEqual(self.store.snapshot()['revision'], before)
        self.assertFalse(context['blocked'])
        self.assertEqual(context['conflicts'], [])
        self.assertTrue(self.row(context, commitment)['governs'])
        self.assertFalse(self.row(context, dissent)['governs'])
        self.assertEqual(context['insights']['challenges'], [{
            'statement': dissent, 'target': commitment, 'relation': 'contradicts',
            'status': 'recorded_disagreement'}])
        view = work_view(context)
        self.assertIn(commitment, [item['reference'] for item in view['accepted_commitments']])
        self.assertEqual(view['challenges'], context['insights']['challenges'])

    def test_only_authorized_accepted_hold_blocks_and_exact_resolution_preserves_dissent(self):
        self.grant({'principal': 'reviewer', 'actions': ['read', 'write'], 'scopes': ['scope']})
        reviewer = self.actor('reviewer', allowed_scopes=['scope'])
        commitment = self.commitment()
        dissent = self.add('dissent', 'An independently recorded objection.', app=reviewer,
                           kind='claim', conflicts=[commitment])
        hold = self.add('hold', 'Wait for contextual review.', app=reviewer, kind='decision',
                        mandatory=True, basis=[dissent], conflicts=[commitment],
                        commitment={'expectation': 'Pause the conflicting commitment'})
        before = self.store.snapshot()['revision']
        with self.assertRaises(PermissionError):
            self.accept(hold, app=reviewer)
        self.assertEqual(self.store.snapshot()['revision'], before)
        pending = reviewer.context(['scope'])
        self.assertFalse(pending['blocked'])
        self.assertFalse(self.row(pending, hold)['governs'])
        self.accept(hold)
        stopped = reviewer.context(['scope'], task='unmatchedintention')
        self.assertTrue(stopped['blocked'])
        self.assertTrue(self.row(stopped, hold)['governs'])
        self.assertIn(sorted([hold['id'], commitment['id']]), stopped['conflicts'])
        resolution = self.add('resolution', 'Resume under the explicit local decision.',
                              kind='decision', mandatory=True, basis=[dissent], supersedes=[hold],
                              commitment={'expectation': 'Replace this exact hold'})
        self.accept(resolution)
        resumed = reviewer.context(['scope'], task='unmatchedintention')
        self.assertFalse(resumed['blocked'])
        self.assertEqual(resumed['conflicts'], [])
        self.assertTrue(self.row(resumed, commitment)['governs'])
        self.assertTrue(self.row(resumed, resolution)['governs'])
        self.assertFalse(self.row(resumed, hold)['governs'])
        self.assertEqual(self.row(resumed, dissent)['body'], 'An independently recorded objection.')
        self.assertEqual(resumed['insights']['challenges'], [{
            'statement': dissent, 'target': commitment, 'relation': 'contradicts',
            'status': 'recorded_disagreement'}])
        self.assertEqual(resumed['insights']['adjudication'], 'not_inferred')

    def test_pinned_old_basis_and_current_readable_head_are_both_in_work_context(self):
        old = self.add('grounds', 'The old assessment.', kind='observation')
        commitment = self.commitment(old)
        current = self.add('grounds', 'The revised assessment.', kind='observation', revision=2)
        context = self.app.context(['scope'], task='unmatchedintention')
        self.assertFalse(context['blocked'])
        self.assertEqual(self.row(context, old)['body'], 'The old assessment.')
        self.assertEqual(self.row(context, current)['body'], 'The revised assessment.')
        self.assertEqual(self.row(context, commitment)['metadata']['basis'], [old])
        self.assertTrue(self.row(context, commitment)['governs'])
        expected = [{'statement': commitment, 'pinned': old, 'current': current,
                     'status': 'pinned_ground_differs'}]
        self.assertEqual(context['insights']['changed_grounds'], expected)
        self.assertEqual(work_view(context)['changed_grounds'], expected)

    def test_advisory_dissent_cannot_bypass_mandatory_byte_overflow(self):
        commitment = self.commitment()
        dissent = self.add('dissent', 'Objection.', kind='claim', conflicts=[commitment])
        before = self.store.snapshot()['revision']
        context = self.app.context(['scope'], task='unmatchedintention', budget=1)
        self.assertTrue(context['blocked'])
        self.assertTrue(context['manifest']['incomplete'])
        self.assertEqual(context['records'], [])
        self.assertEqual(context['manifest']['used_bytes'], 0)
        self.assertTrue(any('mandatory constraints exceed byte budget' in item
                            for item in context['unknowns']))
        self.assertEqual(self.store.snapshot()['revision'], before)
        full = self.app.context(['scope'], task='unmatchedintention')
        self.assertFalse(full['blocked'])
        self.assertEqual(self.row(full, dissent)['id'], dissent['id'])

    def test_unemitted_advisory_dissent_marks_incomplete_without_blocking(self):
        commitment = self.commitment()
        required = self.app.context(['scope'], task='unmatchedintention')
        dissent = self.add('dissent', 'Substantial recorded objection. ' * 50,
                           kind='claim', conflicts=[commitment])
        context = self.app.context(['scope'], task='unmatchedintention',
                                   budget=required['manifest']['used_bytes'])
        self.assertFalse(context['blocked'])
        self.assertTrue(self.row(context, commitment)['governs'])
        self.assertTrue(context['manifest']['incomplete'])
        self.assertTrue(context['insights']['incomplete'])
        self.assertTrue(context['insights']['relations_incomplete'])
        self.assertEqual(['challenges_not_shown', 'optional_reading_left_out'], brief_context(context)['incomplete_reasons'])
        self.assertEqual(context['insights']['challenges'], [])
        self.assertNotIn(dissent['id'], [row['id'] for row in context['records']])

    def test_hidden_dependencies_are_not_disclosed_to_a_scoped_reader(self):
        self.add('private-scope', kind='context', scopes=['private-scope'],
                 context={'purpose': 'Private synthetic material'})
        secret = self.add('secret-ground', 'Confidential evidence text.', scopes=['private-scope'],
                          title='Confidential evidence title')
        hidden = self.add('hidden-commitment', 'Confidential commitment text.', kind='decision',
                          mandatory=True, basis=[secret], title='Confidential commitment title')
        self.app.apply(self.app.propose({}), idempotency_key=self.operation('accept-hidden'),
                       accept=[hidden['id']])
        self.grant({'principal': 'reader', 'actions': ['read'], 'scopes': ['scope']})
        for actor in (self.actor('reader'), self.actor('owner', allowed_scopes=['scope'])):
            with self.subTest(principal=actor.principal):
                context = actor.context(['scope'], task='Confidential')
                self.assertTrue(context['blocked'])
                self.assertTrue(context['manifest']['incomplete'])
                self.assertIn('applicable accepted commitment or basis outside authorized projection',
                              context['unknowns'])
                rendered = json.dumps(context)
                for value in ('private-scope', 'secret-ground', 'hidden-commitment',
                              'Confidential evidence text.', 'Confidential evidence title',
                              'Confidential commitment text.', 'Confidential commitment title',
                              secret['digest'].removeprefix('sha256:'), hidden['digest'].removeprefix('sha256:')):
                    self.assertNotIn(value, rendered)

    def test_explicit_context_scope_excludes_dependencies_outside_the_requested_projection(self):
        self.add('private-scope', kind='context', scopes=['private-scope'],
                 context={'purpose': 'Other synthetic owner context'})
        secret = self.add('secret-ground', 'Hidden grounds.', scopes=['private-scope'],
                          title='Hidden grounds title')
        linked = self.add('cross-context-claim', 'Looks relevant.', kind='claim', basis=[secret],
                          title='Cross context title')
        context = self.app.context(['scope'], task='relevant')
        rendered = json.dumps(context)
        for value in ('secret-ground', 'private-scope', 'Hidden grounds.', 'Hidden grounds title',
                      'cross-context-claim', 'Cross context title',
                      secret['digest'].removeprefix('sha256:'), linked['digest'].removeprefix('sha256:')):
            self.assertNotIn(value, rendered)

    def test_source_asset_terms_retrieve_their_descriptor_without_changing_source_bytes(self):
        raw = 'Only the asset mentions \u043d\u0435\u043f\u043e\u0432\u0442\u043e\u0440\u0438\u043c\u0430\u044f\u043d\u0435\u043f\u0440\u0435\u0440\u044b\u0432\u043d\u043e\u0441\u0442\u044c.\r\n'.encode('utf-8')
        original = self.source(raw, title='Archive', filename='original.txt')
        descriptor = self.app.fetch_record(['scope'], original)
        self.assertNotIn('\u043d\u0435\u043f\u043e\u0432\u0442\u043e\u0440\u0438\u043c\u0430\u044f\u043d\u0435\u043f\u0440\u0435\u0440\u044b\u0432\u043d\u043e\u0441\u0442\u044c', descriptor['body'])
        self.assertNotIn('\u043d\u0435\u043f\u043e\u0432\u0442\u043e\u0440\u0438\u043c\u0430\u044f\u043d\u0435\u043f\u0440\u0435\u0440\u044b\u0432\u043d\u043e\u0441\u0442\u044c', descriptor['metadata']['title'])
        before = self.store.snapshot()['revision']
        context = self.app.context(['scope'], task='\u041d\u0415\u041f\u041e\u0412\u0422\u041e\u0420\u0418\u041c\u0410\u042f\u041d\u0415\u041f\u0420\u0415\u0420\u042b\u0412\u041d\u041e\u0421\u0422\u042c')
        self.assertFalse(context['blocked'])
        self.assertEqual(self.row(context, original)['metadata']['kind'], 'source')
        coverage = context['manifest']['source_search']
        self.assertEqual((coverage['partial_assets'], coverage['unsearchable_assets']), (0, 0))
        self.assertEqual(self.store.snapshot()['revision'], before)
        self.assertEqual(base64.b64decode(self.app.read_source(['scope'], original)['base64']), raw)

    def test_fresh_application_and_process_resume_the_exact_prior_work_view_result(self):
        original = self.source()
        previous = self.add('result', 'First recorded result.', kind='outcome', basis=[original])
        first_entry = self.workspace(self.app).start(task='recorded result')
        first_view = first_entry['contexts'][0]['work_view']
        resume = next(item['reference'] for item in first_view['visible_results']
                      if item['reference']['id'] == previous['id'])
        self.assertEqual(resume, previous)
        current = self.add('result', 'Later revised result.', kind='outcome', revision=2, basis=[original])
        before = self.store.snapshot()['revision']
        fresh_store = GitStore(self.root / 'realm', self.root / 'runtime')
        fresh_app = RealmService(fresh_store, 'owner', lambda: NOW, codec=MarkdownCodec())
        resumed = self.workspace(fresh_app).start(task='unmatchedintention', resume=resume)
        context = resumed['contexts'][0]
        self.assertFalse(resumed['blocked'])
        self.assertEqual(self.row(context, previous)['body'], 'First recorded result.')
        self.assertIn(previous, [item['reference'] for item in context['work_view']['visible_results']])
        self.assertNotIn(current, [item['reference'] for item in context['work_view']['visible_results']])
        script = textwrap.dedent('''
            import json
            import sys
            from ekk.adapters.git_store import GitStore
            from ekk.adapters.markdown import MarkdownCodec
            from ekk.application import RealmService
            from ekk.application.workspace import WorkspaceService
            store = GitStore(sys.argv[1], sys.argv[2])
            app = RealmService(store, 'owner', lambda: '2026-09-08T12:00:00Z', codec=MarkdownCodec())
            workspace = WorkspaceService(lambda: [{
                'realm_id': 'realm:continuity', 'realm_alias': 'synthetic',
                'owner_projection': 'shared', 'scopes': ['scope'], 'context': app.context,
            }])
            print(json.dumps(workspace.start(task='unmatchedintention', resume=json.loads(sys.argv[3]))))
        ''')
        environment = dict(os.environ, PYTHONPATH=str(Path(ekk.__file__).resolve().parents[1]),
                           PYTHONDONTWRITEBYTECODE='1')
        process = subprocess.run([sys.executable, '-c', script, str(self.root / 'realm'),
                                  str(self.root / 'runtime'), json.dumps(resume)], cwd=self.root,
                                 env=environment, text=True, capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        from_process = json.loads(process.stdout)
        self.assertFalse(from_process['blocked'])
        process_context = from_process['contexts'][0]
        self.assertEqual(process_context['manifest']['forced_refs'], [previous])
        self.assertEqual(self.row(process_context, previous)['body'], 'First recorded result.')
        self.assertEqual(process_context['work_view']['visible_results'],
                         context['work_view']['visible_results'])
        self.assertEqual(from_process['entry']['mutations'], 0)
        self.assertEqual(self.store.snapshot()['revision'], before)


def ranked_row(title, body, **metadata):
    return {'metadata': {'title': title, **metadata}, 'body': body}


class RecordRankerTests(unittest.TestCase):
    def test_a_source_lead_equal_to_the_record_body_is_indexed_once(self):
        text = 'Payout minimum  rule.\nPartners receive 3000.'
        asset = {'source': {'assets': [{'path': 'assets/a.md'}]}}
        rows = {'imported': ranked_row('Imported', text, **asset), 'other': ranked_row('Other', 'Avatar queue.')}
        twice = RecordRanker(rows, {'assets/a.md': b'Different payout text.'})
        once = RecordRanker(rows, {'assets/a.md': b'Payout minimum rule. Partners\r\n receive 3000.\n'})
        plain = RecordRanker({**rows, 'imported': ranked_row('Imported', text)}, {})
        self.assertEqual((0, 1), (twice.coverage['duplicate_leads'], once.coverage['duplicate_leads']))
        self.assertEqual(0, once.coverage['scanned_chars'])
        self.assertEqual(plain.scores('payout rule'), once.scores('payout rule'))
        self.assertEqual('body', once.explain('imported', 'payout rule')['section'])

    def test_query_weights_change_ranking_and_the_order_of_matched_terms(self):
        rows = {'fixes': ranked_row('Log', 'Fix fix fix.'), 'payout': ranked_row('Rule', 'Payout minimum.'),
                'both': ranked_row('Mixed', 'Fix the payout.'), 'payouts': ranked_row('More', 'Payout payout aside.'),
                'noise': ranked_row('Noise', 'Avatar queue.')}
        task = 'Fix payout'
        plain = RecordRanker(rows, {})
        weighted = RecordRanker(rows, {}, query_weight=lambda term: 0.05 if term == 'fix' else 1.0)
        invalid = RecordRanker(rows, {}, query_weight=lambda term: 7)
        before, after = plain.scores(task), weighted.scores(task)
        self.assertGreater(before['fixes'], before['payout'])
        self.assertGreater(after['payout'], after['fixes'])
        self.assertEqual((False, True), (plain.coverage['query_weights_applied'], weighted.coverage['query_weights_applied']))
        # 'fix' is the rarer word, so it leads until its weight says it frames the task.
        self.assertEqual(['fix', 'payout'], plain.explain('both', task)['matched_terms'])
        self.assertEqual(['payout', 'fix'], weighted.explain('both', task)['matched_terms'])
        self.assertEqual(before, invalid.scores(task))
        self.assertFalse(invalid.coverage['query_weights_applied'])

    def test_explanation_names_at_most_six_terms(self):
        words = 'alpha bravo charlie delta echo foxtrot golf hotel'
        ranker = RecordRanker({'a': ranked_row('All', words), 'b': ranked_row('Other', 'alpha bravo')}, {})
        matched = ranker.explain('a', words)['matched_terms']
        self.assertEqual(6, len(matched))
        self.assertFalse({'alpha', 'bravo'} & set(matched))

    def test_scores_are_plain_and_priors_belong_to_the_entry(self):
        rows = {'plain': ranked_row('Note', 'Use tabs.'),
                'preferred': ranked_row('Note', 'Use tabs.', preference={'area': 'style', 'stated_by': 'owner'}),
                'imported': ranked_row('Note', 'Use tabs.', migration={'origin': {'path': 'legacy/tabs.md'}})}
        ranker = RecordRanker(rows, {})
        scores = ranker.scores('tabs')
        self.assertEqual((scores['plain'], scores['plain']), (scores['preferred'], scores['imported']))
        self.assertNotIn('boosts', ranker.coverage)
        self.assertEqual((1.5, 0.5), (RecordRanker.PREFERENCE_BOOST, discovery.ARCHIVE_PRIOR))


if __name__ == '__main__':
    unittest.main()
