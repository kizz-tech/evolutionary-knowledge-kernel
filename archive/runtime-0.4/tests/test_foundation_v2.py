"""Adversarial upgrade and action-history contracts."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import yaml
from ekk.kernel import Kernel, KernelError, markdown, checksum
from ekk import semantics, semantics_v1

T='2026-01-01T00:00:00Z'
C={k:k for k in ('authority','rationale','effect','expectation','verification','revisit','rollback')}

def fixture():
    def rec(key,**extra):
        return {'metadata':dict(schema='ekk/1',id=key,title=key,kind='understanding',author='fixture',scopes=['a'],known_from=T,valid_from=T,sources=['source'],relations=[],**extra),'body':key,'path':'records/'+key+'.md'}
    records={k:rec(k,commitment=C) for k in ('one','two')}
    records['source']=rec('source',artifact={'mode':'reference','uri':'fixture:source','version':'1','sha256':'0'*64})
    records['source']['metadata']['sources']=[]
    records['event']=rec('event',event={'type':'change','targets':['one','two']})
    records['decision']=rec('decision',commitment=C)
    records['decision']['metadata']['relations']=[{'predicate':'addresses','target':'event'}]
    return records

class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.k=Kernel(self.base/'root');self.k.init()
        self.source=self.k.reference('fixture:source','1','0'*64,'Source',['a'],'human')
    def add(self,key,**extra):
        return self.k.add(dict(id=key,title=key,kind='claim',author='test',scopes=['a'],sources=[self.source['id']],**extra),key)
    def legacy_root(self,records=None):
        records=records or fixture()
        root=self.base/'legacy';k=Kernel(root);k.init()
        cfg=yaml.safe_load((root/'kernel.yaml').read_text());cfg['version']='0.1.0'
        (root/'kernel.yaml').write_text(yaml.safe_dump(cfg))
        for r in records.values():
            raw=markdown(r['metadata'],r['body']).encode();(root/'records'/(checksum(raw)+'.md')).write_bytes(raw)
        return k
    def test_frozen_reader_file_matches_historical_hash(self):
        expected='c6c6d5f08b8ec8aeaf99c0201ec8b29406530225f1f035a0a4dc3658bfd06c17'
        self.assertEqual(checksum(Path(semantics_v1.__file__).read_bytes()),expected)
    def test_partial_addresses_preserves_other_candidate(self):
        for key in ('one','two'):self.add(key,commitment=C)
        self.add('event',event={'type':'change','targets':['one','two']})
        with self.assertRaisesRegex(KernelError,'explicit candidate'):
            self.add('invalid',commitment=C,relations=[{'predicate':'addresses','target':'event'}])
        self.add('decision',commitment=C,relations=[{'predicate':'addresses','target':'event','commitment':'one'}])
        self.assertEqual({r['commitment'] for r in self.k.evolve(['a'])['candidates']},{'two'})
    def test_legacy_replay_and_upgrade_preserve_bytes_and_meaning(self):
        k=self.legacy_root();before=k.compile(['a'],'',T,T);evolve=k.evolve(['a'],T,T)
        records={str(p.relative_to(k.root)):p.read_bytes() for p in k.root.glob('*/*.md')}
        with self.assertRaisesRegex(KernelError,'explicitly upgrade'):
            k.reference('fixture:blocked','1','1'*64,'No',['a'],'test')
        self.assertEqual(k.check()['records'],5)
        rollback=self.base/'backup';shutil.copytree(k.root,rollback)
        receipt=k.upgrade();self.assertEqual(receipt['records_unchanged'],5)
        self.assertEqual(before,k.compile(['a'],'',T,T,semantic_version='0.1.0'))
        self.assertEqual(evolve,k.evolve(['a'],T,T,semantic_version='0.1.0'))
        self.assertEqual(k.evolve(['a'],T,T)['candidates'],[]) # explicitly retained legacy addresses
        self.assertEqual(records,{str(p.relative_to(k.root)):p.read_bytes() for p in k.root.glob('*/*.md')})
        k.reference('fixture:new','1','1'*64,'New',['a'],'test')
        with self.assertRaisesRegex(KernelError,'pre-upgrade snapshot'):k.compile(['a'],semantic_version='0.1.0')
        self.assertEqual(before,Kernel(rollback).compile(['a'],'',T,T))
    def test_unknown_root_version_rejected(self):
        p=self.k.root/'kernel.yaml';cfg=yaml.safe_load(p.read_text());cfg['version']='9.0.0';p.write_text(yaml.safe_dump(cfg))
        with self.assertRaisesRegex(KernelError,'Unsupported kernel version'):self.k.check()
    def test_snapshot_independent_of_path_but_context_binds_query_and_compiler(self):
        records=fixture();a=semantics.compile_context(records,['a'],'',T,T)
        moved=copy.deepcopy(records)
        for r in moved.values():r['path']='other/location'
        b=semantics.compile_context(moved,['a'],'',T,T)
        self.assertEqual(a,b)
        changed=semantics.compile_context(moved,['a'],'query',T,T)
        self.assertEqual(a['snapshot_sha256'],changed['snapshot_sha256'])
        self.assertNotEqual(a['context_sha256'],changed['context_sha256'])
        self.assertEqual(a['context_sha256'],semantics.digest({k:v for k,v in a.items() if k!='context_sha256'}))
        self.assertEqual(a['compiler'],'0.2.0');self.assertEqual(a['contract'],'ekk/2')
    def test_bogus_completion_rejected_and_legacy_cannot_unlock(self):
        self.add('one',commitment=C)
        action=dict(id='action',title='Action',kind='action',author='test',scopes=['a'],sources=['one'],execution='started',execution_request={'command':['true'],'verifier':['true']})
        self.k._append(action,'pending')
        with self.assertRaisesRegex(KernelError,'completes'):
            self.add('fake',relations=[{'predicate':'completes','target':'action'}])
        records=fixture();records['action']=copy.deepcopy(records['one']);records['action']['metadata'].update(id='action',commitment=None,execution='started',sources=['one'])
        records['fake']=copy.deepcopy(records['event']);records['fake']['metadata'].update(id='fake',event=None,relations=[{'predicate':'completes','target':'action'}])
        k=self.legacy_root(records);self.assertEqual(k.check()['pending_actions'],['action'])
        with self.assertRaisesRegex(KernelError,'pending'):k.upgrade()
    def test_run_stores_exact_reconstructable_context(self):
        self.add('one',commitment=C)
        result=self.k.run('one',['a'],[sys.executable,'-c','pass'],[sys.executable,'-c','pass'],self.base,'test','none')
        request=self.k.get(result['action'])['metadata']['execution_request']
        source=self.k.get(request['context_source'])['metadata']['artifact']
        context=json.loads((self.k.root/source['path']).read_text())
        self.assertEqual(context['context_sha256'],request['context_sha256'])
        self.assertEqual(context['context_sha256'],semantics.digest({k:v for k,v in context.items() if k!='context_sha256'}))
        q=request['query'];replay=self.k.compile(q['scopes'],q['task'],q['at'],q['known_at'],semantic_version=request['compiler'])
        self.assertEqual(context,replay)
    def test_invented_outcome_with_unrelated_blob_rejected(self):
        self.add('one',commitment=C)
        self.k._append(dict(id='action',title='Action',kind='action',author='test',scopes=['a'],sources=['one'],execution='started',execution_request={'command':['true'],'verifier':['true']}),'pending')
        p=self.base/'unrelated.json';p.write_text('{}');source=self.k.observe(p,'Unrelated',['a'],'test')
        with self.assertRaisesRegex(KernelError,'completes is reserved'):
            self.k.add(dict(id='fake',title='fake',kind='outcome',author='test',scopes=['a'],sources=['action',source['id']],outcome={'commitment':'one','verdict':'met'},relations=[{'predicate':'completes','target':'action'},{'predicate':'verifies','target':'one'}]),'fake')
        self.assertEqual(self.k.check()['pending_actions'],['action'])

    def pending(self,verifier):
        self.add('one',commitment=C)
        with self.k._lock():
            return self.k._append(dict(id='action',title='Interrupted action',kind='action',author='test',scopes=['a'],sources=['one'],execution='started',execution_request={'command':[sys.executable,'-c',"raise AssertionError('must not rerun')"],'verifier':verifier,'cwd':str(self.base)}),'Simulated process interruption')
    def test_forged_matching_execution_json_cannot_finish_through_add(self):
        verifier=[sys.executable,'-c','pass'];action=self.pending(verifier)
        evidence={'action':'action','execution':{'argv':action['execution_request']['command'],'exit_code':0},'verification':{'argv':verifier,'exit_code':0},'verdict':'met'}
        p=self.base/'forged.json';p.write_text(json.dumps(evidence));source=self.k.observe(p,'Forged but matching JSON',['a'],'caller')
        with self.assertRaisesRegex(KernelError,'completes is reserved'):
            self.k.add(dict(id='fake',title='fake',kind='outcome',author='process:ekk-run',scopes=['a'],sources=['action',source['id']],outcome={'commitment':'one','verdict':'met'},relations=[{'predicate':'completes','target':'action'},{'predicate':'verifies','target':'one'}]),'fake')
        self.assertEqual(self.k.check()['pending_actions'],['action'])
    def test_public_add_cannot_forge_started_action(self):
        for field,value in [('execution','started'),('execution_request',{})]:
            with self.assertRaisesRegex(KernelError,'reserved'):self.add('fake',**{field:value})
    def test_recovery_verifies_without_rerunning_original_action(self):
        verifier=[sys.executable,'-c',"from pathlib import Path; assert Path('state').read_text()=='done'"]
        self.pending(verifier);(self.base/'state').write_text('done')
        result=self.k.recover('action',['a'],verifier,self.base,'user explicitly authorized verifier')
        self.assertTrue(result['recovered']);self.assertEqual(result['verdict'],'unknown');self.assertFalse(result['original_action_rerun'])
        self.assertEqual(self.k.check()['pending_actions'],[])
        self.assertEqual(self.k.get(result['outcome'])['metadata']['outcome']['verdict'],'unknown')
        artifact=self.k.get(result['evidence'])['metadata']['artifact']
        self.assertEqual(json.loads((self.k.root/artifact['path']).read_text())['execution']['exit_code'],None)
    def test_recovery_failure_retains_pending_and_evidence(self):
        verifier=[sys.executable,'-c','raise SystemExit(3)'];self.pending(verifier)
        result=self.k.recover('action',['a'],verifier,self.base,'test')
        self.assertFalse(result['recovered']);self.assertEqual(result['verification_exit'],3)
        self.assertEqual(self.k.check()['pending_actions'],['action'])
        self.assertFalse(any(r['predicate']=='completes' for r in self.k.get(result['outcome'])['metadata']['relations']))
    def test_recovery_requires_exact_explicit_parameters_and_execution_lease(self):
        verifier=[sys.executable,'-c','pass'];self.pending(verifier)
        with self.assertRaisesRegex(KernelError,'must match'):self.k.recover('action',['a'],['true'],self.base,'test')
        with self.assertRaisesRegex(KernelError,'scopes'):self.k.recover('action',['b'],verifier,self.base,'test')
        with self.k._execution_lock():
            with self.assertRaisesRegex(KernelError,'active'):self.k.recover('action',['a'],verifier,self.base,'test')
        self.assertEqual(self.k.check()['pending_actions'],['action'])

    def test_recovery_verifier_can_read_kernel_without_lock_conflict(self):
        verifier=[sys.executable,'-m','ekk','--root',str(self.k.root),'check']
        self.pending(verifier)
        result=self.k.recover('action',['a'],verifier,self.base,'test')
        self.assertTrue(result['recovered'])
        self.assertEqual(result['verification_exit'],0)
        self.assertEqual(self.k.check()['pending_actions'],[])
