"""Work items are ordinary owner-held records; no parallel knowledge database."""
from copy import deepcopy
from ..application.work import work_projection
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

    def show(self, reference):
        snapshot, realm, policy, records, row = self._row(reference)
        events=[];unavailable=0
        work=row['metadata']['work']
        for ref in work.get('events',[]):
            try:
                if ref['realm']!=realm['id']:raise PermissionError('Event belongs to another realm')
                event=self.app._reference(ref,records)
                self.app._query_readable(event,records,policy,self.scopes)
                marker=event['metadata'].get('work_event',{})
                if marker.get('work_id') != row['metadata']['id']:raise ValueError('Unrelated work event')
                events.append({'reference':ref,'kind':marker['kind'],'body':event['body']})
            except (ValueError,KeyError,OSError):unavailable+=1
        result=work_projection(reference,row['metadata']['title'],work,events,unavailable=unavailable)
        result['earlier_events']=max(0,work.get('event_count',0)-len(work.get('events',[])))
        result['snapshot']=snapshot['revision']
        return result

    def find(self, query, *, limit=10):
        hits=self.app.search_records(self.scopes,query=query,limit=limit,match='ranked',work_only=True)
        results=[]
        for hit in hits['results']:
            work=hit['work']
            results.append({'title':hit['title'],'reference':hit['reference'],'status':work['status'],
                            'intention':work['intention'],'next_step':work.get('next_step','')})
        return {'schema':'ekk.work-search/0.1','results':results[:limit],
                'incomplete':hits['incomplete'] or len(results)>limit,'snapshot':hits['snapshot']}
