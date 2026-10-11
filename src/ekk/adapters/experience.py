"""Background observer: spool files become episodes, outcomes and session cards.

Single consumer under a private lock. Every canonical write goes through the
realm's ordinary durable queue with a deterministic key, so a crash or a replay
publishes one outcome. Failures here never reach the host or the agent.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from .. import observation
from ..application import experience as rules
from . import host_identity
from .experience_store import ExperienceStore
from .observe_hook import card_path, observed_home, repositories, switched_off, workspace_of

SPOOL_DAYS = 7
CARD_SECONDS = 6 * 60 * 60
MAX_TRANSCRIPT_TAIL = 2 * 1024 * 1024
STATE_FRESH_SECONDS = 5 * 60
MAX_DIRTY_PATHS = 200
PUBLISHED = ('read_back', 'read_back_and_discoverable')
SETTLED = ('queued', 'published', 'held', 'rejected', 'skipped', 'failed', 'expired_unreviewed', 'linked', 'not_owner_work')


# ----------------------------------------------------------------- repositories
def _git(repository, *args):
    try:
        result = subprocess.run(['git', '-C', str(repository), *args], capture_output=True, text=True, timeout=5,
                                env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _dirty(repository):
    """Uncommitted paths with a size-and-time signature each, so a further edit to a dirty file is seen."""
    status = _git(repository, 'status', '--porcelain=v1', '-z', '--untracked-files=normal')
    if status is None:
        return None
    paths, entries = [], iter(status.split('\0'))
    for entry in entries:
        if len(entry) > 3:
            paths.append(entry[3:])
            if entry[0] in 'RC' or entry[1] in 'RC':
                next(entries, None)  # the original path of a rename or copy
    signatures = {}
    for path in sorted(set(paths))[:MAX_DIRTY_PATHS]:
        try:
            info = os.lstat(Path(repository) / path)
            signatures[path] = f'{info.st_size}:{info.st_mtime_ns}'
        except OSError:
            signatures[path] = 'absent'
    return signatures


def repository_state(workspace, heads=None, *, fresh=True):
    """Commit and uncommitted paths of the workspace repository and of repositories directly inside it.

    ``heads`` are the commits the hook read at the moment of the event. The
    uncommitted paths are read now; for an event processed late they would
    describe a later moment, so they are left unknown.
    """
    state = {}
    for name, repository in repositories(workspace):
        head = (heads or {}).get(name) or ((_git(repository, 'rev-parse', 'HEAD') or '').strip() if fresh else '')
        if head:
            state[name] = {'head': head, 'dirty': _dirty(repository) if fresh else None}
    return state


def repository_changes(before, after, workspace):
    """What changed between two observed states; an unknown earlier state proves nothing."""
    changes = []
    for name, current in (after or {}).items():
        earlier = (before or {}).get(name)
        if earlier is None:
            continue
        repository = Path(workspace) if name == '.' else Path(workspace) / name
        commits, paths = [], set()
        if isinstance(earlier.get('dirty'), dict) and isinstance(current.get('dirty'), dict):
            paths = {path for path, signature in current['dirty'].items() if earlier['dirty'].get(path) != signature}
        if earlier['head'] != current['head']:
            if _git(repository, 'merge-base', '--is-ancestor', earlier['head'], current['head']) is not None:
                log = _git(repository, 'log', '--format=%h %s', '-n', '20', f'{earlier["head"]}..{current["head"]}')
                commits = [observation.single_line(observation.redact(line), 160) for line in (log or '').splitlines()]
            commits = commits or [f'{current["head"][:12]} (history moved from {earlier["head"][:12]})']
            diff = _git(repository, 'diff', '--name-only', earlier['head'], current['head'])
            paths |= set((diff or '').splitlines())
        if commits or paths:
            changes.append({'repository': Path(workspace).name if name == '.' else name, 'commits': commits,
                            'paths': [observation.single_line(path, 200) for path in sorted(paths)[:40]]})
    return changes


def report_from_transcript(path):
    """Last assistant text of a host transcript, for a host that does not pass it to the hook."""
    try:
        resolved = Path(path).expanduser().resolve()
        if resolved.suffix != '.jsonl' or Path.home().resolve() not in resolved.parents:
            return ''
        with open(resolved, 'rb') as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - MAX_TRANSCRIPT_TAIL))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return ''
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get('isSidechain'):
            continue
        message = record.get('message')
        if record.get('type') == 'user' and isinstance(message, dict) and isinstance(message.get('content'), str):
            return ''  # the owner's prompt comes first: this turn left no final text
        if record.get('type') == 'assistant' and isinstance(message, dict):
            content = message.get('content') if isinstance(message.get('content'), list) else []
            text = '\n'.join(block.get('text', '') for block in content
                             if isinstance(block, dict) and block.get('type') == 'text').strip()
            if text:
                return text
    return ''


# ----------------------------------------------------------------------- routes
def workspace_binding(workspace):
    """The workspace's single realm binding, or None when it cannot own a record."""
    from .local_profile import binding
    try:
        found = binding(Path(workspace))
    except (ValueError, OSError):
        return None
    if found is None:
        return None
    document = found[1]
    bindings = document.get('bindings') if isinstance(document, dict) else None
    if not isinstance(bindings, list) or len(bindings) != 1 or not isinstance(bindings[0], dict) or document.get('observe') is False:
        return None
    return {'realm': bindings[0].get('realm_id'), 'profile': document.get('profile', 'personal'),
            'contexts': list(bindings[0].get('contexts') or [])}


OWNER_PROFILE = 'personal'
OWNER_REALM = 'personal'


def _route(workspace, profile, realm=None):
    """The workspace's bound route, or with ``realm`` an explicit realm alias of ``profile``."""
    return argparse.Namespace(cwd=Path(workspace), profile=profile, realm=realm, root=None, scope=[], state_dir=None,
                              _explicit_profile=realm is not None)


def owner_route(workspace):
    """The owner's personal realm, where owner-wide preferences live: profile 'personal', realm alias 'personal'."""
    from .local_profile import LocalProfile
    try:
        LocalProfile(OWNER_PROFILE).resolve(OWNER_REALM)
    except (ValueError, OSError) as exc:
        raise ValueError(f"Owner-wide preferences need the owner's personal realm: a profile named '{OWNER_PROFILE}' "
                         f"with the realm alias '{OWNER_REALM}' in the local registry ({exc})") from exc
    return _route(workspace, OWNER_PROFILE, OWNER_REALM)


def retain_through_queue(workspace, profile, *, key, title, body, artifacts=(), experience=None, preference=None, supersedes=None,
                         route=None):
    from .activity_cli import resolve
    from .command_line import queue_retention
    args = route or _route(workspace, profile)
    app, scopes, _ = resolve(args)
    return queue_retention(args, app, scopes, list(artifacts), title=title, body=body, key=key,
                           experience=experience, preference=preference, supersedes=supersedes)


def queue_states(workspace, profile, keys):
    """Publication state of queued requests by key; an unknown key is absent."""
    from .activity_cli import local_store, resolve
    app, scopes, manifest = resolve(_route(workspace, profile))
    store = local_store(app, manifest['id'])
    try:
        states = {row['key']: row['state'] for row in store.status(scopes)['operations']}
        return {key: states[key] for key in keys if key in states}
    finally:
        store.close()


# ---------------------------------------------------------------------- observer
class Observer:
    def __init__(self, store=None, *, retain=retain_through_queue, states=queue_states, clock=time.time):
        self.store, self.retain, self.states, self.clock = store or ExperienceStore(), retain, states, clock
        self.touched, self.attempted, self.expired = set(), set(), {}
        self._profile_of = None

    # -- spool -------------------------------------------------------------------
    def ingest(self):
        spool = self.store.directory / 'spool'
        if not spool.is_dir():
            return 0
        self._profile_of = None  # the caller registry is read again on each pass
        documents = []
        for path in sorted(spool.glob('*.json')):
            try:
                documents.append((path, json.loads(path.read_text(encoding='utf-8'))))
            except (OSError, ValueError):
                documents.append((path, None))
        # Uncommitted files are read now, so within one pass only the latest event of a
        # workspace can say what they were at its moment.
        latest = {}
        for path, document in documents:
            if isinstance(document, dict) and document.get('event') != 'UserPromptSubmit' and isinstance(document.get('workspace'), str):
                latest[document['workspace']] = path
        count = 0
        for path, document in documents:
            try:
                if self.clock() - float(document.get('at', 0)) > SPOOL_DAYS * 86400:
                    self.store.count('spool_expired')
                elif self._ingest_one(document, fresh=latest.get(document.get('workspace')) == path):
                    count += 1
            except Exception:  # one unreadable event must not hold back the ones behind it
                self.store.count('spool_invalid')
            try:
                path.unlink()
            except OSError:
                pass
        return count

    def _ingest_one(self, document, *, fresh=True):
        if document.get('schema') != 'ekk.observed-event/0.2':
            self.store.count('spool_invalid')
            return False
        workspace, event, at = document['workspace'], document['event'], float(document['at'])
        bound = workspace_binding(workspace)
        if bound is None:
            self.store.count('unroutable')
            return False
        common = dict(host=document.get('host'), profile=self._profile(document), session=str(document.get('session') or ''),
                      turn=document.get('turn'), workspace=workspace, realm=bound['realm'], at=at,
                      runtime=host_identity.bounded(document.get('runtime'), 64),
                      transcript_path=host_identity.bounded(document.get('transcript_path'), host_identity.MAX_PATH_CHARS))
        self.touched.add(workspace)
        if event == 'UserPromptSubmit':
            added = self.store.add_event(kind='prompt', state='used', **common)
            text = document.get('text') or ''
            if text:
                # A correction follows agent work; the first message of a session is a task.
                if self.store.events(workspace=workspace, session=common['session'], kind='report', before=at):
                    self.store.add_event(kind='correction', text=observation.single_line(text, observation.MAX_CORRECTION_CHARS),
                                         state='pending', **common)
                else:
                    self.store.count('corrections_without_prior_work')
            return bool(added)
        # Taking the signatures in the hook would cost 237–283 ms on a 2,500-file checkout (medians of five
        # `git status` runs, 2 October 2026, under the owner's usual load), so the observer takes them and an
        # event it processes late can credit its session by commits only. The count makes that visible.
        late = self.clock() - at > STATE_FRESH_SECONDS
        known = fresh and not late
        state = {'repositories': repository_state(workspace, document.get('heads'), fresh=known)}
        if late and state['repositories']:
            self.store.count('events_state_unknown')  # processed late: credited by commits only
        if event == 'Stop':
            text = document.get('text') or ''
            if not text and document.get('transcript'):
                raw, _ = observation.bounded(report_from_transcript(document['transcript']).strip(), observation.MAX_REPORT_CHARS + 2000)
                text, _ = observation.bounded(observation.redact(raw), observation.MAX_REPORT_CHARS)
            if not text:
                self.store.count('reports_empty')
                return bool(self.store.add_event(kind='turn_end', state='used', extra=state, **common))
            return bool(self.store.add_event(kind='report', text=text, extra=state, **common))
        if event == 'SessionStart':
            return bool(self.store.add_event(kind='start', state='used', extra={**state, 'source': document.get('source')}, **common))
        if event == 'SessionEnd':
            return bool(self.store.add_event(kind='end', state='used', extra={**state, 'reason': document.get('reason')}, **common))
        return False

    def _profile(self, document):
        """The fleet key of the Codex home the hook saw, mapped as the journal maps CODEX_HOME; None otherwise.

        The spooled profile is never used: the hook cannot read the registry.
        """
        if document.get('host') != 'codex':
            return None
        home = (host_identity.bounded(document.get('codex_home'), host_identity.MAX_PATH_CHARS)
                or host_identity.transcript_home(document.get('transcript_path') or document.get('transcript')))
        if home is None:
            return None
        if self._profile_of is None:
            self._profile_of = host_identity.profile_lookup()
        return self._profile_of(home)

    # -- episodes ----------------------------------------------------------------
    def close_episodes(self):
        now, queued = self.clock(), 0
        sessions = {}
        for report in self.store.events(kind='report', state='new'):
            sessions.setdefault((report['workspace'], report['session']), []).append(report)
        for (workspace, session), reports in sessions.items():
            events = self.store.events(workspace=workspace, session=session)
            ended = any(event['kind'] == 'end' and event['at'] >= reports[-1]['at'] for event in events)
            marks = [event for event in events if event['kind'] in ('start', 'prompt', 'report', 'turn_end')]
            if rules.ready(ended=ended, turn_open=marks[-1]['kind'] == 'prompt', last_activity=marks[-1]['at'], now=now):
                queued += self._close(workspace, session, reports, self._state_after(reports[-1], events))
        return queued

    @staticmethod
    def _state_after(report, events):
        """The repository state the session left: the agent has stopped, so its end event may know more than its last report."""
        states = [event['extra']['repositories'] for event in events
                  if event['at'] >= report['at'] and event['kind'] in ('report', 'turn_end', 'end') and event['extra'].get('repositories')]
        known = [state for state in states if all(isinstance(row.get('dirty'), dict) for row in state.values())]
        return known[-1] if known else report['extra'].get('repositories')

    def _close(self, workspace, session, reports, after):
        first, last, host = reports[0], reports[-1], reports[0]['host'] or 'unknown'
        key = 'episode-' + hashlib.sha256(json.dumps([first['realm'], host, session, first['id']]).encode()).hexdigest()[:40]
        episode = self.store.episode(key)
        if episode and episode['state'] in SETTLED:
            # Stopped between settling the episode and marking its reports.
            covered = json.loads(episode['covers'])
            self.store.set_event_state(covered, 'used', clear_text=True)
            remaining = [report for report in reports if report['id'] not in covered]
            return self._close(workspace, session, remaining, after) if remaining else 0
        if episode and episode.get('request'):
            # Composed before a crash or a refused route: publish the same bytes for the same
            # reports; reports that arrived since form the next episode.
            covered = json.loads(episode['covers'])
            queued = self.publish(key, workspace, json.loads(episode['request']), covered, episode['reason'] or '')
            remaining = [report for report in reports if report['id'] not in covered]
            return queued + (self._close(workspace, session, remaining, after) if queued and remaining else 0)
        else:
            baseline_at, before = self.store.session_baseline(workspace, session, first['at'])
            changes = repository_changes(before, after, workspace)
            others = bool(changes) and self.store.other_sessions_active(
                workspace, session, baseline_at or first['at'], last['at'], idle=rules.IDLE_SECONDS, turn=rules.MAX_TURN_SECONDS)
            action, reason = rules.disposition(reports, changes, others_active=others)
            covered = [report['id'] for report in reports]
            common = dict(workspace=workspace, realm=first['realm'], host=host, profile=first.get('profile'), session=session,
                          first_at=first['at'], last_at=last['at'], reason=reason, rule=rules.EPISODE_RULE, covers=json.dumps(covered))
            if action == 'skip':
                self.store.set_event_state(covered, 'skipped', clear_text=True)
                self.store.save_episode(key, state='skipped', **common)
                self.store.count('episodes_skipped')
                return 0
            corrections = [event for event in self.store.events(workspace=workspace, session=session, kind='correction')
                           if not event['extra'].get('episode')]
            title, body, experience = rules.compose_outcome(reports, changes, host=host, session=session,
                                                            corrections=len(corrections), others_active=others)
            request = {'title': title, 'body': body, 'experience': experience}
            self.store.save_episode(key, state='composed' if action == 'keep' else 'held', title=title,
                                    request=json.dumps(request, ensure_ascii=False), **common)
            for correction in corrections:
                self.store.set_event_extra(correction['id'], {**correction['extra'], 'episode': key})
            if action == 'hold':  # the owner decides on the review page; nothing is published
                self.store.set_event_state(covered, 'used', clear_text=True)
                self.store.count('episodes_held')
                return 0
            return self.publish(key, workspace, request, covered, reason)

    def publish(self, key, workspace, request, covered, reason=''):
        """Queue a composed outcome; on refusal it stays composed for the next pass."""
        self.attempted.add(key)
        bound = workspace_binding(workspace)
        reason = reason.split('; last error', 1)[0]
        try:
            if bound is None:
                raise PermissionError('no single realm binding')
            self.retain(workspace, bound['profile'], key=key, title=request['title'], body=request['body'], experience=request['experience'])
        except Exception as exc:
            self.store.save_episode(key, state='composed', reason=f'{reason}; last error {type(exc).__name__}')
            self.store.count('episodes_retry')
            return 0
        self.store.set_event_state(covered, 'used', clear_text=True)
        self.store.save_episode(key, state='queued', reason=reason)
        self.store.count('episodes_queued')
        return 1

    def retry_composed(self):
        """Queue composed outcomes from their episode rows, which outlive their reports' 30 days.

        A key already attempted in this pass is not retried, nor is a request that is not JSON.
        """
        queued = 0
        for episode in self.store.episodes('composed'):
            if episode['key'] in self.attempted or not episode['request']:
                continue
            try:
                request, covered = json.loads(episode['request']), json.loads(episode['covers'])
            except ValueError:
                continue
            queued += self.publish(episode['key'], episode['workspace'], request, covered, episode['reason'] or '')
        return queued

    def reconcile(self):
        """Follow queued outcomes to publication; the composed text is dropped once the realm holds it."""
        waiting = {}
        for episode in self.store.episodes('queued') + self.store.episodes('failed'):
            waiting.setdefault(episode['workspace'], []).append(episode)
        published = set()
        for workspace, episodes in waiting.items():
            bound = workspace_binding(workspace)
            try:
                states = self.states(workspace, bound['profile'], [episode['key'] for episode in episodes]) if bound else {}
            except Exception:
                continue
            for episode in episodes:
                state = states.get(episode['key'])
                if state in PUBLISHED:
                    self.store.save_episode(episode['key'], state='published', request=None)
                    self.store.count('episodes_published')
                    published.add(workspace)
                elif state == 'needs_attention' and episode['state'] != 'failed':
                    self.store.save_episode(episode['key'], state='failed', request=None)
                    self.store.count('episodes_failed')
        return published

    # -- cards -------------------------------------------------------------------
    def refresh_cards(self, forced=()):
        for workspace in sorted(self.touched | set(forced)):
            path = card_path(workspace)
            try:
                fresh = self.clock() - path.stat().st_mtime < CARD_SECONDS
            except OSError:
                fresh = False
            bound = None if fresh and workspace not in forced else workspace_binding(workspace)
            if bound is None:
                continue
            try:
                write_card(workspace, bound['profile'])
            except Exception:
                self.store.count('cards_failed')

    def run(self):
        """One pass: ingest, close episodes, retry composed ones, follow publication, then expire on the observer clock.

        The only caller of the full expiry; its counted deltas are kept in ``expired``.
        """
        total, self.attempted = 0, set()
        for attempt in range(20):  # events that arrive while this pass works are taken by the same worker
            ingested = self.ingest()
            if attempt and not ingested:
                break
            total += self.close_episodes()
        total += self.retry_composed()
        self.refresh_cards(self.reconcile())
        self.expired = self.store.expire(self.clock())
        return total


def _listed(row):
    metadata = row['metadata']
    return {'id': metadata['id'], 'title': metadata['title'], 'date': str(metadata.get('created_at', ''))[:10]}


def current_preferences(current, *, owner_wide):
    """Owner-stated preferences in force, newest first: the project's own, or the owner-wide ones (area 'owner:all')."""
    rows = [row for row in current.values() if rules.owner_stated(row['metadata'])
            and (row['metadata']['preference'].get('area') == rules.OWNER_AREA) == owner_wide]
    return sorted((_listed(row) for row in rows), key=lambda item: item['date'], reverse=True)


def owner_preferences(workspace):
    """The owner-wide preferences in force, read from the personal realm; none when it is not configured or readable."""
    from .activity_cli import resolve
    try:
        app, scopes, _ = resolve(owner_route(workspace))
        current = app.card_view(scopes)
    except (ValueError, OSError, KeyError, PermissionError):
        return []
    return current_preferences(current, owner_wide=True)


def write_card(workspace, profile):
    """Session card: the contract, the owner's current preferences (the project's, then owner-wide) and the latest results.

    Selection is the application's: readable records of the bound contexts,
    replaced ones left out as entry leaves them out.
    """
    from .activity_cli import resolve
    app, scopes, _ = resolve(_route(workspace, profile))
    current = app.card_view(scopes)
    preferences = current_preferences(current, owner_wide=False)
    results = sorted((_listed(row) for row in current.values() if row['metadata']['kind'] == 'outcome'), key=lambda item: item['date'], reverse=True)
    owner_wide = owner_preferences(workspace)
    path = card_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f'.{path.name}.{os.getpid()}')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(rules.card(preferences, results, owner_wide))
    os.replace(temporary, path)
    return path


def card_after_publication(cwd):
    """Called by the queue worker once a result is in the realm, so the next session sees it.

    The card belongs to the bound workspace enclosing ``cwd`` and is built on its
    own binding, whichever realm the publication went to (an owner-wide
    preference goes to the personal realm).
    """
    try:
        workspace = None if switched_off() else workspace_of(cwd)
        bound = workspace_binding(workspace) if workspace is not None else None
        if bound is not None:
            write_card(str(workspace), bound['profile'])
    except Exception:
        pass  # a card is a convenience; publication has already succeeded


def drain(*, background=False):
    """Run the observer once; with ``background`` leave quietly when another one is running."""
    directory = observed_home()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directory / 'worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if background:
                return {'schema': 'ekk.observer/0.1', 'state': 'already_running'}
            fcntl.flock(lock, fcntl.LOCK_EX)
        store = ExperienceStore(directory)
        try:
            observer = Observer(store)
            queued = observer.run()
            return {'schema': 'ekk.observer/0.1', 'state': 'drained', 'episodes_queued': queued, 'expired': observer.expired,
                    'stats': store.stats()}
        finally:
            store.close()
