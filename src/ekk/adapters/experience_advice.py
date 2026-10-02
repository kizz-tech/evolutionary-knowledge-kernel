"""Shadow advice over observer state.

The configured advisor labels what waits for the owner's review: correction
candidates and held results (triage), and the items of noted entries
(relevance). Labels are stored beside the owner's later verdicts so that the
two can be compared. Nothing here changes what is recorded, shown or ranked.
"""
import json

from ..application import experience as rules
from ..application.semantic_shadow import MAX_CANDIDATES, semantic_shadow
from ..application.triage_shadow import MAX_ITEMS, MAX_TEXT_CHARS, triage_shadow
from .advisor_process import load_advisor
from .experience_store import ExperienceStore


def _batches(rows, size):
    return [rows[start:start + size] for start in range(0, len(rows), size)]


def _pinned(item, realm):
    if not (item.get('id') and item.get('revision') and item.get('digest') and item.get('title')):
        return None
    return {'reference': {'realm': realm, 'id': item['id'], 'revision': item['revision'], 'digest': item['digest']},
            'title': str(item['title'])[:512], 'excerpt': ''}


def advise(limit=50):
    advisor = load_advisor()
    if advisor is None:
        return {'schema': 'ekk.observer-advice/0.1', 'status': 'not_configured',
                'meaning': 'No advisor is configured; nothing was labelled.'}
    model = '{id}@{revision}'.format(**advisor.model)
    size = min(MAX_ITEMS, MAX_CANDIDATES, advisor.max_batch)
    store = ExperienceStore()
    counts = {'triage_labelled': 0, 'relevance_labelled': 0, 'unavailable_batches': 0}
    try:
        done = {(row['target'], row['operation']) for row in store.advice() if row['model'] == model}
        texts = [(event['id'], event['text']) for event in store.events(kind='correction', state='pending') if event['text']]
        for episode in store.episodes('held'):
            request = json.loads(episode['request'] or '{}')
            texts.append((episode['key'].rsplit('-', 1)[-1], (request.get('title', '') + '\n' + request.get('body', ''))))
        waiting = [{'id': target, 'text': text[:MAX_TEXT_CHARS]} for target, text in texts if (target, 'triage') not in done][:limit]
        for batch in _batches(waiting, size):
            shadow = triage_shadow(batch, advisor)
            if shadow['status'] != 'observed':
                counts['unavailable_batches'] += 1
                continue
            for decision in shadow['decisions']:
                store.note_advice(decision['id'], 'triage', model, decision['label'], decision['probabilities'])
                counts['triage_labelled'] += 1
        for delivery in store.deliveries()[:limit]:
            listed = rules.review_items(delivery)
            candidates = [(position, _pinned(item, delivery['realm'])) for position, item in enumerate(listed)]
            candidates = [(position, row) for position, row in candidates
                          if row and (f'{delivery["id"]}:{position}', 'relevance') not in done]
            if not candidates or not delivery['task']:
                continue
            for batch in _batches(candidates, size):
                shadow = semantic_shadow(delivery['task'], [row for _, row in batch], advisor)
                if shadow['status'] != 'observed':
                    counts['unavailable_batches'] += 1
                    continue
                for (position, _), decision in zip(batch, shadow['decisions']):
                    store.note_advice(f'{delivery["id"]}:{position}', 'relevance', model, decision['label'], decision['probabilities'])
                    counts['relevance_labelled'] += 1
        return {'schema': 'ekk.observer-advice/0.1', 'status': 'observed', 'model': advisor.model, **counts,
                'agreement': agreement(store, model),
                'meaning': 'Shadow labels only. They are compared with the owner\'s verdicts and applied nowhere.'}
    finally:
        store.close()


def agreement(store, model):
    """How the advisor's labels compare with the owner's verdicts on the same items."""
    advice = {(row['target'], row['operation']): row['label'] for row in store.advice() if row['model'] == model}
    def compare(pairs):
        pairs = [(owner, positive) for owner, positive in pairs if positive is not None]
        return {'judged': len(pairs), 'agree': sum(owner == positive for owner, positive in pairs)}
    kept = lambda labels, positive: [(bool(verdict), None if advice.get((target, 'triage')) is None else advice[(target, 'triage')] in positive)
                                     for target, verdict in labels.items()]
    relevance = []
    for delivery in store.deliveries():
        for position, verdict in (delivery['labels'] or {}).items():
            label = advice.get((f'{delivery["id"]}:{position}', 'relevance'))
            relevance.append((bool(verdict), None if label is None else label in ('primary', 'supporting')))
    return {'corrections_kept_vs_label_correction': compare(kept(store.labels('correction'), ('correction',))),
            'held_results_kept_vs_label_finding_or_decision': compare(kept(store.labels('episode'), ('finding', 'decision'))),
            'items_relevant_vs_label_primary_or_supporting': compare(relevance)}
