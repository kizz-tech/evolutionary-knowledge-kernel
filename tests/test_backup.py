"""Synthetic owner-operated backup/recovery; never use a registered live store."""
import base64
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.backup import create_backup, restore_backup
from ekk.adapters.command_line import capture_once, service
from ekk.adapters.contained_store import ContainedGitStore
from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.model import RecoveryConflict, ValidationError, digest


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / "data"
        self.env = patch.dict(os.environ, {"EKK_DATA_HOME": str(self.data),
            "EKK_CONFIG_HOME": str(self.root / "config"), "EKK_CACHE_HOME": str(self.root / "cache")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = service(self.root / "realm")
        self.app.init("Backup test", realm_id=self.app.initial_realm_id)
        self.store = self.app.store
        manifest = self.app.codec.load_yaml(self.store.snapshot()["files"][".ekk/realm.yaml"])
        self.realm_id, self.scope = manifest["id"], manifest["default_context"]
        self.raw = b"exact source\r\n\x00\xff with binary bytes\n"
        self.receipt = self.capture(self.app, "capture-original", self.raw)

    def capture(self, app, key, raw=b"new source"):
        return capture_once(app, raw, title="Original source", scopes=[self.scope], filename="original.bin", key=key)

    def backup(self, name="backup.tar", store=None, **options):
        return create_backup(store or self.store, self.root / name, realm_id=self.realm_id,
                             principal=self.app.principal, data_home=self.data, **options)

    def restore(self, backup, name="restored"):
        result = restore_backup(backup["archive"], self.root / name, data_home=self.root / (name + "-data"),
                                expected_sha256=backup["sha256"])
        with patch.dict(os.environ, {"EKK_DATA_HOME": result["data_home"]}):
            app = service(result["realm_path"])
        return result, app

    def refs(self, store):
        return store._git("for-each-ref", "--format=%(refname) %(objectname)", store.operations_ref).stdout

    def members(self, path):
        with tarfile.open(path, "r:") as archive:
            return {member.name: archive.extractfile(member).read() for member in archive}

    def altered_archive(self, path, *, change=None, extra=None):
        members = self.members(path)
        if change:
            change(members)
        target = self.root / "altered.tar"
        with tarfile.open(target, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name, raw in members.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(raw)
                archive.addfile(entry, io.BytesIO(raw))
            if extra:
                archive.addfile(extra, io.BytesIO(b"x" * extra.size) if extra.isreg() else None)
        return target

    def test_exact_history_receipts_capture_replay_and_new_write(self):
        source_ref = self.receipt["source_references"][0]
        metadata = self.app._meta("decision", "Accepted decision", [self.scope],
                                  basis=[source_ref], commitment={"expectation": "Preserve exact bytes"})
        proposal = self.app.propose({"records/decision.md": self.app.codec.encode(metadata)})
        self.app.apply(proposal, idempotency_key="accept-decision", accept=[metadata["id"]])
        history = self.store.history()
        snapshots = {revision: self.store.snapshot(revision)["files"] for revision in history}
        refs = self.refs(self.store)
        backup = self.backup()
        self.assertEqual("realm", backup["backup_scope"])
        self.assertFalse(backup["contains_repository_history"])
        self.assertEqual(1, backup["capture_requests"])
        self.assertEqual(0o600, stat.S_IMODE(Path(backup["archive"]).stat().st_mode))
        # A backup remains pinned even when the live source later advances.
        self.capture(self.app, "later-source")
        source_head = self.store._head()
        result, app = self.restore(backup)
        self.assertEqual(history, app.store.history())
        self.assertEqual(refs, self.refs(app.store))
        for revision, files in snapshots.items():
            self.assertEqual(files, app.store.snapshot(revision)["files"])
        exact = dict(source_ref, realm=self.realm_id)
        source = app.read_source([self.scope], exact)
        self.assertEqual(self.raw, base64.b64decode(source["base64"]))
        with patch.dict(os.environ, {"EKK_DATA_HOME": result["data_home"]}):
            self.assertEqual(self.receipt, self.capture(app, "capture-original", self.raw))
            fresh = self.capture(app, "fresh-on-copy")
        self.assertNotEqual(result["revision"], fresh["revision"])
        self.assertEqual(source_head, self.store._head())
        self.assertEqual("not_performed", result["production_cutover"])
        self.assertFalse((app.store.path / ".git/objects/info/alternates").exists())
        self.assertEqual(0o700, stat.S_IMODE(app.store.path.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(Path(result["data_home"]).stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE((Path(result['data_home'])/'capture-requests').stat().st_mode))

    def test_offline_restore_has_no_source_dependency_or_git_configuration(self):
        self.store._git("config", "credential.helper", "do-not-copy-this-helper")
        self.store._git("config", "remote.origin.url", "https://synthetic-secret.invalid/repository")
        hook = self.store.path / ".git/hooks/post-checkout"
        hook.write_text("#!/bin/sh\nexit 99\n")
        hook.chmod(0o700)
        backup = self.backup()
        self.store.path.rename(self.root / "source-offline")
        self.data.rename(self.root / "data-offline")
        _, app = self.restore(backup)
        self.assertEqual(backup["revision"], app.store._head())
        self.assertNotIn(b"do-not-copy", (app.store.path / ".git/config").read_bytes())
        self.assertNotIn(b"synthetic-secret", (app.store.path / ".git/config").read_bytes())
        self.assertFalse((app.store.path / ".git/hooks/post-checkout").exists())

    def test_only_matching_realm_uid_capture_journals_are_preserved(self):
        other = service(self.root / "other-realm")
        other.init("Other realm", realm_id=other.initial_realm_id)
        other_scope = other.codec.load_yaml(other.store.snapshot()["files"][".ekk/realm.yaml"])["default_context"]
        capture_once(other, b"different owner's synthetic bytes", title="Other", scopes=[other_scope], filename="other.bin", key="other-capture")
        # A pending proposal is not published state and cannot be safely assigned
        # to a contained realm from the legacy row alone.
        pending = {"request_digest": "c" * 64, "proposal": self.app.capture(b"pending", title="Pending", scope=[self.scope])}
        (self.data / "capture-requests" / ("d" * 64 + ".json")).write_text(json.dumps(pending))
        (self.data / "method-evidence").mkdir()
        (self.data / "method-evidence/quarantine-private.json").write_text("host-owned quarantine")
        (self.data / "unrelated-evidence").mkdir()
        (self.data / "unrelated-evidence/credentials.json").write_text("synthetic credentials")
        backup = self.backup()
        members = self.members(backup["archive"])
        self.assertEqual(3, len(members))
        self.assertEqual(1, backup["capture_requests"])
        self.assertFalse(any("method" in name or "credential" in name for name in members))
        result, _ = self.restore(backup)
        self.assertFalse((Path(result["data_home"]) / "method-evidence").exists())
        self.assertIn("published operations", result["capture_request_coverage"])

    def test_incomplete_publication_rejected_without_recovery_or_artifact(self):
        for point in ("recorded", "prepared", "published"):
            with self.subTest(point=point):
                self.store._checkpoint = lambda stage: (_ for _ in ()).throw(RuntimeError("crash")) if stage == point else None
                proposal = self.app.capture(b"pending store", title="Pending store", scope=[self.scope])
                with self.assertRaises(RuntimeError):
                    self.app.apply(proposal, idempotency_key="interrupted-" + point)
                head = self.store._head()
                with self.assertRaises(RecoveryConflict):
                    self.backup(point + ".tar")
                self.assertEqual(head, self.store._head())
                self.assertFalse((self.root / (point + ".tar")).exists())
                self.store._checkpoint = lambda _: None
                self.store.recover()

    def test_restored_method_admission_cannot_replace_missing_host_receipt_or_quarantine(self):
        from ekk.adapters.method_execution import LocalMethodExecutor, MethodAdapter
        from ekk.adapters.method_repository import RealmMethodRepository
        from ekk.application.methods import MethodService, MethodUnavailable
        from ekk.model.methods import sha
        adapter = MethodAdapter("example:add", "1", "fixed/1", (),
            lambda raw: raw == b"add-one", lambda raw, request: request["value"] + 1,
            {"heldout": {"input": {"value": 40}, "expected": 41}},
            lambda value, case: value == case["expected"])
        facts = {"task_family": "arithmetic", "environment": "fixture", "model": "deterministic"}
        spec = {"schema": "ekk.method/0.1", "adapter": adapter.id, "adapter_version": "1",
                "artifact_digest": sha(b"add-one"), "privileges": [],
                "applicability": {key: [value] for key, value in facts.items()},
                "rollback": "Withdraw local admission", "reconsider_when": ["Requirements change"],
                "limitations": ["Synthetic arithmetic"]}
        repo = RealmMethodRepository(self.app, scopes=[self.scope], journal_root=self.data / "method-proposals")
        executor = LocalMethodExecutor({adapter.id: adapter}, self.data / "method-evidence", authorize=lambda *args: True)
        methods = MethodService(repo, executor)
        reference = methods.propose(method_id="method:add", title="Add one", spec=spec, artifact=b"add-one",
                                    explanation="Synthetic fixture", key="method-candidate")["method"]
        evaluation = methods.evaluate(reference, case_id="heldout", facts=facts, key="method-evaluate")
        methods.admit(reference, evaluation["evidence"], explanation="Synthetic fixture only", key="method-admit")
        methods.quarantine(reference, reason="Owner review required")
        backup = self.backup()
        result, app = self.restore(backup)
        restored_repo = RealmMethodRepository(app, scopes=[self.scope], journal_root=Path(result["data_home"]) / "method-proposals")
        restored_executor = LocalMethodExecutor({adapter.id: adapter}, Path(result["data_home"]) / "method-evidence",
                                               authorize=lambda *args: True)
        self.assertTrue(restored_repo.active(reference)["active"])
        self.assertFalse(restored_executor.verify_receipt(evaluation["evaluation"], restored_repo.load(reference)))
        with self.assertRaises(MethodUnavailable):
            MethodService(restored_repo, restored_executor).use(reference, request={"value": 3}, facts=facts, key="forbidden-restored-use")
        self.assertEqual("excluded_unverified", result["host_execution_evidence"])

    def test_corrupt_payload_or_wrong_archive_digest_rejected_before_claiming_paths(self):
        backup = self.backup()
        path = self.altered_archive(backup["archive"], change=lambda members: members.__setitem__("repository.bundle", b"X" + members["repository.bundle"][1:]))
        with self.assertRaisesRegex(ValidationError, "digest mismatch"):
            restore_backup(path, self.root / "bad-copy", data_home=self.root / "bad-data")
        with self.assertRaisesRegex(ValidationError, "expected archive"):
            restore_backup(backup["archive"], self.root / "wrong-copy", data_home=self.root / "wrong-data", expected_sha256="0" * 64)
        self.assertFalse((self.root / "bad-copy").exists())
        self.assertFalse((self.root / "bad-data").exists())

    def test_interrupted_capture_metadata_copy_does_not_activate_a_writer(self):
        from ekk.adapters.git_store import _atomic
        from ekk.model import StoreError
        backup = self.backup()
        target, data = self.root / "partial-copy", self.root / "partial-data"

        def interrupted(path, raw, **kwargs):
            if path.parent == data / "capture-requests":
                raise OSError("synthetic metadata write interruption")
            return _atomic(path, raw, **kwargs)

        with patch("ekk.adapters.backup._atomic", side_effect=interrupted), self.assertRaises(OSError):
            restore_backup(backup["archive"], target, data_home=data)
        copy = GitStore(target)
        with self.assertRaises(StoreError):
            copy.apply({"README.md": b"must remain unwritable"}, base=backup["revision"],
                       idempotency_key="partial-write", principal=self.app.principal, policy_digest="a" * 64)
        self.assertFalse((data / "restore.json").exists())
        self.assertEqual(backup["revision"], self.store._head())

    def test_unsafe_duplicate_truncated_and_oversize_archives_rejected(self):
        backup = self.backup()
        for name, kind in (("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                           ("capture-requests/link.json", tarfile.SYMTYPE), ("repository.bundle", tarfile.REGTYPE)):
            with self.subTest(name=name):
                entry = tarfile.TarInfo(name)
                entry.type, entry.size = kind, 1 if kind == tarfile.REGTYPE else 0
                entry.linkname = "../../outside" if kind == tarfile.SYMTYPE else ""
                path = self.altered_archive(backup["archive"], extra=entry)
                with self.assertRaises(ValidationError):
                    restore_backup(path, self.root / "unsafe-copy", data_home=self.root / "unsafe-data")
        truncated = self.root / "truncated.tar"
        truncated.write_bytes(Path(backup["archive"]).read_bytes()[:800])
        with self.assertRaises(ValidationError):
            restore_backup(truncated, self.root / "truncated-copy", data_home=self.root / "truncated-data")
        with patch("ekk.adapters.backup.MAX_ARCHIVE_BYTES", 100):
            with self.assertRaises(ValidationError):
                restore_backup(backup["archive"], self.root / "large-copy", data_home=self.root / "large-data")
        self.assertFalse((self.root / "escape").exists())

    def test_existing_source_nested_and_symlink_targets_rejected(self):
        backup = self.backup()
        original = Path(backup["archive"]).read_bytes()
        with self.assertRaises(ValidationError):
            self.backup()
        self.assertEqual(original, Path(backup["archive"]).read_bytes())
        for target, data in ((self.store.path, self.root / "new-data"),
                             (self.store.path / "inside", self.root / "new-data"),
                             (self.root / "new-root", self.data),
                             (self.root / "new-root", self.data / "inside")):
            with self.subTest(target=target, data=data), self.assertRaises(ValidationError):
                restore_backup(backup["archive"], target, data_home=data)
        (self.root / "link").symlink_to(self.root)
        with self.assertRaises(ValidationError):
            restore_backup(backup["archive"], self.root / "link/new-root", data_home=self.root / "new-data")
        self.store.path.rename(self.root / "source-offline")
        with self.assertRaisesRegex(ValidationError, "original source"):
            restore_backup(backup["archive"], self.store.path, data_home=self.root / "new-data")

    def test_authorized_identity_and_independent_object_limits(self):
        with self.assertRaises(ValidationError):
            create_backup(self.store, self.root / "wrong-realm.tar", realm_id="wrong", principal=self.app.principal, data_home=self.data)
        with self.assertRaises(PermissionError):
            create_backup(self.store, self.root / "wrong-user.tar", realm_id=self.realm_id, principal="local:uid:999999", data_home=self.data)
        with patch("ekk.adapters.backup.MAX_OBJECT_BYTES", 1), self.assertRaises(ValidationError):
            self.backup("large-objects.tar")
        self.assertFalse((self.root / "large-objects.tar").exists())

    def test_contained_requires_repository_scope_preserves_old_history_and_namespace(self):
        repository = self.root / "project"
        repository.mkdir()
        git = GitStore(repository)
        git._git("init", "--quiet", "--initial-branch=main")
        realm_path = repository / "knowledge"
        for name, raw in self.store.snapshot()["files"].items():
            path = realm_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (repository / "outer-private.txt").write_bytes(b"synthetic outer secret sentinel")
        git._git("add", ".")
        git._git("commit", "--quiet", "-m", "Outer baseline")
        outer_baseline = git._git("rev-parse", "HEAD").stdout.decode().strip()
        contained = ContainedGitStore(realm_path, repository, "refs/heads/main", self.root / "contained-runtime")
        app = RealmService(contained, principal=self.app.principal, codec=MarkdownCodec())
        first = self.capture(app, "contained-first")
        before = contained.history()
        old_refs = self.refs(contained)
        with self.assertRaisesRegex(ValidationError, "Unsupported realm-only"):
            self.backup("realm-only.tar", store=contained)
        self.assertFalse((self.root / "realm-only.tar").exists())
        backup = self.backup("repository-history.tar", store=contained, include_repository_history=True)
        self.assertTrue(backup["contains_repository_history"])
        self.assertEqual("repository-history", backup["backup_scope"])
        self.capture(app, "contained-later")
        live_head = contained._head()
        result, recovered_app = self.restore(backup, "contained-copy")
        restored = recovered_app.store
        self.assertIsInstance(restored, ContainedGitStore)
        self.assertEqual(before, restored.history())
        self.assertEqual(old_refs, self.refs(restored))
        self.assertEqual(contained.operations_ref, restored.operations_ref)
        self.assertEqual(b"synthetic outer secret sentinel", restored._git("show", outer_baseline + ":outer-private.txt").stdout)
        self.assertEqual(first["revision"], restored._head())
        with patch.dict(os.environ, {"EKK_DATA_HOME": result["data_home"]}):
            self.assertEqual(first, self.capture(recovered_app, "contained-first"))
            self.capture(recovered_app, "contained-copy-write")
        self.assertEqual(live_head, contained._head())
        # The same archived copy also restores without the original repository.
        repository.rename(self.root / "contained-offline")
        _, offline_app = self.restore(backup, "contained-offline-copy")
        self.assertEqual(first["revision"], offline_app.store._head())


if __name__ == "__main__":
    unittest.main()
