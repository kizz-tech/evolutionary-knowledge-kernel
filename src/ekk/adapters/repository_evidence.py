"""Bounded read-only checks of explicitly configured current project files.

Records name checks; the owning workspace binding alone selects readable paths.
No retrieved text can choose a filesystem root, executable or new check path.
Matching bytes do not establish the truth of the associated assertion.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

MAX_CHECKS = 32
MAX_FILE_BYTES = 16 * 1024 * 1024
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')


def configured_checks(document):
    """Owner-selected check IDs and files; callers own payload interpretation."""
    rows = document.get('evidence_checks', [])
    if not isinstance(rows, list) or len(rows) > MAX_CHECKS:
        raise ValueError('At most 32 workspace evidence checks are supported')
    output = {}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'id', 'path'}
                or not isinstance(row['id'], str) or not _ID.fullmatch(row['id'])
                or not isinstance(row['path'], str) or len(row['path']) > 4096):
            raise ValueError('Workspace evidence check requires an ID and relative path')
        path = PurePosixPath(row['path'])
        if (path.is_absolute() or str(path) != row['path'] or '..' in path.parts
                or '.' in path.parts or not path.parts or '.git' in path.parts
                or '\\' in row['path'] or row['id'] in output):
            raise ValueError('Invalid or duplicate workspace evidence check')
        output[row['id']] = row['path']
    return output


def read_configured_bytes(root, relative, *, max_bytes):
    """Read one bounded regular file without following any symlink component.

    Directory descriptors bind traversal to the directories actually opened;
    a separate is_symlink check followed by an absolute open would race.
    """
    if not isinstance(relative, str):
        raise ValueError('Configured source requires a relative path')
    root = Path(root)
    path = PurePosixPath(relative)
    if (not root.is_absolute() or '..' in root.parts
            or path.is_absolute() or str(path) != relative or '..' in path.parts
            or not path.parts or '\\' in relative):
        raise ValueError('Configured source requires an absolute root and a relative nontraversing path')
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('Configured source requires a positive byte limit')
    absolute = root / path
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(absolute.anchor, directory_flags)
    try:
        for component in absolute.parts[1:-1]:
            child = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise ValueError('Configured source must be a bounded regular file')
        raw = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > max_bytes or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('Configured source changed or exceeds the byte limit')
    return raw


def check_repository(context, workspace_root, document):
    """Attach observations to emitted records, within a selected workspace route."""
    checked_at = datetime.now(timezone.utc).isoformat()
    result = {'schema': 'ekk.repository-checks/0.1', 'checks': [], 'incomplete': False,
              'checked_at': checked_at, 'coverage': 'emitted records and explicitly configured files only',
              'claim_truth': 'not_inferred', 'authority_effect': 'none'}
    root = Path(workspace_root).expanduser().absolute()
    try:
        configured = configured_checks(document)
        if any(path.is_symlink() for path in (root, *root.parents)):
            raise ValueError('Workspace checks must not traverse symlinks')
    except (ValueError, TypeError, AttributeError):
        result.update(incomplete=True, configuration='unavailable')
        return result
    observed = {}
    for record in context.get('records', []):
        metadata = record['metadata']
        declaration = metadata.get('repository_evidence')
        if declaration is None:
            continue
        reference = {'realm': context['manifest']['realm_id'], 'id': record['id'],
                     'revision': metadata['revision'], 'digest': 'sha256:' + record['digest']}
        if (not isinstance(declaration, dict) or set(declaration) != {'workspace_id', 'files'}
                or declaration.get('workspace_id') != document.get('workspace_id')
                or not isinstance(declaration.get('files'), list)):
            result['incomplete'] = True
            continue
        for item in declaration['files']:
            if len(result['checks']) >= MAX_CHECKS:
                result['incomplete'] = True
                break
            if (not isinstance(item, dict) or set(item) != {'check', 'sha256'}
                    or not isinstance(item['check'], str) or item['check'] not in configured
                    or not isinstance(item['sha256'], str) or not _HASH.fullmatch(item['sha256'])):
                result['incomplete'] = True
                continue
            name = item['check']; relative = configured[name]
            if name not in observed:
                try:
                    raw = read_configured_bytes(root, relative, max_bytes=MAX_FILE_BYTES)
                    observed[name] = hashlib.sha256(raw).hexdigest()
                except (OSError, ValueError):
                    observed[name] = None
            actual = observed[name]
            row = {'statement': reference, 'workspace_id': document['workspace_id'],
                   'check': name, 'path': relative, 'expected_sha256': item['sha256'],
                   'observed_sha256': actual,
                   'status': 'unavailable' if actual is None else 'matches' if actual == item['sha256'] else 'changed',
                   'checked_at': checked_at}
            result['checks'].append(row)
            result['incomplete'] |= actual is None
    if not result['checks']:
        result['coverage'] = 'no applicable repository checks observed'
    result['byte_budget'] = 8192
    while len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()) > result['byte_budget']:
        result['checks'].pop()
        result['incomplete'] = True
    return result


def attach_repository_checks(result, cwd):
    """Only a real resolved workspace binding can enable a current-file adapter."""
    from .local_profile import binding
    selected = binding(cwd)
    if selected is None:
        return result
    root, document = selected
    routes = document.get('bindings', [])
    contexts = result.get('contexts', []) if result.get('schema') == 'ekk.federated-context/0.1' else [result]
    for context in contexts:
        realm = context.get('manifest', {}).get('realm_id')
        if not any(route.get('realm_id') == realm and set(context.get('scopes', [])) <= set(route.get('contexts', [])) for route in routes):
            continue
        checks = check_repository(context, root, document)
        context['repository_checks'] = checks
        context['manifest']['freshness']['repository'] = 'observed_files' if checks['checks'] else 'unknown'
        context['manifest']['incomplete'] |= checks['incomplete']
        if isinstance(context.get('work_view'), dict):
            context['work_view']['repository_checks'] = checks
            context['work_view']['context_incomplete'] = context['manifest']['incomplete']
    return result
