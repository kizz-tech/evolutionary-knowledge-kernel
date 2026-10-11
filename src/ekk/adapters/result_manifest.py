"""Assemble explicitly declared files into the ordinary retention request.

No route, acceptance, queue or publication authority comes from this document.
The assembler freezes bytes in memory; the existing writer owns their lifecycle.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import stat

from .markdown import MAX_DOCUMENT_BYTES
from .operational_store import canonical

MAX_ARTIFACTS = 32
MAX_OUTBOX_BYTES = 16 * 1048576  # OperationalStore.enqueue's existing bound.


def _digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _parent_fd(path):
    """Open every parent without following symlinks, including replacement races."""
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_regular(path, *, limit=None):
    parent = _parent_fd(path)
    try:
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Declared file must be regular and not a symlink: ' + str(path))
        if limit is not None and before.st_size > limit:
            raise ValueError('Declared file exceeds byte limit: ' + str(path))
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if _signature(opened) != _signature(before):
                raise ValueError('Declared file changed before reading: ' + str(path))
            raw = stream.read() if limit is None else stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (_signature(before) != _signature(after) or _signature(before) != _signature(current)
                or len(raw) != before.st_size):
            raise ValueError('Declared file changed while reading: ' + str(path))
        return raw, _signature(before)
    finally:
        os.close(parent)


def _unchanged(path, signature):
    parent = _parent_fd(path)
    try:
        if _signature(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != signature:
            raise ValueError('Declared file changed during assembly: ' + str(path))
    finally:
        os.close(parent)


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(name + ' must be nonempty text')
    return value


def _path(base, value):
    value = _text(value, 'file path')
    if any(character in value for character in '*?[]'):
        raise ValueError('Declared paths must be exact, without globs')
    path = Path(value)
    return Path(os.path.abspath(path if path.is_absolute() else base / path))


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate manifest field: ' + name)
        result[name] = value
    return result


def assemble_manifest(path):
    """Return title/body/exact artifacts, inventory and ordinary-payload digest.

    Paths are relative to the manifest directory unless explicitly absolute.
    The result is the body, not an implicit extra artifact. Inventory describes
    only these declared bytes, never all links or the surrounding directory.
    """
    path = Path(os.path.abspath(path))
    raw, signature = _read_regular(path, limit=MAX_DOCUMENT_BYTES)
    try:
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON constant')))
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('Manifest must be bounded UTF-8 JSON') from exc
    required = {'schema', 'title', 'result_file', 'artifacts'}
    if not isinstance(document, dict) or set(document) != required:
        raise ValueError('Manifest requires only schema, title, result_file and artifacts')
    if document['schema'] != 'ekk.result-manifest/0.1':
        raise ValueError('Unsupported result manifest schema')
    title = _text(document['title'], 'title')
    declarations = document['artifacts']
    if not isinstance(declarations, list) or len(declarations) > MAX_ARTIFACTS:
        raise ValueError('Manifest accepts at most 32 artifacts')
    result_path = _path(path.parent, document['result_file'])
    result, result_signature = _read_regular(result_path, limit=MAX_DOCUMENT_BYTES)
    try:
        body = result.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('result_file must contain UTF-8 text') from exc
    if not body.strip():
        raise ValueError('result_file must contain a nonempty result')
    inventory = [{'role': 'result', 'file': document['result_file'],
                  'filename': result_path.name, 'sha256': _digest(result), 'size': len(result)}]
    artifacts = []
    files = [(path, signature), (result_path, result_signature)]
    seen_paths = set()
    seen_names = set()
    seen_inodes = set()
    for item in declarations:
        if not isinstance(item, dict) or 'path' not in item or set(item) - {'path', 'filename', 'title'}:
            raise ValueError('Artifact requires path and optional filename/title only')
        source = _path(path.parent, item['path'])
        filename = _text(item.get('filename', source.name), 'filename')
        if filename in {'.', '..'} or Path(filename).name != filename or '/' in filename or '\\' in filename:
            raise ValueError('Artifact filename must be a basename')
        if source in seen_paths or filename in seen_names:
            raise ValueError('Duplicate declared artifact path or filename')
        artifact_title = _text(item['title'], 'artifact title') if 'title' in item else None
        data, source_signature = _read_regular(source)
        inode = source_signature[:2]
        if inode in seen_inodes:
            raise ValueError('Duplicate declared artifact file')
        seen_paths.add(source); seen_names.add(filename); seen_inodes.add(inode)
        artifact = {'data': data, 'filename': filename}
        if artifact_title is not None:
            artifact['title'] = artifact_title
        artifacts.append(artifact)
        inventory.append({'role': 'artifact', 'file': item['path'], 'filename': filename,
                          'sha256': _digest(data), 'size': len(data)})
        files.append((source, source_signature))
    for source, source_signature in files:
        _unchanged(source, source_signature)
    payload = {'title': title, 'body': body, 'artifacts': [
        {'base64': base64.b64encode(item['data']).decode(),
         **{name: item[name] for name in ('filename', 'title') if name in item}}
        for item in artifacts]}
    return {'title': title, 'body': body, 'artifacts': artifacts, 'inventory': inventory,
            'payload_digest': _digest(canonical(payload).encode('utf-8'))}


def preflight_payload(payload, *, route=None, wait=False):
    """Check exact async envelope capacity before enqueue; sync has no binary cap.

    The application must still prepare/validate the actual result record before
    enqueue: its 2 MiB bound includes generated metadata as well as the body.
    """
    if wait:
        return {'mode': 'synchronous', 'source_byte_limit': None}
    if route is None:
        raise ValueError('Async capacity preflight requires the actual route')
    size = len(canonical({'route': route, 'operation': 'retain', 'request': payload}).encode('utf-8'))
    if size > MAX_OUTBOX_BYTES:
        raise ValueError('Outbox request exceeds 16 MiB; publish this declared package with --wait')
    return {'mode': 'queued', 'request_bytes': size, 'max_request_bytes': MAX_OUTBOX_BYTES}


def verify_manifest(package, receipt, *, read_source, fetch_result):
    """Verify frozen inventory via ordinary authorized exact-reference ports.

    read_source(reference, offset=..., limit=...) returns app.read_source's row.
    fetch_result(reference) returns app.fetch_record's row (body, metadata).
    Every call must preserve current route/scopes and the returned exact ref.
    Returns partial/pending on unavailable readback, retaining publication facts.
    """
    items = [{**row, 'state': 'pending'} for row in package['inventory']]
    result_reference = receipt.get('result_reference')
    if result_reference:
        try:
            row = fetch_result(result_reference)
            if (row['reference'] != result_reference or row.get('incomplete')
                    or row['body'] != package['body'] or row['metadata']['title'] != package['title']):
                raise ValueError('Result read-back differs from declared result')
            items[0].update(state='verified', reference=result_reference)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            items[0].update(state='unavailable', error=str(exc))
    sources = {row['filename']: row for row in items[1:]}
    errors = []
    for reference in receipt.get('source_references', []):
        target = None
        try:
            offset = 0
            hasher = hashlib.sha256()
            while True:
                row = read_source(reference, offset=offset, limit=262144)
                filename = Path(row['asset']['path']).name
                target = sources.get(filename)
                if target is None:
                    raise ValueError('Read-back source is outside declared inventory')
                if row['reference'] != reference or row['offset'] != offset or row['total_bytes'] != target['size']:
                    raise ValueError('Source read-back does not match declared file')
                if 'sha256:' + row['asset']['sha256'] != target['sha256']:
                    raise ValueError('Source asset digest differs from declared artifact')
                if row['selection']['state'] != 'whole_object':
                    raise ValueError('Source read-back must cover the whole declared artifact')
                chunk = base64.b64decode(row['base64'], validate=True)
                if row['bytes'] != len(chunk):
                    raise ValueError('Source byte count mismatch')
                hasher.update(chunk)
                offset += len(chunk)
                next_offset = row['next_offset']
                if next_offset is None:
                    break
                if not chunk or next_offset != offset or offset >= target['size']:
                    raise ValueError('Source read-back did not advance consistently')
            if offset != target['size'] or 'sha256:' + hasher.hexdigest() != target['sha256']:
                raise ValueError('Source bytes differ from declared artifact')
            if target['state'] == 'verified':
                raise ValueError('Duplicate source reference for declared artifact')
            target.update(state='verified', reference=reference)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append({'reference': reference, 'error': str(exc)})
            if target is not None:
                target.update(state='unavailable', error=str(exc))
    verified = sum(row['state'] == 'verified' for row in items)
    complete = verified == len(items) and not errors
    return {'schema': 'ekk.result-package/0.1',
            'state': 'complete' if complete else ('partial' if verified else 'pending'),
            'inventory': items, 'verified': verified, 'declared': len(items),
            'unavailable_sources': errors,
            'payload_digest': package['payload_digest'],
            'coverage': 'Declared result body and artifacts only; links and surrounding files are not captured.',
            'accepted': False}
