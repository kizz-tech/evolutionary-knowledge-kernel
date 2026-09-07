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
        repo=RealmMethodRepository(app,scopes=scopes,journal_root=data_home()/'method-proposals')
        executor=LocalMethodExecutor(registry(), data_home()/'method-evidence',
            authorize=lambda operation,method,facts: method['spec']['privileges']==[])
        coordinator=MethodService(repo,executor)
        request=json.loads(args.json.read_text() if args.json else sys.stdin.read())
        if not isinstance(request,dict):raise ValueError('object request required')
        if args.operation=='propose':
            request['artifact']=base64.b64decode(request.pop('artifact_base64'),validate=True)
        if args.operation=='inspect':
            loaded=repo.load(request['reference'])
            result={k:v for k,v in loaded.items() if k!='artifact'}
            result['local_admission']=repo.active(request['reference'])
        else:
            result=getattr(coordinator,args.operation)(**request)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps({'error':'method_request_failed','message':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
