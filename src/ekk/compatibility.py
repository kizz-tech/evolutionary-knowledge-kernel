"""Recoverable local snapshots and ownership inventory; never infer ownership.

The v0.2 reader stays unchanged. A snapshot is a private administrative artifact,
not an export, and restoration always targets a new empty location.
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import hashlib
import json
import os
import shutil
import tempfile
from .kernel import Kernel, KernelError


def _manifest(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():
            raise KernelError('Snapshots do not follow symlinks')
        if path.is_file() and path.name not in ('.writer.lock', '.lock'):
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def inventory(root):
    kernel = Kernel(Path(root))
    with kernel._lock():
        records = kernel._load()
        scopes = Counter(s for r in records.values() for s in r['metadata']['scopes'])
        schemas = Counter(r['metadata']['schema'] for r in records.values())
    return {'schema': 'ekk.ownership-inventory/1', 'records': len(records),
            'schemas': dict(schemas), 'scopes': [{'scope': s, 'records': n,
            'owner': None, 'classification': 'unresolved'} for s, n in sorted(scopes.items())],
            'note': 'Counts can overlap. Scope, audience, author and path do not establish ownership.'}


def snapshot(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(root):
        raise KernelError('Snapshot requires a new destination outside source')
    kernel = Kernel(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.ekk-snapshot-', dir=destination.parent))
    try:
        with kernel._lock():
            kernel._load()
            before = _manifest(root)
            shutil.copytree(root, staging / 'base', symlinks=True)
            if _manifest(root) != before or _manifest(staging / 'base') != before:
                raise KernelError('Source changed during snapshot')
        receipt = {'schema': 'ekk.snapshot/1', 'reader': kernel.version,
                   'files': before, 'ownership': 'unresolved', 'public': False}
        (staging / 'manifest.json').write_text(json.dumps(receipt, sort_keys=True, indent=2))
        os.rename(staging, destination)
        return {'status': 'snapshotted', 'path': str(destination), 'files': len(before),
                'reader': kernel.version}
    finally:
        if staging.exists(): shutil.rmtree(staging)


def restore(snapshot_path, destination):
    source, destination = Path(snapshot_path), Path(destination).resolve()
    if destination.exists():
        raise KernelError('Restore never overwrites an existing destination')
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest.get('schema') != 'ekk.snapshot/1' or _manifest(source / 'base') != manifest['files']:
        raise KernelError('Snapshot integrity mismatch')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.ekk-restore-', dir=destination.parent))
    try:
        shutil.copytree(source / 'base', staging / 'base', symlinks=True)
        if _manifest(staging / 'base') != manifest['files']:
            raise KernelError('Restored bytes differ')
        check = Kernel(staging / 'base').check()
        os.rename(staging / 'base', destination)
        return {'status': 'restored', 'path': str(destination), 'check': check}
    finally:
        shutil.rmtree(staging)
