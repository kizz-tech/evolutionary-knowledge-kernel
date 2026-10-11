"""Host-owned observation boundary shared by CLI, capture and private gateways."""
from __future__ import annotations
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib

from .host_identity import load_registry, resolve
from .local_profile import data_home, trusted_principal
from .operation_journal import OperationJournal, TrustedCallerProfile

_ACTIVE = ContextVar('ekk_operation_diagnostic', default=None)
_WARNING = 'Operation diagnostics are incomplete; the returned application result remains authoritative.'


def trusted_caller(profile_id=None):
    """Resolve host registration, never a role, request label or authentication.

    The same resolution as the observer and the CLI (host_identity), strict: a
    registry that cannot be read raises, and the observation boundary reports it.
    """
    if profile_id is not None:
        registry = load_registry()
        return TrustedCallerProfile(profile_id) if registry is not None and profile_id in registry.adapters else None
    caller = resolve(strict=True).caller
    return TrustedCallerProfile(caller) if caller else None


def declared_caller(caller):
    """The caller a host declares, as the journal attributes it: a registered adapter,
    environment or Codex fleet key, else None. Never inferred from the environment;
    a registry that cannot be read raises, as for trusted_caller.
    """
    registry = load_registry()
    return TrustedCallerProfile(caller) if registry is not None and registry.registered(caller) else None


def journal():
    return OperationJournal(data_home().expanduser().resolve() / 'operations')


def legacy_failure(error_code, failure_stage):
    """(error code, stage) as the legacy journal ``ekk.operation-attempt/0.1`` records them.

    Its readers in 0.10.0 and in the gateway's 0.8.0 count an unknown code as damage,
    so a request error stays ``invalid_format``, told apart by the stage ``request``,
    until journal v2 records ``invalid_request`` itself.
    """
    return ('invalid_format', 'request') if error_code == 'invalid_request' else (error_code, failure_stage)


@dataclass
class Observation:
    journal: object = None
    attempt: object = None
    warnings: list = field(default_factory=list)
    mutated: bool = False
    replayed: bool = False
    final_snapshot: str | None = None
    failure_stage: str = 'unknown'
    realm_id: str | None = None
    principal: str | None = None
    key_digest: str | None = None
    caller: object = None
    operation: str | None = None

    def safe(self, callback):
        try:
            return callback()
        except Exception:
            if _WARNING not in self.warnings:
                self.warnings.append(_WARNING)
            return None


def note_snapshots(**values):
    active = _ACTIVE.get()
    if active and active.attempt:
        active.safe(lambda: active.journal.annotate(active.attempt, **values))


def note_stage(stage):
    from .operation_journal import FAILURE_STAGES
    active = _ACTIVE.get()
    if active and stage in FAILURE_STAGES:
        active.failure_stage = stage


def note_publication(receipt, *, replayed):
    active = _ACTIVE.get()
    if active:
        active.mutated |= not replayed
        active.replayed = replayed and not active.mutated
        active.final_snapshot = receipt.get('revision')
        note_snapshots(attempted_base=receipt.get('base'), final_snapshot=receipt.get('revision'))


def note_retry():
    active = _ACTIVE.get()
    if active and active.attempt:
        active.safe(lambda: active.journal.finish(active.attempt, result='conflict', failure_stage='store', error_code='stale_snapshot'))
        active.attempt = active.safe(lambda: active.journal.retry(active.attempt))


def observe_recovery(callback, receipt):
    """A different pending request is a separate recovery, not this caller's write."""
    active = _ACTIVE.get()
    if (active is None or active.operation == 'recover'
            or active.key_digest == receipt.get('idempotency_key_digest')):
        return callback()
    def recover():
        note_stage('store')
        return callback()
    return observed_call('recover', recover, realm_id=active.realm_id,
        principal=active.principal, caller=active.caller, infer_caller=False,
        key='recovery:' + receipt['idempotency_key_digest'], independent=True)


def observed_call(operation, callback, *, realm_id=None, principal=None, key=None,
                  caller=None, infer_caller=True, independent=False):
    """Call once. Metadata failure neither suppresses nor retries domain work."""
    if _ACTIVE.get() is not None and not independent:
        return callback()
    observation_key = 'initialize' if operation == 'init' else key
    active = Observation(realm_id=realm_id, principal=principal or trusted_principal(),
        operation=operation, key_digest=hashlib.sha256(observation_key.encode()).hexdigest()
        if isinstance(observation_key, str) else None)
    token = _ACTIVE.set(active)
    try:
        def begin():
            selected = trusted_caller() if caller is None and infer_caller else caller
            active.caller = selected
            active.journal = journal()
            return active.journal.begin(operation, realm_id=realm_id,
                principal=principal or trusted_principal(), idempotency_key=key, caller=selected)
        active.attempt = active.safe(begin)
        try:
            result = callback()
        except BaseException as exc:
            from ..model import Conflict
            from .command_line import error_code
            status = 'cancelled' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'conflict' if isinstance(exc, Conflict) else 'error'
            code, stage = legacy_failure('cancelled' if status == 'cancelled' else error_code(exc), active.failure_stage)
            if active.attempt:
                active.safe(lambda: active.journal.finish(active.attempt, result=status,
                    failure_stage=stage,
                    mutated=active.mutated, replayed=active.replayed,
                    error_code=code,
                    final_snapshot=active.final_snapshot))
            # A safe annotation allows the CLI to report incomplete diagnostics.
            if active.warnings:
                try: exc.diagnostic_warnings = active.warnings
                except AttributeError: pass
            try: exc.operation_observed = True
            except AttributeError: pass
            raise
        from .command_line import _failed
        data = result.get('data', result) if isinstance(result, dict) else {}
        pending = isinstance(data, dict) and data.get('retention', {}).get('state') == 'published_verification_pending'
        status = 'error' if pending else 'unbound' if isinstance(result, dict) and result.get('status') == 'unbound' else 'blocked' if _failed(result) or isinstance(result, dict) and result.get('status') == 'blocked' else 'completed'
        code, stage = legacy_failure(data['retention'].get('error_code', 'source_unavailable'), 'response') if pending else (None, None)
        if active.attempt:
            active.safe(lambda: active.journal.finish(active.attempt, result=status,
                mutated=active.mutated, replayed=active.replayed,
                failure_stage=stage, error_code=code,
                final_snapshot=active.final_snapshot))
        if isinstance(result, dict) and active.warnings:
            result.setdefault('warnings', []).extend(active.warnings)
        return result
    finally:
        _ACTIVE.reset(token)
