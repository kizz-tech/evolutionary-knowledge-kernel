"""Explicit local method lifecycle using current project routing and installed adapters."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
from .command_line import service, _routes
from .local_profile import binding, data_home
from .method_repository import RealmMethodRepository
from .method_execution import LocalMethodExecutor
from .builtin_methods import registry
from ekk.application.methods import MethodService

OPERATIONS = frozenset({'propose','evaluate','admit','use','reconsider','quarantine','retire','export','receive','inspect'})


def dispatch(app, scopes, operation, request):
    from .operation_diagnostics import observed_call
    realm = app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])['id']
    key = request.get('idempotency_key') if isinstance(request, dict) else None
    return observed_call('method.' + operation, lambda: _dispatch(app, scopes, operation, request),
                         realm_id=realm, principal=app.principal, key=key if isinstance(key, str) else None)


def _dispatch(app, scopes, operation, request):
    """Shared local method entry for CLI and private transports; no caller code loading."""
    from copy import deepcopy
    if operation not in OPERATIONS or not isinstance(request, dict):
        raise ValueError('known method operation and object request required')
    request = deepcopy(request)
    repo = RealmMethodRepository(app, scopes=scopes, journal_root=data_home()/'method-proposals')
    executor = LocalMethodExecutor(registry(), data_home()/'method-evidence',
        authorize=lambda operation, method, facts: method['spec']['privileges'] == [])
    coordinator = MethodService(repo, executor)
    if operation == 'propose':
        request['artifact'] = base64.b64decode(request.pop('artifact_base64'), validate=True)
    if operation == 'inspect':
        if set(request) != {'reference'}:
            raise ValueError('inspect requires only an exact reference')
        loaded = repo.load(request['reference'])
        result = {key: value for key, value in loaded.items() if key != 'artifact'}
        result['local_admission'] = repo.active(request['reference'])
        return result
    return getattr(coordinator, operation)(**request)


def main(argv=None):
    p=argparse.ArgumentParser(prog='ekk method', description=__doc__)
    p.add_argument('operation', choices=['propose','evaluate','admit','use','reconsider','quarantine','retire','export','receive','inspect'])
    p.add_argument('--cwd', type=Path, default=Path.cwd())
    p.add_argument('--profile', default=os.environ.get('EKK_PROFILE'))
    p.add_argument('--realm'); p.add_argument('--root',type=Path)
    p.add_argument('--scope', action='append', default=[])
    p.add_argument('--json', type=Path)
    args=p.parse_args(argv)
    try:
        selected=binding(args.cwd) if not args.root and not args.realm else None
        args.profile=args.profile or (selected[1].get('profile','personal') if selected else 'personal')
        routes=_routes(args)
        if len(routes)!=1:raise ValueError('method mutation requires one explicit owning realm')
        route=routes[0]
        app=service(route['path'],allowed_scopes=route['scopes'] or None)
        scopes=route['scopes']
        if not scopes:
            manifest=app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])
            scopes=[manifest['default_context']] if manifest.get('default_context') else []
        request=json.loads(args.json.read_text() if args.json else sys.stdin.read())
        result=dispatch(app,scopes,args.operation,request)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps({'error':'method_request_failed','message':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
