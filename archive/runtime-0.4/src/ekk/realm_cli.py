"""Local-OS governed client plus explicitly labelled owner administration."""
from pathlib import Path
import argparse
import json
import sys
from .kernel import KernelError
from .realm_registry import RealmRegistry


def parser():
    p=argparse.ArgumentParser(prog='ekk realm',description='Governed realms (local OS identity adapter)')
    p.add_argument('--registry',type=Path)
    sub=p.add_subparsers(dest='operation',required=True)
    init=sub.add_parser('admin-init',help='Initialize owner-controlled local identity registry')
    init.add_argument('--owner',required=True)
    create=sub.add_parser('admin-create',help='Create a new empty sovereign store; no migration')
    create.add_argument('--path',type=Path,required=True);create.add_argument('--id',required=True)
    reg=sub.add_parser('admin-register');reg.add_argument('--path',type=Path,required=True)
    move=sub.add_parser('admin-relocate');move.add_argument('--id',required=True);move.add_argument('--path',type=Path,required=True)
    bind=sub.add_parser('admin-bind');bind.add_argument('--cwd',type=Path,required=True);bind.add_argument('--realm',required=True)
    bind.add_argument('--scope',action='append',required=True);bind.add_argument('--retention',choices=['significant','read-only'],default='significant')
    for name in ('enter','list','get','provenance','export','contribute','adopt'):
        q=sub.add_parser(name);q.add_argument('--cwd',type=Path,default=Path.cwd())
        q.add_argument('--purpose',default='');q.add_argument('--known-at');q.add_argument('--valid-at')
        if name in ('get','provenance','adopt'):q.add_argument('--ref',required=True,help='JSON qualified RecordRef')
        if name=='contribute':q.add_argument('file',type=Path);q.add_argument('--audience',default='private')
        if name=='adopt':
            q.add_argument('--predicate',required=True)
            q.add_argument('--basis',default='',help='Optional decision rationale or external evidence ID')
            q.add_argument('--expected',default='[]',help='JSON array of currently governing qualified refs')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        from .realms import RealmStore,Grant,RecordRef
        registry=RealmRegistry(args.registry)
        op=args.operation
        if op=='admin-init':result=registry.initialize(args.owner)
        elif op=='admin-create':
            cfg=registry.load()
            if not cfg:raise KernelError('Initialize registry first')
            owner=registry.principal(cfg)
            RealmStore.create(args.path.resolve(),args.id,grants=[Grant(owner,('*',),audiences=('*',))])
            result=registry.register(args.path)
        elif op=='admin-register':result=registry.register(args.path)
        elif op=='admin-relocate':result=registry.relocate(args.id,args.path)
        elif op=='admin-bind':result=registry.bind(args.cwd,args.realm,args.scope,args.retention)
        else:
            route=registry.route(args.cwd)
            if route is None:raise KernelError('Project has no governed realm binding')
            session,binding=route
            if op in ('contribute','adopt') and binding['retention']=='read-only':raise KernelError('Project is read-only')
            view=session.view(scopes=binding['scopes'],purpose=args.purpose,known_at=args.known_at,valid_at=args.valid_at)
            if op=='enter':result=view.compile()
            elif op=='list':result=view.list()
            elif op=='export':result=view.export()
            elif op in ('get','provenance'):
                result=getattr(view,op)(RecordRef.from_dict(json.loads(args.ref)))
            elif op=='contribute':
                result=session.contribute(args.file.read_text(),scopes=binding['scopes'],audience=args.audience).to_dict()
            elif op=='adopt':
                result=session.adopt(RecordRef.from_dict(json.loads(args.ref)),predicate=args.predicate,affected_scopes=binding['scopes'],expected_current=[RecordRef.from_dict(r) for r in json.loads(args.expected)],basis=args.basis).to_dict()
        print(json.dumps(result,ensure_ascii=False,indent=2,default=str));return 0
    except (KernelError,ValueError,OSError,KeyError,TypeError) as exc:
        print(f'ekk realm: {exc}',file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
