"""0.10.0's review-page parser, frozen: the rollback target's reading of a page.

Extracted verbatim from `git show c1b132a:src/ekk/application/experience.py`:
`_BOX`, `_RECORD_AS` and `parse_review`, the only names parse_review uses. A page
written by this runtime must give the same marks here as under its own parser.
"""
import re


_BOX = re.compile(r'^- \[(?P<mark>[ xXaAnN-])\] .*<!-- (?P<kind>delivery|item|correction|outcome|episode|decision):(?P<id>[0-9a-f]{8,64}) -->\s*$')
_RECORD_AS = re.compile(r'^\s+record as:\s*(?P<text>.*?)\s*$')


def parse_review(text):
    """Marks from a review page: judged deliveries with item verdicts, corrections, held episodes, outcomes, decisions.

    A correction kept with `[a]` carries ``owner_wide``: it is recorded for every
    project rather than this one.
    """
    result = {'deliveries': {}, 'corrections': {}, 'episodes': {}, 'outcomes': {}, 'decisions': {}}
    current, correction = None, None
    for line in text.splitlines():
        statement = _RECORD_AS.match(line)
        if statement and correction is not None:
            result['corrections'][correction]['statement'] = statement['text']
            correction = None
            continue
        correction = None
        match = _BOX.match(line)
        if not match:
            continue
        mark, kind, identity = match['mark'].lower(), match['kind'], match['id']
        verdict = True if mark in 'xa' else False if mark in 'n-' else None
        if kind == 'delivery':
            current = identity if verdict else None
            if verdict:
                result['deliveries'][identity] = {}
        elif kind == 'item':
            # An unmarked item of a judged delivery is "not relevant".
            if current and identity.startswith(current[:16]):
                result['deliveries'][current][int(identity[16:])] = bool(verdict)
        elif kind == 'correction' and verdict is not None:
            result['corrections'][identity] = {'keep': verdict, 'statement': '', 'owner_wide': mark == 'a'}
            correction = identity
        elif kind == 'episode' and verdict is not None:
            result['episodes'][identity] = verdict
        elif kind == 'outcome' and verdict is not None:
            result['outcomes'][identity] = verdict
        elif kind == 'decision' and verdict is not None:
            result['decisions'][identity] = verdict
    return result
