"""Native declared-file completion and runnable navigation on isolated stores."""
import json
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from ekk.adapters.command_line import dispatch, parser, routed_navigation, service
from ekk.adapters.activity_cli import local_store, publish
from ekk.adapters.markdown import MAX_DOCUMENT_BYTES
from ekk.adapters.work_repository import RealmWorkRepository
from ekk.application.work import WorkService


class ManifestCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        env = patch.dict(os.environ, {'EKK_DATA_HOME':str(self.root/'data'),
            'EKK_CONFIG_HOME':str(self.root/'config'), 'EKK_CACHE_HOME':str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        self.app = service(self.root/'realm')
        self.app.init('Manifest workflow',realm_id=self.app.initial_realm_id,context_id='scope')
        self.files = self.root/'files'; self.files.mkdir()
        (self.files/'result.md').write_bytes(b'Observed result.\r\nNext step remains explicit.\n')
        (self.files/'evidence.bin').write_bytes(b'exact\x00\xff\r\n')
        self.manifest = self.files/'manifest.json'
        self.manifest.write_text(json.dumps({'schema':'ekk.result-manifest/0.1',
            'title':'Actual declared result', 'result_file':'result.md',
            'artifacts':[{'path':'evidence.bin'}]}))

    def args(self,*extra):
        return parser().parse_args(['retain','--root',str(self.root/'realm'),
            '--scope','scope','--manifest',str(self.manifest),*extra])

    def test_sync_declared_inventory_and_unchanged_retry_complete(self):
        args=self.args('--wait','--idempotency-key','declared')
        first=dispatch(args,{})
        package=first['declared_package']
        self.assertEqual(package['state'],'complete')
        self.assertEqual(package['verified'],2)
        self.assertEqual(package['destination']['contexts'],['scope'])
        self.assertFalse(package['accepted'])
        second=dispatch(self.args('--wait','--idempotency-key','declared'),{})
        self.assertEqual(first['result_reference'],second['result_reference'])
        self.assertEqual(second['declared_package']['state'],'complete')

    def test_queue_freezes_declared_bytes_after_originals_are_deleted(self):
        with patch('ekk.adapters.activity_cli.start_worker',return_value={'started':False}):
            pending=dispatch(self.args('--idempotency-key','frozen'),{})
        self.assertEqual(pending['declared_package']['state'],'pending')
        self.assertEqual(pending['declared_package']['verified'],0)
        (self.files/'result.md').unlink(); (self.files/'evidence.bin').unlink()
        store=local_store(self.app,self.app.initial_realm_id)
        self.addCleanup(store.close)
        completed=store.drain(['scope'],publish)
        row=next(r for r in completed['operations'] if r['key']=='frozen')
        self.assertEqual(row['state'],'read_back_and_discoverable')
        result=self.app.fetch_record(['scope'],row['receipt']['result_reference'])
        self.assertEqual(result['body'],'Observed result.\r\nNext step remains explicit.\n')

    def test_invalid_inventory_and_complete_record_limit_do_not_enqueue(self):
        (self.files/'evidence.bin').unlink()
        with patch('ekk.adapters.command_line.queue_retention') as enqueue:
            with self.assertRaises(OSError):dispatch(self.args(),{})
            enqueue.assert_not_called()
        (self.files/'evidence.bin').write_bytes(b'exact')
        (self.files/'result.md').write_bytes(b'x'*MAX_DOCUMENT_BYTES)
        with patch('ekk.adapters.command_line.queue_retention') as enqueue:
            with self.assertRaises(ValueError):dispatch(self.args(),{})
            enqueue.assert_not_called()

    def test_manifest_is_exclusive_and_cannot_affect_other_operations(self):
        for extra,request in [(['--title','override'],{}),([],{'body':'other'}),
                              (['--file',str(self.files/'evidence.bin')],{})]:
            with self.assertRaises(ValueError):dispatch(self.args(*extra),request)
        args=parser().parse_args(['fetch','--root',str(self.root/'realm'),'--scope','scope',
            '--manifest',str(self.manifest),'--id','unused'])
        with self.assertRaises(ValueError):dispatch(args,{})

    def test_exact_navigation_preserves_the_original_route(self):
        receipt=dispatch(self.args('--wait'),{})
        ref=receipt['result_reference']
        data={'navigation':{'selected':{'reference':ref,'argv':['ekk','enter','--resume',json.dumps(ref)]}}}
        args=self.args()
        args.profile='personal'
        shown=routed_navigation(data,args)
        argv=shown['navigation']['selected']['argv']
        self.assertEqual(argv[argv.index('--root')+1],str(self.root/'realm'))
        self.assertIn('--scope',argv)
        parsed=parser().parse_args(argv[1:])
        resumed=dispatch(parsed,{})
        self.assertFalse(resumed['blocked'])
        self.assertEqual(resumed['entry']['resume'],ref)
        self.assertEqual(len(data['navigation']['selected']['argv']),4)

    def navigation(self,reference):
        return {'navigation':{'selected':{'reference':reference,
            'argv':['ekk','enter','--resume',json.dumps(reference)]}}}

    def personal_route(self,*,broader=False):
        """Real LocalProfile fixtures; both stores and configuration are disposable."""
        personal=service(self.root/'personal-realm',realm_id='realm:personal')
        personal.init('Personal',realm_id=personal.initial_realm_id,context_id='scope')
        contexts=['scope']
        if broader:
            contexts.append('other')
            for app in (self.app,personal):
                metadata={'schema':'ekk.record/0.1','id':'other','title':'Other context','kind':'context',
                    'context':{'purpose':'Not selected in this request'},'scope':['other'],'revision':1,
                    'created_at':'2026-10-05T00:00:00Z','created_by':app.principal}
                app.apply(app.propose({'records/other.md':app.codec.encode(metadata,'')}),idempotency_key='fixture-other')
        reference=WorkService(RealmWorkRepository(personal,['scope'])).start(
            title='Personal work',fields={'intention':'Continue my own research'},key='personal-work')['result_reference']
        workspace=self.root/'shared-workspace';(workspace/'.ekk').mkdir(parents=True)
        (workspace/'.ekk/workspace.yaml').write_text(yaml.safe_dump({
            'schema':'ekk.workspace/0.1','workspace_id':'workspace:shared','profile':'navigation',
            'bindings':[{'realm_alias':'shared','realm_id':self.app.initial_realm_id,'contexts':contexts}]}))
        profiles=self.root/'config'/'profiles';profiles.mkdir(parents=True,exist_ok=True)
        (profiles/'navigation.yaml').write_text(yaml.safe_dump({
            'schema':'ekk.profile/0.1','uid':os.getuid(),
            'realms':{'shared':{'path':str(self.root/'realm'),'id':self.app.initial_realm_id},
                      'personal':{'path':str(self.root/'personal-realm'),'id':personal.initial_realm_id}},
            'home':{'realm_alias':'personal','realm_id':personal.initial_realm_id,'contexts':contexts,
                    'cwd_roots':[str(self.root/'personal-home')]}}))
        return workspace,reference

    def replay_navigation(self,args,request,reference):
        value=self.navigation(reference);before=deepcopy(value)
        request_before=deepcopy(request);args_before=deepcopy(vars(args))
        shown=routed_navigation(value,args,request=request)
        self.assertEqual(value,before)
        self.assertEqual(request,request_before)
        self.assertEqual(vars(args),args_before)
        self.assertEqual(routed_navigation(shown,args,request=request),shown,
                         'Rendering a second time must not duplicate route flags')
        item=shown['navigation']['selected']
        replay_args=parser().parse_args(item['argv'][1:])
        resumed=dispatch(replay_args,json.loads(item.get('stdin','{}')))
        self.assertFalse(resumed['blocked'])
        self.assertEqual(resumed['entry']['resume'],reference)
        return shown,resumed

    def test_navigation_replays_personal_work_from_bound_shared_workspace(self):
        workspace,reference=self.personal_route()
        args=parser().parse_args(['enter','--cwd',str(workspace),'--profile','navigation',
                                 '--personal','--resume',json.dumps(reference)])
        original=dispatch(args,{})
        self.assertEqual([c['owner_projection'] for c in original['contexts']],['shared','personal'])
        _,resumed=self.replay_navigation(args,{},reference)
        personal=next(c for c in resumed['contexts'] if c['owner_projection']=='personal')
        self.assertEqual(personal['manifest']['forced_refs'],[reference])

    def test_navigation_keeps_normalized_json_scope_narrower_than_cli_scope(self):
        metadata={'schema':'ekk.record/0.1','id':'other','title':'Other context','kind':'context',
                  'context':{'purpose':'Broader route'},'scope':['other'],'revision':1,
                  'created_at':'2026-10-05T00:00:00Z','created_by':self.app.principal}
        self.app.apply(self.app.propose({'records/other.md':self.app.codec.encode(metadata,'')}),
                       idempotency_key='other-context')
        reference=WorkService(RealmWorkRepository(self.app,['scope'])).start(
            title='Narrow work',fields={'intention':'Use only the selected context'},key='narrow-work')['result_reference']
        for request in ({'payload':{'scopes':['scope']}},{'target_scope':['scope']},
                        {'payload':{'target_scope':['scope']}}):
            with self.subTest(request=request):
                args=parser().parse_args(['enter','--root',str(self.root/'realm'),
                    '--cwd',str(self.root),'--scope','scope','--scope','other','--resume',json.dumps(reference)])
                original=dispatch(args,deepcopy(request))
                self.assertEqual(original['contexts'][0]['scopes'],['scope'])
                _,resumed=self.replay_navigation(args,request,reference)
                self.assertEqual(resumed['contexts'][0]['scopes'],['scope'])

    def test_navigation_combines_json_personal_selection_and_narrowed_scopes(self):
        workspace,reference=self.personal_route(broader=True)
        args=parser().parse_args(['enter','--cwd',str(workspace),'--profile','navigation',
                                 '--scope','scope','--scope','other','--resume',json.dumps(reference)])
        request={'payload':{'personal':True,'target_scope':['scope']}}
        original=dispatch(args,deepcopy(request))
        self.assertEqual([c['owner_projection'] for c in original['contexts']],['shared','personal'])
        shown,resumed=self.replay_navigation(args,request,reference)
        item=shown['navigation']['selected']
        self.assertEqual(json.loads(item['stdin']),{'scopes':['scope']})
        self.assertIn('--stdin',item['argv'])
        self.assertEqual([c['owner_projection'] for c in resumed['contexts']],['shared','personal'])
        self.assertTrue(all(c['scopes']==['scope'] for c in resumed['contexts']))


if __name__=='__main__':unittest.main()
