"""Explicit, local command-line adapter for the knowledge kernel."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .kernel import Kernel, KernelError, parse_markdown
from .integration import global_root, bind_project, enter_project, load_config, binding_for


def resolve_root(value: str | None) -> Path:
    """Resolve explicit configuration or the nearest project-local pointer."""
    configured = value or os.environ.get("EKK_ROOT")
    if configured:
        return Path(configured).expanduser().absolute()
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        marker = directory / ".ekk-root"
        if marker.is_file():
            raw = marker.read_text(encoding="utf-8").strip()
            root = Path(raw)
            if not raw or not root.is_absolute():
                raise ValueError(f"{marker} must contain an absolute root path")
            return root.absolute()
    fallback = global_root()
    if fallback is not None:
        return fallback
    raise ValueError("No kernel root: supply --root, EKK_ROOT, .ekk-root, or install global integration")


def command_vector(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"Invalid command JSON: {exc.msg}") from exc
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and "\x00" not in item for item in value
    ) or not value[0].strip():
        raise argparse.ArgumentTypeError("Command must be a nonempty JSON array of strings")
    return value


def add_scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scope", dest="scopes", action="append", required=True,
                        help="Applicability scope; repeat for multiple scopes (not an OS permission)")


def add_time(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--at", help="Valid time (ISO timestamp with timezone)")
    parser.add_argument("--known-at", help="Knowledge-time cutoff (ISO date/time)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ekk", description="Local knowledge kernel")
    parser.add_argument("--root", help="Kernel directory (otherwise EKK_ROOT or .ekk-root)")
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("realm", help="Governed realms; use ekk realm --help")
    sub.add_parser("pilot", help="Run the synthetic v0.3 end-to-end pilot; use ekk pilot --help")
    sub.add_parser("init", help="Initialize the selected kernel root")
    upgrade = sub.add_parser("upgrade", help="Explicitly activate new semantics; preserve canonical bytes")
    upgrade.add_argument("--from-version", default="0.1.0")
    upgrade.add_argument("--execute", action="store_true")
    enter = sub.add_parser("enter", help="Read the current project context and reconsideration candidates")
    enter.add_argument("--cwd", type=Path, default=Path.cwd())
    enter.add_argument("--task", default="")
    bind = sub.add_parser("project-bind", help="Bind an authorized personal project to stable scopes")
    bind.add_argument("--path", type=Path, required=True)
    bind.add_argument("--scope", dest="scopes", action="append")
    bind.add_argument("--audience", choices=["self"], required=True)
    bind.add_argument("--retention", choices=["significant", "read-only"], required=True)

    observe = sub.add_parser("observe", help="Capture a local source file")
    observe.add_argument("file", type=Path)
    observe.add_argument("--title", required=True)
    add_scope(observe)
    observe.add_argument("--author", required=True)
    observe.add_argument("--valid-from")

    reference = sub.add_parser("reference", help="Retain a versioned external source reference")
    reference.add_argument("uri")
    reference.add_argument("--version", required=True)
    reference.add_argument("--sha256", required=True)
    reference.add_argument("--title", required=True)
    reference.add_argument("--author", required=True)
    add_scope(reference)

    add = sub.add_parser("add", help="Add a Markdown record with YAML frontmatter")
    add.add_argument("file", type=Path)
    get = sub.add_parser("get", help="Read a record by explicit ID")
    get.add_argument("id")

    for name in ("list", "compile", "evolve"):
        command = sub.add_parser(name)
        add_scope(command)
        add_time(command)
        if name in ("compile", "evolve"):
            command.add_argument("--semantic-version", help="Explicit historical semantic implementation")
        if name == "compile":
            command.add_argument("--task", default="")

    provenance = sub.add_parser("provenance", help="Read scoped provenance")
    provenance.add_argument("id")
    add_scope(provenance)
    sub.add_parser("check", help="Check kernel integrity")
    rebuild = sub.add_parser("rebuild", help="Rebuild scoped derived state")
    add_scope(rebuild)

    recover = sub.add_parser("recover", help="Verify current state after an interrupted action; never rerun it")
    recover.add_argument("--action", required=True)
    add_scope(recover)
    recover.add_argument("--verify-json", type=command_vector, required=True)
    recover.add_argument("--cwd", type=Path, required=True)
    recover.add_argument("--authority", required=True)
    recover.add_argument("--execute", action="store_true")

    run = sub.add_parser("run", help="Execute explicit local argument vectors and verify")
    run.add_argument("--commitment", required=True)
    add_scope(run)
    run.add_argument("--command-json", type=command_vector, required=True)
    run.add_argument("--verify-json", type=command_vector, required=True)
    run.add_argument("--cwd", type=Path, required=True)
    run.add_argument("--authority", required=True)
    run.add_argument("--rollback", required=True)
    run.add_argument("--execute", action="store_true",
                     help="Explicitly authorize this local execution")
    return parser


def dispatch(args: argparse.Namespace, kernel: Kernel):
    operation = args.operation
    if operation == "recover":
        if not args.execute:
            raise ValueError("recover requires --execute to run the explicit verifier")
        return kernel.recover(args.action, args.scopes, args.verify_json,
                              args.cwd.expanduser().resolve(), args.authority)
    if operation == "enter":
        return enter_project(args.cwd, args.task, root=kernel.root)
    if operation == "project-bind":
        if global_root() != kernel.root.resolve():
            raise ValueError("Project binding root differs from selected root")
        return bind_project(args.path, args.scopes, args.audience, args.retention)
    if operation == "upgrade":
        if not args.execute:
            raise ValueError("upgrade requires --execute after a recoverable snapshot")
        return kernel.upgrade(expected_version=args.from_version)
    if operation == "init":
        result = kernel.init()
        return result if result is not None else {"initialized": True}
    if operation == "observe":
        return kernel.observe(args.file, title=args.title, scopes=args.scopes,
                              author=args.author, valid_from=args.valid_from)
    if operation == "reference":
        return kernel.reference(args.uri, args.version, args.sha256, args.title, args.scopes, args.author)
    if operation == "add":
        metadata, body = getattr(args, "_record", None) or parse_markdown(args.file.read_text(encoding="utf-8"))
        return kernel.add(metadata, body)
    if operation == "get":
        return getattr(args, "_get_result", None) or kernel.get(args.id)
    if operation in ("list", "compile", "evolve"):
        kwargs = {"scopes": args.scopes, "at": args.at, "known_at": args.known_at}
        if operation in ("compile", "evolve"):
            kwargs["semantic_version"] = args.semantic_version
        if operation == "compile":
            kwargs["task"] = args.task
        return getattr(kernel, operation)(**kwargs)
    if operation == "provenance":
        return kernel.provenance(args.id, scopes=args.scopes)
    if operation == "check":
        return kernel.check()
    if operation == "rebuild":
        return kernel.rebuild(scopes=args.scopes)
    if operation == "run":
        if not args.execute:
            raise ValueError("run requires --execute to authorize local execution")
        return kernel.run(commitment_id=args.commitment, scopes=args.scopes,
                          command=args.command_json, verifier=args.verify_json,
                          cwd=args.cwd.expanduser().resolve(), authority=args.authority,
                          rollback=args.rollback)
    raise ValueError(f"Unknown operation: {operation}")


def guard_global_route(args, kernel):
    """Automatic global access respects binding; explicit root is deliberate admin access."""
    if args.root or os.environ.get("EKK_ROOT"):
        return
    cfg = load_config()
    if not cfg or kernel.root.resolve() != Path(cfg['root']).resolve():
        return
    if args.operation in ('enter', 'project-bind'):
        return
    if args.operation in ('init', 'upgrade', 'check'):
        raise KernelError('Root-wide administration requires explicit --root')
    cwd = args.cwd if args.operation in ('run', 'recover') else Path.cwd()
    binding = binding_for(cfg, cwd)
    if binding is None:
        raise KernelError('Unbound project: use enter and establish owner/audience before access')
    writing = args.operation in ('observe', 'reference', 'add', 'run', 'recover', 'rebuild')
    if writing and binding['retention'] == 'read-only':
        raise KernelError('Project retention is read-only')
    if args.operation == 'get':
        args._get_result = kernel.get(args.id)
        if not set(args._get_result['metadata']['scopes']) & set(binding['scopes']):
            raise KernelError('Record outside project binding scopes')
        return
    scopes = getattr(args, 'scopes', None)
    if args.operation == 'add':
        args._record = parse_markdown(args.file.read_text(encoding='utf-8'))
        scopes = args._record[0].get('scopes')
    if not isinstance(scopes, list) or not scopes or not set(scopes) <= set(binding['scopes']):
        raise KernelError('Requested scopes are outside project binding')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Current operations share one application service. Historical commands remain
    # available only for unmigrated roots and replay fixtures.
    from .adapters.command_line import OPERATIONS, main as current_main
    from .adapters.local_profile import binding as current_binding
    if not argv or argv in (['--help'], ['-h']):
        return current_main(['--help'])
    if argv and argv[0] == 'work':
        from .adapters.work_cli import main as work_main
        return work_main(argv[1:])
    if argv == ['--version']:
        from . import __version__
        print(f'EKK {__version__} (record format 0.1)')
        return 0
    if argv == ['--legacy-help']:
        build_parser().print_help()
        return 0
    operation = next((a for a in argv if a in OPERATIONS | {'enter', 'init', 'recover'}), None)
    if operation in OPERATIONS or (operation in {'init', 'recover'} and '--root' not in argv[:argv.index(operation)]):
        return current_main(argv)
    entry_cwd = Path(argv[argv.index('--cwd')+1]) if '--cwd' in argv and argv.index('--cwd')+1 < len(argv) else Path.cwd()
    if operation == 'enter':
        if any(flag in argv for flag in ('--profile', '--realm', '--compact', '--json', '--stdin')):
            return current_main(argv)
        try:
            portable = current_binding(entry_cwd)
        except (ValueError, OSError, KeyError, TypeError):
            # The current adapter owns structured errors for malformed bindings.
            return current_main(argv)
        if portable is not None:
            return current_main(argv)
        try:
            legacy_config = load_config() or {}
        except (KernelError, OSError, ValueError) as exc:
            print(json.dumps({'error': 'invalid_legacy_configuration', 'message': str(exc)}), file=sys.stderr)
            return 2
        # Retain configured historical integrations for replay. Stale paths alone
        # do not turn a fresh, unbound project into a legacy installation.
        registry_path = os.environ.get('EKK_REALM_REGISTRY')
        legacy_configured = bool(legacy_config) or bool(registry_path and Path(registry_path).expanduser().is_file())
        if legacy_config.get('runtime_retired', False) or not legacy_configured:
            return current_main(argv)
    if argv and argv[0] == "realm":
        from .realm_cli import main as realm_main
        return realm_main(argv[1:])
    if argv and argv[0] == "pilot":
        from .pilot import main as pilot_main
        return pilot_main(argv[1:])
    args = build_parser().parse_args(argv)
    try:
        if not args.root and not os.environ.get("EKK_ROOT"):
            from .realm_registry import RealmRegistry
            registry = RealmRegistry()
            cwd = getattr(args, 'cwd', Path.cwd())
            if args.operation == 'enter':
                routed = registry.enter(cwd, args.task)
                if routed is not None:
                    print(json.dumps(routed, ensure_ascii=False, indent=2, default=str))
                    return 0
            elif args.operation != 'project-bind' and registry.route(cwd) is not None:
                raise KernelError('Governed project: use ekk realm commands; legacy administration requires explicit --root')
        kernel = Kernel(resolve_root(args.root))
        guard_global_route(args, kernel)
        result = dispatch(args, kernel)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.operation == "recover" and not result.get("recovered"):
            return 1
        if args.operation == "run" and result.get("verdict") != "met":
            return 1
        return 0
    except (KernelError, OSError, ValueError) as exc:
        print(f"ekk: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
