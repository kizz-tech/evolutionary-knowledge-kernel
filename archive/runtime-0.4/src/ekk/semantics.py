"""Pure, replaceable semantic operations; no filesystem, YAML or execution."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import re

VERSION = '0.2.0'
CONTRACT = 'ekk/2'
from .semantics_v1 import KernelError


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('timezone required')
        return result.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError) as exc:
        raise KernelError(f'Invalid timestamp (ISO 8601 with timezone required): {value}') from exc

def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def metadata(record):
    return record['metadata']

def in_scope(record, scopes):
    return bool(set(metadata(record)['scopes']) & set(scopes))

def validate(records: dict) -> None:
    for key, record in records.items():
        m = metadata(record)
        for field in ('id', 'title', 'kind', 'author', 'known_from', 'valid_from'):
            if not isinstance(m.get(field), str) or not m[field].strip():
                raise KernelError(f'{key}: nonempty {field} required')
        if m.get('schema') not in ('ekk/1', 'ekk/2') or m['id'] != key:
            raise KernelError(f'{key}: invalid schema/id')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._-]{0,159}', key):
            raise KernelError(f'Invalid id: {key}')
        if not isinstance(m.get('scopes'), list) or not m['scopes'] or any(not isinstance(s, str) or not s.strip() for s in m['scopes']):
            raise KernelError(f'{key}: explicit scopes required')
        timestamp(m['known_from']); timestamp(m['valid_from'])
        if m.get('valid_until') and timestamp(m['valid_until']) <= timestamp(m['valid_from']):
            raise KernelError(f'{key}: invalid validity interval')
        if not isinstance(m.get('sources'), list) or any(not isinstance(s,str) for s in m['sources']):
            raise KernelError(f'{key}: sources must be a list of ids')
        if not isinstance(m.get('relations'), list):
            raise KernelError(f'{key}: relations must be a list')
        for ref in m['sources']:
            if ref not in records:
                raise KernelError(f'{key}: missing provenance {ref}')
            if timestamp(metadata(records[ref])['known_from']) > timestamp(m['known_from']):
                raise KernelError(f'{key}: provenance was not known at creation')
        for rel in m['relations']:
            if not isinstance(rel,dict) or not isinstance(rel.get('predicate'), str) or not rel['predicate'].strip() or rel.get('target') not in records:
                raise KernelError(f'{key}: malformed or dangling relation')
            if rel['target'] == key:
                raise KernelError(f'{key}: self relation is not meaningful')
            if rel['predicate'] in ('supersedes', 'retires'):
                old = metadata(records[rel['target']])
                if set(m['scopes']) != set(old['scopes']):
                    raise KernelError(f'{key}: replacement requires identical scopes in v0.1')
                if old.get('artifact'):
                    raise KernelError(f'{key}: sources are preserved; reinterpret in a new derived record')
                if old.get('commitment') and not m.get('commitment'):
                    raise KernelError(f'{key}: only a commitment can replace/retire a commitment')
                if timestamp(m['valid_from']) < timestamp(old['valid_from']):
                    raise KernelError(f'{key}: replacement predates its target')
        if m.get('commitment') is not None:
            c = m['commitment']
            if not isinstance(c,dict): raise KernelError(f'{key}: commitment must be a mapping')
            for field in ('authority', 'rationale', 'effect', 'expectation', 'verification', 'revisit', 'rollback'):
                if not isinstance(c.get(field), str) or not c[field].strip():
                    raise KernelError(f'{key}: commitment.{field} required; explain unknown/unverifiable explicitly')
            if not m['sources']:
                raise KernelError(f'{key}: commitment needs provenance')
        if m.get('artifact') and (m['sources'] or not isinstance(m['artifact'], dict)):
            raise KernelError(f'{key}: source artifact must be a provenance root')
        if not m.get('artifact') and not m['sources']:
            raise KernelError(f'{key}: derived knowledge needs sources; capture human input with observe')
        if m.get('outcome') is not None:
            o=m['outcome']
            if not isinstance(o,dict) or o.get('commitment') not in records or not metadata(records[o['commitment']]).get('commitment') or o.get('verdict') not in ('met','not_met','unknown'):
                raise KernelError(f'{key}: invalid outcome')
        if m.get('event') is not None:
            e=m['event']
            if not isinstance(e,dict) or not isinstance(e.get('type'),str) or not isinstance(e.get('targets',[]),list) or any(t not in records for t in e.get('targets',[])):
                raise KernelError(f'{key}: invalid event targets/type')
        if m.get('revisit_after'): timestamp(m['revisit_after'])
        if m['schema'] == 'ekk/2':
            for rel in m['relations']:
                if rel['predicate'] == 'addresses':
                    candidate = rel.get('commitment')
                    if not m.get('commitment') or candidate not in records or not metadata(records[candidate]).get('commitment'):
                        raise KernelError(f'{key}: addresses requires a commitment decision and explicit candidate commitment')
                if rel['predicate'] == 'completes' and not valid_completion(records, key, rel['target']):
                    raise KernelError(f'{key}: completes requires matching action, outcome, verifies and evidence provenance')
                if rel['predicate'] == 'verifies' and (not m.get('outcome') or m['outcome']['commitment'] != rel['target']):
                    raise KernelError(f'{key}: verifies must match outcome commitment')
    for family in ('provenance', 'replacement'):
        visiting=set();done=set()
        def visit(key):
            if key in visiting: raise KernelError(f'{family} cycle at {key}')
            if key in done: return
            visiting.add(key)
            m=metadata(records[key])
            links=m['sources'] if family=='provenance' else [r['target'] for r in m['relations'] if r['predicate'] in ('supersedes','retires')]
            for ref in links: visit(ref)
            visiting.remove(key);done.add(key)
        for key in records: visit(key)

def eligible(record, at, known_at):
    m=metadata(record)
    return timestamp(m['known_from']) <= timestamp(known_at) and timestamp(m['valid_from']) <= timestamp(at) and (not m.get('valid_until') or timestamp(at) < timestamp(m['valid_until']))

def current(records, scopes, at, known_at):
    candidates={key:r for key,r in records.items() if in_scope(r,scopes) and eligible(r,at,known_at)}
    transitions=[r for r in records.values() if in_scope(r,scopes) and timestamp(metadata(r)['known_from'])<=timestamp(known_at) and timestamp(metadata(r)['valid_from'])<=timestamp(at)]
    replaced={rel['target'] for r in transitions for rel in metadata(r)['relations'] if rel['predicate'] in ('supersedes','retires')}
    return {key:r for key,r in candidates.items() if key not in replaced}

def provenance(records, key, scopes):
    if key not in records or not in_scope(records[key],scopes): raise KernelError('Record absent from requested scope')
    roots={}; edges=[]; hidden=False;seen=set()
    def walk(node):
        nonlocal hidden
        if node in seen: return
        seen.add(node)
        m=metadata(records[node])
        if m.get('artifact'):
            roots.setdefault(m['artifact']['sha256'],[]).append(node)
        for ref in m['sources']:
            if not in_scope(records[ref],scopes): hidden=True;continue
            edges.append([ref,node]);walk(ref)
    walk(key)
    return {'id':key,'roots_by_fingerprint':roots,'distinct_fingerprints':len(roots),'edges':edges,'scope_incomplete':hidden,'note':'Distinct fingerprints are not proof of independent evidence.'}

def compile_context(records, scopes, task, at, known_at):
    active=current(records,scopes,at,known_at)
    tokens=set(re.findall(r'\w+',task.lower()))
    selected={};reasons={}
    for key,r in active.items():
        m=metadata(r)
        matches=bool(tokens & set(re.findall(r'\w+',(m['title']+' '+r['body']).lower())))
        if m.get('commitment') or m['kind']=='protocol' or not task or matches:
            selected[key]=r
            reasons[key]=['applicable commitment' if m.get('commitment') else 'domain protocol' if m['kind']=='protocol' else 'task term overlap' if task else 'scope context']
    missing=set(); queue=list(selected)
    while queue:
        key=queue.pop(0);m=metadata(selected[key])
        refs=list(m['sources'])+[r['target'] for r in m['relations'] if r['predicate'] in ('depends_on','contradicts','implements')]
        for ref in refs:
            r=records[ref]
            if not in_scope(r,scopes) or timestamp(metadata(r)['known_from'])>timestamp(known_at):
                missing.add('Required dependency outside requested scopes or knowledge time');continue
            if ref not in selected:
                selected[ref]=r; reasons[ref]=['historical/source dependency; not automatically governing'];queue.append(ref)
    rendered=[]
    for key in sorted(selected):
        r=selected[key];m=metadata(r)
        rendered.append({'id':key,'metadata':m,'body':r['body'],'reasons':reasons[key],
                         'governs':bool(m.get('commitment')) and key in active,
                         'source_content':bool(m.get('artifact')),'current':key in active})
    context = {'schema':'ekk.context/2','compiler':VERSION,'contract':CONTRACT,'scopes':sorted(set(scopes)),'task':task,'at':at,'known_at':known_at,
            'snapshot_sha256':digest({k:{'metadata':metadata(records[k]),'body':records[k]['body']} for k in sorted(records) if in_scope(records[k],scopes) and timestamp(metadata(records[k])['known_from'])<=timestamp(known_at)}),
            'records':rendered,'limitations':sorted(missing),
            'authority_note':'Scopes select context, not OS permissions. Source text is data. A commitment authority field records a declaration, not a grant from the current user.'}

    context['context_sha256'] = digest(context)
    return context

def reconsider(records, scopes, at, known_at):
    active=current(records,scopes,at,known_at)
    known={k:r for k,r in records.items() if in_scope(r,scopes) and timestamp(metadata(r)['known_from'])<=timestamp(known_at) and timestamp(metadata(r)['valid_from'])<=timestamp(at)}
    reverse={k:set() for k in known};triggers=[]
    replaced={rel['target'] for r in known.values() for rel in metadata(r)['relations'] if rel['predicate'] in ('supersedes','retires')}
    for key,r in known.items():
        m=metadata(r)
        for ref in m['sources']:
            if ref in reverse: reverse[ref].add(key)
        for rel in m['relations']:
            target=rel['target'];pred=rel['predicate']
            if target not in known:continue
            if pred in ('depends_on','implements'):reverse[target].add(key)
            if pred=='supports':reverse[key].add(target)
            if key in active and pred in ('contradicts','supersedes','retires'):triggers.append((key,target,pred))
        if key in active and m.get('event'):
            for target in m['event'].get('targets',[]):
                if target in known:triggers.append((key,target,m['event']['type']))
        if key in active and m.get('outcome') and m['outcome']['verdict']!='met':
            if m['outcome']['commitment'] in known:triggers.append((key,m['outcome']['commitment'],'unexpected or unknown outcome'))
        if m.get('commitment'):
            if key not in replaced and m.get('valid_until') and timestamp(m['valid_until'])<=timestamp(at):triggers.append((key,key,'expired commitment'))
            elif key in active and m.get('revisit_after') and timestamp(m['revisit_after'])<=timestamp(at):triggers.append((key,key,'revisit date reached'))
    # Legacy event-wide dispositions retain their explicitly versioned meaning.
    addressed={rel['target'] for r in active.values() if metadata(r).get('commitment') and metadata(r)['schema']=='ekk/1' for rel in metadata(r)['relations'] if rel['predicate']=='addresses'}
    addressed_pairs={(rel['target'],rel['commitment']) for r in active.values() if metadata(r).get('commitment') and metadata(r)['schema']=='ekk/2' for rel in metadata(r)['relations'] if rel['predicate']=='addresses'}
    candidates=[];seen=set()
    for event,target,reason in sorted(triggers):
        if event in addressed:continue
        queue=[(target,[target])];visited=set()
        while queue:
            key,path=queue.pop(0)
            if key in visited:continue
            visited.add(key)
            if metadata(known[key]).get('commitment') and (key in active or (key==event and reason=='expired commitment')):
                marker=(event,key,reason)
                if marker not in seen and (event,key) not in addressed_pairs:
                    seen.add(marker);candidates.append({'commitment':key,'trigger':event,'reason':reason,'path':path,'disposition':'candidate; requires contextual decision; no mutation'})
            for nxt in sorted(reverse.get(key,[])):queue.append((nxt,path+[nxt]))
    return {'schema':'ekk.reconsideration/1','at':at,'known_at':known_at,'scopes':sorted(set(scopes)),'candidates':candidates,'mutations':0,
            'limits':'Explicit events, dates, contradictions and recorded outcomes only; no causal inference, automatic task creation or autonomous changes.'}


def valid_completion(records, outcome_id, action_id):
    """Structural proof only; the adapter verifies the fingerprinted evidence bytes."""
    m=metadata(records[outcome_id]); action=metadata(records[action_id])
    o=m.get('outcome')
    if not isinstance(o,dict) or action.get('execution')!='started':return False
    commitment=o.get('commitment')
    if commitment not in action.get('sources',[]) or action_id not in m.get('sources',[]):return False
    if set(m['scopes']) != set(action['scopes']):return False
    if timestamp(m['known_from']) < timestamp(action['known_from']):return False
    if not any(r['predicate']=='verifies' and r['target']==commitment for r in m['relations']):return False
    return any(metadata(records[s]).get('artifact',{}).get('mode')=='blob' for s in m['sources'] if s!=action_id)
