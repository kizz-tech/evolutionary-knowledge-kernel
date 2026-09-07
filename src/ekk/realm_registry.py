"""Owner-controlled locations and local OS identity adapter for governed realms.

This is local administration, not an identity provider for hostile processes with
access to this account's files. Remote deployments inject another trusted adapter.
Legacy project configuration is independent and is never rewritten here.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import fcntl
import os
import tempfile
import yaml
from .kernel import KernelError
from .integration import binding_for


def default_registry():
    return Path(os.environ.get('EKK_REALM_REGISTRY', '~/.config/ekk/realms.yaml')).expanduser().resolve()


class RealmRegistry:
    def __init__(self, path=None):
        self.path = Path(path).expanduser().resolve() if path else default_registry()

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.parent / '.realm-registry.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def load(self):
        try:
            return self._load()
        except (yaml.YAMLError, TypeError, AttributeError, KeyError) as exc:
            raise KernelError('Invalid realm registry') from exc

    def _load(self):
        if not self.path.exists(): return None
        st = self.path.stat()
        if st.st_uid != os.getuid() or st.st_mode & 0o022:
            raise KernelError('Realm registry must be owner-controlled and not group/world writable')
        cfg = yaml.safe_load(self.path.read_text())
        if not isinstance(cfg, dict) or cfg.get('schema') != 'ekk.realm-registry/1':
            raise KernelError('Unsupported realm registry')
        if not isinstance(cfg.get('realms'), dict) or not isinstance(cfg.get('projects'), list):
            raise KernelError('Invalid realm registry')
        if not isinstance(cfg.get('identity'),dict) or cfg['identity'].get('provider') != 'local-os' or not isinstance(cfg['identity'].get('uids'),dict):
            raise KernelError('This adapter requires local-os identity')
        seen = set()
        for key, item in cfg['realms'].items():
            if not isinstance(key,str) or not isinstance(item,dict) or not Path(item.get('location','')).is_absolute():
                raise KernelError('Realm requires stable ID and absolute location')
        for b in cfg['projects']:
            if not isinstance(b,dict) or b.get('realm_id') not in cfg['realms']:
                raise KernelError('Unknown realm in binding')
            if not Path(b.get('path','')).is_absolute() or b['path'] in seen:
                raise KernelError('Invalid or duplicate project binding')
            seen.add(b['path'])
            if not isinstance(b.get('scopes'),list) or not b['scopes'] or any(not isinstance(s,str) or not s for s in b['scopes']):
                raise KernelError('Binding requires explicit scopes')
            if b.get('retention') not in ('significant','read-only'):
                raise KernelError('Invalid retention')
        return cfg

    def _write(self, cfg):
        fd, name = tempfile.mkstemp(prefix='.realm-registry-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as out:
                yaml.safe_dump(cfg,out,sort_keys=False,allow_unicode=True)
                out.flush(); os.fsync(out.fileno())
            os.replace(name,self.path)
            directory=os.open(self.path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if os.path.exists(name):os.unlink(name)

    def initialize(self, principal):
        if not isinstance(principal,str) or not principal.strip():raise KernelError('Principal required')
        with self._lock():
            if self.path.exists():raise KernelError('Registry already exists')
            cfg={'schema':'ekk.realm-registry/1','identity':{'provider':'local-os','uids':{str(os.getuid()):principal}},'realms':{},'projects':[]}
            self._write(cfg)
        return cfg

    def principal(self, cfg):
        principal=cfg['identity'].get('uids',{}).get(str(os.getuid()))
        if not isinstance(principal,str) or not principal:raise KernelError('OS identity is not enrolled')
        return principal

    def register(self, root):
        from .realms import RealmStore
        store=RealmStore(Path(root).resolve())
        with self._lock():
            cfg=self.load()
            if cfg is None:raise KernelError('Initialize registry first')
            realm_id=store.realm_id
            prior=cfg['realms'].get(realm_id)
            location=str(Path(root).resolve())
            if prior and prior['location'] != location:
                raise KernelError('Realm already has a location; use relocate explicitly')
            cfg['realms'][realm_id]={'location':location}
            self._write(cfg)
        return {'realm_id':realm_id,'location':location}

    def relocate(self, realm_id, root):
        from .realms import RealmStore
        root=Path(root).resolve()
        if RealmStore(root).realm_id != realm_id:raise KernelError('Realm identity mismatch')
        with self._lock():
            cfg=self.load()
            if not cfg or realm_id not in cfg['realms']:raise KernelError('Unknown realm')
            cfg['realms'][realm_id]['location']=str(root)
            self._write(cfg)
        return {'realm_id':realm_id,'location':str(root)}

    def bind(self, cwd, realm_id, scopes, retention='significant'):
        path=Path(cwd).resolve()
        if not path.is_dir() or not scopes or any(not isinstance(s,str) or not s for s in scopes):
            raise KernelError('Existing project and scopes required')
        if retention not in ('significant','read-only'):raise KernelError('Invalid retention')
        with self._lock():
            cfg=self.load()
            if not cfg or realm_id not in cfg['realms']:raise KernelError('Register realm first')
            b={'path':str(path),'realm_id':realm_id,'scopes':sorted(set(scopes)),'retention':retention}
            previous=next((item for item in cfg['projects'] if item['path']==str(path)),None)
            if previous and previous != b:raise KernelError('Existing binding differs; explicit owner edit required')
            if not previous:cfg['projects'].append(b);self._write(cfg)
        return b

    def route(self, cwd):
        cfg=self.load()
        if not cfg:return None
        binding=binding_for(cfg,cwd)
        if not binding:return None
        from .realms import RealmStore
        store=RealmStore(cfg['realms'][binding['realm_id']]['location'])
        if store.realm_id != binding['realm_id']:raise KernelError('Registered realm identity mismatch')
        return store.session(self.principal(cfg)),binding

    def enter(self, cwd, task=''):
        route=self.route(cwd)
        if route is None:return None
        session,binding=route
        context=session.view(scopes=binding['scopes'],purpose=task).compile()
        return {'status':'ready','runtime':'governed/3','binding':binding,'context':context,
                'authority_note':'Local OS adapter; not isolation from other processes with the same filesystem access.'}
