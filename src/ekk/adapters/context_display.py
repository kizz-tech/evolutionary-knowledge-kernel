"""Optional CLI display projection; never an application or acceptance input."""
from copy import deepcopy
import json
import re

NEXT = ['ekk fetch --id ID', 'ekk read-source --id ID', 'omit --brief for the full projection']
WHY = {'related': 'challenges or changes a ground of selected material',
       'successor': 'replaces selected material',
       'required': 'pinned for this workspace or a ground of a governing record',
       'dependency': 'ground of selected material'}
CLAIM = 'unaccepted record that claims to replace an accepted one'
# Challenges and successors first, then relevance order; pinned records last, as
# a title and reference, because they appear for every task.
GROUP = {'related': 0, 'successor': 0, 'ranked': 1, 'required': 2}
TITLE_ONLY = {'required'}
_FRONT_MATTER = re.compile(r'\A\s*---[ \t]*\n.*?\n(?:---|\.\.\.)[ \t]*(?:\n|\Z)', re.S)
_NOT_PROSE = re.compile(r'\s*(?:[-*+]\s|\d+[.)]\s|\||>|!\[|<!--)')
_RULE = re.compile(r'\s*(?:[-*_=]\s*){3,}$')
_SENTENCE_END = re.compile(r'[.!?…。](?=["\')\]»”]*(?:\s|$))')


def _size(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def _cut(text, limit):
    """At most limit characters, ending at a sentence boundary where one exists."""
    text = ' '.join((text or '').split())
    if len(text) <= limit:
        return text
    window = text[:limit]
    ends = [found.end() for found in _SENTENCE_END.finditer(text[:limit + 1]) if found.end() <= limit]
    if ends and ends[-1] >= limit // 4:
        return window[:ends[-1]]
    space = window.rfind(' ', 0, limit - 1)
    return (window[:space] if space >= limit // 2 else window[:limit - 1]) + '…'


def _abstract(body, limit):
    """The record's own opening: its first prose paragraph, else its first block.

    A leading YAML front-matter block, headings, rules and fenced code are skipped.
    """
    blocks, current, fenced = [], [], False
    for line in _FRONT_MATTER.sub('', body or '', count=1).splitlines():
        if line.lstrip().startswith(('```', '~~~')):
            fenced = not fenced
            line = ''
        if fenced or not line.strip() or line.lstrip().startswith('#') or _RULE.match(line):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line.strip())
    if current:
        blocks.append(current)
    chosen = next((block for block in blocks if not _NOT_PROSE.match(block[0])), blocks[0] if blocks else [])
    return _cut(' '.join(chosen), limit)


def _links(references, limit=3):
    return [{'id': ref['id'], 'title': ref.get('title', '')} for ref in references[:limit]]


def brief_context(result, *, budget=4000):
    """Agent view: required reading in full, then short items that say why they appear.

    Mandatory and governing records are never summarized away and are not counted
    against the budget, which bounds the bytes of the optional items. Other
    selected records become a title, the record's own abstract, the reason they
    were selected and an exact reference. Grounds of optional items are counted
    on the item with up to three references, not listed. `incomplete` reports
    required gaps only, including a governing record left out by the record
    budget; optional reading left out is named in `incomplete_reasons` and
    `omitted_count`.
    """
    if result.get('schema') == 'ekk.federated-context/0.1':
        return {'schema': 'ekk.federated-brief/0.2', 'atomic_across_realms': False,
                'contexts': [brief_context(child, budget=budget) for child in result['contexts']]}
    if result.get('status') == 'unbound':
        return deepcopy(result)
    if result.get('schema') != 'ekk.context/0.1':
        raise ValueError('Unsupported brief context')
    manifest = result['manifest']
    realm = manifest['realm_id']
    required, candidates = [], []
    for position, row in enumerate(result['records']):
        metadata = row['metadata']
        reference = {'realm': realm, 'id': row['id'], 'revision': metadata['revision'], 'digest': 'sha256:' + row['digest']}
        if row.get('mandatory') or row.get('governs'):
            required.append({**deepcopy(row), 'reference': reference})
            continue
        selection = row.get('selection', 'ranked')
        if selection == 'dependency':
            continue  # counted as `grounds` on the item it supports
        found = row.get('discovery') or {}
        candidates.append((GROUP.get(selection, 1), position, row, reference, selection, found))
    insights = result.get('insights') or {}
    left_out = [{'id': entry['id'], 'title': entry.get('title', '')} if isinstance(entry, dict) else {'id': entry, 'title': ''}
                for entry in manifest.get('omitted_governing', [])]
    gaps = [reason for reason, present in (
        ('blocked', result['blocked']), ('unknowns', result['unknowns']),
        ('reading_warnings', result.get('warnings')),
        # Truncated statement summaries hide no challenge; older payloads carry one flag only.
        ('challenges_not_shown', insights.get('relations_incomplete', insights.get('incomplete'))),
        ('governing_left_out', left_out)) if present]
    reasons = gaps + (['optional_reading_left_out'] if manifest.get('omitted') else [])
    output = {'schema': 'ekk.context-brief/0.3', 'realm': realm, 'scopes': result['scopes'],
              'task': result.get('task', ''), 'blocked': result['blocked'], 'incomplete': bool(gaps),
              'incomplete_reasons': reasons,
              'unknowns': result['unknowns'], 'conflicts': result['conflicts'], 'warnings': result.get('warnings', []),
              'required_reading': required, 'items': [], 'omitted_count': len(manifest.get('omitted', [])),
              'snapshot': manifest['snapshots'], 'next': list(NEXT)}
    if left_out:
        output['governing_left_out'] = left_out  # fetch each: it applies to this scope
    for key in ('repository_checks', 'realm_alias', 'owner_projection'):
        if key in result:
            output[key] = deepcopy(result[key])
    ranked_seen, used = 0, 0
    for _, _, row, reference, selection, found in sorted(candidates, key=lambda item: item[:2]):
        metadata = row['metadata']
        kind = 'preference' if isinstance(metadata.get('preference'), dict) else metadata['kind']
        item = {'title': metadata['title'], 'kind': kind, 'date': str(metadata.get('created_at', ''))[:10]}
        if selection not in TITLE_ONLY:
            width = 600 if selection == 'ranked' and ranked_seen < 2 else 400
            ranked_seen += selection == 'ranked'
            # A record without a body (an agent-retained source) shows its source text instead.
            summary = _abstract(row['body'], width) or _cut(found.get('excerpt'), width)
            if not summary and row.get('source_content'):
                output['omitted_count'] += 1  # a source without readable text adds only a title
                continue
            item['summary'] = summary
        matched = found.get('matched_terms', [])[:4]
        item['why'] = WHY.get(selection) or ('matches: ' + ', '.join(matched) if matched
                                             else 'current version of matching material' if row.get('replaces')
                                             else CLAIM if row.get('claims_to_replace') else 'matches: ')
        if selection in TITLE_ONLY:
            item['id'] = row['id']  # current version: ekk fetch --id ID
        else:
            item['ref'] = reference
        if row.get('tier') == 'archive':
            item['tier'] = 'archive'
        for field in ('replaces', 'superseded_by', 'claims_to_replace', 'replacement_claimed_by'):
            if row.get(field):
                item[field] = _links(row[field])
        if selection not in TITLE_ONLY and row.get('grounds'):
            item['grounds'] = row['grounds']
            if row.get('ground_refs'):
                item['ground_refs'] = _links(row['ground_refs'])
        work = metadata.get('work', {})
        if work.get('schema') == 'ekk.work/0.1':
            item['continuation'] = {k: v for k, v in work.items() if k in ('status', 'next_step', 'domain')}
        if selection == 'required':
            output['items'].append(item)  # pinned or required ground: always listed, title only
        elif used + _size(item) > budget:
            output['omitted_count'] += 1  # optional reading beyond the display target
        else:
            output['items'].append(item)
            used += _size(item)
    if output['omitted_count'] and 'optional_reading_left_out' not in reasons:
        reasons.append('optional_reading_left_out')
    return output


def compact_context(result):
    """The same agent view as --brief; both flags are accepted for compatibility."""
    return brief_context(result)
