"""Pure shadow projection for fallible triage of short observed texts.

The rubric is owned here and versioned; a replaceable advisor only assigns its
labels. The result is never applied: baseline rules keep deciding what an
observed text becomes until a measured gain is shown.

``identity_verified`` repeats the advisor's own statement that it checked the
loaded model against the reported identity; absent means it did not.
"""
import math
from typing import Protocol


SCHEMA = 'ekk.triage-shadow/0.1'
ADVICE_SCHEMA = 'ekk.triage-advice/0.1'
RUBRIC_VERSION = 'ekk.triage-rubric/1'
RUBRIC = {
    'correction': 'The owner corrects or redirects the agent.',
    'decision': 'A choice with its reason.',
    'finding': 'A result, measurement or diagnosis worth keeping.',
    'noise': 'Routine, chat or tool output.',
}
LABELS = tuple(RUBRIC)
DISTRIBUTIONS = ('model', 'top_label_only')
MAX_ITEMS = 32
MAX_ID_CHARS = 256
MAX_TEXT_CHARS = 2000


class TriageAdvisor(Protocol):
    def triage(self, *, items: list[dict]) -> dict: ...


def _bounded_text(value, label, limit):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError('Invalid ' + label)
    return value


def _items(items):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise ValueError('Item count must be between 1 and ' + str(MAX_ITEMS))
    ids, sent = [], []
    for index, row in enumerate(items):
        if not isinstance(row, dict) or set(row) != {'id', 'text'}:
            raise ValueError('Item must be an object with id and text')
        item_id = _bounded_text(row['id'], 'item id', MAX_ID_CHARS)
        if item_id in ids:
            raise ValueError('Duplicate item id')
        ids.append(item_id)
        sent.append({'item_id': 'i' + str(index),
                     'text': _bounded_text(row['text'], 'item text', MAX_TEXT_CHARS)})
    return ids, sent


def _model(raw):
    value = raw.get('model')
    if not isinstance(value, dict) or set(value) != {'id', 'revision'}:
        raise ValueError('Exact advisory model identity required')
    return {'id': _bounded_text(value['id'], 'model id', 256),
            'revision': _bounded_text(value['revision'], 'model revision', 256)}


def _probabilities(value):
    if not isinstance(value, dict) or set(value) != set(LABELS):
        raise ValueError('Complete advisory probabilities required')
    result = {}
    for label in LABELS:
        probability = value[label]
        if type(probability) not in (int, float) or not math.isfinite(probability):
            raise ValueError('Finite advisory probabilities required')
        probability = float(probability)
        if probability < 0.0 or probability > 1.0:
            raise ValueError('Advisory probability outside zero to one')
        result[label] = probability
    if abs(sum(result.values()) - 1.0) > 0.01:
        raise ValueError('Advisory probabilities must sum to one')
    return result


def _advice(raw, ids, sent):
    if not isinstance(raw, dict) or raw.get('schema') != ADVICE_SCHEMA:
        raise ValueError('Unsupported triage advice')
    model = _model(raw)
    distribution = raw.get('distribution', 'model')
    if distribution not in DISTRIBUTIONS:
        raise ValueError('Unknown advisory distribution')
    verified = raw.get('identity_verified', False)
    if type(verified) is not bool:
        raise ValueError('Invalid advisory identity verification flag')
    decisions = raw.get('decisions')
    if not isinstance(decisions, list) or len(decisions) != len(sent):
        raise ValueError('One advisory decision per item required')
    expected = {row['item_id'] for row in sent}
    projected = {}
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
                'item_id', 'label', 'probabilities'}:
            raise ValueError('Invalid advisory decision')
        item_id = decision['item_id']
        if item_id not in expected or item_id in projected:
            raise ValueError('Unknown or duplicate advisory item')
        if decision['label'] not in LABELS:
            raise ValueError('Unknown advisory label')
        probabilities = _probabilities(decision['probabilities'])
        if probabilities[decision['label']] != max(probabilities.values()):
            raise ValueError('Advisory label must match maximum probability')
        projected[item_id] = {'id': ids[int(item_id[1:])], 'label': decision['label'],
                              'probabilities': probabilities}
    return model, verified, distribution, [projected[row['item_id']] for row in sent]


def triage_shadow(items, advisor):
    """Return non-applying triage labels for short texts, in the caller's order.

    Caller input errors are explicit. Advisor absence, failure, and malformed
    output are contained as advisory unavailability so they cannot break the
    path that observed the texts.
    """
    ids, sent = _items(items)
    result = {'schema': SCHEMA, 'rubric': RUBRIC_VERSION, 'mode': 'shadow',
              'applied': False, 'authority_effect': 'none'}
    try:
        raw = advisor.triage(items=[dict(row) for row in sent])
        model, verified, distribution, decisions = _advice(raw, ids, sent)
    except Exception:
        return {**result, 'status': 'unavailable',
                'warning': 'Triage advice unavailable or invalid; nothing is labelled.'}
    return {**result, 'status': 'observed', 'model': model,
            'identity_verified': verified, 'distribution': distribution, 'decisions': decisions,
            'warning': 'Probabilities are fallible model output, not correctness or authority.'}
