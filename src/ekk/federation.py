"""Local, explicit federation; receipts are private transport state, never public exports.

Sessions must be supplied by a trusted adapter. This module cannot protect stores
or receipts from their filesystem administrator. Derivation review is an explicit
source-owner decision about exact bytes, not an automatic sanitization claim.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from .realms import RecordRef, PermissionDenied, Conflict


class TransferError(ValueError):
    pass


def digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _instant(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise TransferError("timezone required")
    return result.astimezone(timezone.utc)


class Federation:
    """Single-host transport with retryable receipts and no projection body cache.

    Keep ``state_dir`` private to the trusted transfer coordinator. Receipts carry
    source identity and review material; only returned target records are exports.
    Target imports require accept, contribute and read (for interrupted recovery).
    A transport can replace this class while retaining the four operation meanings.
    """

    def __init__(self, state_dir: Path, *, clock=None):
        self.path = Path(state_dir)
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @contextmanager
    def _lock(self):
        with (self.path / ".lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _file(self, operation_id):
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise TransferError("operation ID required")
        return self.path / (digest(operation_id) + ".json")

    def _save(self, receipt):
        fd, temporary = tempfile.mkstemp(dir=self.path)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(receipt, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._file(receipt["operation_id"]))
            # Persist the directory entry as well as file contents: replay must
            # retain the prepared target ID across a host power interruption.
            directory = os.open(self.path, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load(self, operation_id):
        try:
            return json.loads(self._file(operation_id).read_text())
        except FileNotFoundError:
            raise TransferError("unknown transfer") from None

    def receipt(self, operation_id):
        """Administrative private audit, not an end-user/public provenance API."""
        with self._lock():
            return self._load(operation_id)

    def _now(self):
        return _instant(self.clock())

    def _check_sessions(self, receipt, source, target):
        # Do not disclose whether an unavailable object exists or why it is denied.
        if source is None or target is None:
            raise PermissionDenied("transfer unavailable")
        if (source.store.realm_id != receipt["source_realm"]
                or target.store.realm_id != receipt["target_realm"]
                or source.principal != receipt["source_principal"]
                or target.principal != receipt["target_principal"]):
            raise PermissionDenied("transfer unavailable")
        if receipt["expires_at"] and self._now() >= _instant(receipt["expires_at"]):
            raise PermissionDenied("transfer unavailable")

    def _authorize(self, receipt, source, target):
        try:
            return self._authorize_live(receipt, source, target)
        except OSError:
            raise PermissionDenied("transfer unavailable") from None

    def _authorize_live(self, receipt, source, target):
        self._check_sessions(receipt, source, target)
        ref = RecordRef.from_dict(receipt["source_ref"])
        action = {"reference": "reference", "projection": "reference",
                  "import": "copy", "derive": "disclose"}[receipt["operation"]]
        decisions = [source.authorize_transfer(action, ref=ref,
                                                target_realm=receipt["target_realm"],
                                                target_audience=receipt["audience"])]
        if receipt["operation"] != "reference":
            decisions.append(source.authorize("read", ref=ref))
        if receipt["operation"] == "import":
            original = source.view(purpose=receipt["purpose"]).get(ref)
            # Selectors are realm-local, not an ordering of confidentiality.
            # Any relabeling therefore needs an explicit disclosure decision.
            if original["audience"] != receipt["audience"]:
                decisions.append(source.authorize_transfer("disclose", ref=ref,
                                                           target_realm=receipt["target_realm"],
                                                           target_audience=receipt["audience"]))
        decisions.append(target.authorize("accept", scopes=receipt["scopes"],
                                           audience=receipt["audience"]))
        return decisions

    @staticmethod
    def _result(receipt):
        # No private source lineage in derivation/public results.
        result = {"operation_id": receipt["operation_id"],
                  "operation": receipt["operation"], "state": receipt["state"]}
        if receipt.get("result_ref"):
            result["ref"] = receipt["result_ref"]
        if receipt["operation"] in ("reference", "projection"):
            result["ref"] = receipt["source_ref"]
        return result

    def prepare(self, operation_id, operation, source, target, ref, *, scopes=(),
                audience="private", purpose="", expires_at=None, body=None,
                approved_digest=None):
        """Review and stage, never publish externally or adopt an imported rule.

        For derive, ``approved_digest`` attests explicit review by the supplied
        source discloser of ``body`` for this destination/audience. This API is a
        trusted review adapter, not an untrusted request deserializer. Omit it or
        change reviewed bytes and preparation fails closed.
        """
        if operation not in {"reference", "projection", "import", "derive"}:
            raise TransferError("unsupported transfer operation")
        if ref.realm_id != source.store.realm_id:
            raise TransferError("source realm mismatch")
        if source.store.realm_id == target.store.realm_id:
            raise TransferError("federation requires distinct realms")
        if operation == "projection" and expires_at is None:
            raise TransferError("projection expiry required")
        if operation == "derive":
            if not isinstance(body, str) or not approved_digest or digest(body) != approved_digest:
                raise TransferError("exact reviewed derivation digest required")
        elif body is not None or approved_digest is not None:
            raise TransferError("only derivation accepts reviewed replacement bytes")
        spec = {"operation_id": operation_id, "operation": operation,
                "source_realm": source.store.realm_id, "target_realm": target.store.realm_id,
                "source_principal": source.principal, "target_principal": target.principal,
                "source_ref": ref.to_dict(), "scopes": sorted(set(scopes)),
                "audience": audience, "purpose": purpose,
                "expires_at": _instant(expires_at).isoformat() if expires_at else None,
                "body": body, "approved_digest": approved_digest}
        with self._lock():
            decisions = self._authorize(spec, source, target)
            if self._file(operation_id).exists():
                old = self._load(operation_id)
                if any(old[key] != value for key, value in spec.items()):
                    raise TransferError("operation ID already binds different content")
                return self._result(old)
            receipt = {**spec, "state": "prepared", "prepared_at": self._now().isoformat(),
                       "decisions": decisions, "result_ref": None,
                       "target_record_id": "transfer-" + uuid.uuid4().hex}
            self._save(receipt)
            return self._result(receipt)

    def accept(self, operation_id, source, target, *, prepared_body=None):
        """Recheck current rights and reviewed bytes; retry a local interrupted write."""
        with self._lock():
            receipt = self._load(operation_id)
            try:
                decisions = self._authorize(receipt, source, target)
                operation = receipt["operation"]
                if operation == "derive":
                    body = receipt["body"] if prepared_body is None else prepared_body
                    if digest(body) != receipt["approved_digest"]:
                        raise TransferError("reviewed derivation changed")
                elif prepared_body is not None:
                    raise TransferError("replacement bytes require a reviewed derivation")
                if receipt["state"] == "accepted":
                    return self._result(receipt)
                if operation in {"import", "derive"}:
                    ref = RecordRef.from_dict(receipt["source_ref"])
                    original = source.view(purpose=receipt["purpose"]).get(ref)
                    if operation == "import":
                        body = original["body"]
                    record_id = receipt["target_record_id"]
                    relations = ([{"predicate": "derived_from", "target": ref.to_dict()}]
                                 if operation == "import" else [])
                    kind = "import" if operation == "import" else "derivation"
                    try:
                        result = target.contribute(body, scopes=receipt["scopes"],
                                                   audience=receipt["audience"], record_id=record_id,
                                                   kind=kind, relations=relations)
                    except Conflict:
                        # A crash may occur after the atomic target write and before
                        # the private receipt is durable. The prepared random ID is
                        # stable across retries and was never exposed before writing.
                        result = target.lookup(record_id)
                        if not target.verify_contribution(result, body=body,
                                                          scopes=receipt["scopes"],
                                                          audience=receipt["audience"],
                                                          kind=kind, relations=relations):
                            raise TransferError("target identity conflicts with prepared transfer")
                    receipt["result_ref"] = result.to_dict()
                receipt.update(state="accepted", accepted_at=self._now().isoformat(),
                               decisions=decisions)
                receipt.pop("error", None)
                self._save(receipt)
                return self._result(receipt)
            except (PermissionDenied, TransferError, OSError, ValueError) as error:
                # Never persist a sensitive exception string from a lower layer.
                if receipt["state"] != "accepted":
                    receipt.update(state="failed", error="transfer unavailable")
                    self._save(receipt)
                if isinstance(error, OSError):
                    raise PermissionDenied("transfer unavailable") from None
                raise

    def resolve(self, operation_id, source, target, *, known_at=None, valid_at=None):
        """Fresh reference/projection resolution. Historical dates never select old ACLs."""
        with self._lock():
            receipt = self._load(operation_id)
            if receipt["state"] != "accepted":
                raise TransferError("transfer has not been accepted")
            self._authorize(receipt, source, target)
            if receipt["operation"] == "reference":
                return {"ref": receipt["source_ref"]}
            if receipt["operation"] != "projection":
                raise TransferError("only live references and projections resolve")
            ref = RecordRef.from_dict(receipt["source_ref"])
            try:
                return source.view(purpose=receipt["purpose"], known_at=known_at,
                                   valid_at=valid_at).get(ref)
            except OSError:
                raise PermissionDenied("transfer unavailable") from None

    def reconsider(self, operation_id, source, target):
        """Report lost source permission for an already accepted local derivative.

        This is a review candidate, not a delete/adopt instruction. An authorized
        import remains a local copy; source revocation cannot recall earlier bytes.
        Only an actor currently able to read the target receives its locator.
        """
        with self._lock():
            receipt = self._load(operation_id)
            if (receipt["state"] != "accepted"
                    or receipt["operation"] not in {"import", "derive"}):
                raise TransferError("accepted local derivative required")
            if (target is None or target.store.realm_id != receipt["target_realm"]
                    or target.principal != receipt["target_principal"]):
                raise PermissionDenied("transfer unavailable")
            local_ref = RecordRef.from_dict(receipt["result_ref"])
            target.authorize("read", ref=local_ref)
            try:
                self._authorize(receipt, source, target)
                reason = None
            except (PermissionDenied, OSError):
                reason = "source_or_transfer_permission_unavailable"
            receipt["reconsideration"] = {"checked_at": self._now().isoformat(),
                                          "reason": reason}
            self._save(receipt)
            return {"ref": local_ref.to_dict(), "reconsider": reason is not None,
                    "reason": reason}
