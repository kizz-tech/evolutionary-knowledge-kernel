"""Compatibility facade for experiment file artifacts and synthetic rehearsal.

Validation and measurement arithmetic live in ekk.model.experiments. New
application use cases depend on that pure model; this module retains the legacy
file-ledger API for callers which explicitly own filesystem persistence.
"""
import json
from pathlib import Path
from ekk.model.experiments import (
    Costs, RunRecord, ExperimentError, ExperimentLedger as _PureExperimentLedger,
    ScaffoldItem, scaffold_inventory, ratio,
)


class ExperimentLedger(_PureExperimentLedger):
    """Legacy file-capable adapter around the single pure ledger implementation."""
    @classmethod
    def read(cls, path: Path):
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        if payload.get('schema') != 'ekk-experiment/1':
            raise ExperimentError('unknown experiment schema')
        ledger = cls()
        for row in payload['records']:
            ledger.add(RunRecord.from_mapping(row))
        # Saved summary is derivative; rebuild it instead of trusting it.
        return ledger

    def write(self, path: Path):
        # New artifact only; no silent rewriting of previous evidence.
        with Path(path).open('x', encoding='utf-8') as stream:
            json.dump({'schema': 'ekk-experiment/1', 'records': self.records,
                       'summary': self.summary()}, stream, ensure_ascii=False, indent=2)
            stream.write('\n')


def deterministic_rehearsal():
    """Exercise the measurement plumbing; zero model calls, no empirical result."""
    ledger = ExperimentLedger()
    for index, outcome in enumerate(('success', 'failure', 'no_change')):
        ledger.add(RunRecord(
            experiment_id='synthetic-measurement-rehearsal', protocol_version='0.3',
            hypothesis='H2', task_family='boundary-check', task_id=f'fixture-{index}',
            trajectory_id='synthetic-pilot-1', condition='capability', split='pilot',
            replica=0, seed=0, model_id='none:deterministic', model_revision='not-applicable',
            harness_version='0.3', kernel_version='0.3', compiler_version='0.3',
            evaluator_version='fixed-fixture/1', environment_id='synthetic:agent',
            evaluator_environment_id='synthetic:evaluator',
            realm_snapshots={'synthetic': 'fixture-v1'}, policy_versions={'synthetic': 'policy-v1'},
            knowledge_digests=(), capability_digests=(), outcome=outcome,
            costs=Costs(0, 0, 0, 0, 0, 0, 0), independently_verified=outcome == 'success',
            reason='' if outcome == 'success' else 'scripted measurement branch, not a model outcome',
            rehearsal=True))
    return {'records': ledger.records, 'summary': ledger.summary(),
            'limitation': 'Scripted branch coverage only; no H1-H4 evidence.'}
