from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from ekk.capabilities import (BasisRef, CapabilityManifest, CapabilityRuntime,
    CapabilityError, BOUNDARY_CHECK, digest, materialize,
    verify_boundary_check, run_boundary_check)


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.manifest = CapabilityManifest('boundary', '1', 'fixture-owner',
            'fixture://boundary', digest(BOUNDARY_CHECK),
            (BasisRef('realm-a', 'rule', 'a' * 64),), 'fixed/1', 'synthetic', (),
            'independent-boundary/1', 'disable and restore previous version',
            'basis change or model upgrade')
        self.allowed = True
        self.current = True
        self.calls = []
        self.runtime = CapabilityRuntime(admit=lambda op, m: self.allowed,
            basis_is_current=lambda ref: self.current,
            verifier=verify_boundary_check,
            runner=lambda data, fixture: self.calls.append(data) or run_boundary_check(data, fixture))

    def test_descriptor_is_inert_and_requires_admission(self):
        self.assertFalse(self.manifest.descriptor()['executable'])
        with self.assertRaises(CapabilityError):
            self.runtime.run('boundary', '1', {})
        self.assertEqual(self.calls, [])
        self.allowed = False
        with self.assertRaisesRegex(CapabilityError, 'denied'):
            self.runtime.activate(self.manifest, BOUNDARY_CHECK)
        self.assertEqual(self.calls, [])

    def test_exact_verified_bytes_reused_on_different_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'check.json'
            self.assertEqual(materialize(artifact, BOUNDARY_CHECK), self.manifest.artifact_digest)
            self.runtime.activate(self.manifest, artifact.read_bytes())
            artifact.write_bytes(b'changed after activation')
            passed = self.runtime.run('boundary', '1', dict(source_disclosure=True, target_acceptance=True, digest_match=True))
            failed = self.runtime.run('boundary', '1', dict(source_disclosure=True, target_acceptance=True))
        self.assertTrue(passed['passed'])
        self.assertEqual(failed['missing_checks'], ['digest_match'])
        self.assertEqual(self.calls, [BOUNDARY_CHECK, BOUNDARY_CHECK])

    def test_changed_artifact_or_unknown_verifier_content_rejected(self):
        with self.assertRaisesRegex(CapabilityError, 'digest'):
            self.runtime.activate(self.manifest, b'evil')
        arbitrary = replace(self.manifest, artifact_digest=digest(b'evil'))
        with self.assertRaisesRegex(CapabilityError, 'verification'):
            self.runtime.activate(arbitrary, b'evil')

    def test_basis_and_authority_rechecked_after_verification(self):
        def verify(data, manifest):
            self.allowed = False
            return True
        self.runtime._verifier = verify
        with self.assertRaisesRegex(CapabilityError, 'denied'):
            self.runtime.activate(self.manifest, BOUNDARY_CHECK)

    def test_basis_change_reconsiders_blocks_execution_preserves_history(self):
        self.runtime.activate(self.manifest, BOUNDARY_CHECK)
        self.current = False
        self.assertFalse(self.runtime.reconsider()[0]['automatic_removal'])
        with self.assertRaisesRegex(CapabilityError, 'basis'):
            self.runtime.run('boundary', '1', {})
        self.assertEqual(self.runtime.history[0]['state'], 'activated')
        self.current = True
        self.allowed = False
        with self.assertRaisesRegex(CapabilityError, 'denied'):
            self.runtime.run('boundary', '1', {})

    def test_retirement_and_reactivation_are_explicit(self):
        self.runtime.activate(self.manifest, BOUNDARY_CHECK)
        self.runtime.retire('boundary', '1', reason='holdout showed no benefit')
        with self.assertRaises(CapabilityError):
            self.runtime.run('boundary', '1', {})
        self.runtime.activate(self.manifest, BOUNDARY_CHECK)
        self.assertEqual([r['state'] for r in self.runtime.history], ['activated', 'retired', 'activated'])
        rows = self.runtime.history
        rows.clear()
        self.assertEqual(len(self.runtime.history), 3)

    def test_safety_removal_boolean_is_not_verification(self):
        manifest = replace(self.manifest, safety_control=True)
        self.runtime.activate(manifest, BOUNDARY_CHECK)
        with self.assertRaisesRegex(CapabilityError, 'safety'):
            self.runtime.retire('boundary', '1', reason='new model', replacement_verified=True)
        self.runtime._retirement_verifier = lambda m, reason: reason == 'independent holdout and replacement checked'
        self.runtime.retire('boundary', '1', reason='independent holdout and replacement checked', replacement_verified=True)

    def test_materialize_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'artifact'
            materialize(path, BOUNDARY_CHECK)
            with self.assertRaises(FileExistsError):
                materialize(path, b'changed')
            self.assertEqual(path.read_bytes(), BOUNDARY_CHECK)

    def test_retired_version_cannot_be_redefined(self):
        self.runtime.activate(self.manifest, BOUNDARY_CHECK)
        self.runtime.retire('boundary', '1', reason='retired')
        with self.assertRaisesRegex(CapabilityError, 'immutable'):
            self.runtime.activate(replace(self.manifest, owner='another-owner'), BOUNDARY_CHECK)
