"""Pure measurement records and arithmetic for H1–H4; no filesystem or process I/O.

Trajectory assignment, independent evaluation and filesystem isolation remain
host responsibilities. The ledger detects declared cross-condition leakage;
it cannot establish operating-system isolation from declarations alone.
"""
from dataclasses import asdict, dataclass, field
import json
import math


class ExperimentError(ValueError):
    pass


def _number(value, name, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ExperimentError(f'{name} must be finite and nonnegative')
    if integer and not isinstance(value, int):
        raise ExperimentError(f'{name} must be an integer')


@dataclass(frozen=True)
class Costs:
    human_minutes: float
    agent_tokens: int
    model_cost: float
    tool_compute_cost: float
    wall_seconds: float
    environment_build_minutes: float
    environment_maintenance_minutes: float
    currency: str = 'USD'

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name != 'currency':
                _number(value, name, name == 'agent_tokens')
        if not self.currency.strip():
            raise ExperimentError('currency required')


@dataclass(frozen=True)
class RunRecord:
    experiment_id: str
    protocol_version: str
    hypothesis: str
    task_family: str
    task_id: str
    trajectory_id: str
    condition: str
    split: str
    replica: int
    seed: int
    model_id: str
    model_revision: str
    harness_version: str
    kernel_version: str
    compiler_version: str
    evaluator_version: str
    environment_id: str
    evaluator_environment_id: str
    realm_snapshots: dict[str, str]
    policy_versions: dict[str, str]
    knowledge_digests: tuple[str, ...]
    capability_digests: tuple[str, ...]
    outcome: str
    costs: Costs
    independently_verified: bool = False
    reason: str = ''
    human_interventions: tuple[str, ...] = ()
    reuse_opportunities: int = 0
    validated_reuses: int = 0
    preventable_opportunities: int = 0
    repeated_errors: int = 0
    error_causes: dict[str, int] = field(default_factory=dict)
    required_context: int = 0
    covered_context: int = 0
    false_inclusions: int = 0
    denied_disclosures: int = 0
    authority_confusions: int = 0
    context_bytes: int = 0
    compile_seconds: float = 0
    rehearsal: bool = False

    @classmethod
    def from_mapping(cls, values):
        data = dict(values)
        data['costs'] = Costs(**data['costs'])
        for key in ('knowledge_digests', 'capability_digests', 'human_interventions'):
            data[key] = tuple(data.get(key, ()))
        return cls(**data).validate()

    def validate(self):
        for name in ('experiment_id', 'protocol_version', 'task_family', 'task_id',
                     'trajectory_id', 'condition', 'model_id', 'model_revision',
                     'harness_version', 'kernel_version', 'compiler_version',
                     'evaluator_version', 'environment_id', 'evaluator_environment_id'):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ExperimentError(f'{name} required')
        for key in ('independently_verified', 'rehearsal'):
            if type(getattr(self, key)) is not bool:
                raise ExperimentError(f'{key} must be Boolean')
        for key in ('knowledge_digests', 'capability_digests'):
            values = getattr(self, key)
            if not isinstance(values, tuple) or any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v) for v in values):
                raise ExperimentError(f'{key} requires SHA-256 digests')
        if self.hypothesis not in ('H1', 'H2', 'H3', 'H4'):
            raise ExperimentError('unknown hypothesis')
        if self.split not in ('train', 'pilot', 'holdout'):
            raise ExperimentError('invalid split')
        if self.outcome not in ('success', 'failure', 'no_change', 'stopped', 'omitted'):
            raise ExperimentError('invalid outcome')
        if self.outcome != 'success' and not self.reason.strip():
            raise ExperimentError('non-success requires reason')
        if self.outcome == 'success' and not self.independently_verified:
            raise ExperimentError('success requires independent verification')
        if self.environment_id == self.evaluator_environment_id:
            raise ExperimentError('evaluator must have a separate environment')
        if not isinstance(self.costs, Costs):
            raise ExperimentError('full costs required')
        if not self.realm_snapshots or set(self.realm_snapshots) != set(self.policy_versions):
            raise ExperimentError('every declared realm requires snapshot and policy version')
        if any(not k or not v for mapping in (self.realm_snapshots, self.policy_versions) for k, v in mapping.items()):
            raise ExperimentError('empty realm snapshot or policy version')
        for name in ('replica', 'seed', 'reuse_opportunities', 'validated_reuses',
                     'preventable_opportunities', 'repeated_errors', 'required_context',
                     'covered_context', 'false_inclusions', 'denied_disclosures',
                     'authority_confusions', 'context_bytes'):
            _number(getattr(self, name), name, True)
        _number(self.compile_seconds, 'compile_seconds')
        for numerator, denominator in (('validated_reuses', 'reuse_opportunities'),
                                       ('repeated_errors', 'preventable_opportunities'),
                                       ('covered_context', 'required_context')):
            if getattr(self, numerator) > getattr(self, denominator):
                raise ExperimentError(f'{numerator} exceeds {denominator}')
        if self.validated_reuses and not self.independently_verified:
            raise ExperimentError('reuse requires independent verification')
        allowed_causes = {'capture', 'interpretation', 'retrieval', 'authorization',
                          'compilation', 'activation', 'obsolete_policy'}
        if set(self.error_causes) - allowed_causes:
            raise ExperimentError('unknown error cause')
        for count in self.error_causes.values():
            _number(count, 'error cause count', True)
        if sum(self.error_causes.values()) != self.repeated_errors:
            raise ExperimentError('each repeated error requires one primary cause')
        return self


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None}


class ExperimentLedger:
    def __init__(self):
        self._records = []

    @property
    def records(self):
        return json.loads(json.dumps(self._records))

    def add(self, record: RunRecord):
        record.validate()
        row = asdict(record)
        for old in self._records:
            if old['experiment_id'] != row['experiment_id']:
                continue
            if (old['trajectory_id'], old['task_id']) == (row['trajectory_id'], row['task_id']):
                raise ExperimentError('duplicate trajectory task')
            same_trajectory = old['trajectory_id'] == row['trajectory_id']
            if same_trajectory:
                # Split is trajectory-level: disclosed pilot cannot become holdout.
                stable = ('condition', 'split', 'replica', 'seed', 'model_id',
                          'model_revision', 'hypothesis', 'protocol_version',
                          'evaluator_version', 'environment_id', 'evaluator_environment_id')
                if any(old[key] != row[key] for key in stable):
                    raise ExperimentError('trajectory assignment changed')
            elif old['environment_id'] == row['environment_id']:
                raise ExperimentError('independent trajectories require separate environments')
            if old['environment_id'] == row['evaluator_environment_id'] or old['evaluator_environment_id'] == row['environment_id']:
                raise ExperimentError('evaluator environment intersects a trajectory')
            # H1 is fixed-model across conditions, not merely inside a trajectory.
            if old['hypothesis'] == row['hypothesis'] == 'H1' and any(old[k] != row[k] for k in ('model_id', 'model_revision', 'protocol_version', 'harness_version', 'evaluator_version')):
                raise ExperimentError('H1 fixed-model block changed')
        self._records.append(json.loads(json.dumps(row)))
        return row

    def summary(self):
        groups = {}
        for row in self._records:
            key = (row['experiment_id'], row['hypothesis'], row['condition'], row['split'], row['model_id'], row['model_revision'], row['rehearsal'])
            groups.setdefault(key, []).append(row)
        output = []
        for key, rows in sorted(groups.items()):
            currencies = {r['costs']['currency'] for r in rows}
            if len(currencies) != 1:
                raise ExperimentError('cannot aggregate different currencies')
            sums = lambda name: sum(r[name] for r in rows)
            output.append({'experiment_id': key[0], 'hypothesis': key[1],
                           'condition': key[2], 'split': key[3], 'model_id': key[4],
                           'model_revision': key[5], 'rehearsal': key[6],
                           'records': len(rows),
                           'independent_trajectories': len({r['trajectory_id'] for r in rows}),
                           'outcomes': {o: sum(r['outcome'] == o for r in rows) for o in ('success', 'failure', 'no_change', 'stopped', 'omitted')},
                           'learning_yield': ratio(sums('validated_reuses'), sums('reuse_opportunities')),
                           'amnesia_rate': ratio(sums('repeated_errors'), sums('preventable_opportunities')),
                           'context_coverage': ratio(sums('covered_context'), sums('required_context')),
                           'costs': {**{n: sum(r['costs'][n] for r in rows) for n in asdict(Costs(0, 0, 0, 0, 0, 0, 0)) if n != 'currency'}, 'currency': next(iter(currencies))},
                           'denied_disclosures': sums('denied_disclosures'),
                           'authority_confusions': sums('authority_confusions'),
                           'error_causes': {cause: sum(r['error_causes'].get(cause, 0) for r in rows) for cause in sorted({c for r in rows for c in r['error_causes']})},
                           'false_inclusions': sums('false_inclusions'),
                           'context_bytes': sums('context_bytes'),
                           'compile_seconds': sums('compile_seconds'),
                           'scientific_proven': False})
        return {'groups': output, 'inference': 'descriptive only; tasks within a trajectory are dependent'}


@dataclass(frozen=True)
class ScaffoldItem:
    artifact_id: str
    version: str
    reason_added: str
    model_dependency: str
    maintenance_minutes: float
    safety_control: bool
    necessity_evidence: tuple[str, ...]
    removal_candidate: bool = False
    removal_verified: bool = False
    holdout_version: str = ''

    def validate(self):
        if not all(isinstance(v, str) and v.strip() for v in (self.artifact_id, self.version, self.reason_added, self.model_dependency)):
            raise ExperimentError('scaffold identity, reason and model dependency required')
        _number(self.maintenance_minutes, 'maintenance_minutes')
        if self.removal_verified and (not self.removal_candidate or not self.holdout_version or not self.necessity_evidence):
            raise ExperimentError('verified removal requires candidate, independent holdout and evidence')
        return self


def scaffold_inventory(items):
    rows = [asdict(item.validate()) for item in items]
    if len({(r['artifact_id'], r['version']) for r in rows}) != len(rows):
        raise ExperimentError('duplicate scaffold inventory item')
    return {'items': rows, 'candidate_count': sum(r['removal_candidate'] for r in rows),
            'verified_removal_count': sum(r['removal_verified'] for r in rows),
            'maintenance_minutes': sum(r['maintenance_minutes'] for r in rows),
            'automatic_removal': False,
            'limitation': 'Evidence inventory, not a composite debt score or removal authority.'}
