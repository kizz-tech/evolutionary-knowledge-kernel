"""The explicit host producer runs committed fixture bytes, never assess code."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/check_report.py'
SPEC = importlib.util.spec_from_file_location('check_report', SCRIPT)
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)


@unittest.skipUnless(os.name == 'posix', 'POSIX process-group producer')
class CheckReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ekk-producer-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'project'
        self.root.mkdir()
        self.git('init')
        (self.root / 'fixture.txt').write_text('committed\n')
        self.git('add', 'fixture.txt')
        self.git('commit', '-m', 'fixture')
        self.head = self.git('rev-parse', 'HEAD').strip()
        (self.root / '.ekk').mkdir()
        (self.root / '.reports').mkdir()
        self.control = self.root / '.ekk/workspace.yaml'
        self.control.write_text('''schema: ekk.workspace/0.1
workspace_id: workspace:fixture
bindings:
  - realm_alias: fixture
    realm_id: realm:fixture
    contexts: [context:fixture]
evidence_checks:
  - id: unit
    path: .reports/unit.json
''')
        self.report = self.root / '.reports/unit.json'

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Fixture',
            '-c', 'user.email=fixture@example.invalid', '-c', 'core.hooksPath=' + os.devnull,
            *args], env=producer._environment(), capture_output=True, text=True, check=True)
        return result.stdout

    def run_check(self, code='pass', **kwargs):
        return producer.produce(self.root, 'unit', [sys.executable, '-c', code], **kwargs)

    def assert_status(self, receipt, status):
        self.assertEqual(status, receipt['status'], receipt)
        report = json.loads(self.report.read_text())
        self.assertEqual(status, report['status'])
        self.assertEqual({'schema', 'workspace_id', 'check_id', 'tested_commit', 'observed_at', 'status'}, set(report))
        self.assertEqual(producer.REPORT_SCHEMA, report['schema'])
        self.assertEqual('workspace:fixture', report['workspace_id'])
        self.assertEqual('unit', report['check_id'])
        self.assertFalse(receipt['producer_authenticated'])
        return report

    def prior_pass(self):
        self.assert_status(self.run_check(), 'passed')

    def test_pass_and_actual_nonzero_have_exact_report_contract(self):
        report = self.assert_status(self.run_check(expected_head=self.head), 'passed')
        self.assertEqual(self.head, report['tested_commit'])
        self.assert_status(self.run_check('raise SystemExit(7)'), 'failed')
        self.assertEqual([], list(self.report.parent.glob('.ekk-check-*')))

    def test_dirty_original_and_untracked_files_are_preserved_and_ignored(self):
        (self.root / 'fixture.txt').write_text('dirty original')
        (self.root / 'untracked.txt').write_text('owner bytes')
        code = "from pathlib import Path; assert Path('fixture.txt').read_text() == 'committed\\n'; assert not Path('untracked.txt').exists()"
        self.assert_status(self.run_check(code), 'passed')
        self.assertEqual('dirty original', (self.root / 'fixture.txt').read_text())
        self.assertEqual('owner bytes', (self.root / 'untracked.txt').read_text())
        self.assertEqual(self.head, self.git('rev-parse', 'HEAD').strip())

    def test_tracked_mutation_is_unknown_even_after_exit_zero(self):
        result = self.run_check("from pathlib import Path; Path('fixture.txt').write_text('changed')")
        self.assert_status(result, 'unknown')
        self.assertEqual('fixture_tracked_bytes_changed', result['reason'])
        self.assertEqual('committed\n', (self.root / 'fixture.txt').read_text())

    def test_added_index_entry_is_unknown(self):
        code = "from pathlib import Path; import subprocess; Path('added.txt').write_text('new'); subprocess.run(['git','add','added.txt'],check=True)"
        self.assert_status(self.run_check(code), 'unknown')

    def test_timeout_invalidates_prior_pass_before_running(self):
        self.prior_pass()
        code = f"import json,time; assert json.load(open({str(self.report)!r}))['status']=='unknown'; time.sleep(10)"
        self.assert_status(self.run_check(code, timeout=0.1), 'unknown')

    def test_setup_failure_invalidates_prior_pass(self):
        self.prior_pass()
        with patch.object(producer, '_checkout', side_effect=OSError('private setup output')):
            result = self.run_check()
        self.assert_status(result, 'unknown')
        self.assertNotIn('private', json.dumps(result))

    def test_expected_head_mismatch_invalidates_and_does_not_execute(self):
        self.prior_pass()
        sentinel = self.root / 'executed'
        result = self.run_check(f'open({str(sentinel)!r}, "w").close()', expected_head='0' * 40)
        report = self.assert_status(result, 'unknown')
        self.assertEqual('0' * 40, report['tested_commit'])
        self.assertEqual('expected_head_mismatch', result['reason'])
        self.assertFalse(sentinel.exists())

    def test_source_head_change_is_unknown(self):
        first = self.head
        self.git('commit', '--allow-empty', '-m', 'next')
        self.head = self.git('rev-parse', 'HEAD').strip()
        code = f"import subprocess; subprocess.run(['git','-C',{str(self.root)!r},'update-ref','HEAD',{first!r}],check=True)"
        self.assert_status(self.run_check(code), 'unknown')

    def test_source_binding_change_is_unknown(self):
        code = f"from pathlib import Path; p=Path({str(self.control)!r}); p.write_text(p.read_text()+'# changed\\n')"
        self.assert_status(self.run_check(code), 'unknown')

    def test_restored_binding_and_tracked_bytes_still_invalidate(self):
        code = f"from pathlib import Path; p=Path({str(self.control)!r}); raw=p.read_bytes(); p.write_bytes(raw+b'# transient\\n'); p.write_bytes(raw)"
        self.assert_status(self.run_check(code), 'unknown')
        code = "from pathlib import Path; p=Path('fixture.txt'); raw=p.read_bytes(); p.write_bytes(b'transient'); p.write_bytes(raw)"
        self.assert_status(self.run_check(code), 'unknown')

    def test_report_parent_replacement_does_not_redirect_write(self):
        outside = self.root.parent / 'outside'
        outside.mkdir()
        target = outside / 'unit.json'
        target.write_text('outside owner bytes')
        old = self.root / '.reports-before'
        code = f"from pathlib import Path; p=Path({str(self.report.parent)!r}); p.rename({str(old)!r}); p.symlink_to({str(outside)!r}, target_is_directory=True)"
        result = self.run_check(code)
        self.assertEqual('unknown', result['status'])
        self.assertEqual('outside owner bytes', target.read_text())
        self.assertEqual('unknown', json.loads((old / 'unit.json').read_text())['status'])

    def test_final_fsync_failure_restores_unknown(self):
        original = producer.os.fsync
        calls = []
        def fail_final_directory(fd):
            calls.append(fd)
            if len(calls) == 4:
                raise OSError('failed final directory fsync')
            original(fd)
        with patch.object(producer.os, 'fsync', fail_final_directory):
            self.assert_status(self.run_check(), 'unknown')

    def test_git_replacement_objects_do_not_change_tested_commit_bytes(self):
        first = self.head
        (self.root / 'fixture.txt').write_text('replacement bytes')
        self.git('add', 'fixture.txt')
        self.git('commit', '-m', 'replacement')
        replacement = self.git('rev-parse', 'HEAD').strip()
        self.git('reset', '--mixed', first)
        self.git('replace', first, replacement)
        code = "from pathlib import Path; assert Path('fixture.txt').read_text() == 'committed\\n'"
        self.assert_status(self.run_check(code, expected_head=first), 'passed')

    def test_malformed_binding_and_unknown_check_do_not_execute(self):
        sentinel = self.root / 'executed'
        command = [sys.executable, '-c', f'open({str(sentinel)!r}, "w").close()']
        result = producer.produce(self.root, 'other', command)
        self.assertEqual('check_not_configured', result['reason'])
        self.assertFalse(result['report_written'])
        self.control.write_text('schema: unsupported\n')
        result = producer.produce(self.root, 'unit', command)
        self.assertEqual('unknown', result['status'])
        self.assertFalse(self.report.exists())
        self.assertFalse(sentinel.exists())

    def test_symlinked_report_parent_and_leaf_are_rejected(self):
        outside = self.root.parent / 'outside'
        outside.mkdir()
        self.report.parent.rmdir()
        self.report.parent.symlink_to(outside, target_is_directory=True)
        self.assertFalse(self.run_check()['report_written'])
        self.assertEqual([], list(outside.iterdir()))
        self.report.parent.unlink()
        self.report.parent.mkdir()
        target = outside / 'existing'
        target.write_text('owner bytes')
        self.report.symlink_to(target)
        self.assertFalse(self.run_check()['report_written'])
        self.assertEqual('owner bytes', target.read_text())

    def test_missing_report_parent_is_not_created(self):
        self.report.parent.rmdir()
        self.assertFalse(self.run_check()['report_written'])
        self.assertFalse(self.report.parent.exists())

    def test_report_cannot_replace_binding_or_committed_source(self):
        for forbidden in ('.ekk/workspace.yaml', 'fixture.txt'):
            original = self.control.read_text()
            self.control.write_text(original.replace('.reports/unit.json', forbidden))
            before = (self.root / forbidden).read_bytes()
            result = self.run_check()
            self.assertFalse(result['report_written'])
            self.assertEqual(before, (self.root / forbidden).read_bytes())
            self.control.write_text(original)

    def test_tracked_report_pathspec_characters_are_literal(self):
        relative = '.reports/unit[1].json'
        tracked = self.root / relative
        tracked.write_text('committed owner bytes')
        self.git('--literal-pathspecs', 'add', relative)
        self.git('commit', '-m', 'tracked report with pathspec characters')
        self.control.write_text(self.control.read_text().replace('.reports/unit.json', relative))
        result = self.run_check()
        self.assertEqual('report_is_tracked_source', result['reason'])
        self.assertFalse(result['report_written'])
        self.assertEqual('committed owner bytes', tracked.read_text())

    def test_no_shell_interpolation_or_command_output_in_receipt(self):
        literal = '$(touch injected); secret-token-value'
        command = [sys.executable, '-c', 'import sys; assert sys.argv[1].startswith("$("); print(sys.argv[1]); print(sys.argv[1],file=sys.stderr)', literal]
        result = subprocess.run([sys.executable, str(SCRIPT), '--cwd', str(self.root), '--check', 'unit', '--', *command],
            capture_output=True, text=True, check=True)
        self.assert_status(json.loads(result.stdout), 'passed')
        self.assertNotIn('secret-token', result.stdout + result.stderr + self.report.read_text())
        self.assertEqual('', result.stderr)
        self.assertFalse((self.root / 'injected').exists())

    def test_inherited_git_routing_and_global_hooks_are_ignored(self):
        config = self.root.parent / 'global.gitconfig'
        sentinel = self.root.parent / 'hook-ran'
        hooks = self.root.parent / 'hooks'
        hooks.mkdir()
        hook = hooks / 'post-checkout'
        hook.write_text(f'#!/bin/sh\ntouch "{sentinel}"\n')
        hook.chmod(0o755)
        config.write_text(f'[core]\n\thooksPath = {hooks}\n')
        with patch.dict(os.environ, {'GIT_DIR': '/does/not/exist', 'GIT_WORK_TREE': '/does/not/exist',
                                     'GIT_CONFIG_GLOBAL': str(config)}):
            self.assert_status(self.run_check(), 'passed')
        self.assertFalse(sentinel.exists())

    def test_cleanup_failure_cannot_publish_pass(self):
        self.prior_pass()
        cleanup = tempfile.TemporaryDirectory.cleanup
        def fail_cleanup(instance):
            cleanup(instance)
            raise OSError('cleanup failed')
        with patch.object(tempfile.TemporaryDirectory, 'cleanup', fail_cleanup):
            self.assert_status(self.run_check(), 'unknown')

    def test_remaining_child_is_terminated_and_result_unknown(self):
        sentinel = self.root.parent / 'late-child'
        child = f"import time; time.sleep(2); open({str(sentinel)!r},'w').close()"
        code = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}])"
        result = self.run_check(code)
        self.assert_status(result, 'unknown')
        self.assertIn(result['reason'], ('command_left_descendants', 'process_group_cleanup_uncertain'))
        time.sleep(2.1)
        self.assertFalse(sentinel.exists())

    def test_binding_must_be_at_actual_git_root(self):
        nested = self.root / 'nested'
        nested.mkdir()
        (nested / '.ekk').mkdir()
        (nested / '.ekk/workspace.yaml').write_bytes(self.control.read_bytes())
        (nested / '.reports').mkdir()
        result = producer.produce(nested, 'unit', [sys.executable, '-c', 'pass'])
        self.assertEqual('binding_is_not_git_root', result['reason'])
        self.assertFalse((nested / '.reports/unit.json').exists())


if __name__ == '__main__':
    unittest.main()
