import json
from pathlib import Path
import tempfile
import unittest
from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.adapters.method_repository import RealmMethodRepository
from ekk.adapters.method_execution import LocalMethodExecutor, MethodAdapter
from ekk.application.methods import MethodService, MethodUnavailable
from ekk.model.methods import sha


class MethodLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.app = RealmService(GitStore(self.root/'shared', self.root/'runtime'), 'owner', codec=MarkdownCodec())
        self.app.init('Shared work', context_id='context:work')
        self.repo = RealmMethodRepository(self.app, scopes=['context:work'], journal_root=self.root/'journal')
        self.allowed = True
        self.adapter = MethodAdapter('example:add', '1', 'fixed-add/1', (),
            lambda artifact: artifact == b'add-one',
            lambda artifact, request: request['value'] + 1,
            {'heldout': {'input': {'value': 40}, 'expected': 41},
             'changed': {'input': {'value': 40}, 'expected': 42}},
            lambda output, case: output == case['expected'])
        self.executor = LocalMethodExecutor({self.adapter.id:self.adapter}, self.root/'evidence',
                                            authorize=lambda *args: self.allowed)
        self.service = MethodService(self.repo, self.executor)
        self.facts = {'task_family':'arithmetic', 'environment':'fixture', 'model':'none:deterministic'}
        self.spec = {'schema':'ekk.method/0.1', 'adapter':self.adapter.id, 'adapter_version':'1',
                     'artifact_digest':sha(b'add-one'), 'privileges':[],
                     'applicability':{k:[v] for k,v in self.facts.items()},
                     'rollback':'Remove local admission; retain original evidence',
                     'reconsider_when':['Expected behavior changes'], 'limitations':['Synthetic arithmetic fixture']}
        self.candidate = self.service.propose(method_id='method:add', title='Add one', spec=self.spec,
            artifact=b'add-one', explanation='Reusable operation, no held-out answer retained', key='candidate-1')
        self.ref = self.candidate['method']

    def admit(self):
        evaluation = self.service.evaluate(self.ref, case_id='heldout', facts=self.facts, key='eval-1')
        accepted = self.service.admit(self.ref, evaluation['evidence'], explanation='Offer for fixture arithmetic only', key='admit-1')
        return evaluation, accepted

    def test_candidate_inert_and_restart_rehydrates_accepted_method(self):
        with self.assertRaises(MethodUnavailable):
            self.service.use(self.ref, request={'value':9}, facts=self.facts, key='run-1')
        self.admit()
        fresh = MethodService(RealmMethodRepository(self.app, scopes=['context:work'], journal_root=self.root/'journal'),
                             LocalMethodExecutor({self.adapter.id:self.adapter}, self.root/'evidence', authorize=lambda *args:True))
        result = fresh.use(self.ref, request={'value':99}, facts=self.facts, key='run-1')
        self.assertEqual(result['output'], 100)
        self.assertEqual(fresh.use(self.ref, request={'value':99}, facts=self.facts, key='run-1'), result)

    def test_adverse_evaluation_quarantine_retirement_preserve_history(self):
        self.admit()
        result = self.service.reconsider(self.ref, case_id='changed', facts=self.facts, key='eval-changed')
        self.assertTrue(result['review_required'])
        self.service.quarantine(self.ref, reason='Changed requirement under review')
        with self.assertRaises(MethodUnavailable):
            self.service.use(self.ref, request={'value':9}, facts=self.facts, key='run-2')
        self.service.retire(self.ref, explanation='Old addition is unsuitable', basis=[result['evidence']['reference']], key='retire-1')
        self.assertFalse(self.repo.active(self.ref)['active'])
        self.assertEqual(self.repo.load(self.ref)['artifact'], b'add-one')
        self.assertTrue(self.app.doctor()['ok'])

    def test_forged_evaluation_and_current_authority_denied(self):
        evaluation, _ = self.admit()
        forged = dict(evaluation['evaluation'], passed=False)
        self.assertFalse(self.executor.verify_receipt(forged, self.repo.load(self.ref)))
        self.allowed = False
        with self.assertRaises(MethodUnavailable):
            self.service.use(self.ref, request={'value':9}, facts=self.facts, key='run-3')

    def test_unknown_environment_is_not_applicable(self):
        self.admit()
        with self.assertRaises(MethodUnavailable):
            self.service.use(self.ref, request={'value':9}, facts={**self.facts,'environment':'other'}, key='run-4')

    def test_exact_retry_does_not_duplicate_candidate(self):
        before = self.app.store.snapshot()['revision']
        again = self.service.propose(method_id='method:add', title='Add one', spec=self.spec,
            artifact=b'add-one', explanation='Reusable operation, no held-out answer retained', key='candidate-1')
        self.assertEqual(again, self.candidate)
        self.assertEqual(before, self.app.store.snapshot()['revision'])

    def test_revision_withdraws_workspace_offer_and_historical_admission(self):
        from ekk.application.workspace import work_view
        evaluation, _ = self.admit()
        self.assertEqual(len(work_view(self.app.context(['context:work']), self.repo.active)['method_offers']), 1)
        self.service.propose(method_id='method:add', title='Revised addition', spec=self.spec,
            artifact=b'add-one', explanation='Changed conditions need new acceptance.',
            key='revision', previous=self.ref)
        self.assertEqual(work_view(self.app.context(['context:work']), self.repo.active)['method_offers'], [])
        with self.assertRaises(MethodUnavailable):
            self.service.admit(self.ref, evaluation['evidence'], explanation='Stale retry', key='stale-admission')

    def test_deleted_evaluation_cannot_authorize_execution(self):
        evaluation, _ = self.admit()
        evidence_id = evaluation['evidence']['reference']['id']
        snapshot = self.app.store.snapshot()
        path = next(path for path, raw in snapshot['files'].items()
                    if path.startswith('records/') and path.endswith('.md')
                    and self.app.codec.decode(raw)['metadata']['id'] == evidence_id)
        assets = self.app.codec.decode(snapshot['files'][path])['metadata']['source']['assets']
        changes = {path: None, **{asset['path']: None for asset in assets}}
        self.app.apply(self.app.propose(changes), idempotency_key='withdraw-evidence')
        self.assertFalse(self.repo.active(self.ref)['active'])
        with self.assertRaises(MethodUnavailable):
            self.service.use(self.ref, request={'value':9}, facts=self.facts, key='run-withdrawn')

    def test_canonical_revocation_during_execution_blocks_result(self):
        from unittest.mock import patch
        self.admit()
        execute = self.executor.execute
        active = self.repo.active
        revoked = False
        def run_then_revoke(*args, **kwargs):
            nonlocal revoked
            result = execute(*args, **kwargs)
            revoked = True
            return result
        def current(reference):
            return {'active':False} if revoked else active(reference)
        with patch.object(self.executor, 'execute', side_effect=run_then_revoke), patch.object(self.repo, 'active', side_effect=current):
            with self.assertRaises(MethodUnavailable):
                self.service.use(self.ref, request={'value':9}, facts=self.facts, key='run-concurrent-withdrawal')

if __name__=='__main__':unittest.main()
