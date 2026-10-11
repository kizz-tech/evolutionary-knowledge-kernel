"""Exact continuation and bounded event discovery under current authority."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.adapters.work_repository import RealmWorkRepository
from ekk.adapters.context_display import brief_context
from ekk.application import RealmService
from ekk.application.work import WorkService
from ekk.application.improvement import improvement
from ekk.application.workspace import WorkspaceService


class WorkNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        env=patch.dict(os.environ,{'EKK_DATA_HOME':str(root/'data'), 'EKK_CACHE_HOME':str(root/'cache'), 'EKK_CONFIG_HOME':str(root/'config')})
        env.start();self.addCleanup(env.stop)
        self.app=RealmService(GitStore(root/'realm',root/'runtime'),'owner',codec=MarkdownCodec())
        self.app.init('Isolated navigation',realm_id='realm:test',context_id='scope')
        self.repo=RealmWorkRepository(self.app,['scope'])
        self.work=WorkService(self.repo)

    def start(self,title='Investigate failure'):
        return self.work.start(title=title,fields={'intention':'Investigate failure','next_step':'Collect initial evidence'},key='start-'+title)['result_reference']

    def replace_metadata(self,ref,change):
        row=self.app._load(self.app.store.snapshot())[-1][ref['id']]
        meta=deepcopy(row['metadata']);meta['revision']+=1;change(meta)
        self.app.apply(self.app.propose({row['path']:self.app.codec.encode(meta,row['body'])}),idempotency_key='change-'+ref['id']+str(meta['revision']))
        return self.app._query_reference('realm:test',self.app._load(self.app.store.snapshot())[-1][ref['id']])

    def add_scope(self):
        meta={'schema':'ekk.record/0.1','id':'other','title':'Other','kind':'context','context':{'purpose':'Other'},'scope':['other'],'revision':1,'created_at':'2026-10-05T00:00:00Z','created_by':'owner'}
        self.app.apply(self.app.propose({'records/other.md':self.app.codec.encode(meta,'')}),idempotency_key='scope-other')

    def test_historical_entry_preserves_old_bytes_and_exact_separate_navigation(self):
        old=self.start()
        current=self.work.update(reference=old,fields={'next_step':'Apply verified repair','status':'completed'},key='complete')['result_reference']
        before=self.app.store.snapshot()['revision']
        workspace=WorkspaceService(lambda:[{'realm_id':'realm:test','realm_alias':'test','owner_projection':'shared','scopes':['scope'],'context':self.app.context}])
        projection=workspace.start(task='unmatched',resume=old)['contexts'][0]
        historical=next(row for row in projection['records'] if row['digest']==old['digest'].removeprefix('sha256:'))
        self.assertEqual(historical['body'],'Investigate failure\n\nCollect initial evidence')
        self.assertEqual(historical['metadata']['work']['status'],'open')
        self.assertTrue(historical['historical'])
        self.assertEqual(historical['current_reference'],current)
        view=next(row for row in projection['work_view']['work_items'] if row['reference']==old)
        self.assertEqual(view['navigation']['status_provenance'],'selected_historical_revision')
        brief=brief_context(projection)
        item=next(item for item in brief['items'] if item.get('ref')==old)
        self.assertEqual(json.loads(item['navigation']['selected']['argv'][-1]),old)
        self.assertEqual(json.loads(item['navigation']['current']['argv'][-1]),current)
        self.assertEqual(item['continuation']['next_step'],'Collect initial evidence')
        self.assertIn('historical',item['navigation']['warning'])
        self.assertNotIn('id',item)
        self.assertEqual(self.app.store.snapshot()['revision'],before)
        self.assertEqual(self.work.show(reference=old)['navigation']['current']['reference'],current)
        self.assertFalse(self.work.show(reference=current)['historical'])
        with self.assertRaises(ValueError):self.work.show(reference={**old,'digest':'sha256:'+'0'*64})

    def test_current_navigation_does_not_expose_out_of_scope_current_reference(self):
        self.add_scope();old=self.start()
        self.replace_metadata(old,lambda meta:meta.update(scope=['other']))
        context=self.app.context(['scope'],focus=[old],task='unmatched')
        row=next(row for row in context['records'] if row['id']==old['id'])
        self.assertTrue(row['historical']);self.assertTrue(row['current_unavailable'])
        self.assertNotIn('current_reference',row)
        self.assertNotIn('current',self.work.show(reference=old)['navigation'])

    def test_event_only_query_returns_current_parent_and_exact_event(self):
        old=self.start()
        current=self.work.event(reference=old,kind='observation',body='Unique finding: quasarzeta occurs in the failure.',key='observe')['result_reference']
        event=self.work.show(reference=current)['events'][0]['reference']
        # A subsequent work revision must not turn the event hit into a stale parent.
        newest=self.work.update(reference=current,fields={'status':'completed'},key='close')['result_reference']
        result=self.work.find(query='quasarzeta')
        self.assertFalse(result['incomplete']);self.assertEqual(len(result['results']),1)
        hit=result['results'][0];self.assertEqual(hit['reference'],newest)
        self.assertEqual(hit['matches'][0]['reference'],event)
        self.assertIn('quasarzeta',hit['matches'][0]['excerpt'])
        self.assertEqual(self.work.find(query='Investigate')['results'][0]['reference'],newest)
        self.assertEqual(self.work.find(query='absent')['results'],[])

    def test_exact_event_version_is_matched_and_basis_annotations_are_readable(self):
        basis=self.start('Grounds')
        parent=self.start()
        annotation=improvement({'episode':'Episode 1','source':'observed_runtime','observation':'Recorded claim only',
            'stage':'unknown','target':{'kind':'component','owner':'local runtime','locator':'search'},
            'change':'Candidate repair','disposition':'candidate'})
        parent=self.repo.save(title=None,fields={},key='observed',previous=parent,event={'kind':'observation','body':'Original quasarzeta lesson','basis':[basis],'improvement':annotation})['result_reference']
        event=self.work.show(reference=parent)['events'][0]
        self.assertEqual(event['basis'],[basis]);self.assertEqual(event['improvement'],annotation)
        # The event's selected immutable version remains searchable after revision.
        self.replace_metadata(event['reference'],lambda meta:meta.update(title='New event version'))
        hit=self.work.find(query='quasarzeta')['results'][0]
        self.assertEqual(hit['matches'][0]['reference'],event['reference'])

    def test_unrelated_unavailable_and_earlier_events_report_limits_even_without_hits(self):
        first=self.start('First');second=self.start('Second')
        first=self.work.event(reference=first,kind='observation',body='secret quasarzeta',key='first-event')['result_reference']
        event=self.work.show(reference=first)['events'][0]['reference']
        missing={**event,'id':'missing','digest':'sha256:'+'0'*64}
        second=self.replace_metadata(second,lambda meta:meta['work'].update(events=[event,missing],event_count=70))
        result=self.work.find(query='absent')
        self.assertEqual(result['results'],[]);self.assertTrue(result['incomplete'])
        self.assertEqual(result['event_coverage']['unavailable_events'],2)
        self.assertEqual(result['event_coverage']['earlier_events'],68)
        shown=self.work.show(reference=second)
        self.assertEqual(shown['events'],[]);self.assertTrue(shown['incomplete'])

    def test_event_dependencies_and_current_authority_are_enforced(self):
        self.add_scope()
        private=RealmWorkRepository(self.app,['other'])
        ground=WorkService(private).start(title='Private',fields={'intention':'private'},key='private')['result_reference']
        parent=self.start()
        parent=self.work.event(reference=parent,kind='observation',body='private quasarzeta',key='event')['result_reference']
        event=self.work.show(reference=parent)['events'][0]['reference']
        changed=self.replace_metadata(event,lambda meta:meta.update(basis=[ground]))
        parent=self.replace_metadata(parent,lambda meta:meta['work'].update(events=[changed]))
        found=self.work.find(query='quasarzeta')
        self.assertEqual(found['results'],[]);self.assertTrue(found['incomplete'])
        self.assertEqual(self.work.show(reference=parent)['unavailable_events'],1)
        denied=RealmWorkRepository(RealmService(self.app.store,'ungranted',codec=MarkdownCodec()),['scope'])
        with self.assertRaises(PermissionError):denied.find('quasarzeta')

    def test_cross_realm_and_nonexact_event_links_are_unavailable_not_navigation(self):
        parent=self.start()
        parent=self.work.event(reference=parent,kind='observation',body='quasarzeta',key='event')['result_reference']
        event=self.work.show(reference=parent)['events'][0]['reference']
        parent=self.replace_metadata(parent,lambda meta:meta['work'].update(
            events=[{**event,'realm':'realm:other'}, {'realm':'realm:test','id':event['id']}],event_count=2))
        result=self.work.find(query='quasarzeta')
        self.assertEqual(result['results'],[]);self.assertTrue(result['incomplete'])
        self.assertEqual(result['event_coverage']['unavailable_events'],2)
        self.assertEqual(self.work.show(reference=parent)['events'],[])

    def test_more_than_64_linked_events_are_bounded_without_hidden_complete_claim(self):
        parent=self.start()
        parent=self.work.event(reference=parent,kind='observation',body='bounded quasarzeta',key='event')['result_reference']
        event=self.work.show(reference=parent)['events'][0]['reference']
        parent=self.replace_metadata(parent,lambda meta:meta['work'].update(events=[event]*65,event_count=65))
        result=self.work.find(query='absent')
        self.assertEqual(result['event_coverage']['readable_events_scanned'],64)
        self.assertEqual(result['event_coverage']['earlier_events'],1)
        self.assertTrue(result['incomplete'])
        self.assertEqual(len(self.work.show(reference=parent)['events']),64)
        for args in ({'query':'x'*2001},{'query':'x','limit':False},{'query':'x','limit':101}):
            with self.assertRaises(ValueError):self.work.find(**args)


if __name__=='__main__':unittest.main()
