"""Explicit owner-selected, read-only text folders. No canonical import or writes."""
import hashlib
import json
import os
from pathlib import Path
import re
from .operational_store import private_directory, canonical
from .git_store import _atomic
from .discovery_index import DiscoveryIndex
from ..application.discovery import terms, rank


class AuthoredSources:
    SUFFIXES={'.md','.txt','.rst','.org'}
    def __init__(self, directory):
        self.directory=private_directory(directory)
        self.config=self.directory/'sources.json'
        if self.config.is_symlink():raise PermissionError('Invalid source registry')
        self.index=DiscoveryIndex(self.directory/'fragments')

    def entries(self):
        return json.loads(self.config.read_text()) if self.config.exists() else {}

    def configure(self, alias, root, scopes):
        if not isinstance(alias,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}',alias):raise ValueError('Simple source alias required')
        path=Path(root).expanduser().absolute()
        if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_dir():raise ValueError('Existing non-symlink author folder required')
        from .file_lock import acquire_lock
        fd=os.open(self.directory/'registry.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a+b') as lock:
            acquire_lock(lock,kind='source_registry')
            entries=self.entries()
            selected={'root':str(path),'scopes':sorted(scopes),'mode':'read_only'}
            if alias in entries and entries[alias]!=selected:raise ValueError('Source alias already bound; remove it explicitly before rebinding')
            entries[alias]=selected
            _atomic(self.config,canonical(entries).encode())
        return {'alias':alias,**selected,'imported_records':0}

    def remove(self, alias, scopes):
        from .file_lock import acquire_lock
        fd=os.open(self.directory/'registry.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a+b') as lock:
            acquire_lock(lock,kind='source_registry')
            entries=self.entries();item=entries[alias]
            if not set(item['scopes'])<=set(scopes):raise PermissionError('Source outside selected scopes')
            del entries[alias];_atomic(self.config,canonical(entries).encode())
        return {'removed':alias,'author_files_changed':0}

    def _read(self, root, relative):
        root=Path(root);path=root/relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts:raise ValueError('Relative author path required')
        if any(p.is_symlink() for p in (path,*path.parents)):raise PermissionError('Author paths must not traverse symlinks')
        if not path.is_relative_to(root) or path.suffix.lower() not in self.SUFFIXES:raise ValueError('Unsupported author source')
        # Bind every directory component while opening it. A preliminary
        # symlink check alone races an author/editor replacing a directory.
        from .repository_evidence import read_configured_bytes
        return read_configured_bytes(root,relative,max_bytes=1048576)

    def search(self, scopes, query='', *, limit=10):
        if not isinstance(query,str) or len(query)>2000 or type(limit) is not int or not 1<=limit<=100:raise ValueError('Bounded author search required')
        results=[];omitted=0;scanned=0;total_bytes=0
        for alias,item in sorted(self.entries().items()):
            if not set(item['scopes'])<=set(scopes):continue
            root=Path(item['root'])
            if not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)):
                omitted+=1;continue
            for parent,dirs,files in os.walk(root,followlinks=False):
                dirs[:]=sorted(d for d in dirs if not d.startswith('.') and d not in {'node_modules','__pycache__'} and not (Path(parent)/d).is_symlink())
                for name in sorted(files):
                    if name.startswith('.') or Path(name).suffix.lower() not in self.SUFFIXES:continue
                    if scanned>=10000 or total_bytes>=32*1048576:omitted+=1;continue
                    relative=str((Path(parent)/name).relative_to(root))
                    try:
                        raw=self._read(root,relative);scanned+=1;total_bytes+=len(raw)
                        body=self.index.text(raw)
                    except (ValueError,OSError,UnicodeError):omitted+=1;continue
                    matched=rank(terms(query),[(relative,body)],name,[],mode='ranked')
                    if matched:
                        matched['fragment']['section']='author_file'
                        results.append({'reference':{'schema':'ekk.authored-reference/0.1','source':alias,'path':relative,
                                        'sha256':hashlib.sha256(raw).hexdigest()},'title':name,**matched})
        results.sort(key=lambda row:(-row['score'],row['reference']['source'],row['reference']['path']))
        return {'schema':'ekk.authored-search/0.1','results':results[:limit],'incomplete':bool(omitted or len(results)>limit),
                'omitted_files':omitted,'authority':'Independent author text; no adoption or execution grant. Current bytes are checked on fetch.'}

    def fetch(self, scopes, reference, *, offset=0, limit=8000):
        if set(reference)!={'schema','source','path','sha256'} or reference['schema']!='ekk.authored-reference/0.1':raise ValueError('Exact author reference required')
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=65536:raise ValueError('Bounded character range required')
        item=self.entries()[reference['source']]
        if not set(item['scopes'])<=set(scopes):raise PermissionError('Source outside selected scopes')
        raw=self._read(item['root'],reference['path'])
        if hashlib.sha256(raw).hexdigest()!=reference['sha256']:
            from ..model import Conflict
            raise Conflict('Author edited the source; search again to select its current version')
        text=raw.decode('utf-8')
        return {'reference':reference,'text':text[offset:offset+limit],'offset':offset,'unit':'unicode_characters',
                'incomplete':offset+limit<len(text),'next_offset':offset+limit if offset+limit<len(text) else None,
                'author_files_changed':0}
