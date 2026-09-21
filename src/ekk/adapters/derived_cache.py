"""Disposable, authenticated local parse cache, never authorization or state.

Only this trusted codec produces cache entries. Exact input bytes and the codec
implementation identify an entry. A missing/corrupt/foreign cache is a miss.
Canonical input, schema checks and current access remain with their owners.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat


class DerivedCache:
    MAX_BYTES = 96 * 1024 * 1024
    MAX_ENTRY = 2 * 1024 * 1024

    def __init__(self, directory, namespace):
        self.db = None
        self.secret = None
        self.namespace = namespace
        try:
            directory = Path(directory).absolute()
            if any(p.is_symlink() for p in (directory, *directory.parents)):
                return
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if directory.stat().st_uid != os.getuid() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
                return
            key = directory / 'key'
            try:
                fd = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(os.urandom(32))
                    stream.flush()
                    os.fsync(stream.fileno())
            if key.is_symlink() or key.stat().st_uid != os.getuid() or stat.S_IMODE(key.stat().st_mode) & 0o077:
                return
            self.secret = key.read_bytes()
            if len(self.secret) != 32:
                return
            path = directory / 'derived.sqlite'
            if any(Path(str(path) + suffix).is_symlink() for suffix in ('', '-wal', '-shm', '-journal')):
                return
            if path.exists() and (path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) & 0o077):
                return
            # Create private before SQLite opens it; WAL inherits this mode.
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            # Gateway calls can finish on a worker and be collected on the
            # transport thread. SQLite serializes statements; no transaction or
            # cursor escapes this cache, and callers retain the live object.
            self.db = sqlite3.connect(path, timeout=0.2, isolation_level=None, check_same_thread=False)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=NORMAL')
            self.db.execute('CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, raw BLOB, value BLOB, mac TEXT, used INTEGER)')
            size = self.db.execute('SELECT coalesce(sum(length(raw)+length(value)),0) FROM entries').fetchone()[0]
            if size > self.MAX_BYTES:
                self.db.execute('DELETE FROM entries WHERE key IN (SELECT key FROM entries ORDER BY used LIMIT (SELECT count(*)/2+1 FROM entries))')
            self.writes = 0
        except (OSError, sqlite3.Error):
            self.close()

    def _key(self, kind, raw):
        return hashlib.sha256(self.namespace.encode() + b'\0' + kind.encode() + b'\0' + raw).hexdigest()

    def _mac(self, key, raw, value):
        return hmac.new(self.secret, key.encode() + b'\0' + raw + b'\0' + value, hashlib.sha256).hexdigest()

    def get(self, kind, raw):
        if self.db is None:
            return None
        try:
            key = self._key(kind, raw)
            row = self.db.execute('SELECT raw,value,mac FROM entries WHERE key=?', (key,)).fetchone()
            if row and row[0] == raw and len(row[1]) <= self.MAX_ENTRY and hmac.compare_digest(row[2], self._mac(key, raw, row[1])):
                return json.loads(row[1])
        except (ValueError, TypeError, sqlite3.Error):
            pass
        return None

    def put(self, kind, raw, value):
        if self.db is None:
            return
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
            if len(raw) + len(encoded) > self.MAX_ENTRY:
                return
            key = self._key(kind, raw)
            import time
            self.db.execute('INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?)',
                            (key, raw, encoded, self._mac(key, raw, encoded), time.time_ns()))
            self.writes += 1
            if self.writes % 128 == 0:
                size = self.db.execute('SELECT coalesce(sum(length(raw)+length(value)),0) FROM entries').fetchone()[0]
                if size > self.MAX_BYTES:
                    self.db.execute('DELETE FROM entries WHERE key IN (SELECT key FROM entries ORDER BY used LIMIT 256)')
        except (ValueError, TypeError, OverflowError, sqlite3.Error):
            pass

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def __del__(self):
        self.close()
