"""Work items are ordinary owner-held records; no parallel knowledge database."""
from copy import deepcopy
from ..application.work import work_projection
from ..application.workspace import exact_reference
from .context_display import work_navigation_argv
from ..application.discovery import terms, rank
from ..model import Conflict, digest
from .retention import _once


class RealmWorkRepository:
    def __init__(self, app, scopes):self.app, self.scopes = app, list(scopes)

    def _row(self, reference):
        snapshot, realm, policy, records = self.app._query_view(self.scopes)
        if reference['realm'] != realm['id']:raise PermissionError('Work belongs to another realm')
        row = self.app._reference(reference, records)
        self.app._query_readable(row, records, policy, self.scopes)
        if row['metadata'].get('work', {}).get('schema') != 'ekk.work/0.1':raise ValueError('Not an EKK work item')
        return snapshot, realm, policy, records, row

    def save(self, *, title, fields, key, previous=None, event=None):
        app = self.app
        request = [title, fields, previous, event, self.scopes]
        def build():
            snapshot, realm, policy, records = app._query_view(self.scopes)
            app._authorized(policy, 'write', self.scopes)
            roots = app._roots(realm)['record_roots']
            root = 'records' if 'records' in roots else roots[0]
            changes = {}
            if previous:
                if previous['realm'] != realm['id']:raise PermissionError('Work belongs to another realm')
                old = records.get(previous['id'])
                if old is None or app._query_reference(realm['id'],old) != previous:
                    raise Conflict('Work changed; read current work and reconsider the update')
                app._query_readable(old, records, policy, self.scopes)
                metadata = deepcopy(old['metadata'])
                if metadata.get('work',{}).get('schema') != 'ekk.work/0.1':raise ValueError('Not an EKK work item')
                metadata['revision'] += 1
                metadata['supersedes'] = [previous]
                if title is not None:metadata['title'] = title
                path = old['path']
            else:
                metadata = app._meta('note', title, self.scopes,
                    work={'schema':'ekk.work/0.1','status':'open','domain':'general','events':[]},
                    retention={'schema':'ekk.retained-result/0.1','claim_source':'authored_work'})
                path = f"{root}/{metadata['id']}.md"
            work = metadata['work']
            work.update(deepcopy(fields))
            metadata['aliases'] = work.get('aliases', [])
            work['updated_at'] = app._now()
            if event:
                # Navigation to a work item does not become an ever-growing
                # dependency closure. Explicit evidence remains strong basis.
                for ref in event['basis']:
                    if ref['realm'] != realm['id']:raise PermissionError('Evidence needs an explicitly authorized local source')
                    source=app._reference(ref,records)
                    app._query_readable(source,records,policy,self.scopes)
                event_meta = app._meta('outcome' if event['kind']=='result' else 'observation',
                    metadata['title'] + ': ' + event['kind'], metadata['scope'], basis=event['basis'],
                    work_event={'schema':'ekk.work-event/0.1','work_id':metadata['id'],'kind':event['kind']})
                if event.get('improvement'):event_meta['improvement']=deepcopy(event['improvement'])
                raw = app.codec.encode(event_meta,event['body'])
                event_ref = {'realm':realm['id'],'id':event_meta['id'],'revision':1,'digest':'sha256:'+digest(raw)}
                changes[f"{root}/{event_meta['id']}.md"] = raw
                work['events'] = [*work.get('events',[]),event_ref][-64:]
                work['event_count'] = work.get('event_count',0)+1
            body = '\n\n'.join(x for x in [work['intention'],work.get('direction'),work.get('next_step')] if x)
            changes[path] = app.codec.encode(metadata,body)
            return app._propose(changes,snapshot)
        # The established durable request journal freezes generated IDs/bytes.
        # Its additive rebase explicitly refuses work edits, preserving CAS.
        return _once(app,operation='work',fingerprint=lambda identity:[identity,'work',request],
                     build=build,scopes=self.scopes,key=key)

    def _events(self, row, realm, policy, records):
        """Only the bounded, exact linked events under today's read authority."""
        events=[];unavailable=0
        work=row['metadata']['work']
        references=work.get('events',[])
        for ref in references[-64:]:
            try:
                ref=exact_reference(ref)
                if ref['realm']!=realm['id']:raise PermissionError('Event belongs to another realm')
                event=self.app._reference(ref,records)
                self.app._query_readable(event,records,policy,self.scopes)
                marker=event['metadata'].get('work_event',{})
                if marker.get('schema') != 'ekk.work-event/0.1' or marker.get('work_id') != row['metadata']['id']:
                    raise ValueError('Unrelated work event')
                candidates=records
                historic=event.get('snapshot_revision')
                if historic and candidates and historic!=next(iter(candidates.values())).get('snapshot_revision'):
                    candidates=self.app._load(self.app.store.snapshot(historic),historical=True)[-1]
                basis=[self.app._query_reference(realm['id'],self.app._reference(ground,candidates))
                    for ground in event['metadata'].get('basis',[])]
                events.append({'reference':deepcopy(ref),'kind':marker['kind'],'body':event['body'],
                    'basis':basis,
                    **({'improvement':deepcopy(event['metadata']['improvement'])} if event['metadata'].get('improvement') else {})})
            except (PermissionError,ValueError,KeyError,OSError):unavailable+=1
        earlier=max(0, max(work.get('event_count',0),len(references))-min(64,len(references)))
        return events,unavailable,earlier

    def show(self, reference):
        snapshot, realm, policy, records, row = self._row(reference)
        work=row['metadata']['work']
        events,unavailable,earlier=self._events(row,realm,policy,records)
        result=work_projection(reference,row['metadata']['title'],work,events,unavailable=unavailable)
        result['earlier_events']=earlier
        result['incomplete']=bool(unavailable or earlier)
        current=records.get(row['metadata']['id'])
        historical=current is None or current['digest']!=row['digest']
        current_ref=None
        if historical and current is not None:
            try:self.app._query_readable(current,records,policy,self.scopes)
            except (PermissionError,ValueError,KeyError,OSError):pass
            else:current_ref=self.app._query_reference(realm['id'],current)
        result['historical']=historical
        result['navigation']=work_navigation_argv(reference,current_ref,historical=historical)
        result['snapshot']=snapshot['revision']
        return result

    def find(self, query, *, limit=10):
        if not isinstance(query,str) or len(query)>2000:raise ValueError('query must be bounded text')
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('limit must be between 1 and 100')
        snapshot,realm,policy,records=self.app._query_view(self.scopes)
        query_terms=terms(query)
        results=[];unavailable=earlier=scanned=0
        for row in records.values():
            metadata=row['metadata'];work=metadata.get('work',{})
            if work.get('schema')!='ekk.work/0.1' or not set(metadata['scope']) & set(self.scopes):continue
            try:self.app._query_readable(row,records,policy,self.scopes)
            except PermissionError:continue
            events,missing,old=self._events(row,realm,policy,records)
            unavailable+=missing;earlier+=old;scanned+=len(events)
            text='\n'.join([metadata['id'],metadata['title'],*metadata.get('aliases',[]),row['body']])
            matches=[]
            direct=rank(query_terms,[(None,text)],metadata['title'],metadata.get('aliases',[]),'ranked')
            if direct is not None:
                matches.append({'kind':'work',**direct,'why':'matches current work text'})
            if query_terms:
                for event in events:
                    found=rank(query_terms,[(None,event['body'])],'',[],'ranked')
                    if found is not None:
                        matches.append({'kind':'event','reference':event['reference'],**found,
                            'why':'matches a readable exact event linked to this current work'})
            if not matches:continue
            score=max(m['score'] for m in matches)
            results.append({'title':metadata['title'],'reference':self.app._query_reference(realm['id'],row),
                'status':work['status'],'intention':work['intention'],'next_step':work.get('next_step',''),
                'score':score,'matches':matches,'unavailable_events':missing,'earlier_events':old})
        results.sort(key=lambda hit:(-hit['score'],hit['reference']['id']))
        return {'schema':'ekk.work-search/0.1','results':results[:limit],
                'incomplete':bool(unavailable or earlier or len(results)>limit),'snapshot':snapshot['revision'],
                'event_coverage':{'max_events_per_work':64,'readable_events_scanned':scanned,
                    'unavailable_events':unavailable,'earlier_events':earlier,
                    'coverage':'current authorized work and its bounded linked exact events only'}}
