"""Temporary action-readiness projection over host-authorized inputs.

No I/O, implicit clock, truth inference, sensor selection or execution authority.
The host owns requirement completeness, evidence interpretation, access, current
version observations and the conditional action. This is an experimental API.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math


@dataclass(frozen=True)
class Condition:
    id: str
    target: str
    version: str
    proposition: str
    expected: bool = True
    modes: tuple[str, ...] = ('observed',)
    max_age_seconds: float = 300
    observation_requests: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequirementSet:
    id: str
    revision: int
    action_id: str
    action_target: str
    action_version: str
    completeness: str
    conditions: tuple[Condition, ...]


@dataclass(frozen=True)
class Observation:
    id: str
    sensor: str
    sensor_version: str
    target: str
    version: str
    proposition: str
    value: bool | None
    mode: str
    observed_at: datetime
    evidence_digest: str
    status: str = 'available'
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservationRequest:
    id: str
    target: str
    version: str
    proposition: str
    available: bool
    cost: str


def _text(*values):
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError('Nonempty identifiers and descriptions required')


def _time(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('Explicit timezone-bearing time required')


def _strings(values):
    if not isinstance(values, tuple):
        raise ValueError('Unique immutable string tuple required')
    _text(*values)
    if len(set(values)) != len(values):
        raise ValueError('Unique immutable string tuple required')


def _rows(values, kind):
    if not isinstance(values, tuple) or any(not isinstance(v, kind) for v in values):
        raise ValueError('Immutable typed input tuple required')
    _text(*(v.id for v in values))
    if len({v.id for v in values}) != len(values):
        raise ValueError('Duplicate input identity')


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def _digest(value):
    data = json.dumps(_jsonable(value), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def assess_action(requirements, observations, *, context, target_versions,
                  assessed_at, requests=(), invalidated_observations=()):
    """Assess a nonempty host-declared requirement set, without performing an act.

    Observations are domain interpretations of pinned sensor payloads, not
    authenticated by this function. Target versions and context must be supplied
    freshly by the host; the result is never a reusable execution permit.
    """
    # Detach mutable caller mappings before validation and evaluation. This
    # preserves one set of inputs for the state, digest and historical output;
    # it does not make observations of separate owning systems atomic.
    context = deepcopy(context)
    target_versions = deepcopy(target_versions)
    if not isinstance(requirements, RequirementSet):
        raise ValueError('Explicit requirement set required')
    _text(requirements.id, requirements.action_id, requirements.action_target,
          requirements.action_version)
    if type(requirements.revision) is not int or requirements.revision < 1:
        raise ValueError('Positive requirement-set revision required')
    if requirements.completeness not in ('complete', 'incomplete', 'unknown'):
        raise ValueError('Explicit requirement completeness required')
    _rows(requirements.conditions, Condition)
    _rows(observations, Observation)
    _rows(requests, ObservationRequest)
    _strings(invalidated_observations)
    _time(assessed_at)
    modes = {'observed', 'inferred', 'assumed'}
    for condition in requirements.conditions:
        _text(condition.id, condition.target, condition.version, condition.proposition)
        _strings(condition.modes)
        _strings(condition.observation_requests)
        if not condition.modes or not set(condition.modes) <= modes:
            raise ValueError('Explicit supported acquisition modes required')
        if type(condition.expected) is not bool:
            raise ValueError('Domain must supply a Boolean prerequisite')
        age = condition.max_age_seconds
        if type(age) not in (int, float) or (type(age) is float and not math.isfinite(age)) or age < 0:
            raise ValueError('Finite nonnegative observation age required')
    for observation in observations:
        _text(observation.id, observation.sensor, observation.sensor_version,
              observation.target, observation.version, observation.proposition)
        _time(observation.observed_at)
        _strings(observation.alternatives)
        if observation.mode not in modes or observation.status not in ('available', 'unavailable'):
            raise ValueError('Explicit observation status and acquisition required')
        if observation.value is not None and type(observation.value) is not bool:
            raise ValueError('Observation value must be Boolean or unknown')
        pin = observation.evidence_digest
        if (not isinstance(pin, str) or len(pin) != 71 or not pin.startswith('sha256:')
                or any(c not in '0123456789abcdef' for c in pin[7:])):
            raise ValueError('Exact sensor-evidence SHA-256 required')
    for request in requests:
        _text(request.id, request.target, request.version, request.proposition, request.cost)
        if type(request.available) is not bool:
            raise ValueError('Host-declared request availability required')
    if (not isinstance(context, dict) or type(context.get('blocked')) is not bool
            or not isinstance(context.get('manifest'), dict) or not context['manifest']):
        raise ValueError('Explicit authorized context and manifest required')
    if not isinstance(target_versions, dict):
        raise ValueError('Explicit host-observed target versions required')
    for target, version in target_versions.items():
        _text(target, version)

    reasons = []
    if context['blocked']:
        reasons.append('context_blocked')
    if context['manifest'].get('incomplete') is True:
        reasons.append('context_incomplete')
    if requirements.completeness != 'complete':
        reasons.append('requirements_' + requirements.completeness)
    if not requirements.conditions:
        reasons.append('no_declared_conditions')
    if target_versions.get(requirements.action_target) != requirements.action_version:
        reasons.append('action_version_unverified_or_changed')

    rows, suggestions = [], {}
    for condition in requirements.conditions:
        usable, excluded = [], []
        version_matches = target_versions.get(condition.target) == condition.version
        for observation in sorted(observations, key=lambda o: o.id):
            if observation.proposition != condition.proposition:
                continue
            why = []
            if observation.target != condition.target:
                why.append('wrong_target')
            if observation.version != condition.version:
                why.append('wrong_version')
            if observation.id in invalidated_observations:
                why.append('invalidated')
            # Wall-clock subtraction with a shared ZoneInfo can ignore a DST
            # transition. Freshness compares actual instants, including folds.
            age = (assessed_at.astimezone(timezone.utc)
                   - observation.observed_at.astimezone(timezone.utc)).total_seconds()
            if age < 0:
                why.append('future_observation')
            elif age > condition.max_age_seconds:
                why.append('stale')
            if observation.status != 'available' or observation.value is None:
                why.append('unavailable_or_unknown')
            if observation.mode not in condition.modes:
                why.append('insufficient_acquisition_mode')
            if why:
                excluded.append({'observation': observation.id, 'reasons': why})
            else:
                usable.append(observation)
        values = {o.value for o in usable}
        alternatives = sorted({a for o in usable for a in o.alternatives})
        if not version_matches:
            state = 'indeterminate'
        elif alternatives or len(values) > 1:
            state = 'conflicted'
        elif values == {condition.expected}:
            state = 'supported'
        elif values:
            state = 'refuted'
        else:
            state = 'unknown'
        row = {'condition': condition.id, 'state': state,
               'considered_observations': [o.id for o in usable],
               'alternatives': alternatives, 'excluded_observations': excluded}
        if not version_matches:
            row['reason'] = 'target_version_unverified_or_changed'
        rows.append(row)
        if state in ('unknown', 'conflicted'):
            for request in requests:
                if (request.id in condition.observation_requests and request.available
                        and (request.target, request.version, request.proposition)
                        == (condition.target, condition.version, condition.proposition)):
                    suggestions[request.id] = asdict(request)

    states = {row['state'] for row in rows}
    if reasons or 'indeterminate' in states:
        state = 'indeterminate'
    elif 'refuted' in states:
        state = 'requirements_not_met'
    elif states == {'supported'}:
        state = 'requirements_met'
    elif suggestions:
        state = 'needs_observation'
    else:
        state = 'indeterminate'
    inputs = {'requirements': asdict(requirements),
              'observations': [asdict(o) for o in observations],
              'context_manifest': context['manifest'], 'context_blocked': context['blocked'],
              'target_versions': target_versions, 'assessed_at': assessed_at,
              'requests': [asdict(r) for r in requests],
              'invalidated_observations': invalidated_observations}
    return {'schema': 'ekk.action-readiness/0.1-experimental',
            'action_id': requirements.action_id, 'assessed_at': assessed_at.isoformat(),
            'state': state, 'reasons': reasons, 'conditions': rows,
            'observation_requests': [suggestions[k] for k in sorted(suggestions)]
                if state == 'needs_observation' else [],
            'requirement_set_digest': _digest(asdict(requirements)),
            'input_digest': _digest(inputs), 'inputs': _jsonable(inputs),
            'snapshot_semantics': 'historical_projection',
            'authority_effect': 'none', 'execution': 'not_performed',
            'outcome': 'not_observed'}
