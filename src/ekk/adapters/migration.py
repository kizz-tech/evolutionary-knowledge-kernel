"""Explicit, local migration preparation. Source trees and realms are never mutated.

Inventory reads names/stat only. Conversion reads bodies only for explicitly routed
units. Snapshots are private full byte copies, including ignored/untracked files and
nested Git histories; linked worktrees/alternates require separately scoped capture
and are rejected rather than represented as independently restorable.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import os
import stat
import subprocess


class MigrationError(ValueError):
    pass


def _root(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise MigrationError('Symlink roots or ancestors are not supported')
    return path


def _path(root, relative):
    value = Path(relative)
    if value.is_absolute() or '..' in value.parts or str(value) in ('', '.'):
        raise MigrationError('Expected a relative source unit path')
    result = root / value
    if any(p.is_symlink() for p in (result, *result.parents) if p != root.parent):
        raise MigrationError('Symlink source units are not read')
    return result


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise MigrationError('Only regular files can be captured')
        data = stream.read()
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise MigrationError('Source changed while being captured')
    return data


def inventory(root):
    """Name/stat inventory including nested repos, links, ignored and untracked files.

    No source bodies, symlink targets, Git remotes, diffs or credential values are
    returned. Git status paths are metadata, never source authority or routing.
    """
    root = _root(root)
    if not root.is_dir():
        raise MigrationError('Source root does not exist')
    units, repositories = [], []
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in sorted(dirs + files):
            path = base / name
            info = path.lstat()
            kind = 'symlink' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'special'
            relative = path.relative_to(root).as_posix()
            units.append({'path': relative, 'type': kind, 'bytes': info.st_size if kind == 'file' else None})
        if '.git' in dirs or '.git' in files:
            item = {'path': base.relative_to(root).as_posix(), 'git_storage': 'internal' if (base / '.git').is_dir() and not (base / '.git').is_symlink() else 'external_or_link'}
            if item['git_storage'] == 'internal':
                env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}
                result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '-C', str(base), 'status', '--porcelain=v1', '-z', '--untracked-files=all'], capture_output=True, env=env)
                item['status_verified'] = result.returncode == 0
                item['dirty'] = bool(result.stdout) if result.returncode == 0 else None
                # Do not include command stderr or configuration in reports.
                head = subprocess.run(['git', '-C', str(base), 'rev-parse', '--verify', 'HEAD'], capture_output=True, env=env)
                candidate = head.stdout.decode('ascii', errors='ignore').strip()
                item['head'] = candidate if head.returncode == 0 and len(candidate) in (40, 64) and all(c in '0123456789abcdef' for c in candidate) else None
            repositories.append(item)
    return {'root': str(root), 'units': sorted(units, key=lambda x: x['path']), 'repositories': repositories, 'body_read': False}


def _capture(root, destination):
    entries = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in sorted(dirs + files):
            path = base / name
            relative = path.relative_to(root).as_posix()
            target = destination / relative
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                # Preserve link metadata without following the link or exposing it.
                link = os.readlink(path)
                os.symlink(link, target)
                entries.append({'path': relative, 'type': 'symlink', 'sha256': sha256(os.fsencode(link)).hexdigest()})
            elif stat.S_ISDIR(info.st_mode):
                target.mkdir(mode=0o700)
                entries.append({'path': relative, 'type': 'directory', 'mode': mode})
            elif stat.S_ISREG(info.st_mode):
                data = _read(path)
                with target.open('xb') as stream:
                    stream.write(data)
                target.chmod(mode & 0o700)
                entries.append({'path': relative, 'type': 'file', 'mode': mode, 'bytes': len(data), 'sha256': sha256(data).hexdigest()})
            else:
                raise MigrationError('Snapshot cannot preserve special filesystem objects')
    return sorted(entries, key=lambda x: x['path'])


def _fingerprints(root):
    entries = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                entries.append((relative, 'symlink', sha256(os.fsencode(os.readlink(path))).hexdigest()))
            elif stat.S_ISDIR(info.st_mode):
                entries.append((relative, 'directory', None))
            elif stat.S_ISREG(info.st_mode):
                entries.append((relative, 'file', sha256(_read(path)).hexdigest()))
            else:
                raise MigrationError('Unsupported filesystem object')
    return sorted(entries)


def create_snapshot(source, destination):
    """Create an independent private snapshot in a NEW directory outside source.

    Explicit invocation authorizes reading every file under source, including Git
    metadata. Use an authorized bounded source; inventory itself needs no body read.
    """
    source, destination = _root(source), _root(destination)
    if destination == source or destination.is_relative_to(source):
        raise MigrationError('Snapshot must be outside source')
    report = inventory(source)
    for repo in report['repositories']:
        git = source / repo['path'] / '.git'
        if repo['git_storage'] != 'internal' or (git / 'objects/info/alternates').exists() or (git / 'commondir').exists() or any(unit['type'] == 'symlink' and (source / unit['path']).is_relative_to(git) for unit in report['units']):
            raise MigrationError('External Git storage requires a separately authorized independent capture')
    before = _fingerprints(source)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    tree = destination / 'tree'
    tree.mkdir(mode=0o700)
    entries = _capture(source, tree)
    if before != _fingerprints(tree) or before != _fingerprints(source):
        raise MigrationError('Source changed or snapshot byte verification failed')
    manifest = {'schema': 'ekk.migration-snapshot/1', 'source': str(source), 'entries': entries, 'repositories': report['repositories'], 'verified': True}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    (destination / 'manifest.json').chmod(0o600)
    return {'snapshot': str(destination), 'verified': True, 'units': len(entries), 'restore_verified': False, 'limitations': ['Symlink objects are preserved; external targets and objects outside the source root are not captured.']}


def restore_snapshot(snapshot, destination):
    """Prove restoration into a NEW directory; never replace an existing path."""
    snapshot, destination = _root(snapshot), _root(destination)
    if destination == snapshot or destination.is_relative_to(snapshot):
        raise MigrationError('Restore destination must be separate from snapshot')
    manifest = json.loads(_read(_path(snapshot, 'manifest.json')))
    if manifest.get('schema') != 'ekk.migration-snapshot/1' or not manifest.get('verified'):
        raise MigrationError('Snapshot manifest is invalid')
    tree = _root(snapshot / 'tree')
    expected = sorted((x['path'], x['type'], x.get('sha256')) for x in manifest['entries'])
    if expected != _fingerprints(tree):
        raise MigrationError('Snapshot integrity verification failed')
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    _capture(tree, destination)
    if expected != _fingerprints(destination):
        raise MigrationError('Restore verification failed')
    return {'destination': str(destination), 'restore_verified': True, 'units': len(expected)}


def plan_migration(source, routes, *, source_id, existing_ids=(), legacy_records=None):
    """Return prepared payloads and complete routing ledger, without realm writes.

    routes maps exact relative paths to {action, reason, realm, context, audience,
    target_id?, classification?, origin_created_at?}. Actions: migrate, external, archive, exclude, review. Only migrate
    reads bytes; it requires ALL three destination fields. No prefix inference.
    legacy_records is an explicitly scoped v0.2 _load()-shaped mapping; callers must
    obtain it only after authorizing its body scope. All immutable IDs survive,
    including superseded records. Source descriptors and their artifact bytes are
    pinned separately. Every imported record is historical, never adopted.
    """
    source = _root(source)
    if not isinstance(source_id, str) or not source_id:
        raise MigrationError('A stable source namespace is required')
    report = inventory(source)
    units = {x['path']: x for x in report['units']}
    if set(routes) - set(units):
        raise MigrationError('Routing map refers to absent source units')
    legacy_by_path = {}
    for identifier, record in (legacy_records or {}).items():
        path = record['path']
        if path in legacy_by_path or identifier != record['metadata'].get('id'):
            raise MigrationError('Legacy ID/path collision')
        legacy_by_path[path] = (identifier, record)
    used = set(existing_ids)
    ledger, changes = [], []
    for relative, unit in sorted(units.items()):
        route = routes.get(relative, {})
        action = route.get('action', 'review')
        if action not in {'migrate', 'external', 'archive', 'exclude', 'review'}:
            raise MigrationError('Unknown routing action')
        row = {'origin': {'source_id': source_id, 'path': relative, 'id': None, 'revision': None, 'sha256': None}, 'action': action, 'realm': route.get('realm'), 'context': route.get('context'), 'audience': route.get('audience'), 'target_ids': [], 'transformation': None, 'reason': route.get('reason') or 'No explicit routing decision', 'verification': 'not_converted'}
        if action != 'review' and not route.get('reason'):
            row.update(action='review', reason='Explicit routing reason required')
        elif action == 'migrate' and (unit['type'] != 'file' or not all(isinstance(route.get(k), str) and route[k] for k in ('realm', 'context', 'audience', 'reason'))):
            row.update(action='review', reason='Migration needs a regular file and explicit realm, context, audience and reason')
        elif action == 'migrate':
            raw = _read(_path(source, relative))
            digest = sha256(raw).hexdigest()
            legacy_id, legacy = legacy_by_path.get(relative, (None, None))
            identifier = route.get('target_id') or legacy_id or 'legacy-' + sha256((source_id + '\0' + relative).encode()).hexdigest()[:32]
            if not isinstance(identifier, str) or not identifier or identifier in used:
                raise MigrationError('Target ID collision or invalid ID')
            used.add(identifier)
            row['origin'].update(id=legacy_id, revision=digest, sha256=digest, created_at=None)
            originals = [{'origin_path': relative, 'sha256': digest, 'bytes': raw}]
            body = raw.decode('utf-8') if _is_text(raw) else 'Original binary source preserved in pinned bytes.'
            title, legacy_kind = Path(relative).name, None
            if legacy:
                metadata = legacy['metadata']
                from .markdown import MarkdownCodec
                decoded = MarkdownCodec().decode(raw, allow_aliases=True)
                actual_metadata, actual_body = decoded['metadata'], decoded['body']
                if actual_metadata != metadata or actual_body != legacy['body']:
                    raise MigrationError('Legacy wrapper differs from preserved source bytes')
                body, title, legacy_kind = legacy['body'], metadata.get('title', title), metadata.get('kind')
                artifact = metadata.get('artifact', {})
                if artifact.get('mode') == 'blob':
                    asset_path = artifact.get('path')
                    asset_route = routes.get(asset_path, {})
                    if asset_route.get('action') != 'migrate' or any(asset_route.get(k) != route.get(k) for k in ('realm', 'context', 'audience')):
                        row.update(action='review', reason='Pinned asset needs explicit matching destination authorization')
                        ledger.append(row)
                        used.remove(identifier)
                        continue
                    asset = _read(_path(source, asset_path))
                    if sha256(asset).hexdigest() != artifact.get('sha256') or len(asset) != artifact.get('bytes'):
                        raise MigrationError('Legacy artifact fingerprint mismatch')
                    originals.append({'origin_path': asset_path, 'sha256': sha256(asset).hexdigest(), 'bytes': asset})
            old_metadata = legacy['metadata'] if legacy else {}
            classification = route.get('classification', old_metadata.get('classification', 'private'))
            levels = {'public': 0, 'internal': 1, 'private': 2, 'restricted': 3}
            if classification not in levels:
                raise MigrationError('Unknown classification requires explicit resolution')
            original_classification = old_metadata.get('classification')
            if original_classification in levels and levels[classification] < levels[original_classification]:
                raise MigrationError('Migration cannot lower original classification')
            original_created_at = old_metadata.get('created_at') or old_metadata.get('known_from') or route.get('origin_created_at')
            row['origin']['created_at'] = original_created_at
            payload = {'id': identifier, 'realm': route['realm'], 'context': route['context'], 'audience': route['audience'], 'classification': classification, 'kind': 'source', 'status': 'historical', 'adoption': 'not_adopted', 'title': title, 'body': body, 'format': 'markdown', 'originals': originals, 'origin': dict(row['origin']), 'legacy_kind': legacy_kind, 'legacy_metadata': legacy['metadata'] if legacy else None}
            changes.append(payload)
            row.update(target_ids=[identifier], transformation='Preserve original bytes; import as historical source without adoption', verification='bytes_pinned_prepared')
        ledger.append(row)
    counts = dict(Counter(x['action'] for x in ledger))
    return {'schema': 'ekk.migration-plan/1', 'source_id': source_id, 'changes': changes, 'ledger': ledger, 'coverage': {'total': len(ledger), 'actions': counts, 'unresolved': counts.get('review', 0), 'prepared': len(changes), 'applied': 0, 'all_migrated': False}}


def _is_text(data):
    try:
        data.decode('utf-8')
        return b'\0' not in data
    except UnicodeDecodeError:
        return False


def realm_changes(plan, *, realm, created_by, recorded_at, codec=None, existing_paths=()):
    """Encode one explicitly selected realm's prepared plan for propose/apply.

    Returned mapping is a proposal input, not applied state. The caller supplies
    existing target paths and IDs at planning time; RealmService validates context
    references, authority, CAS and immutable pins before the single writer applies.
    """
    from .markdown import MarkdownCodec
    from ekk.model import validate_envelope
    codec = codec or MarkdownCodec()
    changes, occupied = {}, set(existing_paths)

    def add(path, data):
        if path in occupied or path in changes:
            raise MigrationError('Target path collision')
        changes[path] = data

    for item in plan['changes']:
        if item['realm'] != realm:
            continue
        identifier = item['id']
        # IDs need not be filenames (legacy IDs are open identifiers).
        file_id = sha256(identifier.encode()).hexdigest()
        pins = []
        for index, original in enumerate(item['originals']):
            raw = original['bytes']
            if sha256(raw).hexdigest() != original['sha256']:
                raise MigrationError('Prepared bytes no longer match their pin')
            suffix = '.md' if _is_text(raw) else '.bin'
            path = f'sources/{file_id}/original-{index}{suffix}'
            add(path, raw)
            pins.append({'path': path, 'sha256': original['sha256']})
        original_created_at = item['origin'].get('created_at')
        legacy_metadata = item['legacy_metadata'] or {}
        record_author = legacy_metadata.get('created_by') or legacy_metadata.get('author') or created_by
        metadata = {'schema': 'ekk.record/0.1', 'id': identifier, 'kind': 'source', 'title': item['title'], 'scope': [item['context']], 'revision': 1, 'created_at': original_created_at or recorded_at, 'created_by': record_author, 'classification': item['classification'], 'audience': item['audience'], 'source': {'assets': pins}, 'recorded_at': recorded_at, 'migration': {'origin': item['origin'], 'originals': pins, 'legacy_kind': item['legacy_kind'], 'legacy_metadata': item['legacy_metadata'], 'status': 'historical', 'adoption': 'not_adopted', 'recorded_by': created_by, 'created_at_basis': 'preserved_legacy_record_or_explicit_origin' if original_created_at else 'new_wrapper_creation_original_unknown'}}
        validate_envelope(metadata)
        add(f'records/{file_id}.md', codec.encode(metadata, item['body']))
    return changes
