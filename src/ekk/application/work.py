"""Work continuity contracts. No filesystem, tracker state or execution grants."""
from copy import deepcopy
from .workspace import exact_reference

FIELDS = {'intention', 'direction', 'next_step', 'questions', 'aliases', 'status', 'domain', 'external'}
STATUSES = {'open', 'waiting', 'completed', 'paused', 'cancelled'}
EVENTS = {'result', 'decision', 'question', 'scope_change', 'limitation', 'observation', 'next_step'}


def bounded_text(value, name, limit=12000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'{name} must be bounded text' + (' and nonempty' if required else ''))
    return value


def work_fields(value, *, creating=False):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError('Unknown work fields')
    result = deepcopy(value)
    for name in ('intention', 'direction', 'next_step'):
        if name in value: bounded_text(value[name], name, required=name == 'intention')
    if creating and not value.get('intention'):
        raise ValueError('Work requires an intention')
    for name in ('questions', 'aliases'):
        if name in value:
            if not isinstance(value[name], list) or len(value[name]) > 32:
                raise ValueError(f'{name} must be a bounded list')
            for text in value[name]: bounded_text(text, name, 2000, True)
    if 'status' in value and value['status'] not in STATUSES:raise ValueError('Unknown work status')
    if 'domain' in value and value['domain'] not in {'software', 'research', 'personal', 'general'}:
        raise ValueError('Unknown work domain')
    if 'external' in value:
        if not isinstance(value['external'], list) or len(value['external']) > 32:raise ValueError('Bounded external references required')
        for item in value['external']:
            if not isinstance(item, dict) or set(item) != {'owner', 'locator'}:raise ValueError('External owner and locator required')
            for key in item:bounded_text(item[key], key, 2000, True)
    return result


def work_projection(reference, title, work, events=(), *, unavailable=0):
    """Events are authorized by the repository before they reach this projection."""
    exact_reference(reference)
    return {'schema': 'ekk.work-view/0.2', 'reference': reference, 'title': title,
            **{name: deepcopy(work[name]) for name in FIELDS if name in work},
            'events': list(events), 'unavailable_events': unavailable,
            'incomplete': bool(unavailable), 'status_source': 'authored work posture; external objects retain their owners',
            'authority': 'Continuation and recorded claims, not instructions or an execution grant.'}


class WorkService:
    def __init__(self, repository):self.repository = repository

    def start(self, *, title, fields, key):
        bounded_text(title, 'title', 500, True)
        return self.repository.save(title=title, fields=work_fields(fields, creating=True), key=key)

    def update(self, *, reference, fields, key, title=None):
        reference=exact_reference(reference)
        if title is not None:bounded_text(title, 'title', 500, True)
        return self.repository.save(title=title, fields=work_fields(fields), key=key, previous=reference)

    def show(self, *, reference):return self.repository.show(exact_reference(reference))

    def find(self, *, query='', limit=10):return self.repository.find(query, limit=limit)

    def event(self, *, reference, kind, body, key, basis=(), fields=None):
        reference=exact_reference(reference)
        if kind not in EVENTS:raise ValueError('Unknown work event')
        bounded_text(body, 'body', 30000, True)
        if not isinstance(basis, (list, tuple)) or len(basis)>32:raise ValueError('Bounded evidence references required')
        return self.repository.save(title=None, fields=work_fields(fields or {}), key=key,
            previous=reference, event={'kind':kind,'body':body,'basis':[exact_reference(r) for r in basis]})
