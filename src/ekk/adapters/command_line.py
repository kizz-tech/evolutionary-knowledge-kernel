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

OPERATIONS={'doctor','context','contexts','search','fetch','read-source','resolve-historical','capture','retain','propose','apply','accept','review','assurance','assess','export','diagnostics','backup','restore'}


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
    from .local_profile import cache_home
    from .discovery_index import DiscoveryIndex
    app=RealmService(storage,principal=trusted_principal(),codec=MarkdownCodec(cache_dir=cache_home()/'parsed'/key),allowed_scopes=allowed_scopes,pack_loader=PackDirectory(pack_directory()),discovery_index=DiscoveryIndex(cache_home()/'discovery'/key))
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
    p.add_argument('--compact',action='store_true',help='Compact enter/context display or assessment summary; preserves evidence identities')
    p.add_argument('--brief',action='store_true',help='Progressive context display; required reading remains explicit')
    p.add_argument('--action',help='Owner-configured named assessment; assess only, without a JSON request')
    p.add_argument('--expected-head',help='Full Git commit for a named assessment; defaults to freshly observed HEAD')
    p.add_argument('--file',type=Path)
    p.add_argument('--result-file',type=Path,help='UTF-8 derivative result body for retain')
    p.add_argument('--since',help='Diagnostic start time, RFC3339')
    p.add_argument('--until',help='Diagnostic end time, RFC3339')
    p.add_argument('--include-repository-history',action='store_true',help='Explicitly include the containing repository in a backup')
    p.add_argument('--sha256',help='Expected backup archive SHA-256')
    p.add_argument('--restore-data-home',type=Path,help='New private runtime root for an isolated restore')
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


def dispatch(args, request, *, render=None):
    from .operation_diagnostics import observed_call, note_stage
    args._explicit_profile = args.profile is not None
    if args.operation == 'diagnostics':
        return _dispatch(args, request)
    realm_id = None
    # Resolve only diagnostic identity. The ordinary route remains authoritative
    # and will independently reject an unavailable or changed binding.
    try:
        if args.profile is None:
            selected = binding(args.cwd) if not args.root and not args.realm else None
            args.profile = selected[1].get('profile', 'personal') if selected else 'personal'
        if (args.operation not in {'init', 'diagnostics', 'restore'}
                and not (args.operation == 'assess' and (args.root or args.realm))):
            routes = _routes(args)
            if len(routes) == 1:
                realm_id = published_manifest(routes[0]['path'])['id']
    except (ValueError, OSError, KeyError, TypeError):
        pass
    payload = request.get('payload', request)
    key = args.idempotency_key or (payload.get('idempotency_key') if isinstance(payload, dict) else None) or request.get('request_id')
    if not isinstance(key, str): key = None
    def run():
        result = _dispatch(args, request)
        if render:
            note_stage('response')
            render(result)
        return result
    return observed_call(args.operation, run, realm_id=realm_id, key=key)


def _dispatch(args, request):
    if args.operation != 'assess' and (args.action is not None or args.expected_head is not None):
        raise ValueError('--action and --expected-head are assess options only')
    from .operation_diagnostics import note_stage
    note_stage('request')
    op=args.operation
    if args.profile is None:
        note_stage('routing')
        selected=binding(args.cwd) if not args.root and not args.realm else None
        args.profile=selected[1].get('profile','personal') if selected else 'personal'
        note_stage('request')
    if request.get('operation') and request['operation']!=op:raise ValueError('Request operation differs from CLI operation')
    if 'payload' in request:
        if not isinstance(request['payload'],dict):raise ValueError('payload must be an object')
        if 'operation' in request['payload'] and request['payload']['operation'] != op:
            raise ValueError('Payload operation differs from CLI operation')
        request={**request['payload'],**{k:v for k,v in request.items() if k!='payload'}}
    if 'target_scope' in request:
        if 'scopes' in request and request['scopes']!=request['target_scope']:raise ValueError('Conflicting scope declarations')
        request['scopes']=request['target_scope']
    if 'expected_snapshot' in request and op=='propose':request['base']=request['expected_snapshot']
    note_stage('unknown')
    if op == 'diagnostics':
        from datetime import datetime
        from .operation_diagnostics import journal
        def moment(value):
            return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
        return journal().report(since=moment(request.get('since', args.since)),
                                until=moment(request.get('until', args.until)))
    if op in {'backup', 'restore'}:
        return backup_operation(args, request)
    if (args.personal or args.resume is not None or 'resume' in request or 'personal' in request) and op != 'enter':
        raise ValueError('personal and resume are enter options only')
    if op == 'assess':
        from .coding_assessment import assess_workspace
        return assess_workspace(args, request, service)
    if op=='init' and args.workspace:
        if not args.realm or not args.scope:raise ValueError('Workspace init requires --realm and --scope')
        note_stage('routing')
        profile=LocalProfile(args.profile);realm_path,realm_manifest=profile.resolve(args.realm)
        from ..model import validate_identifier
        for scope in args.scope:validate_identifier(scope)
        if len(args.scope)!=len(set(args.scope)):raise ValueError('Duplicate context IDs')
        note_stage('store')
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
        note_stage('store')
        app=service(args.root,realm_id=request.get('realm_id') or request.get('target_realm'))
        app.init(title=args.title or request.get('title','Knowledge'),realm_id=app.initial_realm_id,**{k:request[k] for k in ('context_title','owner','context_id','default_visibility','packs') if k in request})
        return {'status':'initialized','realm_id':app.initial_realm_id,'doctor':app.doctor()}
    if op == 'enter' and (args.personal or args.resume is not None or 'resume' in request or 'personal' in request or (not args.root and not args.realm and binding(args.cwd) is None)):
        return workspace_entry(args, request)
    note_stage('routing')
    routes=_routes(args)
    if op not in {'enter','context','contexts','doctor','review','assurance'} and len(routes)!=1:
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
        from .operation_diagnostics import note_snapshots
        note_snapshots(current_snapshot=app.store.snapshot()['revision'], attempted_base=expected)
        note_stage('unknown')
        if op in {'context','enter'}:
            result=app.context(scopes,task=request.get('task',args.task),budget=request.get('budget',args.budget),
                               focus=route.get('working_entries', []) if op == 'enter' else [])
            result['index']=cache_context(result)
            if op == 'enter':
                from ..application.workspace import work_view
                result['work_view'] = work_view(result, method_availability(app, scopes))
            from .repository_evidence import attach_repository_checks
            result = attach_repository_checks(result, args.cwd)
        elif op=='contexts':result=app.list_contexts(scopes)
        elif op=='search':
            result=app.search_records(scopes,query=request.get('query',args.task),
                limit=request.get('limit',20),offset=request.get('offset',0),
                expected_snapshot=request.get('expected_snapshot'),
                source_byte_limit=request.get('source_byte_limit',1048576),match=request.get('match','all'))
        elif op=='fetch':
            result=app.fetch_record(scopes,request['reference'],max_bytes=request.get('max_bytes',131072))
        elif op=='read-source':
            result=app.read_source(scopes,request['reference'],asset_index=request.get('asset_index',0),
                offset=request.get('offset',0),limit=request.get('limit',65536),selector=request.get('selector'))
        elif op=='resolve-historical':
            result=app.resolve_historical(scopes, migration_id=request['migration_id'], origin=request['origin'],
                path=request.get('path'), legacy_id=request.get('legacy_id'),
                source_sha256=request.get('source_sha256'), containing_path=request.get('containing_path'),
                selector=request.get('selector'))
        elif op=='accept':
            result=app.accept_records(scopes,request['references'],expected_snapshot=request['expected_snapshot'],
                idempotency_key=args.idempotency_key or request['idempotency_key'])
        elif op=='doctor':result=app.doctor(revision=args.revision)
        elif op=='review':result=app.review(scopes)
        elif op=='assurance':result=app.assurance(scopes)
        elif op=='capture':
            note_stage('request')
            if args.file:
                data=args.file.read_bytes();filename=args.file.name
            else:
                data=request.get('body','').encode();filename=request.get('filename','original.md')
            key=args.idempotency_key or request.get('idempotency_key') or request.get('request_id')
            if not isinstance(key,str) or not key:raise ValueError('capture requires an idempotency key or request_id')
            result=capture_once(app,data,title=args.title or request.get('title','Source'),scopes=scopes,filename=filename,key=key,expected_snapshot=expected)
        elif op=='retain':
            note_stage('request')
            from .retention import retain_once
            artifacts = []
            if args.file:
                artifacts.append({'data': args.file.read_bytes(), 'filename': args.file.name})
            for item in request.get('artifacts', []):
                if not isinstance(item, dict) or set(item)-{'body','base64','filename','title'} or ('body' in item)==('base64' in item):
                    raise ValueError('artifact requires body or base64, filename and optional title')
                data = item['body'].encode('utf-8') if 'body' in item else base64.b64decode(item['base64'], validate=True)
                artifacts.append({'data':data, **{k:v for k,v in item.items() if k in {'filename','title'}}})
            body = args.result_file.read_text(encoding='utf-8') if args.result_file else request.get('body', '')
            key = args.idempotency_key or request.get('idempotency_key') or request.get('request_id')
            result = retain_once(app, artifacts, title=args.title or request.get('title', ''),
                body=body, scopes=scopes, key=key, expected_snapshot=expected,
                repository_evidence=request.get('repository_evidence'))
        elif op=='propose':
            note_stage('request')
            changes={}
            for path,value in request.get('changes',{}).items():
                if value is None:changes[path]=None
                elif isinstance(value,str):changes[path]=value.encode()
                elif isinstance(value,dict) and set(value)=={'base64'}:changes[path]=base64.b64decode(value['base64'],validate=True)
                else:raise ValueError('Changes require text, base64 object, or null')
            result=app.propose(changes,base=request.get('base'),grounds=request.get('grounds'),explanation=request.get('explanation'))
        elif op=='apply':
            note_stage('request')
            key=args.idempotency_key or request.get('idempotency_key')
            if not key:raise ValueError('apply requires an idempotency key')
            note_stage('store')
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
    index.rebuild([{'id':str(i)+':'+r['id'],'title':r['metadata']['title'],
                    'body':'\n'.join([*r['metadata'].get('aliases', []), r['body']])}
                   for i,r in enumerate(result['records'])],key=key)
    return {'disposable':True,'key':key,'records':len(result['records']),'coverage':'authorized emitted projection only'}


def backup_operation(args, request):
    """Explicit owner administration; workspace scope never expands into backup."""
    from .backup import create_backup, restore_backup
    from .operation_diagnostics import note_stage
    note_stage('routing')
    if (not getattr(args, '_explicit_profile', False) or not args.realm or args.root
            or args.scope or args.workspace
            or any(key in request for key in ('scopes','target_scope','workspace_id','root'))):
        raise PermissionError('Backup and restore require an explicit registered profile and realm, without root or scope overrides')
    profile = LocalProfile(args.profile)
    registered = profile.document.get('realms', {}).get(args.realm)
    if not isinstance(registered, dict) or not registered.get('id') or not registered.get('path'):
        raise PermissionError('Realm is not registered in the selected profile')
    def owner_app():
        root, _ = profile.resolve(args.realm)
        app = service(root)
        realm, policy, _, _ = app._validate(app.store.snapshot())
        if realm.get('owner') != app.principal or policy.get('bootstrap_owner') != app.principal:
            raise PermissionError('Full backup requires the current registered realm owner')
        app._authorized(policy, 'read', ['*'])
        app._authorized(policy, 'write', ['*'])
        return app, realm
    destination = args.destination or request.get('destination')
    if not destination:
        raise ValueError('A new destination is required')
    if args.operation == 'backup':
        app, realm = owner_app()
        note_stage('store')
        return create_backup(app.store, destination, realm_id=realm['id'], principal=app.principal,
            data_home=data_home(), include_repository_history=args.include_repository_history)
    # When the original is present, its current owner policy still applies.
    # An offline recovery keeps the explicit registry identity and verifies the
    # archived owner policy in an isolated copy before final destinations exist.
    if Path(registered['path']).expanduser().exists():
        owner_app()
    archive = args.file or request.get('archive')
    runtime = args.restore_data_home or request.get('restore_data_home')
    if not archive or not runtime:
        raise ValueError('Restore requires an archive and a new restore data home')
    note_stage('store')
    return restore_backup(archive, destination, data_home=runtime,
                          expected_sha256=args.sha256 or request.get('sha256'),
                          expected_realm_id=registered['id'])


def capture_once(app,data,*,title,scopes,filename,key,expected_snapshot=None):
    from .retention import capture_once as capture
    from .operation_diagnostics import observed_call
    realm = app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])['id']
    return observed_call('capture', lambda: capture(app, data, title=title, scopes=scopes,
        filename=filename, key=key, expected_snapshot=expected_snapshot),
        realm_id=realm, principal=app.principal, key=key)

def error_code(exc):
    from ..model import Conflict, DirtyWorkingTree, IdempotencyConflict, RecoveryConflict, StoreError
    from .file_lock import LockBusy
    if isinstance(exc,LockBusy):return 'lock_busy'
    if isinstance(exc,PermissionError):return 'access_denied'
    if isinstance(exc,RecoveryConflict):return 'recovery_required'
    if isinstance(exc,DirtyWorkingTree):return 'dirty_working_tree'
    if isinstance(exc,IdempotencyConflict):return 'idempotency_conflict'
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
        for key in ('snapshot','revision','origin_snapshot','base'):
            if value.get(key) is not None:return value[key]
        if 'doctor' in value:return snapshot(value['doctor'])
        if 'contexts' in value:return [snapshot(item) for item in value['contexts']]
        return None
    def evidence(value):
        if not isinstance(value,dict):return [],[],False,[],[]
        manifest=value.get('manifest',{})
        refs=list(manifest.get('used_refs',[]))+list(value.get('source_references',[]))
        if isinstance(value.get('reference'),dict):refs.append(value['reference'])
        if isinstance(value.get('result_reference'),dict):refs.append(value['result_reference'])
        refs.extend(item['reference'] for item in value.get('results',[]) if isinstance(item,dict) and isinstance(item.get('reference'),dict))
        refs.extend(item['reference'] for item in value.get('candidates',[]) if isinstance(item,dict) and isinstance(item.get('reference'),dict))
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
        if args.brief and (args.compact or args.operation not in {'enter','context'}):
            raise ValueError('--brief supports enter/context and cannot be combined with --compact')
        if args.compact and (args.operation not in {'enter','context','assess'}
                or (args.operation != 'assess' and (args.json or args.stdin))):
            raise ValueError('--compact supports enter/context command options and assess only')
        if common:
            if 'request_id' in request and (not isinstance(request['request_id'],str) or not request['request_id']):raise ValueError('request_id must be nonempty text')
            if 'operation' in request and request['operation']!=args.operation:raise ValueError('Request operation differs from CLI operation')
        emitted_warnings=[]
        def render(result):
            output=result_envelope(request,args.operation,result) if common else result
            if args.brief:
                from .context_display import brief_context
                brief=brief_context(result)
                output=result_envelope(request,args.operation,brief) if common else brief
            if args.compact:
                if args.operation == 'assess':
                    from .coding_assessment import compact_assessment
                    compact = compact_assessment(result)
                    output = result_envelope(request,args.operation,compact) if common else compact
                else:
                    from .context_display import compact_context
                    output=compact_context(result)
            print(json.dumps(output,ensure_ascii=False,indent=2,default=str))
            if isinstance(result, dict):emitted_warnings.extend(result.get('warnings', []))
        result=dispatch(args,request,render=render)
        if args.operation == 'diagnostics':render(result)
        late_warnings=[value for value in result.get('warnings',[]) if value not in emitted_warnings] if isinstance(result,dict) else []
        if late_warnings:print(json.dumps({'operation':args.operation,'warnings':late_warnings}),file=sys.stderr)
        failed=_failed(result) if common else isinstance(result,dict) and (result.get('blocked') or result.get('valid') is False or result.get('ok') is False)
        if failed:return 1
        return 0
    except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
        if not getattr(exc, 'operation_observed', False) and args.operation != 'diagnostics':
            from .operation_diagnostics import observed_call, note_stage
            def rejected():
                note_stage('request')
                raise exc
            try:observed_call(args.operation, rejected)
            except (ValueError,OSError,KeyError,TypeError,AttributeError):pass
        result={'error':error_code(exc),'message':str(exc)}
        from .file_lock import LockBusy
        if isinstance(exc,LockBusy):
            result.update(retryable=True, lock_kind=exc.lock_kind, waited_ms=exc.waited_ms)
        if getattr(exc, 'diagnostic_warnings', None):result['warnings']=exc.diagnostic_warnings
        output=result_envelope(request,args.operation,result,error=True) if common else result
        print(json.dumps(output,ensure_ascii=False),file=sys.stderr)
        return 2


def workspace_entry(args, request):
    from ..application.workspace import WorkspaceService, exact_reference
    from .operation_diagnostics import note_stage
    note_stage('request')
    personal = request.get('personal', args.personal)
    if type(personal) is not bool:
        raise ValueError('personal must be boolean')
    if args.resume is not None and 'resume' in request:
        raise ValueError('Choose one resume reference')
    resume = json.loads(args.resume, parse_constant=_invalid_json_constant) if args.resume is not None else request.get('resume')
    if args.resume is not None or 'resume' in request:
        resume = exact_reference(resume)
    note_stage('routing')
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
        home = profile.home(cwd=args.cwd, explicit=personal) if profile else None
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
                         'working_entries': route.get('working_entries', []),
                         'context': app.context, 'method_availability': method_availability(app, scopes)})
    note_stage('unknown')
    result = WorkspaceService(lambda: prepared).start(
        task=request.get('task', args.task), budget=request.get('budget', args.budget), resume=resume)
    from .repository_evidence import attach_repository_checks
    return attach_repository_checks(result, args.cwd)


def method_availability(app, scopes):
    from .method_repository import RealmMethodRepository
    def current(reference):
        try:
            repository = RealmMethodRepository(app, scopes=scopes, journal_root=data_home()/'method-proposals')
            return repository.active(reference)
        except (ValueError, KeyError, PermissionError):
            return {'active': False}
    return current
