"""Connected daily work, explicit operations and optional practical guidance."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from .command_line import service, _routes, _invalid_json_constant, error_code
from .local_profile import binding, data_home, trusted_principal
from .operational_store import OperationalStore, private_directory
from ..application.work import WorkService
from .work_repository import RealmWorkRepository

GROUPS={
 'work':{'start','update','event','show','find'},
 'queue':{'submit','status','drain','retry','backup','restore'},
 'task':{'create','update','show','list','wait','register-wait','external-attempt','external-outcome'},
 'source':{'add','remove','list','search','fetch'},
 'guide':{'list','show','package'},
 'improve':{'record'},
}


def authorize_controls(app, scopes, *, write=False):
    """Fast enqueue/read of local operations; publication does full validation."""
    snapshot=app.store.snapshot()
    controls=[app.codec.load_yaml(snapshot['files'][path]) for path in
              ('.ekk/realm.yaml','.ekk/governance.yaml','.ekk/packs.lock.yaml')]
    realm,policy,packs=controls
    app.codec.validate_schema('realm',realm)
    if realm.get('schema')!='ekk.realm/0.1' or policy.get('schema')!='ekk.governance/0.1' or packs.get('schema')!='ekk.packs-lock/0.1':raise ValueError('Invalid current controls')
    if policy.get('default_effect')!='deny' or any(c.get('required_semantics') or c.get('requires') for c in controls):raise ValueError('Unsupported current controls')
    # Fast local acknowledgement skips record-wide semantic validation, never
    # the shape of authority. A malformed scalar cannot behave like an action
    # list merely because Python's membership operator finds a substring.
    if not isinstance(policy.get('version',1),int):raise ValueError('Invalid governance version')
    acceptors=policy.get('trusted_acceptors',[])
    if not isinstance(acceptors,list) or any(not isinstance(v,str) or not v for v in acceptors):raise ValueError('Invalid trusted acceptors')
    grants=policy.get('grants',[])
    if not isinstance(grants,list):raise ValueError('Invalid grants')
    for grant in grants:
        if not isinstance(grant,dict) or not isinstance(grant.get('principal'),str) or not grant['principal']:raise ValueError('Invalid grant principal')
        for field in ('actions','scopes'):
            values=grant.get(field)
            if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v for v in values):raise ValueError('Invalid grant '+field)
        if not set(grant['actions'])<={'read','write','accept'}:raise ValueError('Unsupported grant action')
    if not scopes:raise ValueError('Explicit selected contexts required')
    app._authorized(policy,'read',scopes)
    if write:app._authorized(policy,'write',scopes)
    roots=app._roots(realm)['record_roots'];found=set()
    for path,raw in snapshot['files'].items():
        # Read context records only; their names need not equal their IDs.
        if path.endswith('.md') and any(path.startswith(root+'/') for root in roots):
            # This deliberately uses the codec: YAML contents cannot be trusted
            # from filename or a text pattern. The persistent parse cache helps.
            metadata=app.codec.decode(raw)['metadata']
            if metadata.get('kind')=='context' and metadata.get('id') in scopes:
                app.codec.validate_schema('record',metadata);found.add(metadata['id'])
    if set(scopes)!=found:raise ValueError('Selected contexts no longer exist')
    return realm


def resolve(args):
    selected=binding(args.cwd) if not args.root and not args.realm else None
    args.profile=args.profile or (selected[1].get('profile','personal') if selected else 'personal')
    routes=_routes(args)
    if len(routes)!=1:raise ValueError('Select one owning realm for this operation')
    route=routes[0];app=service(route['path'],allowed_scopes=route['scopes'] or None)
    manifest=app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])
    scopes=route['scopes'] or [manifest['default_context']]
    return app,scopes,manifest


def local_store(app, realm):
    key=hashlib.sha256(json.dumps([realm,app.principal],sort_keys=True).encode()).hexdigest()
    # The existing operations/ directory belongs to the strict diagnostics
    # journal and deliberately rejects unrelated files or subdirectories.
    return OperationalStore(data_home()/'work-operations'/key,realm=realm,principal=app.principal)


def route_document(args, realm, scopes):
    return {'cwd':str(args.cwd.expanduser().resolve()),'profile':args.profile,'realm':args.realm,
            'root':str(args.root.expanduser().resolve()) if args.root else None,'scope':list(args.scope),
            'target_realm':realm,'selected_scopes':list(scopes),'principal':trusted_principal()}


def publish(request, key):
    route=request['route']
    if route['principal']!=trusted_principal():raise PermissionError('Queued operation belongs to another principal')
    args=argparse.Namespace(**{k:route[k] for k in ('profile','realm','scope')},
                            cwd=Path(route['cwd']),root=Path(route['root']) if route['root'] else None)
    app,scopes,realm=resolve(args)
    if realm['id']!=route['target_realm'] or not set(route['selected_scopes'])<=set(scopes):
        raise PermissionError('Queued route changed; no automatic reauthorization')
    scopes=route['selected_scopes']
    authorize_controls(app,scopes,write=True)
    operation=request['operation'];payload=dict(request['request'])
    if operation=='retain':
        from .retention import retain_once
        if set(payload)-{'title','body','artifacts','repository_evidence','expected_snapshot','experience','preference','supersedes','decision','basis','aliases'}:raise ValueError('Unsupported retention fields')
        artifacts=[]
        for item in payload.get('artifacts',[]):
            if not isinstance(item,dict) or set(item)-{'body','base64','filename','title'} or ('body' in item)==('base64' in item):raise ValueError('Exact artifact body or base64 required')
            raw=item['body'].encode() if 'body' in item else base64.b64decode(item['base64'],validate=True)
            artifacts.append({'data':raw,**{k:v for k,v in item.items() if k in ('filename','title')}})
        receipt=retain_once(app,artifacts,title=payload.get('title',''),body=payload.get('body',''),scopes=scopes,key=key,
                          expected_snapshot=payload.get('expected_snapshot'),repository_evidence=payload.get('repository_evidence'),
                          experience=payload.get('experience'),preference=payload.get('preference'),supersedes=payload.get('supersedes'),
                          decision=payload.get('decision'),basis=payload.get('basis'),aliases=payload.get('aliases'))
        # The next session in this project is told about the result it has just gained.
        from .experience import card_after_publication
        card_after_publication(args.cwd)
        return receipt
    if operation=='capture':
        from .retention import capture_once
        if set(payload)-{'title','filename','base64','expected_snapshot'}:raise ValueError('Unsupported capture fields')
        return capture_once(app,base64.b64decode(payload['base64'],validate=True),title=payload.get('title',''),scopes=scopes,
                            filename=payload.get('filename',''),key=key,expected_snapshot=payload.get('expected_snapshot'))
    if operation in {'work.start','work.update','work.event','improve.record'}:
        payload['key']=key
        group,action=operation.split('.')
        return canonical_dispatch(app,scopes,group,action,payload)
    raise ValueError('Only registered canonical publication operations can be queued')


def canonical_dispatch(app, scopes, group, operation, request):
    repository=RealmWorkRepository(app,scopes);work=WorkService(repository)
    if group=='work':return getattr(work,operation)(**request)
    if group=='improve':
        from ..application.improvement import improvement
        from ..application.workspace import exact_reference
        if set(request)-{'reference','key','observation','basis'}:raise ValueError('Unknown improvement fields')
        note=improvement(request['observation']);reference=exact_reference(request['reference'])
        basis=[exact_reference(ref) for ref in request.get('basis',[])]
        if len(basis)>32:raise ValueError('Bounded improvement basis required')
        return repository.save(title=None,fields={},key=request['key'],previous=reference,
            event={'kind':'observation','body':json.dumps(note,ensure_ascii=False,indent=2),
                   'basis':basis,'improvement':note})
    raise ValueError('Unknown canonical activity')


def due_audit(app):
    """The full audit of operation evidence, when the store reports it due.

    Writes skip the tree and blob audit of operations that a full pass verified.
    The background publisher owns that pass and repeats it when it is due. A
    refusal is one line in the worker log; the next drain tries again.
    """
    from .file_lock import LockBusy
    from ..model import DirtyWorkingTree
    if not getattr(app.store,'audit_due',lambda:False)():return None
    try:app.store.recover()
    except LockBusy:return None  # another writer is active; the audit stays due
    except Exception as exc:
        code=error_code(exc)
        # The audit records itself as soon as the evidence passed; a working tree
        # or a projection that blocks afterwards is reported per request by the drain.
        if isinstance(exc,DirtyWorkingTree) or not app.store.audit_due():return {'state':'passed','projection':code}
        print(json.dumps({'store_audit':'failed','error':code,'message':str(exc),
                          'next':'Resolve it and run ekk recover, then ekk queue retry for each request.'},
                         ensure_ascii=False),file=sys.stderr,flush=True)
        return {'state':'failed','error':code,'message':str(exc)[:500]}
    return {'state':'passed'}


def start_worker(args, store):
    # Fixed installed entrypoint; no command or executable comes from a queued document.
    command=[sys.executable,'-I','-B','-m','ekk','queue','drain','--background','--cwd',str(args.cwd),'--profile',args.profile]
    if args.realm:command+=['--realm',args.realm]
    if args.root:command+=['--root',str(args.root)]
    if args.state_dir:command+=['--state-dir',str(args.state_dir)]
    for scope in args.scope:command+=['--scope',scope]
    path=store.directory/'worker.log'
    fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'ab') as log:
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                                 close_fds=True,start_new_session=True)
    return {'started':True,'pid':process.pid,'meaning':'Worker spawned; publication status is in the outbox.'}


def execute(group, args, request):
    operation=args.operation
    if group=='guide':
        from ..application.practices import PRACTICES,practice
        if operation=='list':result={'domains':list(PRACTICES),'required':False}
        elif operation=='show':result=practice(args.domain,request)
        else:
            from .practical_methods import artifact,spec
            if args.domain not in PRACTICES:raise ValueError('Choose a known practice domain')
            result={'spec':spec(args.domain),'artifact_base64':base64.b64encode(artifact(args.domain)).decode(),
                    'admitted':False,'next':'Use the ordinary method proposal, evaluation and admission lifecycle if adoption is wanted.'}
    else:
        app,scopes,realm=resolve(args)
        write=not (operation in {'find','show','list','search','fetch','status','backup'})
        authorize_controls(app,scopes,write=write)
        if group in {'work','improve'}:
            if group=='work' and operation=='find':request.setdefault('query',args.query)
            result=canonical_dispatch(app,scopes,group,operation,request)
        else:
            if args.state_dir or (group=='queue' and operation in {'backup','restore'}):
                if app.allowed_scopes is not None or realm['owner']!=app.principal:raise PermissionError('Operational administration requires an explicit full realm owner route')
                policy=app.codec.load_yaml(app.store.snapshot()['files']['.ekk/governance.yaml'])
                app._authorized(policy,'read',['*']);app._authorized(policy,'write',['*'])
            store=OperationalStore(args.state_dir,realm=realm['id'],principal=app.principal) if args.state_dir else local_store(app,realm['id'])
            try:
                if group=='task':result=store.task(scopes,operation,request)
                elif group=='source':
                    from .authored_sources import AuthoredSources
                    sources=AuthoredSources(store.directory/'author-sources')
                    if operation=='add':result=sources.configure(request['alias'],request['root'],scopes)
                    elif operation=='remove':result=sources.remove(request['alias'],scopes)
                    elif operation=='list':result={'sources':{k:v for k,v in sources.entries().items() if set(v['scopes'])<=set(scopes)}}
                    elif operation=='fetch':result=sources.fetch(scopes,**request)
                    else:result=sources.search(scopes,request.get('query',args.query),limit=request.get('limit',10))
                elif operation=='submit':
                    if request.get('operation') not in {'retain','capture','work.start','work.update','work.event','improve.record'} or not isinstance(request.get('request'),dict):raise ValueError('Registered operation and request required')
                    frozen={'route':route_document(args,realm['id'],scopes),'operation':request['operation'],'request':request['request']}
                    result=store.enqueue(request.get('key'),frozen,scopes)
                    if not args.no_start:
                        try:result['worker']=start_worker(args,store)
                        except OSError as exc:result['worker']={'started':False,'error':str(exc),'next':'Run ekk queue drain; the request is already durable.'}
                elif operation=='drain':
                    import time
                    from .file_lock import LockBusy
                    retries=0
                    audit={}
                    def prepare():  # under the worker lock, once per drain: a concurrent worker leaves quietly
                        if args.background and not audit:audit.update(due_audit(app) or {'state':'not_due'})
                        return audit
                    for _ in range(100):
                        try:result=store.drain(scopes,publish,limit=request.get('limit',10),prepare=prepare)
                        except LockBusy:
                            # A live worker holds the outbox and takes later requests in its next pass.
                            if not args.background:raise
                            result=store.status(scopes);break
                        # A request queued while this pass was publishing is taken now, not left for a later trigger.
                        if any(row['state']=='local_pending' for row in result['operations']):continue
                        retry=[row for row in result['operations'] if row['state']=='retry_pending']
                        if not retry or retries==2:break
                        retries+=1
                        time.sleep(min(8,max(0,min(row['next_attempt'] for row in retry)-time.time())))
                    if audit.get('state') in ('passed','failed'):result['store_audit']=audit
                elif operation=='retry':
                    result=store.retry(scopes,request['key'])
                    if not args.no_start:result['worker']=start_worker(args,store)
                elif operation=='backup':
                    # A complete operational backup may include other contexts.
                    if app.allowed_scopes is not None or realm['owner']!=app.principal:raise PermissionError('Operational backup requires an explicit full realm owner route')
                    result=store.backup(request['destination'])
                elif operation=='restore':
                    result=OperationalStore.restore(request['archive'],request['destination'],expected_sha256=request['sha256'],realm=realm['id'],principal=app.principal)
                else:result=store.status(scopes,key=request.get('key'))
            finally:store.close()
    return result


def main(group, argv=None):
    parser=argparse.ArgumentParser(prog='ekk '+group,description=__doc__)
    parser.add_argument('operation',choices=sorted(GROUPS[group]))
    parser.add_argument('--cwd',type=Path,default=Path.cwd());parser.add_argument('--profile',default=os.environ.get('EKK_PROFILE'))
    parser.add_argument('--realm');parser.add_argument('--root',type=Path);parser.add_argument('--scope',action='append',default=[])
    parser.add_argument('--json',type=Path);parser.add_argument('--stdin',action='store_true')
    parser.add_argument('--key');parser.add_argument('--query',default='');parser.add_argument('--domain')
    parser.add_argument('--no-start',action='store_true',help='Queue durably without starting a publisher')
    parser.add_argument('--background',action='store_true',help='drain: leave quietly when another publisher is already running')
    parser.add_argument('--state-dir',type=Path,help='Explicit isolated operational recovery directory; full realm owner only')
    args=parser.parse_args(argv)
    try:
        if args.json and args.stdin:raise ValueError('Choose one JSON input')
        request=json.loads(args.json.read_text() if args.json else sys.stdin.read(),parse_constant=_invalid_json_constant) if args.json or args.stdin else {}
        if not isinstance(request,dict):raise ValueError('Object request required')
        if args.key:
            if request.get('key',args.key)!=args.key:raise ValueError('Conflicting logical keys')
            request['key']=args.key
        from .operation_diagnostics import observed_call
        result=observed_call(group+'.'+args.operation,lambda:execute(group,args,request),key=request.get('key'))
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps({'error':error_code(exc),'message':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
