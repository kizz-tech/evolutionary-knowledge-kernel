"""Private durable local operations; canonical records remain in their realm."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def private_directory(path):
    path=Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise PermissionError('Private state must not traverse symlinks')
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    info=path.stat()
    if info.st_uid!=os.getuid() or info.st_mode & 0o077:raise PermissionError('Private state requires an owner-only directory')
    return path


class OperationalStore:
    def __init__(self, directory, *, realm, principal):
        self.directory=private_directory(directory)
        self.realm,self.principal=realm,principal
        self.path=self.directory/'operations.sqlite'
        for suffix in ('','-wal','-shm','-journal'):
            path=Path(str(self.path)+suffix)
            if path.is_symlink():raise PermissionError('Invalid operational database')
            if path.exists():
                st=path.stat()
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode & 0o077:
                    raise PermissionError('Operational database must be private')
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
        self.db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), realm TEXT, principal TEXT);
          CREATE TABLE IF NOT EXISTS outbox (key TEXT PRIMARY KEY, request TEXT NOT NULL, scopes TEXT NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
            receipt TEXT, error TEXT, updated REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, scopes TEXT NOT NULL,
            value TEXT NOT NULL, updated REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS mutations (key TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL);
        ''')
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO identity VALUES (1,?,?)',(realm,principal))
            identity=self.db.execute('SELECT realm,principal FROM identity').fetchone()
            if tuple(identity)!=(realm,principal):raise PermissionError('Operational owner mismatch')

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def close(self):self.db.close()

    def enqueue(self, key, request, scopes):
        if not isinstance(key,str) or not 1<=len(key)<=500:raise ValueError('Bounded logical key required')
        raw=canonical(request)
        if len(raw.encode())>16*1048576:raise ValueError('Outbox request exceeds 16 MiB')
        scopes=sorted(set(scopes))
        with self.transaction():
            row=self.db.execute('SELECT * FROM outbox WHERE key=?',(key,)).fetchone()
            if row and (row['request']!=raw or json.loads(row['scopes'])!=scopes):
                from ..model import IdempotencyConflict
                raise IdempotencyConflict('Logical key already names another request')
            if not row:
                self.db.execute('INSERT INTO outbox(key,request,scopes,state,updated) VALUES (?,?,?,?,?)',
                                (key,raw,canonical(scopes),'local_pending',time.time()))
        return self.status(scopes,key=key)

    def status(self, scopes, *, key=None):
        rows=self.db.execute('SELECT * FROM outbox '+('WHERE key=? ' if key else '')+'ORDER BY updated DESC',
                             (key,) if key else ()).fetchall()
        result=[]
        for row in rows:
            if not set(json.loads(row['scopes']))<=set(scopes):continue
            result.append({'key':row['key'],'state':row['state'],'attempts':row['attempts'],
                           'next_attempt':row['next_attempt'], 'receipt':json.loads(row['receipt']) if row['receipt'] else None,
                           'error':json.loads(row['error']) if row['error'] else None})
        if key and not result:raise KeyError('Operation unavailable in selected scopes')
        return {'schema':'ekk.outbox/0.1','realm':self.realm,'operations':result,
                'authority':'Local pending is durable host storage, not canonical publication or acceptance.'}

    def drain(self, scopes, publish, *, limit=10):
        """Single publisher. A lost response replays the same frozen logical key."""
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('Bounded drain limit required')
        from .file_lock import acquire_lock
        from .command_line import error_code
        fd=os.open(self.directory/'worker.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a+b') as lock:
            acquire_lock(lock,kind='outbox_worker')
            # Holding the process lock proves no live worker owns these claims.
            self.db.execute("UPDATE outbox SET state='local_pending' WHERE state='publishing'")
            rows=self.db.execute("SELECT * FROM outbox WHERE state IN ('local_pending','retry_pending','published_verification_pending') AND next_attempt<=? ORDER BY updated LIMIT ?",(time.time(),limit)).fetchall()
            for row in rows:
                if not set(json.loads(row['scopes']))<=set(scopes):continue
                self.db.execute("UPDATE outbox SET state='publishing',attempts=attempts+1,updated=? WHERE key=?",(time.time(),row['key']))
                try:
                    receipt=publish(json.loads(row['request']),row['key'])
                    state=receipt.get('retention',{}).get('state','published_verification_pending')
                    if state not in {'read_back','read_back_and_discoverable','published_verification_pending'}:
                        raise ValueError('Publisher did not return a retention receipt')
                    self.db.execute('UPDATE outbox SET state=?,receipt=?,error=NULL,next_attempt=?,updated=? WHERE key=?',
                        (state,canonical(receipt),time.time()+min(300,2**min(row['attempts']+1,8)),time.time(),row['key']))
                except (ValueError,OSError,KeyError,TypeError) as exc:
                    code=error_code(exc)
                    retryable=code in {'lock_busy','source_unavailable'} and row['attempts']<2
                    state='retry_pending' if retryable else 'needs_attention'
                    error={'code':code,'message':str(exc),'outcome':'unconfirmed; reconcile by replaying this key'}
                    self.db.execute('UPDATE outbox SET state=?,error=?,next_attempt=?,updated=? WHERE key=?',
                        (state,canonical(error),time.time()+min(300,2**min(row['attempts']+1,8)),time.time(),row['key']))
        return self.status(scopes)

    def retry(self, scopes, key):
        self.status(scopes,key=key)
        self.db.execute("UPDATE outbox SET state='local_pending',next_attempt=0 WHERE key=? AND state IN ('needs_attention','retry_pending','published_verification_pending')",(key,))
        return self.status(scopes,key=key)

    def task(self, scopes, operation, request):
        """Small local commitments. Referenced external objects have no local status."""
        if operation in {'list','show'}:
            rows=self.db.execute('SELECT * FROM tasks ORDER BY updated DESC').fetchall()
            values=[{**json.loads(r['value']),'id':r['id'],'revision':r['revision']} for r in rows
                    if set(json.loads(r['scopes']))<=set(scopes) and (operation=='list' or r['id']==request['id'])]
            if operation=='show' and not values:raise KeyError('Task unavailable')
            return {'schema':'ekk.tasks/0.1','realm':self.realm,'tasks':values}
        allowed={'create','update','wait','register-wait','external-attempt','external-outcome'}
        if operation not in allowed:raise ValueError('Unknown task operation')
        key=request.get('key')
        if not isinstance(key,str) or not key or len(key)>500:raise ValueError('Task mutation requires a logical key')
        fingerprint=canonical([operation,request,sorted(scopes)])
        with self.transaction():
            old=self.db.execute('SELECT * FROM mutations WHERE key=?',(key,)).fetchone()
            if old:
                if old['request']!=fingerprint:raise ValueError('Task key reused with different input')
                return json.loads(old['result'])
            task_id=str(uuid.uuid4()) if operation=='create' else request['id']
            if operation=='create':
                value={'title':request.get('title'),'status':'open','external':request.get('external'),
                       'work':request.get('work'),'wait':None,'external_action':None};revision=0
            else:
                row=self.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
                if not row or not set(json.loads(row['scopes']))<=set(scopes):raise PermissionError('Task unavailable')
                revision=row['revision'];value=json.loads(row['value'])
                scopes=json.loads(row['scopes'])
                if type(request.get('revision')) is not int or request['revision']!=revision:
                    from ..model import Conflict
                    raise Conflict('Task changed; read its current revision')
                if operation=='update':
                    if set(request)-{'id','revision','key','title','status'}:raise ValueError('Unsupported task update')
                    value.update({k:request[k] for k in ('title','status') if k in request})
                elif operation=='wait':
                    from datetime import datetime
                    when=request.get('until')
                    if when and datetime.fromisoformat(when.replace('Z','+00:00')).tzinfo is None:raise ValueError('Waiting date needs timezone')
                    condition=request.get('condition','')
                    if not isinstance(condition,str) or len(condition)>4000 or not (condition or when):raise ValueError('Waiting condition or date required')
                    value['wait']={'until':when,'condition':condition,'registration':'not_registered',
                                   'host_receipt':None};value['status']='waiting'
                elif operation=='register-wait':
                    receipt=request.get('host_receipt')
                    if not value.get('wait') or not isinstance(receipt,dict) or set(receipt)!={'host','automation_id','receipt'}:
                        raise ValueError('An actual host automation receipt and waiting task are required')
                    if receipt['host']!='codex' or not all(isinstance(v,str) and 0<len(v)<=16000 for v in receipt.values()):raise ValueError('Invalid host receipt')
                    value['wait'].update(registration='receipt_recorded',host_receipt=receipt)
                elif operation=='external-attempt':
                    if value.get('external_action',{} ) and value['external_action'].get('state')=='unknown':
                        raise ValueError('Reconcile the previous external outcome before a new attempt')
                    operation_key=request.get('operation_key')
                    if not isinstance(operation_key,str) or not operation_key or len(operation_key)>500:raise ValueError('External logical key required')
                    value['external_action']={'key':operation_key,'state':'unknown','evidence':None}
                else:
                    action=value.get('external_action')
                    if not action or action['key']!=request.get('operation_key'):raise ValueError('Exact external logical key required')
                    if request.get('outcome') not in {'confirmed','not_performed','unknown'}:raise ValueError('Unknown external outcome')
                    evidence=request.get('evidence')
                    if not isinstance(evidence,str) or not evidence or len(evidence)>12000:raise ValueError('Reconciliation evidence required')
                    action.update(state=request['outcome'],evidence=evidence)
            if not isinstance(value['title'],str) or not 0<len(value['title'])<=1000:raise ValueError('Bounded task title required')
            if value['status'] not in {'open','waiting','completed','cancelled'}:raise ValueError('Unknown task status')
            if value.get('external'):
                external=value['external']
                if not isinstance(external,dict) or set(external)!={'owner','locator'} or not all(isinstance(v,str) and 0<len(v)<=2000 for v in external.values()):raise ValueError('External owner and locator required')
            if value.get('work'):
                from ..application.workspace import exact_reference
                exact_reference(value['work'])
            result={'schema':'ekk.task/0.1','id':task_id,'revision':revision+1,**value,
                    'status_meaning':'local follow-up only; query the external owner for external object status'}
            self.db.execute('INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?)',(task_id,revision+1,canonical(sorted(scopes)),canonical(value),time.time()))
            self.db.execute('INSERT INTO mutations VALUES (?,?,?)',(key,fingerprint,canonical(result)))
            return result

    def backup(self, destination):
        destination=Path(destination)
        if any(p.is_symlink() for p in (destination,*destination.parents)) or destination.exists():raise ValueError('Choose a new non-symlink backup path')
        fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        target=sqlite3.connect(destination)
        try:self.db.backup(target)
        finally:target.close()
        return {'schema':'ekk.operational-backup/0.1','realm':self.realm,'path':str(destination),
                'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                'scope':'local outbox, local tasks and reconciliation; not canonical knowledge or host schedules'}

    @classmethod
    def restore(cls, archive, destination, *, expected_sha256, realm, principal):
        archive=Path(archive).expanduser().absolute();destination=Path(destination).expanduser().absolute()
        if any(p.is_symlink() for p in (archive,*archive.parents,destination,*destination.parents)) or destination.exists():raise ValueError('Restore needs an ordinary archive and a new private destination')
        if archive.stat().st_size>64*1048576 or hashlib.sha256(archive.read_bytes()).hexdigest()!=expected_sha256:raise ValueError('Operational archive digest or size mismatch')
        source=sqlite3.connect(archive.as_uri()+'?mode=ro',uri=True)
        try:
            if source.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('Operational archive is corrupt')
            if source.execute('SELECT realm,principal FROM identity').fetchall()!=[(realm,principal)]:raise PermissionError('Operational archive owner mismatch')
            # Copy selected data, never schema, triggers or views from the archive.
            rows={table:source.execute('SELECT * FROM '+table).fetchmany(100001) for table in ('outbox','tasks','mutations')}
            if any(len(value)>100000 for value in rows.values()):raise ValueError('Operational archive exceeds row bound')
        finally:source.close()
        restored=cls(destination,realm=realm,principal=principal)
        try:
            with restored.transaction():
                for table,values in rows.items():
                    if values:restored.db.executemany('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in values[0])+')',values)
                restored.db.execute("UPDATE outbox SET state='local_pending' WHERE state='publishing'")
        finally:restored.close()
        return {'restored':str(destination),'realm':realm,'activated':False,'host_schedules_restored':False,
                'next':'Inspect the restored queue using --state-dir; draining rechecks current routing and rights.'}
