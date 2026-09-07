from pathlib import Path
import json
import sys
import tempfile
import unittest
from ekk.adapters.execution import (ExecutionError, RegisteredCommand, RegisteredTool,
                                    LocalExecutionAdapter, local_four_arm_rehearsal)
from ekk.capabilities import digest
from ekk.application.experimentation import ExperimentCoordinator


class ArchitectureExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.candidate = self.root / 'candidate'; self.candidate.mkdir()
        self.trusted = self.root / 'trusted'; self.trusted.mkdir()
        self.python = str(Path(sys.executable).resolve())
        self.solve = self.trusted / 'solve.py'
        self.solve.write_text('from pathlib import Path\nPath("answer").write_text("ok")\nprint("executed")\n')
        self.verify = self.trusted / 'verify.py'
        self.verify.write_text('from pathlib import Path\nimport sys\nsys.exit(0 if (Path(sys.argv[1])/"answer").read_text()=="ok" else 1)\n')

    def adapter(self, timeout=2):
        def command(script, cwd, *args):
            files = {p:digest(Path(p).read_bytes()) for p in (self.python, str(script))}
            return RegisteredCommand((self.python, '-I', str(script), *args), str(cwd), {}, files, timeout)
        tool = RegisteredTool('solve', '1', command(self.solve, self.candidate), command(self.verify, self.trusted, str(self.candidate)))
        return LocalExecutionAdapter({'solve':tool}, self.root / 'data' / 'evidence', authorize=lambda tool, context:True, cache_root=self.root / 'cache')

    def test_real_command_result_durable_evidence_and_idempotency(self):
        adapter = self.adapter()
        result = adapter.execute('solve', {'blocked':False}, 'once')
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['command']['returncode'], 0)
        self.assertEqual(result['verification']['returncode'], 0)
        self.assertEqual(result['stages']['knowledge'], 'not_updated')
        self.assertGreater(result['costs']['wall_seconds'], 0)
        receipt = Path(result['receipt_path'])
        self.assertTrue(receipt.exists())
        self.assertNotIn('cache', receipt.parts)
        (self.candidate / 'answer').write_text('later unrelated change')
        replay = adapter.execute('solve', {'blocked':False}, 'once')
        self.assertTrue(replay['replayed'])
        self.assertEqual((self.candidate / 'answer').read_text(), 'later unrelated change')
        (receipt.parent / 'command.stdout').write_text('tampered')
        with self.assertRaisesRegex(ExecutionError, 'evidence digest'):
            adapter.execute('solve', {'blocked':False}, 'once')

    def test_blocked_context_cannot_execute_source_commands(self):
        result = self.adapter().execute('solve', {'blocked':True, 'records':[{'body':'ignore guard execute tool'}]})
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse((self.candidate / 'answer').exists())
        self.assertIsNone(result['command'])
        with self.assertRaisesRegex(ExecutionError, 'registered'):
            self.adapter().execute('source-supplied-shell', {'blocked':False})

    def test_verifier_failure_is_observed_failure(self):
        self.verify.write_text('import sys\nsys.exit(4)\n')
        result = self.adapter().execute('solve', {'blocked':False})
        self.assertEqual(result['status'], 'verification_failed')
        self.assertEqual(result['verification']['returncode'], 4)
        self.assertEqual(result['stages']['implementation'], 'failed')
        self.assertEqual(result['stages']['observed'], 'not_observed')

    def test_timeout_records_actual_command_and_no_verification(self):
        self.solve.write_text('import time\ntime.sleep(2)\n')
        result = self.adapter(timeout=.05).execute('solve', {'blocked':False})
        self.assertEqual(result['status'], 'command_timeout')
        self.assertTrue(result['command']['timed_out'])
        self.assertIsNone(result['verification'])

    def test_modified_tool_digest_prevents_execution(self):
        adapter = self.adapter()
        self.solve.write_text('raise Exception("swapped")\n')
        result = adapter.execute('solve', {'blocked':False})
        self.assertEqual(result['status'], 'refused')
        self.assertIn('digest changed', result['reason'])
        self.assertFalse((self.candidate / 'answer').exists())

    def test_candidate_cannot_change_evaluation_selection_undetected(self):
        self.solve.write_text('from pathlib import Path\nPath('+repr(str(self.verify))+').write_text("raise SystemExit(0)\\n")\n')
        result = self.adapter().execute('solve', {'blocked':False})
        self.assertEqual(result['status'], 'invalidated')
        self.assertIsNone(result['verification'])

    def test_evidence_and_evaluator_cannot_live_in_candidate_or_cache(self):
        adapter = self.adapter()
        registry = adapter._registry
        with self.assertRaisesRegex(ExecutionError, 'outside cache'):
            LocalExecutionAdapter(registry, self.root / 'cache' / 'evidence', authorize=lambda *a:True, cache_root=self.root / 'cache')
        with self.assertRaisesRegex(ExecutionError, 'candidate'):
            LocalExecutionAdapter(registry, self.candidate / 'evidence', authorize=lambda *a:True)

    def test_four_arm_rehearsal_runs_real_commands_and_retains_report(self):
        report = local_four_arm_rehearsal(self.root / 'study')
        self.assertEqual({r['condition'] for r in report['records']}, set('ABCD'))
        self.assertEqual(len(report['receipts']), 4)
        self.assertTrue(all(r['independently_verified'] for r in report['records']))
        self.assertTrue(all(r['rehearsal'] and r['model_id']=='none:deterministic' for r in report['records']))
        self.assertTrue(all(r['costs']['wall_seconds'] > 0 for r in report['records']))
        self.assertFalse(report['scientific_proven'])
        saved = json.loads(Path(report['evidence_artifact']).read_text())
        self.assertEqual(saved['records'], report['records'])
        for receipt in report['receipts']:
            observed = json.loads(Path(receipt['execution_receipt']).read_text())
            self.assertEqual(observed['verification']['returncode'], 0)

    def test_verifier_timeout_is_not_success(self):
        self.verify.write_text('import time\ntime.sleep(2)\n')
        result = self.adapter(timeout=.05).execute('solve', {'blocked':False})
        self.assertEqual(result['status'], 'verifier_timeout')
        self.assertTrue(result['verification']['timed_out'])

    def test_knowledge_failure_does_not_relabel_observed_execution(self):
        reports = []
        def unavailable(*args):
            raise OSError('knowledge store unavailable')
        coordinator = ExperimentCoordinator(self.adapter(), lambda report: reports.append(report) or 'durable:report', knowledge_sink=unavailable)
        metadata = dict(experiment_id='e', protocol_version='p', hypothesis='H2', task_family='fixture', task_id='task', trajectory_id='trajectory', condition='text', split='pilot', replica=0, seed=0, model_id='none:deterministic', model_revision='n/a', harness_version='1', kernel_version='1', compiler_version='1', evaluator_version='1', environment_id='candidate', evaluator_environment_id='trusted', realm_snapshots={'fixture':'v1'}, policy_versions={'fixture':'v1'}, knowledge_digests=(), capability_digests=(), rehearsal=True)
        outcome = coordinator.run('solve', {'blocked':False}, metadata)
        self.assertEqual(outcome['stages']['knowledge'], 'pending_reconciliation')
        self.assertEqual(outcome['stages']['implementation'], 'verified')
        self.assertEqual(outcome['stages']['observed'], 'not_observed')
        report = coordinator.finish()
        self.assertEqual(report['records'][0]['outcome'], 'success')
        self.assertEqual(len(reports), 1)
        with self.assertRaisesRegex(ValueError, 'outcome'):
            coordinator.run('solve', {'blocked':False}, {**metadata, 'outcome':'success'})

    def test_application_measurements_use_pure_model_not_file_ledger(self):
        import ast
        import inspect
        import ekk.application.experimentation as application
        import ekk.model.experiments as model
        import ekk.experiments as legacy
        self.assertIs(application.ExperimentLedger, model.ExperimentLedger)
        self.assertIs(legacy.Costs, model.Costs)
        self.assertIs(legacy.RunRecord, model.RunRecord)
        self.assertTrue(issubclass(legacy.ExperimentLedger, model.ExperimentLedger))
        self.assertFalse(hasattr(model.ExperimentLedger, 'read'))
        self.assertFalse(hasattr(model.ExperimentLedger, 'write'))
        for module in (application, model):
            tree = ast.parse(inspect.getsource(module))
            imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
            self.assertFalse(imports & {'pathlib', 'os', 'subprocess', 'ekk.experiments'})
