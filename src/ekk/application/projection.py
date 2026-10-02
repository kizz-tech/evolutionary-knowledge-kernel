"""Documents as projections of the realm: a decision table rendered from records.

A projection reads the published view and writes nothing to the realm. The
rendered text is derived: the records stay the source, so a change is made to a
record and the document is generated again.
"""
from __future__ import annotations
import re

REASON_MARK = '**Reason, rejected alternative:**'
REVISIT_MARK = '**Revisit when:**'
PREAMBLE = "Generated from the realm's decision records on {date} by ekk project decisions; edit the records, not this table."
COLUMNS = ('ID', 'Decision', 'Reason / rejected alternative', 'Revisit when', 'State')
CELLS = ('id', 'decision', 'reason', 'revisit', 'state')


def paragraphs(body):
    return [part.strip() for part in re.split(r'\n\s*\n', body.strip()) if part.strip()]


def parts(body):
    """Statement, reason and revisit condition of a decision body.

    The canonical shape is the statement, then a paragraph that starts with the
    reason mark, then one that starts with the revisit mark. The statement is
    everything before the first marked paragraph, or the whole body without one.
    """
    found = paragraphs(body)
    cut = next((index for index, part in enumerate(found) if part.startswith((REASON_MARK, REVISIT_MARK))), None)
    def marked(mark):
        return next((part[len(mark):].strip() for part in found if part.startswith(mark)), '')
    statement = found if cut is None else found[:cut]  # a body that opens with a mark has no statement
    return '\n\n'.join(statement), marked(REASON_MARK), marked(REVISIT_MARK)


def natural(text):
    """Order with numbers compared as numbers: D-1.0-2 before D-1.0-10. Long digit runs compare as text."""
    return tuple((0, int(part)) if part.isdecimal() and len(part) <= 18 else (1, part.casefold())
                 for part in re.split(r'([0-9]+)', text) if part)


def decision_rows(app, scopes):
    """One row per readable decision record of the selected contexts, with its current state.

    State is `accepted` for a current acceptance, `superseded by ID` when another
    current, readable record supersedes the record's current bytes exactly, else
    `proposed`. An unaccepted record cannot take the place of an accepted one: its
    link is a claim and leaves the accepted row in force.
    """
    snapshot, _, policy, records = app._query_view(scopes)
    accepted = app._acceptances(snapshot, records)
    def readable(row):
        # The realm's read model: the record and its dependency closure inside the selected contexts.
        try: app._query_readable(row, records, policy, scopes)
        except PermissionError: return False
        return True
    visible = {key: row for key, row in records.items() if readable(row)}
    def exact_target(ref, own):
        # The entry rule: a reference pinned to an earlier version of its target,
        # or a record revising itself, replaces nothing.
        item = {'id': ref} if isinstance(ref, str) else ref
        target_id = item.get('id', item.get('target'))
        target = records.get(target_id)
        if target is None or target_id == own: return None
        if item.get('digest') and app._hash(item['digest']) != target['digest']: return None
        if item.get('revision') and item['revision'] != target['metadata']['revision']: return None
        if item.get('snapshot') and not (item.get('digest') or item.get('revision')) and item['snapshot'] != snapshot['revision']: return None
        return target_id
    successors = {}
    for key, row in visible.items():
        # Only a decision replaces a decision in this table; another kind is not a successor here.
        if row['metadata']['kind'] != 'decision': continue
        for ref in app._links(row['metadata'], 'supersedes'):
            target = exact_target(ref, key)
            if target is not None and not (target in accepted and key not in accepted):
                successors.setdefault(target, set()).add(key)
    counts = {}
    for key, row in visible.items():
        if key in successors: continue  # a replaced record no longer holds its alias
        for alias in row['metadata'].get('aliases') or []:
            counts[alias] = counts.get(alias, 0) + 1
    def shown(key):
        # An alias names a current row while no other current record claims it; a replaced
        # record keeps its alias as history unless a current record has taken it.
        wanted = 0 if key in successors else 1
        aliases = [alias for alias in records[key]['metadata'].get('aliases') or [] if counts.get(alias, 0) == wanted]
        return aliases[0] if aliases else key
    rows = []
    for key, row in visible.items():
        m = row['metadata']
        if m['kind'] != 'decision': continue
        statement, reason, revisit = parts(row['body'])
        declared = m.get('decision') if isinstance(m.get('decision'), dict) else {}
        when = (m.get('review') or {}).get('when') if isinstance(m.get('review'), dict) else None
        state = ('superseded by ' + ', '.join(sorted((shown(successor) for successor in successors[key]), key=natural)) if key in successors
                 else 'accepted' if key in accepted else 'proposed')
        rows.append({'id': shown(key), 'record_id': key, 'decision': statement,
                     'reason': declared['reason'] if isinstance(declared.get('reason'), str) and declared['reason'].strip() else reason,
                     'revisit': '; '.join(when) if isinstance(when, list) and when else revisit,
                     'state': state, 'created_at': str(m.get('created_at', ''))})
    rows.sort(key=lambda row: (natural(row['id']), row['created_at'], row['record_id']))
    return rows


def cell(text):
    """One line of table data: whitespace collapsed, control characters dropped, pipes escaped, bytes otherwise as recorded."""
    flat = ' '.join(''.join(ch if ch.isprintable() else ' ' for ch in str(text)).split())
    return flat.replace('|', '\\|')


def decisions_table(rows, date):
    """The Markdown document: a fixed preamble naming the generation date, then the table."""
    lines = [PREAMBLE.format(date=date), '', '| ' + ' | '.join(COLUMNS) + ' |', '| ' + ' | '.join('---' for _ in COLUMNS) + ' |']
    lines.extend('| ' + ' | '.join(cell(row[name]) for name in CELLS) + ' |' for row in rows)
    return '\n'.join(lines) + '\n'
