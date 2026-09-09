"""Pure configured-check policy over freshly collected host observations.

Adapters own routing, file/report parsing, Git, clocks and publication tokens.
This use case neither acquires evidence nor performs the named action.
"""
from copy import deepcopy
import hashlib
import json

from .beliefs import Condition, ObservationRequest, RequirementSet, assess_action


def _digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def assess_configured_checks(request, observations, *, context, host, assessed_at):
    """Apply coding policy once, independently of CLI and storage adapters."""
    request, context, host = deepcopy(request), deepcopy(context), deepcopy(host)
    projection = context['manifest'].get('projection')
    if (not isinstance(projection, dict)
            or projection.get('schema') != 'ekk.context-projection/0.1'
            or projection.get('kind') != 'action_requirements'
            or type(projection.get('complete')) is not bool):
        raise ValueError('Coding assessment requires an explicit action-requirements context projection')
    if not projection['complete'] and not context['manifest'].get('incomplete'):
        raise ValueError('Inconsistent action context sufficiency')
    workspace_id, commit = host['workspace_id'], request['expected_head']
    conditions, requests = [], []
    for check in request['checks']:
        proposition = 'configured_check:' + check + ':report_declares_passed'
        conditions.append(Condition(check, workspace_id, commit, proposition, modes=('inferred',),
            max_age_seconds=request.get('max_age_seconds', 300), observation_requests=(check,)))
        requests.append(ObservationRequest(check, workspace_id, commit, proposition, True,
            'Host must obtain or correct the configured report; execution and cost are not authorized'))
    unstable = []
    for before, after, reason in (
            ('git_before', 'git_after', 'git_changed_during_assessment'),
            ('binding_before', 'binding_after', 'binding_changed_during_assessment'),
            ('context_before', 'context_after', 'context_changed_during_assessment')):
        if host[before] != host[after]:
            unstable.append(reason)
    observed = host['git_after']
    versions = {workspace_id: observed['commit']} if not unstable and observed['status'] == 'available' else {}
    identity = _digest({'workspace_id': workspace_id,
        **{key: request[key] for key in ('action_id', 'expected_head', 'completeness', 'checks')},
        'max_age_seconds': request.get('max_age_seconds', 300),
        'action_definition_digest': host.get('action_definition_digest')})
    requirements = RequirementSet('configured-checks:' + identity, 1, request['action_id'],
        workspace_id, commit, request['completeness'], tuple(conditions))
    result = assess_action(requirements, tuple(observations), context=context,
        target_versions=versions, assessed_at=assessed_at, requests=tuple(requests))
    result['reasons'].extend(unstable)
    result.update(host_observation=host, manifest=context['manifest'],
        blocked=result['state'] != 'requirements_met',
        assessment_digest=_digest({'projection_digest': result['input_digest'], 'host': host}))
    return result
