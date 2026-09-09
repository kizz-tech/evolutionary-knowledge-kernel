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
from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.application.workspace import WorkspaceService, work_view
from ekk.model import digest


REALM = 'realm:continuity'
NOW = '2026-09-08T12:00:00Z'


class ContextContinuityTests(unittest.TestCase):
    def test_source_scanning_has_a_shared_deterministic_byte_limit(self):
        self.source(b'x'*300+b' needle',title='Source descriptor')
        with patch('ekk.application.service.CONTEXT_SOURCE_SCAN_BYTES',128):
            result=self.app.context(['scope'],task='needle')
        coverage=result['manifest']['source_search']
        self.assertEqual(128,coverage['scanned_bytes'])
        self.assertEqual(128,coverage['scan_budget_bytes'])
        self.assertTrue(result['manifest']['incomplete'])
        self.assertEqual([],result['records'])

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
        self.assertEqual(self.row(context, wrong)['body'], 'Every operation fails.')
        self.assertEqual(self.row(context, corrected)['body'], 'Only one timeout is documented.')
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
        self.assertEqual(context['manifest']['source_search']['omitted_or_partial_assets'], 0)
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


if __name__ == '__main__':
    unittest.main()
