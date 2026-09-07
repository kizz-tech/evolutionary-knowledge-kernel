"""Disposable per-role snapshot index. Canonical bytes always come from the store."""
from __future__ import annotations
from contextlib import closing
import hashlib
import json
import sqlite3
from pathlib import Path


def index_key(*, realm, grant, snapshot, policy, packs, query=''):
    return hashlib.sha256(json.dumps([realm,grant,snapshot,policy,packs,query],sort_keys=True).encode()).hexdigest()


class SQLiteIndex:
    def __init__(self, path):
        self.path=Path(path)

    def rebuild(self, records, *, key):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, title TEXT, body TEXT)')
            db.execute('DELETE FROM records')
            db.executemany('INSERT INTO records VALUES (?,?,?)',[(r['id'],r.get('title',''),r.get('body','')) for r in records])
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('snapshot_key',?)",(key,))
        self.path.chmod(0o600)

    def search(self, text, *, key, limit=50):
        if not self.path.is_file():
            raise ValueError('Rebuild index for the authorized snapshot first')
        with closing(sqlite3.connect(self.path)) as db, db:
            row=db.execute("SELECT value FROM metadata WHERE key='snapshot_key'").fetchone()
            if row is None or row[0] != key:
                raise ValueError('Index permission/snapshot key is stale')
            return [r[0] for r in db.execute('SELECT id FROM records WHERE instr(lower(title || char(10) || body),lower(?)) > 0 ORDER BY id LIMIT ?',(text,limit))]
