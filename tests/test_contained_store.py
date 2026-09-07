"""Contained realms use ordinary outer commits and never stage unrelated work."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ekk.adapters.contained_store import ContainedGitStore
from ekk.adapters.git_store import GitStore
from ekk.model import Conflict, DirtyWorkingTree, RecoveryConflict, StoreError, ValidationError, digest


class ContainedGitStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve() / "project"
        self.repo.mkdir()
        self.realm = self.repo / "knowledge"
        self.realm.mkdir()
        self.runtime = Path(self.temp.name).resolve() / "runtime"
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@localhost")
        (self.repo / "code.py").write_bytes(b"original code\n")
        (self.realm / "note.md").write_bytes(b"one")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Reviewed baseline")
        self.base = self.git("rev-parse", "HEAD").decode().strip()
        self.store = self.make_store()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def make_store(self):
        return ContainedGitStore(self.realm, self.repo, "refs/heads/main", self.runtime)

    def apply(self, changes=None, base=None, key="change"):
        return self.store.apply(changes or {"note.md": b"two"}, base=base or self.base,
                                idempotency_key=key, principal="owner", policy_digest=digest(b"policy-v1"))

    def test_normal_outer_history_contains_real_blobs(self):
        receipt = self.apply()
        revision = receipt["revision"]
        self.assertEqual(revision, self.git("rev-parse", "HEAD").decode().strip())
        self.assertEqual(self.base, self.git("rev-parse", "HEAD^").decode().strip())
        self.assertEqual(b"two", self.git("show", "HEAD:knowledge/note.md"))
        self.assertEqual(b"original code\n", self.git("show", "HEAD:code.py"))
        self.assertIn(b"040000 tree", self.git("ls-tree", "HEAD", "knowledge"))
        self.assertFalse((self.realm / ".git").exists())
        self.assertEqual({"note.md": b"one"}, self.store.snapshot(self.base)["files"])
        self.assertEqual({"note.md": b"two"}, self.store.snapshot()["files"])
        self.assertEqual([revision, self.base], self.store.history())
        self.assertEqual(receipt, self.apply())

    def test_preserves_unrelated_staged_and_unstaged_changes(self):
        (self.repo / "code.py").write_bytes(b"staged code\n")
        (self.repo / "new.py").write_bytes(b"staged new\n")
        self.git("add", "code.py", "new.py")
        staged = self.git("ls-files", "--stage", "-z", "--", "code.py", "new.py")
        (self.repo / "code.py").write_bytes(b"unstaged code\n")
        self.apply()
        self.assertEqual(staged, self.git("ls-files", "--stage", "-z", "--", "code.py", "new.py"))
        self.assertEqual(b"unstaged code\n", (self.repo / "code.py").read_bytes())
        self.assertEqual(b"original code\n", self.git("show", "HEAD:code.py"))
        self.assertEqual(b"", self.git("diff", "--cached", "--", "knowledge"))

    def test_preserves_unrelated_symlink_and_executable_modes(self):
        (self.repo / "link").symlink_to("code.py")
        (self.repo / "run.sh").write_bytes(b"#!/bin/sh\n")
        (self.repo / "run.sh").chmod(0o755)
        self.git("add", "link", "run.sh")
        self.git("commit", "--quiet", "-m", "Code assets")
        base = self.git("rev-parse", "HEAD").decode().strip()
        before = self.git("ls-tree", "HEAD", "link", "run.sh")
        self.apply(base=base)
        self.assertEqual(before, self.git("ls-tree", "HEAD", "link", "run.sh"))

    def test_concurrent_code_commit_invalidates_outer_base(self):
        (self.repo / "code.py").write_bytes(b"new code\n")
        self.git("add", "code.py")
        self.git("commit", "--quiet", "-m", "Code changed")
        with self.assertRaises(Conflict):
            self.apply()
        self.assertEqual(b"one", (self.realm / "note.md").read_bytes())

    def test_code_commit_between_preparation_and_cas_is_preserved(self):
        def concurrent(stage):
            if stage == "prepared":
                (self.repo / "code.py").write_bytes(b"concurrent code\n")
                self.git("add", "code.py")
                self.git("commit", "--quiet", "-m", "Concurrent code")
        self.store._checkpoint = concurrent
        with self.assertRaises(Conflict):
            self.apply()
        self.assertEqual(b"concurrent code\n", self.git("show", "HEAD:code.py"))
        self.assertEqual(b"one", self.git("show", "HEAD:knowledge/note.md"))

    def test_crash_recovery_only_projects_managed_prefix(self):
        for stage in ("recorded", "prepared", "published", "projected:note.md", "complete"):
            with self.subTest(stage=stage):
                # Each iteration is an independent operation on the last snapshot.
                base = self.store.snapshot()["revision"]
                (self.repo / "code.py").write_bytes(stage.encode())
                self.git("add", "code.py")
                staged = self.git("ls-files", "--stage", "-z", "--", "code.py")
                def crash(point):
                    if point == stage:
                        raise RuntimeError("simulated interruption")
                self.store._checkpoint = crash
                with self.assertRaises(RuntimeError):
                    self.apply({"note.md": stage.encode()}, base=base, key=stage)
                self.store = self.make_store()
                self.store.recover()
                self.assertEqual(stage.encode(), (self.realm / "note.md").read_bytes())
                self.assertEqual(stage.encode(), (self.repo / "code.py").read_bytes())
                self.assertEqual(staged, self.git("ls-files", "--stage", "-z", "--", "code.py"))
                self.assertEqual(b"original code\n", self.git("show", "HEAD:code.py"))

    def test_managed_staged_or_editor_changes_are_rejected(self):
        (self.realm / "note.md").write_bytes(b"human")
        self.git("add", "knowledge/note.md")
        (self.realm / "note.md").write_bytes(b"one")
        with self.assertRaises(DirtyWorkingTree):
            self.apply()
        self.assertEqual(b"human", self.git("show", ":knowledge/note.md"))

    def test_recovery_does_not_overwrite_managed_external_edit(self):
        def crash(stage):
            if stage == "published":
                raise RuntimeError("crash")
        self.store._checkpoint = crash
        with self.assertRaises(RuntimeError):
            self.apply()
        (self.realm / "note.md").write_bytes(b"human")
        with self.assertRaises(RecoveryConflict):
            self.make_store().recover()
        self.assertEqual(b"human", (self.realm / "note.md").read_bytes())

    def test_configuration_refuses_wrong_branch_nested_git_and_unborn(self):
        self.git("branch", "other")
        with self.assertRaises(StoreError):
            ContainedGitStore(self.realm, self.repo, "refs/heads/other", self.runtime)
        with self.assertRaises(ValidationError):
            ContainedGitStore(self.repo, self.repo, "refs/heads/main", self.runtime)
        (self.realm / ".git").mkdir()
        with self.assertRaises(StoreError):
            self.make_store()
        (self.realm / ".git").rmdir()
        other = Path(self.temp.name).resolve() / "unborn"
        other.mkdir()
        subprocess.run(["git", "-C", str(other), "init", "--quiet", "--initial-branch=main"], check=True)
        with self.assertRaises(StoreError):
            ContainedGitStore(other / "knowledge", other, "refs/heads/main", self.runtime)

    def test_untracked_prefix_file_collision_is_preserved(self):
        (self.realm / "new.md").write_bytes(b"human")
        with self.assertRaises(DirtyWorkingTree):
            self.apply({"new.md": b"agent"})
        self.assertEqual(b"human", (self.realm / "new.md").read_bytes())

    def test_missing_and_empty_prefix_and_literal_prefix_names(self):
        self.realm = self.repo / "nested" / "knowledge[1]"
        self.runtime = Path(self.temp.name).resolve() / "different-runtime"
        self.store = self.make_store()
        self.assertEqual({}, self.store.snapshot()["files"])
        raw_name = "records/line\nwith\ttab.md"
        raw = b"binary\x00\xff\r\n"
        first = self.apply({raw_name: raw})
        self.assertEqual({raw_name: raw}, self.store.snapshot()["files"])
        self.assertEqual(raw, (self.realm / raw_name).read_bytes())
        self.apply({raw_name: None}, base=first["revision"], key="remove")
        self.assertEqual({}, self.store.snapshot()["files"])
        self.assertEqual(b"one", self.git("show", "HEAD:knowledge/note.md"))

    def test_lost_runtime_journal_is_reconstructed_without_code_projection(self):
        def crash(stage):
            if stage == "published":
                raise RuntimeError("crash")
        self.store._checkpoint = crash
        with self.assertRaises(RuntimeError):
            self.apply()
        for journal in (self.runtime / "journals").glob("*.json"):
            journal.unlink()
        (self.repo / "code.py").write_bytes(b"human staged during crash\n")
        self.git("add", "code.py")
        self.store = self.make_store()
        self.store.recover()
        self.assertEqual(b"two", (self.realm / "note.md").read_bytes())
        self.assertEqual(b"human staged during crash\n", self.git("show", ":code.py"))
        self.assertEqual(b"original code\n", self.git("show", "HEAD:code.py"))
        self.assertEqual(self.store.snapshot()["revision"], self.apply()["revision"])

    def test_staging_during_projection_preserves_unrelated_index_entries(self):
        def stage_code(stage):
            if stage == "projected:note.md":
                (self.repo / "code.py").write_bytes(b"newly staged\n")
                self.git("add", "code.py")
        self.store._checkpoint = stage_code
        self.apply()
        self.assertEqual(b"newly staged\n", self.git("show", ":code.py"))
        self.assertEqual(b"original code\n", self.git("show", "HEAD:code.py"))

    def test_staging_managed_content_during_projection_is_preserved_and_blocks(self):
        def stage_realm(stage):
            if stage == "projected:note.md":
                (self.realm / "note.md").write_bytes(b"human staged")
                self.git("add", "knowledge/note.md")
        self.store._checkpoint = stage_realm
        with self.assertRaises(RecoveryConflict):
            self.apply()
        self.assertEqual(b"human staged", self.git("show", ":knowledge/note.md"))
        self.assertEqual(b"human staged", (self.realm / "note.md").read_bytes())

    def test_existing_index_lock_is_not_removed_and_operation_can_recover(self):
        lock = self.repo / ".git/index.lock"
        lock.write_bytes(b"another Git operation")
        with self.assertRaises(RecoveryConflict):
            self.apply()
        self.assertEqual(b"another Git operation", lock.read_bytes())
        lock.unlink()
        self.store.recover()
        self.assertEqual(b"", self.git("diff", "--cached", "--", "knowledge"))

    def test_recovery_rejects_evidence_with_changes_outside_prefix(self):
        self.apply()
        ref = self.store.operations_ref + digest(b"change")
        evidence = self.git("rev-parse", ref).decode().strip()
        journal = json.loads(GitStore._read_evidence(self.store, evidence)["files"]["operation.json"])
        forged = GitStore._commit(self.store, {"knowledge/note.md": b"two", "code.py": b"unrelated mutation"}, self.base)
        journal["revision"] = journal["receipt"]["revision"] = forged
        forged_evidence = self.store._commit_evidence({"operation.json": json.dumps(journal, sort_keys=True).encode()}, forged)
        self.git("update-ref", ref, forged_evidence, evidence)
        (self.runtime / "journals" / (digest(b"change") + ".json")).unlink()
        with self.assertRaises(RecoveryConflict):
            self.store.recover()
        self.assertEqual(b"original code\n", (self.repo / "code.py").read_bytes())

    def copy_store(self, name="copy"):
        copy = Path(self.temp.name).resolve() / name
        shutil.copytree(self.repo, copy, symlinks=True)
        return copy, Path(self.temp.name).resolve() / (name + "-runtime")

    def restore_copy(self, copy, runtime, **overrides):
        options = {"expected_previous_repository": self.repo, "expected_previous_realm": self.realm}
        options.update(overrides)
        return ContainedGitStore.rebind_runtime(copy / "knowledge", copy, "refs/heads/main", runtime, **options)

    def source_fingerprint(self):
        return {str(path): digest(path.read_bytes()) for root in (self.repo, self.runtime)
                for path in root.rglob("*") if path.is_file() and not path.is_symlink()}

    def test_relocated_copy_retains_retry_history_new_writes_and_source_bytes(self):
        receipt = self.apply()
        source_before = self.source_fingerprint()
        copy, runtime = self.copy_store()
        with self.assertRaises(StoreError):
            ContainedGitStore(copy / "knowledge", copy, "refs/heads/main", runtime)
        restored = self.restore_copy(copy, runtime)
        self.assertEqual(self.store.operations_ref, restored.operations_ref)
        retry = restored.apply({"note.md": b"two"}, base=self.base, idempotency_key="change",
                               principal="owner", policy_digest=digest(b"policy-v1"))
        self.assertEqual(receipt, retry)
        self.assertEqual(self.store.history(), restored.history())
        new = restored.apply({"note.md": b"copy only"}, base=receipt["revision"], idempotency_key="copy-write",
                             principal="owner", policy_digest=digest(b"policy-v1"))
        reopened = ContainedGitStore(copy / "knowledge", copy, "refs/heads/main", runtime)
        reopened.recover()
        self.assertEqual(self.store.operations_ref, reopened.operations_ref)
        self.assertEqual(new["revision"], reopened.snapshot()["revision"])
        self.assertEqual(b"copy only", (copy / "knowledge/note.md").read_bytes())
        self.assertEqual(source_before, self.source_fingerprint())
        self.assertEqual(b"two", (self.realm / "note.md").read_bytes())
        # Repeating the same explicit activation is harmless and keeps later work.
        self.assertEqual(new["revision"], self.restore_copy(copy, runtime).snapshot()["revision"])

    def test_restore_legacy_binding_without_portable_registration(self):
        self.apply()
        copy, runtime = self.copy_store()
        copied_registration = copy / self.store._registration.relative_to(self.repo)
        copied_registration.unlink()
        restored = self.restore_copy(copy, runtime)
        self.assertEqual(self.store.operations_ref, restored.operations_ref)
        self.assertEqual(b"two", restored.snapshot()["files"]["note.md"])

    def test_restore_refuses_wrong_owner_source_runtime_and_dirty_copy(self):
        self.apply()
        copy, runtime = self.copy_store()
        with self.assertRaises(StoreError):
            self.restore_copy(copy, runtime, expected_previous_repository=self.repo.parent / "wrong",
                              expected_previous_realm=self.repo.parent / "wrong/knowledge")
        with self.assertRaises(ValidationError):
            self.restore_copy(copy, self.runtime)
        with self.assertRaises(ValidationError):
            self.restore_copy(self.repo, runtime)
        (copy / "code.py").write_bytes(b"unreviewed copied edit")
        with self.assertRaises(RecoveryConflict):
            self.restore_copy(copy, runtime)
        self.assertFalse(runtime.exists())

    def test_restore_refuses_alternates_hardlinks_and_missing_operation_evidence(self):
        self.apply()
        copy, runtime = self.copy_store()
        alternates = copy / ".git/objects/info/alternates"
        alternates.write_text(str(self.repo / ".git/objects") + "\n")
        with self.assertRaises(StoreError):
            self.restore_copy(copy, runtime)
        alternates.unlink()
        target = copy / ".git/config"
        target.unlink()
        target.hardlink_to(self.repo / ".git/config")
        with self.assertRaises(StoreError):
            self.restore_copy(copy, runtime)
        target.unlink()
        shutil.copyfile(self.repo / ".git/config", target)
        subprocess.run(["git", "-C", str(copy), "update-ref", "-d",
                        self.store.operations_ref + digest(b"change")], check=True)
        with self.assertRaises(RecoveryConflict):
            self.restore_copy(copy, runtime)
        self.assertFalse(runtime.exists())

    def test_restore_revalidates_prefix_only_evidence_before_binding(self):
        self.apply()
        copy, runtime = self.copy_store()
        copied = ContainedGitStore.__new__(ContainedGitStore)
        copied._configure(copy / "knowledge", copy, "refs/heads/main", runtime, restoring=True)
        ref = copied.operations_ref + digest(b"change")
        evidence = copied._git("rev-parse", ref).stdout.decode().strip()
        journal = json.loads(GitStore._read_evidence(copied, evidence)["files"]["operation.json"])
        with tempfile.TemporaryDirectory() as temporary:
            copied.runtime_dir = Path(temporary).resolve()
            forged = GitStore._commit(copied, {"knowledge/note.md": b"two", "code.py": b"bad"}, self.base)
            journal["revision"] = journal["receipt"]["revision"] = forged
            forged_evidence = copied._commit_evidence({"operation.json": json.dumps(journal).encode()}, forged)
        copied._git("update-ref", ref, forged_evidence, evidence)
        with self.assertRaises(RecoveryConflict):
            self.restore_copy(copy, runtime)
        self.assertFalse(runtime.exists())


if __name__ == "__main__":
    unittest.main()
