"""Single-host Git publication with a recoverable ordinary file projection.

Published commits are atomic snapshots; arbitrary filesystem readers are not.
The flock coordinates cooperating writers, not external editors or other hosts.
Runtime journals are durable data and must be backed up with the repository.
"""
from collections import OrderedDict
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import threading
import unicodedata

from ekk.model import (Conflict, DirtyWorkingTree, IdempotencyConflict,
                       RecoveryConflict, StoreError, ValidationError, digest)
from .file_lock import acquire_lock

REF = "refs/ekk/published"
_OBJECT_ID = re.compile(rb"([0-9a-f]{40})\n?")


class _Memo:
    """Process-wide memo of immutable Git facts, bounded by a weight per entry.

    Object IDs fix what they name: a commit its tree and parents, a head the
    history behind it, a blob its digest. Entries never go stale; publication
    only adds new IDs, and refs themselves are always read again. Bounds keep a
    long-running host small.
    """

    def __init__(self, limit, weight=lambda value: 1):
        self.items, self.limit, self.weight, self.total = OrderedDict(), limit, weight, 0
        self.lock = threading.Lock()

    def get(self, key, read=None):
        with self.lock:
            entry = self.items.get(key)
            if entry is not None:
                self.items.move_to_end(key)
                return entry[0]
        if read is None:
            return None
        value = read()
        self.put(key, value)
        return value

    def put(self, key, value):
        weight = self.weight(value)
        if weight > self.limit:
            return
        with self.lock:
            previous = self.items.pop(key, None)
            if previous is not None:
                self.total -= previous[1]
            self.items[key] = (value, weight)
            self.total += weight
            while self.total > self.limit:
                self.total -= self.items.popitem(last=False)[1][1]


_COMMIT_FILES = _Memo(256 * 1024 * 1024, lambda files: sum(len(raw) for raw in files.values()))
_TREES = _Memo(1_000_000, len)
_HISTORIES = _Memo(16)
_PARENTS = _Memo(100_000)


def _loose_ref(git_dir, ref):
    """Object ID from a loose ref file, or None so that Git resolves the ref.

    In the files backend a loose ref takes precedence over packed-refs. Anything
    else (packed or reftable refs, symbolic refs, symlinks) goes to Git.
    """
    try:
        path = Path(git_dir)
        for part in ref.split("/"):
            path = path / part
            if stat.S_ISLNK(os.lstat(path).st_mode):
                return None
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 64:
            return None
        match = _OBJECT_ID.fullmatch(path.read_bytes())
    except (OSError, ValueError):
        return None
    return match.group(1).decode() if match else None


def _mkdir_durable(path):
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        fd = os.open(created.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic(path, data, *, replace=True):
    _mkdir_durable(path.parent)
    fd, name = tempfile.mkstemp(prefix=".ekk-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(name, path)
        else:
            # Link the fully durable temporary inode without replacing an owner
            # claimed concurrently by another restore activation.
            os.link(name, path)
            os.unlink(name)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class GitStore:
    publication_ref = REF
    operations_ref = "refs/ekk/operations/"

    def __init__(self, path, runtime_dir=None):
        raw = Path(path).absolute()
        if raw.is_symlink():
            raise ValidationError("Store path must not traverse symlinks")
        self.path = raw.resolve()
        if (self.path / ".git").is_symlink():
            raise ValidationError("Git metadata must not be a symlink")
        default = (Path.home() / "Library/Application Support/ekk" if sys.platform == "darwin"
                   else Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ekk")
        binding = self.path / ".git/ekk-runtime"
        if binding.is_symlink():
            raise ValidationError("Runtime binding must not be a symlink")
        existing = binding.read_text().strip() if binding.is_file() else None
        self.runtime_dir = Path(runtime_dir or existing or default / digest(str(self.path).encode())).absolute()
        if self.runtime_dir.is_symlink():
            raise ValidationError("Runtime path must not traverse symlinks")
        self.runtime_dir = self.runtime_dir.resolve()
        if self.runtime_dir == self.path or self.path in self.runtime_dir.parents:
            raise ValidationError("Runtime journals must be outside the realm")
        if existing and self.runtime_dir != Path(existing):
            raise StoreError("Store already has a different runtime journal location")

    @classmethod
    def rebind_runtime(cls, path, runtime_dir, *, expected_previous_store):
        """Resume an explicit isolated restore drill; never change source/routes.

        Requires a full independent Git copy, including custom EKK refs. The
        durable clone marker makes partial binding writes retryable. Production
        retirement/cutover remains an external owner operation.
        """
        clone = cls(path)
        previous = Path(expected_previous_store).absolute().resolve()
        if clone.path == previous:
            raise ValidationError("Recovery clone must be distinct from its previous store")
        git_dir = clone.path / ".git"
        if not git_dir.is_dir() or git_dir.is_symlink():
            raise StoreError("Recovery requires a standalone copied Git repository")
        if (git_dir / "objects/info/alternates").exists() or (git_dir / "commondir").exists():
            raise StoreError("Recovery copy must contain independent Git objects")
        runtime = Path(runtime_dir).absolute()
        if runtime.is_symlink():
            raise ValidationError("Recovery runtime must not be a symlink")
        runtime = runtime.resolve()
        if runtime == clone.path or clone.path in runtime.parents:
            raise ValidationError("Recovery requires a runtime outside the clone")
        lock = git_dir / "ekk-writer.lock"
        if lock.is_symlink():
            raise StoreError("Invalid writer lock")
        with lock.open("a+b") as stream:
            acquire_lock(stream, kind='writer')
            marker = git_dir / "ekk-store-path"
            stage_path = git_dir / "ekk-recovery-clone.json"
            if marker.is_symlink() or stage_path.is_symlink():
                raise StoreError("Invalid recovery marker")
            stage = json.loads(stage_path.read_text()) if stage_path.exists() else None
            previous_recovery = None
            if (isinstance(stage, dict) and stage.get("kind") == "recovery_clone"
                    and stage.get("state") == "validated" and stage.get("store_path") == str(previous)
                    and marker.is_file() and marker.read_text() == str(previous)):
                # The copied marker belongs to the source's completed restoration,
                # not to this activation. Retain it as provenance for the new drill.
                previous_recovery, stage = stage, None
            if stage is not None:
                if (not isinstance(stage, dict) or stage.get("kind") != "recovery_clone"
                        or stage.get("source_store") != str(previous) or stage.get("store_path") != str(clone.path)
                        or stage.get("runtime_dir") != str(runtime) or stage.get("state") not in ("prepared", "validated")):
                    raise StoreError("Conflicting recovery activation request")
                previous_runtime = Path(stage["previous_runtime"])
                if clone.runtime_dir not in (previous_runtime, runtime):
                    raise StoreError("Runtime binding differs from pending recovery")
            else:
                previous_runtime = clone.runtime_dir
            if runtime == previous_runtime:
                raise ValidationError("Recovery requires a new independent runtime")
            if (previous_runtime / "store-path").is_symlink():
                raise StoreError("Invalid previous owner marker")
            recorded_owner = (marker.read_text() if marker.is_file()
                              else (previous_runtime / "store-path").read_text()
                              if (previous_runtime / "store-path").is_file() else None)
            allowed_owners = (str(previous), str(clone.path)) if stage else (str(previous),)
            if recorded_owner not in allowed_owners:
                raise StoreError("Previous store owner does not match the recovery request")
            source_binding = previous / ".git/ekk-runtime"
            if source_binding.is_file() and source_binding.read_text() != str(previous_runtime):
                raise StoreError("Copied runtime binding differs from the previous store")
            owner_path = runtime / "store-path"
            if owner_path.is_symlink():
                raise StoreError("Invalid recovery runtime owner")
            if runtime.exists():
                if not runtime.is_dir():
                    raise StoreError("Recovery runtime must be a directory")
                if any(runtime.iterdir()) and (not stage or not owner_path.is_file() or owner_path.read_text() != str(clone.path)):
                    raise StoreError("Recovery runtime is not empty or owned by this activation")
            if clone._head() is None:
                raise RecoveryConflict("Recovery copy is missing the published ref")
            # Validate Git evidence and an exact ordinary projection before changing
            # durable bindings. Scratch journals are derivative verification data.
            current_files = clone.snapshot()["files"]
            clone._check_clean(current_files, current_files)
            with tempfile.TemporaryDirectory(prefix="ekk-restore-check-") as temporary:
                clone.runtime_dir = Path(temporary)
                clone._recover()
                if not any(json.loads(entry.read_text())["revision"] == clone._head()
                           for entry in (clone.runtime_dir / "journals").glob("*.json")):
                    raise RecoveryConflict("Recovery copy is missing evidence for its published snapshot")
            clone.runtime_dir = runtime
            if stage is None:
                stage = {"kind": "recovery_clone", "source_store": str(previous), "store_path": str(clone.path),
                         "runtime_dir": str(runtime), "previous_runtime": str(previous_runtime),
                         "mode": "isolated_restore_drill", "state": "prepared",
                         "source_writer_retirement": "externally_unproven", "production_cutover": "not_performed",
                         "recorded_at": datetime.now(timezone.utc).isoformat()}
                if previous_recovery is not None:
                    stage["previous_recovery"] = previous_recovery
                _atomic(stage_path, json.dumps(stage, sort_keys=True).encode())
            _mkdir_durable(runtime)
            os.chmod(runtime, 0o700)
            if not owner_path.exists():
                try:
                    _atomic(owner_path, str(clone.path).encode(), replace=False)
                except FileExistsError:
                    if owner_path.read_text() != str(clone.path):
                        raise StoreError("Recovery runtime was claimed by another store")
            _atomic(git_dir / "ekk-runtime", str(runtime).encode())
            _atomic(marker, str(clone.path).encode())
            clone._recover()
            stage["state"] = "validated"
            _atomic(stage_path, json.dumps(stage, sort_keys=True).encode())
        return clone

    def _git(self, *args, data=None, env=None, check=True):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        clean.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                      "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "EKK", "GIT_AUTHOR_EMAIL": "ekk@localhost",
                      "GIT_COMMITTER_NAME": "EKK", "GIT_COMMITTER_EMAIL": "ekk@localhost"})
        if env:
            clean.update(env)
        # Large batch input and blob output can fill both pipes on supported
        # hosts. A private anonymous input file removes that duplex dependency;
        # communicate still drains stdout/stderr and no source enters a shell.
        with tempfile.TemporaryFile(mode='w+b') if data is not None else nullcontext(None) as source:
            if source is not None:
                source.write(data)
                source.flush()
                source.seek(0)
            result = subprocess.run(["git", "-c", "core.fsync=committed", "-c", "core.fsyncMethod=fsync", "-C", str(getattr(self, "repository_root", self.path)), *args], stdin=source,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=clean)
        if check and result.returncode:
            raise StoreError(result.stderr.decode(errors="replace").strip())
        return result

    @contextmanager
    def _lock(self):
        if (self.path / ".git").is_symlink() or not (self.path / ".git").is_dir():
            raise StoreError("Expected a standalone Git realm")
        lock = self.path / ".git/ekk-writer.lock"
        if lock.is_symlink():
            raise StoreError("Invalid writer lock")
        with lock.open("a+b") as stream:
            acquire_lock(stream, kind='writer')
            self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            owner = self.runtime_dir / "store-path"
            try:
                with owner.open("xb") as identity:
                    identity.write(str(self.path).encode())
                    identity.flush()
                    os.fsync(identity.fileno())
            except FileExistsError:
                pass
            if owner.is_symlink() or owner.read_text() != str(self.path):
                raise StoreError("Runtime journal directory belongs to another store")
            store_marker = self.path / ".git/ekk-store-path"
            if store_marker.is_symlink() or (store_marker.exists() and store_marker.read_text() != str(self.path)):
                raise StoreError("Copied store requires explicit recovery runtime activation")
            if not store_marker.exists():
                _atomic(store_marker, str(self.path).encode())
            binding = self.path / ".git/ekk-runtime"
            if binding.exists() and binding.read_text().strip() != str(self.runtime_dir):
                raise StoreError("Store already has a different runtime journal location")
            if not binding.exists():
                _atomic(binding, str(self.runtime_dir).encode())
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _metadata_dir(self):
        return getattr(self, "git_dir", None) or self.path / ".git"

    def _memo_scope(self):
        return str(self._metadata_dir()), getattr(self, "prefix", "")

    def _head(self):
        loose = _loose_ref(self._metadata_dir(), self.publication_ref)
        if loose is not None:
            return loose
        result = self._git("rev-parse", "--verify", self.publication_ref, check=False)
        return result.stdout.decode().strip() if not result.returncode else None

    def _path(self, name, *, inspect=True):
        if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
            raise ValidationError("Invalid store path")
        parts = PurePosixPath(name).parts
        if name.startswith("/") or any(p in (".", "..") or p.casefold() == ".git" for p in parts) or str(PurePosixPath(name)) != name:
            raise ValidationError("Unsafe store path")
        target = self.path / name
        if inspect and any(p.is_symlink() for p in (target, *target.parents)):
            raise ValidationError("Store paths must not traverse symlinks")
        return target

    def _validate_files(self, files, *, deletes=False):
        if not isinstance(files, dict):
            raise ValidationError("Files must be a path-to-bytes mapping")
        for name, data in files.items():
            self._path(name)
            if not isinstance(data, bytes) and not (deletes and data is None):
                raise ValidationError("File contents must be bytes")
        names = {unicodedata.normalize("NFC", name).casefold() for name in files}
        if len(names) != len(files):
            raise ValidationError("Unicode-normalized case-insensitive file path collision")
        for name in names:
            if any(str(p) in names for p in PurePosixPath(name).parents if str(p) != "."):
                raise ValidationError("File/directory path collision")

    def _read_tree(self, revision):
        def read():
            entries = {}
            result = self._git("ls-tree", "-rz", "--full-tree", revision).stdout
            for entry in result.split(b"\x00"):
                if not entry:
                    continue
                meta, name = entry.split(b"\t", 1)
                mode, kind, oid = meta.split()
                if mode not in (b"100644", b"100755") or kind != b"blob":
                    raise StoreError("Snapshot contains a symlink or unsupported Git object")
                name = name.decode("utf-8")
                self._path(name, inspect=False)
                entries[name] = oid
            return entries
        # Keyed by the given commit or tree ID; branch names never reach this reader.
        if self._fresh_reads or not re.fullmatch(r"[0-9a-f]{40}", revision):
            return read()
        return dict(_TREES.get((str(self._metadata_dir()), revision), read))

    def _read_blobs(self, oids):
        # Object IDs, never record-controlled expressions, enter the batch protocol.
        # Its length framing preserves arbitrary binary bytes and embedded newlines.
        objects = dict.fromkeys(oids)
        if objects:
            batch = self._git("cat-file", "--batch", data=b"".join(oid + b"\n" for oid in objects)).stdout
            offset = 0
            for oid in objects:
                end = batch.find(b"\n", offset)
                header = batch[offset:end].split() if end >= 0 else []
                if len(header) != 3 or header[:2] != [oid, b"blob"] or not header[2].isdigit():
                    raise StoreError("Invalid Git blob batch response")
                size = int(header[2])
                offset = end + 1
                if batch[offset + size:offset + size + 1] != b"\n":
                    raise StoreError("Truncated Git blob batch response")
                objects[oid] = batch[offset:offset + size]
                offset += size + 1
            if offset != len(batch):
                raise StoreError("Unexpected bytes after Git blob batch")
        return objects

    def _read_files(self, tree):
        objects = self._read_blobs(tree.values())
        return {name: objects[oid] for name, oid in tree.items()}

    def _read_commit(self, revision):
        if self._fresh_reads:
            return {"revision": revision, "files": self._read_files(self._read_tree(revision))}
        files = _COMMIT_FILES.get((self._memo_scope(), revision),
                                  lambda: self._read_files(self._read_tree(revision)))
        # A fresh mapping per call: callers may build candidates from it.
        return {"revision": revision, "files": dict(files)}

    def _history_of(self, head):
        def read():
            revisions = self._git("rev-list", head).stdout.decode().splitlines()
            return tuple(revisions), frozenset(revisions)
        return read() if self._fresh_reads else _HISTORIES.get((str(self._metadata_dir()), head), read)

    def _is_ancestor(self, revision, head):
        if self._fresh_reads:
            return not self._git("merge-base", "--is-ancestor", revision, head, check=False).returncode
        # rev-list of the head is exactly the set merge-base --is-ancestor accepts.
        return revision == head or revision in self._history_of(head)[1]

    def _parents(self, revision):
        def read():
            return tuple(self._git("rev-list", "--parents", "-n", "1", revision).stdout.decode().split()[1:])
        return read() if self._fresh_reads else _PARENTS.get((str(self._metadata_dir()), revision), read)

    @property
    def _fresh_reads(self):
        return getattr(self, "_recovering", False)

    @contextmanager
    def _reading_durable_state(self):
        """Recovery checks what Git holds on disk now, so it bypasses every memo."""
        previous = getattr(self, "_recovering", False)
        self._recovering = True
        try:
            yield
        finally:
            self._recovering = previous

    def snapshot(self, revision=None):
        head = self._head()
        if head is None:
            raise StoreError("Store has no published snapshot")
        revision = revision or head
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValidationError("Historical revision must be a full Git commit ID")
        if not self._is_ancestor(revision, head):
            raise StoreError("Revision is not in published history")
        return self._read_commit(revision)

    def file_at(self, revision, name):
        """Exact bytes of one file in a published commit: snapshot(revision)['files'][name].

        The same ancestry and tree checks apply; only that file's blob is read.
        """
        head = self._head()
        if head is None:
            raise StoreError("Store has no published snapshot")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValidationError("Historical revision must be a full Git commit ID")
        if not self._is_ancestor(revision, head):
            raise StoreError("Revision is not in published history")
        files = _COMMIT_FILES.get((self._memo_scope(), revision))
        if files is not None:
            return files[name]
        oid = self._read_tree(revision)[name]
        return self._read_blobs([oid])[oid]

    def history(self):
        head = self._head()
        if head is None:
            raise StoreError("Store has no published snapshot")
        return list(self._history_of(head)[0])

    def _read_evidence(self, revision):
        # Operation evidence is a whole Git tree, including for contained realms.
        return {"revision": revision, "files": self._read_files(GitStore._read_tree(self, revision))}

    def _commit_evidence(self, files, base):
        return GitStore._commit(self, files, base)

    def _index_matches(self, revision):
        actual = self._git("write-tree").stdout.strip()
        expected = (self._git("rev-parse", revision + "^{tree}").stdout.strip() if revision
                    else self._git("hash-object", "-t", "tree", "--stdin", data=b"").stdout.strip())
        return actual == expected

    def _sync_index(self, revision):
        self._git("read-tree", revision)

    def _commit(self, files, base):
        with tempfile.TemporaryDirectory(prefix="staging-", dir=self.runtime_dir) as temp:
            temp = Path(temp)
            work = temp / "work"
            work.mkdir()
            env = {"GIT_INDEX_FILE": str(temp / "index"), "GIT_WORK_TREE": str(work)}
            self._git("read-tree", "--empty", env=env)
            names = sorted(files)
            paths = []
            for number, name in enumerate(names):
                # Numeric staging names decouple raw hashing from user filenames,
                # attributes, and line-oriented hash-object input framing.
                target = work / str(number)
                target.write_bytes(files[name])
                encoded = os.fsencode(target)
                paths.append(b'"' + b"".join(("\\%03o" % byte).encode() for byte in encoded) + b'"\n')
            if names:
                object_ids = self._git("hash-object", "-w", "--no-filters", "--stdin-paths",
                                       data=b"".join(paths), env=env).stdout.splitlines()
                if len(object_ids) != len(names) or any(not re.fullmatch(b"[0-9a-f]{40}", oid) for oid in object_ids):
                    raise StoreError("Invalid Git hash-object batch response")
                index = b"".join(b"100644 " + oid + b"\t" + name.encode("utf-8") + b"\0"
                                 for name, oid in zip(names, object_ids))
                self._git("update-index", "-z", "--index-info", data=index, env=env)
            tree = self._git("write-tree", env=env).stdout.decode().strip()
            args = ["commit-tree", tree]
            if base:
                args.extend(("-p", base))
            return self._git(*args, data=b"EKK snapshot\n").stdout.decode().strip()

    def _actual(self, name):
        target = self._path(name)
        if target.exists() and not target.is_file():
            raise DirtyWorkingTree("Expected a regular file: " + name)
        return target.read_bytes() if target.exists() else None

    def _check_clean(self, old, new):
        for name in old.keys() | new.keys():
            if self._actual(name) != old.get(name):
                raise DirtyWorkingTree("External working-tree change: " + name)
        head = self._head()
        if not self._index_matches(head):
            raise DirtyWorkingTree("External staged changes must be resolved first")

    def _checkpoint(self, stage):
        """Fault-injection seam; production performs no action."""

    def _save(self, path, journal):
        _atomic(path, json.dumps(journal, sort_keys=True).encode())

    def _finish(self, path, journal):
        old = self._read_commit(journal["base"])["files"] if journal["base"] else {}
        new = self._read_commit(journal["revision"])["files"]
        current = self._head()
        if current not in (journal["base"], journal["revision"]):
            raise RecoveryConflict("Published snapshot diverged from pending operation")
        if current == journal["base"]:
            self._check_clean(old, new)
            result = self._git("update-ref", self.publication_ref, journal["revision"], journal["base"] or "0" * 40, check=False)
            if result.returncode:
                raise Conflict("Published snapshot changed during CAS")
            self._observed_receipt(journal['receipt'], replayed=False)
            self._checkpoint("published")
        else:
            self._observed_receipt(journal['receipt'], replayed=True)
        if not any(self._index_matches(revision) for revision in (journal["base"], journal["revision"])):
            raise RecoveryConflict("External staged changes block recovery")
        if self._head() != journal["revision"]:
            raise RecoveryConflict("Published snapshot changed after CAS")
        # Preflight the entire projection before changing any file. Recovery accepts
        # only exact before/after bytes, never an unrelated editor's new contents.
        for name in old.keys() | new.keys():
            if self._actual(name) not in (old.get(name), new.get(name)):
                raise RecoveryConflict("External change blocks projection recovery: " + name)
        for name in sorted(old.keys() | new.keys()):
            before, after = old.get(name), new.get(name)
            actual = self._actual(name)
            if actual == after:
                continue
            if actual != before:
                raise RecoveryConflict("External change during projection: " + name)
            target = self._path(name)
            if after is None:
                target.unlink()
                fd = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            else:
                _atomic(target, after)
            self._checkpoint("projected:" + name)
        # Keep the ordinary index usable without ever using it for staging.
        if self._head() != journal["revision"]:
            raise RecoveryConflict("Published snapshot changed during projection")
        self._sync_index(journal["revision"])
        if self._head() != journal["revision"]:
            raise RecoveryConflict("Published snapshot changed before completion")
        journal["state"] = "complete"
        self._save(path, journal)
        self._checkpoint("complete")
        return journal["receipt"]

    def _recover(self, *, full=True):
        """Complete interrupted operations after verifying their durable evidence.

        Every pass compares each runtime journal with the immutable operation
        evidence in Git, so no file in the runtime directory vouches for another.
        A full pass also audits the trees and the bytes of every historical
        snapshot. A write uses ``full=False``: for operations that an earlier
        pass audited, and whose ref and runtime journal are unchanged, only that
        tree and blob audit is skipped. Explicit recovery, restore activation
        and a missing or foreign checkpoint audit everything.

        With ``full=False`` the working tree is compared with the head
        projection only when a journal was reconstructed. A new write checks the
        tree against its own base in ``apply``; a replay or ``lookup`` reports
        the recorded publication and does not vouch for the working tree.
        """
        with self._reading_durable_state():
            return self._recover_durable_state(full)

    def _verified_path(self):
        return self.runtime_dir / "verified-operations.json"

    def _verifier(self):
        # Verification rules live in the store adapters; a change re-audits history.
        sources = [Path(__file__), Path(__file__).with_name("contained_store.py")]
        return digest(b"\0".join(path.read_bytes() for path in sources if path.is_file()))

    def _load_checkpoint(self):
        """The audit checkpoint of this store and verifier, or None."""
        path = self._verified_path()
        try:
            if path.is_symlink() or not path.is_file():
                return None
            value = json.loads(path.read_text())
            if (not isinstance(value, dict) or value.get("schema") != "ekk.verified-operations/0.2"
                    or value.get("store") != str(self.path) or value.get("verifier") != self._verifier()
                    or not isinstance(value.get("operations"), dict)
                    or datetime.fromisoformat(value.get("audited_at")).tzinfo is None):
                return None
            return value
        except (OSError, TypeError, ValueError):
            return None

    def _load_verified(self):
        checkpoint = self._load_checkpoint()
        if checkpoint is None:
            return {}
        return {key: row for key, row in checkpoint["operations"].items()
                if isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ("evidence", "revision", "journal"))}

    def _save_verified(self, operations, audited_at):
        _atomic(self._verified_path(), json.dumps({
            "schema": "ekk.verified-operations/0.2", "store": str(self.path), "verifier": self._verifier(),
            "audited_at": audited_at, "operations": operations}, sort_keys=True).encode())

    def _forget_verified(self):
        """Durably remove the checkpoint, so that the next pass audits everything."""
        path = self._verified_path()
        if path.is_symlink() or path.exists():
            path.unlink()
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def audit_due(self, days=7):
        """Whether the last successful full audit of operation evidence is missing or old.

        True without a checkpoint, with one written for another store or by
        other verifying code, and when its audit is older than ``days``.
        """
        checkpoint = self._load_checkpoint()
        if checkpoint is None:
            return True
        return datetime.now(timezone.utc) - datetime.fromisoformat(checkpoint["audited_at"]) >= timedelta(days=days)

    def _read_operation_journals(self, evidences):
        """``operation.json`` of every evidence commit, from one Git process.

        Absent, non-blob and unparsable evidence is None: its operation then
        takes the complete verification, which reports the failure.
        """
        names = list(dict.fromkeys(evidences))
        journals = dict.fromkeys(names)
        if not names:
            return journals
        batch = self._git("cat-file", "--batch",
                          data=b"".join((name + ":operation.json\n").encode() for name in names)).stdout
        offset = 0
        for name in names:
            end = batch.find(b"\n", offset)
            header = batch[offset:end].split() if end >= 0 else []
            offset = end + 1
            if len(header) == 2 and header[1] == b"missing":
                continue
            if len(header) != 3 or not re.fullmatch(rb"[0-9a-f]{40}", header[0]) or not header[2].isdigit():
                raise StoreError("Invalid Git operation evidence batch response")
            size = int(header[2])
            if batch[offset + size:offset + size + 1] != b"\n":
                raise StoreError("Truncated Git operation evidence batch response")
            if header[1] == b"blob":
                try:
                    value = json.loads(batch[offset:offset + size])
                except ValueError:
                    value = None
                journals[name] = value if isinstance(value, dict) else None
            offset += size + 1
        if offset != len(batch):
            raise StoreError("Unexpected bytes after Git operation evidence batch")
        return journals

    @staticmethod
    def _evidence_binds(journal, key_hash):
        """What recorded evidence states about itself; needs no further Git read."""
        receipt, request = journal["receipt"], journal["request"]
        return (journal["state"] == "prepared" and receipt["revision"] == journal["revision"]
                and receipt["idempotency_key_digest"] == key_hash
                and receipt["base"] == journal["base"]
                and request["base"] == journal["base"]
                and request["principal"] == receipt["principal"]
                and request["policy_digest"] == receipt["policy_digest"]
                and digest(json.dumps(request, sort_keys=True).encode()) == journal["request_digest"]
                and bool(re.fullmatch(r"[0-9a-f]{64}", journal["request_digest"])))

    @staticmethod
    def _receipt_fields(journal):
        receipt = journal["receipt"]
        return (receipt["state"] == "published" and isinstance(receipt["principal"], str) and bool(receipt["principal"])
                and isinstance(journal["request"]["changes"], dict)
                and isinstance(receipt["policy_digest"], str)
                and (journal["base"] is None or bool(re.fullmatch(r"[0-9a-f]{64}", receipt["policy_digest"])))
                and datetime.fromisoformat(receipt["recorded_at"]).tzinfo is not None)

    def _audited_before(self, earlier, evidence, recorded, path, key_hash):
        """Whether only the tree and blob audit of this operation may be skipped.

        The checkpoint row names the audited evidence commit and target. The
        completed runtime journal is still compared with that evidence, read
        from Git in this pass; a row cannot make a changed journal acceptable.
        """
        if not earlier or earlier["evidence"] != evidence or not isinstance(recorded, dict) or not path.is_file():
            return False
        raw = path.read_bytes()
        if digest(raw) != earlier["journal"]:
            return False
        try:
            runtime = json.loads(raw)
            return (isinstance(runtime, dict) and runtime.get("state") == "complete"
                    and runtime | {"state": "prepared"} == recorded
                    and recorded["revision"] == earlier["revision"]
                    and self._evidence_binds(recorded, key_hash) and self._receipt_fields(recorded))
        except (KeyError, TypeError, ValueError):
            return False

    def _recover_durable_state(self, full=True):
        receipts = []
        checkpoint = None if full else self._load_checkpoint()
        try:
            verified, refs, reconstructed, completed_projection = self._verify_operations(
                {} if checkpoint is None else self._load_verified())
        except DirtyWorkingTree:
            raise
        except StoreError:
            # The audit refused this operation evidence. A checkpoint from an
            # earlier pass must not keep vouching for it: without one, every
            # write audits in full and refuses until an explicit recovery passes.
            if full:
                self._forget_verified()
            raise
        known_keys = {line.split()[0].rsplit("/", 1)[-1] for line in refs}
        journals = sorted((self.runtime_dir / "journals").glob("*.json"))
        if any(path.stem not in known_keys for path in journals):
            raise RecoveryConflict("Runtime journal has no immutable operation evidence")
        # Every operation was audited when no checkpoint was used. The audit is
        # recorded now: a projection blocked by an external edit, or the
        # working-tree comparison below, is not part of it and must not repeat it.
        if checkpoint is None:
            self._save_verified(verified, datetime.now(timezone.utc).isoformat())
        elif verified != self._load_verified():
            self._save_verified(verified, checkpoint["audited_at"])
        for path in journals:
            if path.is_symlink():
                raise StoreError("Invalid journal path")
            journal = json.loads(path.read_text())
            if journal["state"] != "complete":
                from .operation_diagnostics import observe_recovery
                receipts.append(observe_recovery(lambda: self._finish(path, journal), journal['receipt']))
                completed_projection = None
        if reconstructed and self._head():
            completed_projection = self._head()
        if completed_projection is not None and (full or reconstructed):
            # A new write checks the working tree against its own base instead;
            # a replay reports the recorded publication only.
            files = self._read_commit(completed_projection)["files"]
            self._check_clean(files, files)
        return receipts

    def _verify_operations(self, known):
        """Verify every operation ref; ``known`` rows skip only the tree and blob audit."""
        reconstructed = False
        completed_projection = None
        trees, blob_digests = {}, {}
        verified = {}
        ancestry = {}

        def published(revision, head):
            # One fresh history read per head; identical to merge-base --is-ancestor.
            if head not in ancestry:
                ancestry[head] = frozenset(self._git("rev-list", head).stdout.decode().split())
            return revision in ancestry[head]

        def verified_tree(revision):
            if revision is None:
                return {}
            if revision not in trees:
                tree = self._read_tree(revision)
                # Read every historical blob, including deleted baseline files,
                # once per recovery. Cache only derived digests, never authority
                # across calls or full copies of every historical snapshot.
                missing = (oid for oid in tree.values() if oid not in blob_digests)
                for oid, raw in self._read_blobs(missing).items():
                    blob_digests[oid] = digest(raw)
                trees[revision] = tree
            return trees[revision]
        # Git retains request/receipt evidence independently of runtime journals.
        # A ref created before the journal write is also a recoverable operation.
        refs = self._git("for-each-ref", "--format=%(refname) %(objectname)", self.operations_ref).stdout.decode().splitlines()
        recorded = self._read_operation_journals(line.split()[1] for line in refs)
        # Cooperating writers hold the lock, and nothing below moves the head.
        current = self._head()
        for line in refs:
            ref, evidence = line.split()
            key_hash = ref.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[0-9a-f]{64}", key_hash):
                raise RecoveryConflict("Unrecognized operation ref")
            path = self.runtime_dir / "journals" / (key_hash + ".json")
            if path.is_symlink():
                raise StoreError("Invalid journal path")
            earlier = known.get(key_hash)
            if self._audited_before(earlier, evidence, recorded[evidence], path, key_hash):
                # Audited before with this evidence; the journal still equals it.
                if not current or not published(earlier["revision"], current):
                    raise RecoveryConflict("Runtime journal does not match durable operation evidence")
                verified[key_hash] = earlier
                continue
            try:
                journal = json.loads(self._read_evidence(evidence)["files"]["operation.json"])
                revision = journal["revision"]
                if (not self._evidence_binds(journal, key_hash)
                        or list(self._parents(revision)) != ([journal["base"]] if journal["base"] else [])
                        or list(self._parents(evidence)) != [revision]):
                    raise ValueError("Invalid operation evidence")
            except (KeyError, TypeError, ValueError) as exc:
                raise RecoveryConflict("Operation ref lacks valid durable recovery evidence") from exc
            request = journal["request"]
            try:
                if not self._receipt_fields(journal):
                    raise ValueError("Invalid receipt fields")
                before = verified_tree(journal["base"])
                after = verified_tree(revision)
                expected = dict(before)
                for name, content_digest in request["changes"].items():
                    self._path(name, inspect=False)
                    if content_digest is None:
                        expected.pop(name, None)
                    elif not isinstance(content_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", content_digest) or name not in after or blob_digests[after[name]] != content_digest:
                        raise ValueError("Request content digest does not match target")
                    else:
                        expected[name] = after[name]
                if expected != after:
                    raise ValueError("Target contains changes outside the recorded request")
            except (KeyError, TypeError, ValueError) as exc:
                raise RecoveryConflict("Operation evidence does not match its target snapshot") from exc
            if path.exists():
                try:
                    runtime = json.loads(path.read_text())
                    if not isinstance(runtime, dict) or runtime.get("state") not in ("prepared", "complete") or runtime | {"state": "prepared"} != journal:
                        raise ValueError("Runtime journal differs from immutable evidence")
                    if runtime["state"] == "complete" and (not current or not published(revision, current)):
                        raise ValueError("Completed operation is not in published history")
                    if runtime["state"] == "complete" and revision == current:
                        completed_projection = revision
                    if runtime["state"] == "complete":
                        verified[key_hash] = {"evidence": evidence, "revision": revision, "journal": digest(path.read_bytes())}
                except (TypeError, ValueError) as exc:
                    raise RecoveryConflict("Runtime journal does not match durable operation evidence") from exc
                continue
            if current and current != revision and published(revision, current):
                # Historical publication is proven by ancestry. Do not replay an
                # old projection over a later snapshot; verify the current view below.
                journal["state"] = "complete"
            self._save(path, journal)
            reconstructed = True
        return verified, refs, reconstructed, completed_projection

    def recover(self):
        """Explicit recovery: the full audit, then the working-tree projection check."""
        with self._lock():
            return self._recover()

    def initialize(self, files):
        self._validate_files(files)
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            self._git("init", "--quiet")
        with self._lock():
            self._recover()
            if self._head():
                raise Conflict("Store is already initialized")
            if self._git("rev-parse", "--verify", "HEAD", check=False).returncode == 0:
                raise Conflict("Initialization requires an empty Git repository")
            self._check_clean({}, files)
            self._git("symbolic-ref", "HEAD", self.publication_ref)
            self._publish(files, files, base=None, key="initialize", principal="local-owner", policy_digest="")
            return self.snapshot()

    def _request(self, changes, base, principal, policy_digest):
        return {"base": base, "principal": principal, "policy_digest": policy_digest,
                "changes": {name: digest(value) if value is not None else None for name, value in sorted(changes.items())}}

    def lookup(self, changes, *, base, idempotency_key, principal, policy_digest):
        """Return a prior exact request after the application rechecks authority.

        The receipt reports the recorded publication, still present in published
        history. It says nothing about the working-tree projection: new writes
        and explicit recovery check that.
        """
        self._validate_files(changes, deletes=True)
        if not all(isinstance(v, str) and v for v in (base, idempotency_key, principal, policy_digest)):
            raise ValidationError("base, idempotency_key, principal and policy_digest are required")
        if not re.fullmatch(r"[0-9a-f]{64}", policy_digest):
            raise ValidationError("policy_digest must be a SHA-256 hex digest")
        with self._lock():
            self._recover(full=False)
            path = self.runtime_dir / "journals" / (digest(idempotency_key.encode()) + ".json")
            if not path.exists():
                return None
            journal = json.loads(path.read_text())
            request = self._request(changes, base, principal, policy_digest)
            if journal["request_digest"] != digest(json.dumps(request, sort_keys=True).encode()):
                raise IdempotencyConflict("Idempotency key is bound to different content or authority")
            return self._observed_receipt(journal["receipt"] | {"idempotency_key": idempotency_key}, replayed=True)

    @staticmethod
    def _observed_receipt(receipt, *, replayed):
        # This owning publication path can distinguish replay from a new write.
        # A diagnostic dependency must never discard a confirmed domain receipt.
        try:
            from .operation_diagnostics import note_publication
            note_publication(receipt, replayed=replayed)
        except Exception:
            pass
        return receipt

    def _publish(self, files, changes, *, base, key, principal, policy_digest):
        request = self._request(changes, base, principal, policy_digest)
        request_digest = digest(json.dumps(request, sort_keys=True).encode())
        path = self.runtime_dir / "journals" / (digest(key.encode()) + ".json")
        if path.exists():
            journal = json.loads(path.read_text())
            if journal["request_digest"] != request_digest:
                raise IdempotencyConflict("Idempotency key is bound to different content or authority")
            receipt = journal["receipt"] if journal["state"] == "complete" else self._finish(path, journal)
            return self._observed_receipt(receipt | {"idempotency_key": key}, replayed=True)
        revision = self._commit(files, base)
        receipt = {"base": base, "revision": revision, "idempotency_key_digest": digest(key.encode()),
                   "principal": principal, "policy_digest": policy_digest,
                   "recorded_at": datetime.now(timezone.utc).isoformat(), "state": "published"}
        journal = {"state": "prepared", "base": base, "revision": revision,
                   "request_digest": request_digest, "request": request, "receipt": receipt}
        evidence = self._commit_evidence({"operation.json": json.dumps(journal, sort_keys=True).encode()}, revision)
        self._git("update-ref", self.operations_ref + digest(key.encode()), evidence, "0" * 40)
        self._checkpoint("recorded")
        self._save(path, journal)
        self._checkpoint("prepared")
        return self._observed_receipt(self._finish(path, journal) | {"idempotency_key": key}, replayed=False)

    def apply(self, changes, *, base, idempotency_key, principal, policy_digest):
        """Publish ``changes`` on exactly ``base``, or replay the receipt of this key.

        A new write requires a working tree and index equal to ``base``. A
        replay of an already recorded key returns its receipt without reading
        the working tree; explicit recovery and the next new write check it.
        """
        self._validate_files(changes, deletes=True)
        if not all(isinstance(v, str) and v for v in (base, idempotency_key, principal, policy_digest)):
            raise ValidationError("base, idempotency_key, principal and policy_digest are required")
        if not re.fullmatch(r"[0-9a-f]{64}", policy_digest):
            raise ValidationError("policy_digest must be a SHA-256 hex digest")
        with self._lock():
            self._recover(full=False)
            old = self.snapshot(base)["files"]
            files = dict(old)
            for name, value in changes.items():
                if value is None:
                    files.pop(name, None)
                else:
                    files[name] = value
            self._validate_files(files)
            journal = self.runtime_dir / "journals" / (digest(idempotency_key.encode()) + ".json")
            if not journal.exists():
                if self._head() != base:
                    raise Conflict("Base snapshot is stale")
                self._check_clean(old, files)
            return self._publish(files, changes, base=base, key=idempotency_key,
                                 principal=principal, policy_digest=policy_digest)
