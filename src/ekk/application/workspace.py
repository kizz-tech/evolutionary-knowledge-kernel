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
            result = route['context'](route['scopes'], task=task, budget=budget,
                                      focus=[ref] if ref and route is matches[0] else [])
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
            'accepted_commitments': [anchor(r) for r in rows if r.get('governs')],
            'visible_questions': [anchor(r) for r in rows if r['metadata']['kind'] == 'question'],
            'visible_results': [anchor(r) for r in rows if r['metadata']['kind'] in ('outcome', 'observation')],
            'method_offers': offers,
            'coverage': 'emitted projection only', 'retained_intention': False,
            'execution_authority': 'external owning runtime', 'human_understanding': 'not_inferred'}
