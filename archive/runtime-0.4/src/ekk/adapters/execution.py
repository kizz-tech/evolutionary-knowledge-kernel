"""Trusted-local registered process adapter; no commands are loaded from knowledge.

Registry, evaluator and evidence belong to the host, outside candidate trees.
Digest checks detect mutation; they are not an OS sandbox against the same user.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

from ekk.capabilities import digest
from ekk.model.experiments import Costs


class ExecutionError(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def _within(path, root):
    return path == root or root in path.parents


@dataclass(frozen=True)
class RegisteredCommand:
    argv: tuple[str, ...]
    cwd: str
    environment: dict[str, str]
    file_digests: dict[str, str]
    timeout_seconds: float = 30

    def validate(self):
        if not isinstance(self.argv, tuple) or not self.argv or not all(isinstance(a, str) and a for a in self.argv):
            raise ExecutionError('registered argv must be a nonempty immutable tuple')
        if not Path(self.argv[0]).is_absolute() or not Path(self.cwd).is_absolute():
            raise ExecutionError('registered executable and cwd must be absolute')
        if not isinstance(self.environment, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k,v in self.environment.items()):
            raise ExecutionError('explicit process environment required')
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ExecutionError('positive finite timeout required')
        if not isinstance(self.file_digests, dict) or str(Path(self.argv[0]).resolve()) not in self.file_digests:
            raise ExecutionError('executable digest must be pinned')
        for path, sha in self.file_digests.items():
            if not Path(path).is_absolute() or not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{64}', sha):
                raise ExecutionError('registered file requires absolute path and SHA-256')
        # Explicit filesystem arguments that are code must be included by the
        # registry owner. Validate existing file arguments as a useful guard.
        for arg in self.argv[1:]:
            path = Path(arg)
            if path.is_absolute() and path.is_file() and path.suffix in ('.py', '.sh', '.rb', '.js'):
                if str(path.resolve()) not in self.file_digests:
                    raise ExecutionError('script argument must be pinned')
        return self

    def check(self):
        self.validate()
        for path, expected in self.file_digests.items():
            try:
                actual = digest(Path(path).read_bytes())
            except OSError as error:
                raise ExecutionError('registered tool file unavailable') from error
            if actual != expected:
                raise ExecutionError('registered tool digest changed')


@dataclass(frozen=True)
class RegisteredTool:
    tool_id: str
    version: str
    command: RegisteredCommand
    verifier: RegisteredCommand


class LocalExecutionAdapter:
    def __init__(self, registry: dict[str, RegisteredTool], evidence_root,
                 *, authorize, cache_root=None):
        self.evidence_root = Path(evidence_root).resolve()
        if cache_root is not None and _within(self.evidence_root, Path(cache_root).resolve()):
            raise ExecutionError('durable evidence must be outside cache')
        self._authorize = authorize
        self._registry = {}
        for key, tool in registry.items():
            if key != tool.tool_id or not tool.version:
                raise ExecutionError('registered tool identity/version required')
            # Snapshot mutable dictionaries; external registry edits cannot swap
            # commands during a running experiment.
            commands = [RegisteredCommand(tuple(c.argv), str(Path(c.cwd).resolve()), dict(c.environment), {str(Path(p).resolve()):sha for p,sha in c.file_digests.items()}, c.timeout_seconds).validate() for c in (tool.command, tool.verifier)]
            command, verifier = commands
            if _within(self.evidence_root, Path(command.cwd)):
                raise ExecutionError('evidence must be outside candidate workspace')
            for path in verifier.file_digests:
                if _within(Path(path).resolve(), Path(command.cwd)):
                    raise ExecutionError('evaluator must be outside candidate workspace')
            self._registry[key] = RegisteredTool(key, tool.version, command, verifier)

    @staticmethod
    def _save(path, row):
        temporary = path.with_suffix('.pending')
        with temporary.open('wb') as stream:
            stream.write(_json(row) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _process(command, directory, stage):
        started = time.monotonic()
        stdout_path, stderr_path = directory / (stage + '.stdout'), directory / (stage + '.stderr')
        timed_out = False
        with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
            process = subprocess.Popen(command.argv, cwd=command.cwd, env=command.environment,
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       shell=False, start_new_session=True)
            try:
                returncode = process.wait(timeout=command.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                returncode = process.wait()
            stdout.flush(); os.fsync(stdout.fileno())
            stderr.flush(); os.fsync(stderr.fileno())
        return {'returncode': returncode, 'timed_out': timed_out,
                'wall_seconds': time.monotonic() - started,
                'stdout': {'name': stdout_path.name, 'digest': digest(stdout_path.read_bytes())},
                'stderr': {'name': stderr_path.name, 'digest': digest(stderr_path.read_bytes())}}

    def execute(self, tool_id, context_bundle, operation_id=None):
        if tool_id not in self._registry:
            raise ExecutionError('tool is not registered')
        tool = self._registry[tool_id]
        context = json.loads(_json(context_bundle))
        context_digest = digest(_json(context))
        operation_id = operation_id or str(uuid.uuid4())
        if not re.fullmatch('[a-zA-Z0-9_-]{1,100}', operation_id):
            raise ExecutionError('invalid operation ID')
        registration_digest = digest(_json(asdict(tool)))
        directory = self.evidence_root / operation_id
        receipt_path = directory / 'receipt.json'
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        try:
            directory.mkdir()
        except FileExistsError:
            if not receipt_path.exists():
                raise ExecutionError('interrupted receipt preparation; manual recovery required')
            previous = json.loads(receipt_path.read_text())
            if previous['context_digest'] != context_digest or previous['registration_digest'] != registration_digest:
                raise ExecutionError('operation ID already belongs to a different request')
            if self._authorize(tool_id, context) is not True:
                raise ExecutionError('current execution receipt access denied')
            self._verify_evidence(directory, previous)
            return {**previous, 'receipt_path': str(receipt_path), 'replayed': True}
        row = {'schema': 'ekk.execution/0.1', 'operation_id': operation_id,
               'tool_id': tool_id, 'tool_version': tool.version,
               'registration_digest': registration_digest, 'context_digest': context_digest,
               'context_manifest': context.get('manifest', {}),
               'registration': {'command': {'argv': list(tool.command.argv), 'cwd': tool.command.cwd, 'file_digests': tool.command.file_digests},
                                'verifier': {'argv': list(tool.verifier.argv), 'cwd': tool.verifier.cwd, 'file_digests': tool.verifier.file_digests}},
               'registered_environment': {'command_names': sorted(tool.command.environment), 'verifier_names': sorted(tool.verifier.environment),
                                          'command_digest': digest(_json(tool.command.environment)), 'verifier_digest': digest(_json(tool.verifier.environment))},
               'command': None, 'verification': None, 'status': 'prepared',
               'created_at': datetime.now(timezone.utc).isoformat(),
               'stages': {'code': 'not_executed', 'knowledge': 'not_updated', 'observed': 'not_observed', 'implementation': 'not_run'},
               'costs': asdict(Costs(0,0,0,0,0,0,0)),
               'cost_scope': 'wall time measured; no model calls; human/build/maintenance not measured by process adapter'}
        self._save(receipt_path, row)
        started = time.monotonic()
        try:
            if context.get('blocked') is not False:
                row['status'] = 'blocked'
                row['reason'] = 'context explicitly blocked or missing readiness'
            elif self._authorize(tool_id, context) is not True:
                row['status'] = 'denied'
            else:
                tool.command.check(); tool.verifier.check()
                row['status'] = 'executing'
                self._save(receipt_path, row)
                row['command'] = self._process(tool.command, directory, 'command')
                row['stages']['code'] = 'command_executed_acceptance_not_asserted'
                row['status'] = 'verifying'
                self._save(receipt_path, row)
                # Candidate changes may never replace the independent evaluator.
                tool.verifier.check(); tool.command.check()
                if self._authorize(tool_id, context) is not True:
                    row['status'] = 'denied_after_command'
                elif row['command']['timed_out']:
                    row['status'] = 'command_timeout'
                else:
                    row['verification'] = self._process(tool.verifier, directory, 'verifier')
                    tool.verifier.check()
                    good = row['command']['returncode'] == 0 and row['verification']['returncode'] == 0 and not row['verification']['timed_out']
                    row['status'] = 'verified' if good else 'verifier_timeout' if row['verification']['timed_out'] else 'verification_failed'
                    row['stages']['implementation'] = 'verified' if good else 'failed'
                    # A process verifier does not observe product benefit.
                    row['stages']['observed'] = 'not_observed'
        except (ExecutionError, OSError) as error:
            row['status'] = 'refused' if row['command'] is None else 'invalidated'
            row['reason'] = str(error)
        row['costs']['wall_seconds'] = time.monotonic() - started
        row['finished_at'] = datetime.now(timezone.utc).isoformat()
        self._save(receipt_path, row)
        return {**row, 'receipt_path': str(receipt_path), 'replayed': False}

    @staticmethod
    def _verify_evidence(directory, receipt):
        for stage in ('command', 'verification'):
            result = receipt.get(stage)
            if result:
                for output in ('stdout', 'stderr'):
                    artifact = result[output]
                    if digest((directory / artifact['name']).read_bytes()) != artifact['digest']:
                        raise ExecutionError('durable evidence digest mismatch')


def local_four_arm_rehearsal(destination):
    """Run four real local command/evaluator pairs, not an LLM experiment.

    Conditions are harness labels A/B/C/D. No effectiveness contrast is inferred
    from identical fixed tasks. Candidate/evaluator separation is layout plus
    digest admission, not hostile-process OS isolation.
    """
    from ekk.application.experimentation import ExperimentCoordinator
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=False)
    trusted = root / 'trusted-evaluator'; trusted.mkdir()
    evaluator = trusted / 'evaluate.py'
    evaluator.write_text('import pathlib,sys\np=pathlib.Path(sys.argv[1])/"answer.txt"\nsys.exit(0 if p.exists() and p.read_text()=="42\\n" else 1)\n')
    tool_script = trusted / 'solve.py'
    tool_script.write_text('from pathlib import Path\nPath("answer.txt").write_text("42\\n")\n')
    python = str(Path(sys.executable).resolve())
    pinned = {p: digest(Path(p).read_bytes()) for p in (python, str(evaluator), str(tool_script))}
    registry = {}
    for arm in 'ABCD':
        candidate = root / ('candidate-' + arm); candidate.mkdir()
        registry[arm] = RegisteredTool(arm, 'fixed-rehearsal/1',
            RegisteredCommand((python, '-I', str(tool_script)), str(candidate), {}, {python:pinned[python], str(tool_script):pinned[str(tool_script)]}),
            RegisteredCommand((python, '-I', str(evaluator), str(candidate)), str(trusted), {}, {python:pinned[python], str(evaluator):pinned[str(evaluator)]}))
    adapter = LocalExecutionAdapter(registry, root / 'data' / 'evidence', authorize=lambda tool, context: True, cache_root=root / 'cache')
    def retain(report):
        path = root / 'data' / 'report.json'
        with path.open('x') as stream:
            json.dump(report, stream, indent=2)
        return str(path)
    coordinator = ExperimentCoordinator(adapter, retain)
    runs = []
    for arm in 'ABCD':
        metadata = dict(experiment_id='local-four-arm-rehearsal', protocol_version='architecture-0.1', hypothesis='H1', task_family='fixed-arithmetic-artifact', task_id='task-1', trajectory_id='trajectory-'+arm, condition=arm, split='pilot', replica=0, seed=0, model_id='none:deterministic', model_revision='not-applicable', harness_version='architecture-0.1', kernel_version='architecture-0.1', compiler_version='architecture-0.1', evaluator_version=pinned[str(evaluator)], environment_id='candidate-'+arm, evaluator_environment_id='trusted-evaluator', realm_snapshots={'synthetic':'fixture-1'}, policy_versions={'synthetic':'policy-1'}, knowledge_digests=(), capability_digests=(), rehearsal=True)
        runs.append(coordinator.run(arm, {'blocked':False, 'manifest':{'fixture':'synthetic'}}, metadata, operation_id='arm-'+arm))
    return coordinator.finish(extra={'limitation':'Real subprocess plumbing rehearsal only; A/B/C/D labels do not establish model or memory effects.', 'runs':runs})
