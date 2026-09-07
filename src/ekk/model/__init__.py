"""Pure record contracts. No storage, serialization, or execution dependencies."""
from datetime import datetime
import hashlib
import re
from uuid import uuid4

RECORD_SCHEMA = "ekk.record/0.1"
KNOWN_KINDS = frozenset(("context", "note", "source", "observation", "claim", "question", "decision", "policy", "action", "outcome"))

class ValidationError(ValueError):
    pass

class StoreError(ValueError):
    pass

class Conflict(StoreError):
    pass

class DirtyWorkingTree(Conflict):
    pass

class IdempotencyConflict(Conflict):
    pass

class RecoveryConflict(Conflict):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_id() -> str:
    return str(uuid4())


def _text(value, label, minimum=1, maximum=None):
    if not isinstance(value, str) or len(value) < minimum or (maximum is not None and len(value) > maximum):
        raise ValidationError("Invalid " + label)
    return value


def validate_identifier(value):
    return _text(value, "identifier", 3, 512)


def _revision(value):
    if type(value) is not int or value < 1:
        raise ValidationError("revision must be a positive integer")


def _timestamp(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})", value):
        raise ValidationError(label + " must be an RFC3339 timestamp")
    try:
        datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("Invalid " + label) from exc


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValidationError(label + " must be an object")
    return value


def _array(value, label, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise ValidationError(label + " must be " + ("a nonempty" if nonempty else "an") + " array")
    return value


def validate_reference(ref, *, pinned=False):
    if isinstance(ref, str):
        validate_identifier(ref)
        if pinned:
            raise ValidationError("A consequential basis must pin revision or digest")
        return ref
    _mapping(ref, "Reference")
    validate_identifier(ref.get("target", ref.get("id")))
    if "realm" in ref:
        validate_identifier(ref["realm"])
    if "digest" in ref and (not isinstance(ref["digest"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", ref["digest"])):
        raise ValidationError("Invalid reference digest")
    if "revision" in ref:
        _revision(ref["revision"])
    if "selector" in ref:
        _text(ref["selector"], "selector")
    if pinned and not (ref.get("digest") or ref.get("revision")):
        raise ValidationError("A consequential basis must pin revision or digest")
    return ref


def validate_envelope(metadata):
    """Validate the supplied 0.1 schema without I/O or serializer dependencies."""
    _mapping(metadata, "Record envelope")
    if metadata.get("schema") != RECORD_SCHEMA:
        raise ValidationError("Unsupported record schema")
    validate_identifier(metadata.get("id"))
    kind = _text(metadata.get("kind"), "kind")
    if not re.fullmatch(r"[a-z][a-z0-9_.-]*", kind):
        raise ValidationError("Invalid kind")
    _text(metadata.get("created_by"), "created_by")
    _text(metadata.get("title"), "title")
    scope = _array(metadata.get("scope"), "scope", nonempty=True)
    for item in scope:
        validate_identifier(item)
    if len(set(scope)) != len(scope):
        raise ValidationError("scope must contain unique context IDs")
    _revision(metadata.get("revision"))
    _timestamp(metadata.get("created_at"), "created_at")
    if "classification" in metadata and metadata["classification"] not in ("public", "internal", "private", "restricted"):
        raise ValidationError("Invalid classification")
    if "relations" in metadata:
        for relation in _array(metadata["relations"], "relations"):
            _mapping(relation, "relation")
            _text(relation.get("rel"), "relation rel")
            validate_identifier(relation.get("target"))
            validate_reference(relation)
    if "aliases" in metadata:
        aliases = _array(metadata["aliases"], "aliases")
        for alias in aliases:
            _text(alias, "alias")
        if len(set(aliases)) != len(aliases):
            raise ValidationError("aliases must be unique")
    if kind == "context" and "context" not in metadata:
        raise ValidationError("Context record requires context")
    if "context" in metadata:
        _text(_mapping(metadata["context"], "context").get("purpose"), "context purpose")
    if kind == "source" and "source" not in metadata:
        raise ValidationError("Source record requires source")
    if "source" in metadata:
        source = _mapping(metadata["source"], "source")
        if "assets" not in source and "uri" not in source:
            raise ValidationError("Source requires assets or uri")
        for field in ("uri", "revision"):
            if field in source:
                _text(source[field], "source " + field)
        if "assets" in source:
            for asset in _array(source["assets"], "source assets", nonempty=True):
                _mapping(asset, "source asset")
                _text(asset.get("path"), "asset path")
                if not isinstance(asset.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
                    raise ValidationError("Invalid asset sha256")
    if "review" in metadata:
        review = _mapping(metadata["review"], "review")
        if "due_at" in review:
            _timestamp(review["due_at"], "review due_at")
        if "when" in review:
            for condition in _array(review["when"], "review when"):
                _text(condition, "review condition")
        for trigger in review.get("triggers", []):
            if isinstance(trigger, str):
                continue
            trigger = _mapping(trigger, "review trigger")
            _text(trigger.get("detector"), "review detector")
            if trigger.get("detector") == "observation_gap":
                if "starts_at" in trigger:
                    _timestamp(trigger["starts_at"], "observation starts_at")
                for aspect in _array(trigger.get("aspects"), "observation aspects", nonempty=True):
                    _text(aspect, "observation aspect")
                if len(set(trigger["aspects"])) != len(trigger["aspects"]):
                    raise ValidationError("observation aspects must be unique")
                days = trigger.get("max_age_days")
                if type(days) is not int or days < 1:
                    raise ValidationError("observation max_age_days must be a positive integer")
    if "observation" in metadata:
        observation = _mapping(metadata["observation"], "observation")
        validate_identifier(observation.get("subject"))
        _timestamp(observation.get("observed_at"), "observation observed_at")
        for aspect in _array(observation.get("aspects"), "observation aspects", nonempty=True):
            _text(aspect, "observation aspect")
        if len(set(observation["aspects"])) != len(observation["aspects"]):
            raise ValidationError("observation aspects must be unique")
    if "assurance" in metadata:
        assurance = _mapping(metadata["assurance"], "assurance")
        allowed = {
            "evidence": {"supported", "unsupported", "unknown"},
            "implementation": {"verified", "failed", "not_run", "unknown"},
            "benefit": {"observed", "not_observed", "unknown"},
        }
        if set(assurance) - set(allowed):
            raise ValidationError("Unknown assurance dimension")
        for dimension, states in allowed.items():
            if dimension not in assurance:
                continue
            assertion = _mapping(assurance[dimension], "assurance " + dimension)
            if assertion.get("status") not in states:
                raise ValidationError("Invalid assurance " + dimension + " status")
            basis = _array(assertion.get("basis", []), "assurance " + dimension + " basis")
            if assertion["status"] not in ("unknown", "not_run") and not basis:
                raise ValidationError("Assurance " + dimension + " assertion requires pinned basis")
            for ref in basis:
                validate_reference(ref, pinned=True)
    if "method_package" in metadata:
        from .methods import validate_method, exact_reference
        package = _mapping(metadata['method_package'], 'method package')
        if package.get('schema') != 'ekk.method-package/0.1' or kind != 'note':
            raise ValidationError('inert note method package required')
        validate_method(package.get('spec'))
        source = exact_reference(package.get('artifact_source'))
        if source not in metadata.get('basis', []):
            raise ValidationError('method artifact must be an explicit pinned basis')
    if 'method_admission' in metadata:
        from .methods import exact_reference
        admission = _mapping(metadata['method_admission'], 'method admission')
        if kind != 'decision' or admission.get('status') not in ('available', 'retired'):
            raise ValidationError('method admission is a local decision')
        exact_reference(admission.get('method'))
        if admission['status'] == 'available':
            exact_reference(admission.get('evaluation'))
        if admission['method'] not in metadata.get('basis', []):
            raise ValidationError('method admission requires exact method basis')
    if "method" in metadata:
        method = _mapping(metadata["method"], "method")
        for field in ("supported_work", "guaranteed_result", "checks", "assumptions", "stop_conditions", "autonomy_boundary"):
            values = _array(method.get(field), "method " + field, nonempty=True)
            for value in values:
                _text(value, "method " + field)
    if "evolution" in metadata:
        evolution = _mapping(metadata["evolution"], "evolution")
        if kind not in ("decision", "policy"):
            raise ValidationError("Only a decision or policy can describe rule evolution")
        if evolution.get("propagation") not in ("local", "explicit"):
            raise ValidationError("Evolution propagation must be local or explicit")
        for field in ("applicability", "rollback"):
            _text(evolution.get(field), "evolution " + field)
        origin_scopes = _array(evolution.get("origin_scopes"), "evolution origin_scopes", nonempty=True)
        for item in origin_scopes:
            validate_identifier(item)
        if evolution["propagation"] == "local" and not set(scope) <= set(origin_scopes):
            raise ValidationError("Local evolution cannot expand beyond origin scopes")
        propagation_basis = _array(evolution.get("propagation_basis", []), "evolution propagation basis")
        if evolution["propagation"] == "explicit" and not propagation_basis:
            raise ValidationError("Explicit propagation requires pinned basis")
        for ref in propagation_basis:
            validate_reference(ref, pinned=True)
    if metadata.get("requires"):
        raise ValidationError("Unsupported mandatory record semantics")
    return dict(metadata)
