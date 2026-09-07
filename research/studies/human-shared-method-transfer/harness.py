#!/usr/bin/env python3
"""Validate frozen study declarations and summarize observed records; stdlib only.

This does not run models, evaluate answers, or prove isolation. JSON is used as
valid YAML 1.2 so the protocol can be loaded without adding a YAML dependency.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

ARMS = ('baseline', 'personal', 'shared', 'combined')
PHASES = ('acquire', 'participant_transfer', 'model_replacement', 'adverse')
STAGES = ('setup', 'execution', 'context', 'maintenance', 'experiments_and_failures', 'verification', 'human_review')
UNITS = ('tokens', 'money', 'human_minutes', 'wall_seconds')
CHANNELS = {'baseline': {'ordinary_docs', 'result'}, 'personal': {'personal', 'result'},
            'shared': {'shared', 'method', 'result'}, 'combined': {'personal', 'shared', 'method', 'result'}}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def text(value):
    return isinstance(value, str) and bool(value.strip())


def validate(protocol, rows):
    require(protocol['status'] == 'designed_not_run' and protocol['results'] is None, 'design must not claim results')
    require(set(protocol['arms']) == set(ARMS) and tuple(protocol['phases']) == PHASES, 'arm/phase drift')
    f = protocol['freeze']
    require(isinstance(f, dict), 'study is not frozen; real model/tasks are unset')
    require(f['mode'] in ('rehearsal', 'observed'), 'invalid mode')
    require(type(f['replicas']) is int and f['replicas'] > 0, 'replicas required')
    for key in ('precision_rationale', 'task_family', 'harness_version', 'kernel_version', 'currency', 'observation_window', 'isolation_receipt'):
        require(text(f[key]), key + ' required')
    for key in ('tools_digest', 'baseline_workflow_digest', 'criteria_digest', 'failure_bounds_digest'):
        require(digest(f[key]), key + ' required')
    require(set(f['budget_caps']) == set(UNITS) and all(number(v) for v in f['budget_caps'].values()), 'full equal lifecycle budget required')
    e = f['evaluator']
    require(digest(e['digest']) and text(e['version']) and text(e['environment']), 'immutable evaluator required')
    require(set(f['phases']) == set(PHASES), 'phase freeze missing')
    tasks = []
    for i, phase in enumerate(PHASES):
        p = f['phases'][phase]
        require(all(digest(p[k]) for k in ('task_digest', 'input_digest', 'answer_digest')), 'task/input/answer digest required')
        require(text(p['participant']) and text(p['model_snapshot']), 'participant/model freeze required')
        require(p['related_to'] == (None if i == 0 else f['phases']['acquire']['task_digest']), 'heldout relation drift')
        tasks.append(p['task_digest'])
    require(len(set(tasks)) == 4, 'transfer must use nonidentical tasks')
    a, b, c, d = (f['phases'][p] for p in PHASES)
    require(a['participant'] != b['participant'] == c['participant'] == d['participant'], 'participant replacement schedule')
    require(a['model_snapshot'] == b['model_snapshot'] != c['model_snapshot'] == d['model_snapshot'], 'model replacement schedule')
    sources = f['sources']
    require(sources and len({s['digest'] for s in sources}) == len(sources), 'unique owned sources required')
    for s in sources:
        require(digest(s['digest']) and text(s['owner']) and text(s['provenance']) and s['allowed_participants'], 'source owner/provenance/access required')
    source_map = {s['digest']: s for s in sources}
    answers = {f['phases'][p]['answer_digest'] for p in PHASES}
    require(not answers & set(source_map), 'answers cannot be source inputs')
    expected = {(arm, rep, phase) for arm in ARMS for rep in range(f['replicas']) for phase in PHASES}
    seen, environments, totals = set(), {}, {}
    summary = {arm: {phase: {'count': 0, 'acceptable': 0, 'human_understanding': [], 'harm': 0, 'method_rejected_or_revised': 0} for phase in PHASES} for arm in ARMS}
    for r in rows:
        key = (r['arm'], r['replica'], r['phase'])
        require(type(r['replica']) is int and key in expected and key not in seen, 'unexpected or duplicate observation')
        seen.add(key)
        arm, rep, phase = key
        require(r['mode'] == f['mode'], 'rehearsal/observed mixing')
        for k in ('harness_version', 'kernel_version', 'tools_digest', 'baseline_workflow_digest', 'criteria_digest', 'failure_bounds_digest', 'observation_window', 'currency', 'budget_caps'):
            require(r[k] == f[k], k + ' drift')
        require(r['protocol_version'] == protocol['version'] and r['evaluator'] == e, 'protocol/evaluator drift')
        require(r['phase_assignment'] == f['phases'][phase], 'heldout/participant/model drift')
        env = r['environment']
        require(text(env) and env != e['environment'], 'candidate can access evaluator environment')
        trajectory = (arm, rep)
        require(env not in environments or environments[env] == trajectory, 'cross-arm/replica environment reuse')
        environments[env] = trajectory
        require(text(r['isolation_receipt']) and text(r['evaluation_receipt']), 'observation receipts required')
        require(r['observed_source_digests'] == sorted(source_map), 'source input drift')
        for s in sources:
            require(r['phase_assignment']['participant'] in s['allowed_participants'], 'source audience breach')
        require(r['answer_access_before_evaluation'] is False, 'heldout answer leakage')
        for artifact in r['accessed_artifacts']:
            require(artifact['origin_arm'] == arm and artifact['origin_replica'] == rep, 'cross-arm/replica artifact contamination')
            require(artifact['channel'] in CHANNELS[arm], 'arm mechanism contamination')
            require(digest(artifact['digest']) and artifact['digest'] not in answers, 'answer artifact leakage')
            require(text(artifact['owner']) and text(artifact['provenance']), 'artifact provenance missing')
            require(r['phase_assignment']['participant'] in artifact['allowed_participants'], 'artifact audience breach')
            if artifact['channel'] == 'personal':
                require(artifact['owner'] == r['phase_assignment']['participant'], 'personal archive transferred')
        require(set(r['costs']) == set(STAGES), 'whole lifecycle costs required')
        total = totals.setdefault(trajectory, dict.fromkeys(UNITS, 0))
        for stage in STAGES:
            require(set(r['costs'][stage]) == set(UNITS), 'cost units missing')
            for unit in UNITS:
                value = r['costs'][stage][unit]
                require(number(value), 'invalid cost')
                total[unit] += value
        require(r['outcome'] in ('acceptable', 'failure', 'stopped', 'omitted'), 'invalid outcome')
        require(r['outcome'] == 'acceptable' or text(r['reason']), 'failure/stop/omission reason required')
        for flag in ('independently_evaluated', 'harm', 'method_rejected_or_revised'):
            require(type(r[flag]) is bool, 'invalid observed flag')
        require(r['independently_evaluated'], 'independent evaluation required')
        h = r['human_understanding']
        require(h is None or (number(h) and h <= 1), 'human rubric score must be separate, null or 0..1')
        group = summary[arm][phase]
        group['count'] += 1
        group['acceptable'] += r['outcome'] == 'acceptable'
        group['harm'] += r['harm']
        group['method_rejected_or_revised'] += r['method_rejected_or_revised']
        group['human_understanding'].append(h)
    require(seen == expected, 'missing arm/replica/phase observations; include failures and omissions')
    for total in totals.values():
        require(all(total[u] <= f['budget_caps'][u] for u in UNITS), 'lifecycle budget exceeded')
    return {'status': 'rehearsal_only' if f['mode'] == 'rehearsal' else 'observations_validated',
            'empirical_benefit_established': False, 'groups': summary,
            'costs_by_trajectory': [{'arm': k[0], 'replica': k[1], **v} for k, v in totals.items()],
            'interpretation': 'Descriptive declarations only; no causal benefit or human understanding inferred. External receipts and isolation require independent audit.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('protocol', type=Path)
    parser.add_argument('records', type=Path, help='JSON array of observed run records')
    parser.add_argument('--frozen-sha256', required=True, help='Externally pinned SHA-256 of exact protocol bytes')
    args = parser.parse_args()
    try:
        raw = args.protocol.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == args.frozen_sha256, 'frozen protocol bytes changed')
        result = validate(json.loads(raw), json.loads(args.records.read_bytes()))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f'invalid study: {error}\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
