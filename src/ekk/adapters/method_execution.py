"""Host-installed, read-only method adapters with durable evaluation and quarantine.

The trusted host owns callbacks and fixtures. Knowledge cannot supply Python,
commands, URLs, credentials, evaluator results or registry entries. Local files
are not a hostile-process security boundary; external effects stay elsewhere.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, dataclass
import fcntl
import json
from pathlib import Path
import time
from typing import Callable
from ekk.model.methods import canonical, sha
from ekk.model.experiments import Costs
from .git_store import _atomic


@dataclass(frozen=True)
class MethodAdapter:
    id: str
    version: str
    verifier_version: str
    privileges: tuple[str, ...]
    verify_artifact: Callable
    run: Callable
    cases: dict
    evaluate_result: Callable


class LocalMethodExecutor:
    def __init__(self, registry, evidence_root, *, authorize):
        self.registry = dict(registry)
        self.root = Path(evidence_root).resolve()
        self._authorize = authorize
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for key, adapter in self.registry.items():
            if key != adapter.id or not adapter.version or not adapter.verifier_version:
                raise ValueError('fixed method adapter and verifier versions required')

    def _adapter(self, method):
        spec = method['spec']; adapter = self.registry.get(spec['adapter'])
        if (adapter is None or adapter.version != spec['adapter_version']
                or tuple(spec['privileges']) != adapter.privileges
                or not adapter.verify_artifact(method['artifact'])):
            raise PermissionError('registered exact method adapter unavailable')
        return adapter

    def authorize(self, operation, method, facts):
        try:
            if operation not in ('retire', 'quarantine'):
                self._adapter(method)
            return self._authorize(operation, method, deepcopy(facts)) is True
        except (ValueError, PermissionError, KeyError):
            return False

    def _identity(self, method):
        return {'realm_id': method['realm_id'], 'reference': method['reference'],
                'spec_digest': sha(method['spec']), 'artifact_digest': sha(method['artifact'])}

    def quarantined(self, method):
        return (self.root / ('quarantine-' + sha(self._identity(method)) + '.json')).exists()

    def quarantine(self, method, *, reason):
        if not self.authorize('quarantine', method, {}) or not reason.strip():
            raise PermissionError('quarantine requires host authorization')
        row = {'schema': 'ekk.method-quarantine/0.1', 'method': self._identity(method), 'reason': reason}
        path = self.root / ('quarantine-' + sha(self._identity(method)) + '.json')
        if not path.exists():
            _atomic(path, canonical(row))
        return {'quarantined': True, 'canonical_acceptance_changed': False}

    def _perform(self, method, artifact, *, request, facts, operation_id, case_id=None):
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError('method operation ID required')
        operation = 'evaluate' if case_id is not None else 'run'
        adapter = self._adapter(method)
        if sha(artifact) != method['spec']['artifact_digest']:
            raise ValueError('method artifact differs')
        identity = self._identity(method)
        slot = sha([identity['realm_id'], operation_id])
        path = self.root / (slot + '.json')
        request_digest = sha([operation, identity, facts, request, case_id, adapter.verifier_version])
        with (self.root / (slot + '.lock')).open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not self.authorize(operation, method, facts) or self.quarantined(method):
                raise PermissionError('current method execution unavailable')
            if path.exists():
                old = json.loads(path.read_text())
                if old['request_digest'] != request_digest:
                    raise ValueError('method operation ID belongs to another request')
                return deepcopy(old)
            started = time.monotonic()
            actual_request = deepcopy(adapter.cases[case_id]['input']) if case_id is not None else deepcopy(request)
            output = adapter.run(artifact, actual_request)
            if len(canonical(output)) > 2 * 1024 * 1024:
                raise ValueError('method output too large')
            passed = adapter.evaluate_result(output, adapter.cases[case_id]) is True if case_id is not None else None
            # Revocation/registry/quarantine changes during read-only work suppress output.
            if not self.authorize(operation, method, facts) or self.quarantined(method):
                raise PermissionError('method authority changed while running')
            receipt = {'schema': 'ekk.method-execution/0.1', 'operation_id': operation_id,
                       'operation': operation, 'request_digest': request_digest, 'method': identity,
                       'adapter': adapter.id, 'adapter_version': adapter.version,
                       'verifier_version': adapter.verifier_version, 'case_id': case_id,
                       'facts': deepcopy(facts), 'input_digest': sha(actual_request), 'output': output,
                       'passed': passed, 'costs': asdict(Costs(0, 0, 0, 0, time.monotonic()-started, 0, 0)),
                       'cost_coverage': 'local deterministic adapter; user review and setup time not inferred',
                       'evidence_root_identity': sha(str(self.root).encode()),
                       'effect': 'read_only', 'human_understanding': 'not_measured',
                       'general_benefit': 'not_established'}
            _atomic(path, canonical(receipt))
            return deepcopy(receipt)

    def evaluate(self, method, artifact, *, case_id, facts, operation_id):
        if case_id not in self._adapter(method).cases:
            raise PermissionError('independent evaluation case unavailable')
        return self._perform(method, artifact, request={}, facts=facts, operation_id=operation_id, case_id=case_id)

    def execute(self, method, artifact, *, request, facts, operation_id):
        return self._perform(method, artifact, request=request, facts=facts, operation_id=operation_id)

    def verify_receipt(self, receipt, method):
        if not isinstance(receipt, dict) or receipt.get('operation') != 'evaluate':
            return False
        try:
            adapter = self._adapter(method)
            if (receipt['method'] != self._identity(method) or receipt['adapter'] != adapter.id
                    or receipt['adapter_version'] != adapter.version
                    or receipt['verifier_version'] != adapter.verifier_version
                    or receipt['case_id'] not in adapter.cases
                    or receipt['input_digest'] != sha(adapter.cases[receipt['case_id']]['input'])):
                return False
            path = self.root / (sha([method['realm_id'], receipt['operation_id']]) + '.json')
            if not path.is_file() or json.loads(path.read_text()) != receipt:
                return False
            expected = adapter.evaluate_result(receipt['output'], adapter.cases[receipt['case_id']]) is True
            return receipt.get('passed') is expected
        except (ValueError, KeyError, OSError, PermissionError):
            return False
