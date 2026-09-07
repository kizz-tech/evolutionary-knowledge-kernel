import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ekk.adapters.command_line import main

class CurrentCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.realm=self.root/'realm'
        self.env=patch.dict(os.environ,{'EKK_DATA_HOME':str(self.root/'data'),'EKK_CONFIG_HOME':str(self.root/'config')})
        self.env.start();self.addCleanup(self.env.stop)
        code,data=self.call(['init','--root',str(self.realm),'--title','Example'])
        self.assertEqual(code,0,data)
        from ekk.adapters.command_line import service
        self.app=service(self.realm);self.scope=self.app.codec.load_yaml(self.app.store.snapshot()['files']['.ekk/realm.yaml'])['default_context']
    def call(self,args,body=None):
        output=io.StringIO();error=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error),patch('sys.stdin',io.StringIO(json.dumps(body))):
            code=main(args+(['--stdin'] if body is not None else []))
        return code,json.loads(output.getvalue() or error.getvalue())
    def test_capture_retry_and_changed_request(self):
        args=['capture','--root',str(self.realm),'--scope',self.scope,'--idempotency-key','same']
        a=self.call(args,{'body':'first','title':'One'});self.assertEqual(a[0],0,a)
        b=self.call(args,{'body':'first','title':'One'});self.assertEqual(b,a)
        c=self.call(args,{'body':'different','title':'One'});self.assertEqual(c[0],2,c)
        self.assertEqual(self.app.doctor()['records'],2)
    def test_compact_is_explicit_display_only(self):
        args=['context','--root',str(self.realm),'--scope',self.scope]
        code,full=self.call(args)
        self.assertEqual(code,0,full)
        code,compact=self.call(args+['--compact'])
        self.assertEqual(code,0,compact)
        self.assertEqual(full['schema'],'ekk.context/0.1')
        self.assertEqual(compact['schema'],'ekk.context-display/0.1')
        self.assertEqual(full['records'],compact['records'])
        self.assertEqual(full['manifest']['used_refs'],compact['manifest']['used_refs'])
        code,entered=self.call(['enter','--root',str(self.realm),'--scope',self.scope,'--compact'])
        self.assertEqual(code,0,entered)
        self.assertEqual(entered['schema'],'ekk.context-display/0.1')
        for body in ({}, {'request_id':'one','operation':'context'}):
            code,error=self.call(args+['--compact'],body)
            self.assertEqual(code,2,error)
        code,error=self.call(['capture','--root',str(self.realm),'--compact'])
        self.assertEqual(code,2,error)
    def test_no_capture_key_no_mutation(self):
        code,_=self.call(['capture','--root',str(self.realm),'--scope',self.scope],{'body':'first'})
        self.assertEqual(code,2);self.assertEqual(self.app.doctor()['records'],1)
    def test_malformed_json_shapes_return_json_errors(self):
        for op,body in [('propose',{'changes':[]}),('capture',{'body':{}}),('context',{'scopes':None})]:
            code,data=self.call([op,'--root',str(self.realm),'--scope',self.scope],body)
            self.assertEqual(code,2);self.assertIn('error',data)
    def test_exact_supplied_schema_accepts_initialized_realm(self):
        import jsonschema
        repo=Path(__file__).resolve().parents[1]
        snapshot=self.app.store.snapshot()
        for path,raw in snapshot['files'].items():
            if path=='.ekk/realm.yaml':schema='realm';data=self.app.codec.load_yaml(raw)
            elif path.startswith('contexts/') and path.endswith('.md'):schema='record';data=self.app.codec.decode(raw)['metadata']
            else:continue
            jsonschema.Draft202012Validator(json.loads((repo/'spec/schemas'/f'{schema}.schema.json').read_text()),format_checker=jsonschema.FormatChecker()).validate(data)
    def test_common_envelope_identity_and_budget(self):
        args=['context','--root',str(self.realm),'--scope',self.scope]
        for body in [{'operation':'export'},{'target_realm':'other-realm'},{'workspace_id':'other-workspace'},{'budget':float('nan')},{'budget':True}]:
            code,data=self.call(args,body);self.assertEqual(code,2,data)
        code,data=self.call(args,{'operation':'context','target_scope':[self.scope],'payload':{'task':'Example','budget':1000}})
        self.assertEqual(code,0,data)
        self.assertEqual(data['schema'],'ekk.result/0.1')
        self.assertTrue(data['data']['index']['disposable'])

    def test_common_response_proposal_apply_roundtrip(self):
        metadata={'schema':'ekk.record/0.1','id':'envelope-note','kind':'note','title':'Envelope note','scope':[self.scope],'revision':1,'created_at':'2026-09-07T12:00:00Z','created_by':'declared-author'}
        raw=self.app.codec.encode(metadata,'A proposed note.').decode()
        expected=self.app.store.snapshot()['revision']
        request={'request_id':'prepare-one','operation':'propose','expected_snapshot':expected,'target_scope':[self.scope],'principal':'forged-admin','payload':{'changes':{'records/envelope-note.md':raw},'explanation':'Preserve the supplied note.'}}
        code,envelope=self.call(['propose','--root',str(self.realm),'--scope',self.scope],request)
        self.assertEqual(code,0,envelope)
        self.assertEqual(set(envelope),{'schema','request_id','operation','status','snapshot','data','source_references','incomplete','warnings','guarantees'})
        self.assertEqual(envelope['request_id'],'prepare-one');self.assertEqual(envelope['status'],'completed')
        self.assertEqual(envelope['snapshot'],expected);self.assertEqual(envelope['guarantees']['verified'],[])
        proposal=envelope['data'];self.assertEqual(proposal['impact']['scopes'],[self.scope]);self.assertEqual(proposal['grounds'],[])
        self.assertEqual(proposal['explanation'],'Preserve the supplied note.')
        self.assertEqual(self.app.doctor()['records'],1)
        request={'request_id':'apply-one','operation':'apply','expected_snapshot':expected,'principal':'forged-admin','payload':{'proposal':proposal,'idempotency_key':'apply-envelope'}}
        code,applied=self.call(['apply','--root',str(self.realm),'--scope',self.scope],request)
        self.assertEqual(code,0,applied);self.assertEqual(applied['schema'],'ekk.result/0.1')
        self.assertEqual(applied['snapshot'],applied['data']['revision']);self.assertEqual(applied['data']['principal'],self.app.principal)
        self.assertEqual(self.app.doctor()['records'],2)

    def test_common_errors_are_wrapped_and_shorthand_stays_unwrapped(self):
        code,error=self.call(['context','--root',str(self.realm),'--scope',self.scope],{'request_id':'bad-request','operation':'context','payload':{'budget':True}})
        self.assertEqual(code,2);self.assertEqual(error['schema'],'ekk.result/0.1')
        self.assertEqual(error['status'],'error');self.assertEqual(error['request_id'],'bad-request')
        self.assertEqual(error['data']['error'],'invalid_format');self.assertTrue(error['incomplete'])
        code,plain=self.call(['context','--root',str(self.realm),'--scope',self.scope],{'task':'Example'})
        self.assertEqual(code,0);self.assertEqual(plain['schema'],'ekk.context/0.1');self.assertIn('index',plain)

    def test_common_capture_retry_retains_operation_result(self):
        request={'request_id':'capture-envelope','operation':'capture','payload':{'body':'same source','title':'Common source'}}
        args=['capture','--root',str(self.realm),'--scope',self.scope]
        first=self.call(args,request);second=self.call(args,request)
        self.assertEqual(first[0],0,first);self.assertEqual(first,second)
        self.assertEqual(first[1]['operation'],'capture');self.assertEqual(first[1]['data']['state'],'published')

    def test_common_unbound_result_and_missing_profile_do_not_claim_access(self):
        code,result=self.call(['enter','--cwd',str(self.root)],{'request_id':'unbound-enter','operation':'enter','payload':{}})
        self.assertEqual(code,0,result);self.assertEqual(result['status'],'unbound')
        self.assertTrue(result['incomplete']);self.assertTrue(result['warnings']);self.assertIsNone(result['data']['context'])
        code,result=self.call(['context','--profile','absent-profile','--realm','missing-alias'],{'request_id':'missing-profile','operation':'context','payload':{}})
        self.assertEqual(code,2);self.assertEqual(result['data']['error'],'unresolved_binding')
        self.assertNotIn(str(self.root),json.dumps(result));self.assertNotIn('absent-profile.yaml',json.dumps(result))
        code,result=self.call(['capture','--root',str(self.realm),'--scope',self.scope,'--file',str(self.root/'missing-source')],{'request_id':'missing-source','operation':'capture','payload':{}})
        self.assertEqual(code,2);self.assertEqual(result['data']['error'],'source_unavailable')

    def test_transport_rejects_nonstandard_json_outside_budget(self):
        for value in (float('nan'),float('inf'),float('-inf')):
            code,result=self.call(['capture','--root',str(self.realm),'--scope',self.scope],{'body':value})
            self.assertEqual(code,2);self.assertEqual(result['error'],'invalid_format')
            self.assertIn('Nonstandard JSON constant',result['message'])

    def test_common_init_forwards_only_supported_payload_and_checks_realm(self):
        target=self.root/'common-init';realm_id='urn:uuid:11111111-2222-3333-4444-555555555555'
        request={'request_id':'init-request','operation':'init','target_realm':realm_id,'principal':'forged-admin','payload':{'title':'Common init','context_id':'common-context','principal':'also-forged'}}
        code,result=self.call(['init','--root',str(target)],request)
        self.assertEqual(code,0,result);self.assertEqual(result['schema'],'ekk.result/0.1')
        self.assertEqual(result['data']['realm_id'],realm_id);self.assertTrue(result['data']['doctor']['ok'])
        from ekk.adapters.command_line import service
        created=service(target);manifest=created.codec.load_yaml(created.store.snapshot()['files']['.ekk/realm.yaml'])
        self.assertEqual(manifest['owner'],self.app.principal)
        conflict={**request,'target_realm':'conflicting-realm','payload':{'realm_id':realm_id}}
        code,result=self.call(['init','--root',str(self.root/'conflict-init')],conflict)
        self.assertEqual(code,2);self.assertEqual(result['data']['error'],'invalid_format')
        self.assertFalse((self.root/'conflict-init').exists())

    def test_capture_returns_exact_source_reference(self):
        args=['capture','--root',str(self.realm),'--scope',self.scope,'--idempotency-key','refs']
        code,data=self.call(args,{'request_id':'source-ref','operation':'capture','payload':{'body':'source bytes','title':'Addressable'}})
        self.assertEqual(code,0,data)
        reference=data['source_references'][0]
        record=self.app._load(self.app.store.snapshot())[-1][reference['id']]
        self.assertEqual(reference['digest'],'sha256:'+record['digest'])
        self.assertEqual(reference['revision'],record['metadata']['revision'])
        again=self.call(args,{'request_id':'source-ref','operation':'capture','payload':{'body':'source bytes','title':'Addressable'}})
        self.assertEqual(again,(code,data))

    def test_assurance_is_available_through_current_cli(self):
        code,result=self.call(['assurance','--root',str(self.realm),'--scope',self.scope])
        self.assertEqual(code,0,result)
        self.assertEqual(result['schema'],'ekk.assurance/0.1')
        self.assertEqual(result['mutations'],0)
