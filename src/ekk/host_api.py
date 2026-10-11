"""The declared host facade, ``ekk.host-api/1``: what a host process, such as the private gateway, calls.

- No adapter object crosses it. Arguments are plain values, a Route and the
  caller's registered ID; results are ``ekk.result/0.1`` envelopes, Release
  values or None.
- The caller is declared by the host, never inferred from the process
  environment: a registered adapter, environment or Codex fleet key is
  attributed, anything else is recorded as unknown.
- The working directory is pinned to '/'. Routing is the explicit Route, so a call
  writes no observer rows and attaches no repository evidence.
- Version 1 dispatches the read operations only, plus capture and retain once;
  writes return as an additive version.
- Runtimes are compared by wheel digest only: the loaded runtime is current iff
  ``loaded_release().wheel_sha256`` and ``active_release().wheel_sha256`` are both
  non-None and equal. Never compare by version.

A change to a signature, a field or OPERATIONS bumps HOST_API. Adapters are imported
inside the functions, so importing the facade stays cheap.
"""
from __future__ import annotations
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import re
from typing import Any, TypeVar

HOST_API = 'ekk.host-api/1'
__all__ = ('HOST_API', 'OPERATIONS', 'Route', 'Release', 'dispatch', 'capture_once', 'retain_once', 'observed',
           'error_code', 'record_schema', 'active_release', 'loaded_release')
OPERATIONS = frozenset({'enter', 'context', 'contexts', 'search', 'fetch', 'read-source', 'doctor', 'review', 'assurance'})
# Routing and identity come from the Route and the declared caller, never from a request.
_ROUTING_KEYS = frozenset({'root', 'profile', 'realm', 'principal', 'scopes', 'target_scope', 'target_realm', 'workspace_id',
                           'personal', 'resume', 'payload', 'operation', 'caller', 'caller_profile'})
_BRIEF = frozenset({'enter', 'context'})
_ARTIFACT_KEYS = frozenset({'data', 'filename', 'title'})
T = TypeVar('T')


@dataclass(frozen=True)
class Route:
    """A role profile, a realm alias in it, that realm's published identity and the selected contexts in declared order."""
    profile: str
    realm: str
    realm_id: str
    scopes: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.profile, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', self.profile):
            raise ValueError('Route profile must be a role profile name')
        if not isinstance(self.realm, str) or not self.realm or not isinstance(self.realm_id, str) or not self.realm_id:
            raise ValueError('Route realm and realm_id must be nonempty text')
        if (not isinstance(self.scopes, tuple) or not self.scopes or len(set(self.scopes)) != len(self.scopes)
                or any(not isinstance(scope, str) or not scope for scope in self.scopes)):
            raise ValueError('Route scopes must be a nonempty tuple of distinct context IDs')


@dataclass(frozen=True)
class Release:
    """One runtime build as its record states it; ``record`` names that file, None when there is no usable record."""
    version: str | None
    wheel_sha256: str | None
    source_commit: str | None
    path: str | None
    record: str | None


def _resolve(route):
    """The route's store path, re-resolved on every call; a changed realm identity is refused."""
    if not isinstance(route, Route):
        raise TypeError('route must be a host_api.Route')
    from .adapters.local_profile import LocalProfile
    from .adapters.operation_diagnostics import note_stage
    note_stage('routing')
    path, manifest = LocalProfile(route.profile).resolve(route.realm)
    if manifest.get('id') != route.realm_id:
        raise PermissionError('configured realm identity changed')
    return path


def _service(route):
    from .adapters.command_line import service
    return service(_resolve(route), realm_id=route.realm_id, allowed_scopes=list(route.scopes))


def _envelope(request_id, operation, data):
    from .adapters.command_line import result_envelope
    return result_envelope({'request_id': request_id}, operation, data)


def dispatch(operation: str, request: Mapping[str, Any], *, route: Route, caller: str | None, brief: bool = False,
             request_id: str | None = None) -> dict:
    """Run one read operation on ``route`` as the CLI does, from '/', and return its envelope.

    ``brief`` is the agent view of enter and context, selected with the CLI's
    agent-view record budget unless the request names one. Navigation commands
    in a result stay as the application gives them; the CLI's rewriting with its
    own route options is display for a shell, not part of the envelope.
    """
    if operation not in OPERATIONS:
        raise ValueError(f'{HOST_API} dispatches only ' + ', '.join(sorted(OPERATIONS)))
    if not isinstance(request, Mapping):
        raise TypeError('request must be a mapping')
    refused = sorted(_ROUTING_KEYS & set(request))
    if refused:
        raise PermissionError('Routing and identity come from the route and the declared caller, not the request: ' + ', '.join(refused))
    if brief and operation not in _BRIEF:
        raise ValueError('brief is a view of enter and context only')
    key = request.get('idempotency_key') if isinstance(request.get('idempotency_key'), str) else None

    def run():
        from .adapters import command_line
        _resolve(route)
        args = command_line.parser().parse_args([operation, '--profile=' + route.profile, '--realm=' + route.realm, '--cwd=/',
                                                 *('--scope=' + scope for scope in route.scopes)])
        if brief:
            args.budget = command_line.AGENT_VIEW_RECORD_BUDGET
        # This observation is the outermost, so the CLI's own is a no-op and infers no caller.
        data = command_line.dispatch(args, {**request, 'target_realm': route.realm_id})
        if brief:
            from .adapters.context_display import brief_context
            data = brief_context(data)
        return data
    return _envelope(request_id, operation, observed(operation, run, caller=caller, realm_id=route.realm_id, key=key))


def capture_once(data: bytes, *, route: Route, caller: str | None, title: str, filename: str, key: str,
                 expected_snapshot: str | None = None) -> dict:
    """Preserve one original source once under ``key``; a retry with the same request replays its receipt."""
    def run():
        from .adapters import retention
        return retention.capture_once(_service(route), data, title=title, scopes=list(route.scopes), filename=filename,
                                      key=key, expected_snapshot=expected_snapshot)
    return _envelope(key, 'capture', observed('capture', run, caller=caller, realm_id=route.realm_id, key=key))


def retain_once(artifacts: Sequence[Mapping[str, Any]], *, route: Route, caller: str | None, title: str, body: str, key: str,
                expected_snapshot: str | None = None, repository_evidence: Mapping[str, Any] | None = None) -> dict:
    """Publish one retained result with its exact source artifacts once under ``key``.

    Each artifact is exactly ``{data, filename[, title]}`` without None values: the
    request fingerprint covers every key, so retries of keys first written by the
    gateway on 0.8 replay instead of conflicting. Decisions, preferences and
    experience are not retained through this version.
    """
    items = []
    for artifact in artifacts:
        if (not isinstance(artifact, Mapping) or not {'data', 'filename'} <= set(artifact) <= _ARTIFACT_KEYS
                or not isinstance(artifact['data'], bytes) or any(not isinstance(artifact[name], str) for name in set(artifact) - {'data'})):
            raise ValueError('An artifact is exactly {data: bytes, filename: str[, title: str]}')
        items.append(dict(artifact))

    def run():
        from .adapters import retention
        return retention.retain_once(_service(route), items, title=title, body=body, scopes=list(route.scopes), key=key,
                                     expected_snapshot=expected_snapshot,
                                     repository_evidence=None if repository_evidence is None else dict(repository_evidence))
    return _envelope(key, 'retain', observed('retain', run, caller=caller, realm_id=route.realm_id, key=key))


def observed(operation: str, callback: Callable[[], T], *, caller: str | None, realm_id: str | None = None,
             key: str | None = None) -> T:
    """Call ``callback`` once inside one operation-journal observation attributed to the declared ``caller``.

    A registry that cannot be read records the caller as unknown and adds the
    standard diagnostics warning to a dict result; it never fails the call.
    """
    from .adapters.operation_journal import OPERATIONS as JOURNALED
    if operation not in JOURNALED:
        raise ValueError('Unknown journal operation: ' + str(operation))
    from .adapters.local_profile import trusted_principal
    from .adapters.operation_diagnostics import _WARNING, declared_caller, observed_call
    profile, warning = None, None
    if caller is not None:
        try:
            profile = declared_caller(caller)
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            warning = _WARNING
    result = observed_call(operation, callback, realm_id=realm_id, principal=trusted_principal(), key=key,
                           caller=profile, infer_caller=False)
    if warning and isinstance(result, dict) and warning not in result.setdefault('warnings', []):
        result['warnings'].append(warning)
    return result


def error_code(exc: BaseException) -> str:
    """The stable error code of a refused or failed call, as the CLI reports it; the set may grow."""
    from .adapters.command_line import error_code as code
    return code(exc)


def record_schema() -> dict:
    """The JSON schema of an EKK record, from the loaded runtime's resources."""
    from .assets import schema_directory
    return json.loads((schema_directory() / 'record.schema.json').read_text(encoding='utf-8'))


def active_release() -> Release | None:
    """The release `cli/current` names now, read as a file on every call; None without the link."""
    from .adapters.runtime_release import active_release as active
    value = active()
    return None if value is None else Release(**value)


def loaded_release() -> Release:
    """The runtime this process imported; its digest is None unless it was installed from a wheel."""
    from .adapters.runtime_release import loaded_release as loaded
    return Release(**loaded())
