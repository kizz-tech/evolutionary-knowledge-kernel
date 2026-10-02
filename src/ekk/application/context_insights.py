"""Actor-neutral insights over an application-authorized record projection.

Callers own routing, current heads, exact historical resolution, and byte-budget
closure. A resolver returns a readable record for a *named* reference, or None
when unavailable. This module neither fetches source bodies nor decides whether
an assertion is true, accepted, superseded, or permitted to execute.
"""
from collections.abc import Mapping
import json

from ..model import validate_reference


CHALLENGE_KINDS = frozenset(('claim', 'question', 'observation', 'note'))


def _rows(records):
    return list(records.values()) if isinstance(records, Mapping) else list(records)


def _exact(record, realm_id):
    metadata = record['metadata']
    reference = {'realm': realm_id, 'id': metadata['id'],
                 'revision': metadata['revision'],
                 'digest': 'sha256:' + record['digest'].removeprefix('sha256:')}
    validate_reference(reference, pinned=True)
    return reference


def _key(reference):
    return tuple(reference[field] for field in ('realm', 'id', 'revision', 'digest'))


def _links(metadata, field):
    relations = {'basis': ('derived_from', 'depends_on'),
                 'conflicts': ('contradicts',), 'supersedes': ('supersedes',)}
    refs = list(metadata.get(field, []))
    for relation in metadata.get('relations', []):
        if relation['rel'] in relations.get(field, ()):
            refs.append({'id': relation['target'], **{
                key: relation[key] for key in ('realm', 'revision', 'digest', 'snapshot')
                if key in relation}})
    return refs


def _grounds(metadata):
    refs = _links(metadata, 'basis') + list(metadata.get('depends_on', []))
    refs.extend(metadata.get('context', {}).get('basis', []))
    refs.extend(ref for assertion in metadata.get('assurance', {}).values()
                for ref in assertion.get('basis', []))
    refs.extend(metadata.get('evolution', {}).get('propagation_basis', []))
    return refs


def _resolver(resolve_reference, realm_id):
    """Fail closed on unavailable, foreign, or mismatched named references."""
    def resolve(raw):
        ref = {'id': raw} if isinstance(raw, str) else dict(raw)
        ref['id'] = ref.get('id', ref.get('target'))
        if ref.get('realm', realm_id) != realm_id:
            return None
        try:
            record = resolve_reference(ref)
            if record is None:
                return None
            exact = _exact(record, realm_id)
            if (exact['id'] != ref['id']
                    or ('revision' in ref and exact['revision'] != ref['revision'])
                    or ('digest' in ref and exact['digest'] !=
                        'sha256:' + ref['digest'].removeprefix('sha256:'))):
                return None
            return record
        except (PermissionError, ValueError):
            return None
    return resolve


def _heads(records):
    current = {}
    for record in _rows(records):
        key = record['metadata']['id']
        if key in current:
            raise ValueError('Supply one current readable record per ID')
        current[key] = record
    return current


def related_candidates(anchors, eligible_records, *, realm_id, resolve_reference):
    """Return current candidate IDs for the caller's ordinary budget closure.

    Only explicit challenges to exact anchors and different current heads of
    pinned grounds qualify. Eligibility and currentness are caller-supplied;
    the result makes no statement about records outside that projection.
    """
    anchors = _rows(anchors)
    selected = {_key(_exact(row, realm_id)) for row in anchors}
    selected_ids = {reference[1] for reference in selected}
    current = _heads(eligible_records)
    resolve = _resolver(resolve_reference, realm_id)
    candidates = set()
    incomplete = False
    for key, row in sorted(current.items()):
        if row['metadata']['kind'] not in CHALLENGE_KINDS:
            continue
        for ref in _links(row['metadata'], 'conflicts'):
            target_id = ref if isinstance(ref, str) else ref.get('id', ref.get('target'))
            if target_id not in selected_ids:
                continue
            target = resolve(ref)
            if target is None:
                incomplete = True
            elif _key(_exact(target, realm_id)) in selected:
                candidates.add(key)
    for row in anchors:
        for ref in _grounds(row['metadata']):
            if not isinstance(ref, dict) or not (ref.get('revision') or ref.get('digest')):
                continue
            pinned = resolve(ref)
            if pinned is None:
                incomplete = True
                continue
            head = current.get(pinned['metadata']['id'])
            if head is None:
                incomplete = True
            elif _exact(pinned, realm_id) != _exact(head, realm_id):
                candidates.add(head['metadata']['id'])
    return {'ids': sorted(candidates), 'incomplete': incomplete,
            'coverage': 'supplied readable candidates only'}


def context_insights(records, current_records, *, realm_id, resolve_reference,
                     limit=32, incomplete=False, byte_budget=8192):
    """Project bounded insights using only exact references in emitted records.

    A superseded target is the one reference that may name a record outside the
    emitted rows; it must still resolve through the caller's authorized resolver.

    ``limit`` caps the total rows across all three lists. Challenges and changed
    grounds precede statement summaries. Missing dependencies and truncation
    produce only generic flags, never omitted IDs, titles, digests, or counts.
    ``incomplete`` covers any truncation; ``relations_incomplete`` is true only
    when a challenge, a changed ground or a reference behind one may be missing.
    ``governs`` is copied from each emitted row; disagreements cannot alter it.
    Supersession links are recorded provenance, not an inferred adjudication.
    """
    if type(limit) is not int or limit < 0:
        raise ValueError('insight limit must be a nonnegative integer')
    if type(byte_budget) is not int or byte_budget < 512:
        raise ValueError('insight byte budget must be at least 512 bytes')
    records = _rows(records)
    current = _heads(current_records)
    emitted = {_key(_exact(row, realm_id)) for row in records}
    resolve = _resolver(resolve_reference, realm_id)
    missing = bool(incomplete)
    statements, challenges, changed_grounds = [], [], []
    seen_challenges, seen_changes = set(), set()

    def visible(raw):
        nonlocal missing
        record = resolve(raw)
        if record is None or _key(_exact(record, realm_id)) not in emitted:
            missing = True
            return None
        return record

    for row in sorted(records, key=lambda r: _key(_exact(r, realm_id))):
        metadata = row['metadata']
        reference = _exact(row, realm_id)
        basis, supersedes = {}, {}
        for ref in _grounds(metadata):
            pinned = visible(ref)
            if pinned is None:
                continue
            pinned_ref = _exact(pinned, realm_id)
            basis[_key(pinned_ref)] = pinned_ref
            if not isinstance(ref, dict) or not (ref.get('revision') or ref.get('digest')):
                continue
            head = current.get(pinned_ref['id'])
            if head is None:
                missing = True
                continue
            current_ref = _exact(head, realm_id)
            if current_ref == pinned_ref:
                continue
            if _key(current_ref) not in emitted:
                missing = True
                continue
            marker = (_key(reference), _key(pinned_ref), _key(current_ref))
            if marker not in seen_changes:
                changed_grounds.append({'statement': reference, 'pinned': pinned_ref,
                                        'current': current_ref,
                                        'status': 'pinned_ground_differs'})
                seen_changes.add(marker)
        for ref in _links(metadata, 'supersedes'):
            # Optional reading names its replaced predecessor without emitting
            # its body, so a readable target is listed even when not emitted.
            target = resolve(ref)
            if target is None:
                missing = True
            else:
                target_ref = _exact(target, realm_id)
                supersedes[_key(target_ref)] = target_ref
        if metadata['kind'] in CHALLENGE_KINDS:
            for ref in _links(metadata, 'conflicts'):
                target = visible(ref)
                if target is None:
                    continue
                target_ref = _exact(target, realm_id)
                marker = (_key(reference), _key(target_ref))
                if marker not in seen_challenges:
                    challenges.append({'statement': reference, 'target': target_ref,
                                       'relation': 'contradicts',
                                       'status': 'recorded_disagreement'})
                    seen_challenges.add(marker)
        statements.append({'reference': reference, 'kind': metadata['kind'],
                           'created_by': metadata['created_by'],
                           'attribution': 'recorded',
                           'content_role': ('source_record' if metadata['kind'] == 'source'
                                            else 'recorded_statement'),
                           'basis': [basis[key] for key in sorted(basis)],
                           'supersedes': [supersedes[key] for key in sorted(supersedes)],
                           'governs': bool(row.get('governs', False))})
    output = {}
    remaining = limit
    omitted = relations_cut = missing
    for name, rows in (('challenges', challenges), ('changed_grounds', changed_grounds),
                       ('statements', statements)):
        output[name] = rows[:remaining]
        omitted |= len(rows) > remaining
        relations_cut |= name != 'statements' and len(rows) > remaining
        remaining -= len(output[name])
    result = {'schema': 'ekk.context-insights/0.1', **output,
            'incomplete': bool(omitted), 'omitted': bool(omitted),
            'relations_incomplete': bool(relations_cut),
            'coverage': 'emitted projection only', 'authority_effect': 'none',
            'adjudication': 'not_inferred', 'byte_budget': byte_budget}
    def size(): return len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode())
    while size() > byte_budget:
        for name in ('statements', 'changed_grounds', 'challenges'):
            if result[name]:
                result[name].pop()
                # Setting the flag never grows the output: true is shorter than false.
                result['relations_incomplete'] |= name != 'statements'
                break
        result['incomplete'] = result['omitted'] = True
    return result
