"""Local governed stores, independent of the legacy kernel.

This is a policy-enforcing library boundary, not an OS sandbox or identity provider.
Only trusted runtime code may construct stores/sessions or access their filesystem.
Record bodies are loaded only after current policy authorization. One cooperating
writer per root; filesystem locks do not provide cross-host iCloud coordination.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable, Iterable
import uuid

import yaml


class PermissionDenied(ValueError):
    pass


class NotAvailable(PermissionDenied):
    """Same failure for a missing, foreign, stale or unauthorized reference."""


class Conflict(ValueError):
    pass


class IntegrityError(ValueError):
    pass


def revision_digest(data: bytes) -> str:
    """ekk/3 revision contract: SHA-256 of exact immutable UTF-8 Markdown bytes.

    The bytes include their YAML header, but never physical location, policy state,
    or the digest itself. There is no parse/re-serialize normalization on reads.
    Realm identity is the separate qualified-reference coordinate.
    """
    return hashlib.sha256(data).hexdigest()


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _time(value=None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(timezone.utc)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value):
        raise ValueError("Invalid identifier")
    return value


def _strings(values):
    if isinstance(values, str):
        raise ValueError("Expected a sequence, not a string")
    result = tuple(sorted(set(values)))
    if any(not isinstance(v, str) or not v for v in result):
        raise ValueError("Selectors must be nonempty strings")
    return result


@dataclass(frozen=True)
class RecordRef:
    realm_id: str
    record_id: str
    digest: str

    def __post_init__(self):
        _id(self.realm_id)
        _id(self.record_id)
        if not re.fullmatch(r"[a-f0-9]{64}", self.digest):
            raise ValueError("Invalid revision digest")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return value if isinstance(value, cls) else cls(**value)


@dataclass(frozen=True)
class Grant:
    principal: str
    actions: tuple[str, ...]
    scopes: tuple[str, ...] = ()
    audiences: tuple[str, ...] = ("private",)
    predicates: tuple[str, ...] = ("*",)
    destinations: tuple[str, ...] = ()
    disclosure_audiences: tuple[str, ...] = ()
    expires_at: str | None = None
    not_before: str | None = None

    def __post_init__(self):
        _id(self.principal)
        for field in ("actions", "scopes", "audiences", "predicates", "destinations", "disclosure_audiences"):
            object.__setattr__(self, field, _strings(getattr(self, field)))
        if self.expires_at:
            _time(self.expires_at)
        if self.not_before:
            _time(self.not_before)


@dataclass(frozen=True)
class Limits:
    """Bound serialized knowledge items (records and conflicts), not the fixed
    response envelope/receipt. Zero bytes returns no knowledge items. Item JSON
    includes all metadata and structural separators; no body is loaded on budget
    rejection. Depth bounds dependency traversal independently.
    """
    max_records: int = 100
    max_bytes: int = 256_000
    max_depth: int = 8

    def __post_init__(self):
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in asdict(self).values()):
            raise ValueError("Limits must be nonnegative integers")


def _atomic(path: Path, data: bytes):
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class RealmStore:
    """Administrative handle. Never give this handle to an untrusted client."""

    def __init__(self, path, *, clock: Callable = lambda: datetime.now(timezone.utc)):
        self.path = Path(path)
        self._clock = clock
        self._session_token = object()
        state = self._state()
        self.realm_id = _id(state["realm_id"])

    @classmethod
    def create(cls, path, realm_id, *, grants: Iterable[Grant] = (), clock=None):
        root = Path(path)
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise ValueError("Realm creation requires an empty root")
        _id(realm_id)
        policies = [asdict(g if isinstance(g, Grant) else Grant(**g)) for g in grants]
        (root / "records").mkdir()
        (root / "policies").mkdir()
        policy = {"schema": "ekk/policy/1", "realm_id": realm_id, "epoch": 1,
                  "grants": policies, "recorded_at": _time(clock() if clock else None).isoformat(),
                  "origin": "trusted-runtime-bootstrap", "previous_digest": None}
        policy_bytes = _json(policy)
        digest = hashlib.sha256(policy_bytes).hexdigest()
        _atomic(root / "policies" / (digest + ".json"), policy_bytes)
        _atomic(root / "realm.json", _json({"schema": "ekk/3", "realm_id": realm_id,
                "policy_epoch": 1, "policy_digest": digest, "policy_history": {"1": digest},
                "grants": policies, "records": {}}))
        return cls(root, **({"clock": clock} if clock else {}))

    def _state(self):
        state = json.loads((self.path / "realm.json").read_bytes())
        if state.get("schema") != "ekk/3":
            raise ValueError("Unsupported governed realm schema")
        if hasattr(self, "realm_id") and state.get("realm_id") != self.realm_id:
            raise IntegrityError("Realm identity changed")
        policy = self._policy_snapshot(state.get("policy_digest", ""))
        if (policy["realm_id"] != state["realm_id"] or policy["epoch"] != state["policy_epoch"]
                or _json(policy["grants"]) != _json(state["grants"])
                or state.get("policy_history", {}).get(str(state["policy_epoch"])) != state["policy_digest"]):
            raise IntegrityError("Current policy does not match its immutable snapshot")
        return state

    def _policy_snapshot(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise IntegrityError("Missing or invalid policy snapshot digest")
        data = (self.path / "policies" / (digest + ".json")).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise IntegrityError("Policy snapshot failed integrity verification")
        policy = json.loads(data)
        if policy.get("schema") != "ekk/policy/1":
            raise IntegrityError("Unsupported policy snapshot schema")
        return policy

    @contextmanager
    def _write(self):
        with (self.path / ".writer.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield self._state()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def session(self, principal: str):
        """Bind a principal authenticated by the caller's trusted runtime adapter."""
        return RealmSession(self, _id(principal), self._session_token)

    def _body(self, metadata):
        data = (self.path / "records" / (metadata["ref"]["digest"] + ".md")).read_bytes()
        if revision_digest(data) != metadata["ref"]["digest"]:
            raise IntegrityError("Record revision failed integrity verification")
        return data.decode("utf-8").split("\n---\n", 1)[1]

    def _append(self, state, metadata, body):
        identifier = metadata["record_id"]
        if identifier in state["records"]:
            raise Conflict("Record ID already exists")
        metadata = {**metadata, "sequence": len(state["records"]) + 1}
        data = ("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=True) + "---\n" + body).encode()
        ref = RecordRef(self.realm_id, identifier, revision_digest(data))
        metadata = {**metadata, "ref": ref.to_dict(), "body_bytes": len(body.encode()), "json_body_bytes": len(_json(body))}
        _atomic(self.path / "records" / (ref.digest + ".md"), data)
        state["records"][identifier] = metadata
        _atomic(self.path / "realm.json", _json(state))
        return ref


class RealmSession:
    def __init__(self, store, principal, token):
        if token is not store._session_token:
            raise PermissionDenied("Trusted runtime session required")
        self.store = store
        self.principal = principal

    @property
    def policy_epoch(self):
        return self.store._state()["policy_epoch"]

    def _allowed(self, state, action, scopes=(), audience="private", predicate="*", *, evaluation_at=None):
        now = _time(evaluation_at if evaluation_at is not None else self.store._clock())
        for raw in state["grants"]:
            grant = Grant(**raw)
            if grant.principal != self.principal:
                continue
            if grant.not_before and now < _time(grant.not_before):
                continue
            if grant.expires_at and now >= _time(grant.expires_at):
                continue
            if action not in grant.actions and "*" not in grant.actions:
                continue
            if audience not in grant.audiences and "*" not in grant.audiences:
                continue
            if predicate not in grant.predicates and "*" not in grant.predicates:
                continue
            # Every scope of a disclosed object must fit the same grant. An empty
            # grant selector is an explicit realm-wide grant; grants never union.
            if grant.scopes and (not scopes or not set(scopes).issubset(grant.scopes)):
                continue
            return True
        return False

    def _authorize(self, state, action, scopes=(), audience="private", predicate="*", *, evaluation_at=None):
        checked_at = _time(evaluation_at if evaluation_at is not None else self.store._clock())
        if not self._allowed(state, action, scopes, audience, predicate, evaluation_at=checked_at):
            raise PermissionDenied("Operation not authorized")
        return {"realm_id": self.store.realm_id, "principal": self.principal,
                "action": action, "policy_epoch": state["policy_epoch"],
                "policy_digest": state["policy_digest"], "scopes": list(scopes),
                "audience": audience, "predicate": predicate,
                "checked_at": checked_at.isoformat()}

    def _metadata(self, state, ref, action="read", *, evaluation_at=None):
        ref = RecordRef.from_dict(ref)
        metadata = state["records"].get(ref.record_id)
        if (ref.realm_id != self.store.realm_id or not metadata or metadata["ref"] != ref.to_dict()
                or not self._allowed(state, action, metadata["scopes"], metadata["audience"], metadata.get("predicate", "*"), evaluation_at=evaluation_at)):
            raise NotAvailable("Record not available")
        return metadata

    def authorize(self, action, ref=None, *, scopes=(), audience="private", predicate="*"):
        state = self.store._state()
        checked_at = _time(self.store._clock())
        if ref is not None:
            metadata = self._metadata(state, ref, action, evaluation_at=checked_at)
            scopes, audience, predicate = metadata["scopes"], metadata["audience"], metadata.get("predicate", "*")
        return self._authorize(state, action, scopes, audience, predicate, evaluation_at=checked_at)

    def authorize_transfer(self, action, ref, *, target_realm, target_audience):
        """Check a source action and its destination bounds in the SAME grant.

        Ordinary read/copy/disclose authority never implies audience expansion.
        Only an explicit all-actions/all-audiences owner grant can omit destination
        bounds. Transfer callers must separately gate destination acceptance.
        """
        _id(target_realm)
        state = self.store._state()
        checked_at = _time(self.store._clock())
        metadata = self._metadata(state, ref, action, evaluation_at=checked_at)
        for raw in state["grants"]:
            grant = Grant(**raw)
            owner = "*" in grant.actions and "*" in grant.audiences
            if not owner and (target_realm not in grant.destinations and "*" not in grant.destinations):
                continue
            if not owner and (target_audience not in grant.disclosure_audiences and "*" not in grant.disclosure_audiences):
                continue
            # Explicit owner bounds, when supplied, still constrain the grant.
            if grant.destinations and target_realm not in grant.destinations and "*" not in grant.destinations:
                continue
            if grant.disclosure_audiences and target_audience not in grant.disclosure_audiences and "*" not in grant.disclosure_audiences:
                continue
            bounded = {**state, "grants": [raw]}
            if self._allowed(bounded, action, metadata["scopes"], metadata["audience"], metadata.get("predicate", "*"), evaluation_at=checked_at):
                receipt = self._authorize(bounded, action, metadata["scopes"], metadata["audience"], metadata.get("predicate", "*"), evaluation_at=checked_at)
                return {**receipt, "target_realm": target_realm, "target_audience": target_audience}
        raise PermissionDenied("Transfer destination not authorized")

    def verify_contribution(self, ref, *, body, scopes, audience="private", kind="proposal", relations=()):
        """Validate an interrupted import without disclosing private foreign lineage.

        Callers need read and contribute authority. Only a boolean is returned;
        the normal view continues to redact unauthorized foreign references.
        """
        state = self.store._state()
        metadata = self._metadata(state, ref)
        self._authorize(state, "contribute", metadata["scopes"], metadata["audience"])
        return (metadata["kind"] != "adoption" and metadata["kind"] == kind
                and metadata.get("author") == self.principal
                and metadata.get("contributed_by") == self.principal
                and metadata["scopes"] == list(_strings(scopes)) and metadata["audience"] == audience
                and metadata["relations"] == self._relations(relations, governing=False)
                and self.store._body(metadata) == body)

    def replace_policy(self, grants, *, expected_epoch):
        with self.store._write() as state:
            policy_decision = self._authorize(state, "policy", audience="private")
            if expected_epoch != state["policy_epoch"]:
                raise Conflict("Stale policy epoch")
            state["grants"] = [asdict(g if isinstance(g, Grant) else Grant(**g)) for g in grants]
            state["policy_epoch"] += 1
            policy = {"schema": "ekk/policy/1", "realm_id": self.store.realm_id,
                      "epoch": state["policy_epoch"], "grants": state["grants"],
                      "recorded_at": _time(self.store._clock()).isoformat(),
                      "previous_digest": state["policy_digest"], "authority_decision": policy_decision}
            policy_bytes = _json(policy)
            digest = hashlib.sha256(policy_bytes).hexdigest()
            # Snapshot is durable before the atomic policy pointer is replaced.
            _atomic(self.store.path / "policies" / (digest + ".json"), policy_bytes)
            state["policy_digest"] = digest
            state["policy_history"][str(state["policy_epoch"])] = digest
            _atomic(self.store.path / "realm.json", _json(state))
            return state["policy_epoch"]

    def policy_evidence(self, epoch):
        """Explicit audit action; ordinary read access never reveals policy history."""
        state = self.store._state()
        self._authorize(state, "audit", audience="private")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            raise ValueError("Policy epoch must be a positive integer")
        digest = state["policy_history"].get(str(epoch))
        if digest is None:
            raise NotAvailable("Policy evidence not available")
        snapshot = self.store._policy_snapshot(digest)
        if snapshot["realm_id"] != self.store.realm_id or snapshot["epoch"] != epoch:
            raise IntegrityError("Policy history identity mismatch")
        return {**snapshot, "digest": digest}

    def view(self, *, scopes=(), purpose="", known_at=None, valid_at=None, limits=None):
        """Select ONE action context: all scopes are conjunctive dimensions.

        Never union independent project bindings here. Open identifiers cannot
        reveal whether scopes name projects, disciplines or other dimensions.
        Use compile_contexts for independent actions/bindings.
        """
        return AuthorizedView(self, scopes, purpose, known_at, valid_at, limits or Limits())

    def compile_contexts(self, contexts):
        """Compile independent action contexts without merging their applicability."""
        if isinstance(contexts, (str, dict)):
            raise ValueError("Independent contexts must be a sequence of mappings")
        results = []
        for context in contexts:
            if not isinstance(context, dict) or not context.get("scopes"):
                raise ValueError("Each independent context requires its own scopes")
            results.append(self.view(**context).compile())
        return {"contexts": results, "incomplete": any(r["incomplete"] for r in results)}

    def lookup(self, record_id):
        _id(record_id)
        state = self.store._state()
        metadata = state["records"].get(record_id)
        if not metadata:
            raise NotAvailable("Record not available")
        return RecordRef.from_dict(self._metadata(state, metadata["ref"])["ref"])

    def contribute(self, body, *, scopes, audience="private", record_id=None, kind="proposal",
                   relations=(), author=None, valid_from=None, valid_until=None):
        if (not isinstance(body, str) or not isinstance(kind, str) or not kind
                or not isinstance(audience, str) or not audience
                or (author is not None and not isinstance(author, str))):
            raise ValueError("Body, kind, audience and author must be strings")
        if kind == "adoption":
            raise ValueError("Use controlled adopt for adoption")
        scopes = _strings(scopes)
        record_id = _id(record_id or "r-" + uuid.uuid4().hex)
        relations = self._relations(relations, governing=False)
        if valid_from and valid_until and _time(valid_from) >= _time(valid_until):
            raise ValueError("Invalid validity interval")
        for value in (valid_from, valid_until):
            if value:
                _time(value)
        with self.store._write() as state:
            self._authorize(state, "contribute", scopes, audience)
            for relation in relations:
                ref = relation["target"]
                if ref["realm_id"] == self.store.realm_id:
                    self._metadata(state, ref)
            return self.store._append(state, {"schema": "ekk/3", "record_id": record_id,
                "kind": kind, "scopes": list(scopes), "audience": audience,
                "author": author or self.principal, "contributed_by": self.principal,
                "created_at": _time(self.store._clock()).isoformat(), "valid_from": valid_from,
                "valid_until": valid_until, "relations": relations}, body)

    @staticmethod
    def _relations(relations, governing):
        result = []
        for relation in relations:
            if not isinstance(relation, dict) or not isinstance(relation.get("predicate"), str):
                raise ValueError("Relation requires predicate and qualified target")
            predicate = relation["predicate"]
            scopes = _strings(relation.get("within_scopes", ()))
            if governing and predicate in ("supersedes", "excepts") and not scopes:
                raise ValueError("Scoped governing relation requires within_scopes")
            result.append({"predicate": predicate, "target": RecordRef.from_dict(relation["target"]).to_dict(),
                           "within_scopes": list(scopes)})
        return result

    def adopt(self, proposal_ref, *, predicate, affected_scopes, expected_current, relations=(), basis=""):
        scopes = _strings(affected_scopes)
        if not isinstance(predicate, str) or not predicate or not scopes or not isinstance(basis, str):
            raise ValueError("Adoption requires predicate, basis text and affected scopes")
        relations = self._relations(relations, governing=True)
        with self.store._write() as state:
            proposal = self._metadata(state, proposal_ref)
            if proposal["kind"] == "adoption":
                raise ValueError("Adopt a contribution, not an adoption receipt")
            authority_decision = self._authorize(state, "adopt", scopes, proposal["audience"], predicate)
            if not set(proposal["scopes"]).issubset(scopes):
                raise ValueError("Adoption cannot broaden proposal applicability")
            visible = self.view(scopes=scopes)._visible(state)
            current, _ = self.view(scopes=scopes)._effective(visible)
            actual = {m["ref"]["digest"] for m in visible if m["ref"]["digest"] in current
                      and any(a.get("adopted_ref") == m["ref"] and a.get("predicate") == predicate for a in visible)}
            actual_refs = {_json(m["ref"]) for m in visible if m["ref"]["digest"] in actual}
            expected = {_json(RecordRef.from_dict(r).to_dict()) for r in expected_current}
            if expected != actual_refs:
                raise Conflict("Stale expected_current")
            for relation in relations:
                target = self._metadata(state, relation["target"])
                if relation["predicate"] in ("supersedes", "excepts", "contradicts"):
                    if target["ref"]["digest"] not in actual:
                        raise Conflict("Governing relation must target a current commitment of this predicate")
                    within = relation["within_scopes"]
                    self._authorize(state, relation["predicate"], within or scopes, proposal["audience"], predicate)
                    if within and not set(scopes).issubset(within):
                        raise ValueError("Relation selector cannot broaden adoption applicability")
            decision_id = "a-" + uuid.uuid4().hex
            return self.store._append(state, {"schema": "ekk/3", "record_id": decision_id,
                "kind": "adoption", "scopes": list(scopes), "audience": proposal["audience"],
                "author": self.principal, "adopted_by": self.principal,
                "created_at": _time(self.store._clock()).isoformat(), "valid_from": None,
                "valid_until": None, "relations": relations, "predicate": predicate,
                "adopted_ref": proposal["ref"], "policy_epoch": state["policy_epoch"],
                "policy_digest": state["policy_digest"], "authority_decision": authority_decision,
                "decision_id": decision_id, "basis": basis or "direct-adoption:" + decision_id},
                "Controlled adoption; provenance and authority evidence are in the immutable header.\n")


class AuthorizedView:
    """Reauthorizes each operation. No caller-provided allowlist is accepted."""

    def __init__(self, session, scopes, purpose, known_at, valid_at, limits):
        self._session = session
        self.scopes = _strings(scopes)
        self.purpose = purpose
        self.known_at = _time(known_at) if known_at else None
        self.valid_at = _time(valid_at) if valid_at else None
        self.limits = limits

    def _visible(self, state, *, evaluation_at=None):
        now = _time(evaluation_at if evaluation_at is not None else self._session.store._clock())
        known, valid = self.known_at or now, self.valid_at or now
        result = []
        for metadata in state["records"].values():
            if not self._session._allowed(state, "read", metadata["scopes"], metadata["audience"], metadata.get("predicate", "*"), evaluation_at=now):
                continue
            if self.scopes and not set(metadata["scopes"]).issubset(self.scopes):
                continue
            if _time(metadata["created_at"]) > known:
                continue
            if metadata.get("valid_from") and valid < _time(metadata["valid_from"]):
                continue
            if metadata.get("valid_until") and valid >= _time(metadata["valid_until"]):
                continue
            result.append(metadata)
        return sorted(result, key=lambda m: (m["sequence"], m["record_id"]))

    def _effective(self, visible):
        refs = {m["ref"]["digest"] for m in visible}
        governing = set()
        conflicts = []
        for metadata in visible:
            if metadata["kind"] != "adoption" or metadata["adopted_ref"]["digest"] not in refs:
                continue
            # An unscoped administrative browse is not a union of action contexts.
            if not self.scopes or not set(metadata["scopes"]).issubset(self.scopes):
                continue
            governing.add(metadata["adopted_ref"]["digest"])
            for relation in metadata["relations"]:
                if relation["target"]["digest"] not in refs:
                    continue
                if relation["within_scopes"] and not set(relation["within_scopes"]).issubset(self.scopes):
                    continue
                if relation["predicate"] == "supersedes":
                    governing.discard(relation["target"]["digest"])
                elif relation["predicate"] in ("excepts", "contradicts"):
                    conflicts.append({"predicate": relation["predicate"], "source": metadata["adopted_ref"],
                                      "target": relation["target"], "within_scopes": relation["within_scopes"]})
        return governing, conflicts

    def _present(self, metadata, visible, governing, *, load_body=True):
        allowed = {m["ref"]["digest"] for m in visible}
        # Never pass foreign/denied locators through a relation or adoption header.
        result = {k: metadata[k] for k in ("ref", "kind", "scopes", "audience", "author", "created_at")}
        if "contributed_by" in metadata:
            result["contributed_by"] = metadata["contributed_by"]
        result["relations"] = [r for r in metadata["relations"]
                               if r["target"]["realm_id"] == self._session.store.realm_id and r["target"]["digest"] in allowed]
        if metadata.get("adopted_ref", {}).get("digest") in allowed:
            result["adopted_ref"] = metadata["adopted_ref"]
            result["predicate"] = metadata["predicate"]
            result["adopted_by"] = metadata["adopted_by"]
            result["policy_epoch"] = metadata["policy_epoch"]
            result["policy_digest"] = metadata["policy_digest"]
            result["authority_decision"] = metadata["authority_decision"]
            result["basis"] = metadata["basis"]
            result["decision_id"] = metadata["decision_id"]
        result["governing"] = metadata["ref"]["digest"] in governing
        result["body"] = self._session.store._body(metadata) if load_body else ""
        return result

    def get(self, ref):
        ref = RecordRef.from_dict(ref)
        state = self._session.store._state()
        visible = self._visible(state)
        metadata = next((m for m in visible if m["ref"] == ref.to_dict()), None)
        if not metadata:
            raise NotAvailable("Record not available")
        governing, _ = self._effective(visible)
        cost = len(_json(self._present(metadata, visible, governing, load_body=False))) + metadata["json_body_bytes"] - 2
        if self.limits.max_records < 1 or cost > self.limits.max_bytes:
            raise ValueError("Record exceeds context limits")
        return self._present(metadata, visible, governing)

    def compile(self):
        state = self._session.store._state()
        checked_at = _time(self._session.store._clock())
        visible = self._visible(state, evaluation_at=checked_at)
        governing, conflicts = self._effective(visible)
        ordered = sorted(visible, key=lambda m: (m["ref"]["digest"] not in governing, m["sequence"], m["record_id"]))
        records, used = [], 0
        for metadata in ordered:
            cost = len(_json(self._present(metadata, visible, governing, load_body=False))) + metadata["json_body_bytes"] - 2
            cost += 1 if records else 0  # JSON array separator
            if len(records) >= self.limits.max_records or used + cost > self.limits.max_bytes:
                continue
            records.append(self._present(metadata, visible, governing))
            used += cost
        included = {r["ref"]["digest"] for r in records}
        incomplete = len(records) < len(visible)
        selected_conflicts = []
        for conflict in conflicts:
            # Conflict metadata cannot bypass omitted records or the shared byte
            # budget. An omission reports incompleteness without omitted locators.
            if (conflict["source"]["digest"] not in included
                    or conflict["target"]["digest"] not in included):
                incomplete = True
                continue
            cost = len(_json(conflict)) + (1 if selected_conflicts else 0)
            if used + cost > self.limits.max_bytes:
                incomplete = True
                continue
            selected_conflicts.append(conflict)
            used += cost
        # A blocked/missing dependency gives only a generic signal, no hidden ID.
        def depth_check(metadata, depth, seen):
            nonlocal incomplete
            for relation in metadata["relations"]:
                if relation["predicate"] not in ("depends_on", "implements", "based_on"):
                    continue
                target = relation["target"]
                match = next((m for m in visible if m["ref"] == target), None)
                if match is None or target["digest"] not in included or depth >= self.limits.max_depth:
                    incomplete = True
                elif target["digest"] not in seen:
                    depth_check(match, depth + 1, seen | {target["digest"]})
        for metadata in visible:
            if metadata["ref"]["digest"] in included:
                depth_check(metadata, 0, {metadata["ref"]["digest"]})
        output = {"realm_id": self._session.store.realm_id, "scopes": list(self.scopes),
                  "records": records, "conflicts": selected_conflicts, "incomplete": incomplete,
                  "reasons": ["context_or_dependency_limit"] if incomplete else []}
        output["snapshot_hash"] = hashlib.sha256(_json(output)).hexdigest()
        output["receipt"] = {"principal": self._session.principal, "policy_epoch": state["policy_epoch"],
                             "policy_digest": state["policy_digest"], "checked_at": checked_at.isoformat(),
                             "known_at": (self.known_at or checked_at).isoformat(),
                             "valid_at": (self.valid_at or checked_at).isoformat(),
                             "purpose": self.purpose, "limits": asdict(self.limits)}
        return output

    def list(self):
        return self.compile()["records"]

    def search(self, query):
        return [r for r in self.list() if query.casefold() in r["body"].casefold()]

    def provenance(self, ref):
        return self.get(ref)["relations"]

    def export(self, ref=None):
        """Authorized local representation; this never authorizes public disclosure."""
        return self.get(ref) if ref is not None else self.compile()
