"""Bounded, private operation diagnostics; never knowledge or execution authority.

The host supplies a runtime directory outside code/realms and constructs
``TrustedCallerProfile`` only after checking its own registration. Python types
are a trusted-local boundary, not isolation from another process with this UID.
No request dictionaries, exception text, paths, titles or raw keys are recorded.

``begin(operation, *, realm_id=None, principal=None, idempotency_key=None,
        caller=None, attempted_base=None, current_snapshot=None) -> Attempt``
``retry(parent) -> Attempt`` creates a child, retaining its logical identity.
``annotate(attempt, *, attempted_base=None, current_snapshot=None,
           final_snapshot=None)`` hashes non-None snapshot annotations.
``finish(attempt, *, result, replayed=False, mutated=False, failure_stage=None,
         error_code=None, duration_ms=None, attempted_base=None, current_snapshot=None,
         final_snapshot=None) -> dict`` durably closes an attempt.
``report(*, since=None, until=None) -> dict`` returns aggregates, never rows.

Results are completed/error/conflict/blocked/cancelled/unbound. A mutation means
an independently confirmed publication, even if a later step failed; False is
absence of that confirmation. A replay cannot also be a new mutation. Diagnostics
errors must not replace a confirmed domain receipt or cause its blind retry.
Runtime version comes only from the installed package; older rows without it
remain unknown. Error codes use a fixed vocabulary, never exception messages.

The journal is an atomically replaced JSONL snapshot under an advisory flock.
One fixed pending file bounds interrupted writes; uncertain bytes are preserved
and block further writes. Each pending attempt reserves its maximum final size.
Completed attempts alone are pruned, by completion age then oldest completion.
At most half max_bytes is used by the snapshot; the other half reserves atomic
replacement. Unfinished attempts are never expired: capacity rejects new starts.
This is local diagnostic evidence, not proof against the filesystem owner.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .file_lock import LockBusy, acquire_lock


OPERATIONS = frozenset({
    'init', 'enter', 'doctor', 'context', 'contexts', 'search', 'fetch',
    'read-source', 'resolve-historical', 'capture', 'propose', 'apply', 'accept', 'review',
    'assurance', 'assess', 'export', 'recover', 'retain', 'diagnostics', 'backup', 'restore',
    'method.propose', 'method.evaluate', 'method.admit', 'method.use',
    'method.reconsider', 'method.quarantine', 'method.retire',
    'method.export', 'method.receive', 'method.inspect',
    'work.find','work.show','work.start','work.update','work.event','improve.record',
    'queue.submit','queue.status','queue.retry','queue.drain','queue.backup','queue.restore',
    'task.create','task.list','task.show','task.update','task.wait','task.register-wait',
    'task.external-attempt','task.external-outcome',
    'source.add','source.remove','source.list','source.search','source.fetch',
    'guide.list','guide.show','guide.package',
})
RESULTS = frozenset({'completed', 'error', 'conflict', 'blocked', 'cancelled', 'unbound'})
FAILURE_STAGES = frozenset({'request', 'routing', 'store', 'execution', 'response', 'unknown'})
ERROR_CODES = frozenset({
    'access_denied', 'recovery_required', 'stale_snapshot', 'source_unavailable',
    'unsupported_capability', 'unresolved_binding', 'invalid_format', 'cancelled',
    'internal_error', 'dirty_working_tree', 'idempotency_conflict', 'lock_busy',
})
MAX_RECORD_BYTES = 2048
CONTROL_RESERVE_BYTES = 2048
MAX_JOURNAL_BYTES = 64 * 1024 * 1024
MAX_IDENTITY_BYTES = 4096
MAX_COUNTER = 2**63 - 1
MAX_DURATION_MS = 10**15
_PROFILE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z')
_OPERATION = re.compile(r'[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z', re.ASCII)
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_VERSION = re.compile(
    r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
    r'(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z'
)
_RECORD_KEYS = frozenset({
    'schema', 'attempt_id', 'logical_id', 'parent_attempt_id', 'operation',
    'realm_digest', 'principal_digest', 'keyed', 'caller_profile',
    'caller_provenance', 'started_at', 'finished_at', 'duration_ms',
    'result', 'replayed', 'mutated', 'failure_stage', 'attempted_base',
    'current_snapshot', 'final_snapshot', 'clock_regressed',
})
_OPTIONAL_RECORD_KEYS = frozenset({'runtime_version', 'error_code'})
_RETENTION_KEYS = frozenset({
    'pruned_age', 'pruned_capacity', 'pruned_started_min', 'pruned_started_max',
    'pruned_finished_min', 'pruned_finished_max', 'refused_attempts',
    'refused_first_at', 'refused_last_at', 'counter_saturated',
})


class OperationJournalError(ValueError):
    """Safe diagnostic error: callers retain the owning operation's outcome."""


class JournalCapacityError(OperationJournalError):
    """Unfinished attempts leave no bounded space for another attempt."""


class JournalCorruptError(OperationJournalError):
    """Incomplete diagnostic bytes were preserved; do not invent an outcome."""


@dataclass(frozen=True)
class TrustedCallerProfile:
    """Vetted host-registry ID, constructed by the adapter, never from JSON.

    This checks shape only. The host must verify membership/provenance before
    construction. Neither a registered label nor this object grants rights.
    """
    profile: str

    def __post_init__(self):
        if not isinstance(self.profile, str) or not _PROFILE.fullmatch(self.profile) or self.profile == 'unknown':
            raise OperationJournalError('Caller must be a bounded registered profile identifier')


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    logical_id: str
    _directory: str = field(repr=False, compare=False)
    _monotonic: float = field(repr=False, compare=False)
    _pid: int = field(repr=False, compare=False)


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperationJournalError('A timezone-aware timestamp is required')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _time(value):
    if not isinstance(value, str) or len(value) != 27 or not value.endswith('Z'):
        raise OperationJournalError('Invalid journal timestamp')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise OperationJournalError('Invalid journal timestamp') from None
    if _timestamp(result) != value:
        raise OperationJournalError('Invalid journal timestamp')
    return result


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii') + b'\n'


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate metadata field')
        result[key] = value
    return result


def _parse(raw):
    def invalid_constant(_):
        raise ValueError('Nonstandard metadata number')
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=invalid_constant)


def _identity(value, kind):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_IDENTITY_BYTES:
        raise OperationJournalError('Identity metadata must be a bounded nonempty string')
    try:
        raw = value.encode('utf-8')
    except UnicodeError:
        raise OperationJournalError('Identity metadata must be valid Unicode') from None
    if len(raw) > MAX_IDENTITY_BYTES:
        raise OperationJournalError('Identity metadata is too large')
    return hashlib.sha256(kind.encode('ascii') + b'\0' + raw).hexdigest()


def _uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return str(parsed) == value and parsed.version == 4


def _counter(value):
    return type(value) is int and 0 <= value <= MAX_COUNTER


def _duration(value):
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= MAX_DURATION_MS


def _version(value):
    if not isinstance(value, str) or len(value) > 64 or _VERSION.fullmatch(value) is None:
        return False
    prerelease = value.partition('+')[0].partition('-')[2]
    return all(not (part.isdigit() and len(part) > 1 and part[0] == '0')
               for part in prerelease.split('.'))


def _runtime_version():
    import ekk
    version = getattr(ekk, '__version__', None)
    if not _version(version):
        raise OperationJournalError('Installed runtime version must be a bounded semantic version')
    return version


class OperationJournal:
    def __init__(self, directory, *, retention_days=30, max_entries=10000,
                 max_bytes=16 * 1024 * 1024, forbidden_roots=(), clock=None):
        if type(retention_days) is not int or not 1 <= retention_days <= 3650:
            raise OperationJournalError('Retention days must be between 1 and 3650')
        if type(max_entries) is not int or not 1 <= max_entries <= 100000:
            raise OperationJournalError('Entry limit must be between 1 and 100000')
        if type(max_bytes) is not int or not 8192 <= max_bytes <= MAX_JOURNAL_BYTES:
            raise OperationJournalError('Byte limit must be between 8192 and 67108864')
        candidate = Path(directory).expanduser().absolute()
        if candidate.is_symlink():
            raise OperationJournalError('Journal directory must not be a symlink')
        self.directory = candidate.resolve()
        source_root = Path(__file__).resolve().parents[3]
        forbidden = [source_root, *(Path(p).expanduser().resolve() for p in forbidden_roots)]
        if any(self.directory == p or p in self.directory.parents for p in forbidden):
            raise OperationJournalError('Operation diagnostics must be outside code and realms')
        if any((p / '.git').exists() or (p / '.ekk/realm.yaml').exists()
               for p in (self.directory, *self.directory.parents)):
            raise OperationJournalError('Operation diagnostics must be outside code and realms')
        self.retention_days = retention_days
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._snapshot_limit = max_bytes // 2
        self._clock = clock or _now
        self.path = self.directory / 'operations.jsonl'
        self._pending = self.directory / '.operations.pending'

    @contextmanager
    def _locked(self):
        descriptor = None
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self.directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise OperationJournalError('Journal requires a private owned directory')
            os.chmod(self.directory, 0o700)
            descriptor = os.open(self.directory / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise OperationJournalError('Journal lock must be a private owned file')
            os.fchmod(descriptor, 0o600)
            acquire_lock(descriptor, kind='diagnostics')
            yield
        except LockBusy:
            raise OperationJournalError('Operation journal is busy; diagnostic outcome may be incomplete') from None
        except OSError:
            raise OperationJournalError('Operation journal IO failed; diagnostic outcome may be incomplete') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _new_header(now):
        return {
            'schema': 'ekk.operation-journal/0.1', 'created_at': _timestamp(now),
            'entries': 0, 'records_sha256': hashlib.sha256(b'').hexdigest(),
            'retention': {
                'pruned_age': 0, 'pruned_capacity': 0,
                'pruned_started_min': None, 'pruned_started_max': None,
                'pruned_finished_min': None, 'pruned_finished_max': None,
                'refused_attempts': 0, 'refused_first_at': None,
                'refused_last_at': None, 'counter_saturated': False,
            },
        }

    @staticmethod
    def _validate_header(row):
        if not isinstance(row, dict) or set(row) != {'schema', 'created_at', 'entries', 'records_sha256', 'retention'}:
            raise ValueError('Invalid header fields')
        if row['schema'] != 'ekk.operation-journal/0.1' or not _counter(row['entries']):
            raise ValueError('Invalid header schema')
        _time(row['created_at'])
        if not isinstance(row['records_sha256'], str) or not _DIGEST.fullmatch(row['records_sha256']):
            raise ValueError('Invalid header digest')
        retention = row['retention']
        if not isinstance(retention, dict) or set(retention) != _RETENTION_KEYS:
            raise ValueError('Invalid retention fields')
        for key in ('pruned_age', 'pruned_capacity', 'refused_attempts'):
            if not _counter(retention[key]):
                raise ValueError('Invalid retention count')
        if type(retention['counter_saturated']) is not bool:
            raise ValueError('Invalid retention saturation')
        for prefix in ('pruned_started', 'pruned_finished', 'refused'):
            low, high = (prefix + '_first_at', prefix + '_last_at') if prefix == 'refused' else (prefix + '_min', prefix + '_max')
            if (retention[low] is None) != (retention[high] is None):
                raise ValueError('Invalid retention range')
            if retention[low] is not None and _time(retention[low]) > _time(retention[high]):
                raise ValueError('Invalid retention range')
        return row

    @staticmethod
    def _validate_record(row):
        if not isinstance(row, dict) or not _RECORD_KEYS <= set(row) or not set(row) <= _RECORD_KEYS | _OPTIONAL_RECORD_KEYS or row['schema'] != 'ekk.operation-attempt/0.1':
            raise ValueError('Invalid attempt fields')
        # Earlier 0.6 integration rows did not record these additive fields.
        # Unknown provenance must not be relabelled as the reading runtime.
        row = {'runtime_version': 'unknown', 'error_code': None, **row}
        if row['runtime_version'] != 'unknown' and not _version(row['runtime_version']):
            raise ValueError('Invalid runtime version')
        if row['error_code'] is not None and (not isinstance(row['error_code'], str) or row['error_code'] not in ERROR_CODES):
            raise ValueError('Invalid error code')
        if not _uuid(row['attempt_id']) or not isinstance(row['logical_id'], str) or not _DIGEST.fullmatch(row['logical_id']):
            raise ValueError('Invalid attempt identity')
        if row['parent_attempt_id'] is not None and (not _uuid(row['parent_attempt_id']) or row['parent_attempt_id'] == row['attempt_id']):
            raise ValueError('Invalid parent identity')
        # Operation names are diagnostic labels, not executable semantics. Older
        # readers must preserve labels emitted by newer runtimes sharing this
        # journal. Writers remain limited to their explicit OPERATIONS registry.
        if (not isinstance(row['operation'], str) or len(row['operation']) > 64
                or not _OPERATION.fullmatch(row['operation'])):
            raise ValueError('Invalid operation')
        for key in ('realm_digest', 'principal_digest', 'attempted_base', 'current_snapshot', 'final_snapshot'):
            if row[key] is not None and (not isinstance(row[key], str) or not _DIGEST.fullmatch(row[key])):
                raise ValueError('Invalid metadata digest')
        for key in ('keyed', 'replayed', 'mutated', 'clock_regressed'):
            if type(row[key]) is not bool:
                raise ValueError('Invalid metadata flag')
        if not isinstance(row['caller_profile'], str) or not _PROFILE.fullmatch(row['caller_profile']):
            raise ValueError('Invalid caller label')
        if row['caller_provenance'] != ('unknown' if row['caller_profile'] == 'unknown' else 'host_registry'):
            raise ValueError('Invalid caller provenance')
        _time(row['started_at'])
        if row['finished_at'] is None:
            if row['result'] is not None or row['duration_ms'] is not None or row['replayed'] or row['mutated'] or row['failure_stage'] is not None or row['error_code'] is not None or row['clock_regressed']:
                raise ValueError('Invalid pending attempt')
        else:
            if _time(row['finished_at']) < _time(row['started_at']) or not _duration(row['duration_ms']):
                raise ValueError('Invalid completion time')
            if not isinstance(row['result'], str) or row['result'] not in RESULTS:
                raise ValueError('Invalid result')
            if row['replayed'] and row['mutated']:
                raise ValueError('Replay cannot be a new mutation')
            if row['failure_stage'] is not None and (not isinstance(row['failure_stage'], str) or row['failure_stage'] not in FAILURE_STAGES):
                raise ValueError('Invalid failure stage')
            if row['result'] == 'completed' and (row['failure_stage'] is not None or row['error_code'] is not None):
                raise ValueError('Completed attempt cannot have a failure stage')
        if len(_json(row)) > MAX_RECORD_BYTES:
            raise ValueError('Oversized attempt')
        return row

    def _load(self, now):
        warnings = set()
        if self._pending.exists() or self._pending.is_symlink():
            warnings.add('interrupted_atomic_write')
        if any(p.name not in {'operations.jsonl', '.operations.pending', '.lock'} for p in self.directory.iterdir()):
            warnings.add('unexpected_journal_files')
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return self._new_header(now), [], warnings, 0, 0, True
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise OperationJournalError('Journal metadata must be a private owned file')
            os.fchmod(stream.fileno(), 0o600)
            raw = stream.read(MAX_JOURNAL_BYTES + 1)
        if len(raw) > MAX_JOURNAL_BYTES:
            return None, [], warnings | {'oversized_journal'}, 1, info.st_size, False
        lines = raw.splitlines(keepends=True)
        header = None
        damaged = 0
        try:
            if not lines or not lines[0].endswith(b'\n') or len(lines[0]) > CONTROL_RESERVE_BYTES:
                raise ValueError('Partial header')
            header = self._validate_header(_parse(lines[0]))
        except (ValueError, TypeError, OverflowError, RecursionError):
            warnings.add('damaged_header')
            damaged += 1
        records = []
        for line in lines[1:]:
            try:
                if not line.endswith(b'\n') or len(line) > MAX_RECORD_BYTES:
                    raise ValueError('Partial attempt')
                records.append(self._validate_record(_parse(line)))
            except (ValueError, TypeError, OverflowError, RecursionError):
                damaged += 1
        ids = {}
        for record in records:
            ids[record['attempt_id']] = ids.get(record['attempt_id'], 0) + 1
        duplicates = sum(n for n in ids.values() if n > 1)
        if duplicates:
            records = [r for r in records if ids[r['attempt_id']] == 1]
            damaged += duplicates
        if damaged:
            warnings.add('damaged_metadata')
        if header and (header['entries'] != len(lines) - 1 or
                       header['records_sha256'] != hashlib.sha256(b''.join(lines[1:])).hexdigest()):
            warnings.add('integrity_mismatch')
        by_id = {r['attempt_id']: r for r in records}
        for row in records:
            parent = by_id.get(row['parent_attempt_id'])
            if parent and any(parent[k] != row[k] for k in ('logical_id', 'operation', 'realm_digest', 'principal_digest', 'keyed', 'caller_profile', 'caller_provenance')):
                warnings.add('invalid_retry_link')
        return header, records, warnings, damaged, len(raw), False

    @staticmethod
    def _require_healthy(header, warnings):
        if header is None or warnings:
            raise JournalCorruptError('Operation journal metadata is incomplete; original bytes were retained')

    @staticmethod
    def _bump(retention, key):
        if retention[key] == MAX_COUNTER:
            retention['counter_saturated'] = True
        else:
            retention[key] += 1

    @staticmethod
    def _extend_range(retention, low, high, value):
        retention[low] = min(retention[low] or value, value)
        retention[high] = max(retention[high] or value, value)

    def _drop(self, header, row, reason):
        retained = header['retention']
        self._bump(retained, 'pruned_' + reason)
        for key in ('started', 'finished'):
            self._extend_range(retained, 'pruned_' + key + '_min', 'pruned_' + key + '_max', row[key + '_at'])

    @staticmethod
    def _reserved_bytes(records):
        return CONTROL_RESERVE_BYTES + sum(MAX_RECORD_BYTES if r['finished_at'] is None else len(_json(r)) for r in records)

    def _fits(self, records):
        return len(records) <= self.max_entries and self._reserved_bytes(records) <= self._snapshot_limit

    def _prune(self, header, records, now, *, protected=None):
        cutoff = _timestamp(now - timedelta(days=self.retention_days))
        kept = []
        for row in records:
            if row['attempt_id'] != protected and row['finished_at'] is not None and row['finished_at'] < cutoff:
                self._drop(header, row, 'age')
            else:
                kept.append(row)
        candidates = sorted((r for r in kept if r['finished_at'] is not None and r['attempt_id'] != protected),
                            key=lambda r: (r['finished_at'], r['started_at'], r['attempt_id']))
        for row in candidates:
            if self._fits(kept):
                break
            kept.remove(row)
            self._drop(header, row, 'capacity')
        return kept

    def _write(self, header, records):
        payload = b''.join(_json(row) for row in records)
        header['entries'] = len(records)
        header['records_sha256'] = hashlib.sha256(payload).hexdigest()
        control = _json(header)
        raw = control + payload
        if len(control) > CONTROL_RESERVE_BYTES or len(raw) > self._snapshot_limit:
            raise JournalCapacityError('Operation journal has no bounded space; unfinished attempts were retained')
        descriptor = os.open(self._pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(self._pending, self.path)
        directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _handle(self, row):
        return Attempt(row['attempt_id'], row['logical_id'], str(self.directory), time.monotonic(), os.getpid())

    def _find(self, attempt, records):
        if type(attempt) is not Attempt or attempt._directory != str(self.directory):
            raise OperationJournalError('Attempt must belong to this journal')
        for row in records:
            if row['attempt_id'] == attempt.attempt_id and row['logical_id'] == attempt.logical_id:
                return row
        raise OperationJournalError('Attempt is unavailable in retained diagnostics')

    @staticmethod
    def _snapshots(attempted_base, current_snapshot, final_snapshot):
        return {key: _identity(value, 'snapshot') for key, value in (
            ('attempted_base', attempted_base), ('current_snapshot', current_snapshot),
            ('final_snapshot', final_snapshot)) if value is not None}

    def _insert(self, header, records, row, now):
        records.append(row)
        records = self._prune(header, records, now)
        if not self._fits(records):
            records.remove(row)
            retention = header['retention']
            self._bump(retention, 'refused_attempts')
            self._extend_range(retention, 'refused_first_at', 'refused_last_at', _timestamp(now))
            self._write(header, records)
            raise JournalCapacityError('Operation journal has no bounded space; unfinished attempts were retained')
        self._write(header, records)
        return self._handle(row)

    def begin(self, operation, *, realm_id=None, principal=None, idempotency_key=None,
              caller=None, attempted_base=None, current_snapshot=None):
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise OperationJournalError('Unknown diagnostic operation symbol')
        if caller is not None and type(caller) is not TrustedCallerProfile:
            raise OperationJournalError('Caller provenance must come from the trusted registration adapter')
        realm = _identity(realm_id, 'realm')
        owner = _identity(principal, 'principal')
        key = _identity(idempotency_key, 'idempotency')
        snapshots = self._snapshots(attempted_base, current_snapshot, None)
        now = self._clock()
        row = {
            'schema': 'ekk.operation-attempt/0.1', 'attempt_id': str(uuid.uuid4()),
            'logical_id': hashlib.sha256(_json([realm, operation, owner, key if key is not None else str(uuid.uuid4())])).hexdigest(),
            'parent_attempt_id': None, 'operation': operation,
            'runtime_version': _runtime_version(), 'error_code': None,
            'realm_digest': realm, 'principal_digest': owner, 'keyed': key is not None,
            'caller_profile': caller.profile if caller else 'unknown',
            'caller_provenance': 'host_registry' if caller else 'unknown',
            'started_at': _timestamp(now), 'finished_at': None, 'duration_ms': None,
            'result': None, 'replayed': False, 'mutated': False, 'failure_stage': None,
            'attempted_base': None, 'current_snapshot': None, 'final_snapshot': None,
            'clock_regressed': False, **snapshots,
        }
        self._validate_record(row)
        with self._locked():
            header, records, warnings, _, _, _ = self._load(now)
            self._require_healthy(header, warnings)
            return self._insert(header, records, row, now)

    start = begin

    def retry(self, parent):
        now = self._clock()
        with self._locked():
            header, records, warnings, _, _, _ = self._load(now)
            self._require_healthy(header, warnings)
            previous = self._find(parent, records)
            row = {**previous, 'attempt_id': str(uuid.uuid4()), 'parent_attempt_id': parent.attempt_id,
                   'runtime_version': _runtime_version(), 'error_code': None,
                   'started_at': _timestamp(now), 'finished_at': None, 'duration_ms': None,
                   'result': None, 'replayed': False, 'mutated': False, 'failure_stage': None,
                   'final_snapshot': None, 'clock_regressed': False}
            return self._insert(header, records, row, now)

    def annotate(self, attempt, *, attempted_base=None, current_snapshot=None, final_snapshot=None):
        updates = self._snapshots(attempted_base, current_snapshot, final_snapshot)
        with self._locked():
            header, records, warnings, _, _, _ = self._load(self._clock())
            self._require_healthy(header, warnings)
            row = self._find(attempt, records)
            if row['finished_at'] is not None:
                raise OperationJournalError('Finished diagnostics cannot be annotated')
            row.update(updates)
            self._validate_record(row)
            self._write(header, records)

    def finish(self, attempt, *, result, replayed=False, mutated=False, failure_stage=None,
               error_code=None, duration_ms=None, attempted_base=None, current_snapshot=None, final_snapshot=None):
        if not isinstance(result, str) or result not in RESULTS:
            raise OperationJournalError('Unknown diagnostic result symbol')
        if type(replayed) is not bool or type(mutated) is not bool or (replayed and mutated):
            raise OperationJournalError('A replay cannot be a new mutation')
        if failure_stage is not None and (not isinstance(failure_stage, str) or failure_stage not in FAILURE_STAGES):
            raise OperationJournalError('Unknown diagnostic failure stage')
        if result == 'completed' and failure_stage is not None:
            raise OperationJournalError('Completed attempts cannot have a failure stage')
        if error_code is not None and (not isinstance(error_code, str) or error_code not in ERROR_CODES):
            raise OperationJournalError('Unknown diagnostic error code')
        if result == 'completed' and error_code is not None:
            raise OperationJournalError('Completed attempts cannot have an error code')
        if duration_ms is not None and not _duration(duration_ms):
            raise OperationJournalError('Duration must be a bounded finite nonnegative number')
        updates = self._snapshots(attempted_base, current_snapshot, final_snapshot)
        now = self._clock()
        with self._locked():
            header, records, warnings, _, _, _ = self._load(now)
            self._require_healthy(header, warnings)
            row = self._find(attempt, records)
            fields = {'result': result, 'replayed': replayed, 'mutated': mutated, 'failure_stage': failure_stage, 'error_code': error_code, **updates}
            if row['finished_at'] is not None:
                if any(row[k] != v for k, v in fields.items()) or (duration_ms is not None and row['duration_ms'] != duration_ms):
                    raise OperationJournalError('Attempt already has a different diagnostic result')
                return dict(row)
            if duration_ms is None:
                if attempt._pid != os.getpid():
                    raise OperationJournalError('Cross-process completion requires explicit duration_ms')
                duration_ms = max(0.0, (time.monotonic() - attempt._monotonic) * 1000)
            if not _duration(duration_ms):
                raise OperationJournalError('Duration must be a bounded finite nonnegative number')
            wall = _timestamp(now)
            row.update(fields)
            row.update(finished_at=max(wall, row['started_at']), duration_ms=duration_ms,
                       clock_regressed=wall < row['started_at'])
            self._validate_record(row)
            # Preserve completion order for clocks with equal timestamps. This
            # makes a retry's terminal result reconstructable without another
            # unbounded index or counter. Pending records keep their start order.
            records.remove(row)
            records.append(row)
            records = self._prune(header, records, now, protected=row['attempt_id'])
            self._write(header, records)
            return dict(row)

    @staticmethod
    def _counts(rows, until):
        finished = [r for r in rows if r['finished_at'] is not None and r['finished_at'] < until]
        requests = [r for r in rows if r['parent_attempt_id'] is None]
        durations = [r['duration_ms'] for r in finished]
        results = {value: sum(r['result'] == value for r in finished) for value in sorted(RESULTS)}
        mutations = [r for r in finished if r['mutated']]
        logical_results = {value: 0 for value in sorted(RESULTS | {'pending'})}
        groups = {}
        for index, row in enumerate(rows):
            groups.setdefault(row['logical_id'], []).append((index, row))
        for group in groups.values():
            if any(r['finished_at'] is None or r['finished_at'] >= until for _, r in group):
                logical_results['pending'] += 1
            else:
                _, latest = max(group, key=lambda item: (item[1]['finished_at'], item[0]))
                logical_results[latest['result']] += 1
        return {
            'attempts': len(rows), 'request_attempts': len(requests),
            'child_attempts': len(rows) - len(requests),
            'logical_operations': len({r['logical_id'] for r in rows}),
            'logical_results': logical_results,
            'logical_finished': len(groups) - logical_results['pending'],
            'logical_pending': logical_results['pending'],
            'logical_failed': logical_results['error'] + logical_results['conflict'],
            'repeated_request_attempts': len(requests) - len({r['logical_id'] for r in requests}),
            'finished_attempts': len(finished),
            'pending_at_window_end': len(rows) - len(finished),
            'pending_now': sum(r['finished_at'] is None for r in rows),
            'finished_after_window': sum(r['finished_at'] is not None and r['finished_at'] >= until for r in rows),
            'results': results,
            'failed_attempts': results['error'] + results['conflict'],
            'failure_stages': {value: sum(r['failure_stage'] == value for r in finished) for value in sorted(FAILURE_STAGES)},
            'error_codes': {
                **{value: sum(r['error_code'] == value for r in finished) for value in sorted(ERROR_CODES)},
                'unspecified': sum(r['result'] != 'completed' and r['error_code'] is None for r in finished),
            },
            'runtime_versions': {value: sum(r['runtime_version'] == value for r in rows)
                                 for value in sorted({r['runtime_version'] for r in rows})},
            'replayed_attempts': sum(r['replayed'] for r in finished),
            'confirmed_mutation_attempts': len(mutations),
            'logical_mutations': len({r['logical_id'] for r in mutations}),
            'duration_ms': {'count': len(durations), 'sum': sum(durations),
                            'mean': sum(durations) / len(durations) if durations else None,
                            'max': max(durations) if durations else None},
        }

    def report(self, *, since=None, until=None):
        now = self._clock()
        now_text = _timestamp(now)
        start = _timestamp(since if since is not None else now - timedelta(days=self.retention_days))
        end = _timestamp(until if until is not None else now)
        if start >= end or end > now_text:
            raise OperationJournalError('Report requires a nonempty past or present time window')
        with self._locked():
            header, records, warnings, damaged, byte_count, fresh = self._load(now)
            if header is not None and not warnings:
                original = len(records)
                records = self._prune(header, records, now)
                if fresh or len(records) != original:
                    self._write(header, records)
                    byte_count = self.path.stat().st_size
            if not self._fits(records):
                warnings.add('active_capacity_exceeded')
            if any(r['clock_regressed'] or r['started_at'] > now_text or
                   (r['finished_at'] is not None and r['finished_at'] > now_text) for r in records):
                warnings.add('clock_anomaly')
            retention = header['retention'] if header else None
            limitations = set(warnings)
            if header is None or start < header['created_at']:
                limitations.add('window_predates_journal')
            if retention:
                for prefix, label in (('pruned_started', 'pruned_start_cohort'), ('pruned_finished', 'pruned_completions')):
                    if retention[prefix + '_min'] is not None and retention[prefix + '_min'] < end and retention[prefix + '_max'] >= start:
                        limitations.add(label)
                if retention['refused_first_at'] is not None and retention['refused_first_at'] < end and retention['refused_last_at'] >= start:
                    limitations.add('refused_attempts_in_window')
                if retention['counter_saturated']:
                    limitations.add('retention_counters_saturated')
            cohort = [r for r in records if start <= r['started_at'] < end]
            completions = [r for r in records if r['finished_at'] is not None and start <= r['finished_at'] < end]
            by_operation = {value: self._counts([r for r in cohort if r['operation'] == value], end)
                            for value in sorted({r['operation'] for r in cohort})}
            by_caller = {value: self._counts([r for r in cohort if r['caller_profile'] == value], end)
                         for value in sorted({r['caller_profile'] for r in cohort})}
            by_version = {value: self._counts([r for r in cohort if r['runtime_version'] == value], end)
                          for value in sorted({r['runtime_version'] for r in cohort})}
            errors = [r for r in cohort if r['finished_at'] is not None and r['finished_at'] < end and r['result'] != 'completed']
            by_error = {value: self._counts([r for r in errors if (r['error_code'] or 'unspecified') == value], end)
                        for value in sorted({r['error_code'] or 'unspecified' for r in errors})}
            return {
                'schema': 'ekk.operation-report/0.1',
                'status': 'complete' if not limitations else 'incomplete',
                'window': {'since': start, 'until': end, 'observed_at': now_text},
                'cohort': self._counts(cohort, end),
                'completions_in_window': {**self._counts(completions, end),
                                          'started_before_window': sum(r['started_at'] < start for r in completions)},
                'by_operation': by_operation, 'by_caller_profile': by_caller,
                'by_runtime_version': by_version, 'by_error_code': by_error,
                'coverage': {
                    'complete': not limitations, 'limitations': sorted(limitations),
                    'metadata_integrity_verified': not warnings,
                    'journal_created_at': header['created_at'] if header else None,
                    'earliest_retained_start': min((r['started_at'] for r in records), default=None),
                    'latest_retained_start': max((r['started_at'] for r in records), default=None),
                    'retained_attempts': len(records), 'damaged_records': damaged,
                    'pending_attempt_count_known': not warnings,
                    'retention': dict(retention) if retention else None,
                    'retained_snapshot_bytes': byte_count,
                },
                'policy': {'retention_days': self.retention_days, 'max_entries': self.max_entries,
                           'max_bytes': self.max_bytes, 'snapshot_byte_limit': self._snapshot_limit,
                           'atomic_reserve_bytes': self.max_bytes - self._snapshot_limit,
                           'unfinished_attempts': 'preserved_capacity_rejects_new_starts'},
                'definitions': {
                    'cohort': 'Attempts started in [since, until); finished results require finished_at < until.',
                    'completions_in_window': 'All retained attempts finished in [since, until), including earlier starts.',
                    'logical_operations': 'Distinct observed logical IDs; not necessarily first-ever operations.',
                    'logical_results': 'Latest observed terminal result per logical ID in this group/window; any unfinished member is pending. Equal times use persisted completion order.',
                    'repeated_request_attempts': 'Request attempts minus distinct request logical IDs within this group/window.',
                    'finished_attempts': 'Denominator for result, replay and failure counts; pending attempts are excluded.',
                    'failed_attempts': 'error + conflict; blocked, cancelled and unbound remain separate results.',
                    'logical_mutations': 'Distinct logical IDs with confirmed publications; replays add no mutation.',
                    'duration_ms': 'Finished-attempt wall durations; child/retry durations may overlap parent durations.',
                    'caller_profile': 'Host-registered diagnostic provenance only; no authorization or OS isolation.',
                    'runtime_versions': 'Attempt counts by installed package version at start; absent historical versions remain unknown.',
                    'error_codes': 'Finished non-completed attempts only; unspecified means no normalized code was recorded.',
                    'coverage': 'Counts use structurally valid retained rows. Incomplete coverage is not evidence of success or absence.',
                },
            }
