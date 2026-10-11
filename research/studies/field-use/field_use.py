#!/usr/bin/env python3
"""Field evaluation of EKK in actual work, reconstructed from local host logs.

Reads Codex and Claude Code transcripts plus the EKK operation journal on this
machine, extracts every EKK command an agent ran, and reports adoption, cost,
retrieval behaviour, reuse, retention after changes, owner corrections and entry
use. Episodes contain private task text and record titles, so they are written
only to a private directory outside the repository
(default: <EKK data home>/../evaluation/field-use/<run>).

Reports describe observed behaviour, not causal benefit: agent models, tasks and
EKK versions change together, so metrics are stratified by model and version.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import statistics
import sys
import time

try:
    from ekk import observation
except ImportError:  # run from a checkout without the package installed
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
    from ekk import observation

ID_RE = re.compile(r'\b(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|legacy-[0-9a-f]{32})\b')
DELIVERED_ID_RE = re.compile(r'"id":\s*"(' + ID_RE.pattern.strip('\\b') + ')"')
# An invocation stands in command position; `ekk` inside prose, a grep pattern or a path argument is a mention.
EKK_RE = re.compile(r'''(?:^|[;&|\n(]|\$\()\s*(?:timeout\s+(?:-\S+\s+)*\S+\s+)?(?:\w+=\S+\s+)*(?:[\w./~-]*/)?ekk(?![\w-])((?:[ \t]+--?[\w-]+(?:[ =](?:'[^']*'|"[^"]*"|\$\([^)]*\)|[^\s'"-][^\s'"]*))?)*)[ \t]+([a-z][\w-]*)(?=(?:[ \t]+([a-z][\w-]*))?)''')
# A heredoc body is data for the command on its first line, never a command of its own.
HEREDOC_RE = re.compile(r'''(<<-?\s*(['"]?)(\w+)\2[^\n]*)\n.*?(?:\n[ \t]*\3[ \t]*(?=\n|$)|\Z)''', re.DOTALL)
TASK_RE = re.compile(r'''--(?:task|query)[ =](?:'([^']*)'|"([^"]*)"|(\S+))''')
COMMIT_RE = re.compile(r'(?:^|[\s;&|(])git\b(?:\s+-[cC]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+commit\b')
GROUPS = {'work', 'queue', 'task', 'source', 'guide', 'improve', 'method'}
READ_OPS = {'enter', 'context', 'search', 'fetch', 'read-source', 'work.find', 'work.show'}
WRITE_OPS = {'retain', 'capture', 'apply', 'queue.submit', 'work.start', 'work.update', 'work.event'}
RETAIN_OPS = {'retain', 'capture', 'queue.submit'}
RECEIPT_OPS = RETAIN_OPS | {'queue.status', 'queue.drain'}
RETAINED = ('published', 'queued')
CHANGE_TOOLS = {'Edit': 'file_path', 'Write': 'file_path', 'NotebookEdit': 'notebook_path'}
ANCHOR_LISTS = ('visible_results', 'selected_material', 'accepted_commitments', 'visible_questions', 'work_items')
MIN_TITLE_CHARS = 16
HOT_SHARE = 0.3
UNBOUND = '(unbound)'
# The runtime writes its own host label into experience.host (ekk.adapters.observe_hook); the study names
# hosts by their transcripts.
HOST_LABELS = {'claude-code': 'claude'}
# Version of the collector's part of the correction rule: which transcript records are owner turns and which
# owner messages follow a report. Changing that logic is a new version and needs a new baseline.
COLLECTOR_RULE = 'ekk.field-use-collector/1'
RESULT_ID_RE = re.compile(r'"result_reference":\s*\{[^{}]*?' + DELIVERED_ID_RE.pattern)
QUEUE_KEY_RE = re.compile(r'"key":\s*"([^"\\]+)"')
RULES = {rule.name: rule for rule in observation.CORRECTION_RULES}


def rule_digest(rule=observation.RULE_1):
    """Digest of the content of a correction rule: a baseline is bound to the rule itself, not to its name."""
    def source(pattern):
        return [pattern.pattern, pattern.flags]
    content = [rule.name, COLLECTOR_RULE, observation.MAX_CORRECTION_CHARS,
               [source(p) for p in rule.cues], source(rule.repeat), source(observation._SUPPORT_PASTE),
               source(rule.injected), source(observation._REQUEST_MARK), [source(p) for p in rule.blocks]]
    return 'sha256:' + hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def data_home():
    if os.environ.get('EKK_DATA_HOME'):
        return Path(os.environ['EKK_DATA_HOME']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/EKK/runtime'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'ekk'


def in_period(day, since, until):
    return (not since or day >= since) and (not until or day <= until)


_PROJECTS = {}


def project_of(cwd):
    """Nearest enclosing EKK-bound workspace, else the last two path parts."""
    return bound_project(cwd)[0]


def bound_project(cwd):
    """(project key, whether an EKK workspace binding encloses the directory)."""
    if not cwd:
        return '?', False
    if cwd in _PROJECTS:
        return _PROJECTS[cwd]
    path = Path(cwd.removeprefix('file://'))
    found = None
    for candidate in (path, *path.parents):
        if (candidate / '.ekk/workspace.yaml').is_file():
            found = str(candidate)
            break
    key = found or '/'.join(path.parts[-2:])
    _PROJECTS[cwd] = (key.replace(str(Path.home()), '~'), bool(found))
    return _PROJECTS[cwd]


def shell_text(command):
    """The command without heredoc bodies."""
    return HEREDOC_RE.sub(r'\1', command) if '<<' in command else command


def quoted(text):
    """For each position, whether it lies inside a quoted string rather than at command level or in $( )."""
    flags, stack, index = bytearray(len(text)), [], 0
    while index < len(text):
        char, top = text[index], stack[-1] if stack else None
        flags[index] = top in ("'", '"')
        if top == "'":
            if char == "'":
                stack.pop()
        elif char == '\\':
            index += 1
        elif char == '$' and text[index + 1:index + 2] == '(':
            stack.append('(')
            index += 1
        elif top == '"':
            if char == '"':
                stack.pop()
        elif char in ('"', "'"):
            stack.append(char)
        elif char == ')' and top == '(':
            stack.pop()
        index += 1
    return flags


def commits(command):
    """Whether the shell command runs `git commit`, as opposed to naming it inside a quoted pattern."""
    command = shell_text(command)
    flags = quoted(command)
    return any(not flags[match.end() - 1] for match in COMMIT_RE.finditer(command))


def invocations(command):
    """Each `ekk` invocation in a shell command: operation, task, flags and the record IDs it names."""
    rows = []
    command = shell_text(command)
    # `rg 'a|ekk retain'` and `pgrep -f "ekk enter"` put the word after a separator, but inside a quoted pattern.
    flags = quoted(command)
    matches = [match for match in EKK_RE.finditer(command) if not flags[match.start(2)]]
    for index, match in enumerate(matches):
        options, op, action = match.group(1) or '', match.group(2), match.group(3)
        if op in GROUPS and action:
            op = op + '.' + action
        end = matches[index + 1].start() if index + 1 < len(matches) else len(command)
        segment = command[match.start():min(end, match.start() + 4000)]
        task = TASK_RE.search(segment)
        rows.append({
            'op': op,
            'task': next((g for g in task.groups() if g), None) if task else None,
            'help': bool(re.search(r'\s--help\b|\s-h\b', segment)),
            'flags': sorted(f for f in ('brief', 'compact', 'wait', 'json', 'stdin', 'personal')
                            if re.search(r'--' + f + r'\b', options + segment)),
            'arg_ids': sorted(set(ID_RE.findall(segment))),
        })
    return rows


def receipt_state(output, exit_code=None):
    """published | queued | failed | unknown, judged by the receipt an agent saw, not by the exit code."""
    if re.search(r'"state":\s*"read_back_and_discoverable"', output):
        return 'published'
    # A durable local request, or a publication whose read-back or discovery is not confirmed yet.
    if re.search(r'"schema":\s*"ekk\.(?:retention-queued|outbox)/0\.1"', output) and re.search(
            r'"state":\s*"(?:local_pending|publishing|retry_pending|published_verification_pending)"', output):
        return 'queued'
    if re.search(r'"state":\s*"(?:published|read_back)"', output):
        return 'queued'
    if (re.search(r'"error":\s*[{"]', output) or 'Traceback (most recent call last)' in output
            or 'KeyboardInterrupt' in output or '"needs_attention"' in output or exit_code in (130, 143)):
        return 'failed'
    return 'unknown'


def json_values(output):
    """The top-level JSON objects in a command's output, and the tail that does not parse (a cut object)."""
    decoder, index, values = json.JSONDecoder(), output.find('{'), []
    while index != -1:
        try:
            value, end = decoder.raw_decode(output, index)
        except ValueError:
            return values, output[index:]
        values.append(value)
        index = output.find('{', end)
    return values, ''


def receipt_ids(receipt):
    """Records a publication receipt names as its own: the retained result and the sources published with it."""
    refs = [receipt.get('result_reference'), *listed(receipt.get('source_references'))]
    return [ref['id'] for ref in refs
            if isinstance(ref, dict) and isinstance(ref.get('id'), str) and ID_RE.fullmatch(ref['id'])]


def receipt_records(output):
    """What a retention receipt says about records.

    created_ids: records a publication receipt names itself; queue_keys: the queue keys the receipt names;
    published_keys: per queue key, the records of the publication the queue reports. Any other UUID in the
    output (a realm, a snapshot, a quoted record) is not a created record.
    """
    created, keys, published = [], [], {}
    values, cut = json_values(output)
    for value in values:
        if isinstance(value, dict) and value.get('schema') == 'ekk.result/0.1' and isinstance(value.get('data'), dict):
            value = value['data']
        if not isinstance(value, dict):
            continue
        if value.get('schema') == 'ekk.outbox/0.1':
            for row in listed(value.get('operations')):
                if isinstance(row, dict) and isinstance(row.get('key'), str):
                    keys.append(row['key'])
                    ids = receipt_ids(row['receipt']) if isinstance(row.get('receipt'), dict) else []
                    if ids:
                        published.setdefault(row['key'], []).extend(ids)
        elif value.get('schema') == 'ekk.retention-queued/0.1':
            if isinstance(value.get('key'), str):
                keys.append(value['key'])
        else:
            created += receipt_ids(value)
    if cut:
        # Output cut by `head` or a display limit: the result reference or the key may still be visible.
        created += RESULT_ID_RE.findall(cut)
        if re.search(r'"schema":\s*"ekk\.retention-queued/0\.1"', cut):
            keys += QUEUE_KEY_RE.findall(cut)[:1]
    return {'created_ids': sorted(set(created)), 'queue_keys': sorted(set(keys)),
            'published_keys': {key: sorted(set(ids)) for key, ids in published.items()}}


# Episode rows gained created_ids, queue_keys and published_keys in format 2; a run without
# the format cannot resolve its writes and says so instead of counting them as unresolved.
EPISODE_FORMAT = 2


def run_format(run):
    path = Path(run) / 'run.json'
    collected = json.loads(path.read_text()) if path.is_file() else {}
    return collected.get('episode_format')


def created_records(episodes):
    """(session, time, record IDs) of each successful retention, and how many have no known record ID.

    A published receipt names its records. A queued receipt names only its key; the records come from a
    `queue status` or `queue drain` receipt for the same key, in any session. A write whose publication no
    transcript shows stays unresolved: it is counted, never guessed from other UUIDs in the output.
    """
    by_key = collections.defaultdict(set)
    for e in episodes:
        for key, ids in (e.get('published_keys') or {}).items():
            by_key[key].update(ids)
    writes, unresolved = [], 0
    for e in episodes:
        if e['op'] not in RETAIN_OPS or e.get('help') or not succeeded(e):
            continue
        ids = set(e.get('created_ids') or ()).union(*(by_key.get(key, ()) for key in e.get('queue_keys') or ()))
        if ids:
            writes.append((e['session'], e.get('ts') or '', sorted(ids)))
        else:
            unresolved += 1
    return writes, unresolved


def succeeded(episode):
    """A write an agent could rely on: a receipt for retention, a clean exit for other operations."""
    if 'outcome' in episode:
        return episode['outcome'] in RETAINED
    return not episode.get('error') and episode.get('exit') in (0, None)


def parse_output(op, output, exit_code=None):
    """Derived facts only: size, IDs, error class, receipt state and, for entry, the delivered items."""
    facts = {'out_bytes': len(output.encode('utf-8', 'ignore')), 'ids': sorted(set(ID_RE.findall(output)))}
    if 'KeyboardInterrupt' in output:
        facts['error'] = 'interrupted'
    error = re.search(r'"error":\s*"([a-z_]+)"', output)
    if error and 'error' not in facts:
        facts['error'] = error.group(1)
    if op in RECEIPT_OPS:
        facts['outcome'] = receipt_state(output, exit_code)
        facts.update(receipt_records(output))
    if op not in ('enter', 'context') or '{' not in output:
        return facts
    try:
        data = json.JSONDecoder().raw_decode(output[output.find('{'):])[0]
    except ValueError:
        if op == 'enter':
            # Output cut by `head` or a display limit: the record IDs that reached the agent were still delivered.
            facts['items'] = [{'id': rid, 'kind': None, 'title': None, 'content_chars': None}
                              for rid in dict.fromkeys(DELIVERED_ID_RE.findall(output))]
        return facts
    if isinstance(data, dict) and data.get('schema') == 'ekk.result/0.1':
        data = data.get('data') or {}
    if not isinstance(data, dict):
        return facts
    facts['schema'] = data.get('schema')
    items, anchors = [], []
    for part in [data, *[c for c in listed(data.get('contexts')) if isinstance(c, dict)]]:
        for row in listed(part.get('records')):
            if isinstance(row, dict):
                meta = row.get('metadata') or {}
                items.append({'id': row.get('id'), 'kind': meta.get('kind'), 'title': meta.get('title'),
                              'content_chars': len(row.get('body') or '')})
        for key in ('required_reading', 'material', 'items'):
            for row in listed(part.get(key)):
                if isinstance(row, dict):
                    ref = row.get('reference') or row.get('ref')
                    content = row.get('summary') or row.get('excerpt') or row.get('body') or ''
                    # A title-only item (pinned or required) carries its own id and no content: size unknown, not zero.
                    items.append({'id': (ref.get('id') if isinstance(ref, dict) else None) or row.get('id'),
                                  'kind': row.get('kind') or (row.get('metadata') or {}).get('kind'),
                                  'title': row.get('title') or (row.get('metadata') or {}).get('title'),
                                  'content_chars': len(content) if content or ref else None})
        view = part.get('work_view') if isinstance(part.get('work_view'), dict) else {}
        for key in ANCHOR_LISTS:
            for row in listed(view.get(key)):
                ref = row.get('reference') if isinstance(row, dict) else None
                if isinstance(ref, dict) and ref.get('id'):
                    # An anchor names a record without its content: the size is unknown, not zero.
                    anchors.append({'id': ref['id'], 'kind': None, 'title': row.get('title'), 'content_chars': None})
    known = {i['id'] for i in items if i['id']}
    for anchor in anchors:
        if anchor['id'] not in known:
            known.add(anchor['id'])
            items.append(anchor)
    facts['items'] = items
    return facts


def listed(value):
    return value if isinstance(value, list) else []


def squash(text):
    return re.sub(r'[\W_]+', ' ', text.casefold()).strip()


def short_id(rid):
    return rid[:15] if rid.startswith('legacy-') else rid[:8]


def new_session(host, key):
    return {'host': host, 'file': None, 'files': 0, 'session': key, 'subagent': True, 'cwd': None, 'models': set(),
            'user_messages': 0, 'skill_read': False, 'start': None, 'end': None, 'file_changes': 0, 'commits': 0,
            '_root_cwd': False, '_owner': [], '_reports': [], '_all_reports': []}


def later_owner_texts(prompt):
    """The owner's words under each correction rule after rule 1, as (rule, text) pairs; '' where a rule excludes the turn."""
    return tuple((rule.name, observation.owner_text(prompt, rule)) for rule in observation.CORRECTION_RULES[1:])


def touch(session, stamp):
    if stamp:
        session['start'] = min(session['start'] or stamp, stamp)
        session['end'] = max(session['end'] or stamp, stamp)


def finish(session, rows, messages):
    """Session facts that need the whole thread: corrections after work and use of delivered entry items."""
    owner, reports, all_reports = (sorted(session.pop(key)) for key in ('_owner', '_reports', '_all_reports'))
    session.pop('_root_cwd')
    first_report = reports[0][0] if reports else None
    for stamp, text, later in owner:
        after = first_report is not None and first_report < stamp
        fix = after and observation.is_correction(text)
        # Owner turns are the ones rule 1 keeps; a later rule may exclude some of them and judges its own text.
        rules = {}
        for name, own in later:
            second = after and observation.is_correction(own, RULES[name])
            rules[name] = {'owner': bool(own), 'correction': second,
                           'repeat': second and observation.is_repeat(own, RULES[name])}
        messages.append({'host': session['host'], 'session': session['session'], 'ts': stamp, 'after_report': after,
                         'correction': fix, 'repeat': fix and observation.is_repeat(text), 'rules': rules})
    session['user_messages'] = len(owner)
    rows = sorted((r for r in rows if not r['help']), key=lambda r: r.get('ts') or '')
    squashed = [(stamp, text, squash(text)) for stamp, text in all_reports]
    for index, row in enumerate(rows):
        if row['op'] != 'enter':
            continue
        delivered = {i['id']: i.get('title') or '' for i in row.get('items') or [] if i.get('id')}
        fetched = {rid for later in rows[index + 1:] if later['op'] in ('fetch', 'read-source') for rid in later['arg_ids']}
        after = [r for r in squashed if r[0] >= (row.get('ts') or '')]
        used = {}
        for rid, title in delivered.items():
            mark = re.compile(r'(?<![\w-])' + re.escape(short_id(rid)))
            title = squash(title)
            if rid in fetched:
                used[rid] = 'fetch'
            elif any(mark.search(text) for _, text, _ in after):
                used[rid] = 'report_id'
            elif len(title) >= MIN_TITLE_CHARS and any(title in flat for _, _, flat in after):
                used[rid] = 'report_title'
        row['delivered'], row['used'] = len(delivered), used
    outcomes = collections.Counter(r['outcome'] for r in rows if r['op'] in RETAIN_OPS)
    session['retain'] = dict(outcomes)
    session['changed'] = bool(session['file_changes'] or session['commits'])
    session['retained'] = any(outcomes.get(state) for state in RETAINED)


def utc_day(path):
    return dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).date().isoformat()


def scan_codex(patterns, since, until):
    sessions, episodes = {}, []
    files = sorted({f for p in patterns for f in glob.glob(os.path.expanduser(p), recursive=True)})
    seen = set()
    for path in files:
        # A thread is appended to after its start day; only its last write bounds the period from below.
        day = re.search(r'rollout-(\d{4}-\d{2}-\d{2})T', Path(path).name)
        if (day and until and day.group(1) > until) or (since and utc_day(path) < since):
            continue
        if Path(path).stem in seen:
            continue
        seen.add(Path(path).stem)
        session, subagent, owner_thread = None, False, True
        with open(path, errors='replace') as stream:
            for number, line in enumerate(stream):
                head = line[:600]
                if number == 0:
                    meta = {}
                    if '"session_meta"' in head:
                        try:
                            meta = json.loads(line)['payload']
                        except (ValueError, KeyError):
                            pass
                    # Segments of one thread and its subagents carry the thread's session id.
                    key = meta.get('session_id') or Path(path).stem
                    session = sessions.setdefault(key, new_session('codex', key))
                    subagent = meta.get('thread_source') == 'subagent'
                    owner_thread = meta.get('thread_source') not in ('subagent', 'automation')
                    session['files'] += 1
                    if not subagent and session['subagent']:
                        session.update(subagent=False, cwd=meta.get('cwd'), file=path)
                    elif session['file'] is None:
                        session.update(cwd=meta.get('cwd'), file=path)
                    if meta:
                        continue
                stamp = head[14:head.find('"', 14)] if head.startswith('{"timestamp":"') else ''
                if not in_period(stamp[:10], since, until):
                    continue
                touch(session, stamp)
                kind = head[:120]
                if '"type":"turn_context"' in kind:
                    model = re.search(r'"model":\s*"([^"]+)"', line)
                    if model:
                        session['models'].add(model.group(1))
                    continue
                if '"type":"event_msg"' not in kind:
                    continue
                if '"type":"task_complete"' in head:
                    try:
                        text = json.loads(line)['payload'].get('last_agent_message')
                    except (ValueError, KeyError):
                        continue
                    if isinstance(text, str) and text.strip():
                        session['_all_reports'].append((stamp, text))
                        if not subagent:
                            session['_reports'].append((stamp, text))
                    continue
                if '"type":"item_completed"' not in head:
                    continue
                if '"type":"CommandExecution"' in head:
                    if 'ekk' not in line and 'commit' not in line:
                        continue
                elif '"type":"FileChange"' not in head and not ('"type":"UserMessage"' in head and owner_thread):
                    continue
                try:
                    item = json.loads(line)['payload']['item']
                except (ValueError, KeyError):
                    continue
                if item.get('type') == 'FileChange':
                    session['file_changes'] += item.get('status') == 'completed' and bool(item.get('changes'))
                elif item.get('type') == 'UserMessage' and owner_thread:
                    prompt = '\n'.join(part.get('text') or '' for part in listed(item.get('content'))
                                       if isinstance(part, dict) and part.get('type') == 'text')
                    text = observation.owner_text(prompt)
                    if text:
                        session['_owner'].append((stamp, text, later_owner_texts(prompt)))
                elif item.get('type') == 'CommandExecution':
                    command = item.get('command')
                    command = str(command[-1]) if isinstance(command, list) and command else str(command)
                    if 'ekk-workflow/SKILL.md' in command:
                        session['skill_read'] = True
                    if item.get('exit_code') == 0 and 'commit' in command and commits(command):
                        session['commits'] += 1
                    calls = invocations(command) if 'ekk' in command else []
                    output = item.get('aggregated_output') or item.get('stdout') or ''
                    for call in calls:
                        episodes.append({**call, **parse_output(call['op'], output, item.get('exit_code')),
                                         'host': 'codex', 'session': session['session'], 'ts': stamp,
                                         'exit': item.get('exit_code'), 'multi': len(calls) > 1, 'subagent': subagent})
    return list(sessions.values()), episodes


def claude_text(content):
    if isinstance(content, str):
        return content
    return '\n'.join(part.get('text') or '' for part in listed(content) if isinstance(part, dict) and part.get('type') == 'text')


def scan_claude(patterns, since, until):
    sessions, episodes = {}, []
    files = {f for p in patterns for f in glob.glob(os.path.expanduser(p))}
    # A resumed or compacted session replays earlier records under the same uuid; the oldest file owns them.
    files = sorted(files, key=lambda f: (getattr(os.stat(f), 'st_birthtime', os.path.getmtime(f)), f))
    seen = set()
    for path in files:
        subagent = '/subagents/' in path
        key = Path(path.split('/subagents/')[0]).name if subagent else Path(path).stem
        skip = bool(since and utc_day(path) < since)
        session = None if skip else sessions.setdefault(key, new_session('claude', key))
        if session:
            session['files'] += 1
            if not subagent and session['subagent']:
                session.update(subagent=False, file=path)
            elif session['file'] is None:
                session['file'] = path
        pending, candidate = {}, None
        with open(path, errors='replace') as stream:
            for line in stream:
                if '"type":"user"' not in line and '"type":"assistant"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                kind, message = record.get('type'), record.get('message')
                if kind not in ('user', 'assistant') or not isinstance(message, dict):
                    continue
                if record.get('uuid'):
                    if record['uuid'] in seen:
                        continue
                    seen.add(record['uuid'])
                stamp = record.get('timestamp') or ''
                # A file outside the period still claims its uuids, so a later replay is not counted as new.
                if skip or not in_period(stamp[:10], since, until):
                    continue
                touch(session, stamp)
                if record.get('cwd') and (session['cwd'] is None or (not subagent and not session['_root_cwd'])):
                    session.update(cwd=record['cwd'], _root_cwd=not subagent)
                content = message.get('content')
                parts = [p for p in content if isinstance(p, dict)] if isinstance(content, list) else []
                if kind == 'assistant':
                    if isinstance(message.get('model'), str) and message['model'].startswith('claude'):
                        session['models'].add(message['model'])
                    for part in parts:
                        if part.get('type') != 'tool_use':
                            continue
                        name, given = part.get('name'), part.get('input') if isinstance(part.get('input'), dict) else {}
                        if name == 'Bash':
                            command = str(given.get('command') or '')
                            if 'ekk-workflow' in command:
                                session['skill_read'] = True
                            use = {'command': command if 'ekk' in command and invocations(command) else None,
                                   'commit': 'commit' in command and commits(command), 'ts': stamp}
                            if use['command'] or use['commit']:
                                pending[part.get('id')] = use
                        elif name in CHANGE_TOOLS and given.get(CHANGE_TOOLS[name]):
                            pending[part.get('id')] = {'change': True}
                        elif name == 'Skill' and 'ekk-workflow' in str(given):
                            session['skill_read'] = True
                    text = claude_text(parts)
                    if text.strip() and message.get('stop_reason') == 'end_turn':
                        candidate = (stamp, text)
                    continue
                results = [p for p in parts if p.get('type') == 'tool_result']
                for part in results:
                    use = pending.pop(part.get('tool_use_id'), None)
                    if not use:
                        continue
                    failed = bool(part.get('is_error'))
                    if use.get('change'):
                        session['file_changes'] += not failed
                        continue
                    session['commits'] += use['commit'] and not failed
                    if not use['command']:
                        continue
                    body = part.get('content')
                    output = body if isinstance(body, str) else ''.join(
                        c.get('text', '') for c in listed(body) if isinstance(c, dict))
                    calls = invocations(use['command'])
                    for call in calls:
                        episodes.append({**call, **parse_output(call['op'], output), 'host': 'claude',
                                         'session': session['session'], 'ts': use['ts'],
                                         'exit': 1 if failed else 0, 'multi': len(calls) > 1, 'subagent': subagent})
                if (results or subagent or record.get('isSidechain') or record.get('isMeta')
                        or record.get('isCompactSummary') or 'toolUseResult' in record
                        or (record.get('origin') or {}).get('kind') not in (None, 'human')):
                    continue
                prompt = claude_text(content)
                text = observation.owner_text(prompt)
                if text:
                    # The report the owner answers is the last finished assistant text before this prompt.
                    if candidate:
                        session['_reports'].append(candidate)
                        session['_all_reports'].append(candidate)
                        candidate = None
                    session['_owner'].append((stamp, text, later_owner_texts(prompt)))
        if candidate:
            session['_all_reports'].append(candidate)
            if not subagent:
                session['_reports'].append(candidate)
    return list(sessions.values()), episodes


def collect(args):
    since, until = args.since, args.until
    codex = args.codex or ['~/.codex*/sessions/*/*/*/*.jsonl', '~/.codex*/archived_sessions/*.jsonl']
    claude = args.claude or ['~/.claude/projects/*/*.jsonl', '~/.claude/projects/*/*/subagents/*.jsonl',
                             '~/.claude/projects/*/*/subagents/workflows/*/agent-*.jsonl']
    sessions, episodes, messages = [], [], []
    for scan, patterns in ((scan_codex, codex), (scan_claude, claude)):
        found_sessions, found_episodes = scan(patterns, since, until)
        # A thread with no record inside the period is not a session of the period.
        sessions += [s for s in found_sessions if s['start'] or not (since or until)]
        episodes += found_episodes
    by_session = collections.defaultdict(list)
    for episode in episodes:
        by_session[(episode['host'], episode['session'])].append(episode)
    for session in sessions:
        rows = by_session.get((session['host'], session['session']), [])
        session['models'] = sorted(session['models'])
        session['project'], session['bound'] = bound_project(session['cwd'])
        session['ekk_calls'] = sum(1 for e in rows if not e['help'])
        first = len(messages)
        finish(session, rows, messages)
        for message in messages[first:]:
            message.update(project=session['project'], bound=session['bound'])
        session['owner_after_report'] = sum(m['after_report'] for m in messages[first:])
        session['corrections'] = sum(m['correction'] for m in messages[first:])
        session['repeated_corrections'] = sum(m['repeat'] for m in messages[first:])
        for episode in rows:
            episode['project'] = session['project']
    known = {(s['host'], s['session']) for s in sessions}
    episodes = [e for e in episodes if (e['host'], e['session']) in known]
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_jsonl(out / 'sessions.jsonl', sessions)
    write_jsonl(out / 'episodes.jsonl', episodes)
    write_jsonl(out / 'messages.jsonl', messages)
    (out / 'run.json').write_text(json.dumps({'since': since, 'until': until, 'codex': codex, 'claude': claude,
                                              'episode_format': EPISODE_FORMAT,
                                              'correction_rule': observation.CORRECTION_RULE,
                                              'correction_rule_digest': rule_digest(),
                                              'correction_rules': {name: rule_digest(rule) for name, rule in RULES.items()},
                                              'created_at': dt.datetime.now(dt.timezone.utc).isoformat()}, indent=2))
    os.chmod(out / 'run.json', 0o600)
    return sessions, episodes


def write_jsonl(path, rows):
    with open(path, 'w') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=sorted) + '\n')
    os.chmod(path, 0o600)


def read_jsonl(path):
    with open(path) as stream:
        return [json.loads(line) for line in stream if line.strip()]


def quantiles(values):
    values = sorted(values)
    if not values:
        return {'n': 0}
    return {'n': len(values), 'median': statistics.median(values),
            'p90': values[min(len(values) - 1, int(math.ceil(len(values) * 0.9)) - 1)]}


def always_on(results):
    """Share of each result occupied by items that appear for >= 30% of distinct tasks."""
    if not results:
        return None
    counts = collections.Counter(item for items in results for item in set(items))
    hot = {item for item, n in counts.items() if n / len(results) >= HOT_SHARE}
    shares = [sum(1 for item in items if item in hot) / len(items) for items in results if items]
    return {'tasks': len(results), 'share': statistics.mean(shares) if shares else 0.0, 'hot_items': len(hot)}


def share(part, whole):
    return round(part / whole, 3) if whole else None


def merge_host_events(sessions, pairs):
    """Mark sessions for which EKK itself recorded an outcome from a host event.

    Transcripts cannot show the stores. The caller reads outcome records whose
    metadata has experience.acquisition == "host_event" and passes their
    {"host", "session"} pairs with the runtime's host labels ('claude-code', 'codex'). A pair whose host the
    runtime could not name ('unknown' or absent) matches by session ID when exactly one session has that ID.
    Returns the numbers of distinct pairs that matched a session and that matched none.
    """
    wanted = {(HOST_LABELS.get(p.get('host'), p.get('host')), p.get('session')) for p in pairs if isinstance(p, dict)}
    by_id = collections.defaultdict(list)
    for session in sessions:
        by_id[session['session']].append(session['host'])
    known = {(session['host'], session['session']) for session in sessions}
    found, unmatched = set(), 0
    for host, key in wanted:
        if host in (None, '', 'unknown') and len(by_id.get(key, ())) == 1:
            host = by_id[key][0]
        if (host, key) in known:
            found.add((host, key))
        else:
            unmatched += 1
    for session in sessions:
        session['automatic_outcome'] = (session['host'], session['session']) in found
    return {'matched': len(found), 'unmatched': unmatched}


def retention(sessions):
    """Sessions with changes and the share of them that left a retained outcome, by host and bound project."""
    groups = collections.defaultdict(collections.Counter)
    automatic = any('automatic_outcome' in s for s in sessions)
    for s in sessions:
        project = s['project'] if s.get('bound') else UNBOUND
        changed, agent, auto = bool(s.get('changed')), bool(s.get('retained')), bool(s.get('automatic_outcome'))
        attempts = sum((s.get('retain') or {}).values())
        for key in ('all', 'host:' + s['host'], 'project:' + project, f"host:{s['host']}|project:{project}"):
            row = groups[key]
            row['sessions'] += 1
            row['with_changes'] += changed
            row['with_retained_outcome'] += agent
            row['with_unconfirmed_retain'] += bool(attempts and not agent)
            row['changed_with_retained_outcome'] += changed and agent
            row['with_automatic_outcome'] += auto
            row['changed_with_automatic_outcome'] += changed and auto
            row['changed_with_any_outcome'] += changed and (agent or auto)
    fields = ['sessions', 'with_changes', 'with_retained_outcome', 'with_unconfirmed_retain', 'changed_with_retained_outcome']
    fields += ['with_automatic_outcome', 'changed_with_automatic_outcome', 'changed_with_any_outcome'] if automatic else []
    result = {}
    for key, row in sorted(groups.items(), key=lambda kv: (-kv[1]['with_changes'], kv[0])):
        result[key] = {field: row[field] for field in fields}
        result[key]['retained_share_of_changed'] = share(row['changed_with_retained_outcome'], row['with_changes'])
        if automatic:
            result[key]['any_share_of_changed'] = share(row['changed_with_any_outcome'], row['with_changes'])
    return result


def iso_week(stamp):
    year, week, _ = dt.date.fromisoformat(stamp[:10]).isocalendar()
    return f'{year}-W{week:02d}'


def flags(message, rule, primary):
    """(owner, correction, repeat) of one owner message.

    The row's own fields hold the rule the run was collected under (``primary``, from its run.json);
    a later rule's flags are under 'rules'.
    """
    if rule == primary:
        return True, message['correction'], message['repeat']
    row = message['rules'][rule]
    return row['owner'], row['correction'], row['repeat']


def corrections(messages, since=None, until=None, rule=None, primary=None):
    """Counts only: owner messages after agent work, corrections and repeated corrections under one frozen rule.

    ``primary`` is the rule the run recorded as its own (default: this code's rule 1); ``rule`` defaults to it.
    """
    primary = primary or observation.CORRECTION_RULE
    rule = rule or primary
    def blank():
        return {'owner_messages': 0, 'owner_messages_after_report': 0, 'corrections': 0, 'repeated_corrections': 0}
    rows, hosts, projects, total = (collections.defaultdict(blank), collections.defaultdict(blank),
                                    collections.defaultdict(blank), blank())
    for m in messages:
        if not m.get('ts') or not in_period(m['ts'][:10], since, until):
            continue
        owner, fix, repeat = flags(m, rule, primary)
        if not owner:
            continue
        project = m['project'] if m.get('bound') else UNBOUND
        for row in (rows[(m['host'], project, iso_week(m['ts']))], hosts[m['host']], projects[project], total):
            row['owner_messages'] += 1
            row['owner_messages_after_report'] += bool(m['after_report'])
            row['corrections'] += bool(fix)
            row['repeated_corrections'] += bool(repeat)
    return {'rule': rule,
            'denominator': 'owner_messages_after_report: owner messages that follow at least one agent report in the session',
            'total': total, 'by_host': dict(sorted(hosts.items())),
            'by_project': dict(sorted(projects.items(), key=lambda kv: (-kv[1]['corrections'], kv[0]))),
            'by_host_project_week': [{'host': host, 'project': project, 'week': week, **row}
                                     for (host, project, week), row in sorted(rows.items())]}


def baseline_name(rule):
    """Rule 1 keeps the file name its frozen September baseline has; a later rule gets its own file."""
    if rule == observation.CORRECTION_RULE:
        return 'corrections-baseline.json'
    return 'corrections-baseline-' + rule.removeprefix('ekk.').replace('/', '-') + '.json'


def baseline(args):
    """Freeze correction counts for a fixed period, so that later comparisons use unchanged numbers."""
    run = Path(args.out).expanduser()
    if not (args.since and args.until):
        raise SystemExit('baseline needs --since and --until')
    name = getattr(args, 'rule', None) or observation.CORRECTION_RULE
    if name not in RULES:
        raise SystemExit(f'unknown correction rule {name}; known: {", ".join(RULES)}')
    target = run / baseline_name(name)
    if target.exists():
        raise SystemExit(f'{target} exists and is frozen; write a new baseline into another run directory')
    collected = json.loads((run / 'run.json').read_text())
    if args.since > args.until:
        raise SystemExit('baseline --since is after --until')
    if (collected.get('since') or '') > args.since or (collected.get('until') or args.until) < args.until:
        raise SystemExit('the collected run does not cover the baseline period')
    # The period must have ended before collection: the collection day itself is still open.
    collected_day = dt.datetime.fromisoformat(collected['created_at']).astimezone(dt.timezone.utc).date().isoformat()
    if args.until >= collected_day:
        raise SystemExit('the baseline period was still open when the run was collected; '
                         'end it before the UTC day of collection')
    # Owner turns are collected under rule 1, so every rule's counts also depend on rule 1's content.
    if (collected.get('correction_rule') != observation.CORRECTION_RULE
            or collected.get('correction_rule_digest') != rule_digest()
            or (name != observation.CORRECTION_RULE
                and (collected.get('correction_rules') or {}).get(name) != rule_digest(RULES[name]))):
        raise SystemExit('the run was collected under another correction rule (name or content); collect again')
    turns = {} if name == observation.CORRECTION_RULE else {
        'owner_turn_rule': observation.CORRECTION_RULE, 'owner_turn_rule_digest': rule_digest()}
    result = {'schema': 'ekk.field-use-corrections-baseline/0.1', 'since': args.since, 'until': args.until,
              'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'collected_at': collected['created_at'], 'rule_digest': rule_digest(RULES[name]), **turns,
              **corrections(read_jsonl(run / 'messages.jsonl'), args.since, args.until, name)}
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    os.chmod(target, 0o600)
    return result


def entry_use(enters):
    """Delivered entry items and the ones with a later sign of use, per host."""
    result = {}
    for e in enters:
        if 'delivered' not in e:
            continue
        row = result.setdefault(e['host'], {'enters': 0, 'enters_with_items': 0, 'enters_with_use': 0, 'delivered': 0,
                                            'used': 0, 'by_signal': {'fetch': 0, 'report_id': 0, 'report_title': 0}})
        row['enters'] += 1
        row['enters_with_items'] += bool(e['delivered'])
        row['enters_with_use'] += bool(e['used'])
        row['delivered'] += e['delivered']
        row['used'] += len(e['used'])
        for signal in e['used'].values():
            row['by_signal'][signal] += 1
    for row in result.values():
        row['used_share'] = share(row['used'], row['delivered'])
    return result


def report(args, sessions=None, episodes=None):
    run = Path(args.out).expanduser()
    sessions = sessions if sessions is not None else read_jsonl(run / 'sessions.jsonl')
    episodes = episodes if episodes is not None else read_jsonl(run / 'episodes.jsonl')
    real = [e for e in episodes if not e['help']]
    # Counts are labelled with the rule the run was collected under, which this code may no longer hold.
    collected = json.loads((run / 'run.json').read_text()) if (run / 'run.json').is_file() else {}
    rule = collected.get('correction_rule') or observation.CORRECTION_RULE
    rule_current = (rule, collected.get('correction_rule_digest')) == (observation.CORRECTION_RULE, rule_digest())
    result = {'schema': 'ekk.field-use-report/0.1', 'limits': [
        'Observed behaviour only; no causal benefit is established.',
        'Transcripts are parsed heuristically; hosts without local logs (e.g. a remote gateway) are absent.',
        'An item delivered by entry is not evidence that it was used or helpful; the use signal is a later fetch '
        'of the item or its ID or title in a final report, which misses silent use and counts coincidental mentions.',
        'Retention is judged by the receipt visible in the transcript; redirected output is unknown, not retained.',
        f'Corrections follow {rule}: a cue rule with precision about 0.73 on its tuning '
        'sample and lower out of sample. Use the counts for trends under one rule version, not as exact numbers.',
        'Reuse and benchmark pairs cover only retained records whose ID a transcript shows: in a published receipt '
        'or in a queue status or drain receipt for the same key. Other successful writes are counted as '
        'writes_without_record_id and excluded; outcomes recorded from host events never appear in transcripts.']}
    if not rule_current:
        result['limits'].append(
            f'The run was collected under {rule} with other rule content than this code holds '
            f'({observation.CORRECTION_RULE}, {rule_digest()}): its correction counts are not comparable with '
            'counts under the current rule. Collect again before comparing.')
    host_events = getattr(args, 'host_events', None)
    if host_events:
        merged = merge_host_events(sessions, json.loads(Path(host_events).expanduser().read_text()))
        result['host_event_pairs_matched'], result['host_event_pairs_unmatched'] = merged['matched'], merged['unmatched']
    result['retention'] = retention(sessions)
    result['retain_receipts'] = dict(collections.Counter(
        f"{e['op']}:{e['outcome']}" for e in real if e.get('outcome')).most_common())
    if (run / 'messages.jsonl').is_file():
        result['corrections'] = {**corrections(read_jsonl(run / 'messages.jsonl'), rule=rule, primary=rule),
                                 'rule_matches_code': rule_current}
    result['entry_use'] = entry_use([e for e in real if e['op'] == 'enter'])
    # Adoption
    adoption = collections.defaultdict(lambda: {'sessions': 0, 'with_ekk': 0, 'user_sessions': 0, 'user_with_ekk': 0})
    for s in sessions:
        for key in (('host', s['host']), ('project', s['project'])):
            row = adoption[key]
            row['sessions'] += 1
            row['with_ekk'] += bool(s['ekk_calls'])
            if not s['subagent']:
                row['user_sessions'] += 1
                row['user_with_ekk'] += bool(s['ekk_calls'])
    result['adoption'] = {f'{kind}:{name}': row for (kind, name), row in sorted(adoption.items(), key=lambda kv: -kv[1]['sessions'])[:25]}
    weeks = collections.defaultdict(lambda: [0, 0])
    for s in sessions:
        if s['subagent'] or not s.get('start'):
            continue
        day = dt.date.fromisoformat(s['start'][:10])
        week = (day - dt.timedelta(days=day.weekday())).isoformat()
        weeks[week][0] += 1
        weeks[week][1] += bool(s['ekk_calls'])
    result['user_sessions_by_week'] = {w: {'sessions': a, 'with_ekk': b} for w, (a, b) in sorted(weeks.items())}
    models = collections.defaultdict(lambda: [0, 0])
    for s in sessions:
        for model in s['models'] or ['unknown']:
            models[model][0] += 1
            models[model][1] += bool(s['ekk_calls'])
    result['models'] = {m: {'sessions': a, 'with_ekk': b} for m, (a, b) in sorted(models.items(), key=lambda kv: -kv[1][0])}
    enters = [e for e in real if e['op'] == 'enter']
    result['enter_calls'] = {'total': len(enters), 'from_subagents': sum(e['subagent'] for e in enters)}
    result['operations'] = dict(collections.Counter(e['op'] for e in real).most_common())
    result['transcript_errors'] = dict(collections.Counter(
        (e['op'] + ':' + e['error']) for e in real if e.get('error')).most_common(20))
    # Entry output and retrieval behaviour
    sizes = collections.defaultdict(list)
    for e in enters:
        sizes['brief' if 'brief' in e['flags'] else 'compact' if 'compact' in e['flags'] else 'full'].append(e['out_bytes'])
    result['enter_output_bytes'] = {mode: quantiles(v) for mode, v in sizes.items()}
    per_project = collections.defaultdict(dict)
    for e in enters:
        if e.get('task') and e.get('items') is not None:
            per_project[e['project']].setdefault(e['task'], [i['id'] or i['title'] for i in e['items']])
    result['always_on'] = {p: always_on(list(t.values())) for p, t in per_project.items() if len(t) >= 10}
    items = [i for e in enters for i in e.get('items') or []]
    items = [i for i in items if i['content_chars'] is not None]
    result['empty_content_share'] = (sum(1 for i in items if not i['content_chars']) / len(items)) if items else None
    by_session = collections.defaultdict(list)
    for e in sorted(real, key=lambda e: e.get('ts') or ''):
        by_session[e['session']].append(e)
    followed = entered = 0
    for rows in by_session.values():
        seen = False
        for e in rows:
            if e['op'] == 'enter':
                seen = True
            elif seen and e['op'] in ('fetch', 'read-source'):
                followed += 1
                break
        entered += seen
    result['follow_up_after_enter'] = {'sessions_with_enter': entered, 'followed_by_fetch_or_read': followed}
    # Reuse: IDs produced by writes resurfacing in later reads of other sessions
    created = {}
    if collected.get('episode_format') == EPISODE_FORMAT:
        writes, unresolved = created_records(real)
    else:
        writes, unresolved = [], None
        result['limits'].append(f'The run was collected with an older episode format than this code reads ({EPISODE_FORMAT}): '
                                'reuse and benchmark pairs cannot be resolved from it. Collect again.')
    for session, stamp, ids in sorted(writes, key=lambda write: write[1]):
        for rid in ids:
            created.setdefault(rid, (session, stamp))
    reused = {}
    for e in real:
        if e['op'] in READ_OPS:
            for rid in e['ids']:
                origin = created.get(rid)
                if origin and origin[0] != e['session'] and (e.get('ts') or '') > origin[1]:
                    reused.setdefault(rid, set()).add(e['session'])
    result['reuse'] = {'created_ids': len(created), 'resurfaced_in_later_sessions': len(reused),
                       'writes_without_record_id': unresolved}
    # Operation journal: latency and outcome by operation and runtime version
    journal = Path(args.journal).expanduser() if args.journal else data_home() / 'operations/operations.jsonl'
    if journal.is_file():
        rows = [json.loads(line) for line in journal.read_text().splitlines()[1:] if line.strip()]
        rows = [r for r in rows if in_period((r.get('started_at') or '')[:10], args.since, args.until)]
        for window in args.journal_exclude or []:
            # Development or measurement runs recorded in the owner's journal.
            start, _, end = window.partition('/')
            rows = [r for r in rows if not (start <= (r.get('started_at') or '') <= end)]
        latency = collections.defaultdict(list)
        outcomes = collections.Counter()
        # Host-registered caller (a Codex profile, claude-code, the gateway) or unknown.
        by_caller = collections.defaultdict(collections.Counter)
        for r in rows:
            by_caller[r.get('caller_profile') or 'unknown'][
                'completed' if r.get('result') == 'completed' else 'not_completed'] += 1
            if r.get('duration_ms') is not None and r.get('result') == 'completed':
                # A queued retain returns in about a second; the publication it
                # starts is recorded by the worker under the queue drain.
                operation = r['operation']
                if operation == 'retain' and r.get('duration_ms', 0) < 5000 and not r.get('mutated'):
                    operation = 'retain.enqueue'
                latency[(operation, r.get('runtime_version'))].append(r['duration_ms'] / 1000)
            outcomes[r.get('result') if r.get('result') == 'completed' else f"{r.get('result')}:{r.get('error_code')}"] += 1
        result['journal'] = {
            'operations': len(rows),
            'outcomes': dict(outcomes.most_common()),
            'by_caller': {k: dict(v) for k, v in sorted(by_caller.items())},
            'latency_seconds': {f'{op}@{version}': quantiles(v) for (op, version), v in sorted(latency.items())
                                if op in ('enter', 'retain', 'retain.enqueue', 'search', 'fetch', 'capture', 'queue.submit', 'queue.drain')},
        }
    (run / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (run / 'report.md').write_text(markdown(result))
    os.chmod(run / 'report.json', 0o600)
    os.chmod(run / 'report.md', 0o600)
    return result


def markdown(result):
    lines = ['# EKK field use', '', *[f'- {limit}' for limit in result['limits']], '', '## Adoption', '',
             '| Group | Sessions | With EKK | User sessions | User with EKK |', '| --- | ---: | ---: | ---: | ---: |']
    for key, row in result['adoption'].items():
        lines.append(f"| {key} | {row['sessions']} | {row['with_ekk']} | {row['user_sessions']} | {row['user_with_ekk']} |")
    lines += ['', '## Weekly user sessions', '']
    lines += [f"- {w}: {v['with_ekk']}/{v['sessions']}" for w, v in result['user_sessions_by_week'].items()]
    lines += ['', '## Models', '']
    lines += [f"- {m}: {v['with_ekk']}/{v['sessions']} sessions with EKK" for m, v in result['models'].items()]
    lines += ['', '## Entry', '', f"- calls: {result['enter_calls']}",
              f"- output bytes by mode: {result['enter_output_bytes']}",
              f"- always-on share by project: {result['always_on']}",
              f"- items without content: {result['empty_content_share']}",
              f"- follow-up: {result['follow_up_after_enter']}",
              f"- reuse: {result['reuse']}", '', '### Entry use by host', '']
    lines += [f'- {host}: {row}' for host, row in result['entry_use'].items()]
    automatic = any('with_automatic_outcome' in row for row in result['retention'].values())
    lines += ['', '## Retention after changes', '', f"- receipts: {result['retain_receipts']}"]
    if 'host_event_pairs_matched' in result:
        lines.append(f"- host-event pairs: {result['host_event_pairs_matched']} matched, "
                     f"{result['host_event_pairs_unmatched']} unmatched (no transcript session with that host and ID)")
    lines += ['',
              '| Group | Sessions | With changes | Retained by agent | Changed and retained | Share of changed |'
              + (' Automatic | Changed with any outcome | Any share |' if automatic else ''),
              '| --- | ---: | ---: | ---: | ---: | ---: |' + (' ---: | ---: | ---: |' if automatic else '')]
    for key, row in list(result['retention'].items())[:40]:
        lines.append(f"| {key} | {row['sessions']} | {row['with_changes']} | {row['with_retained_outcome']} | "
                     f"{row['changed_with_retained_outcome']} | {row['retained_share_of_changed']} |"
                     + (f" {row['with_automatic_outcome']} | {row['changed_with_any_outcome']} | {row['any_share_of_changed']} |"
                        if automatic else ''))
    if 'corrections' in result:
        fixes = result['corrections']
        lines += ['', f"## Owner corrections ({fixes['rule']})", '',
                  '| Group | Owner messages | After a report | Corrections | Repeated |', '| --- | ---: | ---: | ---: | ---: |']
        groups = [('all', fixes['total']), *[('host:' + k, v) for k, v in fixes['by_host'].items()],
                  *[('project:' + k, v) for k, v in fixes['by_project'].items()],
                  *[(f"{r['host']} {r['project']} {r['week']}", r) for r in fixes['by_host_project_week']]]
        lines += [f"| {name} | {row['owner_messages']} | {row['owner_messages_after_report']} | {row['corrections']} | "
                  f"{row['repeated_corrections']} |" for name, row in groups]
    lines += ['', '## Errors seen in transcripts', '']
    lines += [f'- {k}: {v}' for k, v in result['transcript_errors'].items()]
    if 'journal' in result:
        lines += ['', '## Journal', '', f"- operations: {result['journal']['operations']}",
                  f"- outcomes: {result['journal']['outcomes']}",
                  f"- by caller: {result['journal']['by_caller']}", '']
        lines += [f'- {k}: {v}' for k, v in result['journal']['latency_seconds'].items()]
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- ranking bench
TEXT_SUFFIXES = {'.md', '.txt', '.csv', '.tsv', '.json', '.yaml', '.yml', '.html', '.xml'}


def legacy_scores(eligible, files, task, scan_limit=8 * 1048576):
    """Replica of the 0.8 entry score: distinct task words found anywhere in the record."""
    tokens = set(re.findall(r'\w+', task.casefold()))
    used, out = 0, {}
    for key, row in eligible.items():
        sections = [row['metadata']['id'], row['metadata']['title'], *row['metadata'].get('aliases', []), row['body']]
        for asset in row['metadata'].get('source', {}).get('assets', []):
            if PurePosixPath(asset['path']).suffix.lower() not in TEXT_SUFFIXES:
                continue
            take = min(1048576, scan_limit - used)
            if take == 0:
                continue
            chunk = files[asset['path']][:take]
            used += len(chunk)
            try:
                sections.append(chunk.decode('utf-8'))
            except UnicodeDecodeError:
                pass
        out[key] = len(tokens & set(re.findall(r'\w+', ' '.join(sections).casefold())))
    return out


def load_store(cwd):
    from ekk.adapters.command_line import service, _routes, parser
    from ekk.adapters.local_profile import binding
    args = parser().parse_args(['enter', '--cwd', cwd])
    args._explicit_profile = False
    args.profile = binding(args.cwd)[1].get('profile', 'personal')
    route = _routes(args)[0]
    app = service(route['path'], allowed_scopes=route['scopes'] or None)
    snapshot = app.store.snapshot()
    records = app._validate(snapshot)[-1]
    scopes = set(route['scopes'])
    eligible = {k: r for k, r in records.items()
                if set(r['metadata']['scope']) & scopes and r['metadata']['kind'] != 'context'}
    return app, route, eligible, snapshot['files']


class CorpusTerms:
    """Task-term weights from a fixed list of tasks, with the runtime's formula."""
    def __init__(self, tasks):
        from ekk.adapters.experience_store import TaskTerms
        from ekk.application.discovery import content_terms
        counts = collections.Counter(stem for task in set(tasks) for stem in set(content_terms(task)))
        self._terms = TaskTerms('bench', store_factory=None)
        self._terms._loaded = (len(set(tasks)), dict(counts))

    @property
    def active(self):
        return self._terms.active

    def weight(self, stem):
        return self._terms.weight(stem)


def tasks_by_project(run):
    """Distinct entry tasks and (task, retained record) pairs per bound project of a collected run."""
    if run_format(run) != EPISODE_FORMAT:
        raise SystemExit(f'{run} was collected with an older episode format than this code reads ({EPISODE_FORMAT}); collect again')
    episodes = read_jsonl(run / 'episodes.jsonl')
    sessions = {s['session']: s for s in read_jsonl(run / 'sessions.jsonl')}
    by_session = collections.defaultdict(list)
    for e in episodes:
        if not e['help']:
            by_session[e['session']].append(e)
    stores = collections.defaultdict(lambda: {'tasks': set(), 'pairs': set(), 'writes_without_record_id': 0})
    made, resolved = collections.defaultdict(set), collections.Counter()
    for session, _, ids in created_records(episodes)[0]:
        made[session].update(ids)
        resolved[session] += 1
    for session, rows in by_session.items():
        project = sessions.get(session, {}).get('project', '?')
        if not project.startswith('~') and not project.startswith('/'):
            continue
        tasks = {e['task'] for e in rows if e['op'] == 'enter' and e.get('task')}
        stores[project]['tasks'] |= tasks
        stores[project]['pairs'] |= {(t, rid) for t in tasks for rid in made[session]}
        stores[project]['writes_without_record_id'] += sum(
            1 for e in rows if e['op'] in RETAIN_OPS and succeeded(e)) - resolved[session]
    return stores


def bench(args):
    run = Path(args.out).expanduser()
    stores = tasks_by_project(run)
    from ekk.application import discovery
    results = {}
    for project, data in sorted(stores.items(), key=lambda kv: -len(kv[1]['tasks'])):
        if len(data['tasks']) < args.min_tasks:
            continue
        cwd = os.path.expanduser(project)
        try:
            app, route, eligible, files = load_store(cwd)
        except (ValueError, OSError, KeyError, IndexError) as exc:
            results[project] = {'error': str(exc)}
            continue
        tasks = sorted(data['tasks'])
        pairs = sorted((t, rid) for t, rid in data['pairs'] if rid in eligible)
        scorers = {'legacy-0.8': lambda task: legacy_scores(eligible, files, task)}
        if hasattr(discovery, 'RecordRanker'):
            started = time.time()
            ranker = discovery.RecordRanker(eligible, files)
            build = time.time() - started
            scorers['current'] = ranker.scores
            # The same ranker with query terms weighted by how ordinary they are across this project's tasks.
            # The weights are fitted on the evaluated tasks themselves (in-sample); with fewer tasks than
            # TaskTerms.MIN_TASKS every weight is 1 and the row repeats 'current'.
            weights = CorpusTerms(tasks)
            scorers['task-weighted'] = discovery.RecordRanker(eligible, files, query_weight=weights.weight).scores
        else:
            build = weights = None
        row = {'eligible': len(eligible), 'tasks': len(tasks), 'pairs': len(pairs), 'current_build_seconds': build,
               # Successful retentions of these sessions whose record ID no transcript shows: they form no pair.
               'writes_without_record_id': data.get('writes_without_record_id', 0)}
        for name, score in scorers.items():
            started = time.time()
            ranked = {t: [k for k, v in sorted(score(t).items(), key=lambda kv: (-kv[1], kv[0])) if v > 0] for t in tasks}
            elapsed = (time.time() - started) / max(len(tasks), 1)
            positions = [ranked[t].index(rid) + 1 if rid in ranked[t] else None for t, rid in pairs]
            per_target = collections.defaultdict(list)
            for (t, rid), pos in zip(pairs, positions):
                per_target[rid].append(1 if pos and pos <= args.k else 0)
            hits = [1 if pos and pos <= args.k else 0 for pos in positions]
            row[name] = {
                f'recall@{args.k}': statistics.mean(hits) if hits else None,
                f'recall@{args.k}_per_target': statistics.mean(statistics.mean(v) for v in per_target.values()) if per_target else None,
                'mrr': statistics.mean((1 / p) if p else 0 for p in positions) if positions else None,
                'always_on': always_on([ranked[t][:args.k] for t in tasks]),
                'empty_results': sum(1 for t in tasks if not ranked[t]),
                'seconds_per_query': elapsed,
            }
        if weights is not None:
            row['task-weighted'].update(query_weights_applied=weights.active,
                                        weights_fitted_on='the evaluated tasks (in-sample)')
        if args.pipeline:
            row['pipeline'] = pipeline(app, route, tasks, args, pairs)
            if getattr(args, 'pipeline_task_weighted', False):
                row['pipeline_task_weighted'] = weighted_pipeline(cwd, tasks, args, pairs)
        results[project] = row
    (run / 'bench.json').write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    os.chmod(run / 'bench.json', 0o600)
    return results


def sampled(tasks, count):
    """Deterministic sample of the tasks for end-to-end entry."""
    return tasks[::max(1, len(tasks) // count)][:count]


def weighted_pipeline(cwd, tasks, args, pairs=()):
    """The same sample through entry with task-term query weights, which the runtime measures but does not apply.

    Runs on a fresh application, so the application of the 'pipeline' row stays as the runtime builds it.
    The weights are fitted on the project's tasks outside the evaluated sample. With fewer such tasks than
    TaskTerms.MIN_TASKS the weights are inactive and the condition cannot be measured: no entry is run.
    """
    sample = set(sampled(tasks, args.pipeline))
    others = sorted(set(tasks) - sample)
    weights = CorpusTerms(others)
    if not weights.active:
        return {'skipped': 'too few tasks outside the sample to fit task-term weights',
                'weights_fitted_on_tasks': len(others), 'query_weights_applied': False}
    app, route, _, _ = load_store(cwd)
    app.task_terms = weights
    return {**pipeline(app, route, tasks, args, pairs), 'weights_fitted_on_tasks': len(others)}


def pipeline(app, route, tasks, args, pairs=()):
    """End-to-end application entry on a deterministic sample of real tasks.

    The application is used as given: `bench` passes the one the runtime builds, so the 'pipeline' row is the
    entry agents receive. Known-item recall here covers everything entry does after scoring: tiers,
    current-first substitution, grounds and the record budget of the agent view.
    """
    sample = sampled(tasks, args.pipeline)
    selections, seconds = {}, []
    for task in sample:
        started = time.time()
        result = app.context(route['scopes'], task=task, budget=64000, focus=route.get('working_entries', []))
        seconds.append(time.time() - started)
        selections[task] = [r['id'] for r in result['records']
                            if not r.get('mandatory') and not r.get('governs') and r.get('selection') in ('ranked', 'related', 'successor', None)]
    counts = collections.Counter(i for s in selections.values() for i in set(s))
    records = app._validate(app.store.snapshot())[-1]
    per_target = collections.defaultdict(list)
    for task, rid in pairs:
        if task in selections:
            per_target[rid].append(1 if rid in selections[task][:args.k] else 0)
    terms = getattr(app, 'task_terms', None)
    return {'tasks': len(sample), 'seconds': quantiles(seconds), 'always_on': always_on(list(selections.values())),
            'query_weights_applied': bool(terms is not None and getattr(terms, 'active', True)),
            f'recall@{args.k}_per_target': statistics.mean(statistics.mean(v) for v in per_target.values()) if per_target else None,
            'targets': len(per_target),
            'most_frequent': [(records.get(i, {}).get('metadata', {}).get('title', i), n)
                              for i, n in counts.most_common(5)]}


# ------------------------------------------------- cold-process latency and equivalence
# The child takes the same path as the `ekk` CLI, but diagnostics are not journaled and
# observation is switched off (EKK_OBSERVE=0), so measurement leaves no rows in the owner's
# operation journal and no deliveries, use marks or task observations in the observer state.
CHILD = '''
import json, sys
import ekk.adapters.operation_diagnostics as diagnostics
diagnostics.observed_call = lambda operation, callback, **_: callback()
from ekk.adapters import command_line
sys.exit(command_line.main(json.loads(sys.argv[1])))
'''


def requests_from(path):
    """Private list of {"label", "argv"}; argv is what follows `ekk` on the command line."""
    rows = json.loads(Path(path).expanduser().read_text())
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get('label'), str)
                                             and isinstance(r.get('argv'), list) for r in rows):
        raise SystemExit('requests file must be a JSON list of {"label", "argv"}')
    return rows


def run_cli(python, argv, pack_directory=None):
    import subprocess
    env = dict(os.environ)
    env['EKK_OBSERVE'] = '0'
    if pack_directory:
        env['EKK_PACK_DIRECTORY'] = str(Path(pack_directory).expanduser())
    started = time.perf_counter()
    proc = subprocess.run([python, '-I', '-B', '-c', CHILD, json.dumps(argv)], capture_output=True,
                          text=True, env=env)
    return time.perf_counter() - started, proc


def store_heads(stores):
    import subprocess
    return {s: subprocess.run(['git', '-C', str(Path(s).expanduser()), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True).stdout.strip() for s in stores or []}


def latency(args):
    """Cold CLI processes with warm disk caches: the case an agent meets in the field."""
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    pythons = args.python or [sys.executable]
    rows = []
    for request in requests_from(args.requests):
        times = {python: [] for python in pythons}
        for run in range(args.warmup + args.runs):
            for python in pythons:  # interleaved, so drift affects every runtime alike
                elapsed, proc = run_cli(python, request['argv'], args.pack_directory)
                if proc.returncode not in (0, 1):
                    raise SystemExit(f"{request['label']} failed with {python}: {proc.stderr[-800:]}")
                if run >= args.warmup:
                    times[python].append(elapsed)
        for python, values in times.items():
            row = {'label': request['label'], 'python': python, 'runs': len(values),
                   'median_s': round(statistics.median(values), 2), 'min_s': round(min(values), 2),
                   'max_s': round(max(values), 2)}
            rows.append(row)
            print(f"{row['label']:<28} {row['median_s']:>6.2f}s median ({row['min_s']:.2f}-{row['max_s']:.2f})  {python}",
                  flush=True)
    (out / 'latency.json').write_text(json.dumps(rows, indent=2))
    os.chmod(out / 'latency.json', 0o600)
    return rows


VOLATILE_KEYS = {'assembled_at', 'observed_at', 'checked_at', 'generated_at', 'duration_ms', 'elapsed_ms'}


def normalized(value):
    if isinstance(value, dict):
        return {k: ('<volatile>' if k in VOLATILE_KEYS else normalized(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def compare(args):
    """Same requests through two runtimes; outputs must be identical after normalization."""
    if not args.python or len(args.python) != 2:
        raise SystemExit('compare needs exactly two --python interpreters')
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    rows = []
    for request in requests_from(args.requests):
        stable = False
        for _ in range(3):
            before = store_heads(args.store)
            results = [run_cli(python, request['argv'], args.pack_directory)[1] for python in args.python]
            if store_heads(args.store) == before:
                stable = True
                break  # otherwise a concurrent publication changed a store; repeat the pair
        outputs = []
        for proc in results:
            try:
                outputs.append(normalized(json.loads(proc.stdout)))
            except ValueError:
                outputs.append({'unparsed_stdout': proc.stdout[-2000:], 'stderr': proc.stderr[-2000:]})
        same = outputs[0] == outputs[1] and results[0].returncode == results[1].returncode
        if not same:
            for name, output in zip(('a', 'b'), outputs):
                path = out / f"{request['label']}.{name}.json"
                path.write_text(json.dumps(output, ensure_ascii=False, indent=1, sort_keys=True))
                os.chmod(path, 0o600)
        rows.append({'label': request['label'], 'identical': same, 'exit_codes': [r.returncode for r in results],
                     'stores_stable': stable})
        print(f"{'same' if same else 'DIFFERENT':9} {request['label']}", flush=True)
    (out / 'compare.json').write_text(json.dumps(rows, indent=2))
    os.chmod(out / 'compare.json', 0o600)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['collect', 'report', 'bench', 'run', 'latency', 'compare', 'baseline'])
    parser.add_argument('--out', default=str(data_home().parent / 'evaluation/field-use' /
                                              dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
    parser.add_argument('--since')
    parser.add_argument('--until')
    parser.add_argument('--rule', help='baseline: correction rule to freeze (default: ekk.correction-rule/1)')
    parser.add_argument('--codex', action='append', help='Glob of Codex session files (repeatable)')
    parser.add_argument('--claude', action='append', help='Glob of Claude Code transcript files (repeatable)')
    parser.add_argument('--journal', help='EKK operation journal path')
    parser.add_argument('--host-events', help='report: JSON list of {"host", "session"} for sessions whose outcome '
                                              'EKK recorded itself (experience.acquisition == "host_event")')
    parser.add_argument('--journal-exclude', action='append',
                        help='Skip journal rows started within START/END (RFC 3339, repeatable)')
    parser.add_argument('--k', type=int, default=8)
    parser.add_argument('--min-tasks', type=int, default=20)
    parser.add_argument('--pipeline', type=int, default=0, help='Also run full entry on N sampled tasks per store')
    parser.add_argument('--pipeline-task-weighted', action='store_true',
                        help='bench: with --pipeline, also run the sample with task-term query weights fitted on '
                             'the tasks outside it, as a separately named row')
    parser.add_argument('--requests', help='latency/compare: private JSON list of {"label", "argv"}')
    parser.add_argument('--python', action='append', help='latency/compare: interpreter with ekk installed (repeatable)')
    parser.add_argument('--pack-directory', default=os.environ.get('EKK_PACK_DIRECTORY'),
                        help='latency/compare: EKK_PACK_DIRECTORY for the child processes')
    parser.add_argument('--runs', type=int, default=5, help='latency: measured runs per request')
    parser.add_argument('--warmup', type=int, default=1, help='latency: discarded runs per request')
    parser.add_argument('--store', action='append', help='compare: store checkout whose head must not change')
    args = parser.parse_args(argv)
    if args.command == 'latency':
        return latency(args)
    if args.command == 'compare':
        return compare(args)
    if args.command == 'baseline':
        baseline(args)
        name = baseline_name(args.rule or observation.CORRECTION_RULE)
        print(json.dumps({'output': str(Path(args.out).expanduser() / name)}))
        return
    sessions = episodes = None
    if args.command in ('collect', 'run'):
        sessions, episodes = collect(args)
    if args.command in ('report', 'run'):
        report(args, sessions, episodes)
    if args.command == 'bench' or (args.command == 'run' and args.pipeline):
        bench(args)
    print(json.dumps({'output': str(Path(args.out).expanduser())}))


if __name__ == '__main__':
    main()
