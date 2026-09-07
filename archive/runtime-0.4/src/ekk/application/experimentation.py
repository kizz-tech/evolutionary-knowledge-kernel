"""Experiment orchestration through ports, independent of filesystem/processes."""
from dataclasses import asdict, replace
from typing import Protocol
from ekk.model.experiments import Costs, ExperimentLedger, RunRecord


class Executor(Protocol):
    def execute(self, tool_id, context_bundle, operation_id=None) -> dict: ...


class EvidenceSink(Protocol):
    def __call__(self, report: dict) -> str: ...


class ExperimentCoordinator:
    """Convert observed executor receipts into existing measurement records.

    The host owns registry, evaluator and retention callbacks. Metadata cannot
    supply outcome or verification success. Code execution, knowledge retention
    and observed evaluation remain separate stages, never a shared transaction.
    """
    def __init__(self, executor: Executor, evidence_sink: EvidenceSink, *, knowledge_sink=None):
        self.executor = executor
        self.evidence_sink = evidence_sink
        self.knowledge_sink = knowledge_sink
        self.ledger = ExperimentLedger()
        self.receipts = []

    def run(self, tool_id, context_bundle, metadata, *, operation_id=None,
            overhead_costs=None):
        forbidden = {'outcome', 'independently_verified', 'costs', 'reason'}
        if forbidden & set(metadata):
            raise ValueError('outcome and verifier result come from observed execution')
        overhead = overhead_costs or Costs(0,0,0,0,0,0,0)
        # Validate method configuration before any side effect.
        pending = RunRecord(**metadata, outcome='omitted', reason='pending execution',
                            costs=overhead).validate()
        # Check trajectory assignment before execution, without adding a phantom
        # measurement to the durable ledger.
        provisional = ExperimentLedger()
        for old in self.ledger.records:
            provisional.add(RunRecord.from_mapping(old))
        provisional.add(pending)
        receipt = self.executor.execute(tool_id, context_bundle, operation_id=operation_id)
        command, verifier = receipt.get('command'), receipt.get('verification')
        verified = (receipt.get('status') == 'verified' and isinstance(command, dict)
                    and command.get('returncode') == 0 and command.get('timed_out') is False
                    and isinstance(verifier, dict) and verifier.get('returncode') == 0
                    and verifier.get('timed_out') is False)
        stopped = receipt.get('status') in ('blocked', 'denied', 'refused', 'prepared', 'executing', 'verifying')
        outcome = 'success' if verified else 'stopped' if stopped else 'failure'
        costs = replace(overhead, wall_seconds=overhead.wall_seconds + receipt['costs']['wall_seconds'])
        result = replace(pending, outcome=outcome, independently_verified=verified,
                         reason='' if verified else receipt.get('reason', receipt['status']), costs=costs)
        self.ledger.add(result)
        stages = dict(receipt.get('stages', {}))
        knowledge_receipt = None
        if self.knowledge_sink is not None:
            try:
                knowledge_receipt = self.knowledge_sink(receipt, asdict(result))
                stages['knowledge'] = 'updated' if knowledge_receipt else 'no_change'
            except Exception as error:
                # An executed effect is not undone by failure to record knowledge.
                stages['knowledge'] = 'pending_reconciliation'
                knowledge_receipt = {'error_type': type(error).__name__}
        link = {'operation_id': receipt['operation_id'], 'execution_receipt': receipt.get('receipt_path'),
                'status': receipt['status'], 'stages': stages, 'knowledge_receipt': knowledge_receipt}
        self.receipts.append(link)
        return link

    def finish(self, *, extra=None):
        report = {'schema':'ekk.experiment-report/0.1', 'records':self.ledger.records,
                  'summary':self.ledger.summary(), 'receipts':self.receipts,
                  'scientific_proven':False, 'extra':extra or {}}
        artifact = self.evidence_sink(report)
        return {**report, 'evidence_artifact':artifact}
