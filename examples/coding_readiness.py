"""Exercise the installed assessment CLI in a disposable Git project.

The driver runs harmless fixture tests and one local file effect. `ekk assess`
only reads context, Git identity and configured report bytes. No model, network,
existing profile, real project or production environment is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def demonstrate(executable):
    executable = shutil.which(executable)
    if not executable:
        raise ValueError('Install EKK or supply --ekk /path/to/venv/bin/ekk')
    executable = str(Path(executable).absolute())
    with tempfile.TemporaryDirectory(prefix='ekk-coding-readiness-') as temporary:
        root = Path(temporary).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('EKK_', 'GIT_')) and k != 'PYTHONPATH'}
        env.update(EKK_CONFIG_HOME=str(root / 'config'), EKK_DATA_HOME=str(root / 'runtime'),
            EKK_CACHE_HOME=str(root / 'cache'), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        workspace, realm = root / 'project', root / 'realm'
        workspace.mkdir()

        def call(operation, *options, request=None, expected=0):
            command = [executable, operation, *map(str, options)]
            if request is not None:
                command.append('--stdin')
            result = subprocess.run(command, input=json.dumps(request) if request is not None else None,
                cwd=root, env=env, capture_output=True, text=True, timeout=60)
            if result.returncode != expected:
                raise RuntimeError(f'{operation}: expected {expected}, got {result.returncode}: {result.stderr or result.stdout}')
            return json.loads(result.stdout)

        def git(*options):
            return subprocess.check_output(['git', '-C', str(workspace), '-c', 'core.hooksPath=' + os.devnull,
                '-c', 'commit.gpgsign=false', *options], env=env, text=True, stderr=subprocess.PIPE).strip()

        initialized = call('init', '--root', realm, request={'context_id': 'context:demo'})
        profiles = root / 'config/profiles'; profiles.mkdir(parents=True)
        (profiles / 'demo.yaml').write_text(json.dumps({'schema': 'ekk.profile/0.1', 'uid': os.getuid(),
            'realms': {'project': {'id': initialized['realm_id'], 'path': str(realm)}}}))
        call('init', '--workspace', '--cwd', workspace, '--profile', 'demo', '--realm', 'project', '--scope', 'context:demo')
        control = workspace / '.ekk/workspace.yaml'
        # The CLI produced YAML. Reconstruct the documented synthetic binding as
        # JSON (valid YAML) so this example driver needs only the standard library.
        workspace_id = 'workspace:coding-demo'
        control.write_text(json.dumps({'schema': 'ekk.workspace/0.1', 'workspace_id': workspace_id, 'profile': 'demo',
            'bindings': [{'realm_alias': 'project', 'realm_id': initialized['realm_id'], 'contexts': ['context:demo']}],
            'evidence_checks': [{'id': 'unit', 'path': '.reports/unit.json'}],
            'assessment_actions': [{'id': 'review-selected-commit', 'checks': ['unit'],
                'grounds': [], 'completeness': 'complete'}]}, indent=2))
        (workspace / '.gitignore').write_text('.reports/\n__pycache__/\n')
        source = workspace / 'math_tool.py'
        source.write_text('def twice(value):\n    return value * 2\n')
        (workspace / 'test_math_tool.py').write_text(
            'import unittest\nfrom math_tool import twice\n\n'
            'class FixtureTests(unittest.TestCase):\n'
            '    def test_twice(self):\n        self.assertEqual(twice(3), 6)\n')
        git('init', '-q'); git('config', 'user.name', 'Synthetic EKK demo')
        git('config', 'user.email', 'demo@example.invalid')
        git('add', '.'); git('commit', '-qm', 'Initial demo commit')
        reports = workspace / '.reports'; reports.mkdir()
        report = reports / 'unit.json'
        request = {'schema': 'ekk.coding-assessment/0.1', 'action_id': 'review-selected-commit',
                   'expected_head': git('rev-parse', 'HEAD'), 'completeness': 'complete', 'checks': ['unit']}
        cases, validation_runs = {}, []

        def assess(name, expected_state):
            response = call('assess', '--cwd', workspace, request=request,
                            expected=0 if expected_state == 'requirements_met' else 1)
            assert response['state'] == expected_state, (name, response)
            assert response['authority_effect'] == 'none' and response['execution'] == 'not_performed'
            assert response['outcome'] == 'not_observed'
            cases[name] = {'state': response['state'], 'assessment_digest': response['assessment_digest'],
                'next_checks': [row['id'] for row in response['observation_requests']]}
            return response

        def observe_validation():
            commit = git('rev-parse', 'HEAD')
            producer = Path(__file__).resolve().parents[1] / 'tools/check_report.py'
            process = subprocess.run([sys.executable, str(producer), '--cwd', str(workspace),
                '--check', 'unit', '--expected-head', commit, '--', sys.executable,
                '-B', '-m', 'unittest', 'discover', '-s', '.', '-p', 'test_math_tool.py'],
                cwd=root, env=env, capture_output=True, text=True, timeout=60)
            receipt = json.loads(process.stdout)
            assert process.returncode in (0, 1) and receipt['status'] in ('passed', 'failed'), receipt
            assert receipt['report_written'] and receipt['tested_commit'] == commit
            validation_runs.append({'commit': commit, 'exit_code': process.returncode,
                'status': receipt['status'],
                'report_sha256': hashlib.sha256(report.read_bytes()).hexdigest()})

        assess('missing_report', 'needs_observation')
        observe_validation()
        historical = assess('matching_report', 'requirements_met')
        compact = call('assess', '--cwd', workspace, '--action', 'review-selected-commit', '--compact')
        assert compact['state'] == 'requirements_met' and compact['target'] == request['expected_head']
        assert compact['checks'][0]['state'] == 'supported'
        assert compact['requirements_source'] == 'workspace_owner_named_action'
        assert compact['working_tree'] == 'not_assessed'
        source.write_text('def twice(value):\n    return value + value\n')
        git('add', 'math_tool.py'); git('commit', '-qm', 'Equivalent implementation')
        assess('selected_target_changed', 'indeterminate')
        request['expected_head'] = git('rev-parse', 'HEAD')
        assess('old_report_for_new_commit', 'needs_observation')
        observe_validation()
        assess('fresh_report_for_new_commit', 'requirements_met')
        assert historical['inputs']['requirements']['action_version'] != request['expected_head']
        assert historical['snapshot_semantics'] == 'historical_projection'
        source.write_text('def twice(value):\n    return value * 3\n')
        git('add', 'math_tool.py'); git('commit', '-qm', 'Observable fixture defect')
        request['expected_head'] = git('rev-parse', 'HEAD')
        observe_validation()
        assess('reported_check_failure', 'requirements_not_met')
        source.write_text('def twice(value):\n    return value * 2\n')
        git('add', 'math_tool.py'); git('commit', '-qm', 'Repair fixture defect')
        request['expected_head'] = git('rev-parse', 'HEAD')
        observe_validation()
        assess('repaired_commit', 'requirements_met')

        # A host action receipt is distinct from observing its effect. These
        # fixture effects belong to this driver, never to the assessment CLI.
        effect = reports / 'effect.txt'
        receipt = {'request': 'write-local-demo-marker', 'status': 'accepted'}
        assert receipt['status'] == 'accepted' and not effect.exists()
        cases['accepted_request_without_effect'] = {'request_accepted': True, 'effect_observed': False}
        process = subprocess.run([sys.executable, '-I', '-c',
            'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("demo effect")', str(effect)],
            cwd=root, env=env, capture_output=True, timeout=30)
        assert process.returncode == 0 and effect.read_text() == 'demo effect'
        cases['separate_effect_observation'] = {'command_exit_code': process.returncode,
                                               'effect_observed': effect.read_text() == 'demo effect'}
        return {'schema': 'ekk.coding-readiness-demo/0.1', 'cases': cases,
                'validation_runs': validation_runs, 'mechanism_demonstration': True,
                'comparative_study': 'not_run', 'model_calls': 0, 'network_calls': 0,
                'limitation': 'Explicit disposable-checkout host producer; no authentication of external CI or measured agent benefit.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ekk', default='ekk', help='Installed EKK executable')
    args = parser.parse_args()
    print(json.dumps(demonstrate(args.ekk), indent=2))
