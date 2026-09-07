"""Local role routing. Profiles select accessible stores; bindings cannot grant access."""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path
import yaml


def config_home():
    if os.environ.get('EKK_CONFIG_HOME'):
        return Path(os.environ['EKK_CONFIG_HOME']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/EKK/config'
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config')) / 'ekk'


def data_home():
    if os.environ.get('EKK_DATA_HOME'):
        return Path(os.environ['EKK_DATA_HOME']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/EKK/runtime'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share')) / 'ekk'


def cache_home():
    if os.environ.get('EKK_CACHE_HOME'):
        return Path(os.environ['EKK_CACHE_HOME']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Caches/EKK'
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache')) / 'ekk'


def trusted_principal():
    return 'local:uid:' + str(os.getuid())


def read_yaml(path):
    from .markdown import MarkdownCodec
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Control files must not traverse symlinks')
    return MarkdownCodec().load_yaml(path.read_bytes())


def published_manifest(root):
    from .git_store import GitStore
    from .markdown import MarkdownCodec
    # Registry identity comes from immutable published bytes, never a dirty file.
    if (root/'.git').is_dir():
        raw=GitStore(root).snapshot()['files']['.ekk/realm.yaml']
    else:
        from .contained_store import ContainedGitStore
        import subprocess, hashlib
        repository = root.parent
        branch = subprocess.run(['git','-C',str(repository),'symbolic-ref','HEAD'], capture_output=True,text=True)
        if branch.returncode or not (repository/'.git').is_dir():
            raise ValueError('Realm identity requires a published Git store')
        selected = branch.stdout.strip()
        committed = subprocess.run(['git','-C',str(repository),'show',selected+':'+root.name+'/.ekk/realm.yaml'],capture_output=True)
        if committed.returncode:
            raise ValueError('Realm identity is absent from the selected publication')
        identity = MarkdownCodec().load_yaml(committed.stdout)['id']
        runtime = data_home()/hashlib.sha256(identity.encode()).hexdigest()
        raw = ContainedGitStore(root,repository,selected,runtime).snapshot()['files']['.ekk/realm.yaml']
    if (root/'.ekk/realm.yaml').read_bytes()!=raw:raise ValueError('Working realm manifest differs from published identity')
    return MarkdownCodec().load_yaml(raw)

def binding(cwd):
    path = Path(cwd).expanduser().resolve()
    found = []
    for root in (path, *path.parents):
        candidate = root / '.ekk/workspace.yaml'
        if candidate.is_file():
            found.append((root, read_yaml(candidate)))
        if (root/'.git').exists():
            break
    if len(found) > 1:
        raise ValueError('Ambiguous nested workspace bindings; resolve explicitly')
    return found[0] if found else None


class LocalProfile:
    def __init__(self, name, *, directory=None):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
            raise ValueError('Invalid profile name')
        self.name = name
        self.path = Path(directory or config_home()/'profiles').expanduser().resolve()/(name+'.yaml')
        try:self.document = read_yaml(self.path)
        except FileNotFoundError as exc:raise ValueError('Role profile unavailable') from exc
        if self.document.get('schema') != 'ekk.profile/0.1':
            raise ValueError('Unknown profile schema')
        if self.document.get('uid') != os.getuid():
            raise ValueError('Profile belongs to another local OS principal')
        self.principal = trusted_principal()

    def resolve(self, alias):
        entry = self.document.get('realms', {}).get(alias)
        if not isinstance(entry, dict) or not entry.get('path') or not entry.get('id'):
            raise ValueError('Realm alias unavailable in active role')
        configured=Path(entry['path']).expanduser()
        if not configured.is_absolute():raise ValueError('Profile store paths must be absolute')
        root = configured.resolve()
        manifest = published_manifest(root)
        realm_id = manifest.get('id', manifest.get('realm_id'))
        if realm_id != entry['id']:
            raise ValueError('Realm identity differs from profile')
        return root, manifest

    def workspace(self, cwd):
        selected = binding(cwd)
        if selected is None:
            raise ValueError('No workspace binding')
        root, document = selected
        if document.get('schema') != 'ekk.workspace/0.1':
            raise ValueError('Unknown workspace schema')
        from ..model import validate_identifier
        validate_identifier(document.get('workspace_id'))
        expected_profile = document.get('profile')
        if expected_profile and expected_profile != self.name:
            raise ValueError('Workspace requires another role profile')
        contexts = document.get('bindings', [])
        if not isinstance(contexts, list) or not contexts:
            raise ValueError('Workspace has no permitted realm contexts')
        routes = []
        seen = set()
        for entry in contexts:
            if not isinstance(entry,dict):raise ValueError('Binding must be an object')
            alias = entry['realm_alias']
            if not isinstance(alias,str) or not alias:raise ValueError('Invalid realm alias')
            validate_identifier(entry.get('realm_id'))
            if alias in seen:
                raise ValueError('Ambiguous duplicate realm alias')
            seen.add(alias)
            location, manifest = self.resolve(alias)
            if entry.get('realm_id') != manifest['id']:
                raise ValueError('Workspace realm identity differs from registry')
            scopes = entry.get('contexts', [])
            if not isinstance(scopes, list) or not scopes or not all(isinstance(s,str) and s for s in scopes):
                raise ValueError('Explicit context IDs required')
            for scope in scopes:validate_identifier(scope)
            if len(scopes)!=len(set(scopes)):raise ValueError('Duplicate context IDs')
            routes.append({'alias':alias,'path':location,'manifest':manifest,'scopes':scopes})
        return root, document, routes
