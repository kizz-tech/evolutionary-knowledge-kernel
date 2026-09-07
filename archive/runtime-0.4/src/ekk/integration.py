"""Explicit project routing for the agent's global EKK entry point.

Bindings are owner-controlled local configuration, not instructions from sources.
Unknown projects never inherit another project's scope or retention authority.
"""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import os
import subprocess
import tempfile
import uuid
import yaml

from .kernel import Kernel, KernelError


def config_path():
    return Path(os.environ.get('EKK_CONFIG', '~/.config/ekk/config.yaml')).expanduser().absolute()


def _absolute(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise KernelError('Integration paths must be absolute')
    return Path(value).resolve()


def load_config():
    p = config_path()
    if not p.exists():
        return None
    try:
        cfg = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise KernelError('Invalid EKK integration configuration') from exc
    if not isinstance(cfg, dict) or cfg.get('schema') != 'ekk.integration/1':
        raise KernelError('Unsupported EKK integration schema')
    _absolute(cfg.get('root'))
    bindings = cfg.get('projects')
    if not isinstance(bindings, list):
        raise KernelError('Project bindings must be a list')
    paths = set()
    for b in bindings:
        if not isinstance(b, dict):
            raise KernelError('Invalid project binding')
        path = str(_absolute(b.get('path')))
        if path in paths:
            raise KernelError('Duplicate project binding')
        paths.add(path)
        if not isinstance(b.get('scopes'), list) or not b['scopes'] or any(not isinstance(s,str) or not s.strip() for s in b['scopes']):
            raise KernelError('Explicit project scopes required')
        if b.get('audience') != 'self' or b.get('retention') not in ('significant', 'read-only'):
            raise KernelError('This private-root integration supports self audience only')
    return cfg


def global_root():
    cfg = load_config()
    return Path(cfg['root']).absolute() if cfg else None


def git_root(cwd):
    cwd = Path(cwd).expanduser().resolve()
    if not cwd.is_dir():
        raise KernelError('Project directory does not exist')
    # Do not inspect remotes, repository content, credentials or other projects.
    proc = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                          capture_output=True, text=True, timeout=10)
    return Path(proc.stdout.strip()).resolve() if proc.returncode == 0 else None


def project_path(cwd):
    return git_root(cwd) or Path(cwd).expanduser().resolve()


def binding_for(cfg, cwd):
    cwd = Path(cwd).expanduser().resolve()
    matches = [b for b in cfg['projects'] if cwd.is_relative_to(_absolute(b['path']))]
    # An independently versioned nested repository is a different project unless bound.
    discovered = git_root(cwd)
    matches = [b for b in matches if not (discovered is not None and discovered.is_relative_to(_absolute(b['path'])) and discovered != _absolute(b['path']))]
    if matches:
        return max(matches, key=lambda b: len(Path(b['path']).parts))
    return None


@contextmanager
def _config_lock():
    p = config_path()
    if not p.parent.is_dir():
        raise KernelError('Install EKK integration configuration first')
    with open(p.parent / '.projects.lock', 'a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise KernelError('Project registry is busy; retry after writer finishes') from exc
        yield


def bind_project(cwd, scopes=None, audience='self', retention='significant'):
    if audience != 'self' or retention not in ('significant', 'read-only'):
        raise KernelError('Use a separately authorized root for another audience')
    path = project_path(cwd)
    with _config_lock():
        cfg = load_config()
        if cfg is None:
            raise KernelError('Global EKK integration is not installed')
        existing = next((b for b in cfg['projects'] if _absolute(b['path']) == path), None)
        if existing:
            if scopes and sorted(set(scopes)) != sorted(set(existing['scopes'])) or existing['audience'] != audience or existing['retention'] != retention:
                raise KernelError('Existing binding differs; review owner configuration explicitly')
            return {'status': 'existing', 'binding': existing}
        scopes = scopes or ['project:' + uuid.uuid4().hex]
        if any(not isinstance(s,str) or not s.strip() for s in scopes):
            raise KernelError('Nonempty scopes required')
        binding = dict(path=str(path), scopes=sorted(set(scopes)), audience=audience, retention=retention)
        cfg['projects'].append(binding)
        p = config_path()
        fd, temporary = tempfile.mkstemp(prefix='.ekk-', dir=p.parent)
        try:
            with os.fdopen(fd, 'w') as out:
                yaml.safe_dump(cfg, out, sort_keys=False, allow_unicode=True)
                out.flush(); os.fsync(out.fileno())
            os.replace(temporary, p)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return {'status': 'bound', 'binding': binding}


def enter_project(cwd, task='', root=None):
    cfg = load_config()
    if cfg is None:
        raise KernelError('Global EKK integration is not installed')
    chosen = Path(cfg['root']).absolute()
    if root is not None and Path(root).resolve() != chosen:
        raise KernelError('Project routing root differs from selected root; use explicit scoped commands')
    binding = binding_for(cfg, cwd)
    if not binding:
        return {'status': 'unbound', 'project_path': str(project_path(cwd)),
                'context': None, 'retention': 'none',
                'next': 'Agent: establish project owner/audience, then project-bind for authorized self/private knowledge; continue task without retention if unclear.'}
    kernel = Kernel(chosen)
    return {'status': 'ready', 'root': str(chosen), 'binding': binding,
            'context': kernel.compile(binding['scopes'], task=task),
            'reconsideration': kernel.evolve(binding['scopes']),
            'authority_note': 'Binding selects applicability and retention intent; not filesystem isolation or authority for external action.'}
