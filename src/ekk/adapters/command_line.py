"""JSON transport and local composition root for the current EKK application."""
from __future__ import annotations
import argparse
import base64
import hashlib
import fcntl
import json
import os
from pathlib import Path
import sys
import uuid
import yaml
from .local_profile import LocalProfile, binding, config_home, data_home, trusted_principal, published_manifest

OPERATIONS={'doctor','context','capture','propose','apply','review','assurance','export'}


def service(root, *, realm_id=None, allowed_scopes=None):
    from .git_store import GitStore
    from .markdown import MarkdownCodec
    from .packs import PackDirectory
    from ..assets import pack_directory
    from ..application import RealmService
    root=Path(root).expanduser().resolve()
    manifest_path=root/'.ekk/realm.yaml'
    if manifest_path.is_file():
        manifest=published_manifest(root)
        identity=manifest['id']
        if realm_id and realm_id != identity:raise ValueError('Realm identity mismatch')
    else:
        identity=realm_id or 'urn:uuid:'+str(uuid.uuid4())
    key=hashlib.sha256(identity.encode()).hexdigest()
    if manifest_path.exists() and not (root/'.git').is_dir():
        from .contained_store import ContainedGitStore
        import subprocess
        branch=subprocess.run(['git','-C',str(root.parent),'symbolic-ref','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
        storage=ContainedGitStore(root,root.parent,branch,data_home()/key)
    else:storage=GitStore(root,runtime_dir=data_home()/key)
    app=RealmService(storage,principal=trusted_principal(),codec=MarkdownCodec(),allowed_scopes=allowed_scopes,pack_loader=PackDirectory(pack_directory()))
    app.initial_realm_id=identity
    return app


def parser():
    p=argparse.ArgumentParser(prog='ekk',description='Personal work entry, shared continuity and revisable methods. Start with enter --task; methods: ekk method --help')
    p.add_argument('operation',choices=sorted(OPERATIONS|{'init','enter','recover'}))
    p.add_argument('--root',type=Path)
    p.add_argument('--profile',default=os.environ.get('EKK_PROFILE'))
    p.add_argument('--realm',help='Alias in the active role profile')
    p.add_argument('--cwd',type=Path,default=Path.cwd())
    p.add_argument('--json',type=Path,help='JSON request file; omit to use command options')
    p.add_argument('--stdin',action='store_true',help='Read JSON request from stdin')
    p.add_argument('--scope',action='append',default=[])
    p.add_argument('--task',default='')
    p.add_argument('--personal',action='store_true',help='Include explicitly configured personal home on enter')
    p.add_argument('--resume',help='Exact JSON reference with realm, id, revision and digest on enter')
    p.add_argument('--budget',type=int,default=16000)
    p.add_argument('--compact',action='store_true',help='Display enter/context without historical metadata duplication; command options only')
    p.add_argument('--file',type=Path)
    p.add_argument('--title',default='')
    p.add_argument('--idempotency-key')
    p.add_argument('--accept',action='append',default=[])
    p.add_argument('--id',action='append',default=[])
    p.add_argument('--destination')
    p.add_argument('--revision')
    p.add_argument('--workspace',action='store_true')
    return p


def _invalid_json_constant(value):
    raise ValueError('Nonstandard JSON constant: '+value)


def _input(args):
    if args.json and args.stdin:raise ValueError('Choose one JSON input')
    result=json.loads(args.json.read_text() if args.json else sys.stdin.read(),parse_constant=_invalid_json_constant) if args.json or args.stdin else {}
    if not isinstance(result,dict):raise ValueError('JSON request must be an object')
    return result


def _routes(args):
    if args.root:
        return [{'path':args.root.expanduser().resolve(),'scopes':args.scope,'alias':None}]
    profile=LocalProfile(args.profile)
    if args.realm:
        root,manifest=profile.resolve(args.realm)
        scopes=args.scope or ([manifest['default_context']] if manifest.get('default_context') else [])
        return [{'path':root,'scopes':scopes,'alias':args.realm}]
    _,workspace,routes=profile.workspace(args.cwd)
    for route in routes:route['workspace_id']=workspace['workspace_id']
    if args.scope:
        for route in routes:
            if not set(args.scope)<=set(route['scopes']):raise ValueError('Scope outside workspace binding')
            route['scopes']=args.scope
    return routes


def dispatch(args, request):
    op=args.operation
    if args.profile is None:
        selected=binding(args.cwd) if not args.root and not args.realm else None
        args.profile=selected[1].get('profile','personal') if selected else 'personal'
    if request.get('operation') and request['operation']!=op:raise ValueError('Request operation differs from CLI operation')
    if 'payload' in request:
        if not isinstance(request['payload'],dict):raise ValueError('payload must be an object')
        request={**request['payload'],**{k:v for k,v in request.items() if k!='payload'}}
    if 'target_scope' in request:
        if 'scopes' in request and request['scopes']!=request['target_scope']:raise ValueError('Conflicting scope declarations')
        request['scopes']=request['target_scope']
    if 'expected_snapshot' in request and op=='propose':request['base']=request['expected_snapshot']
    if (args.personal or args.resume is not None or 'resume' in request or 'personal' in request) and op != 'enter':
        raise ValueError('personal and resume are enter options only')
    if op=='init' and args.workspace:
        if not args.realm or not args.scope:raise ValueError('Workspace init requires --realm and --scope')
        profile=LocalProfile(args.profile);realm_path,realm_manifest=profile.resolve(args.realm)
        from ..model import validate_identifier
        for scope in args.scope:validate_identifier(scope)
        if len(args.scope)!=len(set(args.scope)):raise ValueError('Duplicate context IDs')
        service(realm_path,allowed_scopes=args.scope).context(args.scope,task='',budget=1)
        root=args.cwd.expanduser().resolve();target=root/'.ekk/workspace.yaml'
        if any(p.is_symlink() for p in (target,*target.parents)):raise ValueError('Binding path must not traverse symlinks')
        if target.exists():raise ValueError('Workspace binding already exists')
        target.parent.mkdir(parents=True,exist_ok=True)
        doc={'schema':'ekk.workspace/0.1','workspace_id':'urn:uuid:'+str(uuid.uuid4()),'profile':args.profile,'bindings':[{'realm_alias':args.realm,'realm_id':realm_manifest['id'],'contexts':args.scope}],'packs':[],'execution':{'checks':[]}}
        with target.open('x') as stream:stream.write(yaml.safe_dump(doc,sort_keys=False))
        return {'status':'initialized','workspace':str(root),'binding':doc}
    if op=='init':
        if not args.root:raise ValueError('Realm init requires --root')
        if request.get('realm_id') and request.get('target_realm') and request['realm_id']!=request['target_realm']:raise ValueError('Conflicting realm declarations')
        app=service(args.root,realm_id=request.get('realm_id') or request.get('target_realm'))
        app.init(title=args.title or request.get('title','Knowledge'),realm_id=app.initial_realm_id,**{k:request[k] for k in ('context_title','owner','context_id','default_visibility','packs') if k in request})
        return {'status':'initialized','realm_id':app.initial_realm_id,'doctor':app.doctor()}
    if op == 'enter' and (args.personal or args.resume is not None or 'resume' in request or 'personal' in request or (not args.root and not args.realm and binding(args.cwd) is None)):
        return workspace_entry(args, request)
    routes=_routes(args)
    if op not in {'enter','context','doctor','review','assurance'} and len(routes)!=1:
        raise ValueError('Mutation/export requires one explicit realm')
    results=[]
    for route in routes:
        app=service(route['path'],allowed_scopes=route['scopes'] or None);scopes=request.get('scopes',route['scopes'])
        if route['scopes'] and not set(scopes)<=set(route['scopes']):raise ValueError('JSON scope outside binding')
        if request.get('workspace_id') and request['workspace_id']!=route.get('workspace_id'):raise ValueError('Request workspace differs from resolved binding')
        manifest=app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])
        if request.get('target_realm') and request['target_realm']!=manifest['id']:raise ValueError('Request realm differs from resolved binding')
        expected=request.get('expected_snapshot')
        if expected and op=='apply' and request.get('proposal',request).get('base')!=expected:raise ValueError('Proposal base differs from expected snapshot')
        if expected and op=='capture' and app.store.snapshot()['revision']!=expected:raise ValueError('Capture snapshot is stale')
        if op in {'context','enter'}:
            result=app.context(scopes,task=request.get('task',args.task),budget=request.get('budget',args.budget))
            result['index']=cache_context(result)
            if op == 'enter':
                from ..application.workspace import work_view
                result['work_view'] = work_view(result, method_availability(app, scopes))
        elif op=='doctor':result=app.doctor(revision=args.revision)
        elif op=='review':result=app.review(scopes)
        elif op=='assurance':result=app.assurance(scopes)
        elif op=='capture':
            if args.file:
                data=args.file.read_bytes();filename=args.file.name
            else:
                data=request.get('body','').encode();filename=request.get('filename','original.md')
            key=args.idempotency_key or request.get('idempotency_key') or request.get('request_id')
            if not isinstance(key,str) or not key:raise ValueError('capture requires an idempotency key or request_id')
            result=capture_once(app,data,title=args.title or request.get('title','Source'),scopes=scopes,filename=filename,key=key)
        elif op=='propose':
            changes={}
            for path,value in request.get('changes',{}).items():
                if value is None:changes[path]=None
                elif isinstance(value,str):changes[path]=value.encode()
                elif isinstance(value,dict) and set(value)=={'base64'}:changes[path]=base64.b64decode(value['base64'],validate=True)
                else:raise ValueError('Changes require text, base64 object, or null')
            result=app.propose(changes,base=request.get('base'),grounds=request.get('grounds'),explanation=request.get('explanation'))
        elif op=='apply':
            key=args.idempotency_key or request.get('idempotency_key')
            if not key:raise ValueError('apply requires an idempotency key')
            result=app.apply(request.get('proposal',request),idempotency_key=key,accept=args.accept or request.get('accept',[]))
        elif op=='export':
            result=app.export(args.id or request.get('ids',[]),destination=args.destination or request.get('destination'),grants=request.get('grants',[]))
        elif op=='recover':result=app.store.recover()
        else:raise ValueError('Unknown operation')
        if isinstance(result,dict):
            result.setdefault('realm_alias',route['alias'])
        results.append(result)
    if len(results)==1:return results[0]
    return {'schema':'ekk.federated-context/0.1','atomic_across_realms':False,'contexts':results}


def cache_context(result):
    """Index only the authorized emitted projection; never feed cache into authority."""
    from .sqlite_index import SQLiteIndex,index_key
    from .local_profile import cache_home
    manifest=result['manifest']
    key=index_key(realm=manifest['realm_id'],grant=[manifest['principal'],result['scopes']],snapshot=manifest['snapshots'],policy=manifest['policy_digest'],packs=manifest['packs_digest'],query=[result['task'],manifest['budget_bytes']])
    index=SQLiteIndex(cache_home()/'projections'/(key+'.sqlite'))
    index.rebuild([{'id':str(i)+':'+r['id'],'title':r['metadata']['title'],'body':r['body']} for i,r in enumerate(result['records'])],key=key)
    return {'disposable':True,'key':key,'records':len(result['records']),'coverage':'authorized emitted projection only'}


def capture_once(app,data,*,title,scopes,filename,key):
    from .git_store import _atomic
    # Journals are durable private runtime data, never a cache or a second writer.
    manifest=app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])
    identity={'realm_id':manifest['id'],'principal':app.principal,'key':key}
    name=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    directory=data_home()/'capture-requests';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/(name+'.json')
    request_digest=hashlib.sha256(json.dumps([identity,title,scopes,filename,hashlib.sha256(data).hexdigest()],sort_keys=True).encode()).hexdigest()
    with (directory/(name+'.lock')).open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        # Enforce current scope authority before persisting a request or replaying it.
        app.context(scopes,task='',budget=1)
        if path.exists():
            row=json.loads(path.read_text())
            if row['request_digest']!=request_digest:raise ValueError('Idempotency key already bound to another capture')
        else:
            row={'request_digest':request_digest,'proposal':app.capture(data,title=title,scope=scopes,filename=filename)}
            _atomic(path,json.dumps(row,sort_keys=True).encode())
        receipt=app.apply(row['proposal'],idempotency_key=key)
        references=[]
        for relative,encoded in row['proposal']['changes'].items():
            if encoded is None or not relative.endswith('.md') or not any(relative.startswith(root+'/') for root in manifest['storage']['record_roots']):continue
            raw=base64.b64decode(encoded)
            try:metadata=app.codec.decode(raw)['metadata']
            except ValueError:continue
            if metadata.get('kind')=='source':references.append({'id':metadata['id'],'revision':metadata['revision'],'digest':'sha256:'+hashlib.sha256(raw).hexdigest()})
        return {**receipt,'source_references':references}

def error_code(exc):
    from ..model import Conflict, RecoveryConflict, StoreError
    if isinstance(exc,PermissionError):return 'access_denied'
    if isinstance(exc,RecoveryConflict):return 'recovery_required'
    if isinstance(exc,Conflict):return 'stale_snapshot'
    if isinstance(exc,FileNotFoundError):return 'source_unavailable'
    message=str(exc).lower()
    if 'unsupported' in message or 'unknown mandatory' in message:return 'unsupported_capability'
    if any(word in message for word in ('binding','profile','realm alias')):return 'unresolved_binding'
    if isinstance(exc,StoreError):return 'recovery_required'
    return 'invalid_format'

def _common_request(request):
    return any(key in request for key in ('request_id','operation','payload'))


def _failed(result):
    if not isinstance(result,dict):return False
    return bool(result.get('blocked') or result.get('valid') is False or result.get('ok') is False or any(_failed(item) for item in result.get('contexts',[])))


def result_envelope(request, operation, data, *, error=False):
    """Normalize observed output only; this transport adds no verification."""
    def snapshot(value):
        if not isinstance(value,dict):return None
        if value.get('manifest',{}).get('snapshots') is not None:return value['manifest']['snapshots']
        for key in ('revision','origin_snapshot','base'):
            if value.get(key) is not None:return value[key]
        if 'doctor' in value:return snapshot(value['doctor'])
        if 'contexts' in value:return [snapshot(item) for item in value['contexts']]
        return None
    def evidence(value):
        if not isinstance(value,dict):return [],[],False,[],[]
        manifest=value.get('manifest',{})
        refs=list(manifest.get('used_refs',[]))+list(value.get('source_references',[]))
        if value.get('schema')=='ekk.export/0.1':refs.extend({'id':ref['id'],'revision':ref['revision'],'digest':ref['digest']} for ref in value.get('records',[]))
        warnings=list(value.get('warnings',[]))+list(value.get('limitations',[]))+list(value.get('unknowns',[]))+list(value.get('unverified',[]))
        incomplete=bool(value.get('incomplete') or manifest.get('incomplete') or value.get('impact',{}).get('scopes_complete') is False or value.get('status')=='unbound' or _failed(value))
        if value.get('status')=='unbound':warnings.append(value.get('instruction','No knowledge binding was resolved.'))
        guarantees=value.get('guarantees',{})
        verified=list(guarantees.get('verified',[])) if isinstance(guarantees,dict) else []
        unverified=list(value.get('guarantees_not_verified',[]))
        if isinstance(guarantees,dict):unverified.extend(guarantees.get('unverified',[]))
        children=value.get('contexts',[])+([value['doctor']] if isinstance(value.get('doctor'),dict) else [])
        for child in children:
            child_refs,child_warnings,child_incomplete,child_verified,child_unverified=evidence(child)
            refs.extend(child_refs);warnings.extend(child_warnings);incomplete|=child_incomplete
            verified.extend(child_verified);unverified.extend(child_unverified)
        return refs,warnings,incomplete,verified,unverified
    refs,warnings,incomplete,verified,unverified=evidence(data)
    return {'schema':'ekk.result/0.1','request_id':request.get('request_id'),'operation':operation,'status':'error' if error else 'unbound' if isinstance(data,dict) and data.get('status')=='unbound' else 'blocked' if _failed(data) else 'completed','snapshot':snapshot(data),'data':data,'source_references':refs,'incomplete':bool(error or incomplete),'warnings':warnings,'guarantees':{'verified':verified,'unverified':unverified}}


def main(argv=None):
    args=parser().parse_args(argv);request={};common=False
    try:
        request=_input(args);common=_common_request(request)
        if args.compact and (args.operation not in {'enter','context'} or args.json or args.stdin):
            raise ValueError('--compact supports enter/context command options only; JSON requests retain the full response contract')
        if common:
            if 'request_id' in request and (not isinstance(request['request_id'],str) or not request['request_id']):raise ValueError('request_id must be nonempty text')
            if 'operation' in request and request['operation']!=args.operation:raise ValueError('Request operation differs from CLI operation')
        result=dispatch(args,request)
        output=result_envelope(request,args.operation,result) if common else result
        if args.compact:
            from .context_display import compact_context
            output=compact_context(result)
        print(json.dumps(output,ensure_ascii=False,indent=2,default=str))
        failed=_failed(result) if common else isinstance(result,dict) and (result.get('blocked') or result.get('valid') is False or result.get('ok') is False)
        if failed:return 1
        return 0
    except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
        result={'error':error_code(exc),'message':str(exc)}
        output=result_envelope(request,args.operation,result,error=True) if common else result
        print(json.dumps(output,ensure_ascii=False),file=sys.stderr)
        return 2


def workspace_entry(args, request):
    from ..application.workspace import WorkspaceService, exact_reference
    personal = request.get('personal', args.personal)
    if type(personal) is not bool:
        raise ValueError('personal must be boolean')
    if args.resume is not None and 'resume' in request:
        raise ValueError('Choose one resume reference')
    resume = json.loads(args.resume, parse_constant=_invalid_json_constant) if args.resume is not None else request.get('resume')
    if args.resume is not None or 'resume' in request:
        resume = exact_reference(resume)
    bound = bool(args.root or args.realm or binding(args.cwd) is not None)
    routes = _routes(args) if bound else []
    for route in routes:
        route['owner_projection'] = 'shared'
    if personal or not bound:
        try:
            profile = LocalProfile(args.profile)
        except ValueError as exc:
            if str(exc) != 'Role profile unavailable' or personal:
                raise
            profile = None
        home = profile.home() if profile else None
        if personal and home is None:
            raise ValueError('Explicit personal home unavailable')
        if home:
            home['owner_projection'] = 'personal'
            routes.append(home)
    prepared = []
    for route in routes:
        scopes = request.get('scopes', route['scopes'])
        if args.scope and not bound:
            scopes = args.scope
        if not set(scopes) <= set(route['scopes']):
            raise ValueError('Scope outside resolved route')
        app = service(route['path'], allowed_scopes=route['scopes'] or None)
        manifest = app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])
        if request.get('target_realm') and request['target_realm'] != manifest['id']:
            raise ValueError('Request realm differs from resolved binding')
        if request.get('workspace_id') and route['owner_projection'] == 'shared' and request['workspace_id'] != route.get('workspace_id'):
            raise ValueError('Request workspace differs from resolved binding')
        prepared.append({'realm_id': manifest['id'], 'realm_alias': route['alias'],
                         'owner_projection': route['owner_projection'], 'scopes': scopes,
                         'context': app.context, 'method_availability': method_availability(app, scopes)})
    return WorkspaceService(lambda: prepared).start(
        task=request.get('task', args.task), budget=request.get('budget', args.budget), resume=resume)


def method_availability(app, scopes):
    from .method_repository import RealmMethodRepository
    def current(reference):
        try:
            repository = RealmMethodRepository(app, scopes=scopes, journal_root=data_home()/'method-proposals')
            return repository.active(reference)
        except (ValueError, KeyError, PermissionError):
            return {'active': False}
    return current
