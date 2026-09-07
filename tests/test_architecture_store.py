import concurrent.futures
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ekk.adapters.git_store import GitStore
from ekk.model import Conflict, DirtyWorkingTree, IdempotencyConflict, RecoveryConflict, ValidationError, validate_envelope


class GitStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "realm"
        self.runtime = Path(self.temp.name) / "runtime"
        self.store = GitStore(self.path, self.runtime)
        self.base = self.store.initialize({"records/a.md": b"one", ".gitignore": b"views/\n"})["revision"]

    def apply(self, store=None, key="change", base=None, changes=None, principal="owner"):
        return (store or self.store).apply(changes or {"records/a.md": b"two"}, base=base or self.base,
            idempotency_key=key, principal=principal, policy_digest="a" * 64)

    def test_history_idempotency_and_restore(self):
        first = self.apply()
        self.assertEqual(first, self.apply())
        self.assertEqual(b"one", self.store.snapshot(self.base)["files"]["records/a.md"])
        self.assertEqual(b"two", (self.path / "records/a.md").read_bytes())
        with self.assertRaises(IdempotencyConflict):
            self.apply(principal="other")
        with self.assertRaises(IdempotencyConflict):
            self.apply(changes={"records/a.md": b"different"})
        restored = self.apply(base=first["revision"], key="restore", changes={"records/a.md": b"one"})
        self.assertNotEqual(restored["revision"], self.base)
        self.assertEqual(self.store.snapshot()["files"], self.store.snapshot(self.base)["files"])

    def test_two_writers_exact_base(self):
        def change(n):
            try:
                return self.apply(GitStore(self.path), key=str(n), changes={"records/" + str(n) + ".md": b"independent"})
            except Conflict:
                return "conflict"
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(change, [1, 2]))
        self.assertEqual(1, results.count("conflict"))

    def test_dirty_files_and_index_preserved(self):
        (self.path / "records/a.md").write_bytes(b"human")
        with self.assertRaises(DirtyWorkingTree):
            self.apply()
        self.assertEqual(self.base, self.store.snapshot()["revision"])
        subprocess.run(["git", "-C", str(self.path), "add", "records/a.md"], check=True)
        (self.path / "records/a.md").write_bytes(b"one")
        with self.assertRaises(DirtyWorkingTree):
            self.apply()

    def test_crash_recovery_each_stage(self):
        for stage in ("prepared", "published", "projected:records/a.md", "complete"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                store = GitStore(Path(temp) / "realm", Path(temp) / "runtime")
                base = store.initialize({"records/a.md": b"one"})["revision"]
                def crash(point):
                    if point == stage:
                        raise RuntimeError("simulated process failure")
                store._checkpoint = crash
                with self.assertRaises(RuntimeError):
                    self.apply(store, base=base)
                store = GitStore(store.path)
                store.recover()
                self.assertEqual(b"two", store.snapshot()["files"]["records/a.md"])
                self.assertEqual(b"two", (store.path / "records/a.md").read_bytes())
                self.assertEqual(store.snapshot()["revision"], self.apply(store, base=base)["revision"])

    def test_recovery_does_not_overwrite_external_edit(self):
        def crash(stage):
            if stage == "published":
                raise RuntimeError("crash")
        self.store._checkpoint = crash
        with self.assertRaises(RuntimeError):
            self.apply()
        (self.path / "records/a.md").write_bytes(b"human")
        with self.assertRaises(RecoveryConflict):
            GitStore(self.path).recover()
        self.assertEqual(b"human", (self.path / "records/a.md").read_bytes())
        self.assertEqual(b"two", self.store.snapshot()["files"]["records/a.md"])

    def test_traversal_symlink_and_other_runtime_rejected(self):
        for name in ("../outside", ".git/config", "records/../escape", "/absolute"):
            with self.assertRaises(ValidationError):
                self.apply(changes={name: b"bad"})
        (self.path / "link").symlink_to(Path(self.temp.name))
        with self.assertRaises(ValidationError):
            self.apply(changes={"link/outside": b"bad"})
        with self.assertRaises(ValueError):
            GitStore(self.path, Path(self.temp.name) / "another-runtime")

    def test_real_process_exit_recovery(self):
        script = """
import os, sys
from ekk.adapters.git_store import GitStore
store = GitStore(sys.argv[1])
store._checkpoint = lambda stage: os._exit(73) if stage == 'published' else None
store.apply({'records/a.md': b'two'}, base=sys.argv[2], idempotency_key='exit', principal='owner', policy_digest='a' * 64)
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.path), self.base])
        self.assertEqual(73, result.returncode)
        recovered = GitStore(self.path).recover()
        self.assertEqual(1, len(recovered))
        self.assertEqual(b"two", (self.path / "records/a.md").read_bytes())

    def test_external_ref_change_blocks_cas(self):
        other = None
        def change_ref(stage):
            nonlocal other
            if stage == "prepared":
                tree = self.store._git("rev-parse", self.base + "^{tree}").stdout.decode().strip()
                other = self.store._git("commit-tree", tree, "-p", self.base, data=b"external commit").stdout.decode().strip()
                self.store._git("update-ref", "refs/ekk/published", other, self.base)
        self.store._checkpoint = change_ref
        with self.assertRaises(RecoveryConflict):
            self.apply()
        self.assertEqual(other, self.store.snapshot()["revision"])
        self.assertEqual(b"one", (self.path / "records/a.md").read_bytes())

    def test_runtime_journals_cannot_be_shared_between_realms(self):
        other = GitStore(Path(self.temp.name) / "other", self.runtime)
        with self.assertRaises(ValueError):
            other.initialize({"a.md": b"other"})
        self.assertEqual(self.base, self.store.snapshot()["revision"])

    def test_batched_io_preserves_binary_paths_and_ignores_attributes(self):
        subprocess.run(["git", "-C", str(self.path), "config", "core.autocrlf", "true"], check=True)
        changes = {
            ".gitattributes": b"*.md text eol=lf\n",
            "records/space and таб.md": b"line\r\nnext\r\n",
            "records/line\nwith\ttab.md": b"blob\x00\xff\n123 blob 8\n",
            "records/-leading.md": b"",
            'records/"quote.md': b"same blob",
            "records/duplicate.md": b"same blob",
        }
        receipt = self.apply(changes=changes)
        for name, content in changes.items():
            self.assertEqual(content, self.store.snapshot(receipt["revision"])["files"][name])
            self.assertEqual(content, (self.path / name).read_bytes())

    def test_git_process_count_is_bounded_independent_of_file_count(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            store = GitStore(Path(temp) / "realm", Path(temp) / "runtime")
            files = {f"records/{n}.md": str(n).encode() for n in range(40)}
            with patch.object(store, "_git", wraps=store._git) as git:
                base = store.initialize(files)["revision"]
                self.assertLess(git.call_count, 55)
                git.reset_mock()
                self.assertEqual(files, store.snapshot()["files"])
                self.assertLessEqual(git.call_count, 4)
                git.reset_mock()
                self.apply(store, base=base, changes={"records/0.md": b"updated"})
                self.assertLess(git.call_count, 55)

    def test_lost_runtime_journal_recovers_receipt_and_projection(self):
        import shutil
        def crash(stage):
            if stage == "published":
                raise RuntimeError("crash")
        self.store._checkpoint = crash
        with self.assertRaises(RuntimeError):
            self.apply()
        shutil.rmtree(self.runtime / "journals")
        store = GitStore(self.path)
        store.recover()
        receipt = self.apply(store)
        self.assertEqual(receipt["revision"], store.snapshot()["revision"])
        self.assertEqual(b"two", (self.path / "records/a.md").read_bytes())
        with self.assertRaises(IdempotencyConflict):
            self.apply(store, principal="other")

    def test_lost_historical_journal_does_not_restore_old_projection(self):
        import shutil
        first = self.apply()
        second = self.apply(base=first["revision"], key="second", changes={"records/a.md": b"three"})
        shutil.rmtree(self.runtime / "journals")
        store = GitStore(self.path)
        store.recover()
        self.assertEqual(first, self.apply(store))
        self.assertEqual(second["revision"], store.snapshot()["revision"])
        self.assertEqual(b"three", (self.path / "records/a.md").read_bytes())
        self.assertEqual([second["revision"], first["revision"], self.base], store.history())

    def test_crash_between_evidence_ref_and_runtime_journal(self):
        self.store._checkpoint = lambda stage: (_ for _ in ()).throw(RuntimeError("crash")) if stage == "recorded" else None
        with self.assertRaises(RuntimeError):
            self.apply()
        store = GitStore(self.path)
        store.recover()
        self.assertEqual(b"two", (self.path / "records/a.md").read_bytes())
        self.assertEqual(store.snapshot()["revision"], self.apply(store)["revision"])

    def test_unborn_staged_index_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "realm"
            path.mkdir()
            subprocess.run(["git", "-C", str(path), "init", "--quiet"], check=True)
            (path / "human.md").write_bytes(b"human")
            subprocess.run(["git", "-C", str(path), "add", "human.md"], check=True)
            store = GitStore(path, Path(temp) / "runtime")
            with self.assertRaises(DirtyWorkingTree):
                store.initialize({"agent.md": b"agent"})
            self.assertIsNone(store._head())
            self.assertEqual(b"human", (path / "human.md").read_bytes())

    def test_ref_advanced_after_cas_does_not_report_completion(self):
        def advance(stage):
            if stage == "published":
                current = self.store._head()
                tree = self.store._git("rev-parse", current + "^{tree}").stdout.decode().strip()
                other = self.store._git("commit-tree", tree, "-p", current, data=b"external commit").stdout.decode().strip()
                self.store._git("update-ref", "refs/ekk/published", other, current)
        self.store._checkpoint = advance
        with self.assertRaises(RecoveryConflict):
            self.apply()
        with self.assertRaises(RecoveryConflict):
            GitStore(self.path).recover()
        self.assertEqual(b"one", (self.path / "records/a.md").read_bytes())

    def test_unicode_normalized_collision_rejected_before_publication(self):
        with self.assertRaises(ValidationError):
            self.apply(changes={"records/é.md": b"NFC", "records/e\u0301.md": b"NFD"})
        self.assertEqual(self.base, self.store.snapshot()["revision"])

    def test_orphan_operation_ref_without_evidence_fails_closed(self):
        self.store._git("update-ref", self.store.operations_ref + "a" * 64, self.base)
        with self.assertRaises(RecoveryConflict):
            self.store.recover()

    def test_git_operation_evidence_does_not_retain_raw_retry_key(self):
        key = "caller-supplied-private-retry-key"
        receipt = self.apply(key=key)
        self.assertEqual(key, receipt["idempotency_key"])
        refs = self.store._git("for-each-ref", "--format=%(objectname)", self.store.operations_ref).stdout.decode().splitlines()
        for revision in refs:
            evidence = self.store._read_evidence(revision)["files"]["operation.json"]
            self.assertNotIn(key.encode(), evidence)

    def test_existing_journal_cannot_forge_receipt_or_pending_target(self):
        import json
        from ekk.model import digest
        self.apply()
        path = self.runtime / "journals" / (digest(b"change") + ".json")
        journal = json.loads(path.read_text())
        journal["receipt"]["principal"] = "forged"
        path.write_text(json.dumps(journal))
        with self.assertRaises(RecoveryConflict):
            self.apply()

    def test_prepared_journal_cannot_publish_unrecorded_target(self):
        import json
        from ekk.model import digest
        self.store._checkpoint = lambda stage: (_ for _ in ()).throw(RuntimeError("crash")) if stage == "prepared" else None
        with self.assertRaises(RuntimeError):
            self.apply()
        path = self.runtime / "journals" / (digest(b"change") + ".json")
        journal = json.loads(path.read_text())
        other = self.store._commit({"records/a.md": b"malicious", ".gitignore": b"views/\n"}, self.base)
        journal["revision"] = other
        journal["receipt"]["revision"] = other
        path.write_text(json.dumps(journal))
        with self.assertRaises(RecoveryConflict):
            GitStore(self.path).recover()
        self.assertEqual(self.base, self.store.snapshot()["revision"])
        self.assertEqual(b"one", (self.path / "records/a.md").read_bytes())

    def test_lookup_binds_exact_request_after_later_revision(self):
        receipt = self.apply()
        self.apply(base=receipt["revision"], key="later", changes={"records/a.md": b"three"})
        kwargs = dict(base=self.base, idempotency_key="change", principal="owner", policy_digest="a" * 64)
        self.assertEqual(receipt, self.store.lookup({"records/a.md": b"two"}, **kwargs))
        with self.assertRaises(IdempotencyConflict):
            self.store.lookup({"records/a.md": b"forged"}, **kwargs)

    def test_independent_full_copy_rebind_recovers_without_source_mutation(self):
        import json
        import shutil
        first = self.apply()
        source_binding = (self.path / ".git/ekk-runtime").read_bytes()
        clone_path = Path(self.temp.name) / "restored"
        shutil.copytree(self.path, clone_path)
        runtime = Path(self.temp.name) / "restored-runtime"
        with self.assertRaises(ValueError):
            GitStore(clone_path).recover()
        with self.assertRaises(ValueError):
            GitStore.rebind_runtime(clone_path, runtime, expected_previous_store=Path(self.temp.name) / "wrong")
        clone = GitStore.rebind_runtime(clone_path, runtime, expected_previous_store=self.path)
        self.assertEqual(first["revision"], clone.snapshot()["revision"])
        self.assertEqual(self.store.history(), clone.history())
        self.assertEqual(first, self.apply(clone))
        self.apply(clone, base=first["revision"], key="restore-drill", changes={"records/a.md": b"drill"})
        self.assertEqual(b"two", (self.path / "records/a.md").read_bytes())
        self.assertEqual(first["revision"], self.store.snapshot()["revision"])
        self.assertEqual(source_binding, (self.path / ".git/ekk-runtime").read_bytes())
        marker = json.loads((clone_path / ".git/ekk-recovery-clone.json").read_text())
        self.assertEqual("recovery_clone", marker["kind"])
        self.assertEqual("validated", marker["state"])
        self.assertEqual(0o700, runtime.stat().st_mode & 0o777)

    def test_rebind_resumes_after_each_durable_binding_write(self):
        import shutil
        from unittest.mock import patch
        import ekk.adapters.git_store as adapter
        for suffix in ("ekk-recovery-clone.json", "store-path", "ekk-runtime", "ekk-store-path"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temp:
                copy = Path(temp) / "copy"
                runtime = Path(temp) / "runtime"
                shutil.copytree(self.path, copy)
                original = adapter._atomic
                crashed = False
                def fail_after(path, data, **kwargs):
                    nonlocal crashed
                    original(path, data, **kwargs)
                    if not crashed and path.name == suffix and (path.parent == (copy / ".git").resolve() or path.parent == runtime.resolve()):
                        crashed = True
                        raise RuntimeError("binding write interruption")
                with patch.object(adapter, "_atomic", side_effect=fail_after):
                    with self.assertRaises(RuntimeError):
                        GitStore.rebind_runtime(copy, runtime, expected_previous_store=self.path)
                restored = GitStore.rebind_runtime(copy, runtime, expected_previous_store=self.path)
                self.assertEqual(self.base, restored.snapshot()["revision"])
                self.assertEqual(self.base, self.store.snapshot()["revision"])

    def test_recovery_copy_can_be_restored_again_after_new_work(self):
        import json
        import shutil
        first_path = Path(self.temp.name) / "first-restored"
        shutil.copytree(self.path, first_path)
        first = GitStore.rebind_runtime(first_path, Path(self.temp.name) / "first-runtime", expected_previous_store=self.path)
        changed = self.apply(first, key="first-new-work", changes={"records/a.md": b"new work"})
        second_path = Path(self.temp.name) / "second-restored"
        shutil.copytree(first_path, second_path)
        second = GitStore.rebind_runtime(second_path, Path(self.temp.name) / "second-runtime", expected_previous_store=first_path)
        self.assertEqual(changed["revision"], second.snapshot()["revision"])
        self.assertEqual(b"new work", (second_path / "records/a.md").read_bytes())
        self.assertEqual(self.base, self.store.snapshot()["revision"])
        marker = json.loads((second_path / ".git/ekk-recovery-clone.json").read_text())
        self.assertEqual(str(first_path.resolve()), marker["source_store"])
        self.assertEqual(str(self.path.resolve()), marker["previous_recovery"]["source_store"])

    def test_untracked_collision_preserved(self):
        (self.path / "new.md").write_bytes(b"human")
        with self.assertRaises(DirtyWorkingTree):
            self.apply(changes={"new.md": b"agent"})
        self.assertEqual(b"human", (self.path / "new.md").read_bytes())


class EnvelopeTests(unittest.TestCase):
    def test_unknown_kinds_remain_documents_and_required_fields_validated(self):
        record = dict(schema="ekk.record/0.1", id="legacy-id", kind="custom", title="Title", scope=["context-id"], revision=1,
                      created_at="2026-09-07T10:00:00+03:00", created_by="owner")
        self.assertEqual(record, validate_envelope(record))
        for bad in ({"revision": True}, {"scope": "context-id"}, {"created_at": None}, {"schema": "future"}, {"requires": ["future"]}):
            with self.assertRaises(ValidationError):
                validate_envelope(record | bad)


class SuppliedSchemaTests(unittest.TestCase):
    def test_exact_optional_fields_and_open_identifiers(self):
        record = dict(schema="ekk.record/0.1", id="human readable/идентификатор", kind="source", title=" ", scope=["scope with spaces"], revision=1,
                      created_at="2026-09-07T10:00:00+03:00", created_by="Human Name <owner>", classification="restricted",
                      source={"assets": [{"path": "sources/original.bin", "sha256": "a" * 64}]},
                      relations=[{"rel": "supports", "target": "another/id", "digest": "sha256:" + "b" * 64}],
                      aliases=["Alias"], review={"due_at": "2026-10-01T00:00:00Z", "when": ["New evidence"]})
        self.assertEqual(record, validate_envelope(record))
        for bad in ({"kind": "Upper"}, {"id": "ab"}, {"scope": ["duplicate", "duplicate"]}, {"classification": "secret"},
                    {"source": {}}, {"source": {"assets": []}}, {"aliases": ["same", "same"]},
                    {"relations": [{"rel": "supports", "target": "another", "digest": 111}]},
                    {"kind": "context"}):
            with self.assertRaises(ValidationError):
                validate_envelope(record | bad)
