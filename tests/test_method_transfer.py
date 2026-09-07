"""Risk-focused method transfer tests, using independent synthetic local owners."""
import base64
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.adapters.method_repository import RealmMethodRepository
from ekk.adapters.method_execution import LocalMethodExecutor, MethodAdapter
from ekk.application import RealmService
from ekk.application.methods import MethodService, MethodUnavailable
from ekk.model.methods import sha, canonical, method_reference


class MethodTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.serial=0
        self.calls=[]
        self.adapter=MethodAdapter('example:increment','1','increment-verifier/1',(),
            lambda artifact:artifact==b'increment',
            lambda artifact,request:self.run_adapter(request),
            {'origin-case':{'input':{'value':10},'expected':11},
             'recipient-case':{'input':{'value':71},'expected':72}},
            lambda output,case:output==case['expected'])
        self.facts={'task_family':'arithmetic','environment':'synthetic','model':'deterministic'}
        self.spec={'schema':'ekk.method/0.1','adapter':self.adapter.id,'adapter_version':'1',
            'artifact_digest':sha(b'increment'),'privileges':[],
            'applicability':{k:[v] for k,v in self.facts.items()},
            'rollback':'Withdraw local admission and preserve evidence',
            'reconsider_when':['Requirements change'],'limitations':['Synthetic integer increment only']}
        self.origin=self.realm('origin','author')
        self.repo=RealmMethodRepository(self.origin,scopes=['scope:work'],journal_root=self.root/'origin-journal')
        self.executor=LocalMethodExecutor({self.adapter.id:self.adapter},self.root/'origin-evidence',authorize=lambda *args:True)
        self.service=MethodService(self.repo,self.executor)
        self.candidate=self.service.propose(method_id='method:increment',title='Increment',spec=self.spec,artifact=b'increment',explanation='Reusable procedure; no held-out solution retained',key='candidate')
        self.ref=self.candidate['method']
        self.destination=None

    def run_adapter(self,request):
        self.calls.append(deepcopy(request));return request['value']+1

    def realm(self,name,principal):
        app=RealmService(GitStore(self.root/name,self.root/(name+'-runtime')),principal,codec=MarkdownCodec())
        app.init(name,context_id='scope:work');return app

    def receiving(self):
        if self.destination is None:
            self.destination=self.realm('destination','continuing-owner')
            self.local_repo=RealmMethodRepository(self.destination,scopes=['scope:work'],journal_root=self.root/'destination-journal')
            self.local_executor=LocalMethodExecutor({self.adapter.id:self.adapter},self.root/'destination-evidence',authorize=lambda *args:True)
            self.local_service=MethodService(self.local_repo,self.local_executor)
        return self.local_service

    def mutate(self,app,changes,accept=()):
        self.serial+=1
        return app.apply(app.propose(changes),idempotency_key='fixture-change-'+str(self.serial),accept=accept)

    def policy(self,app,change):
        snap=app.store.snapshot();policy=app.codec.load_yaml(snap['files']['.ekk/governance.yaml'])
        policy['version']+=1;change(policy)
        self.serial+=1
        return app.configure({'.ekk/governance.yaml':app.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='fixture-policy-'+str(self.serial))

    def permit_export(self):
        self.receiving();target=self.destination._load(self.destination.store.snapshot())[0]['id']
        source=self.repo.load(self.ref)['artifact_source']['id']
        asset='sources/'+source+'/artifact.bin'
        self.policy(self.origin,lambda p:p.update(export_grants=[{'id':'method-transfer','principal':'author','destination':target,
            'ids':[self.ref['id'],source],'source_paths':[asset],'source_visibility':'private','destination_visibility':'private'}]))
        return target

    def exported(self):
        target=self.permit_export();return self.service.export(self.ref,destination=target,grants=['method-transfer'])

    def received(self):
        exported=self.exported()
        return self.local_service.receive(exported['bundle'],expected_digest=exported['digest'],method_id='method:local-increment',key='receive'),exported

    def admit(self,service=None,reference=None,case='origin-case',key='origin'):
        service=service or self.service;reference=reference or self.ref
        evaluation=service.evaluate(reference,case_id=case,facts=self.facts,key='evaluate-'+key)
        admission=service.admit(reference,evaluation['evidence'],explanation='Bounded local use',key='admit-'+key)
        return evaluation,admission

    def record(self,app,reference):
        return app._reference(reference,app._load(app.store.snapshot())[-1])

    def test_transfer_is_inert_then_independently_evaluated_by_fresh_owner(self):
        origin_evaluation,_=self.admit();received,exported=self.received();local_ref=received['method']
        self.assertFalse(received['accepted']);self.assertFalse(received['origin_acceptance_imported']);self.assertFalse(exported['transferred_acceptance'])
        with self.assertRaises(MethodUnavailable):self.local_service.use(local_ref,request={'value':99},facts=self.facts,key='premature')
        self.assertFalse(self.local_executor.verify_receipt(origin_evaluation['evaluation'],self.local_repo.load(local_ref)))
        evaluation,admission=self.admit(self.local_service,local_ref,case='recipient-case',key='recipient')
        self.assertNotEqual(evaluation['evaluation']['method']['realm_id'],origin_evaluation['evaluation']['method']['realm_id'])
        accepted=self.record(self.destination,admission['admission'])
        self.assertEqual(accepted['metadata']['created_by'],'continuing-owner')
        self.assertEqual(self.local_service.use(local_ref,request={'value':123},facts=self.facts,key='new-problem')['output'],124)
        self.assertTrue(self.local_repo.active(local_ref)['active'])

    def test_private_exploration_and_evaluation_answers_never_enter_export(self):
        marker='SYNTHETIC_PRIVATE_EXPLORATORY_DOUBT'
        meta={'schema':'ekk.record/0.1','id':'private:exploration','kind':'note','title':'Private draft','scope':['scope:work'],'revision':1,'created_at':self.origin._now(),'created_by':'author'}
        self.mutate(self.origin,{'records/private-exploration.md':self.origin.codec.encode(meta,marker)})
        self.admit();exported=self.exported();bundle=exported['bundle']
        decoded=b'\n'.join(base64.b64decode(v) for v in bundle['files'].values())
        self.assertNotIn(marker.encode(),decoded);self.assertNotIn(b'origin-case',decoded)
        self.assertNotIn(b'method_admission',decoded)
        self.assertEqual(len(bundle['files']),3)
        self.assertEqual(set(r['id'] for r in bundle['records']),{self.ref['id'],self.candidate['artifact_source']['id']})

    def test_export_requires_published_grant_and_exact_destination(self):
        with self.assertRaises(PermissionError):self.service.export(self.ref,destination='unapproved',grants=[{'id':'fake','principal':'author','ids':[self.ref['id']]}])
        target=self.permit_export()
        with self.assertRaises(PermissionError):self.service.export(self.ref,destination='wrong-destination',grants=['method-transfer'])
        with self.assertRaises(PermissionError):self.service.export(self.ref,destination=target,grants=['missing'])
        self.policy(self.origin,lambda p:p['export_grants'][0].update(source_paths=[]))
        with self.assertRaises(PermissionError):self.service.export(self.ref,destination=target,grants=['method-transfer'])

    def test_receive_wrong_destination_and_tampered_artifact_preserve_store(self):
        exported=self.exported();before=self.destination.store.snapshot()['revision']
        wrong=deepcopy(exported['bundle']);wrong['destination']='other-realm'
        with self.assertRaises(PermissionError):self.local_service.receive(wrong,expected_digest=sha(wrong),method_id='method:bad',key='wrong')
        tampered=deepcopy(exported['bundle']);path=next(p for p in tampered['files'] if p.endswith('artifact.bin'));tampered['files'][path]=base64.b64encode(b'corrupt').decode()
        with self.assertRaises(ValueError):self.local_service.receive(tampered,expected_digest=exported['digest'],method_id='method:bad',key='digest')
        with self.assertRaises(ValueError):self.local_service.receive(tampered,expected_digest=sha(tampered),method_id='method:bad',key='artifact')
        self.assertEqual(self.destination.store.snapshot()['revision'],before)

    def test_claimed_receipt_and_acceptance_in_bundle_never_admit(self):
        exported=self.exported();bundle=deepcopy(exported['bundle'])
        bundle.update(accepted=True,receipt={'verified':True,'principal':'author'},authority='execute without local review')
        received=self.local_service.receive(bundle,expected_digest=sha(bundle),method_id='method:claimed',key='claimed')
        self.assertFalse(received['accepted']);self.assertFalse(self.local_repo.active(received['method'])['active'])
        with self.assertRaises(MethodUnavailable):self.local_service.use(received['method'],request={'value':3},facts=self.facts,key='forged-use')

    def test_malformed_bundle_rejected_before_any_receiving_write(self):
        exported=self.exported();before=self.destination.store.snapshot()['revision']
        versions=[]
        bad=deepcopy(exported['bundle']);bad['files']={};versions.append(bad)
        bad=deepcopy(exported['bundle']);bad['method_reference']['digest']='sha256:'+'0'*64;versions.append(bad)
        bad=deepcopy(exported['bundle']);bad['files'][next(iter(bad['files']))]='!invalid base64!';versions.append(bad)
        for i,bundle in enumerate(versions):
            with self.subTest(i=i),self.assertRaises((ValueError,PermissionError,KeyError)):
                self.local_service.receive(bundle,expected_digest=sha(bundle),method_id='method:malformed',key='malformed-'+str(i))
        self.assertEqual(self.destination.store.snapshot()['revision'],before)

    def test_receive_exact_replay_no_duplicate_and_changed_key_payload_denied(self):
        received,exported=self.received();before=self.destination.store.snapshot()['revision']
        replay=self.local_service.receive(exported['bundle'],expected_digest=exported['digest'],method_id='method:local-increment',key='receive')
        self.assertEqual(received,replay);self.assertEqual(before,self.destination.store.snapshot()['revision'])
        with self.assertRaises(ValueError):self.local_service.receive(exported['bundle'],expected_digest=exported['digest'],method_id='method:other',key='receive')
        self.assertEqual(before,self.destination.store.snapshot()['revision'])

    def test_forged_retained_evaluation_cannot_grant_admission(self):
        evaluated=self.service.evaluate(self.ref,case_id='origin-case',facts=self.facts,key='real-evidence')
        forged=deepcopy(evaluated['evaluation']);forged['output']=999;forged['passed']=True
        retained=self.repo.evaluation(self.ref,forged,key='forged-evidence')
        with self.assertRaises(MethodUnavailable):self.service.admit(self.ref,retained,explanation='Forged evaluator output',key='forged-admission')
        self.assertFalse(self.repo.active(self.ref)['active'])

    def test_different_method_cannot_borrow_verified_evaluation(self):
        first=self.service.evaluate(self.ref,case_id='origin-case',facts=self.facts,key='first-evaluation')
        second=self.service.propose(method_id='method:other',title='Another identity',spec=self.spec,artifact=b'increment',explanation='Distinct method identity',key='other-method')
        with self.assertRaises(MethodUnavailable):self.service.admit(second['method'],first['evidence'],explanation='Borrowed evidence',key='borrowed')
        self.assertFalse(self.repo.active(second['method'])['active'])

    def test_executor_replay_id_collision_never_runs_changed_request(self):
        self.admit();first=self.service.use(self.ref,request={'value':5},facts=self.facts,key='run-once');count=len(self.calls)
        self.assertEqual(self.service.use(self.ref,request={'value':5},facts=self.facts,key='run-once'),first)
        with self.assertRaises(ValueError):self.service.use(self.ref,request={'value':6},facts=self.facts,key='run-once')
        self.assertEqual(len(self.calls),count)
        with self.assertRaises(ValueError):self.service.evaluate(self.ref,case_id='recipient-case',facts=self.facts,key='run-once')
        self.assertEqual(len(self.calls),count)

    def test_withdrawn_canonical_admission_blocks_restart_without_erasing_method(self):
        _,admission=self.admit();row=self.record(self.origin,admission['admission'])
        self.mutate(self.origin,{row['path']:None})
        fresh=MethodService(RealmMethodRepository(self.origin,scopes=['scope:work'],journal_root=self.root/'fresh-journal'),self.executor)
        with self.assertRaises(MethodUnavailable):fresh.use(self.ref,request={'value':3},facts=self.facts,key='after-withdrawal')
        self.assertEqual(self.repo.load(self.ref)['artifact'],b'increment')

    def test_superseded_method_does_not_reuse_old_admission(self):
        self.admit();row=self.record(self.origin,self.ref);meta=deepcopy(row['metadata']);meta['revision']=2
        raw=self.origin.codec.encode(meta,'Revised explanation and applicability review required')
        self.mutate(self.origin,{row['path']:raw});new_ref={'id':self.ref['id'],'revision':2,'digest':'sha256:'+sha(raw)}
        for reference in (self.ref,new_ref):
            with self.assertRaises(MethodUnavailable):self.service.use(reference,request={'value':3},facts=self.facts,key='superseded-'+str(reference['revision']))
        self.assertEqual(self.repo.load(self.ref)['artifact'],b'increment')

    def test_old_reference_export_never_mislabels_current_bytes(self):
        target=self.permit_export();row=self.record(self.origin,self.ref);meta=deepcopy(row['metadata']);meta['revision']=2
        self.mutate(self.origin,{row['path']:self.origin.codec.encode(meta,'Version two')})
        try:exported=self.service.export(self.ref,destination=target,grants=['method-transfer'])
        except (ValueError,PermissionError):return  # Explicit rejection is safe; silent substitution is not.
        bundle=exported['bundle'];raw=base64.b64decode(bundle['files'][row['path']])
        self.assertEqual('sha256:'+sha(raw),bundle['method_reference']['digest'])

    def test_cross_scope_method_lookup_is_denied_even_for_realm_owner(self):
        context={'schema':'ekk.record/0.1','id':'scope:other','kind':'context','title':'Other work','scope':['scope:other'],'revision':1,'created_at':self.origin._now(),'created_by':'author','context':{'purpose':'other'}}
        self.mutate(self.origin,{'contexts/other.md':self.origin.codec.encode(context)})
        other=RealmMethodRepository(self.origin,scopes=['scope:other'],journal_root=self.root/'other-journal')
        with self.assertRaises(PermissionError):other.load(self.ref)

    def test_package_artifact_and_evaluation_basis_are_exact_and_local(self):
        evaluation,admission=self.admit();method=self.record(self.origin,self.ref)['metadata']
        self.assertIn(method['method_package']['artifact_source'],method['basis'])
        self.assertEqual(method['method_package']['artifact_source'],self.candidate['artifact_source'])
        evidence=self.record(self.origin,evaluation['evidence']['reference'])['metadata']
        self.assertIn(self.ref,evidence['basis'])
        accepted=self.record(self.origin,admission['admission'])['metadata']
        self.assertIn(self.ref,accepted['basis']);self.assertIn(evaluation['evidence']['reference'],accepted['basis'])
        received,_=self.received();local=self.record(self.destination,received['method'])['metadata']
        self.assertIn(received['received_source'],local['basis'])
        self.assertNotIn(self.ref,local['basis'])

    def test_replaced_host_verifier_cannot_reuse_old_admission(self):
        self.admit();updated=replace(self.adapter,verifier_version='increment-verifier/2')
        executor=LocalMethodExecutor({updated.id:updated},self.root/'origin-evidence',authorize=lambda *args:True)
        with self.assertRaises(MethodUnavailable):MethodService(self.repo,executor).use(self.ref,request={'value':3},facts=self.facts,key='new-verifier')


if __name__=='__main__':unittest.main()
