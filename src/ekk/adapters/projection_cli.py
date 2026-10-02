"""`ekk project`: documents rendered from the records of the route's selected contexts.

A projection reads the realm and writes nothing to it. The document is derived
from the records and is generated again after they change; without `--out` it is
printed, with `--out` the file is replaced only once the new text is complete.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from ..application import projection

DOCUMENTS = ('decisions',)


def today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def write_atomically(path, text):
    """The previous document stays intact until the new one is complete."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temporary = path.with_name(f'.{path.name}.ekk-{os.getpid()}')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ekk project', description=__doc__.splitlines()[0])
    parser.add_argument('document', choices=DOCUMENTS)
    parser.add_argument('--cwd', type=Path, default=Path.cwd())
    parser.add_argument('--profile', default=os.environ.get('EKK_PROFILE'))
    parser.add_argument('--realm'); parser.add_argument('--root', type=Path)
    parser.add_argument('--scope', action='append', default=[])
    parser.add_argument('--out', type=Path, help='Write the document to this file instead of printing it')
    args = parser.parse_args(argv)
    try:
        from .activity_cli import resolve
        app, scopes, manifest = resolve(args)
        rows = projection.decision_rows(app, scopes)
        text = projection.decisions_table(rows, today())
        if args.out is None:
            sys.stdout.write(text)
        else:
            if not args.out.is_absolute():
                args.out = args.cwd / args.out  # relative to the project, like every other --cwd route
            write_atomically(args.out, text)
            print(json.dumps({'schema': 'ekk.projection/0.1', 'document': args.document, 'path': str(args.out), 'rows': len(rows),
                              'realm': manifest['id'], 'scopes': list(scopes), 'snapshot': app.store.snapshot()['revision'],
                              'meaning': 'Derived from the records; edit a record and generate the document again.'},
                             ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, PermissionError) as exc:
        from .command_line import error_code
        print(json.dumps({'error': error_code(exc), 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
