"""Manual, read-only assessment of configured reports for a Git commit.

The bound workspace selects report paths. Reports declare check results; this
adapter does not run checks, authenticate their producer, or authorize actions.
Only the committed object is assessed, never uncommitted working-tree contents.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

from ..application.beliefs import Observation
from ..application.coding_readiness import assess_configured_checks
from ..application.workspace import working_references
from .local_profile import LocalProfile, binding
from .markdown import MarkdownCodec
from .operation_diagnostics import note_snapshots, note_stage
from .repository_evidence import MAX_CHECKS, configured_checks, read_configured_bytes

REQUEST_SCHEMA = 'ekk.coding-assessment/0.1'
REPORT_SCHEMA = 'ekk.configured-check-report/0.1'
MAX_REPORT_BYTES = 65536
_COMMIT = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
_ACTION = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')


def _digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate report field')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Nonstandard report value')


def _head(root):
    # Fixed local plumbing only. Inherited Git routing/configuration cannot
    # redirect the sensor to another repository, replacement object or process.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS='1', GIT_OPTIONAL_LOCKS='0')
    def git(*args):
        process = subprocess.run(['git', '-C', str(root), '-c', 'core.fsmonitor=false',
            '-c', 'core.hooksPath=' + os.devnull, 'rev-parse', *args],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=5)
        if process.returncode:
            raise ValueError('Current bound Git commit is unavailable')
        return process.stdout.strip()
    try:
        if Path(git('--show-toplevel')).resolve() != root:
            return {'status': 'unavailable', 'reason': 'binding_is_not_git_root'}
        commit = git('--verify', 'HEAD^{commit}')
        if not _COMMIT.fullmatch(commit):
            raise ValueError('Git did not return an exact commit')
        return {'status': 'available', 'commit': commit}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'status': 'unavailable', 'reason': 'git_commit_unavailable'}


def _request(request):
    required = {'schema', 'action_id', 'expected_head', 'completeness', 'checks'}
    transport = {'request_id', 'operation', 'scopes', 'target_scope', 'workspace_id', 'target_realm'}
    if not required <= set(request) or set(request) - required - transport - {'max_age_seconds'}:
        raise ValueError('Assessment requires its exact contract; supplied context, paths and commands are unsupported')
    if request['schema'] != REQUEST_SCHEMA:
        raise ValueError('Unsupported coding assessment schema')
    if not isinstance(request['action_id'], str) or not request['action_id'].strip() or len(request['action_id']) > 256:
        raise ValueError('Assessment action_id must be bounded nonempty text')
    if not isinstance(request['expected_head'], str) or not _COMMIT.fullmatch(request['expected_head']):
        raise ValueError('expected_head must be a full lowercase Git commit ID')
    if request['completeness'] not in ('complete', 'incomplete', 'unknown'):
        raise ValueError('Declare requirement completeness')
    checks = request['checks']
    if (not isinstance(checks, list) or not 1 <= len(checks) <= MAX_CHECKS
            or not all(isinstance(c, str) for c in checks) or len(set(checks)) != len(checks)):
        raise ValueError('Assessment requires nonempty unique configured check IDs')
    age = request.get('max_age_seconds', 300)
    if type(age) not in (int, float) or (type(age) is float and not math.isfinite(age)) or age < 0:
        raise ValueError('max_age_seconds must be finite and nonnegative')


def _report(root, path, workspace_id, check_id, proposition):
    pin = None
    reason = 'unreadable_or_unsafe_file'
    try:
        raw = read_configured_bytes(root, path, max_bytes=MAX_REPORT_BYTES)
        pin = _digest(raw)
        reason = 'invalid_json'
        report = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
        reason = 'invalid_report_schema'
        fields = {'schema', 'workspace_id', 'check_id', 'tested_commit', 'observed_at', 'status'}
        if not isinstance(report, dict) or set(report) != fields or report['schema'] != REPORT_SCHEMA:
            raise ValueError('Unsupported report contract')
        reason = 'wrong_workspace_or_check'
        if report['workspace_id'] != workspace_id or report['check_id'] != check_id:
            raise ValueError('Report belongs to another workspace or check')
        reason = 'invalid_commit'
        if not isinstance(report['tested_commit'], str) or not _COMMIT.fullmatch(report['tested_commit']):
            raise ValueError('Exact tested commit required')
        reason = 'invalid_timestamp'
        stamp = report['observed_at']
        if not isinstance(stamp, str) or len(stamp) > 64 or 'T' not in stamp:
            raise ValueError('Report observation requires a timestamp')
        observed_at = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if observed_at.utcoffset() is None:
            raise ValueError('Explicit report time required')
        reason = 'invalid_status'
        if report['status'] not in ('passed', 'failed', 'unknown'):
            raise ValueError('Explicit report time and status required')
        observation = Observation(check_id + ':' + pin, 'configured-check-report', '0.1', workspace_id,
            report['tested_commit'], proposition, {'passed': True, 'failed': False, 'unknown': None}[report['status']],
            'inferred', observed_at, pin)
        return observation, {'check_id': check_id, 'status': 'read', 'sha256': pin,
                             'producer_authenticated': False}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, FileNotFoundError):
            reason = 'missing_file'
        elif isinstance(exc, PermissionError):
            reason = 'file_access_denied'
        return None, {'check_id': check_id, 'status': 'unavailable_or_invalid', 'sha256': pin,
                      'reason': reason, 'producer_authenticated': False}


def _actions(document, configured, realm_id):
    rows = document.get('assessment_actions', [])
    if not isinstance(rows, list) or len(rows) > MAX_CHECKS:
        raise ValueError('At most 32 named assessment actions are supported')
    actions = {}
    for row in rows:
        required = {'id', 'checks', 'grounds', 'completeness'}
        if (not isinstance(row, dict) or not required <= set(row)
                or set(row) - required - {'max_age_seconds'}
                or not isinstance(row['id'], str) or not _ACTION.fullmatch(row['id'])
                or row['id'] in actions):
            raise ValueError('Named assessment actions require unique IDs and their exact contract')
        _request({'schema': REQUEST_SCHEMA, 'action_id': row['id'], 'expected_head': '0' * 40,
            'checks': row['checks'], 'completeness': row['completeness'],
            'max_age_seconds': row.get('max_age_seconds', 300)})
        if any(check not in configured for check in row['checks']):
            raise ValueError('Named action selects an unconfigured check')
        actions[row['id']] = {**row, 'grounds': working_references(row['grounds'], realm_id)}
    return actions


def compact_assessment(result):
    """Present the same assessment and evidence identities without input duplication."""
    reports = {row['check_id']: row for row in result['host_observation']['reports']}
    checks = []
    for condition in result['conditions']:
        report = reports[condition['condition']]
        reasons = {reason for row in condition['excluded_observations'] for reason in row['reasons']}
        if report.get('reason'):
            reasons.add(report['reason'])
        if condition.get('reason'):
            reasons.add(condition['reason'])
        state = condition['state']
        next_step = ('repair_failed_check' if state == 'refuted' else
                     'obtain_or_correct_report' if state in ('unknown', 'conflicted') else
                     'reobserve_target' if state == 'indeterminate' else None)
        checks.append({'id': condition['condition'], 'state': state, 'reasons': sorted(reasons),
                       'report_sha256': report['sha256'], 'next_step': next_step})
    host = result['host_observation']
    return {key: result[key] for key in ('schema', 'action_id', 'assessed_at', 'state', 'blocked',
        'reasons', 'observation_requests', 'requirement_set_digest', 'input_digest',
        'assessment_digest', 'snapshot_semantics', 'authority_effect', 'execution', 'outcome',
        'realm_alias')} | {
            'target': result['inputs']['requirements']['action_version'],
            'target_semantics': host['target_semantics'], 'working_tree': host['working_tree'],
            'requirements_source': host['requirements_source'],
            'producer_authenticated': False, 'checks': checks, 'manifest': result['manifest'],
            'display_projection': 'compact; full normalized evidence remains available without --compact'}


def assess_workspace(args, request, service_factory):
    """Use one bound route and fresh host observations; never execute a check."""
    note_stage('request')
    if args.root or args.realm:
        raise ValueError('assess requires the project binding; --root and --realm are unsupported')
    named = args.action is not None
    if named:
        if request or args.json or args.stdin:
            raise ValueError('Choose a named action or an explicit JSON assessment, not both')
    else:
        if args.expected_head is not None:
            raise ValueError('--expected-head is a named-action option; JSON assessments pin expected_head in their request')
        _request(request)
    note_stage('routing')
    if binding(args.cwd) is None:
        raise ValueError('assess requires an explicit workspace binding')
    root, document, routes = LocalProfile(args.profile).workspace(args.cwd)
    if len(routes) != 1:
        raise ValueError('assess requires exactly one bound realm route')
    route = routes[0]
    scopes = args.scope or route['scopes']
    if not set(scopes) <= set(route['scopes']):
        raise ValueError('Scope outside workspace binding')
    requested = request.get('scopes', scopes)
    if (not isinstance(requested, list) or not requested
            or not all(isinstance(s, str) for s in requested) or len(set(requested)) != len(requested)
            or not set(requested) <= set(scopes)):
        raise ValueError('JSON scope outside binding')
    if request.get('workspace_id', document['workspace_id']) != document['workspace_id']:
        raise ValueError('Request workspace differs from resolved binding')
    if request.get('target_realm', route['manifest']['id']) != route['manifest']['id']:
        raise ValueError('Request realm differs from resolved binding')
    configured = configured_checks(document)
    actions = _actions(document, configured, route['manifest']['id'])
    action_id = args.action if named else request['action_id']
    definition = actions.get(action_id)
    if (named or 'assessment_actions' in document) and definition is None:
        raise ValueError('Unknown owner-configured assessment action')
    if definition:
        if set(requested) != set(route['scopes']):
            raise ValueError('Named assessment actions require the full bound context scope')
        if not named and (set(request['checks']) != set(definition['checks'])
                or request['completeness'] != definition['completeness']
                or request.get('max_age_seconds', 300) != definition.get('max_age_seconds', 300)):
            raise ValueError('JSON assessment differs from its owner-configured action')
    before_binding = read_configured_bytes(root, '.ekk/workspace.yaml', max_bytes=MAX_REPORT_BYTES)
    if MarkdownCodec().load_yaml(before_binding) != document:
        raise ValueError('Workspace binding changed during routing')
    before_git = _head(root)
    if named:
        expected = args.expected_head
        if expected is None:
            if before_git['status'] != 'available':
                raise ValueError('Current Git commit is unavailable for the named action')
            expected = before_git['commit']
        request = {'schema': REQUEST_SCHEMA, 'action_id': action_id, 'expected_head': expected,
            'checks': definition['checks'], 'completeness': definition['completeness'],
            'max_age_seconds': definition.get('max_age_seconds', 300)}
        _request(request)
    if any(check not in configured for check in request['checks']):
        raise ValueError('Assessment check is not configured by the workspace owner')
    note_stage('store')
    app = service_factory(route['path'], allowed_scopes=requested)
    grounds = list(route.get('working_entries', []))
    for ref in definition['grounds'] if definition else ():
        if ref not in grounds:
            grounds.append(ref)
    context = app.context(requested, task='', budget=args.budget, focus=grounds,
                          selection='action_requirements')
    initial_snapshot = context['manifest']['snapshots'][0]['revision']
    note_snapshots(current_snapshot=initial_snapshot)
    observations, reports = [], []
    workspace_id = document['workspace_id']
    for check in request['checks']:
        proposition = 'configured_check:' + check + ':report_declares_passed'
        observation, evidence = _report(root, configured[check], workspace_id, check, proposition)
        reports.append(evidence)
        if observation is not None:
            observations.append(observation)
    after_git = _head(root)
    after_binding = read_configured_bytes(root, '.ekk/workspace.yaml', max_bytes=MAX_REPORT_BYTES)
    after_snapshot = app.publication_revision()
    host = {'schema': REQUEST_SCHEMA, 'target_semantics': 'committed_git_object_only',
            'working_tree': 'not_assessed',
            'requirements_source': 'workspace_owner_named_action' if definition else 'caller_declared_for_bound_workspace',
            'target_selection': 'freshly_observed_default' if named and args.expected_head is None else 'caller_pinned',
            'action_definition_digest': _digest(json.dumps(definition, sort_keys=True, separators=(',', ':')).encode()) if definition else None,
            'workspace_id': workspace_id, 'git_before': before_git, 'git_after': after_git,
            'binding_before': _digest(before_binding), 'binding_after': _digest(after_binding),
            'context_before': initial_snapshot, 'context_after': after_snapshot, 'reports': reports}
    result = assess_configured_checks(request, observations, context=context, host=host,
                                      assessed_at=datetime.now(timezone.utc))
    result['realm_alias'] = route['alias']
    return result
