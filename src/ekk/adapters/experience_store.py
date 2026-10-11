"""Private, bounded observer state: host events, episodes, deliveries and task terms.

One SQLite database per OS user under the runtime home. It is operational
state, never canonical knowledge: rows expire, texts are bounded and redacted
before they arrive, and nothing here grants access or acceptance. Canonical
records are written only through the realm's ordinary durable writer.

The schema is the 0.10.0 tables plus one additive step (`SCHEMA_VERSION`, kept
in `PRAGMA user_version`) of nullable columns, so 0.10.0's own statements still
run against it. A NULL `runtime` means unstamped: written by 0.10.0 or earlier,
never a specific version. The step's ledger `episode_keys`, which 0.10.0 never
touches, holds the key of every episode present at the step or counted as created
since, less those counted as deleted; comparing it with `episodes` shows what a
runtime created or deleted without a count.
"""
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from pathlib import Path
import sqlite3
import time
import uuid

from .. import __version__
from ..homes import data_home

DAY = 86400
EVENT_DAYS = 30  # events other than corrections
DELIVERY_DAYS = 60  # unlabelled deliveries; an owner-labelled one is kept to ROW_DAYS, outside the cap
MAX_DELIVERIES = 2000
READING_DAYS = 60
MAX_READINGS = 10000
MAX_SEEN_TASKS = 20000
ROW_DAYS = 365
NOTICE_DAYS = 14

# The retention table `ekk.observer-expiry/1`, its one source: per kind and state, (text days, row days)
# from the last activity, `coalesce(last_at, updated)` for an episode and `at` for a correction event.
# At its text horizon an unjudged state (UNJUDGED) becomes a counted `expired_unreviewed` tombstone;
# any other state's text is cleared and the state kept. None: no text left. 0.11's states are listed
# already, so a rollback from 0.11 keeps its policy; a state not listed falls under UNKNOWN_STATE.
EXPIRY_POLICY = 'ekk.observer-expiry/1'
EXPIRED = 'expired_unreviewed'
EXPIRY = {
    'episode': {'held': (60, ROW_DAYS), 'composed': (60, ROW_DAYS),
                'queued': (30, ROW_DAYS), 'failed': (30, ROW_DAYS),  # in flight: reconcile needs only the key
                'published': (30, ROW_DAYS), 'rejected': (30, ROW_DAYS), 'linked': (30, ROW_DAYS),
                'not_owner_work': (30, ROW_DAYS), 'skipped': (14, ROW_DAYS), EXPIRED: (None, ROW_DAYS)},
    'correction': {'pending': (90, ROW_DAYS), 'review_dialogue': (90, ROW_DAYS), 'confirmed': (90, ROW_DAYS),
                   'rejected': (90, ROW_DAYS), 'not_owner_work': (90, ROW_DAYS), EXPIRED: (None, ROW_DAYS)},
}
UNJUDGED = {'episode': ('held', 'composed'), 'correction': ('pending', 'review_dialogue')}
UNKNOWN_STATE = (60, ROW_DAYS)  # text cleared, state kept, row kept to the end, each counted apart
# Where each kind lives: table, age, row filter, text clearing, "still has text".
_KINDS = {'episode': ('episodes', 'coalesce(last_at,updated)', '1=1', 'title=NULL,request=NULL', '(title IS NOT NULL OR request IS NOT NULL)'),
          'correction': ('events', 'at', "kind='correction'", "text=''", "text!=''")}
EXPIRY_COUNTERS = (tuple(f'{kind}s_expired_{state}' for kind, states in UNJUDGED.items() for state in states)
                   + tuple(f'{kind}s_{action}' for kind in EXPIRY
                           for action in ('text_cleared', 'text_cleared_unknown_state', 'deleted', 'deleted_unknown_state'))
                   + ('events_expired', 'deliveries_expired', 'readings_expired', 'readings_delivery_expired', 'task_seen_dropped',
                      'labels_expired', 'advice_expired', 'review_applications_expired'))
# json_type is evaluated only on valid JSON; a rule that is not text stays unknown, never guessed.
_RULE_IS_TEXT = "CASE WHEN json_valid(request) THEN json_type(request,'$.experience.rule')='text' ELSE 0 END"

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS events(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, host TEXT, profile TEXT, session TEXT, turn TEXT,
  workspace TEXT NOT NULL, realm TEXT, at REAL NOT NULL, text TEXT NOT NULL DEFAULT '',
  extra TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_session ON events(workspace, session, at);
CREATE TABLE IF NOT EXISTS episodes(
  key TEXT PRIMARY KEY, workspace TEXT NOT NULL, realm TEXT, host TEXT, session TEXT,
  first_at REAL, last_at REAL, state TEXT NOT NULL, title TEXT, request TEXT, covers TEXT NOT NULL DEFAULT '[]',
  reason TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS deliveries(
  id TEXT PRIMARY KEY, at REAL NOT NULL, workspace TEXT, realm TEXT, task TEXT, snapshot TEXT,
  items TEXT NOT NULL, baseline TEXT NOT NULL DEFAULT '[]', used TEXT NOT NULL DEFAULT '[]', labels TEXT);
CREATE TABLE IF NOT EXISTS readings(
  id TEXT PRIMARY KEY, at REAL NOT NULL, operation TEXT NOT NULL,
  workspace TEXT, realm TEXT, record_id TEXT, revision INTEGER, digest TEXT,
  host TEXT, profile TEXT, session TEXT, delivery_id TEXT, link_state TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS readings_delivery ON readings(delivery_id);
CREATE TABLE IF NOT EXISTS labels(target TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS task_terms(realm TEXT NOT NULL, stem TEXT NOT NULL, tasks INTEGER NOT NULL, PRIMARY KEY(realm, stem));
CREATE TABLE IF NOT EXISTS task_seen(realm TEXT NOT NULL, digest TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(realm, digest));
CREATE TABLE IF NOT EXISTS advice(
  target TEXT NOT NULL, operation TEXT NOT NULL, model TEXT NOT NULL, label TEXT NOT NULL,
  probabilities TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(target, operation, model));
CREATE TABLE IF NOT EXISTS stats(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
'''
SCHEMA_VERSION = 1
# The additive step to SCHEMA_VERSION: nullable columns, two tables and one index. The deliveries
# columns before `runtime` are the 0.10.0 migration, kept for databases older than that.
_COLUMNS = (
    ('events', (('runtime', 'TEXT'), ('transcript_path', 'TEXT'), ('expired_from', 'TEXT'), ('expired_at', 'REAL'))),
    ('episodes', (('profile', 'TEXT'), ('runtime', 'TEXT'), ('rule', 'TEXT'), ('shadow', 'TEXT'),
                  ('expired_from', 'TEXT'), ('expired_at', 'REAL'))),
    ('deliveries', (('host', 'TEXT'), ('profile', 'TEXT'), ('session', 'TEXT'), ('reading_schema', 'INTEGER NOT NULL DEFAULT 1'),
                    ('runtime', 'TEXT'), ('labels_application', 'TEXT'))),
    ('readings', (('runtime', 'TEXT'),)),
    ('labels', (('runtime', 'TEXT'), ('application', 'TEXT'))),
    ('advice', (('runtime', 'TEXT'),)),
)
_LEDGER = ('episode_keys', 'CREATE TABLE IF NOT EXISTS episode_keys(key TEXT PRIMARY KEY)')
_OBJECTS = (
    ('review_applications', 'CREATE TABLE IF NOT EXISTS review_applications(id TEXT PRIMARY KEY, at REAL NOT NULL, page TEXT, '
                            'page_sha256 TEXT, declared TEXT NOT NULL, words TEXT, words_sha256 TEXT, words_chars INTEGER, host TEXT, '
                            'profile TEXT, session TEXT, statement_session TEXT, contradicts INTEGER NOT NULL DEFAULT 0, counts TEXT, '
                            'runtime TEXT)'),
    ('episodes_state', 'CREATE INDEX IF NOT EXISTS episodes_state ON episodes(state, last_at)'),
    _LEDGER,
)
EPISODE_FIELDS = ('workspace', 'realm', 'host', 'profile', 'session', 'first_at', 'last_at', 'state', 'title', 'request', 'covers',
                  'reason', 'rule', 'shadow', 'expired_from', 'expired_at')
# Explicit projections: a column a later runtime adds never leaks into these outputs.
_READING_COLUMNS = 'id,at,operation,workspace,realm,record_id,revision,digest,host,profile,session,delivery_id,link_state,runtime'
_DELIVERY_COLUMNS = 'id,at,workspace,realm,task,snapshot,items,baseline,used,labels,host,profile,session,reading_schema,runtime'


def _digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _missing(db):
    """What the additive step still has to add: [(table, column, declaration)] and [statement]."""
    columns = []
    for table, added in _COLUMNS:
        present = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        columns += [(table, name, declaration) for name, declaration in added if name not in present]
    objects = {row[0] for row in db.execute('SELECT name FROM sqlite_master WHERE name IN (' + ','.join('?' * len(_OBJECTS)) + ')',
                                            [name for name, _ in _OBJECTS])}
    return columns, [statement for name, statement in _OBJECTS if name not in objects]


def _migrate(db):
    """The one additive step, inside the caller's write transaction.

    The version is never lowered, and a newer one is kept. `episodes.rule` is
    backfilled from the stored request when this step adds the column, and the
    ledger `episode_keys` is seeded from the present episodes when this step
    creates it, never later: a later seed would absorb uncounted creations.
    """
    version = db.execute('PRAGMA user_version').fetchone()[0]
    columns, objects = _missing(db)
    for table, name, declaration in columns:
        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
    for statement in objects:
        db.execute(statement)
    if ('episodes', 'rule', 'TEXT') in columns:
        db.execute("UPDATE episodes SET rule=json_extract(request,'$.experience.rule') WHERE " + _RULE_IS_TEXT)
    if _LEDGER[1] in objects:
        db.execute('INSERT OR IGNORE INTO episode_keys(key) SELECT key FROM episodes')
    if version < SCHEMA_VERSION:
        db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')


def horizons(state, kind='episode'):
    """(text days, row days) of a state of an 'episode' or a 'correction'; a state not in the table gets UNKNOWN_STATE."""
    return EXPIRY[kind].get(state, UNKNOWN_STATE)


def expires_at(state, last_activity, *, kind='episode'):
    """When an item in ``state`` loses its text, in epoch seconds, from the retention table.

    For an unjudged state (held, composed, pending, review_dialogue) this is when it
    expires unreviewed. None when nothing is left to expire or the activity is unknown.
    """
    days = horizons(state, kind)[0]
    return None if days is None or last_activity is None else last_activity + days * DAY


def _iso(at):
    return None if at is None else datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _text_groups(kind):
    """{text days: states} of the table's states whose text is cleared rather than tombstoned."""
    groups = {}
    for state, (days, _) in EXPIRY[kind].items():
        if days is not None and state not in UNJUDGED[kind]:
            groups.setdefault(days, []).append(state)
    return groups


def _row_groups(kind):
    groups = {}
    for state, (_, days) in EXPIRY[kind].items():
        groups.setdefault(days, []).append(state)
    return groups


def _marks(values):
    return ','.join('?' * len(values))


def _expiry_state(db, now):
    """The expiry state at ``now`` of any connection to the observer database; see ExperienceStore.expiry_state."""
    stepped = 'expired_from' in {row[1] for row in db.execute('PRAGMA table_info(episodes)')}
    unjudged, clearing, tombstones, text_free = {}, [], {}, {}
    for kind, (table, age, rows, _, has_text) in _KINDS.items():
        for state in UNJUDGED[kind]:
            days = EXPIRY[kind][state][0]
            count, oldest, soon = db.execute(f'SELECT count(*),min({age}),coalesce(sum({age}<=?),0) FROM {table} WHERE {rows} AND state=?',
                                             (now + (NOTICE_DAYS - days) * DAY, state)).fetchone()
            unjudged[state] = {'count': count, 'oldest': _iso(oldest), 'next_expiry': _iso(expires_at(state, oldest, kind=kind)),
                               'within_14_days': soon}
        known = tuple(EXPIRY[kind])
        groups = [(days, f'state IN ({_marks(states)})', states) for days, states in _text_groups(kind).items()]
        groups.append((UNKNOWN_STATE[0], f'state NOT IN ({_marks(known)})', known))
        for days, where, values in groups:
            oldest = db.execute(f'SELECT min({age}) FROM {table} WHERE {rows} AND {where} AND {has_text}', values).fetchone()[0]
            if oldest is not None:
                clearing.append(oldest + days * DAY)
        if stepped:
            tombstones[kind] = {row[0]: row[1] for row in db.execute(
                f"SELECT coalesce(expired_from,'unknown'),count(*) FROM {table} WHERE {rows} AND state=? GROUP BY 1 ORDER BY 1", (EXPIRED,))}
        settled = (*UNJUDGED[kind], EXPIRED)
        text_free[kind] = db.execute(f'SELECT count(*) FROM {table} WHERE {rows} AND state NOT IN ({_marks(settled)}) AND NOT {has_text}',
                                     settled).fetchone()[0]
    stats = {row[0]: row[1] for row in db.execute('SELECT name,value FROM stats')}
    deleted = created = None  # unknown without the ledger
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_LEDGER[0],)).fetchone():
        deleted, created = db.execute('SELECT (SELECT count(*) FROM episode_keys WHERE key NOT IN (SELECT key FROM episodes)),'
                                      '(SELECT count(*) FROM episodes WHERE key NOT IN (SELECT key FROM episode_keys))').fetchone()
    losses = [row['next_expiry'] for row in unjudged.values() if row['next_expiry']]
    return {'policy': EXPIRY_POLICY, 'unjudged': unjudged, 'next_expiry': min(losses, default=None),
            'next_text_clearing': _iso(min(clearing, default=None)),
            'expired_unreviewed': {f'{kind}s': rows for kind, rows in tombstones.items()},
            'text_free_rows': {f'{kind}s': count for kind, count in text_free.items()},
            'counters': {name: stats.get(name, 0) for name in EXPIRY_COUNTERS},
            'episodes_deleted_uncounted': deleted, 'episodes_created_uncounted': created,
            'meaning': 'next_expiry is the earliest loss of material the owner has not judged (held and composed results, '
                       'pending corrections); next_text_clearing is when judged or terminal rows next lose their text. '
                       'episodes_deleted_uncounted is 0 unless a runtime deleted episodes without a count; '
                       'episodes_created_uncounted counts episodes a runtime created without a count, for information.'}


class ExperienceStore:
    def __init__(self, directory=None, *, timeout=5):
        self.directory = Path(directory) if directory else data_home() / 'observed'
        if self.directory.is_symlink():
            raise PermissionError('Observer state must not be a symlink')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.directory.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError('Observer state must be private to the OS owner')
        path = self.directory / 'state.sqlite'
        if not path.exists():
            os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
        self.db = sqlite3.connect(path, timeout=timeout, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript(_SCHEMA)
        if self.db.execute('PRAGMA user_version').fetchone()[0] >= SCHEMA_VERSION and _missing(self.db) == ([], []):
            return
        # Serialize the additive step, its presence check included, against another
        # host process opening an older private database at the same time.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            _migrate(self.db)
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            self.db.close()
            raise

    def close(self):
        self.db.close()

    # ------------------------------------------------------------------ events
    def add_event(self, *, kind, host, profile, session, turn, workspace, realm, at, text='', extra=None, state='new',
                  runtime=None, transcript_path=None):
        """Insert one observed event once; a replayed spool file changes nothing.

        ``runtime`` is the capturing hook's, from the spool; it is not part of the identity.
        """
        identity = _digest(kind, host, session, turn, workspace, round(at, 3), hashlib.sha256(text.encode()).hexdigest())
        inserted = self.db.execute(
            'INSERT OR IGNORE INTO events(id,kind,host,profile,session,turn,workspace,realm,at,text,extra,state,runtime,transcript_path) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity, kind, host, profile, session, turn, workspace, realm, at, text,
             json.dumps(extra or {}, ensure_ascii=False), state, runtime, transcript_path)).rowcount
        return identity if inserted else None

    def events(self, *, workspace=None, session=None, kind=None, state=None, before=None):
        query, values = 'SELECT * FROM events WHERE 1=1', []
        for column, value in (('workspace', workspace), ('session', session), ('kind', kind), ('state', state)):
            if value is not None:
                query += f' AND {column}=?'
                values.append(value)
        if before is not None:
            query += ' AND at<?'
            values.append(before)
        return [self._event(row) for row in self.db.execute(query + ' ORDER BY at, id', values)]

    @staticmethod
    def _event(row):
        return {**dict(row), 'extra': json.loads(row['extra'])}

    def set_event_state(self, identities, state, *, clear_text=False):
        for identity in identities:
            self.db.execute('UPDATE events SET state=?' + (", text=''" if clear_text else '') + ' WHERE id=?', (state, identity))

    def set_event_extra(self, identity, extra):
        self.db.execute('UPDATE events SET extra=? WHERE id=?', (json.dumps(extra, ensure_ascii=False), identity))

    def session_baseline(self, workspace, session, before):
        """The repository state this session itself observed last before a moment, with its time."""
        row = self.db.execute("SELECT at,extra FROM events WHERE workspace=? AND session=? AND at<? AND extra LIKE '%\"repositories\"%' "
                              'ORDER BY at DESC LIMIT 1', (workspace, session, before)).fetchone()
        return (row['at'], json.loads(row['extra']).get('repositories')) if row else (None, None)

    def other_sessions_active(self, workspace, session, since, until, *, idle, turn):
        """Whether another session was live in the workspace during a period.

        Live: it had an event in the period, or shortly before it without having
        ended: within ``idle`` seconds, or within ``turn`` seconds with a turn in progress.
        """
        last = {}
        for row in self.db.execute('SELECT session,kind,at FROM events WHERE workspace=? AND session!=? AND at>=? AND at<=? ORDER BY at',
                                   (workspace, session, since - turn, until)):
            if row['at'] >= since:
                return True
            last[row['session']] = (row['kind'], row['at'])
        return any(kind == 'prompt' or (kind != 'end' and since - at <= idle) for kind, at in last.values())

    # ---------------------------------------------------------------- episodes
    def episode(self, key):
        row = self.db.execute('SELECT * FROM episodes WHERE key=?', (key,)).fetchone()
        return dict(row) if row else None

    def save_episode(self, key, **fields):
        """Set the named fields of one episode, stamped with this runtime; columns not named keep their values.

        A new key enters the ledger and is counted as ``episodes_created``, in the
        transaction that writes the row; a re-saved key does neither. SQLite checks
        NOT NULL before it resolves a conflict, so the row offered for insertion is
        the merged one.
        """
        unknown = set(fields) - set(EPISODE_FIELDS)
        if unknown:
            raise ValueError('Unknown episode fields: ' + ', '.join(sorted(unknown)))
        with self._atomic('save_episode'):
            current = self.episode(key)
            named = {**fields, 'updated': time.time(), 'runtime': __version__}
            row = {**(current or {'covers': '[]'}), **named}
            columns = ('key', *EPISODE_FIELDS, 'updated', 'runtime')
            self.db.execute('INSERT INTO episodes(' + ','.join(columns) + ') VALUES (' + ','.join('?' * len(columns)) + ') '
                            'ON CONFLICT(key) DO UPDATE SET ' + ','.join(f'{name}=excluded.{name}' for name in named),
                            (key, *(row.get(column) for column in columns[1:])))
            if current is None:
                self.db.execute('INSERT OR IGNORE INTO episode_keys(key) VALUES (?)', (key,))
                self.count('episodes_created')

    def episodes(self, state=None):
        rows = self.db.execute('SELECT * FROM episodes' + (' WHERE state=?' if state else '') + ' ORDER BY updated', (state,) if state else ())
        return [dict(row) for row in rows]

    # -------------------------------------------------------------- deliveries
    def note_delivery(self, *, workspace, realm, task, snapshot, items, baseline=(),
                      host=None, profile=None, session=None, at=None):
        """An entry's exact selected references, with only observed caller identity.

        Delivery is not opening, application, or benefit. Unknown identities remain
        unknown; legacy `used` marks are never upgraded by this schema.
        """
        at = time.time() if at is None else at
        identity = _digest(workspace, realm, task, snapshot, host, profile, session, at)
        self.db.execute('INSERT INTO deliveries(id,at,workspace,realm,task,snapshot,items,baseline,host,profile,session,reading_schema,runtime) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?,?,2,?)',
                        (identity, at, workspace, realm, task, snapshot, json.dumps(items, ensure_ascii=False),
                         json.dumps(list(baseline), ensure_ascii=False), host, profile, session, __version__))
        self.prune(at)
        return identity

    @staticmethod
    def _exact_reference(reference):
        return (isinstance(reference, dict) and all(isinstance(reference.get(k), str) and reference[k]
                                                   for k in ('realm', 'id'))
                and type(reference.get('revision')) is int and reference['revision'] > 0
                and isinstance(reference.get('digest'), str)
                and re.fullmatch(r'sha256:[0-9a-f]{64}', reference['digest']) is not None)

    def note_reading(self, *, reference, operation, workspace=None, host=None, profile=None,
                     session=None, at=None, within=86400):
        """A successful exact fetch/source opening; never a claim of actual use.

        Link only one matching delivery with established identity and exact bytes.
        Multiple deliveries are ambiguous, not a reason to choose the latest.
        Missing identity/version remains explicit unknown. No report text is stored.
        """
        self.db.execute('BEGIN IMMEDIATE')
        try:
            identity = self._note_reading(reference=reference, operation=operation, workspace=workspace,
                                          host=host, profile=profile, session=session, at=at, within=within)
            self.db.execute('COMMIT')
            return identity
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _note_reading(self, *, reference, operation, workspace, host, profile, session, at, within):
        # The candidate check and receipt are one database observation, so a
        # concurrent entry cannot change the candidate set between them.
        if operation not in ('fetch', 'read-source'):
            raise ValueError('A reading operation must be fetch or read-source')
        at = time.time() if at is None else at
        reference = reference if isinstance(reference, dict) else {}
        exact = self._exact_reference(reference)
        known_identity = all(isinstance(value, str) and value and value != 'unknown'
                             for value in (workspace, host, session))
        state, linked = ('unknown_reference' if not exact else 'unknown_identity'), None
        if exact and known_identity:
            matches = []
            for row in self.db.execute('SELECT id,items FROM deliveries WHERE reading_schema=2 AND realm=? '
                                       'AND workspace=? AND host=? AND session=? AND profile IS ? AND at>=? AND at<=?',
                                       (reference['realm'], workspace, host, session, profile, at - within, at)):
                if any(self._exact_reference(item) and
                       all(item[k] == reference[k] for k in ('realm', 'id', 'revision', 'digest'))
                       for item in json.loads(row['items'])):
                    matches.append(row['id'])
            if len(matches) == 1:
                state, linked = 'linked', matches[0]
            else:
                state = 'ambiguous_delivery' if matches else 'no_matching_delivery'
        identity = _digest(reference, operation, workspace, host, profile, session, at)
        self.db.execute('INSERT OR IGNORE INTO readings(id,at,operation,workspace,realm,record_id,revision,digest,host,profile,session,delivery_id,link_state,runtime) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (identity, at, operation, workspace, reference.get('realm'), reference.get('id'),
                         reference.get('revision'), reference.get('digest'), host, profile, session, linked, state, __version__))
        self.prune(at)
        return identity

    def note_use(self, realm, record_id, *, within=86400):
        """Compatibility for old callers: a version/identity-unknown opening.

        No new legacy `used` mark and no exact delivery attribution is inferred.
        """
        return self.note_reading(reference={'realm': realm, 'id': record_id}, operation='fetch', within=within)

    def readings(self, *, since=0, delivery_id=None):
        query, values = f'SELECT {_READING_COLUMNS} FROM readings WHERE at>=?', [since]
        if delivery_id is not None:
            query += ' AND delivery_id=?'
            values.append(delivery_id)
        return [{'schema': 'ekk.reading-receipt/0.1', **dict(row),
                 'meaning': 'Successful opening only; application and benefit are unknown.'}
                for row in self.db.execute(query + ' ORDER BY at,id', values)]

    def deliveries(self, *, since=0, workspace=None):
        query, values = f'SELECT {_DELIVERY_COLUMNS} FROM deliveries WHERE at>=?', [since]
        if workspace:
            query += ' AND workspace=?'
            values.append(workspace)
        return [{**dict(row), 'items': json.loads(row['items']), 'baseline': json.loads(row['baseline']), 'used': json.loads(row['used']),
                 'labels': json.loads(row['labels']) if row['labels'] else None,
                 'used_semantics': 'legacy_id_only_not_exact_reading', 'legacy_used': json.loads(row['used'])}
                for row in self.db.execute(query + ' ORDER BY at DESC', values)]

    def label_delivery(self, identity, labels, *, application=None):
        """Set the owner's item verdicts of one delivery; ``application`` names the review application that set them."""
        self.db.execute('UPDATE deliveries SET labels=?,labels_application=coalesce(?,labels_application) WHERE id=?',
                        (json.dumps(labels), application, identity))

    def label(self, target, kind, value, *, application=None):
        """Set one verdict, stamped with this runtime and with the review application that set it when one is named;
        other columns of the row keep their values."""
        self.db.execute('INSERT INTO labels(target,kind,value,at,runtime,application) VALUES (?,?,?,?,?,?) ON CONFLICT(target) DO UPDATE SET '
                        'kind=excluded.kind,value=excluded.value,at=excluded.at,runtime=excluded.runtime,'
                        'application=coalesce(excluded.application,labels.application)',
                        (target, kind, json.dumps(value), time.time(), __version__, application))

    def labels(self, kind=None):
        rows = self.db.execute('SELECT * FROM labels' + (' WHERE kind=?' if kind else ''), (kind,) if kind else ())
        return {row['target']: json.loads(row['value']) for row in rows}

    # ----------------------------------------------------- review applications
    def start_review_application(self, *, page, page_sha256, declared, host, profile, session, statement_session=None,
                                 words=None, words_sha256=None, words_chars=None, contradicts=False):
        """Record how one review page is applied, before its first label; returns the row's id.

        Its counts stay NULL until finish_review_application: a row without counts is
        an application that was interrupted. ``session`` is the host identity's;
        ``statement_session`` the one the owner spoke in.
        """
        identity = uuid.uuid4().hex
        self.db.execute('INSERT INTO review_applications(id,at,page,page_sha256,declared,words,words_sha256,words_chars,host,profile,'
                        'session,statement_session,contradicts,runtime) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (identity, time.time(), page, page_sha256, declared, words, words_sha256, words_chars, host, profile, session,
                         statement_session, int(bool(contradicts)), __version__))
        return identity

    def finish_review_application(self, identity, counts):
        self.db.execute('UPDATE review_applications SET counts=? WHERE id=?', (json.dumps(counts, sort_keys=True), identity))

    def review_applications(self, *, contradicting=False):
        """Review applications, oldest first; with ``contradicting`` only those whose declaration contradicts the host identity."""
        rows = self.db.execute('SELECT * FROM review_applications' + (' WHERE contradicts=1' if contradicting else '') + ' ORDER BY at, id')
        return [{**dict(row), 'contradicts': bool(row['contradicts']), 'counts': json.loads(row['counts']) if row['counts'] else None}
                for row in rows]

    # -------------------------------------------------------------- task terms
    def observe_task(self, realm, stems, task):
        """Count each distinct task once: how many tasks used each term."""
        digest = hashlib.sha256(task.encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('INSERT OR IGNORE INTO task_seen(realm,digest,at) VALUES (?,?,?)', (realm, digest, time.time())).rowcount:
                for stem in set(stems):
                    self.db.execute('INSERT INTO task_terms(realm,stem,tasks) VALUES (?,?,1) ON CONFLICT(realm,stem) DO UPDATE SET tasks=tasks+1',
                                    (realm, stem))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def task_terms(self, realm):
        total = self.db.execute('SELECT count(*) FROM task_seen WHERE realm=?', (realm,)).fetchone()[0]
        return total, {row['stem']: row['tasks'] for row in self.db.execute('SELECT stem,tasks FROM task_terms WHERE realm=?', (realm,))}

    # ------------------------------------------------------------------ advice
    def note_advice(self, target, operation, model, label, probabilities):
        """Set one advisory label, stamped with this runtime; other columns of the row keep their values."""
        self.db.execute('INSERT INTO advice(target,operation,model,label,probabilities,at,runtime) VALUES (?,?,?,?,?,?,?) '
                        'ON CONFLICT(target,operation,model) DO UPDATE SET '
                        'label=excluded.label,probabilities=excluded.probabilities,at=excluded.at,runtime=excluded.runtime',
                        (target, operation, model, label, json.dumps(probabilities), time.time(), __version__))

    def advice(self, operation=None):
        rows = self.db.execute('SELECT * FROM advice' + (' WHERE operation=?' if operation else ''), (operation,) if operation else ())
        return [{**dict(row), 'probabilities': json.loads(row['probabilities'])} for row in rows]

    # ------------------------------------------------------------ stats, expiry
    def count(self, name, amount=1):
        self.db.execute('INSERT INTO stats(name,value) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=value+?', (name, amount, amount))

    def stats(self):
        return {row['name']: row['value'] for row in self.db.execute('SELECT * FROM stats')}

    @contextlib.contextmanager
    def _atomic(self, name):
        """One write transaction, or a savepoint inside the caller's (note_reading holds BEGIN IMMEDIATE)."""
        nested = self.db.in_transaction
        self.db.execute(f'SAVEPOINT {name}' if nested else 'BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            if self.db.in_transaction:
                self.db.execute(f'ROLLBACK TO {name}' if nested else 'ROLLBACK')
                if nested:
                    self.db.execute(f'RELEASE {name}')
            raise
        self.db.execute(f'RELEASE {name}' if nested else 'COMMIT')

    def _tally(self, counts, name, cursor):
        if cursor.rowcount > 0:
            self.count(name, cursor.rowcount)
            counts[name] = counts.get(name, 0) + cursor.rowcount

    def prune(self, now=None):
        """Bound deliveries, readings and seen tasks, every deletion counted; the agent's path runs only this.

        An owner-labelled delivery is kept outside the cap until ROW_DAYS. A reading whose
        delivery is gone loses the link, counted. Returns the counted deltas.
        """
        now = time.time() if now is None else now
        counts = {}
        with self._atomic('prune'):
            self._tally(counts, 'deliveries_expired', self.db.execute(
                'DELETE FROM deliveries WHERE CASE WHEN labels IS NULL THEN at<? OR id NOT IN '
                '(SELECT id FROM deliveries WHERE labels IS NULL ORDER BY at DESC LIMIT ?) ELSE at<? END',
                (now - DELIVERY_DAYS * DAY, MAX_DELIVERIES, now - ROW_DAYS * DAY)))
            self._tally(counts, 'readings_expired', self.db.execute(
                'DELETE FROM readings WHERE at<? OR id NOT IN (SELECT id FROM readings ORDER BY at DESC LIMIT ?)',
                (now - READING_DAYS * DAY, MAX_READINGS)))
            # Expired deliveries cannot leave a falsely live association.
            self._tally(counts, 'readings_delivery_expired', self.db.execute(
                "UPDATE readings SET delivery_id=NULL,link_state='delivery_expired' WHERE delivery_id IS NOT NULL "
                'AND delivery_id NOT IN (SELECT id FROM deliveries)'))
            self._tally(counts, 'task_seen_dropped', self.db.execute(
                'DELETE FROM task_seen WHERE digest NOT IN (SELECT digest FROM task_seen ORDER BY at DESC LIMIT ?)', (MAX_SEEN_TASKS,)))
        return counts

    def expire(self, now=None):
        """Apply the retention table once, in one transaction, every transition and deletion counted.

        In order: held and composed episodes, then pending and review-dialogue corrections,
        become `expired_unreviewed` tombstones (prior state in `expired_from`, text gone);
        other text is cleared per state; rows past their row horizon are deleted; then
        non-correction events (`events_expired`) and the bounded tables. No UPDATE touches
        `last_at`, `updated` or `at`, so the row horizon still counts from the last activity.
        Only the observer worker runs this. Returns the counted deltas.
        """
        now = time.time() if now is None else now
        counts = {}
        with self._atomic('expire'):
            # The rule is the one fact of a request a text-free row keeps: copied before any text goes.
            self.db.execute("UPDATE episodes SET rule=json_extract(request,'$.experience.rule') "
                            'WHERE rule IS NULL AND request IS NOT NULL AND ' + _RULE_IS_TEXT)
            for kind, (table, age, rows, clear, _) in _KINDS.items():
                for state in UNJUDGED[kind]:  # one statement per prior state, so each count is exact
                    self._tally(counts, f'{kind}s_expired_{state}', self.db.execute(
                        f'UPDATE {table} SET state=?,expired_from=?,expired_at=?,{clear} WHERE {rows} AND state=? AND {age}<?',
                        (EXPIRED, state, now, state, now - EXPIRY[kind][state][0] * DAY)))
            for kind, (table, age, rows, clear, has_text) in _KINDS.items():
                for days, states in _text_groups(kind).items():
                    self._tally(counts, f'{kind}s_text_cleared', self.db.execute(
                        f'UPDATE {table} SET {clear} WHERE {rows} AND state IN ({_marks(states)}) AND {age}<? AND {has_text}',
                        (*states, now - days * DAY)))
                known = tuple(EXPIRY[kind])
                self._tally(counts, f'{kind}s_text_cleared_unknown_state', self.db.execute(
                    f'UPDATE {table} SET {clear} WHERE {rows} AND state NOT IN ({_marks(known)}) AND {age}<? AND {has_text}',
                    (*known, now - UNKNOWN_STATE[0] * DAY)))
            for kind, (table, age, rows, _, _) in _KINDS.items():
                for days, states in _row_groups(kind).items():
                    self._tally(counts, f'{kind}s_deleted', self._delete(
                        table, f'{rows} AND state IN ({_marks(states)}) AND {age}<?', (*states, now - days * DAY)))
                known = tuple(EXPIRY[kind])
                self._tally(counts, f'{kind}s_deleted_unknown_state', self._delete(
                    table, f'{rows} AND state NOT IN ({_marks(known)}) AND {age}<?', (*known, now - UNKNOWN_STATE[1] * DAY)))
            self._tally(counts, 'events_expired', self.db.execute(
                "DELETE FROM events WHERE kind!='correction' AND at<?", (now - EVENT_DAYS * DAY,)))
            for name, delta in self.prune(now).items():
                counts[name] = counts.get(name, 0) + delta
            for table in ('labels', 'advice', 'review_applications'):
                self._tally(counts, f'{table}_expired', self.db.execute(f'DELETE FROM {table} WHERE at<?', (now - ROW_DAYS * DAY,)))
        return counts

    def _delete(self, table, where, values):
        """DELETE FROM ``table`` WHERE ``where``; deleted episode keys leave the ledger in the caller's transaction."""
        if table == 'episodes':
            self.db.execute(f'DELETE FROM episode_keys WHERE key IN (SELECT key FROM episodes WHERE {where})', values)
        return self.db.execute(f'DELETE FROM {table} WHERE {where}', values)

    def expiry_state(self, now=None):
        """What expires when, from the retention table; a pure read.

        Per unjudged class (held, composed, pending, review_dialogue): count, oldest
        activity, next expiry and how many expire within NOTICE_DAYS. ``next_expiry``
        is the minimum over unjudged material only; ``next_text_clearing`` is separate.
        Tombstones by prior state, text-free rows, the cumulative counters, and from
        the ledger: ``episodes_deleted_uncounted``, its keys absent from `episodes`,
        and ``episodes_created_uncounted``, episode keys absent from it (tombstones
        and text-free rows are present). Both are None without the ledger.
        """
        return _expiry_state(self.db, time.time() if now is None else now)


# ------------------------------------------------------------------ read-only
class UnknownObserverSchema(ValueError):
    """The observer database carries a schema version newer than this runtime knows."""


def _known_columns():
    """Columns of every table this runtime's schema has, from an in-memory copy of it."""
    db = sqlite3.connect(':memory:')
    try:
        db.executescript(_SCHEMA)
        _migrate(db)
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {table: {row[1] for row in db.execute(f'PRAGMA table_info({table})')} for table in tables}
    finally:
        db.close()


class ObserverReader:
    """The observer database opened read-only: no DDL, no write, no directory or file created.

    ``present`` is False when there is no observer state; the read helpers then
    give empty counts. SQLite may still create its -wal and -shm sidecars beside a
    WAL database; the main file is never written. The helpers read 0.10.0 columns
    only, so version 0 is readable.
    """

    def __init__(self, path=None, *, strict=True):
        self.path, self.db, self.schema_version, self.unknown_columns, self._tables = path, None, None, {}, set()
        if path is None:
            return
        self.db = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)
        try:
            self.db.execute('PRAGMA query_only=ON')
            self.schema_version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if strict and self.schema_version > SCHEMA_VERSION:
                raise UnknownObserverSchema(f'Observer schema {self.schema_version} is newer than this runtime ({SCHEMA_VERSION})')
            self._tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            known = _known_columns()
            for table in sorted(self._tables & set(known)):
                unknown = {row[1] for row in self.db.execute(f'PRAGMA table_info({table})')} - known[table]
                if unknown:
                    self.unknown_columns[table] = sorted(unknown)
        except BaseException:
            self.db.close()
            raise

    @property
    def present(self):
        return self.db is not None

    def close(self):
        if self.db is not None:
            self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def episodes_older_than(self, days, now=None):
        """Episodes whose last activity is more than ``days`` before ``now``, counted by state."""
        if 'episodes' not in self._tables:
            return {}
        cutoff = (time.time() if now is None else now) - days * 86400
        return {row[0]: row[1] for row in
                self.db.execute('SELECT state,count(*) FROM episodes WHERE coalesce(last_at,updated)<? GROUP BY state ORDER BY state', (cutoff,))}

    def expiry_state(self, now=None):
        """ExperienceStore.expiry_state, read-only; None without observer state. A version-0 database
        has no tombstones and no ledger, so its uncounted episode values are None."""
        if not {'episodes', 'events', 'stats'} <= self._tables:
            return None
        return _expiry_state(self.db, time.time() if now is None else now)

    def corrections_older_than(self, days, now=None):
        """Correction events of any state taken more than ``days`` before ``now``."""
        if 'events' not in self._tables:
            return 0
        cutoff = (time.time() if now is None else now) - days * 86400
        return self.db.execute("SELECT count(*) FROM events WHERE kind='correction' AND at<?", (cutoff,)).fetchone()[0]

    def labelled_deliveries_beyond(self, days, cap, now=None):
        """Owner-labelled deliveries made more than ``days`` before ``now`` or outside the newest ``cap``
        deliveries of all rows: what a runtime that ranks every row against one cap deletes of them."""
        if 'deliveries' not in self._tables:
            return 0
        cutoff = (time.time() if now is None else now) - days * 86400
        return self.db.execute('SELECT count(*) FROM deliveries WHERE labels IS NOT NULL AND '
                               '(at<? OR id NOT IN (SELECT id FROM deliveries ORDER BY at DESC LIMIT ?))', (cutoff, cap)).fetchone()[0]


def open_read_only(home=None, *, strict=True):
    """The observer database of a runtime (data) home, ``home/observed/state.sqlite``, read-only.

    It never creates a directory or a file: missing state gives a reader that is
    not ``present``. Strict readers, which interpret rows, refuse a newer schema
    with UnknownObserverSchema; tolerant ones, such as the installer's rollback
    guard, read on and report ``schema_version`` and ``unknown_columns``.
    """
    directory = Path(home if home is not None else data_home()) / 'observed'
    if directory.is_symlink():
        raise PermissionError('Observer state must not be a symlink')
    if not directory.is_dir():
        return ObserverReader(strict=strict)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError('Observer state must be private to the OS owner')
    path = directory / 'state.sqlite'
    return ObserverReader(path if path.is_file() else None, strict=strict)


class TaskTerms:
    """How ordinary each query term is across the realm's past tasks.

    A word that appears in many task statements ("fix", "current", "determine")
    says little about the topic. The weight is the term's inverse task frequency
    scaled to (0, 1]; with too few tasks every weight is 1.
    """
    MIN_TASKS = 30
    FLOOR = 0.15

    def __init__(self, realm, store_factory=ExperienceStore):
        self.realm, self._factory, self._loaded = realm, store_factory, None

    def _load(self):
        if self._loaded is None:
            try:
                store = self._factory()
                try:
                    self._loaded = store.task_terms(self.realm)
                finally:
                    store.close()
            except (OSError, sqlite3.Error, PermissionError):
                self._loaded = (0, {})
        return self._loaded

    @property
    def active(self):
        return self._load()[0] >= self.MIN_TASKS

    def weight(self, stem):
        total, tasks = self._load()
        if total < self.MIN_TASKS:
            return 1.0
        value = math.log((total + 1) / (tasks.get(stem, 0) + 0.5)) / math.log(total + 1)
        return max(self.FLOOR, min(1.0, value))

    def observe(self, task, stems):
        try:
            store = self._factory()
            try:
                store.observe_task(self.realm, stems, task)
            finally:
                store.close()
        except (OSError, sqlite3.Error, PermissionError):
            pass
