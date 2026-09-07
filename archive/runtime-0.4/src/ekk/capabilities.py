"""Explicit admission of externally owned capabilities; descriptors are inert data.

Callbacks are part of the trusted host. This module is not a sandbox, identity
provider or a loader for arbitrary executable paths supplied in knowledge.
"""
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
from typing import Callable


class CapabilityError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class BasisRef:
    realm_id: str
    record_id: str
    revision_digest: str

    def __post_init__(self):
        if not self.realm_id or not self.record_id or not _sha(self.revision_digest):
            raise CapabilityError('basis requires qualified identity and SHA-256 revision')


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


@dataclass(frozen=True)
class CapabilityManifest:
    capability_id: str
    version: str
    owner: str
    artifact_uri: str
    artifact_digest: str
    basis: tuple[BasisRef, ...]
    generator_version: str
    target_environment: str
    requested_privileges: tuple[str, ...]
    verifier: str
    rollback: str
    reconsider_when: str
    safety_control: bool = False

    def __post_init__(self):
        for name in ('capability_id', 'version', 'owner', 'artifact_uri',
                     'generator_version', 'target_environment', 'verifier',
                     'rollback', 'reconsider_when'):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise CapabilityError(f'{name} is required')
        if type(self.safety_control) is not bool:
            raise CapabilityError('safety_control must be Boolean')
        if not _sha(self.artifact_digest):
            raise CapabilityError('artifact_digest must be SHA-256')
        if not isinstance(self.basis, tuple) or not self.basis or not all(isinstance(b, BasisRef) for b in self.basis):
            raise CapabilityError('basis must be a nonempty immutable tuple of BasisRef')
        if not isinstance(self.requested_privileges, tuple) or not all(isinstance(p, str) and p for p in self.requested_privileges):
            raise CapabilityError('privileges must be an immutable tuple')

    def descriptor(self):
        return {'kind': 'capability', 'manifest': asdict(self), 'executable': False,
                'relations': [{'predicate': 'implements', 'target': asdict(b)} for b in self.basis]}


class CapabilityRuntime:
    """One host-owned activation registry, with independent trusted callbacks.

    admit(operation, manifest) checks *current* request authority. verifier gets
    the exact bytes and manifest; runner gets those same frozen bytes and a
    fixture. Neither callback is resolved from a URI or a document string.
    State is deliberately local to this runtime; restart requires re-admission.
    """
    def __init__(self, *, admit: Callable, basis_is_current: Callable,
                 verifier: Callable, runner: Callable, retirement_verifier: Callable | None = None):
        self._admit = admit
        self._basis_current = basis_is_current
        self._verifier = verifier
        self._runner = runner
        self._retirement_verifier = retirement_verifier
        self._active = {}
        self._versions = {}
        self._history = []

    @property
    def history(self):
        # Callers must not be able to alter the audit trail through returned data.
        return json.loads(json.dumps(self._history))

    def _authorize(self, operation, manifest):
        if self._admit(operation, manifest) is not True:
            raise CapabilityError(f'{operation} denied')

    def _current(self, manifest):
        return all(self._basis_current(ref) is True for ref in manifest.basis)

    def activate(self, manifest: CapabilityManifest, artifact: bytes):
        if not isinstance(artifact, bytes):
            raise CapabilityError('activation requires immutable artifact bytes')
        self._authorize('activate', manifest)
        if digest(artifact) != manifest.artifact_digest:
            raise CapabilityError('artifact digest mismatch')
        if not self._current(manifest):
            raise CapabilityError('basis changed or unavailable: reconsideration required')
        if self._verifier(artifact, manifest) is not True:
            raise CapabilityError('independent verification failed')
        # Recheck authority/basis after verification, which may take time.
        self._authorize('activate', manifest)
        if not self._current(manifest):
            raise CapabilityError('basis changed during verification')
        key = (manifest.capability_id, manifest.version)
        if key in self._versions and self._versions[key] != manifest:
            raise CapabilityError('active version is immutable; use a new version')
        self._versions[key] = manifest
        self._active[key] = (manifest, artifact)
        return self._record('activated', manifest)

    def reconsider(self):
        return [{'capability_id': m.capability_id, 'version': m.version,
                 'reason': 'basis_changed_or_unavailable', 'automatic_removal': False}
                for m, _ in self._active.values() if not self._current(m)]

    def run(self, capability_id: str, version: str, fixture):
        try:
            manifest, artifact = self._active[(capability_id, version)]
        except KeyError:
            raise CapabilityError('capability is not active') from None
        self._authorize('run', manifest)
        if not self._current(manifest):
            raise CapabilityError('basis changed or unavailable: reconsideration required')
        result = self._runner(artifact, fixture)
        self._record('executed', manifest)
        return result

    def retire(self, capability_id: str, version: str, *, reason: str,
               replacement_verified: bool = False):
        key = (capability_id, version)
        if key not in self._active:
            raise CapabilityError('capability is not active')
        manifest, _ = self._active[key]
        self._authorize('retire', manifest)
        if not reason.strip():
            raise CapabilityError('retirement reason required')
        # A supplied Boolean is not an attestation. The independent callback
        # verifies a removal candidate; the flag merely requests that workflow.
        if manifest.safety_control and (not replacement_verified or
                self._retirement_verifier is None or
                self._retirement_verifier(manifest, reason) is not True):
            raise CapabilityError('safety removal requires independent replacement verification')
        self._authorize('retire', manifest)
        del self._active[key]
        return self._record('retired', manifest, reason=reason,
                            rollback='re-activate original verified bytes with current authorization')

    def _record(self, state, manifest, **extra):
        row = {'sequence': len(self._history) + 1, 'state': state,
               'capability_id': manifest.capability_id, 'version': manifest.version,
               'artifact_digest': manifest.artifact_digest, **extra}
        self._history.append(row)
        return dict(row)


def materialize(path: Path, artifact: bytes) -> str:
    """Create an owner-selected artifact without overwriting or executing it."""
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(artifact)
    return digest(artifact)


BOUNDARY_CHECK = b'{"format":"ekk-boundary-check/1","require":["source_disclosure","target_acceptance","digest_match"]}\n'


def verify_boundary_check(artifact: bytes, manifest: CapabilityManifest) -> bool:
    return artifact == BOUNDARY_CHECK and manifest.requested_privileges == ()


def run_boundary_check(artifact: bytes, fixture: dict) -> dict:
    """A fixed harmless implementation, not eval/exec of descriptor content."""
    if artifact != BOUNDARY_CHECK:
        raise CapabilityError('unsupported boundary artifact')
    required = json.loads(artifact)['require']
    missing = [key for key in required if fixture.get(key) is not True]
    return {'passed': not missing, 'missing_checks': missing}
