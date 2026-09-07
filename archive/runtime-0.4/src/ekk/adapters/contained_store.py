"""A realm projected from a prefix of an explicitly selected outer Git branch.

Publication, receipts and recovery use GitStore's transaction implementation.
Only the tree and index projection differ. A reviewed outer baseline must exist;
this adapter never initializes or stages the surrounding project.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from ekk.adapters.git_store import GitStore, _atomic, _mkdir_durable
from ekk.model import RecoveryConflict, StoreError, ValidationError, digest


class ContainedGitStore(GitStore):
    def __init__(self, realm_path, repository_root, publication_ref, runtime_dir):
        self._configure(realm_path, repository_root, publication_ref, runtime_dir)

    def _configure(self, realm_path, repository_root, publication_ref, runtime_dir, *, restoring=False):
        self.path = Path(realm_path).absolute()
        self.repository_root = Path(repository_root).absolute()
        for path in (self.path, self.repository_root):
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise ValidationError("Contained store paths must not traverse symlinks")
        self.path = self.path.resolve()
        self.repository_root = self.repository_root.resolve()
        if self.repository_root not in self.path.parents:
            raise ValidationError("Contained realm must be a strict repository subdirectory")
        self.prefix = self.path.relative_to(self.repository_root).as_posix() + "/"
        self._pathspec = ":(literal)" + self.prefix.rstrip("/")
        # Validate the configured prefix with the same rules as record paths.
        self._path(self.prefix.rstrip("/"), inspect=False)
        if not isinstance(publication_ref, str) or not publication_ref.startswith("refs/heads/"):
            raise ValidationError("Contained publication requires an explicit branch ref")
        self.publication_ref = publication_ref
        self.git_dir = self.repository_root / ".git"
        if self.git_dir.is_symlink() or not self.git_dir.is_dir():
            raise StoreError("Contained storage requires an ordinary outer Git repository")
        if self._git("check-ref-format", publication_ref, check=False).returncode:
            raise ValidationError("Invalid publication branch ref")
        actual_root = Path(self._git("rev-parse", "--show-toplevel").stdout.decode().strip()).resolve()
        if actual_root != self.repository_root:
            raise StoreError("repository_root must identify the outer Git root")
        self._check_binding()
        if self._head() is None:
            raise StoreError("Contained storage requires a reviewed outer baseline commit")
        identity = json.dumps({"repository": str(self.repository_root), "realm": str(self.path),
                               "publication_ref": publication_ref}, sort_keys=True)
        self._identity = identity
        namespace = digest(identity.encode())
        selector = digest(json.dumps([self.prefix, publication_ref]).encode())
        self._registration = self.git_dir / "ekk-contained" / "realms" / (selector + ".json")
        registration = self._read_registration()
        if registration is not None:
            if (registration.get("prefix") != self.prefix or registration.get("publication_ref") != publication_ref
                    or not isinstance(registration.get("namespace"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", registration["namespace"])):
                raise StoreError("Invalid contained registration")
            if not restoring and (registration.get("owner") != identity or registration.get("state") != "validated"):
                raise StoreError("Copied contained store requires explicit recovery runtime activation")
            namespace = registration["namespace"]
        self._namespace = namespace
        self.operations_ref = "refs/ekk/contained/" + namespace + "/operations/"
        self._binding = self.git_dir / "ekk-contained" / namespace / "runtime"
        if self._binding.is_symlink():
            raise ValidationError("Runtime binding must not be a symlink")
        self.runtime_dir = Path(runtime_dir).absolute()
        if any(part.is_symlink() for part in (self.runtime_dir, *self.runtime_dir.parents)):
            raise ValidationError("Runtime path must not traverse symlinks")
        self.runtime_dir = self.runtime_dir.resolve()
        if self.runtime_dir == self.repository_root or self.repository_root in self.runtime_dir.parents:
            raise ValidationError("Runtime journals must be outside the outer repository")
        if not restoring and self._binding.exists() and self._binding.read_text() != str(self.runtime_dir):
            raise StoreError("Contained store already has a different runtime location")
        if not restoring and registration is None and not self._binding.exists():
            if any((self.git_dir / "ekk-contained").glob("*/runtime")):
                raise StoreError("Unknown contained binding; copied stores require explicit recovery activation")

    def _read_registration(self):
        if self._registration.is_symlink():
            raise StoreError("Invalid contained registration")
        if not self._registration.exists():
            return None
        try:
            registration = json.loads(self._registration.read_text())
            if not isinstance(registration, dict):
                raise ValueError()
            return registration
        except (ValueError, TypeError) as exc:
            raise StoreError("Invalid contained registration") from exc

    def _registration_data(self, *, state="validated", restoration=None):
        record = {"prefix": self.prefix, "publication_ref": self.publication_ref,
                  "namespace": self._namespace, "owner": self._identity,
                  "runtime_dir": str(self.runtime_dir), "state": state}
        if restoration is not None:
            record["restoration"] = restoration
        return record

    @classmethod
    def rebind_runtime(cls, realm_path, repository_root, publication_ref, runtime_dir, *,
                       expected_previous_repository, expected_previous_realm):
        """Activate only an isolated full copy, retaining its operation namespace.

        This neither retires the source writer nor changes project routing. The
        expected old identity must match copied registration/binding evidence.
        """
        clone = cls.__new__(cls)
        clone._configure(realm_path, repository_root, publication_ref, runtime_dir, restoring=True)
        previous_repo = Path(expected_previous_repository).absolute().resolve()
        previous_realm = Path(expected_previous_realm).absolute().resolve()
        if (previous_repo not in previous_realm.parents
                or previous_realm.relative_to(previous_repo).as_posix() + "/" != clone.prefix):
            raise ValidationError("Recovery requires the same contained prefix in the expected previous repository")
        if (clone.repository_root == previous_repo or previous_repo in clone.repository_root.parents
                or clone.repository_root in previous_repo.parents):
            raise ValidationError("Recovery copy must be separate from its previous repository")
        if clone.runtime_dir == previous_repo or previous_repo in clone.runtime_dir.parents:
            raise ValidationError("Recovery runtime must be outside the source repository")
        previous_identity = json.dumps({"repository": str(previous_repo), "realm": str(previous_realm),
                                       "publication_ref": publication_ref}, sort_keys=True)
        if (any((clone.git_dir / name).exists() for name in
                ("objects/info/alternates", "objects/info/http-alternates", "commondir", "shallow"))
                or any((clone.git_dir / "objects/pack").glob("*.promisor"))
                or clone._git("config", "--get", "extensions.partialClone", check=False).returncode == 0):
            raise StoreError("Recovery requires an independent full Git copy")
        for directory, directories, files in os.walk(clone.git_dir):
            for name in directories + files:
                item = Path(directory) / name
                if item.is_symlink() or (item.is_file() and item.stat().st_nlink > 1):
                    raise StoreError("Recovery Git metadata and objects must not be linked to another copy")
        lock = clone.git_dir / "ekk-writer.lock"
        with lock.open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            registration = clone._read_registration()
            restoration = registration.get("restoration") if registration else None
            resumed = (registration is not None and registration.get("owner") == clone._identity)
            if resumed:
                if (not isinstance(restoration, dict) or restoration.get("previous_owner") != previous_identity
                        or registration.get("runtime_dir") != str(clone.runtime_dir)
                        or registration.get("state") not in ("prepared", "validated")):
                    raise StoreError("Conflicting contained recovery activation request")
                previous_runtime = Path(restoration["previous_runtime"])
                if (clone._binding.is_symlink() or not clone._binding.is_file()
                        or clone._binding.read_text() not in (str(previous_runtime), str(clone.runtime_dir))):
                    raise StoreError("Copied runtime binding differs from pending recovery")
            else:
                if registration is not None and (registration.get("owner") != previous_identity
                                                or registration.get("state") != "validated"):
                    raise StoreError("Copied contained owner differs from the expected previous owner")
                if registration is None:
                    clone._namespace = digest(previous_identity.encode())
                    clone.operations_ref = "refs/ekk/contained/" + clone._namespace + "/operations/"
                    clone._binding = clone.git_dir / "ekk-contained" / clone._namespace / "runtime"
                if clone._binding.is_symlink() or not clone._binding.is_file():
                    raise StoreError("Copy lacks the expected previous contained runtime binding")
                previous_runtime = Path(clone._binding.read_text())
                if registration is not None and registration.get("runtime_dir") != str(previous_runtime):
                    raise StoreError("Copied contained runtime binding differs from its registration")
                restoration = {"previous_owner": previous_identity, "previous_runtime": str(previous_runtime),
                               "mode": "isolated_restore_drill", "source_writer_retirement": "externally_unproven",
                               "production_cutover": "not_performed"}
            if (clone.runtime_dir == previous_runtime or previous_runtime in clone.runtime_dir.parents
                    or clone.runtime_dir in previous_runtime.parents):
                raise ValidationError("Recovery requires a new independent runtime directory")
            source_binding = previous_repo / ".git/ekk-contained" / clone._namespace / "runtime"
            if source_binding.is_symlink() or (source_binding.is_file() and source_binding.read_text() != str(previous_runtime)):
                raise StoreError("Expected source binding differs from the copied binding")
            source_owner = previous_runtime / "store-path"
            if source_owner.is_symlink() or (source_owner.is_file() and source_owner.read_text() != previous_identity):
                raise StoreError("Expected previous runtime has a different owner")
            owner = clone.runtime_dir / "store-path"
            if owner.is_symlink():
                raise StoreError("Invalid recovery runtime owner")
            if clone.runtime_dir.exists():
                if not clone.runtime_dir.is_dir() or (any(clone.runtime_dir.iterdir())
                        and (not resumed or not owner.is_file() or owner.read_text() != clone._identity)):
                    raise StoreError("Recovery runtime must be empty or owned by this activation")
            # Validate the entire copied checkout, then let the existing journal
            # engine authenticate all retained operation evidence in scratch space.
            if clone._git("status", "--porcelain", "--untracked-files=all").stdout:
                raise RecoveryConflict("Recovery requires a clean copied outer checkout and index")
            current = clone.snapshot()["files"]
            clone._check_clean(current, current)
            if not clone._git("for-each-ref", "--format=%(refname)", clone.operations_ref).stdout:
                raise RecoveryConflict("Copy lacks contained operation evidence")
            if (previous_repo / ".git").is_dir():
                source_refs = clone._git("-C", str(previous_repo), "for-each-ref",
                                         "--format=%(refname) %(objectname)", clone.operations_ref).stdout.splitlines()
                copied_refs = clone._git("for-each-ref", "--format=%(refname) %(objectname)",
                                         clone.operations_ref).stdout.splitlines()
                if not set(source_refs).issubset(copied_refs):
                    raise RecoveryConflict("Copy is missing or changed previous contained operation refs")
            runtime = clone.runtime_dir
            with tempfile.TemporaryDirectory(prefix="ekk-contained-restore-check-") as temporary:
                clone.runtime_dir = Path(temporary).resolve()
                clone._recover()
            clone.runtime_dir = runtime
            prepared = clone._registration_data(state="prepared", restoration=restoration)
            _atomic(clone._registration, json.dumps(prepared, sort_keys=True).encode())
            _mkdir_durable(runtime)
            os.chmod(runtime, 0o700)
            if not owner.exists():
                _atomic(owner, clone._identity.encode(), replace=False)
            _atomic(clone._binding, str(runtime).encode())
            clone._recover()
            validated = clone._registration_data(restoration=restoration)
            _atomic(clone._registration, json.dumps(validated, sort_keys=True).encode())
        return clone

    def _check_binding(self):
        if self.git_dir.is_symlink() or not self.git_dir.is_dir():
            raise StoreError("Outer Git metadata changed")
        for directory in (self.path, *self.path.parents):
            if directory == self.repository_root:
                break
            if directory.is_symlink() or (directory / ".git").exists() or (directory / ".git").is_symlink():
                raise StoreError("Contained realm cannot traverse a nested Git repository or symlink")
        branch = self._git("symbolic-ref", "--quiet", "HEAD", check=False)
        if branch.returncode or branch.stdout.decode().strip() != self.publication_ref:
            raise StoreError("The selected publication branch must be checked out")

    @contextmanager
    def _lock(self):
        self._check_binding()
        lock = self.git_dir / "ekk-writer.lock"
        if lock.is_symlink():
            raise StoreError("Invalid writer lock")
        with lock.open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                self._check_binding()
                _mkdir_durable(self.runtime_dir)
                owner = self.runtime_dir / "store-path"
                if owner.is_symlink():
                    raise StoreError("Invalid runtime owner")
                if owner.exists() and owner.read_text() != self._identity:
                    raise StoreError("Runtime journal directory belongs to another store")
                if not owner.exists():
                    _atomic(owner, self._identity.encode())
                if self._binding.exists() and self._binding.read_text() != str(self.runtime_dir):
                    raise StoreError("Contained store already has a different runtime location")
                if not self._binding.exists():
                    _atomic(self._binding, str(self.runtime_dir).encode())
                registration = self._read_registration()
                if registration is not None and (registration.get("owner") != self._identity
                        or registration.get("state") != "validated"
                        or registration.get("runtime_dir") != str(self.runtime_dir)):
                    raise StoreError("Contained registration changed; explicit recovery activation required")
                if registration is None:
                    _atomic(self._registration, json.dumps(self._registration_data(), sort_keys=True).encode())
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def initialize(self, files):
        raise StoreError("Contained storage uses an existing reviewed baseline; publish with apply and its exact base")

    def _head(self):
        self._check_binding()
        return super()._head()

    def _read_commit(self, revision):
        entry = self._git("ls-tree", "-z", revision, "--", self._pathspec).stdout
        if not entry:
            return {"revision": revision, "files": {}}
        metadata, _ = entry.rstrip(b"\0").split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if mode != b"040000" or kind != b"tree":
            raise StoreError("Contained realm must be an ordinary Git tree, not a gitlink or file")
        snapshot = GitStore._read_commit(self, oid.decode())
        return {"revision": revision, "files": snapshot["files"]}

    def _read_evidence(self, revision):
        evidence = super()._read_evidence(revision)
        target = self._git("rev-parse", revision + "^").stdout.decode().strip()
        changed = self._git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                            target + "^", target).stdout.split(b"\0")
        if any(name and not name.startswith(self.prefix.encode("utf-8")) for name in changed):
            raise RecoveryConflict("Contained operation changes files outside its managed prefix")
        return evidence

    def _commit(self, files, base):
        if base is None:
            raise StoreError("Contained publication requires an outer baseline")
        # The shared byte-preserving builder produces the managed subtree. Its
        # temporary commit is never published as outer history.
        subtree = GitStore._commit(self, files, None)
        with tempfile.TemporaryDirectory(prefix="contained-tree-", dir=self.runtime_dir) as temp:
            env = {"GIT_INDEX_FILE": str(Path(temp) / "index")}
            self._git("read-tree", base, env=env)
            existing = self._git("ls-files", "-z", "--", self._pathspec, env=env).stdout.split(b"\0")
            removals = b"".join(b"0 " + b"0" * 40 + b"\t" + name + b"\0" for name in existing if name)
            if removals:
                self._git("update-index", "-z", "--index-info", data=removals, env=env)
            self._git("read-tree", "--prefix=" + self.prefix, subtree, env=env)
            tree = self._git("write-tree", env=env).stdout.decode().strip()
            return self._git("commit-tree", tree, "-p", base, data=b"EKK contained snapshot\n").stdout.decode().strip()

    def _tree_index_entries(self, revision):
        if revision is None:
            return b""
        entries = self._git("ls-tree", "-rz", revision, "--", self._pathspec).stdout
        result = []
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            mode, _, oid = metadata.split()
            result.append(mode + b" " + oid + b" 0\t" + name + b"\0")
        return b"".join(result)

    def _index_matches(self, revision):
        actual = self._git("ls-files", "--stage", "-z", "--", self._pathspec).stdout
        return actual == self._tree_index_entries(revision)

    def _sync_index(self, revision):
        # Lock the real index only for this final projection. External staging
        # before this point remains intact; concurrent normal Git staging fails
        # recoverably while the lock is held. Never read-tree over the full index.
        self._check_binding()
        index = self.git_dir / "index"
        lock = self.git_dir / "index.lock"
        if index.is_symlink():
            raise RecoveryConflict("Invalid outer index")
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise RecoveryConflict("Outer Git index is locked; retry recovery after its owner finishes") from exc
        installed = False
        try:
            with os.fdopen(fd, "wb") as stream:
                parent = self._git("rev-parse", revision + "^").stdout.decode().strip()
                if not (self._index_matches(parent) or self._index_matches(revision)):
                    raise RecoveryConflict("External staged realm changes block recovery")
                with tempfile.TemporaryDirectory(prefix="contained-index-", dir=self.runtime_dir) as temp:
                    private_index = Path(temp) / "index"
                    if index.exists():
                        private_index.write_bytes(index.read_bytes())
                    env = {"GIT_INDEX_FILE": str(private_index)}
                    existing = self._git("ls-files", "-z", "--", self._pathspec, env=env).stdout.split(b"\0")
                    updates = b"".join(b"0 " + b"0" * 40 + b"\t" + name + b"\0" for name in existing if name)
                    # --index-info accepts the stage-bearing format from ls-files.
                    updates += self._tree_index_entries(revision)
                    if updates:
                        self._git("update-index", "-z", "--index-info", data=updates, env=env)
                    elif not private_index.exists():
                        self._git("read-tree", "--empty", env=env)
                    if self._head() != revision:
                        raise RecoveryConflict("Outer branch changed during index projection")
                    stream.write(private_index.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(lock, index)
                installed = True
                directory = os.open(self.git_dir, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if not installed and lock.exists():
                lock.unlink()
