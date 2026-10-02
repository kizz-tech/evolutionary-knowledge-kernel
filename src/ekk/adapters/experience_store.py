"""Private, bounded observer state: host events, episodes, deliveries and task terms.

One SQLite database per OS user under the runtime home. It is operational
state, never canonical knowledge: rows expire, texts are bounded and redacted
before they arrive, and nothing here grants access or acceptance. Canonical
records are written only through the realm's ordinary durable writer.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from ..homes import data_home

EVENT_DAYS = 30
CORRECTION_DAYS = 90
DELIVERY_DAYS = 60
MAX_DELIVERIES = 2000
MAX_SEEN_TASKS = 20000

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
CREATE TABLE IF NOT EXISTS labels(target TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS task_terms(realm TEXT NOT NULL, stem TEXT NOT NULL, tasks INTEGER NOT NULL, PRIMARY KEY(realm, stem));
CREATE TABLE IF NOT EXISTS task_seen(realm TEXT NOT NULL, digest TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(realm, digest));
CREATE TABLE IF NOT EXISTS advice(
  target TEXT NOT NULL, operation TEXT NOT NULL, model TEXT NOT NULL, label TEXT NOT NULL,
  probabilities TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(target, operation, model));
CREATE TABLE IF NOT EXISTS stats(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
'''


def _digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ExperienceStore:
    def __init__(self, directory=None):
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
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript(_SCHEMA)

    def close(self):
        self.db.close()

    # ------------------------------------------------------------------ events
    def add_event(self, *, kind, host, profile, session, turn, workspace, realm, at, text='', extra=None, state='new'):
        """Insert one observed event once; a replayed spool file changes nothing."""
        identity = _digest(kind, host, session, turn, workspace, round(at, 3), hashlib.sha256(text.encode()).hexdigest())
        inserted = self.db.execute(
            'INSERT OR IGNORE INTO events(id,kind,host,profile,session,turn,workspace,realm,at,text,extra,state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity, kind, host, profile, session, turn, workspace, realm, at, text,
             json.dumps(extra or {}, ensure_ascii=False), state)).rowcount
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
        current = self.episode(key) or {'key': key, 'covers': '[]'}
        row = {**current, **fields, 'updated': time.time()}
        columns = ('key', 'workspace', 'realm', 'host', 'session', 'first_at', 'last_at', 'state', 'title', 'request', 'covers', 'reason', 'updated')
        self.db.execute('INSERT OR REPLACE INTO episodes(' + ','.join(columns) + ') VALUES (' + ','.join('?' * len(columns)) + ')',
                        tuple(row.get(column) for column in columns))

    def episodes(self, state=None):
        rows = self.db.execute('SELECT * FROM episodes' + (' WHERE state=?' if state else '') + ' ORDER BY updated', (state,) if state else ())
        return [dict(row) for row in rows]

    # -------------------------------------------------------------- deliveries
    def note_delivery(self, *, workspace, realm, task, snapshot, items, baseline=()):
        """What entry showed for a task, and what plain lexical order would have shown.

        The basis of owner samples, of the comparison between the two orders and of
        the use signal.
        """
        at = time.time()
        identity = _digest(workspace, realm, task, snapshot, at)
        self.db.execute('INSERT INTO deliveries(id,at,workspace,realm,task,snapshot,items,baseline) VALUES (?,?,?,?,?,?,?,?)',
                        (identity, at, workspace, realm, task, snapshot, json.dumps(items, ensure_ascii=False),
                         json.dumps(list(baseline), ensure_ascii=False)))
        return identity

    def note_use(self, realm, record_id, *, within=86400):
        """A record read by ID shortly after an entry that listed it counts as used."""
        rows = self.db.execute('SELECT id,items,used FROM deliveries WHERE realm=? AND at>=?', (realm, time.time() - within)).fetchall()
        for row in rows:
            used = json.loads(row['used'])
            if record_id not in used and any(item.get('id') == record_id for item in json.loads(row['items'])):
                self.db.execute('UPDATE deliveries SET used=? WHERE id=?', (json.dumps(used + [record_id]), row['id']))

    def deliveries(self, *, since=0, workspace=None):
        query, values = 'SELECT * FROM deliveries WHERE at>=?', [since]
        if workspace:
            query += ' AND workspace=?'
            values.append(workspace)
        return [{**dict(row), 'items': json.loads(row['items']), 'baseline': json.loads(row['baseline']), 'used': json.loads(row['used']),
                 'labels': json.loads(row['labels']) if row['labels'] else None}
                for row in self.db.execute(query + ' ORDER BY at DESC', values)]

    def label_delivery(self, identity, labels):
        self.db.execute('UPDATE deliveries SET labels=? WHERE id=?', (json.dumps(labels), identity))

    def label(self, target, kind, value):
        self.db.execute('INSERT OR REPLACE INTO labels(target,kind,value,at) VALUES (?,?,?,?)', (target, kind, json.dumps(value), time.time()))

    def labels(self, kind=None):
        rows = self.db.execute('SELECT * FROM labels' + (' WHERE kind=?' if kind else ''), (kind,) if kind else ())
        return {row['target']: json.loads(row['value']) for row in rows}

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
        self.db.execute('INSERT OR REPLACE INTO advice(target,operation,model,label,probabilities,at) VALUES (?,?,?,?,?,?)',
                        (target, operation, model, label, json.dumps(probabilities), time.time()))

    def advice(self, operation=None):
        rows = self.db.execute('SELECT * FROM advice' + (' WHERE operation=?' if operation else ''), (operation,) if operation else ())
        return [{**dict(row), 'probabilities': json.loads(row['probabilities'])} for row in rows]

    # ------------------------------------------------------------ stats, expiry
    def count(self, name, amount=1):
        self.db.execute('INSERT INTO stats(name,value) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=value+?', (name, amount, amount))

    def stats(self):
        return {row['name']: row['value'] for row in self.db.execute('SELECT * FROM stats')}

    def expire(self, now=None):
        """Drop what has outlived its purpose; counts stay."""
        now = now or time.time()
        day = 86400
        expired = self.db.execute("DELETE FROM events WHERE (kind!='correction' AND at<?) OR at<?",
                                  (now - EVENT_DAYS * day, now - CORRECTION_DAYS * day)).rowcount
        self.db.execute('DELETE FROM deliveries WHERE at<? OR id NOT IN (SELECT id FROM deliveries ORDER BY at DESC LIMIT ?)',
                        (now - DELIVERY_DAYS * day, MAX_DELIVERIES))
        self.db.execute('DELETE FROM task_seen WHERE digest NOT IN (SELECT digest FROM task_seen ORDER BY at DESC LIMIT ?)', (MAX_SEEN_TASKS,))
        # No episode keeps report text past the event horizon, whatever state it is stuck in.
        self.db.execute('DELETE FROM episodes WHERE coalesce(last_at, updated)<?', (now - EVENT_DAYS * day,))
        self.db.execute('DELETE FROM labels WHERE at<?', (now - 365 * day,))
        self.db.execute('DELETE FROM advice WHERE at<?', (now - 365 * day,))
        if expired:
            self.count('events_expired', expired)


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
