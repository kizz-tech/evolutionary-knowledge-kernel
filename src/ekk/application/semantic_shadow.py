"""Pure shadow projection for fallible semantic candidate advice."""
import copy
import math

from ..model import validate_reference


SCHEMA = 'ekk.semantic-shadow/0.1'
ADVICE_SCHEMA = 'ekk.semantic-advice/0.1'
LABELS = ('primary', 'supporting', 'background', 'irrelevant')
MAX_CANDIDATES = 32
MAX_TASK_CHARS = 2000
MAX_TITLE_CHARS = 512
MAX_EXCERPT_CHARS = 2000


def _bounded_text(value, label, limit, *, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value) or len(value) > limit:
        raise ValueError('Invalid ' + label)
    return value


def _candidate(row, index):
    if not isinstance(row, dict):
        raise ValueError('Candidate must be an object')
    reference = copy.deepcopy(row.get('reference'))
    validate_reference(reference, pinned=True)
    title = _bounded_text(row.get('title'), 'candidate title', MAX_TITLE_CHARS)
    excerpt = _bounded_text(row.get('excerpt', ''), 'candidate excerpt',
                            MAX_EXCERPT_CHARS, allow_empty=True)
    return {'candidate_id': 'c' + str(index), 'title': title, 'excerpt': excerpt}


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


def _advice(raw, candidates, baseline):
    if not isinstance(raw, dict) or raw.get('schema') != ADVICE_SCHEMA:
        raise ValueError('Unsupported semantic advice')
    model = _model(raw)
    verified = raw.get('identity_verified', False)
    if type(verified) is not bool:
        raise ValueError('Invalid advisory identity verification flag')
    decisions = raw.get('decisions')
    if not isinstance(decisions, list) or len(decisions) != len(candidates):
        raise ValueError('One advisory decision per candidate required')
    expected = {candidate['candidate_id'] for candidate in candidates}
    observed = set()
    projected = []
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
                'candidate_id', 'label', 'probabilities'}:
            raise ValueError('Invalid advisory decision')
        candidate_id = decision['candidate_id']
        if candidate_id not in expected or candidate_id in observed:
            raise ValueError('Unknown or duplicate advisory candidate')
        if decision['label'] not in LABELS:
            raise ValueError('Unknown advisory label')
        probabilities = _probabilities(decision['probabilities'])
        if probabilities[decision['label']] != max(probabilities.values()):
            raise ValueError('Advisory label must match maximum probability')
        observed.add(candidate_id)
        index = int(candidate_id[1:])
        projected.append({'reference': copy.deepcopy(baseline[index]['reference']),
                          'label': decision['label'],
                          'probabilities': probabilities})
    if observed != expected:
        raise ValueError('Incomplete advisory candidate coverage')
    return model, verified, projected


def semantic_shadow(task, candidates, advisor):
    """Return non-applying advice beside an unchanged authorized baseline.

    Caller input errors are explicit. Advisor absence, failure, and malformed
    output are contained as advisory unavailability so they cannot break the
    baseline read path.
    """
    task = _bounded_text(task, 'task', MAX_TASK_CHARS)
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise ValueError('Candidate count must be between 1 and ' + str(MAX_CANDIDATES))
    baseline = copy.deepcopy(candidates)
    advisor_candidates = [_candidate(row, index) for index, row in enumerate(candidates)]
    result = {'schema': SCHEMA, 'mode': 'shadow', 'applied': False,
              'authority_effect': 'none', 'baseline': baseline,
              'agent_recheck': {'required': True,
                  'instruction': 'Use the exact candidate reference and source read before reliance.'}}
    try:
        raw = advisor.advise(task=task, candidates=copy.deepcopy(advisor_candidates))
        model, verified, decisions = _advice(raw, advisor_candidates, baseline)
    except Exception:
        return {**result, 'status': 'unavailable',
                'warning': 'Semantic advice unavailable or invalid; baseline is unchanged.'}
    return {**result, 'status': 'observed', 'model': model, 'identity_verified': verified, 'decisions': decisions,
            'warning': 'Probabilities are fallible model output, not correctness or authority.'}

