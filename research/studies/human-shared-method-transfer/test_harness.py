"""Synthetic contract tests. These are not empirical task/model observations."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness import ARMS, PHASES, STAGES, UNITS, validate

HERE = Path(__file__).resolve().parent


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    p = json.loads((HERE / 'protocol.yaml').read_text())
    phases = {}
    for i, phase in enumerate(PHASES):
        phases[phase] = {'task_digest': sha(phase), 'input_digest': sha('input-' + phase),
                         'answer_digest': sha('answer-' + phase),
                         'related_to': None if i == 0 else sha('acquire'),
                         'participant': 'A' if i == 0 else 'B',
                         'model_snapshot': 'synthetic-model-1' if i < 2 else 'synthetic-model-2'}
    p['freeze'] = f = {'mode': 'rehearsal', 'replicas': 1, 'precision_rationale': 'One replica for contract testing only',
        'task_family': 'synthetic-contract', 'harness_version': '0.1', 'kernel_version': 'test',
        'currency': 'USD', 'observation_window': 'synthetic', 'isolation_receipt': 'fixture-only',
        'tools_digest': sha('tools'), 'baseline_workflow_digest': sha('baseline'),
        'criteria_digest': sha('criteria'), 'failure_bounds_digest': sha('bounds'),
        'budget_caps': dict.fromkeys(UNITS, 1000), 'phases': phases,
        'evaluator': {'digest': sha('evaluator'), 'version': 'test', 'environment': 'isolated-evaluator'},
        'sources': [{'digest': sha('source'), 'owner': 'fixture-owner', 'provenance': 'synthetic only', 'allowed_participants': ['A', 'B']}]}
    rows = []
    for arm in ARMS:
        for phase in PHASES:
            row = {k: copy.deepcopy(f[k]) for k in ('mode', 'harness_version', 'kernel_version', 'tools_digest', 'baseline_workflow_digest', 'criteria_digest', 'failure_bounds_digest', 'observation_window', 'currency', 'budget_caps', 'evaluator')}
            row.update(arm=arm, replica=0, phase=phase, protocol_version=p['version'], phase_assignment=copy.deepcopy(phases[phase]),
                environment=arm + '-0', isolation_receipt='fixture-only', evaluation_receipt='fixture-only',
                observed_source_digests=[sha('source')], answer_access_before_evaluation=False,
                accessed_artifacts=[], costs={s: dict.fromkeys(UNITS, 1) for s in STAGES},
                outcome='failure', reason='Synthetic fixture, not an execution', independently_evaluated=True,
                harm=False, method_rejected_or_revised=False, human_understanding=None)
            rows.append(row)
    return p, rows


class ContractTests(unittest.TestCase):
    def test_unfrozen_design_cannot_run(self):
        p, rows = fixture()
        p['freeze'] = None
        with self.assertRaisesRegex(ValueError, 'not frozen'):
            validate(p, rows)

    def test_synthetic_never_establishes_benefit(self):
        p, rows = fixture()
        result = validate(p, rows)
        self.assertEqual(result['status'], 'rehearsal_only')
        self.assertFalse(result['empirical_benefit_established'])
        self.assertEqual(result['groups']['combined']['adverse']['human_understanding'], [None])

    def test_drift_and_missing_data_rejected(self):
        mutations = {
            'missing arm': lambda p, r: r.__delitem__(slice(0, 4)),
            'duplicate': lambda p, r: r.append(copy.deepcopy(r[0])),
            'model': lambda p, r: r[0]['phase_assignment'].__setitem__('model_snapshot', 'changed'),
            'participant': lambda p, r: r[1]['phase_assignment'].__setitem__('participant', 'A'),
            'heldout': lambda p, r: r[1]['phase_assignment'].__setitem__('task_digest', sha('other')),
            'answers': lambda p, r: r[0].__setitem__('answer_access_before_evaluation', True),
            'evaluator': lambda p, r: r[0]['evaluator'].__setitem__('digest', sha('changed')),
            'evaluator environment': lambda p, r: r[0].__setitem__('environment', 'isolated-evaluator'),
            'shared environment': lambda p, r: r[4].__setitem__('environment', 'baseline-0'),
            'version': lambda p, r: r[0].__setitem__('kernel_version', 'changed'),
            'budget drift': lambda p, r: r[0]['budget_caps'].__setitem__('tokens', 2000),
            'budget excess': lambda p, r: r[0]['costs']['maintenance'].__setitem__('tokens', 1001),
            'missing costs': lambda p, r: r[0]['costs'].__delitem__('experiments_and_failures'),
            'NaN cost': lambda p, r: r[0]['costs']['execution'].__setitem__('money', float('nan')),
            'source drift': lambda p, r: r[0].__setitem__('observed_source_digests', []),
            'source audience': lambda p, r: p['freeze']['sources'][0].__setitem__('allowed_participants', ['A']),
            'mixed evidence': lambda p, r: r[0].__setitem__('mode', 'observed'),
            'evaluation absent': lambda p, r: r[0].__setitem__('independently_evaluated', False),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                p, rows = fixture()
                mutate(p, rows)
                with self.assertRaises(ValueError):
                    validate(p, rows)

    def test_artifact_leakage(self):
        for change in ({'origin_arm': 'personal'}, {'channel': 'method'},
                       {'digest': sha('answer-acquire')}, {'allowed_participants': ['B']},
                       {'origin_replica': 1}):
            with self.subTest(change=change):
                p, rows = fixture()
                artifact = {'origin_arm': 'baseline', 'origin_replica': 0, 'channel': 'result',
                    'digest': sha('result'), 'owner': 'A', 'provenance': 'synthetic', 'allowed_participants': ['A']}
                artifact.update(change)
                rows[0]['accessed_artifacts'] = [artifact]
                with self.assertRaises(ValueError):
                    validate(p, rows)

    def test_personal_archive_cannot_follow_participant(self):
        p, rows = fixture()
        rows[5]['accessed_artifacts'] = [{'origin_arm': 'personal', 'origin_replica': 0, 'channel': 'personal',
            'digest': sha('private'), 'owner': 'A', 'provenance': 'synthetic', 'allowed_participants': ['A', 'B']}]
        with self.assertRaisesRegex(ValueError, 'personal archive'):
            validate(p, rows)

    def test_cli_rejects_changed_frozen_bytes(self):
        p, rows = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = json.dumps(p).encode()
            (root / 'p.yaml').write_bytes(raw)
            (root / 'r.json').write_text(json.dumps(rows))
            command = [sys.executable, str(HERE / 'harness.py'), str(root / 'p.yaml'), str(root / 'r.json'), '--frozen-sha256', hashlib.sha256(raw).hexdigest()]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            (root / 'p.yaml').write_bytes(raw + b'\n')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('frozen protocol bytes changed', result.stderr)


if __name__ == '__main__':
    unittest.main()
