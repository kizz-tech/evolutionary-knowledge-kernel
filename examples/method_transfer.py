"""Executable preservation, transfer and unlearning; no model calls or real accounts."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.application.methods import MethodService, MethodUnavailable
from ekk.adapters.method_repository import RealmMethodRepository
from ekk.adapters.method_execution import LocalMethodExecutor
from ekk.adapters.builtin_methods import registry, spec, EXCERPT, REFERENCE
from ekk.model.methods import canonical, sha

FACTS={'task_family':'handoff','environment':'synthetic-local','model':'none:deterministic'}


def connect(root, name, principal, initialize=False):
    app=RealmService(GitStore(root/name, root/(name+'-journal')), principal, codec=MarkdownCodec())
    if initialize: app.init(name, context_id='context:work')
    repo=RealmMethodRepository(app, scopes=['context:work'], journal_root=root/'method-proposals')
    executor=LocalMethodExecutor(registry(),root/(name+'-evidence'),authorize=lambda *args:True)
    return app,repo,MethodService(repo,executor)


def fresh(root,name,principal,reference,request,key, *, expected=True):
    packet={'name':name,'principal':principal,'reference':reference,'request':request,'key':key}
    env={k:v for k,v in os.environ.items() if not k.startswith('EKK_')}
    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(root)],
        input=json.dumps(packet),text=True,capture_output=True,env=env)
    if expected and result.returncode:raise AssertionError(result.stderr)
    if not expected and result.returncode==0:raise AssertionError('Unavailable method ran')
    return json.loads(result.stdout) if result.returncode==0 else {'denied':True}


def run(root):
    personal,_,_=connect(root,'a-personal','participant:A',True)
    private=b'SYNTHETIC_PERSONAL_DOUBT_NOT_A_PROJECT_COMMITMENT'
    personal.apply(personal.capture(private,title='Private exploration',scope=['context:work']),idempotency_key='private-exploration')
    app,repo,methods=connect(root,'shared-project','participant:A',True)
    target,target_repo,target_methods=connect(root,'b-personal','participant:B',True)
    candidate=methods.propose(method_id='method:handoff',title='Source-aware handoff',
        spec=spec(EXCERPT),artifact=EXCERPT,explanation='Transfer a usable source identity with the question.',key='create-method')
    ref=candidate['method']
    evaluation=methods.evaluate(ref,case_id='public-training',facts=FACTS,key='evaluate-source')
    methods.admit(ref,evaluation['evidence'],explanation='Offer this version for evaluated synthetic handoffs.',key='admit-source')
    unseen={'question':'What should a successor verify first?','source_id':'public:new-result',
            'source_text':'Verify current acceptance before using a previous result.','source_disclosure':True}
    first=fresh(root,'shared-project','participant:A',ref,unseen,'restart-use')
    assert first['output']['source_digest']==sha(unseen['source_text'].encode())

    # The synthetic owner authorizes exactly these two records and artifact bytes.
    snapshot=app.store.snapshot();governance=app.codec.load_yaml(snapshot['files']['.ekk/governance.yaml'])
    target_id=target.codec.load_yaml(target.store.snapshot()['files']['.ekk/realm.yaml'])['id']
    source_id=candidate['artifact_source']['id']
    source=next(r for r in app.context(['context:work'])['records'] if r['id']==source_id)
    governance['version']+=1
    governance['export_grants']=[{'id':'grant:method-transfer','principal':'participant:A','destination':target_id,
        'ids':[ref['id'],source_id],'source_visibility':'private','destination_visibility':'private',
        'source_paths':[source['metadata']['source']['assets'][0]['path']]}]
    app.configure({'.ekk/governance.yaml':app.codec.dump_yaml(governance)},base=snapshot['revision'],idempotency_key='authorize-method-transfer')
    exported=methods.export(ref,destination=target_id,grants=['grant:method-transfer'])
    assert private.decode() not in canonical(exported).decode()
    received=target_methods.receive(exported['bundle'],expected_digest=exported['digest'],method_id='method:local-handoff',key='receive-method')
    local_ref=received['method']
    fresh(root,'b-personal','participant:B',local_ref,unseen,'inert-transfer',expected=False)
    tested=target_methods.evaluate(local_ref,case_id='public-transfer',facts=FACTS,key='receiver-evaluation')
    target_methods.admit(local_ref,tested['evidence'],explanation='Local admission after independent receiver evaluation.',key='receiver-admission')
    transfer=fresh(root,'b-personal','participant:B',local_ref,unseen,'recipient-new-task')
    assert transfer['output']['source_digest']==first['output']['source_digest']
    adverse=target_methods.reconsider(local_ref,case_id='private-change',facts=FACTS,key='adverse-evaluation')
    assert adverse['review_required'] and target.review(['context:work'])['candidates']
    target_methods.quarantine(local_ref,reason='Disclosure conditions changed; review before further use.')
    fresh(root,'b-personal','participant:B',local_ref,unseen,'quarantine-check',expected=False)
    retired=target_methods.retire(local_ref,explanation='Retire excerpt method after failed disclosure evaluation.',
        basis=[adverse['evidence']['reference']],key='retire-old-version')
    assert not target_repo.active(local_ref)['active']
    assert target_repo.load(local_ref)['artifact']==EXCERPT
    replacement=target_methods.propose(method_id=local_ref['id'],previous=local_ref,title='Source-aware handoff',
        spec=spec(REFERENCE),artifact=REFERENCE,explanation='Retain identity and digest; omit source text.',
        basis=[adverse['evidence']['reference']],key='revise-method')
    next_ref=replacement['method'];assert next_ref['revision']==2
    tested_new=target_methods.evaluate(next_ref,case_id='private-change',facts=FACTS,key='verify-replacement')
    target_methods.admit(next_ref,tested_new['evidence'],explanation='Admit reference method for evaluated synthetic handoffs.',key='admit-replacement')
    private_request={'question':'Can the recipient recognize the basis?','source_id':'allowed:opaque-id',
                     'source_text':'SYNTHETIC_PRIVATE_PAYLOAD','source_disclosure':False}
    safe=fresh(root,'b-personal','participant:B',next_ref,private_request,'replacement-new-session')
    assert 'excerpt' not in safe['output'] and private_request['source_text'] not in canonical(safe['output']).decode()
    assert not target_repo.active(local_ref)['active'] and target_repo.load(local_ref)['artifact']==EXCERPT
    assert all(owner.doctor()['ok'] for owner in (personal,app,target))
    result={'schema':'ekk.method-transfer-demonstration/0.1','status':'passed',
        'checks':{'private_exploration_stays_private':True,'shared_work_survives_fresh_process':True,
                  'exact_authorized_transfer':True,'received_method_inert_until_local_evaluation_and_acceptance':True,
                  'new_participant_new_task':True,'adverse_case_observed':True,'review_candidate_retained':True,
                  'quarantine_blocks_use':True,'canonical_retirement':True,'same_id_next_revision':True,
                  'replacement_works_in_fresh_process':True,'historical_bytes_preserved':True},
        'participants':'two synthetic principals; same trusted OS owner, no hostile-user isolation claim',
        'model_calls':0,'external_deliveries':0,'model_effectiveness':'not_measured','human_understanding':'not_measured',
        'limit':'Deterministic mechanism demonstration, not a comparative productivity or longitudinal study.'}
    (root/'result.json').write_bytes(canonical(result)+b'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='New destination for synthetic evidence; default disposable')
    parser.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:
        request=json.load(sys.stdin)
        _,repo,methods=connect(args.worker,request['name'],request['principal'])
        try:
            result=methods.use(request['reference'],request=request['request'],facts={**FACTS,'model':'none:deterministic:new-session'},key=request['key'])
        except (PermissionError,ValueError) as exc:
            print(str(exc),file=sys.stderr);return 2
    elif args.output:
        root=args.output.expanduser().resolve();root.mkdir(parents=True,exist_ok=False)
        result=run(root)
    else:
        with tempfile.TemporaryDirectory(prefix='ekk-method-transfer-') as temporary:
            result=run(Path(temporary).resolve())
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
