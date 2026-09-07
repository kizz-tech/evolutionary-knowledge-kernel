"""Read exact starter packs; deterministic directory artifact pins, no execution."""
from pathlib import Path
import json
from .markdown import MarkdownCodec
from ..model import digest

def artifact_digest(files):
    return digest(json.dumps({p:digest(raw) for p,raw in files.items()},sort_keys=True,separators=(',',':')).encode())

class PackDirectory:
    def __init__(self, root):self.root=Path(root).resolve()
    def __call__(self, pack_id, version):
        name=pack_id.removeprefix('ekk/')
        if not name or '/' in name or '\\' in name or name in ('.','..'):raise ValueError('Invalid pack ID')
        root=self.root/name
        if root.is_symlink():raise ValueError('Pack symlinks are not supported')
        files={}
        for path in sorted(root.rglob('*')):
            if path.is_symlink():raise ValueError('Pack symlinks are not supported')
            if path.is_file():files[path.relative_to(root).as_posix()]=path.read_bytes()
        data=MarkdownCodec().load_yaml(files['pack.yaml'])
        if data.get('id')!=pack_id or data.get('version')!=version:raise ValueError('Pack version mismatch')
        if data.get('installation_executes_code') is not False:raise ValueError('Unsupported pack installation behavior')
        return files
    def pin(self, pack_id):
        name=pack_id.removeprefix('ekk/')
        raw=(self.root/name/'pack.yaml').read_bytes();m=MarkdownCodec().load_yaml(raw)
        files=self(m['id'],m['version'])
        return {'id':m['id'],'version':m['version'],'origin':'pack:'+m['id'],'sha256':artifact_digest(files)}
