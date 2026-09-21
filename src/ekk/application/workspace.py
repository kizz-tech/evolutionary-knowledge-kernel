"""Read-only intention entry: independent authorized projections, exact continuation.

The resolver owns routing and access. This coordinator neither chooses a fallback
store nor writes knowledge, tasks, grants, or personal preferences.
"""
import re
from ..model import validate_identifier


def exact_reference(ref):
    if not isinstance(ref, dict) or set(ref) != {'realm', 'id', 'revision', 'digest'}:
        raise ValueError('Exact resume requires realm, id, revision and digest')
    validate_identifier(ref['realm'])
    validate_identifier(ref['id'])
    if type(ref['revision']) is not int or ref['revision'] < 1:
        raise ValueError('Exact resume revision must be positive integer')
    if not isinstance(ref['digest'], str) or not re.fullmatch(r'(sha256:)?[0-9a-f]{64}', ref['digest']):
        raise ValueError('Exact resume requires SHA-256 digest')
    return {**ref, 'digest': 'sha256:' + ref['digest'].removeprefix('sha256:')}


def working_references(values, realm_id):
    """Explicit reading material, never an acceptance or an inferred owner."""
    if not isinstance(values, list) or len(values) > 16:
        raise ValueError('working_entries must contain at most 16 exact references')
    result = []
    for value in values:
        ref = exact_reference(value)
        if ref['realm'] != realm_id:
            raise ValueError('working entry belongs to another realm')
        if ref not in result:
            result.append(ref)
    return result


class WorkspaceService:
    def __init__(self, resolver):
        self.resolver = resolver

    def start(self, *, task='', budget=16000, resume=None):
        if not isinstance(task, str):
            raise ValueError('Intention must be text')
        ref = exact_reference(resume) if resume is not None else None
        routes = list(self.resolver())
        matches = [r for r in routes if ref and r['realm_id'] == ref['realm']]
        if ref and len(matches) != 1:
            raise ValueError('Resume requires one explicitly resolved realm route')
        if not routes:
            return {'status': 'unbound', 'context': None,
                    'instruction': 'No access to a knowledge realm was inferred.'}
        contexts = []
        for route in routes:
            if route['owner_projection'] not in ('personal', 'shared'):
                raise ValueError('Explicit projection owner required')
            selected = working_references(route.get('working_entries', []), route['realm_id'])
            if ref and route is matches[0] and ref not in selected:
                selected.append(ref)
            result = route['context'](route['scopes'], task=task, budget=budget, focus=selected)
            if result['manifest']['realm_id'] != route['realm_id']:
                raise ValueError('Context realm differs from resolved route')
            contexts.append({**result, 'work_view': work_view(result, route.get('method_availability')), 'realm_alias': route['realm_alias'],
                             'owner_projection': route['owner_projection']})
        return {'schema': 'ekk.federated-context/0.1', 'atomic_across_realms': False,
                'contexts': contexts, 'blocked': any(c.get('blocked', False) for c in contexts), 'entry': {'task': task, 'resume': ref,
                'mutations': 0, 'retained': False, 'owner_projections_separate': True}}


def work_view(context, method_availability=None):
    """Useful continuation anchors from the emitted projection, not a task database."""
    realm = context['manifest']['realm_id']
    rows = context['records']
    def anchor(row):
        return {'title': row['metadata']['title'], 'reference': {'realm': realm, 'id': row['id'],
                'revision': row['metadata']['revision'], 'digest': 'sha256:' + row['digest']}}
    selected = context['manifest'].get('forced_refs', [])
    offers = []
    for row in rows:
        declaration = row['metadata'].get('method_admission', {})
        if not row.get('governs') or declaration.get('status') != 'available':
            continue
        if method_availability is None or not method_availability(declaration['method']).get('active'):
            continue
        offers.append({'method': declaration['method'], 'admission': anchor(row)['reference'],
                       'execution': 'requires_current_canonical_and_host_admission'})
    return {'schema': 'ekk.work-view/0.1', 'intention': context.get('task', ''),
            'selected_material': [anchor(r) for r in rows if anchor(r)['reference'] in selected],
            'accepted_commitments': [anchor(r) for r in rows if r.get('governs')],
            'visible_questions': [anchor(r) for r in rows if r['metadata']['kind'] == 'question'],
            'visible_results': [anchor(r) for r in rows if r['metadata']['kind'] in ('outcome', 'observation')],
            'work_items': [{**anchor(r), **{key:value for key,value in r['metadata']['work'].items()
                if key in ('intention','direction','next_step','questions','status','domain','external')},
                'events_read':'use work show with the exact reference'}
                for r in rows if r['metadata'].get('work',{}).get('schema')=='ekk.work/0.1'],
            'method_offers': offers,
            'challenges': context.get('insights', {}).get('challenges', []),
            'changed_grounds': context.get('insights', {}).get('changed_grounds', []),
            'statement_attribution': 'recorded; not truth, trust or execution authority',
            'context_incomplete': bool(context['manifest'].get('incomplete')),
            'coverage': 'emitted projection only', 'retained_intention': False,
            'execution_authority': 'external owning runtime', 'human_understanding': 'not_inferred'}
