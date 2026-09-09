"""Trusted-local use cases; source documents never confer execution authority."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import json
import re
from pathlib import PurePosixPath
from ekk.model import Conflict, validate_envelope, validate_reference, digest, new_id

CONTROL = ('.ekk/realm.yaml', '.ekk/governance.yaml', '.ekk/packs.lock.yaml')
KINDS = {'context','note','source','observation','claim','question','decision','policy','action','outcome'}
CONTEXT_SOURCE_SCAN_BYTES = 8 * 1048576

class RealmService:
    def __init__(self, store, principal, clock=None, *, codec, pack_loader=None, allowed_scopes=None):
        if not isinstance(principal, str) or not principal:
            raise ValueError('trusted principal required')
        self.store, self.principal, self.clock, self.codec = store, principal, clock, codec
        self.pack_loader = pack_loader
        self.allowed_scopes=None if allowed_scopes is None else frozenset(allowed_scopes)

    def _now(self):
        value = self.clock.now() if hasattr(self.clock, 'now') else self.clock() if self.clock else datetime.now(timezone.utc)
        return value.isoformat() if isinstance(value, datetime) else value

    @staticmethod
    def _time(value):
        moment=datetime.fromisoformat(value.replace('Z','+00:00'))
        if moment.tzinfo is None: raise ValueError('timezone required')
        return moment

    def _meta(self, kind, title, scope, **extra):
        return dict(schema='ekk.record/0.1', id=new_id(), kind=kind, title=title, scope=scope, revision=1, created_at=self._now(), created_by=self.principal, **extra)

    def init(self, title, context_title='General', *, realm_id=None, owner=None, context_id=None, default_visibility='private', packs=None):
        context = self._meta('context', context_title, ['general'], context={'purpose': context_title, 'concepts': [], 'relations': [], 'basis': []})
        context['id'] = context_id or context['id']
        context['scope'] = [context['id']]
        validate_envelope(context)
        if owner is not None and owner != self.principal: raise PermissionError('init owner must be trusted current principal')
        realm = {'schema':'ekk.realm/0.1','id':realm_id or new_id(),'name':title,'owner':self.principal,'default_classification':default_visibility,'storage':{'mode':'git-files','record_roots':['contexts','records'],'source_root':'sources','receipts_root':'governance/receipts'},'required_semantics':[], 'default_context':context['id']}
        governance = {'schema':'ekk.governance/0.1','mode':'trusted-single-owner','bootstrap_owner':self.principal,'default_effect':'deny','trusted_acceptors':[self.principal],'version':1,'grants':[{'principal':self.principal,'actions':['read','write','accept'],'scopes':['*']}], 'export_grants':[]}
        files={CONTROL[0]:self.codec.dump_yaml(realm),CONTROL[1]:self.codec.dump_yaml(governance),CONTROL[2]:self.codec.dump_yaml({'schema':'ekk.packs-lock/0.1','packages':packs or []}), f"contexts/{context['id']}.md":self.codec.encode(context), 'README.md':('# '+title+'\n').encode(), '.gitignore':b'views/\n'}
        self._validate({'revision':None,'files':files})
        return self.store.initialize(files)

    def _load(self, snapshot, *, historical=False):
        files = snapshot['files']
        allow_aliases=historical and snapshot['revision'] is not None and snapshot['revision']!=self.store.history()[0]
        configs = [self.codec.load_yaml(files[p],allow_aliases=allow_aliases) for p in CONTROL]
        self.codec.validate_schema('realm',configs[0])
        self._realm_id=configs[0]['id']
        roots=self._roots(configs[0])
        records = {}
        for path, raw in sorted(files.items()):
            if any(path.startswith(root+'/') for root in roots['record_roots']) and path.endswith('.md'):
                record = self.codec.decode(raw,allow_aliases=allow_aliases)
                self.codec.validate_schema('record',record['metadata'])
                m = validate_envelope(record['metadata'])
                if m['id'] in records: raise ValueError('duplicate record ID: '+m['id'])
                records[m['id']] = {**record,'metadata':m,'path':path,'digest':digest(raw),'snapshot_revision':snapshot['revision']}
        return (*configs, records)

    def _grants(self, governance):
        if 'grants' in governance:return governance['grants']
        if governance.get('mode')=='trusted-single-owner' and governance.get('bootstrap_owner'):
            owner=governance['bootstrap_owner']
            return [{'principal':owner,'actions':['read','write']+(['accept'] if owner in governance.get('trusted_acceptors',[]) else []),'scopes':['*']}]
        return []

    def _authorized(self, governance, action, scopes):
        if self.allowed_scopes is not None and not set(scopes)<=self.allowed_scopes:raise PermissionError('operation outside workspace binding scopes')
        permitted = set()
        found = False
        for grant in self._grants(governance):
            if grant.get('principal') == self.principal and action in grant.get('actions', []):
                found = True
                permitted.update(grant.get('scopes', []))
        if not found or ('*' not in permitted and not set(scopes) <= permitted):
            raise PermissionError(f'{action} not granted for requested scopes')

    @staticmethod
    def _roots(realm):
        storage=realm.get('storage',{})
        if storage.get('mode','git-files')!='git-files': raise ValueError('unsupported storage mode')
        roots=storage.get('record_roots',[])
        if not roots:raise ValueError('record roots required')
        for root in list(roots)+[storage.get('source_root'),storage.get('receipts_root')]:
            if not isinstance(root,str) or not root or PurePosixPath(root).is_absolute() or '..' in PurePosixPath(root).parts or str(PurePosixPath(root))!=root or root.startswith(('.git','.ekk')):raise ValueError('unsafe storage root')
        return storage

    @staticmethod
    def _hash(value):
        return value.removeprefix('sha256:') if isinstance(value,str) else value

    def _reference(self, ref, records):
        validate_reference(ref)
        item = {'id':ref} if isinstance(ref,str) else {**ref,'id':ref.get('id',ref.get('target'))}
        def matches(target):
            return target and (not item.get('digest') or self._hash(item['digest']) == target['digest']) and (not item.get('revision') or item['revision'] == target['metadata']['revision'])
        if item.get('realm') and item['realm']!=self._realm_id:raise ValueError('external reference unverified; local resolution forbidden')
        target=records.get(item['id'])
        if matches(target):return target
        history=self.store.history()
        as_of=next(iter(records.values())).get('snapshot_revision') if records else None
        if as_of:
            history=history[history.index(as_of):] if as_of in history else []
        if item.get('snapshot') and item['snapshot'] not in history:raise ValueError('reference snapshot is outside the historical horizon')
        revisions=[item['snapshot']] if item.get('snapshot') else history if item.get('digest') or item.get('revision') else []
        for revision in revisions:
            historic=self._load(self.store.snapshot(revision),historical=True)[-1]
            target=historic.get(item['id'])
            if matches(target):return target
        raise ValueError('unresolved reference: '+item['id'])

    def _relation_ref(self, relation):
        ref={'id':relation['target']}
        ref.update({k:relation[k] for k in ('revision','digest','snapshot','realm','selector') if k in relation})
        return ref

    def _links(self, m, field):
        names={'basis':('derived_from','depends_on'),'supersedes':('supersedes',),'conflicts':('contradicts',),'depends_on':('depends_on',)}
        return [ref for ref in m.get(field,[]) if not isinstance(ref,dict) or not ref.get('realm') or ref['realm']==self._realm_id]+[self._relation_ref(r) for r in m.get('relations',[]) if r['rel'] in names.get(field,()) and (not r.get('realm') or r['realm']==self._realm_id)]

    def _receipt_supersedes(self, metadata):
        # Immutable 0.1 receipts preserved selectors on direct references but
        # omitted selectors projected from relations. Keep those exact bytes'
        # interpretation; source selection cannot rewrite an acceptance receipt.
        legacy = {**metadata, 'relations': [
            {key: value for key, value in relation.items() if key != 'selector'}
            for relation in metadata.get('relations', [])]}
        return self._links(legacy, 'supersedes')

    @staticmethod
    def _assessment_refs(m):
        refs = [ref for assertion in m.get('assurance', {}).values() for ref in assertion.get('basis', [])]
        return refs + list(m.get('evolution', {}).get('propagation_basis', []))

    def _refs(self, m):
        refs=list(m.get('basis', [])) + list(m.get('depends_on', [])) + list(m.get('supersedes', [])) + list(m.get('conflicts', []))
        refs.extend(self._relation_ref(r) for r in m.get('relations',[]) if not r.get('realm') or r['realm']==self._realm_id)
        refs.extend(self._assessment_refs(m))
        if m.get('kind')=='context':refs.extend(m.get('context',{}).get('basis',[]))
        return [ref for ref in refs if not isinstance(ref,dict) or not ref.get('realm') or ref['realm']==self._realm_id]

    def _external_refs(self,m):
        refs=[ref for field in ('basis','depends_on','supersedes','conflicts') for ref in m.get(field,[]) if isinstance(ref,dict)]
        refs.extend(self._assessment_refs(m))
        refs.extend(m.get('relations',[]))
        refs.extend(ref for ref in m.get('context',{}).get('basis',[]) if isinstance(ref,dict))
        return [ref for ref in refs if ref.get('realm') and ref['realm']!=self._realm_id]

    def _acceptances(self, snapshot, records):
        accepted = {}
        self._unverified_receipts=[]
        root=self._roots(self.codec.load_yaml(snapshot['files'][CONTROL[0]],allow_aliases=snapshot['revision'] is not None and snapshot['revision']!=self.store.history()[0]))['receipts_root']
        for path, raw in snapshot['files'].items():
            if not path.startswith(root+'/') or not path.endswith(('.json','.yaml','.yml')): continue
            receipt = self.codec.load_json(raw) if path.endswith('.json') else self.codec.load_yaml(raw,allow_aliases=snapshot['revision'] is not None and snapshot['revision']!=self.store.history()[0])
            self.codec.validate_schema('receipt',receipt)
            for field in ('id','record_id','actor','adopted_at','governance_sha256','record_sha256','record_revision'):
                if not receipt.get(field):raise ValueError('receipt missing '+field)
            for field in ('governance_sha256','record_sha256'):
                if not re.fullmatch('[0-9a-f]{64}',str(receipt[field])):raise ValueError('invalid receipt digest')
            current_record=records.get(receipt['record_id'])
            record=self._reference({'id':receipt['record_id'],'digest':'sha256:'+receipt['record_sha256'],'revision':receipt['record_revision']},records)
            # Verify the actual policy version under which this receipt was made.
            if receipt.get('record_revision')!=record['metadata']['revision']:raise ValueError('receipt revision mismatch')
            if not receipt.get('base') or not receipt.get('authority_basis'):
                self._unverified_receipts.append({'id':receipt['record_id'],'reason':'receipt structure valid; actor and policy acceptance unverified by this runtime'})
                continue
            historical = self.store.snapshot(receipt['base'])
            policy_raw = historical['files'][CONTROL[1]]
            if digest(policy_raw) != receipt.get('governance_sha256'): raise ValueError('receipt policy digest mismatch')
            policy = self.codec.load_yaml(policy_raw,allow_aliases=receipt['base']!=self.store.history()[0])
            if receipt.get('policy_version') != policy.get('version',1): raise ValueError('receipt policy version mismatch')
            self._time(receipt.get('adopted_at'))
            principal = receipt.get('actor')
            permitted = set()
            for grant in self._grants(policy):
                if grant.get('principal') == principal and 'accept' in grant.get('actions', []): permitted.update(grant.get('scopes', []))
            if '*' not in permitted and not set(record['metadata']['scope']) <= permitted: raise ValueError('receipt authority invalid')
            if receipt.get('authority_basis') != 'trusted-local-policy-grant': raise ValueError('receipt authority basis invalid')
            if receipt.get('supersedes', []) != self._receipt_supersedes(record['metadata']): raise ValueError('receipt replacement mismatch')
            if current_record and current_record['digest']==record['digest']:accepted[record['metadata']['id']] = receipt
        return accepted

    def _validate_asset_ownership(self, snapshot, roots, records):
        owned={asset['path'] for r in records.values() if r['metadata']['kind']=='source' for asset in r['metadata']['source'].get('assets',[])}
        if any(path.startswith(roots['source_root']+'/') and path not in owned for path in snapshot['files']):raise ValueError('source file has no owning source descriptor')

    def _validate(self, snapshot, *, historical=False, check_asset_ownership=True):
        realm, policy, packs, records = self._load(snapshot,historical=historical)
        if realm.get('schema') != 'ekk.realm/0.1' or not all(realm.get(k) for k in ('id','name','owner','default_context','default_classification','storage')): raise ValueError('invalid realm manifest')
        if realm.get('required_semantics') or realm.get('requires'): raise ValueError('unknown mandatory realm semantics')
        if policy.get('schema') != 'ekk.governance/0.1' or not isinstance(policy.get('version',1), int): raise ValueError('invalid governance version')
        if policy.get('required_semantics') or policy.get('requires'):raise ValueError('unknown mandatory governance semantics')
        if policy.get('default_effect')!='deny':raise ValueError('unsupported governance default effect')
        if not isinstance(policy.get('trusted_acceptors',[]),list) or any(not isinstance(x,str) or not x for x in policy.get('trusted_acceptors',[])):raise ValueError('trusted_acceptors must be a list of principals')
        grants=policy.get('grants',[])
        if not isinstance(grants,list):raise ValueError('grants must be a list')
        for grant in grants:
            if not isinstance(grant,dict) or not isinstance(grant.get('principal'),str) or not grant['principal']:raise ValueError('invalid grant principal')
            for field in ('actions','scopes'):
                values=grant.get(field)
                if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v for v in values):raise ValueError('grant '+field+' must be a nonempty list')
            if not set(grant['actions'])<={'read','write','accept'}:raise ValueError('unsupported grant action')
        exports=policy.get('export_grants',[])
        if not isinstance(exports,list):raise ValueError('export_grants must be a list')
        seen_export=set()
        for grant in exports:
            if not isinstance(grant,dict):raise ValueError('export grant must be an object')
            for field in ('id','principal','destination','source_visibility','destination_visibility'):
                if not isinstance(grant.get(field),str) or not grant[field]:raise ValueError('invalid export grant '+field)
            if grant['id'] in seen_export:raise ValueError('duplicate export grant ID')
            seen_export.add(grant['id'])
            for field in ('ids','source_paths'):
                values=grant.get(field,[])
                if not isinstance(values,list) or any(not isinstance(v,str) or not v for v in values):raise ValueError('invalid export grant '+field)
            if 'declassify' in grant and type(grant['declassify']) is not bool:raise ValueError('declassify must be boolean')

        if packs.get('schema')!='ekk.packs-lock/0.1' or not isinstance(packs.get('packages'),list):raise ValueError('invalid packs lock')
        for pack in packs['packages']:
            if not all(pack.get(k) for k in ('id','version','origin','sha256')):raise ValueError('pack must pin id, version, origin and artifact sha256')
            if pack.get('required_semantics') or pack.get('requires'):raise ValueError('unknown mandatory pack semantics')
            if self.pack_loader is None:raise ValueError('pinned pack payload unavailable')
            payload=self.pack_loader(pack['id'],pack['version'])
            for path,raw in payload.items():
                posix=PurePosixPath(path)
                if posix.is_absolute() or '..' in posix.parts or str(posix)!=path or not isinstance(raw,bytes):raise ValueError('invalid pack payload')
            inventory={path:digest(raw) for path,raw in payload.items()}
            artifact=digest(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode())
            if artifact!=pack['sha256']:raise ValueError('pack artifact digest mismatch')
            manifest=self.codec.load_yaml(payload['pack.yaml'])
            if manifest.get('schema')!='ekk.pack/0.1' or manifest.get('id')!=pack['id'] or manifest.get('version')!=pack['version']:raise ValueError('pack identity/version mismatch')
            if manifest.get('requires') or manifest.get('required_semantics') or any(f!='ekk.record/0.1' for f in manifest.get('requires_format',[])):raise ValueError('unknown mandatory pack semantics')
            if manifest.get('installation_executes_code') is not False:raise ValueError('executable pack installation unsupported')
            if any(entry not in payload for entry in manifest.get('entrypoints',[])):raise ValueError('pack entrypoint missing')
        contexts = {key for key,r in records.items() if r['metadata']['kind']=='context'}
        if not contexts: raise ValueError('at least one context required')
        if realm.get('default_context') and realm['default_context'] not in contexts: raise ValueError('default context missing')
        roots=self._roots(realm)
        if realm['default_classification'] not in ('public','internal','private','restricted'):raise ValueError('invalid realm classification')
        for key,r in records.items():
            m = r['metadata']
            if not set(m['scope']) <= contexts: raise ValueError('scope must resolve to context IDs')
            if m.get('required_semantics') or m.get('requires'): raise ValueError('unknown mandatory record semantics')
            for field in ('basis','depends_on','supersedes','conflicts'):
                if not isinstance(m.get(field,[]),list): raise ValueError(field+' must be a list')
            if m.get('commitment') is not None and not isinstance(m['commitment'],dict): raise ValueError('commitment must be a mapping')
            for field in ('valid_from','valid_until'):
                if m.get(field): self._time(m[field])
            for ref in self._refs(m): self._reference(ref, records)
            for assertion in m.get('assurance',{}).values():
                for ref in assertion.get('basis',[]):self._reference(ref,records)
            for ref in m.get('evolution',{}).get('propagation_basis',[]):self._reference(ref,records)
            if not set(m.get('evolution',{}).get('origin_scopes',[])) <= contexts:raise ValueError('evolution origins must resolve to contexts')
            observation=m.get('observation')
            if observation and 'subject' in observation and observation['subject'] not in records:raise ValueError('observation subject must resolve')
            if m['kind']=='source':
                source = m.get('source', {})
                for asset in source.get('assets',[]):
                    path=asset['path'];posix=PurePosixPath(path)
                    if not path.startswith(roots['source_root']+'/') or '..' in posix.parts or str(posix)!=path or digest(snapshot['files'][path])!=asset['sha256']:raise ValueError('source bytes digest mismatch')
                if not source.get('assets') and not source.get('uri'):raise ValueError('source needs assets or external URI')
        if check_asset_ownership:self._validate_asset_ownership(snapshot,roots,records)
        for family in (('basis','depends_on'), ('supersedes',)):
            visiting=set();done=set()
            def visit(key):
                if key in visiting: raise ValueError('dependency/replacement cycle')
                if key in done:return
                visiting.add(key)
                for field in family:
                    for ref in self._links(records[key]['metadata'],field):
                        target=self._reference(ref,records)
                        if target['metadata']['id'] in records and target['digest']==records[target['metadata']['id']]['digest']:visit(target['metadata']['id'])
                visiting.remove(key);done.add(key)
            for key in records:visit(key)
        return realm,policy,packs,records

    def _query_view(self, scopes):
        """One published view, authorized by its current policy, for public reads."""
        if not isinstance(scopes, (list, tuple)) or not scopes:
            raise ValueError('explicit query scopes required')
        snapshot = self.store.snapshot()
        realm, policy, _, records = self._validate(snapshot)
        self._authorized(policy, 'read', scopes)
        if any(key not in records or records[key]['metadata']['kind'] != 'context' for key in scopes):
            raise ValueError('requested context IDs required')
        return snapshot, realm, policy, records

    def _query_readable(self, record, records, policy, scopes):
        """Read permission covers the exact record and its local dependency closure."""
        seen = set()
        def visit(row, candidates):
            marker = (row['metadata']['id'], row['digest'])
            if marker in seen:
                return
            seen.add(marker)
            if not set(row['metadata']['scope']) <= set(scopes):
                raise PermissionError('record or dependency outside selected contexts')
            self._authorized(policy, 'read', row['metadata']['scope'])
            historic = row.get('snapshot_revision')
            if historic and candidates and historic != next(iter(candidates.values())).get('snapshot_revision'):
                candidates = self._load(self.store.snapshot(historic), historical=True)[-1]
            for ref in self._refs(row['metadata']):
                visit(self._reference(ref, candidates), candidates)
        visit(record, records)

    @staticmethod
    def _query_reference(realm_id, row):
        return {'realm': realm_id, 'id': row['metadata']['id'],
                'revision': row['metadata']['revision'], 'digest': 'sha256:' + row['digest']}

    def list_contexts(self, scopes):
        """Describe only explicitly selected contexts, without exposing control files."""
        snapshot, realm, policy, records = self._query_view(scopes)
        visible = []
        for key in sorted(set(scopes)):
            row = records[key]
            self._query_readable(row, records, policy, scopes)
            visible.append({'id': key, 'title': row['metadata']['title'],
                            'reference': self._query_reference(realm['id'], row)})
        return {'schema': 'ekk.context-catalog/0.1', 'realm': realm['id'],
                'snapshot': snapshot['revision'], 'contexts': visible,
                'coverage': 'explicit authorized contexts only'}

    def search_records(self, scopes, *, query='', limit=20, offset=0,
                       expected_snapshot=None, source_byte_limit=1048576):
        """Search canonical records and their owned UTF-8 assets; return exact refs.

        An empty query browses the selected contexts. Pagination must pin the first
        result's snapshot; a changed publication never silently shifts a page.
        """
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError('query must be bounded text')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('limit must be between 1 and 100')
        if type(offset) is not int or offset < 0 or (offset and not expected_snapshot):
            raise ValueError('pagination requires an offset and exact snapshot')
        if type(source_byte_limit) is not int or not 1 <= source_byte_limit <= 4194304:
            raise ValueError('invalid source search bound')
        snapshot, realm, policy, records = self._query_view(scopes)
        if expected_snapshot and expected_snapshot != snapshot['revision']:
            from ekk.model import Conflict
            raise Conflict('search snapshot changed; restart pagination')
        terms = list(dict.fromkeys(re.findall(r'\w+', query.casefold())))
        hits = []
        omitted_sources = 0
        text_suffixes = {'.md', '.txt', '.csv', '.tsv', '.json', '.yaml', '.yml', '.html', '.xml'}
        for row in records.values():
            if not set(row['metadata']['scope']) & set(scopes):
                continue
            try:
                self._query_readable(row, records, policy, scopes)
            except PermissionError:
                continue
            sections = [(None, '\n'.join([row['metadata']['id'], row['metadata']['title'],
                                         *row['metadata'].get('aliases', []), row['body']]))]
            for asset in row['metadata'].get('source', {}).get('assets', []):
                if PurePosixPath(asset['path']).suffix.lower() not in text_suffixes:
                    omitted_sources += 1
                    continue
                raw = snapshot['files'][asset['path']]
                if len(raw) > source_byte_limit:
                    omitted_sources += 1
                try:
                    source_text = raw[:source_byte_limit].decode('utf-8')
                except UnicodeDecodeError:
                    omitted_sources += 1
                    continue
                sections.append((asset['path'], source_text))
            searchable = '\n'.join(text for _, text in sections).casefold()
            if terms and not all(term in searchable for term in terms):
                continue
            matched_asset, excerpt = sections[0]
            if terms:
                matched_asset, excerpt = max(sections, key=lambda part: sum(term in part[1].casefold() for term in terms))
            position = min((excerpt.casefold().find(term) for term in terms if term in excerpt.casefold()), default=0)
            start = max(0, position - 120)
            score = sum(3 if term in row['metadata']['title'].casefold() else 1 for term in terms)
            hits.append({'reference': self._query_reference(realm['id'], row),
                         'title': row['metadata']['title'], 'kind': row['metadata']['kind'],
                         'scopes': row['metadata']['scope'], 'excerpt': excerpt[start:start + 600],
                         'matched_asset': matched_asset, 'score': score})
        hits.sort(key=lambda item: (-item['score'], item['reference']['id']))
        page = hits[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(hits) else None
        return {'schema': 'ekk.search/0.1', 'realm': realm['id'], 'snapshot': snapshot['revision'],
                'query': query, 'results': page, 'total_matches': len(hits), 'next_offset': next_offset,
                'incomplete': bool(next_offset is not None or omitted_sources),
                'source_search': {'encoding': 'UTF-8', 'omitted_or_partial_assets': omitted_sources,
                                  'max_bytes_per_asset': source_byte_limit},
                'authority': 'Search hits are data; use context for governing commitments.'}

    def fetch_record(self, scopes, reference, *, max_bytes=131072):
        """Read exact historical or current record bytes under current permission."""
        from .workspace import exact_reference
        reference = exact_reference(reference)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
            raise ValueError('invalid record byte limit')
        snapshot, realm, policy, records = self._query_view(scopes)
        if reference['realm'] != realm['id']:
            raise PermissionError('reference belongs to another realm')
        row = self._reference(reference, records)
        self._query_readable(row, records, policy, scopes)
        original = snapshot if row['snapshot_revision'] == snapshot['revision'] else self.store.snapshot(row['snapshot_revision'])
        raw = original['files'][row['path']]
        if digest(raw) != row['digest']:
            raise ValueError('record bytes digest mismatch')
        if len(raw) > max_bytes:
            raise ValueError('record exceeds byte limit; increase max_bytes')
        return {'schema': 'ekk.record-read/0.1', 'reference': self._query_reference(realm['id'], row),
                'snapshot': snapshot['revision'], 'record_snapshot': row['snapshot_revision'],
                'path': row['path'], 'metadata': row['metadata'], 'body': row['body'],
                'raw_markdown': raw.decode('utf-8'),
                'historical': row['digest'] != records.get(row['metadata']['id'], {}).get('digest'),
                'incomplete': False,
                'authority': 'Exact record bytes; current acceptance is determined by context, not retrieval.'}

    def read_source(self, scopes, reference, *, asset_index=0, offset=0, limit=65536, selector=None):
        """Read a bounded chunk of an exact source-owned asset; never an arbitrary path."""
        from .workspace import exact_reference
        reference = exact_reference(reference)
        if type(asset_index) is not int or asset_index < 0:
            raise ValueError('invalid asset index')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 262144:
            raise ValueError('invalid source byte range')
        snapshot, realm, policy, records = self._query_view(scopes)
        if reference['realm'] != realm['id']:
            raise PermissionError('reference belongs to another realm')
        row = self._reference(reference, records)
        self._query_readable(row, records, policy, scopes)
        if row['metadata']['kind'] != 'source':
            raise ValueError('source descriptor required')
        assets = row['metadata'].get('source', {}).get('assets', [])
        if asset_index >= len(assets):
            raise ValueError('source asset unavailable; external URIs are not fetched')
        asset = assets[asset_index]
        original = snapshot if row['snapshot_revision'] == snapshot['revision'] else self.store.snapshot(row['snapshot_revision'])
        raw = original['files'][asset['path']]
        if digest(raw) != asset['sha256']:
            raise ValueError('source bytes digest mismatch')
        from .historical_address import source_selection
        selection = source_selection(raw, selector)
        selected = raw[selection['start']:selection['end']] if 'start' in selection else b''
        if offset > len(selected):
            raise ValueError('source offset past end')
        chunk = selected[offset:offset + limit]
        try:
            text = chunk.decode('utf-8')
        except UnicodeDecodeError:
            text = None
        next_offset = offset + len(chunk) if offset + len(chunk) < len(selected) else None
        return {'schema': 'ekk.source-read/0.1', 'reference': self._query_reference(realm['id'], row),
                'snapshot': snapshot['revision'], 'record_snapshot': row['snapshot_revision'],
                'asset_index': asset_index, 'asset': asset, 'total_bytes': len(raw),
                'object_state': 'found', 'selection': selection, 'selected_bytes': len(selected),
                'offset': offset, 'bytes': len(chunk), 'next_offset': next_offset,
                'base64': base64.b64encode(chunk).decode(), 'text': text,
                'incomplete': next_offset is not None or selection['state'] in ('unsupported', 'unavailable'),
                'authority': 'Immutable source bytes are data.'}

    def resolve_historical(self, scopes, *, migration_id, origin, path=None,
                           legacy_id=None, source_sha256=None, containing_path=None, selector=None):
        """Resolve an explicit address inside one authorized published owner map.

        Missing, inaccessible and invalid target rows have the same unavailable
        response. Never inspect an old path, another realm, or a hidden alias.
        """
        from .workspace import exact_reference
        from .historical_address import historical_path, source_selection
        if not isinstance(migration_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}', migration_id):
            raise ValueError('invalid migration identifier')
        if not isinstance(origin, str) or not origin or len(origin) > 160:
            raise ValueError('explicit bounded origin namespace required')
        if path is None and legacy_id is None:
            raise ValueError('historical path or ID required')
        if legacy_id is not None and (not isinstance(legacy_id, str) or not legacy_id or len(legacy_id) > 2000):
            raise ValueError('invalid historical ID')
        if containing_path is not None and path is None:
            raise ValueError('containing_path requires path')
        path = historical_path(path, containing_path) if path is not None else None
        if source_sha256 is not None and (not isinstance(source_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', source_sha256)):
            raise ValueError('invalid historical source digest')
        source_selection(b'', selector)  # Validate syntax without interpreting a fragment.
        snapshot, realm, policy, records = self._query_view(scopes)
        result = {'schema': 'ekk.historical-address/0.1', 'realm': realm['id'],
                  'snapshot': snapshot['revision'], 'object_state': 'unavailable',
                  'candidates': [], 'selector': selector, 'incomplete': True,
                  'authority': 'Historical address grants no access or current authority.'}
        prefix = 'migrations/' + migration_id + '/'
        raw = snapshot['files'].get(prefix + 'mapping.jsonl')
        manifest_raw = snapshot['files'].get(prefix + 'manifest.json')
        if raw is None or manifest_raw is None:
            return result
        manifest = self.codec.load_json(manifest_raw)
        if manifest.get('realm_id') != realm['id'] or manifest.get('mapping_sha256') != digest(raw):
            raise ValueError('migration evidence integrity mismatch')
        candidates = {}
        for line in raw.splitlines():
            entry = self.codec.load_json(line)
            address = entry.get('origin', {})
            if entry.get('address_schema') != 'ekk.historical-address-row/0.1' or address.get('namespace') != origin:
                continue
            if path is not None and address.get('path') != path:
                continue
            if legacy_id is not None and address.get('id') != legacy_id:
                continue
            if source_sha256 is not None and address.get('sha256') != source_sha256:
                continue
            try:
                ref = exact_reference(entry['native_reference'])
                if ref['realm'] != realm['id'] or entry.get('realm_id') != realm['id']:
                    continue
                row = self._reference(ref, records)
                self._query_readable(row, records, policy, scopes)
                index = entry['asset_index']
                if type(index) is not int or index < 0 or row['metadata']['kind'] != 'source':
                    continue
                asset = row['metadata']['source']['assets'][index]
                if asset['sha256'] != address.get('sha256') or asset['path'] != entry['asset_path']:
                    continue
                original = snapshot if row['snapshot_revision'] == snapshot['revision'] else self.store.snapshot(row['snapshot_revision'])
                if digest(original['files'][asset['path']]) != asset['sha256']:
                    continue
                candidate = {'reference': ref, 'asset_index': index, 'asset': asset,
                             'origin': address, 'selector': selector, 'title': row['metadata']['title']}
                candidates[(ref['id'], ref['digest'], index)] = candidate
            except (PermissionError, ValueError, KeyError, IndexError):
                continue
        result['candidates'] = list(candidates.values())
        result['object_state'] = 'found' if len(candidates) == 1 else 'ambiguous' if candidates else 'unavailable'
        result['incomplete'] = result['object_state'] != 'found'
        return result

    def accept_records(self, scopes, references, *, expected_snapshot, idempotency_key):
        """Accept exact bytes at an explicit base; retries use the ordinary write journal."""
        from .workspace import exact_reference
        if not isinstance(references, list) or not 1 <= len(references) <= 32:
            raise ValueError('acceptance requires 1 to 32 exact references')
        refs = [exact_reference(ref) for ref in references]
        if len({ref['id'] for ref in refs}) != len(refs):
            raise ValueError('duplicate acceptance references')
        _, realm, policy, _ = self._query_view(scopes)
        base = self.store.snapshot(expected_snapshot)
        base_records = self._load(base, historical=True)[-1]
        for ref in refs:
            row = base_records.get(ref['id'])
            if ref['realm'] != realm['id'] or row is None or self._query_reference(realm['id'], row) != ref:
                raise ValueError('acceptance bytes differ from the explicit base')
            self._query_readable(row, base_records, policy, scopes)
            self._authorized(policy, 'accept', row['metadata']['scope'])
        try:
            return self.apply(self.propose({}, base=expected_snapshot),
                              idempotency_key=idempotency_key, accept=[ref['id'] for ref in refs])
        except ValueError as exc:
            # The ordinary journal gets the first chance to resolve an exact
            # replay. An unresolvable old-base request is a conflict even when
            # candidate validation notices a newer revision before store CAS.
            from ekk.model import Conflict
            if not isinstance(exc, Conflict) and self.store.snapshot()['revision'] != expected_snapshot:
                raise Conflict('acceptance snapshot changed; read current context') from exc
            raise

    def doctor(self, revision=None):
        snapshot = self.store.snapshot(revision)
        try:
            realm,policy,packs,records = self._validate(snapshot,historical=bool(revision))
            accepted = self._acceptances(snapshot,records)
            unverified_receipts=list(self._unverified_receipts)
            if self.allowed_scopes is not None:
                records={key:r for key,r in records.items() if set(r['metadata']['scope'])<=self.allowed_scopes}
                accepted={key:r for key,r in accepted.items() if key in records}
            return {'ok':True,'revision':snapshot['revision'],'realm_id':realm['id'],'records':len(records),'accepted':sorted(accepted),'unverified':[{'id':key,'reason':'external source/reference availability and authority unverified'} for key,r in records.items() if r['metadata'].get('source',{}).get('uri') or self._external_refs(r['metadata'])]+[item for item in unverified_receipts if item['id'] in records]+[{'id':key,'reason':warning} for key,r in records.items() for warning in r.get('serialization_warnings',[])],'limitations':['Trusted-local journal is not cryptographic proof against the OS owner.','Git is not an independent backup.']}
        except (ValueError,KeyError,TypeError) as exc:
            return {'ok':False,'revision':snapshot['revision'],'errors':[str(exc) if self.allowed_scopes is None else 'realm validation failed; details require full realm access']}

    def propose(self, changes, *, base=None, grounds=None, explanation=None):
        snapshot = self.store.snapshot(base)
        realm=self.codec.load_yaml(snapshot['files'][CONTROL[0]])
        roots=self._roots(realm)
        permitted_roots=roots['record_roots']+[roots['source_root']]
        for path,raw in changes.items():
            p = PurePosixPath(path)
            if p.is_absolute() or '..' in p.parts or str(p)!=path: raise ValueError('unsafe path')
            if path in CONTROL or path.startswith(roots['receipts_root']+'/'):raise PermissionError('proposal cannot edit control or receipt files')
            if not any(path.startswith(root+'/') for root in permitted_roots): raise PermissionError('proposal cannot edit control or receipt files')
            if raw is not None and not isinstance(raw,bytes): raise ValueError('changes must contain bytes')
        submitted_scopes=set();scoped_files=set();inferred=[]
        for path,raw in changes.items():
            if raw is None or not path.endswith('.md') or not any(path.startswith(root+'/') for root in roots['record_roots']):continue
            try:
                metadata=validate_envelope(self.codec.decode(raw)['metadata'])
            except ValueError:
                continue # The apply validator remains authoritative for the full candidate.
            submitted_scopes.update(metadata['scope']);scoped_files.add(path)
            if metadata['kind']=='source':scoped_files.update(asset['path'] for asset in metadata.get('source',{}).get('assets',[]))
            inferred.extend(metadata.get('basis',[]));inferred.extend(metadata.get('depends_on',[]))
            inferred.extend(self._relation_ref(ref) for ref in metadata.get('relations',[]) if ref['rel'] in ('derived_from','depends_on'))
        if grounds is None:grounds=inferred
        if not isinstance(grounds,list):raise ValueError('proposal grounds must be a list of references')
        for ref in grounds:validate_reference(ref)
        if explanation is not None and not isinstance(explanation,str):raise ValueError('proposal explanation must be text')
        unique={json.dumps(ref,sort_keys=True,ensure_ascii=False):ref for ref in grounds}
        proposal={'schema':'ekk.proposal/0.1','base':snapshot['revision'],'changes':{p:None if raw is None else base64.b64encode(raw).decode() for p,raw in sorted(changes.items())},'grounds':[unique[key] for key in sorted(unique)],'impact':{'files':sorted(changes),'scopes':sorted(submitted_scopes),'scopes_complete':all(path in scoped_files for path in changes)},'authority_note':'Grounds, impact and explanation describe submitted content; they do not grant permissions or establish acceptance.'}
        if explanation is not None:proposal['explanation']=explanation
        return proposal

    def capture(self, data, *, title, scope, filename='original.bin'):
        if not isinstance(data,bytes): raise ValueError('source must be exact bytes')
        if PurePosixPath(filename).name != filename or filename in ('.','..'): raise ValueError('filename must be a basename')
        m = self._meta('source',title,scope)
        realm=self.codec.load_yaml(self.store.snapshot()['files'][CONTROL[0]])
        roots=self._roots(realm)
        path = f"{roots['source_root']}/{m['id']}/{filename}"
        m['source'] = {'assets':[{'path':path,'sha256':digest(data)}]}
        m['recorded_at']=self._now()
        root='records' if 'records' in roots['record_roots'] else roots['record_roots'][0]
        return self.propose({path:data,f"{root}/{m['id']}.md":self.codec.encode(m)})

    def retain(self, artifacts, *, title, body, scope, repository_evidence=None):
        """Prepare exact sources and one discoverable, unaccepted result together."""
        if not isinstance(artifacts, list) or len(artifacts) > 32:
            raise ValueError('retain accepts at most 32 source artifacts')
        if not isinstance(title, str) or not title or not isinstance(body, str) or not body.strip():
            raise ValueError('retain requires a title and a nonempty result body')
        realm = self.codec.load_yaml(self.store.snapshot()['files'][CONTROL[0]])
        roots = self._roots(realm)['record_roots']
        changes = {}; references = []
        for artifact in artifacts:
            if not isinstance(artifact, dict) or set(artifact) - {'data', 'filename', 'title'}:
                raise ValueError('artifact requires exact data, filename and optional title')
            proposal = self.capture(artifact['data'], title=artifact.get('title', artifact['filename']),
                                    scope=scope, filename=artifact['filename'])
            for path, encoded in proposal['changes'].items():
                raw = base64.b64decode(encoded, validate=True)
                changes[path] = raw
                if path.endswith('.md') and any(path.startswith(root + '/') for root in roots):
                    try: metadata = self.codec.decode(raw)['metadata']
                    except ValueError: continue
                    if metadata.get('kind') == 'source':
                        references.append({'id': metadata['id'], 'revision': metadata['revision'],
                                           'digest': 'sha256:' + digest(raw)})
        root = 'records' if 'records' in roots else roots[0]
        metadata = self._meta('outcome', title, scope, basis=references,
                              retention={'schema': 'ekk.retained-result/0.1',
                                         'claim_source': 'recorded_assertion'})
        if repository_evidence is not None:
            if not isinstance(repository_evidence, dict):
                raise ValueError('repository evidence must be a recorded declaration')
            metadata['repository_evidence'] = repository_evidence
        changes[f"{root}/{metadata['id']}.md"] = self.codec.encode(metadata, body)
        return self.propose(changes)

    def verify_retention(self, scopes, proposal, receipt):
        """Read a publication back under current access; verify sources as bytes.

        This is a storage check, not acceptance or a test of the result's truth.
        The adapter keeps the publication receipt even if this check is unavailable.
        """
        snapshot, realm, policy, current = self._query_view(scopes)
        published = self.store.snapshot(receipt['revision'])
        records = self._load(published, historical=True)[-1]
        references = []; result_reference = None
        changes = {path: base64.b64decode(raw, validate=True)
                   for path, raw in proposal['changes'].items() if raw is not None}
        for row in records.values():
            if row['path'] not in changes:
                continue
            self._query_readable(row, records, policy, scopes)
            raw = published['files'][row['path']]
            if raw != changes[row['path']]:
                raise ValueError('published record differs from the retained request')
            ref = self._query_reference(realm['id'], row)
            if row['metadata']['kind'] == 'source':
                for asset in row['metadata'].get('source', {}).get('assets', []):
                    data = published['files'][asset['path']]
                    if data != changes.get(asset['path']) or digest(data) != asset['sha256']:
                        raise ValueError('published source differs from the retained bytes')
                references.append(ref)
            elif row['metadata'].get('retention', {}).get('schema') == 'ekk.retained-result/0.1':
                result_reference = ref
        return {'source_references': references, 'result_reference': result_reference,
                'read_back': True, 'snapshot': receipt['revision']}

    def _read_basis(self, metadata, records, policy):
        seen=set()
        def basis_links(m):
            return self._links(m,'basis')+self._links(m,'depends_on')+self._assessment_refs(m)
        def visit(ref, candidates, consequential):
            if consequential:validate_reference(ref,pinned=True)
            record=self._reference(ref,candidates)
            marker=(record['metadata']['id'],record['digest'],consequential)
            if marker in seen:return
            seen.add(marker)
            self._authorized(policy,'read',record['metadata']['scope'])
            if self._external_refs(record['metadata']):raise ValueError('external acceptance dependency remains unverified')
            snapshot_revision=record.get('snapshot_revision')
            nested=candidates
            if snapshot_revision and candidates and snapshot_revision!=next(iter(candidates.values())).get('snapshot_revision'):
                nested=self._load(self.store.snapshot(snapshot_revision),historical=True)[-1]
            evidence=basis_links(record['metadata'])
            for dependency in self._refs(record['metadata']):
                visit(dependency,nested,consequential and dependency in evidence)
        for ref in basis_links(metadata):visit(ref,records,True)

    def apply(self, proposal, *, idempotency_key, accept=()):
        if proposal.get('schema') != 'ekk.proposal/0.1': raise ValueError('invalid proposal')
        changes = {p:None if raw is None else base64.b64decode(raw,validate=True) for p,raw in proposal['changes'].items()}
        self.propose(changes,base=proposal['base']) # Recheck untrusted proposal paths.
        base = self.store.snapshot(proposal['base'])
        current = self.store.snapshot()
        # Store also enforces CAS; authorization always uses published current policy.
        realm,policy,packs,old = self._validate(current)
        files = dict(base['files'])
        for p,raw in changes.items():
            if raw is None: files.pop(p,None)
            else: files[p]=raw
        candidate = {'revision':base['revision'],'files':files}
        _,_,_,records = self._validate(candidate,check_asset_ownership=False)
        # Retry attribution is checked against the original exact request, after
        # current permission checks and before interpreting later record revisions.
        original_affected=[r for r in records.values() if r['path'] in changes]
        base_records=self._load(base,historical=True)[-1]
        original_affected.extend(r for r in base_records.values() if r['path'] in changes)
        if changes or not accept:self._authorized(policy,'write',{scope for r in original_affected for scope in r['metadata']['scope']})
        replay_changes=dict(changes);can_lookup=True
        for key in sorted(set(accept)):
            r=records[key];self._authorized(policy,'accept',r['metadata']['scope'])
            self._read_basis(r['metadata'],records,policy)
            receipt_path=f'{self._roots(realm)["receipts_root"]}/{digest(key.encode())}-{r["digest"]}.json'
            raw=current['files'].get(receipt_path)
            if raw and json.loads(raw).get('base')==proposal['base'] and json.loads(raw).get('actor')==self.principal:replay_changes[receipt_path]=raw
            else:can_lookup=False
        if can_lookup:
            replay=self.store.lookup(replay_changes,base=proposal['base'],idempotency_key=idempotency_key,principal=self.principal,policy_digest=digest(base['files'][CONTROL[1]]))
            if replay is not None:return replay
            if current['revision'] != proposal['base']:
                raise Conflict('Base snapshot is stale; no exact publication was found')
        current_accepted=self._acceptances(current,old)
        for key in current_accepted:
            before=old[key]
            after=records.get(key)
            if after is None or after['digest']!=before['digest']:
                self._authorized(policy,'accept',before['metadata']['scope'])
                if after:self._authorized(policy,'accept',after['metadata']['scope'])
        for key,before in old.items():
            if before['metadata']['kind']!='context':continue
            after=records.get(key)
            before_basis=before['metadata'].get('context',{}).get('basis',[])
            after_basis=after['metadata'].get('context',{}).get('basis',[]) if after else None
            if before_basis!=after_basis or (after and before['metadata']['scope']!=after['metadata']['scope']):
                self._authorized(policy,'accept',before['metadata']['scope'])
                if after:self._authorized(policy,'accept',after['metadata']['scope'])
        for key,after in records.items():
            if key not in old and after['metadata']['kind']=='context' and after['metadata'].get('context',{}).get('basis'):self._authorized(policy,'accept',after['metadata']['scope'])
        affected = [r for r in records.values() if r['path'] in changes]
        affected += [r for r in old.values() if r['path'] in changes]
        source_paths={asset['path'] for r in affected if r['metadata']['kind']=='source' for asset in r['metadata'].get('source',{}).get('assets',[])}
        for path in changes:
            if path.startswith(self._roots(realm)['source_root']+'/') and path not in source_paths:raise PermissionError('source bytes require an affected authorized source descriptor')
        scopes = sorted({s for r in affected for s in r['metadata']['scope']})
        if changes or not accept:self._authorized(policy,'write',scopes)
        self._validate_asset_ownership(candidate,self._roots(realm),records)
        for key,r in records.items():
            if key in old and r['digest'] != old[key]['digest'] and r['metadata']['revision'] != old[key]['metadata']['revision']+1: raise ValueError('edited record requires next revision')
        recreated={key for key in records if key not in old}
        historic_revisions={}
        if recreated:
            for revision in self.store.history():
                for key,r in self._load(self.store.snapshot(revision),historical=True)[-1].items():
                    if key in recreated:historic_revisions[key]=max(historic_revisions.get(key,0),r['metadata']['revision'])
            for key,previous_revision in historic_revisions.items():
                if records[key]['metadata']['revision']!=previous_revision+1:raise ValueError('recreated ID requires next historical revision')
        for path in changes:
            if path.startswith(self._roots(realm)['source_root']+'/') and path in base['files'] and changes[path] is not None and changes[path] != base['files'][path]: raise ValueError('preserved source bytes are immutable')
        accepted = self._acceptances(base,records)
        for key in set(accepted)-set(current_accepted):self._authorized(policy,'accept',records[key]['metadata']['scope'])
        for key in sorted(set(accept)):
            r = records[key]; m=r['metadata']
            if m['kind'] not in ('decision','policy'): raise ValueError('only explicit decisions/policies can be accepted')
            self._authorized(policy,'accept',m['scope'])
            self._read_basis(m,records,policy)
            for ref in self._links(m,'basis'): validate_reference(ref,pinned=True)
            if not self._links(m,'basis'): raise ValueError('acceptance requires pinned basis')
            if self._external_refs(m):raise ValueError('external acceptance basis remains unverified')
            for ref in self._links(m,'supersedes'):
                validate_reference(ref,pinned=True)
                target=self._reference(ref,records)
                if target['metadata']['id'] not in accepted or target['digest']!=records[target['metadata']['id']]['digest'] or set(target['metadata']['scope']) != set(m['scope']): raise ValueError('replacement needs accepted target in same scopes')
            receipt={'schema':'ekk.receipt/0.1','id':new_id(),'record_id':key,'record_revision':m['revision'],'record_sha256':r['digest'],'adopted_at':self._now(),'actor':self.principal,'governance_sha256':digest(current['files'][CONTROL[1]]),'policy_version':policy.get('version',1),'authority_basis':'trusted-local-policy-grant','base':current['revision'],'supersedes':self._receipt_supersedes(m)}
            receipt_path=f'{self._roots(realm)["receipts_root"]}/{digest(key.encode())}-{r["digest"]}.json'
            previous=current['files'].get(receipt_path)
            if previous and json.loads(previous).get('base') == proposal['base'] and json.loads(previous).get('actor') == self.principal:
                changes[receipt_path]=previous
            else:
                changes[receipt_path]=(json.dumps(receipt,sort_keys=True)+'\n').encode()
        return self.store.apply(changes,base=proposal['base'],idempotency_key=idempotency_key,principal=self.principal,policy_digest=digest(current['files'][CONTROL[1]]))

    def retain_migration_evidence(self, mapping, *, migration_id, target_realm, idempotency_key):
        if self.allowed_scopes is not None:raise PermissionError('migration evidence requires explicit realm administration')
        current=self.store.snapshot();realm,policy,_,records=self._validate(current)
        if realm['owner']!=self.principal or policy.get('bootstrap_owner')!=self.principal:raise PermissionError('migration evidence requires current trusted owner')
        if target_realm!=realm['id']:raise ValueError('migration evidence target realm mismatch')
        if realm['default_classification']=='public':raise PermissionError('public evidence transfer requires explicit export')
        if not isinstance(migration_id,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,159}',migration_id):raise ValueError('invalid migration identifier')
        if not isinstance(mapping,list) or not mapping:raise ValueError('nonempty mapping rows required')
        targets=set()
        for row in mapping:
            if not isinstance(row,dict) or row.get('realm_id')!=target_realm:raise ValueError('each mapping row must name its target realm_id')
            if not isinstance(row.get('origin'),dict) or not row['origin']:raise ValueError('mapping origin required')
            ids=row.get('target_ids')
            if not isinstance(ids,list) or any(not isinstance(key,str) or key not in records for key in ids):raise ValueError('mapping target IDs must resolve in this realm')
            targets.update(ids)
        self._authorized(policy,'write',{scope for key in targets for scope in records[key]['metadata']['scope']})
        raw=b''.join((json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode() for row in mapping)
        prefix='migrations/'+migration_id+'/'
        paths=[prefix+'mapping.jsonl',prefix+'manifest.json',prefix+'validation.md']
        present=[path in current['files'] for path in paths]
        if any(present):
            if not all(present) or current['files'][paths[0]]!=raw:raise ValueError('migration evidence is immutable')
            manifest=self.codec.load_json(current['files'][paths[1]])
            if manifest.get('realm_id')!=target_realm or manifest.get('mapping_sha256')!=digest(raw):raise ValueError('migration evidence integrity mismatch')
            receipt=self.store.lookup({path:current['files'][path] for path in paths},base=manifest['base'],idempotency_key=idempotency_key,principal=self.principal,policy_digest=manifest['governance_sha256'])
            if receipt is None:raise ValueError('migration evidence exists under another operation')
            return receipt
        manifest={'schema':'ekk.migration-evidence/0.1','id':migration_id,'realm_id':realm['id'],'classification':realm['default_classification'],'base':current['revision'],'mapping_sha256':digest(raw),'rows':len(mapping),'validated_target_ids':sorted(targets),'governance_sha256':digest(current['files'][CONTROL[1]]),'recorded_at':self._now(),'validation':'target IDs resolve in the named snapshot; semantic migration and outcomes not proven'}
        files={paths[0]:raw,paths[1]:(json.dumps(manifest,sort_keys=True,ensure_ascii=False)+'\n').encode(),paths[2]:('Target IDs verified: '+str(len(targets))+'\nSnapshot: '+current['revision']+'\nMapping SHA-256: '+digest(raw)+'\nThis verifies mapping structure and target existence, not semantic completeness, adoption, or outcome.\n').encode()}
        return self.store.apply(files,base=current['revision'],idempotency_key=idempotency_key,principal=self.principal,policy_digest=manifest['governance_sha256'])

    def configure(self, changes, *, base, idempotency_key):
        if self.allowed_scopes is not None:raise PermissionError('configuration requires explicit realm administration')
        current=self.store.snapshot()
        realm,policy,_,_=self._validate(current)
        if realm.get('owner')!=self.principal or policy.get('bootstrap_owner')!=self.principal: raise PermissionError('configuration requires current trusted owner')
        if not changes or not set(changes)<=set(CONTROL) or any(not isinstance(v,bytes) for v in changes.values()): raise PermissionError('configuration only edits control documents')
        files={**current['files'],**changes}
        updated,new_policy,_,_=self._validate({'revision':current['revision'],'files':files})
        if updated['id']!=realm['id'] or updated.get('owner')!=realm.get('owner') or new_policy.get('bootstrap_owner')!=policy.get('bootstrap_owner'): raise PermissionError('realm identity/owner transfer requires separate migration')
        if CONTROL[1] in changes and new_policy.get('version',1)!=policy.get('version',1)+1: raise ValueError('governance requires next version')
        return self.store.apply(changes,base=base,idempotency_key=idempotency_key,principal=self.principal,policy_digest=digest(current['files'][CONTROL[1]]))

    def publication_revision(self):
        """Current publication token, without exposing storage representation."""
        return self.store.snapshot()['revision']

    def context(self, scopes, task='', budget=16000, *, focus=(), selection='discovery'):
        if selection not in ('discovery', 'action_requirements'):
            raise ValueError('Unknown context selection')
        action_requirements = selection == 'action_requirements'
        if action_requirements and task:
            raise ValueError('Action context uses explicit grounds, not discovery text')
        if type(budget) is not int or budget<1:raise ValueError('budget must be a positive integer number of bytes')
        snapshot = self.store.snapshot()
        realm,policy,packs,records = self._validate(snapshot)
        self._authorized(policy,'read',scopes)
        if not scopes or any(s not in records or records[s]['metadata']['kind']!='context' for s in scopes): raise ValueError('requested context IDs required')
        from .workspace import exact_reference
        if not isinstance(focus, (list, tuple)):
            raise ValueError('focus must be a list of exact references')
        forced = [exact_reference(ref) for ref in focus]
        if any(ref['realm'] != realm['id'] for ref in forced):
            raise ValueError('focus realm differs from resolved realm')
        accepted = self._acceptances(snapshot,records)
        receipt_unknowns=any(item['id'] in records and set(records[item['id']]['metadata']['scope']) & set(scopes) for item in self._unverified_receipts)
        now = self._now()
        access_unknowns=['unverified acceptance receipt present; no governing authority inferred'] if receipt_unknowns else []
        def readable(r):
            try:
                self._query_readable(r, records, policy, scopes)
                return True
            except PermissionError:
                return False
        relevant={k:r for k,r in records.items() if set(r['metadata']['scope']) & set(scopes)}
        eligible={k:r for k,r in relevant.items() if readable(r)}
        def active(r):
            m=r['metadata']
            return (not m.get('valid_from') or self._time(m['valid_from'])<=self._time(now)) and (not m.get('valid_until') or self._time(m['valid_until'])>self._time(now))
        if any(k in accepted and active(r) and r['metadata']['kind'] in ('decision','policy') for k,r in relevant.items() if k not in eligible):
            access_unknowns.append('applicable accepted commitment or basis outside authorized projection')
        governing = {k for k in accepted if k in eligible and active(eligible[k]) and eligible[k]['metadata']['kind'] in ('decision','policy')}
        replaced=set()
        for key in governing:
            for ref in self._links(records[key]['metadata'],'supersedes'):
                target=self._reference(ref,records);target_id=target['metadata']['id']
                if target_id in records and target['digest']==records[target_id]['digest']:replaced.add(target_id)
        governing -= replaced
        declared=set()
        declaration_unknowns=list(access_unknowns)
        for scope in scopes:
            for ref in records[scope]['metadata'].get('context',{}).get('basis',[]):
                if isinstance(ref,dict) and ref.get('realm') and ref['realm']!=self._realm_id:
                    declaration_unknowns.append('declared context basis requires an authorized external projection')
                    continue
                target=self._reference(ref,records);key=target['metadata']['id']
                declared.add(key)
                if key not in governing or target['digest']!=records[key]['digest']: declaration_unknowns.append('declared context basis is not a current accepted commitment')
        mandatory = sorted(declared | {k for k in governing if records[k]['metadata'].get('mandatory') or records[k]['metadata']['kind']=='policy'})
        if action_requirements:
            # Every applicable governing commitment matters to an assessment,
            # including decisions that are optional in ordinary reading context.
            mandatory = sorted(set(mandatory) | governing)
        tokens = set(re.findall(r'\w+',task.casefold()))
        source_search_omitted = set()
        source_scan_limit = CONTEXT_SOURCE_SCAN_BYTES
        source_scan_bytes = 0
        def score(k):
            nonlocal source_scan_bytes
            r=eligible[k]
            sections = [r['metadata']['id'], r['metadata']['title'],
                        *r['metadata'].get('aliases', []), r['body']]
            for asset in r['metadata'].get('source', {}).get('assets', []):
                if PurePosixPath(asset['path']).suffix.lower() not in {'.md','.txt','.csv','.tsv','.json','.yaml','.yml','.html','.xml'}:
                    source_search_omitted.add(asset['path']); continue
                raw = snapshot['files'][asset['path']]
                take = min(1048576, source_scan_limit - source_scan_bytes)
                if len(raw) > take: source_search_omitted.add(asset['path'])
                if take == 0: continue
                chunk = raw[:take]
                source_scan_bytes += len(chunk)
                try: sections.append(chunk.decode('utf-8'))
                except UnicodeDecodeError: source_search_omitted.add(asset['path'])
            return len(tokens & set(re.findall(r'\w+', ' '.join(sections).casefold())))
        scores = {key: score(key) for key in eligible} if task else {}
        def relevance(key): return scores.get(key, 0)
        ranked = sorted((k for k in eligible if k not in mandatory and (k in governing or not task or relevance(k))),key=lambda k:(-relevance(k),k))
        if action_requirements:
            ranked = []
        selected={}; unknowns=list(declaration_unknowns); used=0; blocked=False; omitted=[]
        reading_unknowns = set()
        def closure(key, bundle, override=None, candidates=None, historical_focus=False):
            candidates = records if candidates is None else candidates
            r=override or candidates[key]
            marker=key if key in records and r['digest']==records[key]['digest'] else key+'@'+r['digest']
            if marker in bundle or marker in selected: return
            if not (set(r['metadata']['scope']) & set(scopes)) or not readable(r):
                unknowns.append('required dependency outside requested or authorized projection')
                return
            if self._external_refs(r['metadata']):unknowns.append('external reference unverified; no cross-realm lookup performed')
            if r['metadata']['kind']=='source' and r['metadata'].get('source',{}).get('uri') and not r['metadata']['source'].get('revision'):unknowns.append('external source version unknown')
            bundle[marker]=r
            historic = r.get('snapshot_revision')
            if historic and candidates and historic != next(iter(candidates.values())).get('snapshot_revision'):
                candidates = self._load(self.store.snapshot(historic), historical=True)[-1]
            for ref in self._refs(r['metadata']):
                if historical_focus and (not isinstance(ref, dict) or not any(ref.get(field) for field in ('revision','digest','snapshot'))):
                    reading_unknowns.add('selected historical material has an unpinned dependency; its version at initial publication is not identified')
                dependency=self._reference(ref,candidates)
                depkey=dependency['metadata']['id']
                if not (set(dependency['metadata']['scope']) & set(scopes)) or not readable(dependency):
                    unknowns.append('required dependency outside requested or authorized projection')
                    continue
                # Pinned historical bytes, never silently substitute the latest body.
                closure(depkey,bundle,dependency,candidates,historical_focus)
        required={}
        for key in mandatory: closure(key,required)
        for ref in forced:
            target = self._reference(ref, records)
            if not set(target['metadata']['scope']) & set(scopes) or not readable(target):
                raise PermissionError('focus outside requested or authorized projection')
            closure(ref['id'], required, target, historical_focus=target['digest'] != records.get(ref['id'], {}).get('digest'))
        from .context_insights import related_candidates, context_insights
        def authorized_exact(ref):
            target = self._reference(ref, records)
            self._query_readable(target, records, policy, scopes)
            return target
        if not action_requirements:
            related = related_candidates(list(required.values()) + [eligible[key] for key in ranked],
                eligible, realm_id=realm['id'], resolve_reference=authorized_exact)
            ranked = sorted(set(ranked) | (set(related['ids']) - set(mandatory)),
                            key=lambda key: (key not in related['ids'], -relevance(key), key))
        cost=lambda bundle:sum(len(self.codec.encode(r['metadata'],r['body'])) for r in bundle.values())
        if cost(required)>budget:
            blocked=True; unknowns.append(('required rules or selected material' if forced else 'mandatory constraints')+' exceed byte budget; narrow scope or increase budget')
        else:
            selected.update(required);used=cost(required)
            for key in ranked:
                bundle={};closure(key,bundle)
                size=cost(bundle)
                if used+size>budget: omitted.append(key);continue
                selected.update(bundle);used+=size
        conflicts=[]
        for key in sorted(governing):
            for ref in self._links(records[key]['metadata'],'conflicts'):
                resolved=self._reference(ref,records);target=resolved['metadata']['id']
                if target in governing and resolved['digest']==records[target]['digest']: conflicts.append(sorted([key,target]))
        if conflicts: blocked=True
        if unknowns: blocked=True
        result=[]
        for key,r in selected.items():
            m=r['metadata'];known=m['kind'] in KINDS
            result.append({'id':m['id'],'metadata':m,'body':r['body'],'digest':r['digest'],'governs':key in governing and known,'mandatory':key in mandatory,'source_content':m['kind']=='source','inert':not known,'serialization_warnings':r.get('serialization_warnings',[])})
        if action_requirements:
            incomplete = bool(blocked or unknowns or reading_unknowns)
            projection = {'schema': 'ekk.context-projection/0.1', 'kind': selection,
                          'complete': not incomplete, 'optional_reading': 'excluded',
                          'coverage': 'all applicable governing commitments and explicit grounds with their dependency closure'}
            return {'schema': 'ekk.context/0.1', 'blocked': blocked, 'scopes': sorted(scopes),
                    'task': '', 'records': result, 'conflicts': conflicts,
                    'unknowns': sorted(set(unknowns)), 'warnings': sorted(reading_unknowns),
                    'manifest': {'realm_id': realm['id'],
                        'snapshots': [{'realm_id': realm['id'], 'revision': snapshot['revision']}],
                        'principal': self.principal, 'policy_digest': digest(snapshot['files'][CONTROL[1]]),
                        'packs_digest': digest(snapshot['files'][CONTROL[2]]), 'packs': packs.get('packages', []),
                        'projection': projection, 'forced_refs': forced,
                        'used_refs': [{'id': r['id'], 'revision': r['metadata']['revision'], 'digest': r['digest']} for r in result],
                        'freshness': {'snapshot': snapshot['revision'], 'assembled_at': now, 'external_sources': 'unknown'},
                        'incomplete': incomplete, 'omitted': [], 'budget_scope': 'canonical_record_bytes',
                        'budget_bytes': budget, 'used_bytes': used},
                    'authority_note': 'Sufficiency covers the declared action grounds and applicable governing commitments, not all knowledge, truth or execution permission. Advisory discovery is not performed.'}
        insights = context_insights(result, eligible, realm_id=realm['id'],
            resolve_reference=authorized_exact,
            incomplete=related['incomplete'] or bool(set(related['ids']) & set(omitted)))
        return {'schema':'ekk.context/0.1','blocked':blocked,'scopes':sorted(scopes),'task':task,'records':result,'insights':insights,'conflicts':conflicts,'unknowns':sorted(set(unknowns)),'warnings':sorted(reading_unknowns), 'manifest':{'realm_id':realm['id'],'snapshots':[{'realm_id':realm['id'],'revision':snapshot['revision']}],'principal':self.principal,'policy_digest':digest(snapshot['files'][CONTROL[1]]),'packs_digest':digest(snapshot['files'][CONTROL[2]]),'packs':packs.get('packages',[]),**({'forced_refs':forced} if forced else {}),'used_refs':[{'id':r['id'],'revision':r['metadata']['revision'],'digest':r['digest']} for r in result],'freshness':{'snapshot':snapshot['revision'],'assembled_at':now,'external_sources':'unknown'},'source_search':{'encoding':'UTF-8','max_bytes_per_asset':1048576,'scan_budget_bytes':source_scan_limit,'scanned_bytes':source_scan_bytes,'omitted_or_partial_assets':len(source_search_omitted)},'incomplete':bool(omitted or unknowns or reading_unknowns or blocked or insights['incomplete'] or source_search_omitted),'omitted':omitted,'budget_scope':'canonical_record_bytes','budget_bytes':budget,'used_bytes':used,'insights_budget_bytes':insights['byte_budget']},'authority_note':'All statements are fallible recorded content. Acceptance is local authority, not truth or execution permission. Scopes filter output, not filesystem access.'}

    def review(self, scopes):
        snapshot=self.store.snapshot();_,policy,_,records=self._validate(snapshot)
        self._authorized(policy,'read',scopes)
        accepted=self._acceptances(snapshot,records); now=self._now(); candidates=[];unregistered=[];unknowns=[]
        for key in sorted(accepted):
            m=records[key]['metadata']
            if not set(m['scope']) & set(scopes):continue
            try:self._authorized(policy,'read',m['scope'])
            except PermissionError:
                unknowns.append('applicable review subject outside authorized projection');continue
            try:
                for ref in self._refs(m):self._authorized(policy,'read',self._reference(ref,records)['metadata']['scope'])
            except PermissionError:
                unknowns.append('review dependency outside authorized projection');continue
            review=m.get('review',{})
            unregistered.extend({'id':key,'condition':condition} for condition in review.get('when',[]))
            if review.get('due_at') and self._time(review['due_at'])<=self._time(now):candidates.append({'id':key,'detector':'due_at','reasons':['selected review date reached'],'disposition':'requires contextual decision'})
            triggers=review.get('triggers',[])
            for trigger in triggers:
                kind=trigger if isinstance(trigger,str) else trigger.get('detector')
                reasons=[]
                if kind=='expired':
                    if m.get('valid_until') and self._time(m['valid_until'])<=self._time(now): reasons=['validity expired']
                elif kind=='changed_basis':
                    for ref in self._links(m,'basis'):
                        item={'id':ref} if isinstance(ref,str) else ref
                        current=records.get(item['id'])
                        if current and ((item.get('digest') and self._hash(item['digest'])!=current['digest']) or (item.get('revision') and item['revision']!=current['metadata']['revision'])): reasons.append('pinned basis has a newer revision')
                elif kind=='failed_expectation':
                    for outcome in records.values():
                        om=outcome['metadata']
                        try:self._authorized(policy,'read',om['scope'])
                        except PermissionError:continue
                        o=om.get('outcome',{})
                        if om['kind']=='outcome' and set(om['scope']) & set(scopes) and o.get('decision')==key and o.get('verdict') in ('not_met','unknown'):
                            reasons.append('recorded expectation '+o['verdict'])
                elif kind=='observation_gap':
                    if not isinstance(trigger,dict):
                        unregistered.append({'id':key,'condition':trigger});continue
                    if trigger.get('starts_at') and self._time(now)<self._time(trigger['starts_at']):continue
                    required=set(trigger.get('aspects',[]));latest={}
                    for observation in records.values():
                        om=observation['metadata'];profile=om.get('observation',{})
                        if om['kind']!='observation' or profile.get('subject')!=key:continue
                        if not set(m['scope']) <= set(om['scope']) or not self._links(om,'basis'):continue
                        try:
                            self._authorized(policy,'read',om['scope'])
                            self._read_basis(om,records,policy)
                        except (PermissionError,ValueError):continue
                        observed_at=self._time(profile['observed_at'])
                        if observed_at>self._time(now):continue
                        if trigger.get('starts_at') and observed_at<self._time(trigger['starts_at']):continue
                        for aspect in required & set(profile.get('aspects',[])):
                            latest[aspect]=max(observed_at,latest.get(aspect,observed_at))
                    max_age=trigger['max_age_days']*86400
                    missing=sorted(required-set(latest))
                    stale=sorted(aspect for aspect,moment in latest.items() if (self._time(now)-moment).total_seconds()>max_age)
                    if missing:reasons.append('unobserved aspects: '+', '.join(missing))
                    if stale:reasons.append('stale observations: '+', '.join(stale))
                else: unregistered.append({'id':key,'condition':trigger});continue
                if reasons:candidates.append({'id':key,'detector':kind,'reasons':sorted(set(reasons)),'disposition':'requires contextual decision'})
        return {'schema':'ekk.review/0.1','revision':snapshot['revision'],'candidates':candidates,'unregistered_conditions':unregistered,'unknowns':sorted(set(unknowns)),'incomplete':bool(unknowns),'mutations':0,'scheduler':False}

    def assurance(self, scopes):
        """Report independent lifecycle dimensions without inferring truth or causality."""
        snapshot=self.store.snapshot();_,policy,_,records=self._validate(snapshot)
        self._authorized(policy,'read',scopes);accepted=self._acceptances(snapshot,records);items=[]
        for key in sorted(records):
            m=records[key]['metadata']
            if m['kind'] not in ('decision','policy') or not set(m['scope']) & set(scopes):continue
            try:self._authorized(policy,'read',m['scope'])
            except PermissionError:continue
            declared=m.get('assurance',{})
            def dimension(name,default):
                value=declared.get(name,{'status':default,'basis':[]})
                try:
                    self._read_basis({'basis':value.get('basis',[])},records,policy)
                except PermissionError:
                    return {'status':'unknown','basis':[],'claim_source':'unavailable','unknown_reason':'basis outside authorized projection'}
                return {'status':value['status'],'basis':value.get('basis',[]),'claim_source':'recorded_assertion' if name in declared else 'absent',
                        'scope_of_claim':value.get('scope_of_claim','Not specified; no broader guarantee inferred.')}
            items.append({'id':key,
                'owner_authorized':{'status':'accepted' if key in accepted else 'unaccepted','receipt_id':accepted.get(key,{}).get('id')},
                'evidence_supported':dimension('evidence','unknown'),
                'implementation_verified':dimension('implementation','not_run'),
                'observed_benefit':dimension('benefit','unknown')})
        return {'schema':'ekk.assurance/0.1','revision':snapshot['revision'],'items':items,'limitations':['Recorded assertions and provenance do not establish truth or causality.','Unobserved aspects remain unknown.'],'mutations':0}

    def export(self, ids, *, destination, grants):
        if not ids or not destination or not grants: raise PermissionError('explicit IDs, destination and policy grant selection required')
        snapshot=self.store.snapshot();realm,policy,_,records=self._validate(snapshot)
        # Caller selects grant IDs; only published governance supplies their authority.
        if not isinstance(grants,list) or any(not isinstance(g,(str,dict)) for g in grants):raise ValueError('grant IDs must be a list')
        selected={g if isinstance(g,str) else g.get('id') for g in grants}
        if any(not isinstance(g,str) or not g for g in selected):raise ValueError('nonempty grant IDs required')
        authorized=[g for g in policy.get('export_grants',[]) if g.get('id') in selected and g.get('principal')==self.principal and g.get('destination')==destination]
        if selected!={grant['id'] for grant in authorized}:raise PermissionError('selected export grant unavailable for principal or destination')
        files={}; refs=[];used_grants=set()
        for key in sorted(set(ids)):
            r=records[key];m=r['metadata']
            self._authorized(policy,'read',m['scope'])
            for ref in self._refs(m):self._authorized(policy,'read',self._reference(ref,records)['metadata']['scope'])
            visibility=m.get('classification',realm['default_classification'])
            matches=[g for g in authorized if key in g.get('ids',[]) and g.get('source_visibility')==visibility and g.get('destination_visibility') and (g['destination_visibility']==visibility or g.get('declassify') is True)]
            if not matches:raise PermissionError('no explicit export grant for selected record and classification')
            used_grants.update(grant['id'] for grant in matches)
            files[r['path']]=base64.b64encode(snapshot['files'][r['path']]).decode()
            source=m.get('source',{})
            for asset in source.get('assets',[]):
                if not any(asset['path'] in g.get('source_paths',[]) for g in matches):raise PermissionError('source bytes require explicit export allowlist')
                files[asset['path']]=base64.b64encode(snapshot['files'][asset['path']]).decode()
            refs.append({'id':key,'revision':m['revision'],'digest':r['digest'],'classification':visibility})
        return {'schema':'ekk.export/0.1','origin_realm':realm['id'],'origin_snapshot':snapshot['revision'],'destination':destination,'policy_digest':digest(snapshot['files'][CONTROL[1]]),'grant_ids':sorted(used_grants),'records':refs,'files':files,'authority':'reference only; import requires local adoption'}
