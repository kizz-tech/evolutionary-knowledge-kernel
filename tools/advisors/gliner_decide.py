#!/usr/bin/env python3
"""EKK advisor process for GLiNER2 classification checkpoints (GLiNER2.5-Decide).

Runs in the model's own Python environment (gliner2 and torch), never in EKK's,
and imports nothing from EKK. It reads one ``ekk.advisor-request/0.1`` JSON
object from standard input and prints one ``ekk.advisor-response/0.1`` object
to standard output; the contract is described in ekk/adapters/advisor_process.py.
Everything else, including library banners, goes to standard error.

    python gliner_decide.py --model WEIGHTS_DIR --model-id ID --revision REV

The weights are loaded from the local directory only (HF_HUB_OFFLINE=1).
``download-provenance.json`` beside the weights must name the same ``repo`` as
--model-id and the same ``revision`` as --revision, so the reported identity
is not just an echo of the config; the response then says
``"identity_verified": true``. A provenance value that differs always fails. A
missing or unreadable file, or one without both values, fails too unless
--allow-unverified is given, and the response then says false. The provenance
file is the downloader's own record: this is a consistency check, not a digest
of the weights.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import sys
import time

REQUEST_SCHEMA = 'ekk.advisor-request/0.1'
RESPONSE_SCHEMA = 'ekk.advisor-response/0.1'
PROMPTS = {
    'relevance': 'Decide how relevant the candidate is to the task.',
    'triage': 'Classify this message from a coding-agent session.',
}
TASK_KEY = 'decision'
PROVENANCE_NAME = 'download-provenance.json'
# The model card states 512 encoder positions.
TOKEN_LIMIT = 512
TOKEN_MARGIN = 24
BATCH_SIZE = 8


def fail(message, code=2):
    print('gliner_decide: ' + message, file=sys.stderr)
    raise SystemExit(code)


def read_request():
    try:
        request = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    except ValueError:
        fail('request is not valid JSON')
    if not isinstance(request, dict) or request.get('schema') != REQUEST_SCHEMA:
        fail('unsupported request schema')
    if request.get('operation') not in PROMPTS:
        fail('unsupported operation')
    labels, items = request.get('labels'), request.get('items')
    if (not isinstance(labels, dict) or len(labels) < 2
            or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v
                   for k, v in labels.items())):
        fail('labels must map at least two names to descriptions')
    if (not isinstance(items, list) or not items
            or any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
                   or not isinstance(row.get('text'), str) for row in items)):
        fail('items must be objects with id and text')
    task = request.get('task')
    if request['operation'] == 'relevance' and (not isinstance(task, str) or not task):
        fail('relevance needs a task')
    return request['operation'], task, labels, items


def verify_identity(model_dir, model_id, revision, allow_unverified=False):
    """Return whether the weights' provenance confirms the given identity."""
    try:
        recorded = json.loads((Path(model_dir) / PROVENANCE_NAME).read_bytes())
    except (OSError, ValueError, RecursionError):
        recorded = None
    if not isinstance(recorded, dict):
        recorded = {}
    known = {name: recorded.get(name) for name in ('repo', 'revision')}
    complete = all(isinstance(value, str) and value for value in known.values())
    if isinstance(known['revision'], str) and known['revision'] != revision:
        fail('weights revision differs from --revision')
    if isinstance(known['repo'], str) and known['repo'] != model_id:
        fail('weights repository differs from --model-id')
    if not complete and not allow_unverified:
        fail(PROVENANCE_NAME + ' is missing, unreadable or lacks repo and revision; '
             'pass --allow-unverified to run without the identity check')
    return complete


class Bounder:
    """Cuts text to a token budget; falls back to characters without a fast tokenizer."""

    def __init__(self, engine):
        tokenizer = getattr(getattr(engine, 'processor', None), 'tokenizer', None)
        self.tokenizer = tokenizer if getattr(tokenizer, 'is_fast', False) else None
        self.unit = 'tokens' if self.tokenizer else 'characters'

    def count(self, text):
        if self.tokenizer:
            return len(self.tokenizer(text, add_special_tokens=False)['input_ids'])
        return (len(text) + 1) // 2

    def cut(self, text, budget):
        """Return (text within budget, whether it was cut)."""
        budget = max(budget, 1)
        if not self.tokenizer:
            # Two characters per token is conservative for Cyrillic and code.
            return (text, False) if len(text) <= budget * 2 else (text[:budget * 2], True)
        offsets = self.tokenizer(text, add_special_tokens=False,
                                 return_offsets_mapping=True)['offset_mapping']
        if len(offsets) <= budget:
            return text, False
        return text[:offsets[budget - 1][1]], True


def compose(operation, task, labels, items, bounder):
    overhead = bounder.count(PROMPTS[operation] + ' ' + ' '.join(
        name + ' ' + description for name, description in labels.items()))
    budget = TOKEN_LIMIT - TOKEN_MARGIN - 4 * len(labels) - overhead
    texts, truncated = [], 0
    if operation == 'relevance':
        head, head_cut = bounder.cut(task, budget // 3)
        frame = 'Task: ' + head + '\nCandidate: '
        rest = budget - bounder.count(frame)
        for row in items:
            body, cut = bounder.cut(row['text'], rest)
            texts.append(frame + body)
            truncated += bool(cut or head_cut)
    else:
        for row in items:
            body, cut = bounder.cut(row['text'], budget)
            texts.append(body)
            truncated += bool(cut)
    return texts, truncated


def classify(engine, torch, operation, labels, texts):
    names = list(labels)
    base = {'labels': labels, 'prompt': PROMPTS[operation]}

    def run(extra):
        with torch.inference_mode():
            return engine.batch_classify_text(texts, {TASK_KEY: {**base, **extra}},
                                              batch_size=BATCH_SIZE, include_confidence=True)

    # Softmax over all labels with a zero threshold returns the whole distribution.
    rows = run({'multi_label': True, 'class_act': 'softmax', 'cls_threshold': 0.0})
    results = []
    for row in rows:
        value = row.get(TASK_KEY) if isinstance(row, dict) else None
        scores = ({entry.get('label'): entry.get('confidence') for entry in value
                   if isinstance(entry, dict)} if isinstance(value, list) else {})
        total = sum(v for v in scores.values() if isinstance(v, float))
        if set(scores) != set(names) or abs(total - 1.0) > 0.01:
            results = None
            break
        results.append({name: scores[name] / total for name in names})
    if results is not None:
        return 'model', results
    # Fallback: only the top label's probability is the model's; the rest is spread evenly.
    results = []
    for row in run({'multi_label': False}):
        value = row[TASK_KEY]
        top = min(max(float(value['confidence']), 1.0 / len(names)), 1.0)
        rest = (1.0 - top) / (len(names) - 1)
        results.append({name: top if name == value['label'] else rest for name in names})
    return 'top_label_only', results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--model', required=True, help='local weights directory')
    parser.add_argument('--model-id', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--allow-unverified', action='store_true',
                        help='run when the weights carry no usable provenance record')
    args = parser.parse_args()

    # Libraries print banners to stdout; keep the real stdout for the response only.
    response_fd = os.dup(1)
    os.dup2(2, 1)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'

    operation, task, labels, items = read_request()
    verified = verify_identity(args.model, args.model_id, args.revision, args.allow_unverified)

    started = time.perf_counter()
    import torch
    from gliner2 import AutoExtractor
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    engine = AutoExtractor.from_pretrained(args.model, map_location='cpu')
    engine.eval()
    load_seconds = time.perf_counter() - started

    bounder = Bounder(engine)
    texts, truncated = compose(operation, task, labels, items, bounder)
    started = time.perf_counter()
    distribution, rows = classify(engine, torch, operation, labels, texts)
    inference_seconds = time.perf_counter() - started

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != 'darwin':
        peak *= 1024
    response = {
        'schema': RESPONSE_SCHEMA,
        'model': {'id': args.model_id, 'revision': args.revision},
        'identity_verified': verified,
        'distribution': distribution,
        'truncated': truncated,
        'truncation_unit': bounder.unit,
        'results': [{'id': item['id'], 'label': max(row, key=row.get), 'probabilities': row}
                    for item, row in zip(items, rows)],
        'diagnostics': {'load_seconds': round(load_seconds, 3),
                        'inference_seconds': round(inference_seconds, 3),
                        'peak_rss_bytes': peak, 'token_limit': TOKEN_LIMIT},
    }
    with os.fdopen(response_fd, 'w', encoding='utf-8') as out:
        json.dump(response, out, ensure_ascii=False)
        out.write('\n')


if __name__ == '__main__':
    main()
