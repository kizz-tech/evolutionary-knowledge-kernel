"""First-install discovery must reach the current runtime, including unbound entry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('EKK_')}
        self.env.update(EKK_CONFIG=str(self.root / 'no-legacy-config'),
                        EKK_CONFIG_HOME=str(self.root / 'config'),
                        EKK_DATA_HOME=str(self.root / 'data'),
                        EKK_CACHE_HOME=str(self.root / 'cache'))

    def call(self, *args):
        return subprocess.run([sys.executable, '-m', 'ekk', *map(str, args)],
                              cwd=self.root, env=self.env, capture_output=True, text=True)

    def test_help_and_version_describe_current_runtime(self):
        for args in [(), ('--help',), ('-h',)]:
            result = self.call(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('capture', result.stdout)
            self.assertIn('propose', result.stdout)
            self.assertIn('recover', result.stdout)
            self.assertNotIn('project-bind', result.stdout)
        result = self.call('--version')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0.5.0', result.stdout)
        self.assertIn('record format 0.1', result.stdout)

    def test_unbound_entry_uses_current_result_and_does_not_create_state(self):
        for options in [(), ('--compact',)]:
            result = self.call('enter', '--cwd', self.root, *options)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'unbound')
            self.assertEqual(list(self.root.iterdir()), [])

    def test_current_entry_does_not_read_unrelated_legacy_configuration(self):
        Path(self.env['EKK_CONFIG']).write_text('malformed: [')
        result = self.call('enter', '--cwd', self.root, '--profile', 'absent', '--realm', 'missing')
        self.assertEqual(result.returncode, 2)
        self.assertIn('error', json.loads(result.stderr))
        self.assertNotIn('Traceback', result.stderr)
        result = self.call('enter', '--cwd', self.root, '--compact')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'unbound')

    def test_missing_legacy_registry_is_not_an_installation(self):
        self.env['EKK_REALM_REGISTRY'] = str(self.root / 'no-registry')
        result = self.call('enter', '--cwd', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'unbound')

    def test_command_first_recovery_uses_current_store(self):
        realm = self.root / 'realm'
        initialized = self.call('init', '--root', realm)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        before = (realm / '.ekk/realm.yaml').read_bytes()
        recovered = self.call('recover', '--root', realm)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout), [])  # No interrupted operations.
        self.assertEqual((realm / '.ekk/realm.yaml').read_bytes(), before)
        self.assertTrue(json.loads(self.call('doctor', '--root', realm).stdout)['ok'])

    def test_legacy_commands_are_not_active_runtime_paths(self):
        result = self.call('--legacy-help')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('project-bind', result.stdout)


if __name__ == '__main__':
    unittest.main()
