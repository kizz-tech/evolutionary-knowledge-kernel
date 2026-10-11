"""JSON transport and local composition root for the current EKK application."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys
import uuid
import yaml
from ..application.errors import RequestError, unknown_id
from .local_profile import LocalProfile, binding, config_home, data_home, trusted_principal, published_manifest

AGENT_VIEW_RECORD_BUDGET=64000
OPERATIONS={'doctor','context','contexts','search','fetch','read-source','resolve-historical','capture','retain','decide','propose','apply','accept','review','assurance','assess','export','diagnostics','backup','restore'}
DECISION_SCHEMA='ekk.decision/0.1'
DECISION_STATED_BY=('owner_relayed','agent')  # the same closed set the application validates


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
    from .history_index import HistoryIndex
    # Task-term query weights (experience_store.TaskTerms) are measured but not applied:
    # on real tasks they did not improve known-item recall over plain BM25.
    app=RealmService(storage,principal=trusted_principal(),codec=MarkdownCodec(cache_dir=cache_home()/'parsed'/key),allowed_scopes=allowed_scopes,pack_loader=PackDirectory(pack_directory()),discovery_index=DiscoveryIndex(cache_home()/'discovery'/key),history_index=HistoryIndex(cache_home()/'history'/key))
    app.initial_realm_id=identity
    return app


def parser():
    p=argparse.ArgumentParser(prog='ekk',description='Personal work entry, shared continuity and revisable methods. Start with enter --task; methods: ekk method --help')
    p.add_argument('operation',choices=sorted(OPERATIONS|{'init','enter','recover'}),help='Also: ekk observe …, ekk method …, ekk project decisions (documents generated from records)')
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
    p.add_argument('--compact',action='store_true',help='enter/context: short agent view, same as --brief; assess: compact summary; ignored elsewhere')
    p.add_argument('--brief',action='store_true',help='enter/context: short agent view with exact references; required reading stays complete; ignored elsewhere')
    p.add_argument('--wait',action='store_true',help='retain/decide: publish and verify read-back before returning; by default the request is queued and published in the background')
    p.add_argument('--reason',help='decide: the reason and the rejected alternative')
    p.add_argument('--revisit',help='decide: the condition under which the decision is reconsidered')
    p.add_argument('--supersedes',help='decide: ID of the decision or outcome this one replaces (its current version, exactly)')
    p.add_argument('--ground',action='append',default=[],help='decide: ID of a record the decision rests on (repeatable; current version, exactly)')
    p.add_argument('--alias',action='append',default=[],help='decide: a name the decision is also known by (repeatable)')
    p.add_argument('--stated-by',choices=['owner-relayed','agent'],help='decide (required): who stated the decision: agent, its own decision, or owner-relayed, an agent relaying the owner\'s words with --owner-words')
    p.add_argument('--owner-words',type=Path,metavar='FILE',help="decide --stated-by owner-relayed: a file with the owner's verbatim words, kept as an exact source of the decision")
    p.add_argument('--statement-session',help='decide: cross-check only; the host session this command runs in, in which the owner spoke')
    p.add_argument('--statement-file',type=Path,help='accept: JSON statement of the owner behind the acceptance (by, via, at, optional host, session, words)')
    p.add_argument('--words',type=Path,metavar='FILE',help="accept --id: a file with the owner's verbatim words of acceptance (UTF-8, at most 600 characters); "
                   'records {by: owner, via: host_chat, host, session, at, words} with the host session and the runtime clock')
    p.add_argument('--action',help='Owner-configured named assessment; assess only, without a JSON request')
    p.add_argument('--expected-head',help='Full Git commit for a named assessment; defaults to freshly observed HEAD')
    p.add_argument('--file',type=Path)
    p.add_argument('--result-file',type=Path,help='UTF-8 derivative result body for retain')
    p.add_argument('--manifest',type=Path,help='retain: explicitly declared result and artifact files; assembled into the ordinary retention request')
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


def current_reference(app, scopes, ids, option='--id'):
    """Exact reference to the current version of one record named with ``option``.

    Lookup stays exact; an exact ID outside the selected contexts is refused later
    as access_denied. A miss is the request error ``unknown_id``. A value of at
    least 8 characters that starts exactly one record readable from the selected
    contexts (RealmService.readable_prefix_matches) names that full ID; several
    give only their count. Nothing is resolved automatically.
    """
    if len(ids)!=1:raise RequestError('Give one '+option+' or a JSON request with an exact reference',option=option)
    given=ids[0]
    _,realm,_,records=app._query_view(scopes)
    row=records.get(given)
    if row is None:raise unknown_id(given,app.readable_prefix_matches(scopes,given),option)
    return {'realm':realm['id'],'id':given,'revision':row['metadata']['revision'],'digest':'sha256:'+row['digest']}


def retention_payload(artifacts, *, title, body, expected_snapshot=None, repository_evidence=None,
                      experience=None, preference=None, supersedes=None, decision=None, basis=None, aliases=None):
    if len(artifacts)>32:raise RequestError('retain accepts at most 32 source artifacts',option='artifacts')
    if not isinstance(title,str) or not title or not isinstance(body,str) or not body.strip():
        raise RequestError('retain requires a title and a nonempty result body',option='title' if not isinstance(title,str) or not title else 'body')
    if repository_evidence is not None and not isinstance(repository_evidence,dict):
        raise RequestError('repository evidence must be a recorded declaration',option='repository_evidence')
    payload={'title':title,'body':body,'artifacts':[
        {'base64':base64.b64encode(item['data']).decode(),**{k:item[k] for k in ('filename','title') if k in item}}
        for item in artifacts]}
    if repository_evidence is not None:payload['repository_evidence']=repository_evidence
    if expected_snapshot is not None:payload['expected_snapshot']=expected_snapshot
    for name,value in (('experience',experience),('preference',preference),('supersedes',supersedes),('decision',decision),('basis',basis),('aliases',aliases)):
        if value is not None:payload[name]=value
    return payload


def capture_payload(data, *, title, filename, expected_snapshot=None):
    if not isinstance(data,bytes) or not data:raise RequestError('capture requires nonempty source bytes',option='body')
    if not isinstance(title,str) or not title or not isinstance(filename,str) or not filename:
        raise RequestError('capture requires a title and a filename',option='title' if not isinstance(title,str) or not title else 'filename')
    payload={'title':title,'filename':filename,'base64':base64.b64encode(data).decode()}
    if expected_snapshot is not None:payload['expected_snapshot']=expected_snapshot
    return payload


def content_key(operation, realm_id, scopes, payload):
    """The key of a write that was given none: identical content yields the same
    key, queued or synchronous, so a retry cannot create a second result."""
    return operation+'-'+hashlib.sha256(json.dumps([realm_id,sorted(scopes),payload],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:40]


def queue_retention(args, app, scopes, artifacts, *, title, body, key, expected_snapshot=None, repository_evidence=None,
                    experience=None, preference=None, supersedes=None, decision=None, basis=None, aliases=None):
    """Durable local retention request with a background publisher.

    Publication, read-back and discoverability are confirmed later by the queue;
    this result never claims them. A decision travels as a retention request
    with the ``decision``, ``basis`` and ``aliases`` fields.
    """
    payload=retention_payload(artifacts,title=title,body=body,expected_snapshot=expected_snapshot,
                              repository_evidence=repository_evidence,experience=experience,preference=preference,supersedes=supersedes,
                              decision=decision,basis=basis,aliases=aliases)
    return queue_write(args,app,scopes,'retain',payload,key)


def queue_capture(args, app, scopes, data, *, title, filename, key, expected_snapshot=None):
    """Durable local request to preserve one original source; published in the background."""
    return queue_write(args,app,scopes,'capture',capture_payload(data,title=title,filename=filename,expected_snapshot=expected_snapshot),key)


def queue_write(args, app, scopes, operation, payload, key):
    from .activity_cli import authorize_controls, local_store, route_document, start_worker
    realm=authorize_controls(app,scopes,write=True)
    key=key or content_key(operation,realm['id'],scopes,payload)
    frozen={'route':route_document(args,realm['id'],scopes),'operation':operation,'request':payload}
    store=local_store(app,realm['id'])
    try:
        try:queued=store.enqueue(key,frozen,scopes)
        except ValueError as exc:
            if 'exceeds' in str(exc):raise RequestError(str(exc)+'; publish a source of this size with --wait',option='--wait') from exc
            raise
        row=queued['operations'][0] if queued['operations'] else {'state':'local_pending'}
        if row['state']=='read_back_and_discoverable':
            worker={'started':False,'meaning':'This key is already published and verified.'}
        else:
            try:worker=start_worker(argparse.Namespace(**{**vars(args),'state_dir':None}),store)
            except OSError as exc:worker={'started':False,'error':str(exc),'next':'Run ekk queue drain with the same route; the request is already durable.'}
    finally:store.close()
    meaning=('Already published and verified under this key.' if row['state']=='read_back_and_discoverable' else
             'Durable local request. Publication, read-back and discoverability are not confirmed yet; '
             'report it as pending until queue status shows read_back_and_discoverable. Use --wait to publish now.')
    return {'schema':'ekk.retention-queued/0.1','key':key,'state':row['state'],'worker':worker,
            'check':'ekk queue status '+route_options(args)+' --key '+shlex.quote(key),'meaning':meaning}


def _now():
    """The runtime's clock as a statement records it, never the agent's: RFC 3339 UTC to the second."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def accept_request(args, request):
    """An accept request checked before routing: (the owner's statement or None, the idempotency key).

    The --id form resolves current references itself, so it refuses JSON
    ``references`` and ``expected_snapshot``, and it takes exactly one statement:
    --words FILE, --statement-file or the JSON ``statement``. --words builds the
    host-chat statement from the file's bytes, the host identity's host and
    session and the runtime's clock (host_chat_statement); the others are taken
    as given. The JSON form names every field it lacks.
    """
    key=args.idempotency_key or request.get('idempotency_key')
    if args.id and ('references' in request or 'expected_snapshot' in request):
        raise RequestError('accept --id resolves the current exact references and snapshot itself; omit references and expected_snapshot',option='--id')
    sources=[name for name,given in (('--words',args.words is not None),('--statement-file',args.statement_file is not None),('statement','statement' in request)) if given]
    if len(sources)>1 and (args.id or args.words is not None):
        raise RequestError('Give the statement once: '+' or '.join(sources),option=sources[0] if sources[0]!='statement' else sources[1])
    if args.words is not None:
        from .host_identity import resolve
        from ..application.experience import host_chat_statement
        try:data=args.words.read_bytes()
        except OSError as exc:
            raise RequestError(f"--words takes the path of a file holding the owner's words; {args.words} cannot be read: {exc.strerror or exc}",
                               refusal='words_unreadable',option='--words') from None
        identity=resolve()
        statement=host_chat_statement(data,host=identity.host,session=identity.session,at=_now(),overflow='refuse')[0]
    elif args.statement_file is not None:
        statement=request_json(args.statement_file.read_text(encoding='utf-8'),'--statement-file')
    else:
        statement=request.get('statement')
    if args.id and statement is None:
        raise RequestError("accept --id records the owner's words: --words FILE with their verbatim words, or --statement-file for another channel",
                           refusal='words_missing',option='--words',  # FILE is to hold the owner's words
                           next='ekk accept '+route_options(args)+''.join(' --id '+shlex.quote(key) for key in args.id)+' --words FILE')
    missing=[name for name,given in (('references',request.get('references')),('expected_snapshot',request.get('expected_snapshot')),('idempotency_key',key)) if given is None]
    if not args.id and missing:
        raise RequestError('accept needs '+', '.join(missing)+' in its JSON request; or name the records with --id ID --words FILE, '
                           'and EKK resolves their current versions',option=missing[0])
    return statement,key


def statement_session(identity, declared, *, relayed, option):
    """The session a decision or preference source records: the host identity's own, a fact (decision 12).

    A relayed statement needs one, since it names the session in which the owner
    spoke (refused naming --stated-by). A declared session, ``option``, only
    cross-checks it: the source has room for one session, so one that differs is
    refused.
    """
    if declared is not None and declared!=identity.session:
        raise RequestError(f'{option} names session {declared}, but this command runs in '+(f'session {identity.session}' if identity.session else 'no host session')
                           +'; a source records the session its command runs in, so words the owner spoke in another session are recorded from that session',
                           refusal='session_mismatch',option=option)
    if relayed and not identity.session:
        raise RequestError(f'host {identity.host} gives this command no session; a relayed statement names the host session in which the owner spoke. '
                           'Record it from that session',refusal='session_identity_missing',option='--stated-by')
    return identity.session


def decide_command(args, declaration):
    """The caller's decide command rebuilt from its options, with ``declaration`` in place of how it stated the decision."""
    parts=['ekk decide',route_options(args)]
    for option,value in (('--title',args.title or None),('--result-file',args.result_file),('--reason',args.reason),('--revisit',args.revisit),
                         ('--supersedes',args.supersedes),('--idempotency-key',args.idempotency_key),('--json',args.json)):
        if value is not None:parts+=[option,shlex.quote(str(value))]
    parts+=[part for option,values in (('--ground',args.ground),('--alias',args.alias)) for value in values for part in (option,shlex.quote(value))]
    parts+=[flag for flag,given in (('--stdin',args.stdin),('--wait',args.wait)) if given]
    return ' '.join(parts+[declaration])


def decide_request(args, request):
    """Who stated a decision, checked before routing: (stated_by, the owner's words as bytes or None, the source).

    --stated-by (JSON ``stated_by``) is required: ``agent``, the agent's own
    decision, takes no owner words; ``owner-relayed`` takes the owner's verbatim
    words, --owner-words FILE (JSON ``owner_words``, text), kept as an exact
    source of the decision, and needs a host session. The source is the host
    identity's host and session (statement_session) and the runtime's day.
    Refusals give the corrected command.
    """
    from .host_identity import resolve
    from ..application.experience import host_chat_statement
    stated_by=args.stated_by if args.stated_by is not None else request.get('stated_by')
    agent,relayed=decide_command(args,'--stated-by agent'),decide_command(args,'--stated-by owner-relayed --owner-words FILE')
    forms=f"`{agent}` for the agent's own decision, or `{relayed}` when it relays the owner's words (FILE: the owner's verbatim words)"
    if stated_by is None:
        raise RequestError('decide records who stated the decision: '+forms,refusal='stated_by_missing',option='--stated-by')
    if not isinstance(stated_by,str) or stated_by.replace('-','_') not in DECISION_STATED_BY:raise RequestError('stated_by must be owner-relayed or agent',option='stated_by')
    stated_by=stated_by.replace('-','_')
    words,option=None,'--owner-words' if args.owner_words is not None else 'owner_words'
    if args.owner_words is not None:
        try:words=args.owner_words.read_bytes()
        except OSError as exc:
            raise RequestError(f"--owner-words takes the path of a file holding the owner's words; {args.owner_words} cannot be read: {exc.strerror or exc}",
                               refusal='words_unreadable',option='--owner-words') from None
    elif 'owner_words' in request:
        if not isinstance(request['owner_words'],str):raise RequestError('owner_words must be text',option='owner_words')
        words=request['owner_words'].encode('utf-8')
    if stated_by=='agent' and words is not None:
        raise RequestError("--stated-by agent records the agent's own decision and takes no owner words: "+forms,refusal='words_with_agent',option=option)
    if stated_by=='owner_relayed' and words is None:
        raise RequestError("--stated-by owner-relayed keeps the owner's verbatim words as an exact source of the decision: "+forms,
                           refusal='words_missing',option='--owner-words',next=relayed)
    declared=args.statement_session if args.statement_session is not None else request.get('statement_session')
    if declared is not None and not isinstance(declared,str):raise RequestError('statement_session must be text',option='statement_session')
    identity=resolve()
    session=statement_session(identity,declared,relayed=stated_by=='owner_relayed',
                              option='statement_session' if args.statement_session is None else '--statement-session')
    if words is not None:  # strict UTF-8 and not blank; any length, as an exact source
        host_chat_statement(words,host=identity.host,session=session,at=_now(),overflow='excerpt',option=option)
    # The host is the host identity's, never a terminal check; the day is the content's date.
    return stated_by,words,{'host':identity.host,**({'session':session} if session else {}),'at':_now()[:10]}


def route_options(args):
    """The caller's route as shell-quoted options of a command it is told to run next:
    --cwd, the profile when the caller named one, --realm, --root and every --scope."""
    return ' '.join(['--cwd',shlex.quote(str(args.cwd))]+(['--profile',shlex.quote(args.profile)] if getattr(args,'_explicit_profile',False) else [])
                    +(['--realm',shlex.quote(args.realm)] if args.realm else [])+(['--root',shlex.quote(str(args.root))] if args.root else [])
                    +[part for scope in args.scope for part in ('--scope',shlex.quote(scope))])


def corrected_command(argv, option, given, replacement):
    """The caller's own command line with only the value ``given`` of ``option`` replaced,
    as ``option VALUE`` or ``option=VALUE``; every other token stays as typed. None when
    ``argv`` does not carry that value, so an unchanged command is never offered."""
    argv=[str(part) for part in argv];changed=False
    for index,part in enumerate(argv):
        if part==option+'='+given:argv[index]=option+'='+replacement;changed=True
        elif part==given and index and argv[index-1]==option:argv[index]=replacement;changed=True
    return 'ekk '+shlex.join(argv) if changed else None


def note_delivery(args, result, brief):
    """Remember privately what entry showed for a task and what plain lexical order
    would have shown: the basis of owner samples and exact opening linkage. Only inside a
    bound, observed project; never affects the entry itself."""
    try:
        if args.operation!='enter':return
        from .experience_store import ExperienceStore
        from .host_identity import resolve
        from .observe_hook import switched_off, workspace_of
        from ..application.discovery import content_terms
        from .. import observation
        workspace=None if switched_off() else workspace_of(args.cwd)
        if workspace is None:return
        host,profile,session,_=resolve()
        federated=str(brief.get('schema','')).startswith('ekk.federated-brief/')
        pairs=list(zip(result.get('contexts',[]),brief.get('contexts',[]))) if federated else [(result,brief)]
        store=None
        try:
            for full,short in pairs:
                if not str(short.get('schema','')).startswith('ekk.context-brief/') or not short.get('task'):continue
                task=observation.single_line(observation.redact(str(short['task'])[:observation.MAX_TASK_CHARS*4]),observation.MAX_TASK_CHARS)
                # Pinned items appear for every task; they are kept for opening linkage, not for relevance samples.
                items=[{'realm':(item.get('ref') or {}).get('realm') or short.get('realm'),'id':(item.get('ref') or {}).get('id') or item.get('id'),'title':item.get('title'),'kind':item.get('kind'),
                        **({k:item['ref'].get(k) for k in ('revision','digest')} if item.get('ref') else {'pinned':True})}
                       for item in short.get('items',[]) if (item.get('ref') or {}).get('id') or item.get('id')]
                plain=((full.get('manifest') or {}).get('ranking') or {}).get('plain_order') or []
                store=store or ExperienceStore(timeout=0.05)
                store.note_delivery(workspace=str(workspace),realm=short.get('realm'),task=task,
                                    snapshot=json.dumps(short.get('snapshot')),items=items,host=host,profile=profile,session=session,
                                    baseline=[{k:row[k] for k in ('id','title','kind','revision','digest') if k in row} for row in plain if isinstance(row,dict) and row.get('id')])
                store.observe_task(short.get('realm'),content_terms(task),task)
        finally:
            if store is not None:store.close()
    except Exception:pass


def note_use(args, result, record_id):
    """Record a successful exact opening, separately from application or benefit.

    The host's declared environment only (host_identity); no session is inferred
    from shell or PID. Telemetry is optional and cannot make a successful read fail.
    """
    try:
        from .experience_store import ExperienceStore
        from .host_identity import resolve
        from .observe_hook import switched_off, workspace_of
        workspace=None if switched_off() else workspace_of(args.cwd)
        if not record_id or workspace is None or result.get('incomplete'):return
        if args.operation not in ('fetch','read-source'):return
        host,profile,session,_=resolve()
        store=ExperienceStore(timeout=0.05)
        try:store.note_reading(reference=result.get('reference'),operation=args.operation,
                               workspace=str(workspace),host=host,profile=profile,session=session)
        finally:store.close()
    except Exception:pass


def normalized_request(request, operation):
    """One request shape for dispatch and display-only continuation commands."""
    if request.get('operation') and request['operation'] != operation:
        raise RequestError('Request operation differs from CLI operation',option='operation')
    if 'payload' in request:
        if not isinstance(request['payload'],dict):raise RequestError('payload must be an object',option='payload')
        if 'operation' in request['payload'] and request['payload']['operation'] != operation:
            raise RequestError('Payload operation differs from CLI operation',option='operation')
        request={**request['payload'],**{k:v for k,v in request.items() if k!='payload'}}
    else:
        request=dict(request)
    if 'target_scope' in request:
        if 'scopes' in request and request['scopes'] != request['target_scope']:
            raise RequestError('Conflicting scope declarations',option='target_scope')
        request['scopes']=request['target_scope']
    return request


def routed_navigation(value, args, *, scopes=(), request=None):
    """Keep display-only exact navigation in the caller's original owning route."""
    from copy import deepcopy
    request=normalized_request(request or {},args.operation)
    personal=request.get('personal',getattr(args,'personal',False))
    effective_scopes=request.get('scopes',args.scope or scopes)
    route = ['--cwd',str(args.cwd.expanduser().resolve())]
    if args.profile:route += ['--profile',args.profile]
    if args.root:route += ['--root',str(args.root.expanduser().resolve())]
    elif args.realm:route += ['--realm',args.realm]
    # JSON scopes constrain every projection, while CLI scopes only constrain
    # bound shared routes. Preserve that distinction for combined personal entry.
    stdin=None
    if personal:
        route += ['--personal']
        if 'scopes' in request:
            for scope in args.scope:route += ['--scope',scope]
            route += ['--stdin']
            stdin=json.dumps({'scopes':effective_scopes},ensure_ascii=False)
        else:
            for scope in effective_scopes:route += ['--scope',scope]
    else:
        for scope in effective_scopes:route += ['--scope',scope]
    result = deepcopy(value)
    def visit(node):
        if isinstance(node,dict):
            navigation = node.get('navigation')
            if isinstance(navigation,dict):
                for name in ('selected','current'):
                    item = navigation.get(name)
                    if isinstance(item,dict) and item.get('argv',[])[:3] == ['ekk','enter','--resume']:
                        item['argv'] = item['argv'][:4] + route
                        item.pop('stdin',None)
                        if stdin is not None:item['stdin']=stdin
            for child in node.values():visit(child)
        elif isinstance(node,list):
            for child in node:visit(child)
    visit(result)
    return result


def _invalid_json_constant(value, option=None):
    raise RequestError('Nonstandard JSON constant: '+value,option=option)


def request_json(text, option):
    """A JSON value the caller passed with ``option``: malformed JSON and the
    nonstandard constants NaN and Infinity are request errors naming it."""
    try:return json.loads(text,parse_constant=lambda value:_invalid_json_constant(value,option))
    except json.JSONDecodeError as exc:raise RequestError(f'{option} is not valid JSON: {exc}',option=option) from None


def _input(args):
    if args.json and args.stdin:raise RequestError('Choose one JSON input',option='--stdin')
    option='--json' if args.json else '--stdin'
    result=request_json(args.json.read_text() if args.json else sys.stdin.read(),option) if args.json or args.stdin else {}
    if not isinstance(result,dict):raise RequestError('JSON request must be an object',option=option)
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
    # The journal names registered operations; a decision is published as a retention request.
    return observed_call(args.operation, run, realm_id=realm_id, key=key)


def _dispatch(args, request):
    if args.manifest is not None:
        if args.operation != 'retain':raise RequestError('--manifest is a retain option only',option='--manifest')
        if request or args.json or args.stdin or args.file or args.result_file or args.title:
            raise RequestError('--manifest cannot be combined with another result or JSON input',option='--manifest')
    if args.operation != 'assess' and (args.action is not None or args.expected_head is not None):
        raise RequestError('--action and --expected-head are assess options only',option='--action' if args.action is not None else '--expected-head')
    decide_only=[name for name,given in (('--reason',args.reason is not None),('--revisit',args.revisit is not None),('--supersedes',args.supersedes is not None),
                                         ('--ground',args.ground),('--alias',args.alias),('--stated-by',args.stated_by is not None),
                                         ('--owner-words',args.owner_words is not None),('--statement-session',args.statement_session is not None)) if given]
    if args.operation != 'decide' and decide_only:
        raise RequestError('--reason, --revisit, --supersedes, --ground, --alias, --stated-by, --owner-words and --statement-session are decide options only',option=decide_only[0])
    accept_only=[name for name,given in (('--statement-file',args.statement_file is not None),('--words',args.words is not None)) if given]
    if args.operation != 'accept' and accept_only:
        raise RequestError('--statement-file and --words are accept options only',option=accept_only[0])
    from .operation_diagnostics import note_stage
    note_stage('request')
    op=args.operation
    if args.profile is None:
        note_stage('routing')
        selected=binding(args.cwd) if not args.root and not args.realm else None
        args.profile=selected[1].get('profile','personal') if selected else 'personal'
        note_stage('request')
    request=normalized_request(request,op)
    if 'expected_snapshot' in request and op=='propose':request['base']=request['expected_snapshot']
    accepting=accept_request(args,request) if op=='accept' else None
    deciding=decide_request(args,request) if op=='decide' else None
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
        raise RequestError('personal and resume are enter options only',option='--personal' if args.personal or 'personal' in request else '--resume')
    if op == 'assess':
        from .coding_assessment import assess_workspace
        return assess_workspace(args, request, service)
    if op=='init' and args.workspace:
        if not args.realm or not args.scope:raise RequestError('Workspace init requires --realm and --scope',option='--realm' if not args.realm else '--scope')
        note_stage('routing')
        profile=LocalProfile(args.profile);realm_path,realm_manifest=profile.resolve(args.realm)
        from ..model import validate_identifier
        for scope in args.scope:validate_identifier(scope)
        if len(args.scope)!=len(set(args.scope)):raise RequestError('Duplicate context IDs',option='--scope')
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
        if not args.root:raise RequestError('Realm init requires --root',option='--root')
        if request.get('realm_id') and request.get('target_realm') and request['realm_id']!=request['target_realm']:raise RequestError('Conflicting realm declarations',option='target_realm')
        note_stage('store')
        app=service(args.root,realm_id=request.get('realm_id') or request.get('target_realm'))
        app.init(title=args.title or request.get('title','Knowledge'),realm_id=app.initial_realm_id,**{k:request[k] for k in ('context_title','owner','context_id','default_visibility','packs') if k in request})
        return {'status':'initialized','realm_id':app.initial_realm_id,'doctor':app.doctor()}
    if op == 'enter' and (args.personal or args.resume is not None or 'resume' in request or 'personal' in request or (not args.root and not args.realm and binding(args.cwd) is None)):
        return workspace_entry(args, request)
    note_stage('routing')
    routes=_routes(args)
    if op not in {'enter','context','contexts','doctor','review','assurance'} and len(routes)!=1:
        raise RequestError('Mutation/export requires one explicit realm',option='--realm')
    results=[]
    for route in routes:
        app=service(route['path'],allowed_scopes=route['scopes'] or None);scopes=request.get('scopes',route['scopes'])
        if route['scopes'] and not set(scopes)<=set(route['scopes']):raise ValueError('JSON scope outside binding')
        if request.get('workspace_id') and request['workspace_id']!=route.get('workspace_id'):raise ValueError('Request workspace differs from resolved binding')
        manifest=app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])
        if request.get('target_realm') and request['target_realm']!=manifest['id']:raise ValueError('Request realm differs from resolved binding')
        expected=request.get('expected_snapshot')
        if expected and op=='apply' and request.get('proposal',request).get('base')!=expected:raise RequestError('Proposal base differs from expected snapshot',option='expected_snapshot')
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
            result=app.fetch_record(scopes,request.get('reference') or current_reference(app,scopes,args.id,'--id'),max_bytes=request.get('max_bytes',131072))
            note_use(args,result,(result.get('reference') or {}).get('id'))
        elif op=='read-source':
            result=app.read_source(scopes,request.get('reference') or current_reference(app,scopes,args.id,'--id'),asset_index=request.get('asset_index',0),
                offset=request.get('offset',0),limit=request.get('limit',65536),selector=request.get('selector'))
            note_use(args,result,(result.get('reference') or {}).get('id'))
        elif op=='resolve-historical':
            result=app.resolve_historical(scopes, migration_id=request['migration_id'], origin=request['origin'],
                path=request.get('path'), legacy_id=request.get('legacy_id'),
                source_sha256=request.get('source_sha256'), containing_path=request.get('containing_path'),
                selector=request.get('selector'))
        elif op=='accept':
            # The owner's statement is the provenance recorded; --words adds the host and
            # session it runs in as facts beside the owner's words, never in their place.
            statement,key=accepting
            if args.id:result=app.accept_current(scopes,args.id,statement=statement,idempotency_key=key)
            else:
                result=app.accept_records(scopes,request['references'],expected_snapshot=request['expected_snapshot'],idempotency_key=key,statement=statement)
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
            if args.wait:
                key=key or content_key('capture',manifest['id'],scopes,capture_payload(data,title=args.title or request.get('title','Source'),filename=filename,expected_snapshot=expected))
                result=capture_once(app,data,title=args.title or request.get('title','Source'),scopes=scopes,filename=filename,key=key,expected_snapshot=expected)
            else:
                # Queue the exact bytes durably and return; publication runs in the background.
                result=queue_capture(args,app,scopes,data,title=args.title or request.get('title','Source'),filename=filename,key=key,expected_snapshot=expected)
        elif op=='retain':
            note_stage('request')
            from .retention import retain_once
            package = None
            if args.manifest:
                from .result_manifest import assemble_manifest, preflight_payload
                from .activity_cli import route_document
                package = assemble_manifest(args.manifest)
                artifacts, body, title = package['artifacts'], package['body'], package['title']
                payload = retention_payload(artifacts, title=title, body=body)
                preflight_payload(payload, route=route_document(args,manifest['id'],scopes), wait=args.wait)
                # Prepare through the owning application without publication:
                # its complete-record limit includes metadata and exact grounds.
                app.retain(artifacts, title=title, body=body, scope=scopes)
            else:
                artifacts = []
                if args.file:
                    artifacts.append({'data': args.file.read_bytes(), 'filename': args.file.name})
                for item in request.get('artifacts', []):
                    if not isinstance(item, dict) or set(item)-{'body','base64','filename','title'} or ('body' in item)==('base64' in item):
                        raise RequestError('artifact requires body or base64, filename and optional title',option='artifacts')
                    data = item['body'].encode('utf-8') if 'body' in item else base64.b64decode(item['base64'], validate=True)
                    artifacts.append({'data':data, **{k:v for k,v in item.items() if k in {'filename','title'}}})
                body = args.result_file.read_text(encoding='utf-8') if args.result_file else request.get('body', '')
                title = args.title or request.get('title', '')
            key = args.idempotency_key or request.get('idempotency_key') or request.get('request_id')
            if args.wait:
                key = key or content_key('retain', manifest['id'], scopes, retention_payload(
                    artifacts, title=title, body=body, expected_snapshot=expected,
                    repository_evidence=request.get('repository_evidence')))
                result = retain_once(app, artifacts, title=title,
                    body=body, scopes=scopes, key=key, expected_snapshot=expected,
                    repository_evidence=request.get('repository_evidence'))
            else:
                result = queue_retention(args, app, scopes, artifacts, title=title,
                    body=body, key=key, expected_snapshot=expected,
                    repository_evidence=request.get('repository_evidence'))
            if package is not None:
                from .result_manifest import verify_manifest
                declared = verify_manifest(package, result,
                    read_source=lambda ref,**kw:app.read_source(scopes,ref,**kw),
                    fetch_result=lambda ref:app.fetch_record(scopes,ref,max_bytes=1048576))
                declared['destination'] = {'realm':manifest['id'],'contexts':list(scopes),'profile':args.profile,'realm_alias':route['alias']}
                declared['frozen_inventory'] = True
                if declared['state'] != 'complete':
                    declared['next'] = 'Inspect the existing queue or retry the unchanged manifest and key with --wait; changed files are a new candidate.'
                result['declared_package'] = declared
        elif op=='decide':
            # A decision is a retention request with a decision annotation: queued by
            # default, published through the ordinary route, unaccepted until the owner says so.
            note_stage('request')
            from .retention import retain_once
            statement=args.result_file.read_text(encoding='utf-8') if args.result_file else request.get('body','')
            title=args.title or request.get('title','')
            stated_by,words,source=deciding
            decision={'schema':DECISION_SCHEMA,'stated_by':stated_by,'source':source}
            # The owner's relayed words are an exact source beside the statement, unless they are the statement itself.
            artifacts=[{'data':words,'filename':'owner-words.md','title':'Owner words: '+title[:80]}] if words is not None and words!=statement.encode('utf-8') else []
            for name in ('reason','revisit'):
                value=getattr(args,name) or request.get(name)
                if value is not None:decision[name]=value
            def exact(ids, option):
                return [{k:current_reference(app,scopes,[i],option)[k] for k in ('id','revision','digest')} for i in ids]
            supersedes=exact([args.supersedes],'--supersedes') if args.supersedes else request.get('supersedes')
            basis=exact(args.ground,'--ground') if args.ground else request.get('basis')
            aliases=list(args.alias) if args.alias else request.get('aliases')
            key=args.idempotency_key or request.get('idempotency_key') or request.get('request_id')
            key=key or content_key('decide',manifest['id'],scopes,retention_payload(artifacts,title=title,body=statement,expected_snapshot=expected,
                                                                                decision=decision,supersedes=supersedes,basis=basis,aliases=aliases))
            if args.wait:
                result=retain_once(app,artifacts,title=title,body=statement,scopes=scopes,key=key,expected_snapshot=expected,
                                   decision=decision,supersedes=supersedes,basis=basis,aliases=aliases)
            else:
                result=queue_retention(args,app,scopes,artifacts,title=title,body=statement,key=key,expected_snapshot=expected,
                                       decision=decision,supersedes=supersedes,basis=basis,aliases=aliases)
        elif op=='propose':
            note_stage('request')
            changes={}
            for path,value in request.get('changes',{}).items():
                if value is None:changes[path]=None
                elif isinstance(value,str):changes[path]=value.encode()
                elif isinstance(value,dict) and set(value)=={'base64'}:changes[path]=base64.b64decode(value['base64'],validate=True)
                else:raise RequestError('Changes require text, base64 object, or null',option='changes')
            result=app.propose(changes,base=request.get('base'),grounds=request.get('grounds'),explanation=request.get('explanation'))
        elif op=='apply':
            note_stage('request')
            key=args.idempotency_key or request.get('idempotency_key')
            if not key:raise RequestError('apply requires an idempotency key',option='--idempotency-key')
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
        raise RequestError('A new destination is required',option='--destination')
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
        raise RequestError('Restore requires an archive and a new restore data home',option='--file' if not archive else '--restore-data-home')
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
    # A caller's correctable request first: its message may quote values that contain any word.
    if isinstance(exc,RequestError):return 'invalid_request'
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
        # Display flags only change presentation; other operations ignore them.
        agent_view=args.operation in {'enter','context'} and (args.brief or args.compact)
        if agent_view and not any(arg=='--budget' or str(arg).startswith('--budget=') for arg in (sys.argv[1:] if argv is None else argv)):
            # The agent view summarizes selected records, so selection is not
            # starved by a few large pinned ones; the display has its own target.
            args.budget=AGENT_VIEW_RECORD_BUDGET
        if common:
            if 'request_id' in request and (not isinstance(request['request_id'],str) or not request['request_id']):raise RequestError('request_id must be nonempty text',option='request_id')
            if 'operation' in request and request['operation']!=args.operation:raise RequestError('Request operation differs from CLI operation',option='operation')
        emitted_warnings=[]
        def render(result):
            displayed=routed_navigation(result,args,request=request)
            output=result_envelope(request,args.operation,displayed) if common else displayed
            if agent_view:
                from .context_display import brief_context
                brief=routed_navigation(brief_context(result),args,request=request)
                note_delivery(args,result,brief)
                output=result_envelope(request,args.operation,brief) if common else brief
            elif args.compact and args.operation == 'assess':
                from .coding_assessment import compact_assessment
                compact = compact_assessment(result)
                output = result_envelope(request,args.operation,compact) if common else compact
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
        result=error_document(exc,sys.argv[1:] if argv is None else argv)
        if getattr(exc, 'diagnostic_warnings', None):result['warnings']=exc.diagnostic_warnings
        output=result_envelope(request,args.operation,result,error=True) if common else result
        print(json.dumps(output,ensure_ascii=False),file=sys.stderr)
        return 2


def error_document(exc, argv=()):
    """What a refused caller is told: {error, message, refusal?, option?, record_ids?, next?}, plus the lock fields.

    A request error names the option at fault and any full record IDs. For an
    unknown ID that starts exactly one readable record, ``next`` is the caller's
    own ``argv`` with only that value replaced by the full ID. An acceptance by ID
    that fails after its first write adds ``accepted_so_far``, the exact
    references it accepted.
    """
    from .file_lock import LockBusy
    result={'error':error_code(exc),'message':str(exc)}
    if isinstance(exc,RequestError):
        command=exc.next
        if command is None and exc.refusal=='unknown_id' and len(exc.record_ids)==1 and exc.option and exc.value is not None:
            command=corrected_command(argv,exc.option,exc.value,exc.record_ids[0])
        result.update((name,value) for name,value in (('refusal',exc.refusal),('option',exc.option),('record_ids',list(exc.record_ids)),('next',command)) if value)
    if getattr(exc,'accepted_so_far',None):result['accepted_so_far']=exc.accepted_so_far
    if isinstance(exc,LockBusy):
        result.update(retryable=True, lock_kind=exc.lock_kind, waited_ms=exc.waited_ms)
    return result


def workspace_entry(args, request):
    from ..application.workspace import WorkspaceService, exact_reference
    from .operation_diagnostics import note_stage
    note_stage('request')
    personal = request.get('personal', args.personal)
    if type(personal) is not bool:
        raise RequestError('personal must be boolean', option='personal')
    if args.resume is not None and 'resume' in request:
        raise RequestError('Choose one resume reference', option='--resume')
    resume = request_json(args.resume, '--resume') if args.resume is not None else request.get('resume')
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
            raise RequestError('Scope outside resolved route', option='--scope')
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
