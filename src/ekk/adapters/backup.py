"""Owner-local, immutable backups and isolated recovery drills.

The caller must resolve one explicitly registered realm, verify the current OS
principal owns its *entire* published store, and reject workspace/gateway scope
ceilings. A contained realm additionally requires authority and acknowledgment
to retain its selected outer branch's complete history. Original commit IDs
necessarily retain that history, including files outside the managed prefix.

Only published Git history, this store's operation refs, and exact capture
requests matched to those operations and the supplied UID are retained. Legacy
capture rows do not contain their identity/key; missing or unpublished rows
cannot be reconstructed or safely attributed to a contained realm. Other host
journals, credentials, Git configuration/hooks, profiles, caches and execution
receipts/quarantine are excluded. Restored knowledge never grants execution:
existing method admission still needs the host's independently verified receipt.

This is a local integrity archive, not a signature, remote backup, cutover or a
second record store. Keep its returned SHA-256 separately when authenticity of
the selected archive matters. Restore always claims new paths and delegates
publication validation and runtime activation to the existing Git stores.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile

from .contained_store import ContainedGitStore
from .git_store import GitStore, _atomic
from .markdown import MarkdownCodec
from ekk.model import RecoveryConflict, StoreError, ValidationError, digest


SCHEMA = "ekk.backup/0.1"
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_PAYLOADS = 10000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_OBJECT_BYTES = 512 * 1024 * 1024
MAX_OBJECTS = 100000
_HEX = re.compile(r"[0-9a-f]{64}")
_OID = re.compile(r"[0-9a-f]{40}")
_REQUEST = re.compile(r"capture-requests/[0-9a-f]{64}\.json")


def _json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValidationError("Duplicate backup JSON key")
            value[key] = item
        return value

    def constant(_):
        raise ValidationError("Nonstandard backup JSON value")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise ValidationError("Invalid backup JSON") from exc


def _canonical(value):
    return json.dumps(value, sort_keys=True).encode()


def _safe_path(value):
    path = Path(value).expanduser().absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValidationError("Backup paths must not traverse symlinks")
    return path.resolve()


def _overlap(first, second):
    return first == second or first in second.parents or second in first.parents


def _new_path(value):
    path = _safe_path(value)
    if path.exists():
        raise ValidationError("Backup and recovery destinations must be new paths")
    if not path.parent.is_dir():
        raise ValidationError("Destination parent must already exist")
    return path


def _regular_bytes(path, limit):
    path = _safe_path(path)
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValidationError("Backup input must be a regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValidationError("Backup input exceeds its size limit")
    return raw


def _hash_file(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _refs(store):
    rows = store._git("for-each-ref", "--format=%(refname) %(objectname)", store.operations_ref).stdout.decode().splitlines()
    if len(rows) >= MAX_OBJECTS:
        raise ValidationError("Too many backup operation refs")
    refs = {store.publication_ref: store._head()}
    for row in rows:
        name, oid = row.split()
        if name != store.operations_ref + name.rsplit("/", 1)[-1] or not _HEX.fullmatch(name.rsplit("/", 1)[-1]):
            raise RecoveryConflict("Unrecognized operation ref")
        refs[name] = oid
    if not refs[store.publication_ref] or len(refs) == 1:
        raise RecoveryConflict("Backup requires published operation evidence")
    return refs


def _completed_operations(store, refs):
    """Read only while the caller holds _lock; never recursively acquire it."""
    head = refs[store.publication_ref]
    history = set(store.history())
    operations = {}
    for ref, oid in refs.items():
        if ref == store.publication_ref:
            continue
        row = _json(store._read_evidence(oid)["files"]["operation.json"])
        if (not isinstance(row, dict) or row.get("state") != "prepared"
                or not isinstance(row.get("revision"), str) or row["revision"] not in history):
            raise RecoveryConflict("Incomplete publication; run store recovery before backup")
        operations[ref] = row
    directory = store.runtime_dir / "journals"
    _safe_path(directory)
    if directory.exists():
        for path in directory.iterdir():
            if path.suffix != ".json":
                continue
            row = _json(_regular_bytes(path, MAX_REQUEST_BYTES))
            expected = operations.get(store.operations_ref + path.stem)
            if (not isinstance(row, dict) or row.get("state") != "complete"
                    or row | {"state": "prepared"} != expected):
                raise RecoveryConflict("Incomplete or conflicting runtime journal; recover before backup")
    snapshot = store.snapshot(head)
    store._check_clean(snapshot["files"], snapshot["files"])
    return operations


def _capture_requests(store, operations, principal, data_home):
    directory = data_home / "capture-requests"
    if not directory.exists():
        return {}, {}
    _safe_path(directory)
    matches = {}
    for ref, row in operations.items():
        request = row.get("request", {})
        if request.get("principal") == principal:
            key = _canonical([request.get("base"), request.get("changes")])
            matches.setdefault(key, ref)
    payloads, bindings = {}, {}
    for number, path in enumerate(directory.iterdir()):
        if number >= MAX_PAYLOADS * 2:
            raise ValidationError("Too many capture-request journal entries")
        if path.suffix != ".json":
            continue
        if not _HEX.fullmatch(path.stem):
            raise ValidationError("Unrecognized capture-request journal name")
        raw = _regular_bytes(path, MAX_REQUEST_BYTES)
        row = _json(raw)
        if not isinstance(row, dict) or not isinstance(row.get("proposal"), dict):
            raise ValidationError("Invalid capture-request journal")
        proposal = row["proposal"]
        if proposal.get("schema") != "ekk.proposal/0.1" or not isinstance(proposal.get("changes"), dict):
            raise ValidationError("Invalid capture-request proposal")
        try:
            changes = {name: None if value is None else digest(base64.b64decode(value, validate=True))
                       for name, value in proposal["changes"].items()}
        except (ValueError, TypeError) as exc:
            raise ValidationError("Invalid capture-request bytes") from exc
        ref = matches.get(_canonical([proposal.get("base"), changes]))
        if ref is None:
            continue  # Not a proven publication for this realm and principal.
        if not isinstance(row.get("request_digest"), str) or not _HEX.fullmatch(row["request_digest"]):
            raise ValidationError("Invalid capture-request digest")
        name = "capture-requests/" + path.name
        payloads[name], bindings[name] = raw, ref
    return payloads, bindings


def _source(store, data_home):
    contained = isinstance(store, ContainedGitStore)
    repository = store.repository_root if contained else store.path
    for path in (repository, store.path, store.runtime_dir, data_home):
        _safe_path(path)
    git_dir = repository / ".git"
    if any((git_dir / name).exists() for name in ("shallow", "commondir")):
        raise ValidationError("Backup requires complete standalone Git history")
    return {"kind": "contained" if contained else "standalone",
            "repository_path": str(repository), "realm_path": str(store.path),
            "runtime_dir": str(store.runtime_dir), "data_home": str(data_home),
            "prefix": store.prefix if contained else "",
            "publication_ref": store.publication_ref,
            "operations_ref": store.operations_ref,
            "namespace": store._namespace if contained else None}


def create_backup(store, destination, *, realm_id, principal, data_home, include_repository_history=False):
    """Publish a new private tar archive of a completed immutable store version.

    Preconditions in the module docstring are the composition root's duty. This
    adapter verifies supplied realm/UID identity but is not an authorization port.
    Pending publications fail without recovery or source projection changes.
    """
    if type(store) not in (GitStore, ContainedGitStore):
        raise ValidationError("Backup requires an explicit supported owner store")
    if type(include_repository_history) is not bool:
        raise ValidationError("Repository-history acknowledgment must be a boolean")
    if isinstance(store, ContainedGitStore) and not include_repository_history:
        raise ValidationError("Unsupported realm-only backup for contained storage; explicit repository-history authority required")
    if principal != "local:uid:" + str(os.getuid()):
        raise PermissionError("Backup principal must be the current local OS owner")
    destination, data_home = _new_path(destination), _safe_path(data_home)
    source = _source(store, data_home)
    if any(_overlap(destination, Path(source[key])) for key in
           ("repository_path", "runtime_dir", "data_home")):
        raise ValidationError("Backup destination must be outside source and runtime trees")
    with tempfile.TemporaryDirectory(prefix=".ekk-backup-", dir=destination.parent) as temporary:
        temporary = Path(temporary)
        bundle = temporary / "repository.bundle"
        # Pin the manifest, operation namespace, and capture-request selection
        # inside the same cooperating writer lock; no lock-taking store calls.
        with store._lock():
            refs = _refs(store)
            operations = _completed_operations(store, refs)
            current = store.snapshot(refs[store.publication_ref])
            realm = MarkdownCodec().load_yaml(current["files"][".ekk/realm.yaml"])
            if realm.get("id") != realm_id:
                raise ValidationError("Backup realm identity differs from published bytes")
            requests, bindings = _capture_requests(store, operations, principal, data_home)
            if len(requests) + 1 > MAX_PAYLOADS:
                raise ValidationError("Too many backup capture requests")
            store._git("bundle", "create", str(bundle), *sorted(refs))
            if _bundle_refs(store, bundle) != refs or _refs(store) != refs:
                raise RecoveryConflict("Store refs changed during backup")
        payloads = {"repository.bundle": {"size": bundle.stat().st_size, "sha256": _hash_file(bundle)}}
        payloads.update({name: {"size": len(raw), "sha256": digest(raw)} for name, raw in requests.items()})
        manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                    "realm_id": realm_id, "principal": principal, "source": source,
                    "backup_scope": "repository-history" if source["kind"] == "contained" else "realm",
                    "contains_repository_history": source["kind"] == "contained",
                    "revision": refs[store.publication_ref], "refs": refs, "payloads": payloads,
                    "capture_operations": bindings,
                    "capture_request_coverage": "existing requests matching published operations for this realm and UID only",
                    "host_execution_evidence": "excluded_unverified", "production_cutover": "not_performed"}
        # Verify the independent objects and existing recovery engine before
        # reporting a completed backup. This touches only a disposable copy.
        _materialize(bundle, temporary / "verify", manifest)
        _activate(temporary / "verify", temporary / "verify-data", manifest)
        raw_manifest = _canonical(manifest)
        if len(raw_manifest) > MAX_MANIFEST_BYTES:
            raise ValidationError("Backup manifest exceeds its size limit")
        archive = temporary / "archive.tar"
        with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as output:
            _tar_add(output, "manifest.json", raw_manifest)
            with bundle.open("rb") as stream:
                entry = tarfile.TarInfo("repository.bundle")
                entry.size, entry.mode = bundle.stat().st_size, 0o600
                output.addfile(entry, stream)
            for name, raw in sorted(requests.items()):
                _tar_add(output, name, raw)
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValidationError("Backup archive exceeds its size limit")
        os.chmod(archive, 0o600)
        with archive.open("rb") as stream:
            os.fsync(stream.fileno())
        archive_digest = _hash_file(archive)
        # Atomic, no-overwrite publication: never replace a racing destination.
        os.link(archive, destination)
        _fsync(destination.parent)
    return {"schema": SCHEMA, "archive": str(destination), "sha256": archive_digest,
            "realm_id": realm_id, "revision": manifest["revision"], "refs": len(refs),
            "backup_scope": manifest["backup_scope"], "contains_repository_history": manifest["contains_repository_history"],
            "capture_requests": len(requests), "capture_request_coverage": manifest["capture_request_coverage"],
            "verified": ["independent_git_objects", "published_history_and_receipts", "isolated_runtime_activation"],
            "host_execution_evidence": "excluded_unverified", "production_cutover": "not_performed"}


def _fsync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _tar_add(output, name, raw):
    entry = tarfile.TarInfo(name)
    entry.size, entry.mode = len(raw), 0o600
    output.addfile(entry, io.BytesIO(raw))


def _bundle_refs(store, bundle):
    result = {}
    for line in store._git("bundle", "list-heads", str(bundle)).stdout.decode().splitlines():
        oid, name = line.split()
        if name in result or not _OID.fullmatch(oid):
            raise ValidationError("Invalid or duplicate Git bundle ref")
        result[name] = oid
    return result


def _validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValidationError("Unsupported backup manifest")
    required = {"schema", "created_at", "realm_id", "principal", "source", "revision", "refs", "payloads",
                "capture_operations", "capture_request_coverage", "host_execution_evidence", "production_cutover",
                "backup_scope", "contains_repository_history"}
    if set(manifest) != required or manifest["host_execution_evidence"] != "excluded_unverified" or manifest["production_cutover"] != "not_performed":
        raise ValidationError("Unknown backup semantics")
    if manifest["principal"] != "local:uid:" + str(os.getuid()):
        raise PermissionError("Restore must retain the same local OS principal")
    if not isinstance(manifest["realm_id"], str) or not manifest["realm_id"]:
        raise ValidationError("Backup realm identity required")
    source = manifest["source"]
    fields = {"kind", "repository_path", "realm_path", "runtime_dir", "data_home", "prefix", "publication_ref", "operations_ref", "namespace"}
    if not isinstance(source, dict) or set(source) != fields or source["kind"] not in ("standalone", "contained"):
        raise ValidationError("Unsupported backup source")
    if (manifest["contains_repository_history"] is not (source["kind"] == "contained")
            or manifest["backup_scope"] != ("repository-history" if source["kind"] == "contained" else "realm")):
        raise ValidationError("Backup scope differs from retained Git history")
    for name in ("repository_path", "realm_path", "runtime_dir", "data_home"):
        if not isinstance(source[name], str) or not Path(source[name]).is_absolute() or str(Path(source[name])) != source[name]:
            raise ValidationError("Backup source paths must be canonical absolute paths")
    if not isinstance(source["prefix"], str) or not isinstance(source["publication_ref"], str):
        raise ValidationError("Invalid backup Git identity")
    if source["kind"] == "standalone":
        if (source["prefix"] or source["namespace"] is not None
                or source["repository_path"] != source["realm_path"]
                or source["publication_ref"] != GitStore.publication_ref or source["operations_ref"] != GitStore.operations_ref):
            raise ValidationError("Invalid standalone backup identity")
    else:
        prefix = source["prefix"]
        if (not prefix.endswith("/") or PurePosixPath(prefix).is_absolute()
                or any(part in (".", "..", ".git") for part in PurePosixPath(prefix).parts)
                or str(PurePosixPath(prefix)) + "/" != prefix or "\\" in prefix
                or not source["publication_ref"].startswith("refs/heads/")
                or not isinstance(source["namespace"], str) or not _HEX.fullmatch(source["namespace"])
                or source["operations_ref"] != "refs/ekk/contained/" + source["namespace"] + "/operations/"
                or Path(source["repository_path"]) / prefix != Path(source["realm_path"])):
            raise ValidationError("Invalid contained backup identity")
    refs = manifest["refs"]
    if (not isinstance(refs, dict) or not 1 < len(refs) <= MAX_OBJECTS
            or refs.get(source["publication_ref"]) != manifest["revision"]):
        raise ValidationError("Backup lacks pinned publication and operation refs")
    for name, oid in refs.items():
        if (not isinstance(oid, str) or not _OID.fullmatch(oid)
                or (name != source["publication_ref"] and
                    (not name.startswith(source["operations_ref"]) or not _HEX.fullmatch(name[len(source["operations_ref"]):])))):
            raise ValidationError("Backup contains a ref outside its declared store")
    payloads = manifest["payloads"]
    if not isinstance(payloads, dict) or not 1 <= len(payloads) <= MAX_PAYLOADS or "repository.bundle" not in payloads:
        raise ValidationError("Backup payload manifest required")
    total = 0
    for name, row in payloads.items():
        if (name != "repository.bundle" and not _REQUEST.fullmatch(name)) or not isinstance(row, dict) or set(row) != {"size", "sha256"}:
            raise ValidationError("Unsafe backup payload")
        limit = MAX_ARCHIVE_BYTES if name == "repository.bundle" else MAX_REQUEST_BYTES
        if (type(row["size"]) is not int or not 0 <= row["size"] <= limit
                or not isinstance(row["sha256"], str) or not _HEX.fullmatch(row["sha256"])):
            raise ValidationError("Invalid backup payload size or digest")
        total += row["size"]
    if total > MAX_ARCHIVE_BYTES:
        raise ValidationError("Backup payload total exceeds its size limit")
    bindings = manifest["capture_operations"]
    if (not isinstance(bindings, dict) or set(bindings) != set(payloads) - {"repository.bundle"}
            or any(not isinstance(ref, str) or ref == source["publication_ref"] or ref not in refs for ref in bindings.values())):
        raise ValidationError("Capture requests must be bound to pinned operations")


def _read_archive(archive, temporary):
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValidationError("Backup archive exceeds its size limit")
    seen, manifest = set(), None
    # Uncompressed, explicitly allowlisted regular members only. Never extractall
    # or follow archive paths/links, including tar extended headers and sparse data.
    with tarfile.open(archive, "r:") as stream:
        while True:
            member = stream.next()
            if member is None:
                break
            name = member.name
            if (name in seen or member.type != tarfile.REGTYPE or member.pax_headers or member.sparse
                    or member.linkname or len(seen) > MAX_PAYLOADS):
                raise ValidationError("Unsafe or duplicate backup archive member")
            if not seen:
                if name != "manifest.json" or not 0 < member.size <= MAX_MANIFEST_BYTES:
                    raise ValidationError("Backup must begin with its bounded manifest")
                manifest = _json(stream.extractfile(member).read())
                _validate_manifest(manifest)
            else:
                row = manifest["payloads"].get(name)
                if row is None or row["size"] != member.size:
                    raise ValidationError("Archive member differs from manifest")
                target = temporary / ("repository.bundle" if name == "repository.bundle" else name.split("/")[1])
                hasher = hashlib.sha256()
                with target.open("xb") as output, stream.extractfile(member) as source:
                    while block := source.read(1024 * 1024):
                        hasher.update(block)
                        output.write(block)
                if hasher.hexdigest() != row["sha256"]:
                    raise ValidationError("Backup payload digest mismatch")
                os.chmod(target, 0o600)
            seen.add(name)
    if manifest is None or seen != {"manifest.json", *manifest["payloads"]}:
        raise ValidationError("Backup archive is incomplete")
    return manifest


def _materialize(bundle, target, manifest):
    target.mkdir(mode=0o700)
    store = GitStore(target)
    store._git("init", "--quiet", "--template=")
    # New Git metadata contains no source configuration, credentials or hooks.
    if _bundle_refs(store, bundle) != manifest["refs"]:
        raise ValidationError("Git bundle refs differ from the pinned manifest")
    store._git("bundle", "verify", str(bundle))
    store._git("bundle", "unbundle", str(bundle))
    store._git("fsck", "--full", "--strict", "--no-reflogs", "--no-dangling")
    sizes = store._git("cat-file", "--batch-all-objects", "--batch-check=%(objectsize)").stdout.splitlines()
    if len(sizes) > MAX_OBJECTS or sum(int(size) for size in sizes) > MAX_OBJECT_BYTES:
        raise ValidationError("Backup Git objects exceed recovery limits")
    for name, oid in manifest["refs"].items():
        if store._git("check-ref-format", name, check=False).returncode:
            raise ValidationError("Invalid Git ref in backup")
        store._git("update-ref", name, oid, "0" * 40)
    store._git("symbolic-ref", "HEAD", manifest["source"]["publication_ref"])
    revision = manifest["revision"]
    # Build ordinary bytes directly, without checkout filters or Git hooks.
    files = store._read_commit(revision)["files"]
    store._validate_files(files)
    for name, raw in files.items():
        _atomic(store._path(name), raw, replace=False)
    # Preserve executable bits so a contained checkout remains clean.
    for entry in store._git("ls-tree", "-rz", revision).stdout.split(b"\0"):
        if entry:
            metadata, name = entry.split(b"\t", 1)
            os.chmod(store._path(name.decode()), 0o700 if metadata.startswith(b"100755 ") else 0o600)
    store._git("read-tree", revision)
    source = manifest["source"]
    if source["kind"] == "standalone":
        _atomic(target / ".git/ekk-store-path", source["realm_path"].encode())
        _atomic(target / ".git/ekk-runtime", source["runtime_dir"].encode())
    else:
        selector = digest(json.dumps([source["prefix"], source["publication_ref"]]).encode())
        identity = json.dumps({"repository": source["repository_path"], "realm": source["realm_path"],
                               "publication_ref": source["publication_ref"]}, sort_keys=True)
        registration = {"prefix": source["prefix"], "publication_ref": source["publication_ref"],
                        "namespace": source["namespace"], "owner": identity,
                        "runtime_dir": source["runtime_dir"], "state": "validated"}
        _atomic(target / ".git/ekk-contained/realms" / (selector + ".json"), _canonical(registration))
        _atomic(target / ".git/ekk-contained" / source["namespace"] / "runtime", source["runtime_dir"].encode())


def _activate(target, data_home, manifest):
    source = manifest["source"]
    runtime = data_home / digest(manifest["realm_id"].encode())
    if source["kind"] == "standalone":
        return GitStore.rebind_runtime(target, runtime, expected_previous_store=source["realm_path"])
    return ContainedGitStore.rebind_runtime(target / source["prefix"], target, source["publication_ref"], runtime,
        expected_previous_repository=source["repository_path"], expected_previous_realm=source["realm_path"],
        expected_operation_refs={name: oid for name, oid in manifest["refs"].items() if name != source["publication_ref"]})


def restore_backup(archive, target, *, data_home, expected_sha256=None, expected_realm_id=None):
    """Restore a verified backup into a new repository and new EKK data home.

    Replays must supply this returned data_home (EKK_DATA_HOME for the CLI).
    Neither profile registration nor source retirement/production cutover occurs.
    A failed activation can leave private partial destinations; it never reports
    success or reuses them. Retry with fresh paths after inspecting the failure.
    """
    archive, target, data_home = _safe_path(archive), _new_path(target), _new_path(data_home)
    if not archive.is_file() or _overlap(target, data_home) or any(_overlap(archive, path) for path in (target, data_home)):
        raise ValidationError("Restore requires distinct archive, repository and data-home paths")
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValidationError("Backup archive exceeds its size limit")
    archive_digest = _hash_file(archive)
    if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not _HEX.fullmatch(expected_sha256) or archive_digest != expected_sha256):
        raise ValidationError("Backup archive digest differs from the expected archive")
    with tempfile.TemporaryDirectory(prefix=".ekk-restore-", dir=target.parent) as temporary:
        temporary = Path(temporary)
        try:
            manifest = _read_archive(archive, temporary)
        except (tarfile.TarError, EOFError) as exc:
            raise ValidationError("Invalid or incomplete backup archive") from exc
        if expected_realm_id is not None and manifest['realm_id'] != expected_realm_id:
            raise PermissionError('Backup realm differs from the explicitly registered route')
        for key in ("repository_path", "realm_path", "runtime_dir", "data_home"):
            original = Path(manifest["source"][key]).resolve()
            if any(_overlap(path, original) for path in (target, data_home)):
                raise ValidationError("Recovery destinations must be separate from the original source and runtime")
        # Validate both Git data and activation before claiming final destinations.
        verification = temporary / "verify"
        _materialize(temporary / "repository.bundle", verification, manifest)
        clone = _activate(verification, temporary / "verify-data", manifest)
        realm = MarkdownCodec().load_yaml(clone.snapshot()["files"][".ekk/realm.yaml"])
        if realm.get("id") != manifest["realm_id"]:
            raise ValidationError("Restored realm differs from backup identity")
        if expected_realm_id is not None:
            from ..application import RealmService
            from ..assets import pack_directory
            from .packs import PackDirectory
            app = RealmService(clone, principal=manifest['principal'], codec=MarkdownCodec(),
                               pack_loader=PackDirectory(pack_directory()))
            _, policy, _, _ = app._validate(clone.snapshot())
            if realm.get('owner') != app.principal or policy.get('bootstrap_owner') != app.principal:
                raise PermissionError('Registered recovery requires the retained realm owner')
            app._authorized(policy, 'read', ['*'])
            app._authorized(policy, 'write', ['*'])
        # Verify capture attribution against the restored immutable operation refs.
        for name, ref in manifest["capture_operations"].items():
            row = _json(_regular_bytes(temporary / name.split("/")[1], MAX_REQUEST_BYTES))
            operation = _json(clone._read_evidence(manifest["refs"][ref])["files"]["operation.json"])
            proposal = row.get("proposal", {}) if isinstance(row, dict) else {}
            try:
                changes = {name: None if raw is None else digest(base64.b64decode(raw, validate=True))
                           for name, raw in proposal["changes"].items()}
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                raise ValidationError("Invalid restored capture request") from exc
            if (proposal.get("schema") != "ekk.proposal/0.1" or proposal.get("base") != operation["base"]
                    or changes != operation["request"]["changes"] or operation["request"]["principal"] != manifest["principal"]
                    or not isinstance(row.get("request_digest"), str) or not _HEX.fullmatch(row["request_digest"])):
                raise ValidationError("Capture request differs from its owning operation")
        # Claim before writes; never overwrite or merge an existing root/runtime.
        data_home.mkdir(mode=0o700)
        _materialize(temporary / "repository.bundle", target, manifest)
        # Replay IDs must be durable before the copy can become writable. An
        # interrupted metadata copy retains the previous owner's Git markers,
        # so the existing store refuses writes until explicit activation.
        if manifest['capture_operations']:
            (data_home / 'capture-requests').mkdir(mode=0o700)
        for name in manifest["capture_operations"]:
            _atomic(data_home / name, (temporary / name.split("/")[1]).read_bytes(), replace=False)
            os.chmod(data_home / name, 0o600)
        clone = _activate(target, data_home, manifest)
        receipt = {"schema": "ekk.restore/0.1", "archive": str(archive), "archive_sha256": archive_digest,
                   "realm_id": manifest["realm_id"], "revision": manifest["revision"],
                   "backup_scope": manifest["backup_scope"], "contains_repository_history": manifest["contains_repository_history"],
                   "realm_path": str(clone.path), "repository_path": str(target), "runtime_dir": str(clone.runtime_dir),
                   "data_home": str(data_home), "mode": "isolated_restore_drill", "state": "validated",
                   "capture_requests": len(manifest["capture_operations"]),
                   "capture_request_coverage": manifest["capture_request_coverage"],
                   "host_execution_evidence": "excluded_unverified", "source_writer_retirement": "externally_unproven",
                   "production_cutover": "not_performed"}
        _atomic(data_home / "restore.json", _canonical(receipt), replace=False)
        _fsync(target.parent)
        _fsync(data_home.parent)
        return receipt
