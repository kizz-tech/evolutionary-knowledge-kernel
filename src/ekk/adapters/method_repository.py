"""Method lifecycle represented by ordinary source/note/decision records and receipts.

This adapter alone knows the Markdown/Git representation. A private proposal
journal makes retries stable; it is not a second method catalogue or authority.
"""
from __future__ import annotations
import base64
from contextlib import contextmanager
from functools import wraps
from threading import local
from copy import deepcopy
import fcntl
import json
from pathlib import Path
from ekk.model.methods import canonical, sha, validate_method, method_reference, exact_reference
from ekk.model import validate_identifier
from .git_store import _atomic


def _one_read_view(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._read_view():
            return method(self, *args, **kwargs)
    return call


class RealmMethodRepository:
    def __init__(self, realm_service, *, scopes, journal_root):
        self._views = local()
        self.realm = realm_service
        self.scopes = list(scopes)
        self.journal_root = Path(journal_root).resolve()
        self.realm.context(self.scopes, budget=1)
        _, manifest, _, _ = self._snapshot()
        roots = self.realm._roots(manifest)
        self.record_root = 'records' if 'records' in roots['record_roots'] else roots['record_roots'][0]
        self.source_root = roots['source_root']

    @contextmanager
    def _read_view(self):
        # One coherent canonical snapshot per nested read. It cannot survive a
        # call, cross a thread or authorize the next activation/run boundary.
        outer = getattr(self._views, 'depth', 0) == 0
        self._views.depth = getattr(self._views, 'depth', 0) + 1
        if outer: self._views.snapshot = None
        try:
            yield
        finally:
            self._views.depth -= 1
            if outer: self._views.snapshot = None

    def _snapshot(self):
        if getattr(self._views, 'depth', 0) and self._views.snapshot is not None:
            return self._views.snapshot
        snapshot = self.realm.store.snapshot()
        realm, policy, packs, records = self.realm._validate(snapshot)
        self.realm._authorized(policy, 'read', self.scopes)
        result = snapshot, realm, policy, records
        if getattr(self._views, 'depth', 0): self._views.snapshot = result
        return result

    def _read(self, reference):
        exact_reference(reference)
        snapshot, realm, policy, records = self._snapshot()
        row = self.realm._reference(reference, records)
        self.realm._authorized(policy, 'read', row['metadata']['scope'])
        if not set(row['metadata']['scope']) <= set(self.scopes):
            raise PermissionError('method record outside selected work')
        self.realm._read_basis(row['metadata'], records, policy)
        seen = set()
        def check_scope(record):
            marker = record['digest']
            if marker in seen: return
            seen.add(marker)
            if not set(record['metadata']['scope']) <= set(self.scopes):
                raise PermissionError('method dependency outside selected work')
            for ref in self.realm._refs(record['metadata']):
                check_scope(self.realm._reference(ref, records))
        check_scope(row)
        return snapshot, realm, policy, records, row

    def _meta(self, identifier, kind, title, **extra):
        validate_identifier(identifier)
        return {'schema': 'ekk.record/0.1', 'id': identifier, 'kind': kind, 'title': title,
                'scope': self.scopes, 'revision': 1, 'created_at': self.realm._now(),
                'created_by': self.realm.principal, **extra}

    def _apply(self, key, request, build):
        validate_identifier(key)
        _, realm, _, _ = self._snapshot()
        slot = sha([realm['id'], self.realm.principal, key])
        directory = self.journal_root / realm['id']
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / (slot + '.json')
        with (directory / (slot + '.lock')).open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                row = json.loads(path.read_text())
                if row['request_digest'] != sha(request):
                    raise ValueError('method request key belongs to different bytes')
            else:
                proposal, result, accept = build()
                row = {'request_digest': sha(request), 'proposal': proposal, 'result': result, 'accept': accept}
                _atomic(path, canonical(row))
            receipt = self.realm.apply(row['proposal'], idempotency_key=key, accept=row['accept'])
            return {**deepcopy(row['result']), 'receipt': receipt}

    def candidate(self, *, method_id, title, spec, artifact, explanation, basis, key, previous=None):
        validate_identifier(method_id); validate_method(spec)
        request = ['candidate', method_id, title, spec, sha(artifact), explanation, basis, self.scopes, previous]
        def build():
            _, _, _, current_records = self._snapshot()
            old = current_records.get(method_id)
            if old and (previous is None or method_reference(old) != exact_reference(previous)):
                raise ValueError('method revision requires the exact current predecessor')
            if previous and not old:
                raise ValueError('method predecessor unavailable')
            source_id = 'source:method-' + sha([method_id, key])
            asset_path = self.source_root + '/' + source_id + '/artifact.bin'
            source = self._meta(source_id, 'source', title + ' — exact method artifact',
                                source={'assets': [{'path': asset_path, 'sha256': sha(artifact)}]})
            source_raw = self.realm.codec.encode(source)
            source_ref = {'id': source_id, 'revision': 1, 'digest': 'sha256:' + sha(source_raw)}
            metadata = self._meta(method_id, 'note', title, basis=[source_ref, *deepcopy(basis)],
                                  method_package={'schema': 'ekk.method-package/0.1', 'spec': spec,
                                                  'artifact_source': source_ref})
            if old:
                metadata['revision'] = old['metadata']['revision'] + 1
                metadata['created_at'] = old['metadata']['created_at']
                metadata['supersedes'] = [previous]
            raw = self.realm.codec.encode(metadata, explanation)
            proposal = self.realm.propose({self.record_root + '/' + source_id + '.md': source_raw,
                                           asset_path: artifact, self.record_root + '/' + method_id + '.md': raw})
            return proposal, {'method': {'id': method_id, 'revision': metadata['revision'], 'digest': 'sha256:' + sha(raw)},
                              'artifact_source': source_ref, 'accepted': False}, []
        return self._apply(key, request, build)

    @_one_read_view
    def load(self, reference):
        snapshot, realm, policy, records, row = self._read(reference)
        package = row['metadata'].get('method_package', {})
        if package.get('schema') != 'ekk.method-package/0.1':
            raise ValueError('record is not a method package')
        spec = validate_method(package['spec'])
        source = self.realm._reference(exact_reference(package['artifact_source']), records)
        self.realm._authorized(policy, 'read', source['metadata']['scope'])
        assets = source['metadata'].get('source', {}).get('assets', [])
        if len(assets) != 1 or assets[0]['sha256'] != spec['artifact_digest']:
            raise ValueError('exact single method artifact required')
        historical = source.get('snapshot_revision')
        files = self.realm.store.snapshot(historical)['files'] if historical else snapshot['files']
        artifact = files[assets[0]['path']]
        if sha(artifact) != spec['artifact_digest']:
            raise ValueError('artifact digest mismatch')
        current = records.get(row['metadata']['id'])
        return {'reference': method_reference(row), 'realm_id': realm['id'], 'spec': spec,
                'artifact': artifact, 'title': row['metadata']['title'], 'explanation': row['body'],
                'artifact_source': method_reference(source),
                'current': bool(current and current['digest'] == row['digest'])}

    def evaluation(self, reference, receipt, *, key):
        self.load(reference)
        request = ['evaluation', reference, receipt]
        def build():
            identifier = 'source:method-evaluation-' + sha([reference, key])
            asset_path = self.source_root + '/' + identifier + '/evaluation.json'
            data = canonical(receipt)
            metadata = self._meta(identifier, 'source', 'Method evaluation', basis=[reference],
                                  source={'assets': [{'path': asset_path, 'sha256': sha(data)}]})
            raw = self.realm.codec.encode(metadata)
            proposal = self.realm.propose({self.record_root + '/' + identifier + '.md': raw, asset_path: data})
            return proposal, {'reference': {'id': identifier, 'revision': 1, 'digest': 'sha256:' + sha(raw)},
                              'accepted': False}, []
        return self._apply('evidence-' + key, request, build)

    @_one_read_view
    def evidence(self, reference):
        snapshot, _, policy, records, row = self._read(reference.get('reference', reference))
        assets = row['metadata'].get('source', {}).get('assets', [])
        if len(assets) != 1:
            raise ValueError('exact evaluation source required')
        files = self.realm.store.snapshot(row.get('snapshot_revision'))['files']
        raw = files[assets[0]['path']]
        if sha(raw) != assets[0]['sha256']:
            raise ValueError('evaluation source changed')
        return json.loads(raw)

    def admit(self, reference, evidence, *, explanation, key):
        self.load(reference)
        evidence = exact_reference(evidence.get('reference', evidence))
        request = ['admit', reference, evidence, explanation]
        def build():
            identifier = 'decision:method-use-' + sha([reference, key])
            metadata = self._meta(identifier, 'decision', 'Locally admitted method',
                basis=[reference, evidence], commitment={'expectation': explanation},
                method_admission={'method': reference, 'evaluation': evidence, 'status': 'available'},
                review={'triggers': ['changed_basis', 'failed_expectation'],
                        'when': ['The method becomes unsuitable for its declared work or environment.']})
            raw = self.realm.codec.encode(metadata, explanation)
            proposal = self.realm.propose({self.record_root + '/' + identifier + '.md': raw})
            return proposal, {'admission': {'id': identifier, 'revision': 1, 'digest': 'sha256:' + sha(raw)},
                              'accepted': True, 'automatic_execution': False}, [identifier]
        return self._apply(key, request, build)

    def _governing(self):
        snapshot, _, policy, records = self._snapshot()
        accepted = self.realm._acceptances(snapshot, records)
        now = self.realm._time(self.realm._now())
        active = {k for k in accepted if (not records[k]['metadata'].get('valid_until')
                  or now < self.realm._time(records[k]['metadata']['valid_until']))
                  and (not records[k]['metadata'].get('valid_from')
                       or now >= self.realm._time(records[k]['metadata']['valid_from']))}
        replaced = set()
        for key in active:
            for ref in self.realm._links(records[key]['metadata'], 'supersedes'):
                row = self.realm._reference(ref, records)
                if row['metadata']['id'] in records and records[row['metadata']['id']]['digest'] == row['digest']:
                    replaced.add(row['metadata']['id'])
        return policy, records, active - replaced

    @_one_read_view
    def active(self, reference):
        loaded = self.load(reference)
        if not loaded['current']:
            return {'active': False, 'reason': 'method superseded; re-evaluate exact new version'}
        policy, records, governing = self._governing()
        # An accepted hold may point *towards* an admission or another current
        # constraint in this work scope. The client must not rely on the direction
        # of the admission's own links, or on an ID without its pinned bytes.
        relevant = {key for key in governing if records[key]['metadata']['kind'] in ('decision','policy')
                    and set(records[key]['metadata']['scope']) & set(self.scopes)}
        if any(item['id'] in records and set(records[item['id']]['metadata']['scope']) & set(self.scopes)
               for item in self.realm._unverified_receipts):
            return {'active': False, 'reason': 'current acceptance evidence is incomplete'}
        for key in sorted(relevant):
            row = records[key]
            try: self.realm._query_readable(row, records, policy, self.scopes)
            except PermissionError:
                return {'active': False, 'reason': 'current commitment or grounds outside the selected projection'}
            for conflict in self.realm._links(row['metadata'], 'conflicts'):
                target = self.realm._reference(conflict, records)
                target_id = target['metadata']['id']
                if target_id in relevant and target['digest'] == records[target_id]['digest']:
                    return {'active': False, 'reason': 'unresolved accepted conflict in the current work scope'}
        for scope in self.scopes:
            for basis in records[scope]['metadata'].get('context', {}).get('basis', []):
                target = self.realm._reference(basis, records)
                target_id = target['metadata']['id']
                if target_id not in relevant or target['digest'] != records[target_id]['digest']:
                    return {'active': False, 'reason': 'declared context constraint is not current accepted authority'}
        for key in sorted(governing):
            row = records[key]; metadata = row['metadata']
            declaration = metadata.get('method_admission', {})
            if declaration.get('method') != reference or declaration.get('status') != 'available':
                continue
            self.realm._authorized(policy, 'read', metadata['scope'])
            if not set(metadata['scope']) <= set(self.scopes):
                continue
            self.realm._read_basis(metadata, records, policy)
            for ref in self.realm._links(metadata, 'basis'):
                if isinstance(ref, dict):
                    current = records.get(ref.get('id'))
                    if current is None or ref.get('digest') != 'sha256:' + current['digest']:
                        return {'active': False, 'reason': 'admission basis changed'}
            return {'active': True, 'admission': method_reference(row),
                    'evaluation': self.evidence(declaration['evaluation'])}
        return {'active': False, 'reason': 'no current local acceptance'}

    def retire(self, reference, *, explanation, basis, key):
        request = ['retire', reference, explanation, basis]
        def build():
            policy, records, governing = self._governing()
            admissions = [method_reference(records[k]) for k in sorted(governing)
                          if records[k]['metadata'].get('method_admission', {}).get('method') == reference
                          and records[k]['metadata']['method_admission'].get('status') == 'available']
            if not admissions:
                raise ValueError('active local method admission required for retirement')
            identifier = 'decision:method-retired-' + sha([reference, key])
            metadata = self._meta(identifier, 'decision', 'Retired local method',
                basis=[reference, *basis], supersedes=admissions,
                commitment={'expectation': explanation},
                method_admission={'method': reference, 'status': 'retired'})
            raw = self.realm.codec.encode(metadata, explanation)
            proposal = self.realm.propose({self.record_root + '/' + identifier + '.md': raw})
            return proposal, {'retirement': {'id': identifier, 'revision': 1, 'digest': 'sha256:' + sha(raw)},
                              'accepted': True, 'history_preserved': True}, [identifier]
        return self._apply(key, request, build)

    def outcome(self, reference, evidence, passed, *, key):
        active = self.active(reference)
        if not active['active']:
            return {'retained': False, 'reason': 'no active commitment to assess'}
        source_ref = exact_reference(evidence.get('reference', evidence))
        request = ['outcome', reference, source_ref, passed, active['admission']]
        def build():
            identifier = 'outcome:method-' + sha([reference, key])
            metadata = self._meta(identifier, 'outcome', 'Method re-evaluation result',
                basis=[reference, source_ref, active['admission']],
                outcome={'decision': active['admission']['id'], 'verdict': 'met' if passed else 'not_met'},
                assurance={'implementation': {'status': 'verified' if passed else 'failed', 'basis': [source_ref]},
                           'benefit': {'status': 'unknown', 'basis': []}})
            raw = self.realm.codec.encode(metadata, 'Bounded independent case evaluation; no causal effectiveness inference.')
            proposal = self.realm.propose({self.record_root + '/' + identifier + '.md': raw})
            return proposal, {'reference': {'id': identifier, 'revision': 1, 'digest': 'sha256:' + sha(raw)},
                              'retained': True, 'governs': False}, []
        return self._apply('outcome-' + key, request, build)

    def export(self, reference, *, destination, grants):
        loaded = self.load(reference)
        if not loaded['current']:
            raise ValueError('historical method must be explicitly released as a current candidate before export')
        bundle = self.realm.export([reference['id'], loaded['artifact_source']['id']],
                                   destination=destination, grants=grants)
        bundle['method_reference'] = reference
        return {'bundle': bundle, 'digest': sha(bundle), 'transferred_acceptance': False}

    def receive(self, bundle, *, expected_digest, method_id, key):
        if sha(bundle) != expected_digest or bundle.get('schema') != 'ekk.export/0.1':
            raise ValueError('exact exported method bundle required')
        _, realm, _, _ = self._snapshot()
        if bundle.get('destination') != realm['id']:
            raise PermissionError('method bundle belongs to another destination')
        # The host supplies the expected digest over a separately authorized transfer.
        # This check proves bytes, not a remote issuer's authority or authenticity.
        reference = exact_reference(bundle['method_reference'])
        files = {path: base64.b64decode(raw, validate=True) for path, raw in bundle['files'].items()}
        records = {}
        for path, raw in files.items():
            if path.endswith('.md'):
                record = self.realm.codec.decode(raw)
                records[record['metadata']['id']] = {**record, 'digest': sha(raw)}
        row = records.get(reference['id'])
        if not row or method_reference(row) != reference:
            raise ValueError('exported method identity differs')
        package = row['metadata']['method_package']
        spec = validate_method(package['spec'])
        source_ref = exact_reference(package['artifact_source'])
        source = records.get(source_ref['id'])
        if not source or method_reference(source) != source_ref:
            raise ValueError('exported artifact source identity differs')
        assets = source['metadata'].get('source', {}).get('assets', [])
        if len(assets) != 1 or assets[0]['sha256'] != spec['artifact_digest']:
            raise ValueError('exported artifact contract differs')
        artifact = files[assets[0]['path']]
        if sha(artifact) != spec['artifact_digest']:
            raise ValueError('exported artifact bytes differ')
        # Keep exact received source separately. Local IDs/admission are independent.
        request = ['receive', expected_digest, method_id, self.scopes]
        def build():
            source_id = 'source:received-method-' + sha([method_id, key])
            asset_path = self.source_root + '/' + source_id + '/bundle.json'
            metadata = self._meta(source_id, 'source', 'Received method bundle',
                source={'assets': [{'path': asset_path, 'sha256': expected_digest}]})
            raw = self.realm.codec.encode(metadata)
            proposal = self.realm.propose({self.record_root + '/' + source_id + '.md': raw, asset_path: canonical(bundle)})
            return proposal, {'reference': {'id': source_id, 'revision': 1, 'digest': 'sha256:' + sha(raw)}}, []
        received = self._apply('receive-' + key, request, build)
        local = self.candidate(method_id=method_id, title=row['metadata']['title'], spec=spec, artifact=artifact,
            explanation=row['body'], basis=[received['reference']], key='candidate-' + key)
        return {**local, 'received_source': received['reference'], 'accepted': False,
                'origin_acceptance_imported': False}
