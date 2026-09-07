"""Preserve, evaluate, transfer and unlearn methods without transferring authority."""
from copy import deepcopy
from ekk.model.methods import validate_method, applicable, sha, exact_reference


class MethodUnavailable(PermissionError):
    pass


class MethodService:
    def __init__(self, repository, executor):
        self.repository, self.executor = repository, executor

    def propose(self, *, method_id, title, spec, artifact, explanation, basis=(), key, previous=None):
        validate_method(spec)
        if not isinstance(artifact, bytes) or sha(artifact) != spec['artifact_digest']:
            raise ValueError('exact immutable method artifact required')
        if not explanation.strip():
            raise ValueError('reason for retaining a method required')
        return self.repository.candidate(method_id=method_id, title=title, spec=spec, artifact=artifact,
                                         explanation=explanation, basis=list(basis), key=key, previous=previous)

    def _method(self, reference, facts, operation, *, active=False):
        exact_reference(reference)
        loaded = self.repository.load(reference)
        if not applicable(loaded['spec'], facts):
            raise MethodUnavailable('method does not apply to this task, environment or model')
        if sha(loaded['artifact']) != loaded['spec']['artifact_digest']:
            raise MethodUnavailable('method artifact changed')
        if not self.executor.authorize(operation, loaded, facts):
            raise MethodUnavailable('current host method admission unavailable')
        if self.executor.quarantined(loaded):
            raise MethodUnavailable('method quarantined; reviewed replacement required')
        if active:
            admission = self.repository.active(reference)
            if (not admission.get('active') or admission['evaluation'].get('passed') is not True
                    or not self.executor.verify_receipt(admission['evaluation'], loaded)):
                raise MethodUnavailable('current local acceptance and verified evaluation required')
            if not applicable(loaded['spec'], admission['evaluation']['facts']):
                raise MethodUnavailable('accepted evaluation does not cover method applicability')
        return loaded

    def evaluate(self, reference, *, case_id, facts, key):
        loaded = self._method(reference, facts, 'evaluate')
        receipt = self.executor.evaluate(loaded, loaded['artifact'], case_id=case_id, facts=facts, operation_id=key)
        if not self.executor.verify_receipt(receipt, loaded):
            raise MethodUnavailable('independent evaluation receipt unavailable')
        retained = self.repository.evaluation(reference, receipt, key=key)
        return {'evaluation': receipt, 'evidence': retained, 'accepted': False,
                'benefit': 'bounded evaluation only; human understanding and general effectiveness unmeasured'}

    def admit(self, reference, evidence, *, explanation, key):
        loaded = self.repository.load(exact_reference(reference))
        if not loaded['current']:
            raise MethodUnavailable('historical method requires a current revision before admission')
        receipt = self.repository.evidence(evidence)
        if (not self.executor.verify_receipt(receipt, loaded) or not receipt.get('passed')
                or not applicable(loaded['spec'], receipt['facts'])
                or not self.executor.authorize('admit', loaded, receipt['facts'])
                or self.executor.quarantined(loaded)):
            raise MethodUnavailable('verified local evaluation and current admission required')
        return self.repository.admit(reference, evidence, explanation=explanation, key=key)

    def use(self, reference, *, request, facts, key):
        loaded = self._method(reference, facts, 'run', active=True)
        # Reconstruct eligibility at each call. Persisted knowledge is not a cached activation permit.
        from ekk.capabilities import CapabilityManifest, CapabilityRuntime, BasisRef
        manifest = CapabilityManifest(reference['id'], str(reference['revision']), loaded['realm_id'],
            'source:' + loaded['artifact_source']['id'], loaded['spec']['artifact_digest'],
            (BasisRef(loaded['realm_id'], reference['id'], reference['digest'].removeprefix('sha256:')),),
            'ekk-method-coordinator/1', facts['environment'], tuple(loaded['spec']['privileges']),
            loaded['spec']['adapter'] + '@' + loaded['spec']['adapter_version'],
            loaded['spec']['rollback'], '; '.join(loaded['spec']['reconsider_when']))
        def admitted(operation, ignored):
            self._method(reference, facts, 'run', active=True)
            return True
        runtime = CapabilityRuntime(admit=admitted,
            basis_is_current=lambda ref: self.repository.active(reference).get('active') is True,
            verifier=lambda artifact, descriptor: sha(artifact) == loaded['spec']['artifact_digest'],
            runner=lambda artifact, value: self.executor.execute(loaded, artifact, request=value,
                                                                  facts=facts, operation_id=key))
        runtime.activate(manifest, loaded['artifact'])
        result = runtime.run(reference['id'], str(reference['revision']), deepcopy(request))
        # Read-only output is released only while canonical and host admission still hold.
        self._method(reference, facts, 'run', active=True)
        return result

    def reconsider(self, reference, *, case_id, facts, key):
        result = self.evaluate(reference, case_id=case_id, facts=facts, key=key)
        result['review_required'] = not result['evaluation']['passed']
        result['outcome'] = self.repository.outcome(reference, result['evidence'], result['evaluation']['passed'], key=key)
        result['automatic_canonical_change'] = False
        return result

    def quarantine(self, reference, *, reason):
        loaded = self.repository.load(exact_reference(reference))
        if not reason.strip() or not self.executor.authorize('quarantine', loaded, {}):
            raise MethodUnavailable('host quarantine authority required')
        return self.executor.quarantine(loaded, reason=reason)

    def retire(self, reference, *, explanation, basis, key):
        loaded = self.repository.load(exact_reference(reference))
        if not self.executor.authorize('retire', loaded, {}):
            raise MethodUnavailable('local method retirement authority required')
        if not explanation.strip() or not basis:
            raise ValueError('retirement needs an explanation and pinned grounds')
        # Host removal and canonical retirement are separate. Quarantine already blocks future use.
        self.executor.quarantine(loaded, reason=explanation)
        return self.repository.retire(reference, explanation=explanation, basis=basis, key=key)

    def export(self, reference, *, destination, grants):
        return self.repository.export(exact_reference(reference), destination=destination, grants=grants)

    def receive(self, bundle, *, expected_digest, method_id, key):
        if sha(bundle) != expected_digest:
            raise ValueError('received exact bundle digest differs')
        return self.repository.receive(bundle, expected_digest=expected_digest, method_id=method_id, key=key)
