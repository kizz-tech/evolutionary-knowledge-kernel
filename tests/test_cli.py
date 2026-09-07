import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.cli import main, resolve_root


class CliTests(unittest.TestCase):
    def test_run_requires_execute_without_calling_kernel_run(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ekk.cli.Kernel') as kernel:
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                result = main(['--root', tmp, 'run', '--commitment', 'c', '--scope', 'a',
                               '--command-json', '["command"]', '--verify-json', '["verifier"]',
                               '--cwd', tmp, '--authority', 'user', '--rollback', 'none'])
            self.assertEqual(result, 2)
            self.assertIn('--execute', error.getvalue())
            kernel.return_value.run.assert_not_called()

    def test_scope_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['--root', '/unused', 'compile'])
        self.assertEqual(error.exception.code, 2)

    def test_explicit_root_overrides_environment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'EKK_ROOT': '/other'}):
            self.assertEqual(resolve_root(str(Path(tmp).resolve())), Path(tmp).resolve())

    def test_nearest_pointer_and_relative_pointer_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp).resolve()
            child = root / 'child'
            child.mkdir()
            marker = root / '.ekk-root'
            marker.write_text(str(root / 'knowledge'))
            with patch('ekk.cli.Path.cwd', return_value=child):
                self.assertEqual(resolve_root(None), root / 'knowledge')
                marker.write_text('relative/path')
                with self.assertRaisesRegex(ValueError, 'absolute'):
                    resolve_root(None)

    def test_run_failed_verdict_exit_one_json(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ekk.cli.Kernel') as kernel:
            kernel.return_value.run.return_value = {'verdict': 'not_met'}
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(['--root', tmp, 'run', '--commitment', 'c', '--scope', 'a',
                             '--command-json', '["command"]', '--verify-json', '["verifier"]',
                             '--cwd', tmp, '--authority', 'user', '--rollback', 'none', '--execute'])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue()), {'verdict': 'not_met'})

    def test_recover_requires_execute_without_running_verifier(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ekk.cli.Kernel') as kernel:
            with contextlib.redirect_stderr(io.StringIO()):
                result=main(['--root',tmp,'recover','--action','a','--scope','p',
                             '--verify-json','["true"]','--cwd',tmp,'--authority','user'])
            self.assertEqual(result,2)
            kernel.return_value.recover.assert_not_called()

    def test_recovery_failed_verification_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ekk.cli.Kernel') as kernel:
            kernel.return_value.recover.return_value={'recovered':False,'verdict':'unknown'}
            with contextlib.redirect_stdout(io.StringIO()):
                result=main(['--root',tmp,'recover','--action','a','--scope','p',
                             '--verify-json','["true"]','--cwd',tmp,'--authority','user','--execute'])
            self.assertEqual(result,1)
