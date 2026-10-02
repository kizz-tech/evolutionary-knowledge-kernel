"""`ekk observe`: the observer, the owner's review and host hook registration.

`ekk observe --event NAME` is the host hook itself and is handled before this
module is imported. The commands here are for the background worker and for the
owner: nothing in them runs on an agent's foreground path.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import time

from ..application import experience as rules
from ..homes import config_home, data_home
from .experience import Observer, _route, drain, owner_route, retain_through_queue, workspace_binding, write_card
from .experience_store import ExperienceStore
from .observe_hook import EVENTS, host_of, observed_home, switched_off

HOOK_TIMEOUT_SECONDS = 10
LAUNCHD_LABEL = 'me.kizz.ekk-observe'
LAUNCHD_PLIST = Path('Library/LaunchAgents') / (LAUNCHD_LABEL + '.plist')  # under the user's home
LAUNCHD_INTERVAL_SECONDS = 3600
REVIEW_DELIVERIES = 6
REVIEW_CORRECTIONS = 30
REVIEW_EPISODES = 10
REVIEW_DECISIONS = 10


def _day(at):
    return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d')


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _target(episode):
    return episode['key'].rsplit('-', 1)[-1]


def status():
    store = ExperienceStore()
    try:
        spool = observed_home() / 'spool'
        events = {f'{row[0]}:{row[1]}': row[2] for row in store.db.execute('SELECT kind,state,count(*) FROM events GROUP BY kind,state')}
        episodes = {row[0]: row[1] for row in store.db.execute('SELECT state,count(*) FROM episodes GROUP BY state')}
        attention = [f'{count} outcome(s) failed to publish: ekk queue status' for count in [episodes.get('failed', 0)] if count]
        attention += [f'{count} composed outcome(s) wait for a route' for count in [episodes.get('composed', 0)] if count]
        if (observed_home() / 'hook-errors.log').exists():
            attention.append('hook errors were logged: ' + str(observed_home() / 'hook-errors.log'))
        return {'schema': 'ekk.observer-status/0.2', 'observing': not switched_off(),
                'spooled': len(list(spool.glob('*.json'))) if spool.is_dir() else 0, 'events': events, 'episodes': episodes,
                'waiting_for_review': {'corrections': events.get('correction:pending', 0), 'held_results': episodes.get('held', 0)},
                'deliveries': store.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 'stats': store.stats(),
                'attention': attention,
                'meaning': 'Operational observer state; canonical records are in the realm stores.'}
    finally:
        store.close()


def review(days, out):
    """Write the page the owner marks: entry results, corrections, held and automatic results."""
    store = ExperienceStore()
    try:
        since = time.time() - days * 86400
        seen, deliveries = set(), []
        for delivery in store.deliveries(since=since):
            key = (delivery['workspace'], delivery['task'])
            if delivery['labels'] is not None or key in seen or not delivery['items'] or not delivery['task']:
                continue
            seen.add(key)
            deliveries.append({'id': delivery['id'], 'workspace_name': Path(delivery['workspace'] or '').name, 'date': _day(delivery['at']),
                               'task': delivery['task'], 'items': rules.review_items(delivery)})
            if len(deliveries) == REVIEW_DELIVERIES:
                break
        corrections = [{'id': event['id'], 'workspace_name': Path(event['workspace']).name, 'date': _day(event['at']), 'text': event['text']}
                       for event in store.events(kind='correction', state='pending') if event['text']][-REVIEW_CORRECTIONS:]
        def listed(episode):
            return {'id': _target(episode), 'workspace_name': Path(episode['workspace']).name, 'date': _day(episode['last_at']),
                    'title': episode['title'] or ''}
        held = [listed(episode) for episode in store.episodes('held')][-REVIEW_EPISODES:]
        judged = store.labels('outcome')
        outcomes = [listed(episode) for episode in store.episodes() if episode['state'] in ('queued', 'published')
                    and episode['reason'] != 'kept_by_owner' and (episode['last_at'] or 0) >= since
                    and _target(episode) not in judged][-REVIEW_EPISODES:]
        decisions = proposed_decisions(store)[:REVIEW_DECISIONS]
        page = rules.review_page(_day(time.time()), deliveries, corrections, held, outcomes, decisions)
    finally:
        store.close()
    path = Path(out) if out else data_home().parent / 'evaluation' / 'review' / f'review-{_day(time.time())}.md'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(page)
    return {'schema': 'ekk.review/0.2', 'page': str(path), 'entry_results': len(deliveries), 'corrections': len(corrections),
            'held_results': len(held), 'outcomes': len(outcomes), 'decisions': len(decisions),
            'next': f'Mark the page, then run: ekk observe apply-review {path}'}


def proposed_decisions(store):
    """Unaccepted decisions of the bound projects the observer has seen, newest first, each with the page's marker.

    A proposed decision is any `decision` record that is not a preference, is not
    accepted and is not replaced by an accepted successor (an unaccepted successor
    is listed beside it: accepting the successor accepts the chain); one the
    owner already judged on a page is left out. Titles are record data.
    """
    from .activity_cli import resolve
    judged = store.labels('decision')
    seen = {row[0] for table in ('events', 'episodes', 'deliveries')
            for row in store.db.execute(f'SELECT DISTINCT workspace FROM {table}') if row[0]}
    found = []
    for workspace in sorted(seen):
        bound = workspace_binding(workspace)
        if bound is None:
            continue
        try:
            app, scopes, _ = resolve(_route(workspace, bound['profile']))
            snapshot, _, _, records = app._query_view(scopes)
            accepted = app._acceptances(snapshot, records)
            current = app.card_view(scopes)  # readable, and replaced by an exact successor of equal standing
            successors = app._supersession(snapshot, records, current, accepted)[0]
        except (ValueError, OSError, KeyError, PermissionError):
            continue
        replaced = {target for target, keys in successors.items() if keys & set(accepted)}
        for row in records.values():
            metadata = row['metadata']
            if (metadata['kind'] != 'decision' or isinstance(metadata.get('preference'), dict) or metadata['id'] in accepted
                    or metadata['id'] in replaced or metadata['id'] not in current and metadata['id'] not in successors):
                continue
            marker = hashlib.sha256(json.dumps([workspace, metadata['id']]).encode()).hexdigest()[:40]
            if marker in judged:
                continue
            found.append({'id': marker, 'record_id': metadata['id'], 'workspace': workspace, 'workspace_name': Path(workspace).name,
                          'profile': bound['profile'], 'date': str(metadata.get('created_at', ''))[:10], 'title': metadata['title']})
    return sorted(found, key=lambda item: (item['date'], item['record_id']), reverse=True)


def accept_decision(candidate, statement):
    """Accept one proposed decision through the ordinary route, at the current snapshot, with the owner's statement.

    A decision that replaces unaccepted decisions is accepted after them, bottom
    up, so that the chain the owner judged is the chain that governs.
    """
    from .activity_cli import resolve
    from .command_line import current_reference
    app, scopes, _ = resolve(_route(candidate['workspace'], candidate['profile']))
    snapshot, _, _, records = app._query_view(scopes)
    accepted = app._acceptances(snapshot, records)
    chain, seen = [], set()
    def collect(record_id):
        if record_id in seen or record_id in accepted or record_id not in records or records[record_id]['metadata']['kind'] != 'decision':
            return
        seen.add(record_id)
        for ref in app._links(records[record_id]['metadata'], 'supersedes'):
            collect(ref['id'] if isinstance(ref, dict) else ref)
        chain.append(record_id)
    collect(candidate['record_id'])
    result = None
    for index, record_id in enumerate(chain):
        reference = current_reference(app, scopes, [record_id])
        result = app.accept_records(scopes, [reference], expected_snapshot=app.store.snapshot()['revision'],
                                    idempotency_key='review-accept-' + candidate['id'] + (f'-{index}' if record_id != candidate['record_id'] else ''),
                                    statement=statement)
    return result


def prefer(workspace, statement, *, stated_by, words=None, source=None, supersedes=None, owner_wide=False):
    """Queue a preference for the workspace's realm, or with ``owner_wide`` for every project in the owner's personal realm.

    ``stated_by`` labels origin: 'owner' only from the review page, 'owner_relayed'
    for an agent relaying the owner's words, 'agent' for an agent's own reading.
    Only the first two reach session cards or rank above other matches.
    """
    bound = workspace_binding(workspace)
    if bound is None:
        raise ValueError('The project has no single realm binding for a preference')
    if stated_by == 'owner_relayed' and not (isinstance(source, dict) and source.get('session')):
        raise ValueError("A relayed statement names the host session the owner spoke in (--statement-session)")
    route = owner_route(workspace) if owner_wide else _route(workspace, bound['profile'])
    title, body, preference = rules.preference_record(statement, words or statement, area=rules.OWNER_AREA if owner_wide else Path(workspace).name,
                                                      stated_by=stated_by, source=source)
    artifacts = [{'data': (words or statement).encode('utf-8'), 'filename': 'owner-words.md', 'title': 'Owner statement: ' + title[:80]}]
    exact = None
    if supersedes:
        from .activity_cli import resolve
        from .command_line import current_reference
        app, scopes, _ = resolve(route)
        reference = current_reference(app, scopes, [supersedes])
        exact = [{key: reference[key] for key in ('id', 'revision', 'digest')}]
    # Without a supplied key the queue derives one from the whole request: the same
    # statement from the same source is one record, anything else is another.
    return retain_through_queue(workspace, route.profile, key=None, title=title, body=body, artifacts=artifacts,
                                preference=preference, supersedes=exact, route=route)


def apply_review(path):
    """Record the owner's marks: relevance labels, kept or rejected corrections and results, accepted decisions."""
    marks = rules.parse_review(Path(path).read_text(encoding='utf-8'))
    store = ExperienceStore()
    counts = {'preferences_queued': 0, 'corrections_rejected': 0, 'results_kept': 0, 'results_rejected': 0,
              'decisions_accepted': 0, 'decisions_left': 0}
    errors = []
    try:
        known = {delivery['id'] for delivery in store.deliveries()}
        for identity, labels in marks['deliveries'].items():
            if identity in known:
                store.label_delivery(identity, {str(position): verdict for position, verdict in labels.items()})
        events = {event['id']: event for event in store.events(kind='correction')}
        for identity, verdict in marks['corrections'].items():
            event = events.get(identity)
            if event is None or event['state'] != 'pending':
                continue
            if verdict['keep']:
                try:
                    prefer(event['workspace'], verdict['statement'] or event['text'], stated_by='owner', words=event['text'],
                           source={'host': event['host'], 'session': event['session'], 'at': _day(event['at']), 'event': identity[:16]},
                           owner_wide=verdict.get('owner_wide', False))
                except Exception as exc:
                    errors.append({'correction': identity[:12], 'error': type(exc).__name__, 'message': str(exc)[:200]})
                    continue
            # The realm now holds a kept statement; a rejected one has no further use.
            store.set_event_state([identity], 'confirmed' if verdict['keep'] else 'rejected', clear_text=True)
            store.label(identity, 'correction', verdict['keep'])
            counts['preferences_queued' if verdict['keep'] else 'corrections_rejected'] += 1
        held = {_target(episode): episode for episode in store.episodes('held')}
        observer = Observer(store)
        for identity, keep in marks['episodes'].items():
            episode = held.get(identity)
            if episode is None:
                continue
            if keep:
                if not observer.publish(episode['key'], episode['workspace'], json.loads(episode['request']),
                                        json.loads(episode['covers']), 'kept_by_owner'):
                    store.save_episode(episode['key'], state='held')
                    errors.append({'result': identity[:12], 'error': 'not_queued', 'message': 'The route refused the result; it stays held.'})
                    continue
            else:
                store.save_episode(episode['key'], state='rejected', request=None)
            store.label(identity, 'episode', keep)
            counts['results_kept' if keep else 'results_rejected'] += 1
        for identity, verdict in marks['outcomes'].items():
            store.label(identity, 'outcome', verdict)
        # The owner's mark is the statement behind an acceptance; the page is the owner's own path.
        candidates = {item['id']: item for item in proposed_decisions(store)} if marks['decisions'] else {}
        for identity, verdict in marks['decisions'].items():
            candidate = candidates.get(identity)
            if candidate is None:
                continue
            if verdict:
                try:
                    accept_decision(candidate, {'by': 'owner', 'via': 'review_page', 'at': _now()})
                except Exception as exc:
                    errors.append({'decision': identity[:12], 'error': type(exc).__name__, 'message': str(exc)[:200]})
                    continue
            store.label(identity, 'decision', verdict)
            counts['decisions_accepted' if verdict else 'decisions_left'] += 1
        precision = rules.precision_at(store.deliveries())
        judged = sum(1 for delivery in store.deliveries() if delivery['labels'])
        useful, corrections = list(store.labels('outcome').values()), list(store.labels('correction').values())
    finally:
        store.close()
    def share(values):
        return None if not values else round(sum(values) / len(values), 3)
    def rounded(pair):
        return {'precision': None if pair[0] is None else round(pair[0], 3), 'entries': pair[1]}
    return {'schema': 'ekk.review-applied/0.2', 'entry_results_judged': len(marks['deliveries']), **counts,
            'outcomes_judged': len(marks['outcomes']), 'decisions_judged': len(marks['decisions']), 'errors': errors,
            'totals': {'entries_judged': judged,
                       f'owner_precision_at_{rules.REVIEW_TOP}': {'entry_order': rounded(precision['entry']),
                                                                  'plain_lexical_order': rounded(precision['plain'])},
                       'automatic_outcomes_useful': {'share': share(useful), 'judged': len(useful)},
                       'correction_candidates_kept': {'share': share(corrections), 'judged': len(corrections)}},
            'meaning': 'Preferences and kept results are queued as unaccepted records; an accepted decision governs its scope, '
                       'with the owner\'s statement in its receipt.'}


# ------------------------------------------------------------- hook registration
def hook_command(event):
    """A command that cannot fail its host: a runtime without `observe` exits nonzero, which a host could treat as a block."""
    launcher = shutil.which('ekk') or str(Path.home() / '.local/bin/ekk')
    return f'{shlex.quote(launcher)} observe --event {event} 2>/dev/null || true'


def install(host, home, dry_run):
    """Add the observer hooks to a host's user configuration; existing hooks stay as they are."""
    if host == 'launchd':
        return install_launchd(home, dry_run)
    if host == 'claude-code':
        path = Path(home).expanduser() / 'settings.json' if home else Path.home() / '.claude/settings.json'
    elif host == 'codex':
        if not home:
            raise ValueError('codex needs --home with the profile directory')
        path = Path(home).expanduser() / 'hooks.json'
    else:
        raise ValueError('Unknown host')
    path = path.resolve()  # a configuration kept elsewhere through a link is edited where it lives
    document = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(document, dict) or not isinstance(document.setdefault('hooks', {}), dict):
        raise ValueError('Unexpected hook configuration shape')
    added = []
    for event in sorted(EVENTS):
        groups = document['hooks'].setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError('Unexpected hook configuration shape')
        if any('observe --event ' + event in str(hook.get('command', '')) for group in groups if isinstance(group, dict)
               for hook in group.get('hooks', []) if isinstance(hook, dict)):
            continue
        # SessionEnd gets little time from hosts; the hook itself returns within a fraction of a second.
        groups.append({'hooks': [{'type': 'command', 'command': hook_command(event),
                                  'timeout': 3 if event == 'SessionEnd' else HOOK_TIMEOUT_SECONDS}]})
        added.append(event)
    result = {'schema': 'ekk.hook-install/0.1', 'host': host, 'path': str(path), 'added': added, 'dry_run': dry_run}
    if added and not dry_run:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        if path.exists():
            backup = path.with_name(path.name + f'.before-ekk-observe-{time.strftime("%Y%m%dT%H%M%S")}')
            shutil.copy2(path, backup)
            result['backup'] = str(backup)
        temporary = path.with_name(f'.{path.name}.ekk-{os.getpid()}')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(document, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    if host == 'codex':
        result['next'] = 'Codex runs a new hook only after the owner trusts it: start that profile in a terminal and review hooks (/hooks).'
    else:
        result['next'] = 'New Claude Code sessions use the hooks; running sessions keep their earlier configuration.'
    return result


# ------------------------------------------------------------ hourly observer run
def launchd_plist(home=None):
    """Where the user agent is defined: the LaunchAgents directory of the user's home unless ``home`` names another."""
    return (Path(home).expanduser() / LAUNCHD_PLIST.name if home else Path.home() / LAUNCHD_PLIST).resolve()


def launchd_agent():
    """The hourly observer run as a launchd user agent: no environment of its own, output to the private observer home."""
    launcher = shutil.which('ekk') or str(Path.home() / '.local/bin/ekk')
    log = str(observed_home() / 'launchd.log')
    return {'Label': LAUNCHD_LABEL, 'ProgramArguments': [launcher, 'observe', 'drain', '--background'],
            'StartInterval': LAUNCHD_INTERVAL_SECONDS, 'RunAtLoad': False, 'StandardOutPath': log, 'StandardErrorPath': log}


def _launchctl(*args):
    """One launchctl call, reported rather than raised: the schedule is a convenience, the hooks do not depend on it."""
    try:
        run = subprocess.run(['launchctl', *args], capture_output=True, text=True, timeout=30)
        error = '' if run.returncode == 0 else (run.stderr.strip() or run.stdout.strip() or f'exit {run.returncode}')[-200:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        error = type(exc).__name__
    return {'command': ['launchctl', *args], 'ok': not error, 'error': error}


def install_launchd(home, dry_run):
    """Register the hourly observer run with launchd; an earlier definition is replaced."""
    path, agent, domain = launchd_plist(home), launchd_agent(), f'gui/{os.getuid()}'
    text = plistlib.dumps(agent).decode('utf-8')
    result = {'schema': 'ekk.observer-schedule/0.1', 'host': 'launchd', 'label': LAUNCHD_LABEL, 'path': str(path),
              'interval_seconds': LAUNCHD_INTERVAL_SECONDS, 'dry_run': dry_run}
    if dry_run:
        return {**result, 'plist': text}
    observed_home().mkdir(parents=True, exist_ok=True, mode=0o700)  # launchd opens the log before the program runs
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    temporary = path.with_name(f'.{path.name}.ekk-{os.getpid()}')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(text)
    os.chmod(temporary, 0o644)  # launchd reads it; a group- or world-writable agent is refused
    os.replace(temporary, path)
    # launchd keeps the definition it loaded; a changed launcher path needs the agent booted out first.
    calls = [_launchctl('bootout', f'{domain}/{LAUNCHD_LABEL}')] if existed else []
    calls.append(_launchctl('bootstrap', domain, str(path)))
    if not calls[-1]['ok']:
        calls.append(_launchctl('load', '-w', str(path)))  # an older launchctl
    result.update(launchctl=calls, loaded=calls[-1]['ok'])
    result['next'] = (f'launchd runs the observer every hour; inspect with: launchctl print {domain}/{LAUNCHD_LABEL}'
                      if calls[-1]['ok'] else f'launchd did not load the agent: {calls[-1]["error"]}')
    return result


def uninstall(host, home):
    """Remove the hourly observer run; the host hooks stay registered."""
    if host != 'launchd':
        raise ValueError('Unknown host')
    path, domain = launchd_plist(home), f'gui/{os.getuid()}'
    calls = [_launchctl('bootout', f'{domain}/{LAUNCHD_LABEL}')]
    if not calls[-1]['ok'] and path.exists():
        calls.append(_launchctl('unload', '-w', str(path)))  # an older launchctl
    removed = path.exists()
    if removed:
        path.unlink()
    return {'schema': 'ekk.observer-schedule/0.1', 'host': 'launchd', 'label': LAUNCHD_LABEL, 'path': str(path),
            'launchctl': calls, 'unloaded': calls[-1]['ok'], 'removed': removed}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ekk observe', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    worker = commands.add_parser('drain', help='Process observed events once')
    worker.add_argument('--background', action='store_true')
    commands.add_parser('status', help='Counts of observed events, episodes and losses')
    commands.add_parser('on', help='Resume observation')
    commands.add_parser('off', help='Stop observation; hooks then do nothing')
    page = commands.add_parser('review', help='Write the page the owner marks')
    page.add_argument('--days', type=int, default=7)
    page.add_argument('--out')
    marks = commands.add_parser('apply-review', help='Record the marks of a review page')
    marks.add_argument('page')
    statement = commands.add_parser('prefer', help='Record a preference for a project, or owner-wide')
    statement.add_argument('--cwd', type=Path, default=Path.cwd())
    statement.add_argument('--statement', required=True)
    statement.add_argument('--words', help="The owner's own words, when they differ from the statement")
    statement.add_argument('--supersedes', help='ID of the preference this one replaces')
    statement.add_argument('--stated-by', choices=['owner-relayed', 'agent'], default='agent',
                           help="Who states it: an agent on its own reading (default), or an agent relaying the owner's words")
    statement.add_argument('--statement-session', help='Host session ID in which the owner spoke')
    statement.add_argument('--owner-wide', action='store_true',
                           help="For every project: recorded in the owner's personal realm (profile and realm alias 'personal')")
    card = commands.add_parser('card', help='Rebuild and print the session card of a project')
    card.add_argument('--cwd', type=Path, default=Path.cwd())
    hooks = commands.add_parser('install', help='Register the hooks with a host, or the hourly observer run with launchd')
    hooks.add_argument('--host', required=True, choices=['claude-code', 'codex', 'launchd'])
    hooks.add_argument('--home', help='Host configuration directory (required for codex; for launchd the LaunchAgents directory)')
    hooks.add_argument('--dry-run', action='store_true')
    removal = commands.add_parser('uninstall', help='Remove the hourly observer run')
    removal.add_argument('--host', required=True, choices=['launchd'])
    removal.add_argument('--home', help='The LaunchAgents directory, when not the one of the user\'s home')
    advice = commands.add_parser('advise', help='Run the configured advisor in shadow over pending material')
    advice.add_argument('--limit', type=int, default=50)
    args = parser.parse_args(argv)
    try:
        if args.command == 'drain':
            result = drain(background=args.background)
            if args.background:
                return 0  # a worker's log holds failures, not a line per turn
        elif args.command == 'status':
            result = status()
        elif args.command in ('on', 'off'):
            switch = config_home() / 'observe-off'
            if args.command == 'off':
                switch.parent.mkdir(parents=True, exist_ok=True)
                switch.touch()
            elif switch.exists():
                switch.unlink()
            result = {'schema': 'ekk.observer-status/0.2', 'observing': not switched_off()}
        elif args.command == 'review':
            result = review(args.days, args.out)
        elif args.command == 'apply-review':
            result = apply_review(args.page)
        elif args.command == 'prefer':
            from .observe_hook import workspace_of
            workspace = workspace_of(args.cwd)
            if workspace is None:
                raise ValueError('The directory is not inside one bound, observed project')
            # Provenance is what the caller declares; the host comes from its environment markers, never a terminal check.
            source = {'host': host_of({})[0], **({'session': args.statement_session} if args.statement_session else {}), 'at': _day(time.time())}
            result = prefer(str(workspace), args.statement, stated_by=args.stated_by.replace('-', '_'), words=args.words,
                            source=source, supersedes=args.supersedes, owner_wide=args.owner_wide)
        elif args.command == 'card':
            from .observe_hook import workspace_of
            workspace = workspace_of(args.cwd)
            bound = workspace_binding(workspace) if workspace else None
            if bound is None:
                raise ValueError('The directory is not inside one bound, observed project')
            result = {'schema': 'ekk.session-card/0.1', 'card': write_card(str(workspace), bound['profile']).read_text(encoding='utf-8')}
        elif args.command == 'advise':
            from .experience_advice import advise
            result = advise(args.limit)
        elif args.command == 'uninstall':
            result = uninstall(args.host, args.home)
        else:
            result = install(args.host, args.home, args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, PermissionError) as exc:
        from .command_line import error_code
        print(json.dumps({'error': error_code(exc), 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
