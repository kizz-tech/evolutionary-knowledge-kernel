from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from ekk.experiments import Costs, RunRecord, ExperimentLedger, ExperimentError, deterministic_rehearsal, ScaffoldItem, scaffold_inventory


def record(**changes):
    base = RunRecord('exp-1', 'protocol-1', 'H1', 'family', 'task-1',
        'trajectory-1', 'D', 'pilot', 0, 1, 'fixed-model', 'revision-1',
        'harness-1', 'kernel-1', 'compiler-1', 'evaluator-1', 'env-1', 'eval-1',
        {'realm': 'snapshot-1'}, {'realm': 'policy-1'}, (), (), 'success',
        Costs(2, 100, .1, .2, 8, 10, 3), independently_verified=True)
    return replace(base, **changes)


class ExperimentTests(unittest.TestCase):
    def test_costs_are_separate_and_absent_opportunities_are_na(self):
        ledger = ExperimentLedger()
        ledger.add(record())
        ledger.add(record(task_id='task-2', outcome='stopped', reason='budget'))
        group = ledger.summary()['groups'][0]
        self.assertIsNone(group['learning_yield']['value'])
        self.assertEqual(group['independent_trajectories'], 1)
        self.assertEqual(group['outcomes']['stopped'], 1)
        self.assertEqual(group['costs']['environment_build_minutes'], 20)
        self.assertEqual(group['costs']['human_minutes'], 4)
        self.assertFalse(group['scientific_proven'])

    def test_counts_and_causes_require_valid_denominators(self):
        with self.assertRaises(ExperimentError):
            record(validated_reuses=1).validate()
        with self.assertRaises(ExperimentError):
            record(preventable_opportunities=1, repeated_errors=1).validate()
        valid = record(reuse_opportunities=2, validated_reuses=1,
                       preventable_opportunities=3, repeated_errors=1,
                       error_causes={'retrieval': 1})
        ledger = ExperimentLedger()
        ledger.add(valid)
        self.assertEqual(ledger.summary()['groups'][0]['learning_yield']['value'], .5)

    def test_invalid_cost_and_success_rejected(self):
        for value in (float('nan'), -1, True):
            with self.assertRaises(ExperimentError):
                Costs(value, 0, 0, 0, 0, 0, 0)
        with self.assertRaises(ExperimentError):
            record(independently_verified=False).validate()
        with self.assertRaises(ExperimentError):
            record(outcome='failure').validate()

    def test_trajectory_assignment_model_and_split_frozen(self):
        for update in ({'condition': 'B'}, {'split': 'holdout'}, {'model_revision': 'new'}):
            ledger = ExperimentLedger()
            ledger.add(record())
            with self.assertRaises(ExperimentError):
                ledger.add(record(task_id='task-2', **update))
        ledger = ExperimentLedger()
        ledger.add(record())
        with self.assertRaisesRegex(ExperimentError, 'fixed-model'):
            ledger.add(record(trajectory_id='t2', environment_id='env-2', model_revision='new'))

    def test_shared_trajectory_or_evaluator_environment_rejected(self):
        ledger = ExperimentLedger()
        ledger.add(record())
        with self.assertRaises(ExperimentError):
            ledger.add(record(trajectory_id='other'))
        with self.assertRaises(ExperimentError):
            ledger.add(record(trajectory_id='other', environment_id='eval-1'))
        with self.assertRaises(ExperimentError):
            record(evaluator_environment_id='env-1').validate()

    def test_ledger_owns_snapshot_and_does_not_overwrite_artifacts(self):
        ledger = ExperimentLedger()
        row = record()
        ledger.add(row)
        row.realm_snapshots['realm'] = 'mutated'
        self.assertEqual(ledger.records[0]['realm_snapshots']['realm'], 'snapshot-1')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'run.json'
            ledger.write(path)
            self.assertEqual(json.loads(path.read_text())['schema'], 'ekk-experiment/1')
            self.assertEqual(ExperimentLedger.read(path).summary(), ledger.summary())
            with self.assertRaises(FileExistsError):
                ledger.write(path)

    def test_rehearsal_is_explicitly_synthetic_and_complete(self):
        output = deterministic_rehearsal()
        self.assertEqual({r['outcome'] for r in output['records']}, {'success', 'failure', 'no_change'})
        self.assertTrue(all(r['rehearsal'] for r in output['records']))
        self.assertTrue(all(r['costs']['agent_tokens'] == 0 for r in output['records']))
        self.assertFalse(output['summary']['groups'][0]['scientific_proven'])

    def test_scaffold_inventory_preserves_safety_and_requires_holdout_evidence(self):
        item = ScaffoldItem('guard', '1', 'authority invariant', 'model-independent',
                            2, True, (), removal_candidate=True)
        inventory = scaffold_inventory([item])
        self.assertEqual(inventory['candidate_count'], 1)
        self.assertEqual(inventory['verified_removal_count'], 0)
        self.assertFalse(inventory['automatic_removal'])
        with self.assertRaises(ExperimentError):
            scaffold_inventory([replace(item, removal_verified=True)])
        checked = replace(item, removal_verified=True, holdout_version='holdout-new', necessity_evidence=('external-verifier-receipt',))
        self.assertEqual(scaffold_inventory([checked])['verified_removal_count'], 1)
