"""Idempotent additive retention with publication lookup and exact read-back.

Only adapter-created capture/retain proposals may advance to a fresh base. Normal
apply, edits and acceptance retain their explicit compare-and-swap contract.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path

from ..model import Conflict, DirtyWorkingTree, IdempotencyConflict, RecoveryConflict
from .git_store import _atomic
from .file_lock import acquire_lock
from .local_profile import data_home


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _decoded(proposal):
    return {path: None if raw is None else base64.b64decode(raw, validate=True)
            for path, raw in proposal['changes'].items()}


def _lookup(app, proposal, key):
    base = app.store.snapshot(proposal['base'])
    return app.store.lookup(_decoded(proposal), base=proposal['base'],
                            idempotency_key=key, principal=app.principal,
                            policy_digest=_hash(base['files']['.ekk/governance.yaml']))


def _advance(app, proposal, key, expected_snapshot):
    """Absence is checked in the owning journal before changing a request base."""
    replay = _lookup(app, proposal, key)
    if replay is not None:
        return proposal, replay
    base = app.store.snapshot(proposal['base'])
    current = app.store.snapshot()
    if expected_snapshot is not None or current['revision'] == base['revision']:
        raise Conflict('Retention base is stale; explicit snapshots are not rebased')
    # Both scope authority and source ownership are validated again by apply.
    for path in ('.ekk/realm.yaml', '.ekk/governance.yaml', '.ekk/packs.lock.yaml'):
        if base['files'][path] != current['files'][path]:
            raise Conflict('Retention controls changed; no automatic rebase')
    changes = _decoded(proposal)
    if any(raw is None or path in base['files'] or path in current['files']
           for path, raw in changes.items()):
        raise Conflict('Only unpublished additions may retry on a fresh base')
    return {**proposal, 'base': current['revision']}, None


def _verify(app, scopes, proposal, receipt):
    """Preserve a confirmed publication even if later verification is unavailable."""
    try:
        verified = app.verify_retention(scopes, proposal, receipt)
        refs = verified['source_references']
        result_ref = verified['result_reference']
        target = result_ref or (refs[0] if refs else None)
        found = False
        if target:
            matches = app.search_records(scopes, query=target['id'], limit=100)
            found = target in [row['reference'] for row in matches['results']]
        return {**receipt, 'source_references': refs,
                **({'result_reference': result_ref} if result_ref else {}),
                'retention': {'state': 'read_back_and_discoverable' if found else 'read_back',
                              'read_back': True, 'discovery': 'found' if found else 'not_found',
                              'query': target['id'] if target else None,
                              'snapshot': receipt['revision'], 'accepted': False},
                **({'incomplete': True, 'warnings': ['Publication read back; discovery not confirmed.']}
                   if not found else {})}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        from .command_line import error_code
        # Do not claim failure before execution, invent a fresh key, or roll back.
        return {**receipt, 'retention': {'state': 'published_verification_pending',
                                        'read_back': False, 'discovery': 'unknown',
                                        'error_code': error_code(exc),
                                        'snapshot': receipt['revision'], 'accepted': False},
                'incomplete': True,
                'warnings': ['Publication confirmed; exact read-back is unavailable. Retry the identical request and key to verify.']}


def _once(app, *, operation, fingerprint, build, scopes, key, expected_snapshot=None):
    if not isinstance(key, str) or not key:
        raise ValueError('retention requires a nonempty idempotency key')
    snapshot, realm, policy, _ = app._query_view(scopes)
    app._authorized(policy, 'write', scopes)
    identity = {'realm_id': realm['id'], 'principal': app.principal, 'key': key}
    name = _hash(json.dumps(identity, sort_keys=True).encode())
    directory = data_home().expanduser().resolve() / 'capture-requests'
    if directory.is_symlink():
        raise PermissionError('Retention journal must not be a symlink')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError('Retention journal must be private to the OS owner')
    path = directory / (name + '.json')
    request_digest = _hash(json.dumps(fingerprint(identity), sort_keys=True).encode())
    lock_fd = os.open(directory / (name + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a+b') as lock:
        acquire_lock(lock, kind='retention_request')
        if path.is_symlink():
            raise PermissionError('Retention request must not be a symlink')
        newly_prepared = not path.exists()
        if path.exists():
            row = json.loads(path.read_text())
            if row['request_digest'] != request_digest:
                raise IdempotencyConflict('Idempotency key already bound to another retention request')
        else:
            if expected_snapshot is not None and snapshot['revision'] != expected_snapshot:
                raise Conflict('Retention snapshot is stale')
            proposal = build()
            if expected_snapshot is not None and proposal['base'] != expected_snapshot:
                raise Conflict('Retention snapshot changed during preparation')
            row = {'request_digest': request_digest, 'proposal': proposal,
                   'schema': 'ekk.capture-request/0.2', 'operation': operation,
                   'realm_id': realm['id'], 'principal': app.principal,
                   'last_confirmed_stage': 'prepared'}
            _atomic(path, json.dumps(row, sort_keys=True).encode())
        from .operation_diagnostics import note_retry, note_snapshots, note_stage
        receipt = None
        for attempt in range(3):
            proposal = row['proposal']
            note_snapshots(attempted_base=proposal['base'], current_snapshot=app.store.snapshot()['revision'])
            # Recheck current access even for a previously completed publication.
            _, _, current_policy, _ = app._query_view(scopes)
            app._authorized(current_policy, 'write', scopes)
            # A new proposal reaches the application's exact publication lookup
            # after its current authorization checks. Do not recover the whole
            # history twice before that call. Existing requests keep early replay
            # so later record changes cannot invalidate an already-published result.
            replay = None if newly_prepared and attempt == 0 else _lookup(app, proposal, key)
            if replay is not None:
                receipt = replay
                break
            try:
                note_stage('store')
                receipt = app.apply(proposal, idempotency_key=key)
                break
            except (DirtyWorkingTree, IdempotencyConflict, RecoveryConflict):
                raise
            except Conflict:
                fresh, replay = _advance(app, proposal, key, expected_snapshot)
                if replay is not None:
                    receipt = replay
                    break
                if attempt == 2:
                    raise Conflict('Retention retry limit reached; retry the identical request and key')
                # Same IDs, bytes and key; only the unpublished base changes.
                row = {**row, 'proposal': fresh}
                _atomic(path, json.dumps(row, sort_keys=True).encode())
                note_retry()
        result = _verify(app, scopes, row['proposal'], receipt)
        row['last_confirmed_stage'] = result['retention']['state']
        row['publication_revision'] = receipt['revision']
        try:
            _atomic(path, json.dumps(row, sort_keys=True).encode())
        except OSError:
            result.setdefault('warnings', []).append('Publication receipt is confirmed; retention-stage metadata could not be updated.')
        return result


def capture_once(app, data, *, title, scopes, filename, key, expected_snapshot=None):
    if not isinstance(data, bytes):
        raise ValueError('capture requires exact bytes')
    # Keep the original fingerprint byte-for-byte for existing request journals.
    def fingerprint(identity):
        value = [identity, title, scopes, filename, _hash(data)]
        return value if expected_snapshot is None else [*value, {'expected_snapshot': expected_snapshot}]
    return _once(app, operation='capture', fingerprint=fingerprint,
                 build=lambda: app.capture(data, title=title, scope=scopes, filename=filename),
                 scopes=scopes, key=key, expected_snapshot=expected_snapshot)


def retain_once(app, artifacts, *, title, body, scopes, key, expected_snapshot=None, repository_evidence=None,
                experience=None, preference=None, supersedes=None, decision=None, basis=None, aliases=None):
    """Publish one retained result once under ``key``.

    With ``decision`` the request is a decision: ``body`` is its statement, and
    the application composes the record (RealmService.decide) with the exact
    grounds ``basis`` and the ``aliases``; the queue carries the same fields.
    """
    if not isinstance(artifacts, list) or len(artifacts) > 32:
        raise ValueError('retain accepts at most 32 source artifacts')
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not isinstance(artifact.get('data'), bytes):
            raise ValueError('retained artifact requires exact bytes')
    def fingerprint(identity):
        sources = [{**{k: v for k, v in item.items() if k != 'data'}, 'sha256': _hash(item['data'])}
                   for item in artifacts]
        value = [identity, 'retain', title, body, scopes, sources, expected_snapshot]
        if repository_evidence is not None: value = [*value, repository_evidence]
        # Appended only when present, so earlier request journals keep their digests.
        extras = {name: item for name, item in (('experience', experience), ('preference', preference), ('supersedes', supersedes),
                                                ('decision', decision), ('basis', basis), ('aliases', aliases)) if item is not None}
        return [*value, extras] if extras else value
    def build():
        if decision is not None:
            return app.decide(body, title=title, scope=scopes, decision=decision, supersedes=supersedes, basis=basis,
                              aliases=aliases, artifacts=artifacts)
        if basis is not None or aliases is not None: raise ValueError('grounds and aliases belong to a decision')
        return app.retain(artifacts, title=title, body=body, scope=scopes, repository_evidence=repository_evidence,
                          experience=experience, preference=preference, supersedes=supersedes)
    from .operation_diagnostics import observed_call
    realm = app.codec.load_yaml(app.store.snapshot()['files']['.ekk/realm.yaml'])['id']
    return observed_call('retain', lambda: _once(app, operation='retain', fingerprint=fingerprint, build=build,
                 scopes=scopes, key=key, expected_snapshot=expected_snapshot),
                 realm_id=realm, principal=app.principal, key=key)
