"""Integrity and recovery contracts for real-work continuity, not benefit trials."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.application.work import WorkService
from ekk.adapters.work_repository import RealmWorkRepository
from ekk.adapters.operational_store import OperationalStore
from ekk.adapters.authored_sources import AuthoredSources
from ekk.adapters.derived_cache import DerivedCache
from ekk.adapters.context_display import brief_context
from ekk.model import Conflict, IdempotencyConflict


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.env=patch.dict(os.environ,{'EKK_DATA_HOME':str(self.root/'data')})
        self.env.start();self.addCleanup(self.env.stop)
        self.app=RealmService(GitStore(self.root/'realm',self.root/'runtime'),'owner',codec=MarkdownCodec())
        self.app.init('Work',realm_id='realm:test',context_id='scope')
        self.work=WorkService(RealmWorkRepository(self.app,['scope']))

    def test_continuation_is_versioned_and_retries_do_not_duplicate(self):
        request={'title':'Product direction','fields':{'intention':'Improve the platform','aliases':['EKK roadmap']},'key':'new'}
        first=self.work.start(**request);ref=first['result_reference']
        self.assertEqual(first['retention']['state'],'read_back_and_discoverable')
        self.assertEqual(self.work.start(**request)['result_reference'],ref)
        self.assertEqual(self.work.find(query='EKK next release')['results'][0]['reference'],ref)
        changed=self.work.event(reference=ref,kind='result',body='The first change is available.',key='result',
                                fields={'next_step':'Observe actual use'})['result_reference']
        current=self.work.show(reference=changed)
        self.assertEqual(current['events'][0]['kind'],'result')
        self.assertEqual(current['next_step'],'Observe actual use')
        self.assertEqual(self.work.show(reference=ref)['events'],[])
        with self.assertRaises(Conflict):self.work.update(reference=ref,fields={'status':'completed'},key='stale')
        denied=WorkService(RealmWorkRepository(RealmService(self.app.store,'other',codec=MarkdownCodec()),['scope']))
        with self.assertRaises(PermissionError):denied.show(reference=changed)

    def test_lost_publication_response_reconciles_exact_work(self):
        store=OperationalStore(self.root/'operations',realm='realm:test',principal='owner');self.addCleanup(store.close)
        request={'title':'One work','fields':{'intention':'One durable result'},'key':'one'}
        store.enqueue('one',request,['scope'])
        def crash(payload,key):
            self.work.start(**payload)
            raise KeyboardInterrupt('response lost after publication')
        with self.assertRaises(KeyboardInterrupt):store.drain(['scope'],crash)
        self.assertEqual(store.status(['scope'])['operations'][0]['state'],'publishing')
        result=store.drain(['scope'],lambda payload,key:self.work.start(**payload))
        self.assertEqual(result['operations'][0]['state'],'read_back_and_discoverable')
        self.assertEqual(len(self.work.find(query='One work')['results']),1)

    def test_fast_local_authorization_rejects_malformed_or_revoked_grants(self):
        from ekk.adapters.activity_cli import authorize_controls
        snapshot=self.app.store.snapshot()
        policy=self.app.codec.load_yaml(snapshot['files']['.ekk/governance.yaml'])
        for grants in ([{'principal':'owner','actions':'read,write','scopes':['scope']}],
                       [{'principal':'owner','actions':['read'],'scopes':'scope'}],
                       [{'principal':'owner','actions':['read','unknown'],'scopes':['scope']}]):
            policy['grants']=grants
            candidate={**snapshot,'files':{**snapshot['files'],'.ekk/governance.yaml':self.app.codec.dump_yaml(policy)}}
            with patch.object(self.app.store,'snapshot',return_value=candidate):
                with self.assertRaises(ValueError):authorize_controls(self.app,['scope'],write=True)
        policy['grants']=[{'principal':'owner','actions':['read'],'scopes':['scope']}]
        candidate={**snapshot,'files':{**snapshot['files'],'.ekk/governance.yaml':self.app.codec.dump_yaml(policy)}}
        with patch.object(self.app.store,'snapshot',return_value=candidate):
            with self.assertRaises(PermissionError):authorize_controls(self.app,['scope'],write=True)


class LocalOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.store=OperationalStore(self.root/'ops',realm='realm:test',principal='owner');self.addCleanup(self.store.close)

    def test_queue_frozen_keys_private_scopes_and_backup(self):
        self.store.enqueue('one',{'body':'exact'},['scope'])
        with self.assertRaises(IdempotencyConflict):self.store.enqueue('one',{'body':'changed'},['scope'])
        self.assertEqual(self.store.status(['other'])['operations'],[])
        receipt=self.store.backup(self.root/'backup.sqlite')
        self.assertEqual(receipt['sha256'],hashlib.sha256((self.root/'backup.sqlite').read_bytes()).hexdigest())
        import sqlite3
        db=sqlite3.connect(self.root/'backup.sqlite')
        self.assertEqual(db.execute('SELECT state FROM outbox').fetchone()[0],'local_pending');db.close()
        self.assertEqual((self.root/'backup.sqlite').stat().st_mode & 0o077,0)
        restored=OperationalStore.restore(self.root/'backup.sqlite',self.root/'restored',expected_sha256=receipt['sha256'],realm='realm:test',principal='owner')
        self.assertFalse(restored['activated'])
        copy=OperationalStore(self.root/'restored',realm='realm:test',principal='owner')
        try:self.assertEqual(copy.status(['scope'])['operations'][0]['state'],'local_pending')
        finally:copy.close()

    def test_local_work_state_does_not_pollute_the_existing_diagnostic_journal(self):
        from types import SimpleNamespace
        from ekk.adapters.activity_cli import local_store
        from ekk.adapters.operation_diagnostics import journal
        with patch.dict(os.environ,{'EKK_DATA_HOME':str(self.root/'host-runtime')}):
            diagnostics=journal();attempt=diagnostics.begin('queue.submit')
            store=local_store(SimpleNamespace(principal='owner'),'realm:test')
            try:store.enqueue('request',{'body':'exact'},['scope'])
            finally:store.close()
            diagnostics.finish(attempt,result='completed')
            attempt=diagnostics.begin('queue.status');diagnostics.finish(attempt,result='completed')

    def test_waiting_and_unknown_external_outcome_are_explicit(self):
        task=self.store.task(['scope'],'create',{'key':'new','title':'Follow up','external':{'owner':'tracker','locator':'issue:12'}})
        waiting=self.store.task(['scope'],'wait',{'id':task['id'],'revision':1,'key':'wait','until':'2026-10-01T10:00:00+03:00'})
        self.assertEqual(waiting['wait']['registration'],'not_registered')
        attempt=self.store.task(['scope'],'external-attempt',{'id':task['id'],'revision':2,'key':'attempt','operation_key':'send:1'})
        self.assertEqual(attempt['external_action']['state'],'unknown')
        with self.assertRaises(ValueError):self.store.task(['scope'],'external-attempt',{'id':task['id'],'revision':3,'key':'attempt2','operation_key':'send:2'})
        reconciled=self.store.task(['scope'],'external-outcome',{'id':task['id'],'revision':3,'key':'reconcile','operation_key':'send:1','outcome':'confirmed','evidence':'Owner system receipt #1'})
        self.assertEqual(reconciled['external_action']['state'],'confirmed')
        with self.assertRaises(Conflict):self.store.task(['scope'],'update',{'id':task['id'],'revision':1,'key':'old','status':'completed'})

    def test_authored_search_pins_bytes_and_never_writes_author_file(self):
        folder=self.root/'notes';folder.mkdir();note=folder/'Direction.md';note.write_text('\u0420\u0430\u0437\u0432\u0438\u0442\u0438\u0435 EKK: \u0451\u043c\u043a\u0430\u044f \u0437\u0430\u043c\u0435\u0442\u043a\u0430.\n')
        before=note.read_bytes();source=AuthoredSources(self.root/'sources')
        source.configure('notes',folder,['scope'])
        found=source.search(['scope'],'\u0435\u043c\u043a\u0430\u044f')['results'][0]
        self.assertIn('\u0451\u043c\u043a\u0430\u044f',source.fetch(['scope'],found['reference'])['text'])
        self.assertEqual(source.search(['other'],'\u0435\u043c\u043a\u0430\u044f')['results'],[])
        self.assertEqual(note.read_bytes(),before)
        note.write_text('Changed by author')
        with self.assertRaises(Conflict):source.fetch(['scope'],found['reference'])
        (folder/'linked.md').symlink_to(self.root/'ops/operations.sqlite')
        self.assertGreater(source.search(['scope'])['omitted_files'],0)

    def test_cache_corruption_falls_back_and_grammar_remains_strict(self):
        cache=DerivedCache(self.root/'cache','test');self.addCleanup(cache.close)
        cache.put('kind',b'input',{'trusted':'parsed'})
        self.assertEqual(cache.get('kind',b'input'),{'trusted':'parsed'})
        cache.db.execute("UPDATE entries SET value=?",(b'{"forged":true}',))
        self.assertIsNone(cache.get('kind',b'input'))
        codec=MarkdownCodec(cache_dir=self.root/'parsed')
        self.assertEqual(codec.load_yaml(b'a: 1\n'),{'a':1})
        with self.assertRaises(ValueError):codec.load_yaml(b'a: 1\na: 2\n')

    def test_author_directory_swap_cannot_expand_the_selected_folder(self):
        folder=self.root/'notes';nested=folder/'drafts';nested.mkdir(parents=True)
        (nested/'note.md').write_text('Selected author bytes')
        outside=self.root/'outside';outside.mkdir();(outside/'note.md').write_text('Unselected private bytes')
        source=AuthoredSources(self.root/'sources');source.configure('notes',folder,['scope'])
        reference=source.search(['scope'],'Selected')['results'][0]['reference']
        open_file=os.open
        def swap(component,flags,*args,**kwargs):
            if component=='drafts':
                nested.rename(folder/'original');nested.symlink_to(outside,target_is_directory=True)
            return open_file(component,flags,*args,**kwargs)
        with patch('ekk.adapters.repository_evidence.os.open',side_effect=swap):
            with self.assertRaises(OSError):source.fetch(['scope'],reference)

    def test_brief_keeps_required_constraints_and_marks_optional_excerpt(self):
        row={'id':'rule','digest':'a'*64,'metadata':{'revision':1,'title':'Rule','kind':'policy'},'body':'exact restriction','mandatory':True,'governs':True}
        result={'schema':'ekk.context/0.1','blocked':False,'unknowns':[],'conflicts':[],'scopes':['scope'],
                'records':[row,{**row,'id':'note','mandatory':False,'governs':False,'body':'x'*2000}],
                'manifest':{'realm_id':'realm:test','snapshots':[],'incomplete':False,'omitted':[]}}
        brief=brief_context(result,budget=3000)
        self.assertEqual(brief['required_reading'][0]['body'],'exact restriction')
        self.assertTrue(brief['material'][0]['full_read_required_for_use'])

    def test_disposable_cache_can_close_on_gateway_transport_thread(self):
        import threading
        cache=DerivedCache(self.root/'thread-cache','thread')
        errors=[]
        def finish():
            try:
                cache.put('bytes',b'exact',{'value':1})
                self.assertEqual(cache.get('bytes',b'exact'),{'value':1})
                cache.close()
            except BaseException as exc:errors.append(exc)
        thread=threading.Thread(target=finish);thread.start();thread.join()
        self.assertEqual(errors,[])


if __name__=='__main__':unittest.main()
