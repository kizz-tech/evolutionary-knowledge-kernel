import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import time
import unittest
from unittest.mock import patch
from ekk.adapters.command_line import main
from ekk.adapters.host_identity import SCRUB_VARIABLES

class CurrentCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.realm=self.root/'realm'
        self.env=patch.dict(os.environ,{'EKK_DATA_HOME':str(self.root/'data'),'EKK_CONFIG_HOME':str(self.root/'config')})
        self.env.start();self.addCleanup(self.env.stop)
        for name in SCRUB_VARIABLES:os.environ.pop(name,None)  # decide records the host session it runs in
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
        args=['capture','--root',str(self.realm),'--scope',self.scope,'--idempotency-key','same','--wait']
        a=self.call(args,{'body':'first','title':'One'});self.assertEqual(a[0],0,a)
        b=self.call(args,{'body':'first','title':'One'});self.assertEqual(b,a)
        c=self.call(args,{'body':'different','title':'One'});self.assertEqual(c[0],2,c)
        self.assertEqual(self.app.doctor()['records'],2)
    def test_compact_and_brief_are_one_display_only_agent_view(self):
        args=['context','--root',str(self.realm),'--scope',self.scope]
        code,full=self.call(args)
        self.assertEqual(code,0,full)
        self.assertEqual(full['schema'],'ekk.context/0.1')
        code,compact=self.call(args+['--compact'])
        self.assertEqual(code,0,compact)
        self.assertEqual(compact,self.call(args+['--brief'])[1])
        self.assertEqual(compact['schema'],'ekk.context-brief/0.3')
        self.assertEqual(compact['snapshot'],full['manifest']['snapshots'])
        code,entered=self.call(['enter','--root',str(self.realm),'--scope',self.scope,'--compact'])
        self.assertEqual(code,0,entered)
        self.assertEqual(entered['schema'],'ekk.context-brief/0.3')
        code,wrapped=self.call(args+['--compact'],{'request_id':'one','operation':'context'})
        self.assertEqual(code,0,wrapped)
        self.assertEqual(wrapped['data']['schema'],'ekk.context-brief/0.3')
        # Display flags elsewhere are accepted and change nothing.
        code,listed=self.call(['contexts','--root',str(self.realm),'--scope',self.scope,'--compact'])
        self.assertEqual(code,0,listed)
        self.assertEqual(listed,self.call(['contexts','--root',str(self.realm),'--scope',self.scope])[1])
    def test_retain_is_queued_by_default_and_published_with_wait(self):
        args=['retain','--root',str(self.realm),'--scope',self.scope,'--title','Result']
        before=self.app.doctor()['records']
        with patch('ekk.adapters.activity_cli.start_worker',return_value={'started':False,'test':True}) as worker:
            code,queued=self.call(args,{'body':'Local result.'})
            self.assertEqual(code,0,queued)
            self.assertEqual((queued['schema'],queued['state']),('ekk.retention-queued/0.1','local_pending'))
            self.assertNotIn('retention',queued)
            self.assertIn('not confirmed',queued['meaning'])
            self.assertEqual(self.call(args,{'body':'Local result.'})[1]['key'],queued['key'])
            self.assertNotEqual(self.call(args,{'body':'Other result.'})[1]['key'],queued['key'])
            self.assertEqual(worker.call_count,3)
        self.assertEqual(self.app.doctor()['records'],before)
        code,error=self.call(args,{'body':' '})
        self.assertEqual(code,2,error)
        code,published=self.call(args+['--wait','--idempotency-key','sync'],{'body':'Local result.'})
        self.assertEqual(code,0,published)
        self.assertIn(published['retention']['state'],{'read_back','read_back_and_discoverable'})
        reference=published['result_reference']
        code,read=self.call(['fetch','--root',str(self.realm),'--scope',self.scope,'--id',reference['id']])
        self.assertEqual(code,0,read)
        self.assertEqual(read['reference']['digest'],reference['digest'])
        code,error=self.call(['fetch','--root',str(self.realm),'--scope',self.scope])
        self.assertEqual(code,2,error)
    def test_decide_is_queued_like_retain_and_accept_keeps_the_owners_statement(self):
        statement=self.root/'decision.md';statement.write_text('Keep BM25 as the fixed baseline.\n')
        args=['decide','--root',str(self.realm),'--scope',self.scope,'--title','BM25 stays','--result-file',str(statement),'--reason','Models start in shadow','--stated-by','agent']
        with patch('ekk.adapters.activity_cli.start_worker',return_value={'started':False,'test':True}):
            code,queued=self.call(args)
            self.assertEqual(code,0,queued)
            self.assertEqual((queued['schema'],queued['state']),('ekk.retention-queued/0.1','local_pending'))
            self.assertTrue(queued['key'].startswith('decide-'))
            self.assertEqual(self.call(args)[1]['key'],queued['key'])  # the same decision is one request
            self.assertNotEqual(self.call(args+['--revisit','A model beats it'])[1]['key'],queued['key'])
        self.assertEqual(self.app.doctor()['records'],1)
        code,published=self.call(args+['--wait','--revisit','A model beats it on owner samples','--alias','bm25-baseline'])
        self.assertEqual(code,0,published)
        self.assertIn(published['retention']['state'],{'read_back','read_back_and_discoverable'})
        reference=published['result_reference']
        code,read=self.call(['fetch','--root',str(self.realm),'--scope',self.scope,'--id',reference['id']])
        self.assertEqual(code,0,read)
        self.assertEqual(('decision','agent','Models start in shadow'),(read['metadata']['kind'],read['metadata']['decision']['stated_by'],read['metadata']['decision']['reason']))
        self.assertEqual({'when':['A model beats it on owner samples']},read['metadata']['review'])
        self.assertEqual((['bm25-baseline'],1),(read['metadata']['aliases'],len(read['metadata']['basis'])))  # its statement is its exact source
        self.assertEqual('Keep BM25 as the fixed baseline.\n\n**Reason, rejected alternative:** Models start in shadow\n\n**Revisit when:** A model beats it on owner samples\n',read['body'])
        self.assertIn(read['metadata']['decision']['source']['host'],{'claude-code','codex','unknown'})  # environment markers, never a terminal check
        # A later decision replaces it exactly and rests on it; a note cannot be replaced by a decision.
        code,later=self.call(['decide','--root',str(self.realm),'--scope',self.scope,'--title','BM25 stays until measured','--result-file',str(statement),
                              '--supersedes',reference['id'],'--ground',reference['id'],'--stated-by','agent','--wait'])
        self.assertEqual(code,0,later)
        code,read_later=self.call(['fetch','--root',str(self.realm),'--scope',self.scope,'--id',later['result_reference']['id']])
        exact={k:reference[k] for k in ('id','revision','digest')}
        self.assertEqual(([exact],exact),(read_later['metadata']['supersedes'],{k:read_later['metadata']['basis'][1][k] for k in exact}))
        note=self.app._meta('note','Note',[self.scope]);self.app.apply(self.app.propose({f"records/{note['id']}.md":self.app.codec.encode(note,'A note.')}),idempotency_key='note')
        code,error=self.call(['decide','--root',str(self.realm),'--scope',self.scope,'--title','x','--result-file',str(statement),'--supersedes',note['id'],'--stated-by','agent','--wait'])
        self.assertEqual(code,2,error);self.assertIn('supersedes a decision or an outcome',error['message'])
        code,error=self.call(['retain','--root',str(self.realm),'--scope',self.scope,'--title','x','--reason','y'],{'body':'z'})
        self.assertEqual(code,2,error);self.assertIn('decide options only',error['message'])
        # Acceptance carries the owner's statement into the receipt and the result; nothing about the caller is inferred.
        words=self.root/'statement.json';words.write_text(json.dumps({'by':'owner','via':'cli','at':'2026-10-02T10:00:00Z','words':'Yes, this is the rule'}))
        snapshot=self.app.store.snapshot()['revision']
        request={'references':[reference],'expected_snapshot':snapshot,'idempotency_key':'accept-1'}
        code,accepted=self.call(['accept','--root',str(self.realm),'--scope',self.scope,'--statement-file',str(words)],request)
        self.assertEqual(code,0,accepted)
        self.assertEqual(('published',{'by':'owner','via':'cli','at':'2026-10-02T10:00:00Z','words':'Yes, this is the rule'}),(accepted['state'],accepted['statement']))
        self.assertEqual(accepted,self.call(['accept','--root',str(self.realm),'--scope',self.scope,'--statement-file',str(words)],request)[1])
        receipts=[json.loads(raw) for path,raw in self.app.store.snapshot()['files'].items() if path.startswith('governance/receipts/')]
        self.assertEqual([accepted['statement']],[receipt['statement'] for receipt in receipts])
        self.assertTrue(self.app.doctor()['ok'])
        self.assertIn(reference['id'],self.app.doctor()['accepted'])
        for bad in ({'by':'agent','via':'cli','at':'2026-10-02T10:00:00Z'},{'by':'owner','via':'email','at':'2026-10-02T10:00:00Z'},
                    {'by':'owner','via':'cli','at':'2026-10-02T10:00:00'},{'by':'owner','via':'cli','at':'2026-10-02T10:00:00Z','words':'w'*601},
                    {'by':'owner','via':'cli','at':'2026-10-02T10:00:00Z','actor':'root'}):
            code,error=self.call(['accept','--root',str(self.realm),'--scope',self.scope],{**request,'references':[later['result_reference']],'idempotency_key':'accept-2','statement':bad})
            self.assertEqual(code,2,error)
        code,plain=self.call(['accept','--root',str(self.realm),'--scope',self.scope],{**request,'references':[later['result_reference']],
                              'expected_snapshot':self.app.store.snapshot()['revision'],'idempotency_key':'accept-2'})
        self.assertEqual(code,0,plain);self.assertNotIn('statement',plain)  # without a statement the receipt says nothing about who spoke
        code,error=self.call(['retain','--root',str(self.realm),'--scope',self.scope,'--statement-file',str(words)],{'body':'z','title':'t'})
        self.assertEqual(code,2,error)
    def records(self):
        from ekk.adapters.command_line import service
        app=service(self.realm);return app._load(app.store.snapshot())[-1],app.store.snapshot()['files']
    def queued(self):
        from ekk.adapters import activity_cli
        store=activity_cli.local_store(self.app,self.app.initial_realm_id)
        try:return [json.loads(row[0]) for row in store.db.execute('SELECT request FROM outbox ORDER BY updated')]
        finally:store.close()
    def test_decide_refuses_without_a_declaration_of_who_stated_it(self):
        base=['--root',str(self.realm),'--scope',self.scope]
        statement=self.root/'decision.md';statement.write_text('Keep the queue.\n')
        words=self.root/'words.md';words.write_text('\u0414\u0430, \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f.\n')
        blank=self.root/'blank.md';blank.write_text(' \n')
        latin=self.root/'latin.md';latin.write_bytes('Oui, gardée.'.encode('latin-1'))
        argv=['decide',*base,'--title','Queue stays','--result-file',str(statement),'--reason','Writes block']
        command=(f'ekk decide --cwd {shlex.quote(str(Path.cwd()))} --root {shlex.quote(str(self.realm))} --scope {shlex.quote(self.scope)} '
                 f"--title 'Queue stays' --result-file {shlex.quote(str(statement))} --reason 'Writes block'")
        session={'CLAUDECODE':'1','CLAUDE_CODE_SESSION_ID':'s-1'}
        json_only=['decide',*base,'--title','Queue stays']
        cases=[
            (argv,None,{},'stated_by_missing','--stated-by',None),
            (json_only,{'body':'Keep the queue.'},session,'stated_by_missing','--stated-by',None),
            (argv+['--stated-by','owner-relayed'],None,session,'words_missing','--owner-words',command+' --stated-by owner-relayed --owner-words FILE'),
            (json_only,{'body':'x','stated_by':'owner-relayed'},session,'words_missing','--owner-words',
             command.split(' --title ')[0]+" --title 'Queue stays' --stdin --stated-by owner-relayed --owner-words FILE"),
            (argv+['--stated-by','agent','--owner-words',str(words)],None,session,'words_with_agent','--owner-words',None),
            (json_only,{'body':'x','stated_by':'agent','owner_words':'\u0414\u0430'},session,'words_with_agent','owner_words',None),
            (argv+['--stated-by','owner-relayed','--owner-words',str(words)],None,{'CLAUDECODE':'1'},'session_identity_missing','--stated-by',None),
            (json_only,{'body':'x','stated_by':'owner-relayed','owner_words':'\u0414\u0430'},{},'session_identity_missing','--stated-by',None),
            (argv+['--stated-by','owner-relayed','--owner-words',str(words),'--statement-session','s-2'],None,session,'session_mismatch','--statement-session',None),
            (argv+['--stated-by','agent','--statement-session','s-2'],None,session,'session_mismatch','--statement-session',None),
            (json_only,{'body':'x','stated_by':'owner-relayed','owner_words':'\u0414\u0430','statement_session':'s-2'},session,'session_mismatch','statement_session',None),
            (argv+['--stated-by','owner-relayed','--owner-words',str(blank)],None,session,'words_missing','--owner-words',None),
            (argv+['--stated-by','owner-relayed','--owner-words',str(latin)],None,session,'words_unreadable','--owner-words',None),
            (argv+['--stated-by','owner-relayed','--owner-words',str(self.root/'\u0414\u0430, \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f.')],None,session,'words_unreadable','--owner-words',None),
        ]
        records=self.app.doctor()['records']
        for args,body,environment,refusal,option,command_next in cases:
            with self.subTest(args=args,body=body),patch.dict(os.environ,environment):
                code,result=self.call(args,body)
                self.assertEqual((2,'invalid_request',refusal,option),(code,result['error'],result.get('refusal'),result.get('option')),result)
                self.assertEqual(command_next,result.get('next'))
        code,error=self.call(argv)
        self.assertIn(f'`{command} --stated-by agent`',error['message'])
        self.assertIn(f'`{command} --stated-by owner-relayed --owner-words FILE`',error['message'])
        self.assertEqual((records,[]),(self.app.doctor()['records'],self.queued()))  # nothing queued or written
    def test_decide_keeps_the_owners_relayed_words_as_an_exact_source(self):
        base=['--root',str(self.realm),'--scope',self.scope]
        statement=self.root/'decision.md';statement.write_text('Keep the queue.\n')
        words=self.root/'words.md';words.write_text('\u0414\u0430, \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f.\n')
        other=self.root/'other.md';other.write_text('\u0414\u0430, \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f \u043d\u0430\u0432\u0441\u0435\u0433\u0434\u0430.\n')
        argv=['decide',*base,'--title','Queue stays','--result-file',str(statement)]
        relayed=argv+['--stated-by','owner-relayed','--owner-words',str(words)]
        day=time.strftime('%Y-%m-%d',time.gmtime())
        with patch.dict(os.environ,{'CLAUDECODE':'1','CLAUDE_CODE_SESSION_ID':'s-1'}),patch('ekk.adapters.activity_cli.start_worker',return_value={'started':False,'test':True}):
            code,queued=self.call(relayed)
            self.assertEqual(0,code,queued)
            self.assertEqual(queued['key'],self.call(relayed+['--statement-session','s-1'])[1]['key'])  # a matching cross-check changes nothing
            self.assertNotEqual(queued['key'],self.call(argv+['--stated-by','owner-relayed','--owner-words',str(other)])[1]['key'])
            [request,_]=self.queued()
            self.assertEqual(({'host':'claude-code','session':'s-1','at':day},['owner-words.md']),
                             (request['request']['decision']['source'],[item['filename'] for item in request['request']['artifacts']]))
            code,published=self.call(['decide',*base,'--title','Queue stays, enveloped','--wait'],
                                     {'request_id':'r-1','operation':'decide','payload':{'body':'Keep the queue.\n','stated_by':'owner-relayed',
                                                                                         'owner_words':'\u0414\u0430, \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f.\n'}})
            self.assertEqual(0,code,published)
            code,same=self.call(['decide',*base,'--title','Queue stays, in the owner\'s words','--wait'],
                                {'body':'\u0414\u0430, \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f.\n','stated_by':'owner-relayed','owner_words':'\u0414\u0430, \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f.\n'})
            self.assertEqual(0,code,same)
            code,agent=self.call(['decide',*base,'--title','Queue stays, by the agent','--result-file',str(statement),'--stated-by','agent','--wait'])
            self.assertEqual(0,code,agent)
        records,files=self.records()
        def read(result):
            return records[result['data']['result_reference']['id'] if 'data' in result else result['result_reference']['id']]['metadata']
        def source_bytes(reference):
            asset=records[reference['id']]['metadata']['source']['assets'][0]
            return asset['path'].rsplit('/',1)[-1],files[asset['path']]
        enveloped=read(published)
        self.assertEqual(({'schema':'ekk.decision/0.1','stated_by':'owner_relayed','source':{'host':'claude-code','session':'s-1','at':day}},'owner_statement'),
                         (enveloped['decision'],enveloped['retention']['claim_source']))
        self.assertEqual([('decision.md',b'Keep the queue.\n'),('owner-words.md','\u0414\u0430, \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f.\n'.encode())],[source_bytes(ref) for ref in enveloped['basis']])
        self.assertEqual(1,len(read(same)['basis']))  # words equal to the statement are its one exact source
        self.assertEqual(('agent',{'host':'claude-code','session':'s-1','at':day},1),
                         (read(agent)['decision']['stated_by'],read(agent)['decision']['source'],len(read(agent)['basis'])))
    def test_a_decide_request_queued_by_0_10_0_drains_unchanged(self):
        from ekk.adapters import activity_cli
        statement=self.root/'decision.md';statement.write_text('Keep the queue.\n')
        with patch('ekk.adapters.activity_cli.start_worker',return_value={'started':False,'test':True}):
            code,queued=self.call(['decide','--root',str(self.realm),'--scope',self.scope,'--title','Queue stays','--result-file',str(statement),'--stated-by','agent'])
        self.assertEqual(0,code,queued)
        [request]=self.queued()  # an agent's decision without a host session: the request 0.10.0 queues and drains
        self.assertEqual({'title':'Queue stays','body':'Keep the queue.\n','artifacts':[],'decision':{'schema':'ekk.decision/0.1','stated_by':'agent',
                          'source':{'host':'unknown','at':request['request']['decision']['source']['at']}}},request['request'])
        realm=self.app.codec.load_yaml(self.app.store.snapshot()['files']['.ekk/realm.yaml'])['id']
        old={'title':'Queued by 0.10.0','body':'Keep the old queue.\n','artifacts':[],
             'decision':{'schema':'ekk.decision/0.1','stated_by':'agent','source':{'host':'codex','at':'2026-10-09'}}}
        store=activity_cli.local_store(self.app,realm)
        try:
            store.enqueue('decide-0-10-0',{**request,'request':old},[self.scope])
            store.drain([self.scope],activity_cli.publish)
            states={row['key']:row['state'] for row in store.status([self.scope])['operations']}
        finally:store.close()
        self.assertEqual({'read_back_and_discoverable'},set(states.values()),states)
        records,_=self.records()
        [metadata]=[row['metadata'] for row in records.values() if row['metadata']['title']=='Queued by 0.10.0']
        self.assertEqual((old['decision'],1),(metadata['decision'],len(metadata['basis'])))
    def test_capture_without_key_derives_the_content_key(self):
        # The same bytes name the same key, so a retry publishes nothing new.
        code,first=self.call(['capture','--root',str(self.realm),'--scope',self.scope,'--wait'],{'body':'first'})
        self.assertEqual(code,0,first);self.assertEqual(self.app.doctor()['records'],2)
        code,again=self.call(['capture','--root',str(self.realm),'--scope',self.scope,'--wait'],{'body':'first'})
        self.assertEqual(code,0,again);self.assertEqual(self.app.doctor()['records'],2)
        self.assertEqual(first['reference']['id'] if 'reference' in first else first.get('result_reference'),
                         again['reference']['id'] if 'reference' in again else again.get('result_reference'))
    def test_capture_is_queued_by_default_and_published_by_the_worker(self):
        from ekk.adapters import activity_cli
        args=['capture','--root',str(self.realm),'--scope',self.scope,'--title','Page']
        with patch('ekk.adapters.activity_cli.start_worker',return_value={'started':False,'test':True}):
            code,queued=self.call(args,{'body':'exact source bytes','filename':'page.html'})
            self.assertEqual(code,0,queued)
            self.assertEqual((queued['schema'],queued['state']),('ekk.retention-queued/0.1','local_pending'))
            self.assertTrue(queued['key'].startswith('capture-'))
            self.assertEqual(self.call(args,{'body':'exact source bytes','filename':'page.html'})[1]['key'],queued['key'])
        self.assertEqual(self.app.doctor()['records'],1)
        store=activity_cli.local_store(self.app,self.app.initial_realm_id)
        try:
            result=store.drain([self.scope],activity_cli.publish)
            row=store.status([self.scope],key=queued['key'])['operations'][0]
        finally:store.close()
        self.assertEqual(row['state'],'read_back_and_discoverable',result)
        records=self.app._load(self.app.store.snapshot())[-1]
        source=next(r for r in records.values() if r['metadata']['kind']=='source')
        asset=source['metadata']['source']['assets'][0]
        self.assertEqual(self.app.store.snapshot()['files'][asset['path']],b'exact source bytes')
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
        self.assertEqual((error['data']['error'],error['data']['option']),('invalid_request','budget'));self.assertTrue(error['incomplete'])
        code,plain=self.call(['context','--root',str(self.realm),'--scope',self.scope],{'task':'Example'})
        self.assertEqual(code,0);self.assertEqual(plain['schema'],'ekk.context/0.1');self.assertIn('index',plain)

    def test_common_capture_retry_retains_operation_result(self):
        request={'request_id':'capture-envelope','operation':'capture','payload':{'body':'same source','title':'Common source'}}
        args=['capture','--root',str(self.realm),'--scope',self.scope,'--wait']
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
            self.assertEqual(code,2);self.assertEqual((result['error'],result['option']),('invalid_request','--stdin'))
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
        self.assertEqual(code,2);self.assertEqual((result['data']['error'],result['data']['option']),('invalid_request','target_realm'))
        self.assertFalse((self.root/'conflict-init').exists())

    def test_capture_returns_exact_source_reference(self):
        args=['capture','--root',str(self.realm),'--scope',self.scope,'--idempotency-key','refs','--wait']
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

class RequestErrorCliTests(unittest.TestCase):
    """invalid_request: a request the caller can correct names its option; unknown IDs stay exact."""
    setUp=CurrentCliTests.setUp
    call=CurrentCliTests.call
    def raw(self,args,text):
        output=io.StringIO();error=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error),patch('sys.stdin',io.StringIO(text)):
            code=main(args)
        return code,json.loads(output.getvalue() or error.getvalue())
    def note(self,identity,scope=None):
        note=self.app._meta('note','Note '+identity,scope or [self.scope]);note['id']=identity
        self.app.apply(self.app.propose({f'records/{identity}.md':self.app.codec.encode(note,'A note.')}),idempotency_key='note-'+identity)
        return identity
    def rows(self):
        return [row for row in map(json.loads,(self.root/'data/operations/operations.jsonl').read_text().splitlines()) if 'attempt_id' in row]
    def test_error_codes_put_a_correctable_request_first_and_keep_the_rest(self):
        from ekk.adapters.command_line import error_code
        from ekk.adapters.file_lock import LockBusy
        from ekk.application.errors import RequestError
        from ekk.model import Conflict, ValidationError
        for message in ('x','Scope outside workspace binding','No profile named record-binding','unsupported value'):
            self.assertEqual('invalid_request',error_code(RequestError(message)))  # whatever words a quoted value carries
        self.assertEqual('invalid_format',error_code(ValueError('record bytes digest mismatch')))  # malformed records keep their code
        self.assertEqual('invalid_format',error_code(ValidationError('title must be text')))
        self.assertEqual(('lock_busy','access_denied','stale_snapshot','unresolved_binding'),
                         (error_code(LockBusy('writer',30000)),error_code(PermissionError('x')),error_code(Conflict('x')),error_code(ValueError('Scope outside workspace binding'))))
    def test_each_request_check_is_invalid_request_naming_its_option(self):
        from ekk.adapters import activity_cli
        from ekk.adapters.command_line import error_code, normalized_request
        realm_id=self.app.codec.load_yaml(self.app.store.snapshot()['files']['.ekk/realm.yaml'])['id']
        profiles=self.root/'config/profiles';profiles.mkdir(parents=True)
        (profiles/'test.yaml').write_text(json.dumps({'schema':'ekk.profile/0.1','uid':os.getuid(),'realms':{'owned':{'id':realm_id,'path':str(self.realm)}}}))
        cwd=self.root/'elsewhere';cwd.mkdir()
        base=['--root',str(self.realm),'--scope',self.scope]
        code,published=self.call(['retain',*base,'--title','Result','--wait','--idempotency-key','table'],{'body':'Local result.'})
        self.assertEqual(code,0,published);record=published['result_reference']['id']
        anyfile=self.root/'any.json';anyfile.write_text('{}');bad=self.root/'bad.json';bad.write_text('not json')
        cases=[
            (['retain',*base,'--title','T'],{'body':'x','artifacts':[{'body':'a','filename':f'{i}.txt'} for i in range(33)]},'artifacts'),
            (['retain',*base,'--title','T'],{'body':' '},'body'),
            (['retain',*base],{'body':'x'},'title'),
            (['retain',*base,'--title','T'],{'body':'x','repository_evidence':'text'},'repository_evidence'),
            (['retain',*base,'--title','T'],{'body':'x','artifacts':[{'x':1}]},'artifacts'),
            (['capture',*base],{'body':''},'body'),
            (['capture',*base],{'body':'x','title':''},'title'),
            (['capture',*base],{'body':'x','filename':''},'filename'),
            (['context',*base],{'request_id':'r','payload':[]},'payload'),
            (['context',*base],{'request_id':'r','payload':{'operation':'fetch'}},'operation'),
            (['context',*base],{'target_scope':[self.scope],'scopes':['other']},'target_scope'),
            (['fetch',*base,'--manifest',str(anyfile)],None,'--manifest'),
            (['retain',*base,'--manifest',str(anyfile),'--title','T'],None,'--manifest'),
            (['context',*base,'--expected-head','a'*40],None,'--expected-head'),
            (['context',*base,'--ground','x'],None,'--ground'),
            (['context',*base,'--statement-file',str(anyfile)],None,'--statement-file'),
            (['context',*base,'--personal'],None,'--personal'),
            (['init','--workspace','--cwd',str(cwd)],None,'--realm'),
            (['init','--workspace','--cwd',str(cwd),'--profile','test','--realm','owned','--scope',self.scope,'--scope',self.scope],None,'--scope'),
            (['init','--cwd',str(cwd)],None,'--root'),
            (['apply',*base],{'expected_snapshot':'a'*40,'proposal':{'base':'b'*40},'idempotency_key':'k'},'expected_snapshot'),
            (['apply',*base],{'proposal':{}},'--idempotency-key'),
            (['decide',*base,'--title','T'],{'body':'x','stated_by':'owner'},'stated_by'),
            (['decide',*base,'--title','T'],{'body':'x'},'--stated-by'),
            (['decide',*base,'--title','T'],{'body':'x','stated_by':'agent','statement_session':5},'statement_session'),
            (['decide',*base,'--title','T'],{'body':'x','stated_by':'agent','owner_words':5},'owner_words'),
            (['decide',*base,'--title','T','--stated-by','owner-relayed'],{'body':'x'},'--owner-words'),
            (['propose',*base],{'changes':{'a.md':5}},'changes'),
            (['backup','--profile','test','--realm','owned','--cwd',str(cwd)],None,'--destination'),
            (['restore','--profile','test','--realm','owned','--cwd',str(cwd),'--destination',str(cwd/'copy')],None,'--file'),
            (['context',*base],{'request_id':''},'request_id'),
            (['context',*base],{'operation':'fetch'},'operation'),
            (['enter',*base],{'personal':'yes'},'personal'),
            (['enter',*base,'--resume','{}'],{'resume':{}},'--resume'),
            (['enter',*base,'--resume','not json'],None,'--resume'),
            (['enter',*base],{'personal':False,'scopes':['other']},'--scope'),
            (['context',*base,'--json',str(anyfile)],{},'--stdin'),
            (['context',*base,'--json',str(bad)],None,'--json'),
            (['accept',*base,'--statement-file',str(bad)],None,'--statement-file'),
            (['fetch',*base],None,'--id'),
            (['fetch',*base,'--id',record],{'max_bytes':0},'max_bytes'),
            (['fetch',*base,'--id',record],{'max_bytes':1},'max_bytes'),
            (['context',*base],{'budget':True},'budget'),
        ]
        for args,body,option in cases:
            with self.subTest(args=args,body=body):
                code,result=self.call(args,body)
                data=result.get('data',result) if result.get('schema')=='ekk.result/0.1' else result
                self.assertEqual((code,data['error'],data.get('option')),(2,'invalid_request',option),result)
        for text,option in (('not json','--stdin'),('[]','--stdin')):
            code,result=self.raw(['context',*base,'--stdin'],text)
            self.assertEqual((code,result['error'],result['option']),(2,'invalid_request',option),result)
        with patch('ekk.adapters.operational_store.OperationalStore.enqueue',side_effect=ValueError('Outbox request exceeds 16 MiB')):
            code,result=self.call(['retain',*base,'--title','T'],{'body':'x'})
        self.assertEqual((code,result['error'],result['option']),(2,'invalid_request','--wait'),result)
        route={'path':self.realm,'scopes':[self.scope],'alias':None}
        with patch('ekk.adapters.command_line._routes',return_value=[route,dict(route)]):
            code,result=self.call(['fetch',*base,'--id',record])
        self.assertEqual((code,result['error'],result['option']),(2,'invalid_request','--realm'),result)
        with self.assertRaises(ValueError) as raised:normalized_request({'operation':'fetch'},'context')
        self.assertEqual(('invalid_request','operation'),(error_code(raised.exception),raised.exception.option))
        # The legacy journal keeps 0.10.0's codes: every one of these is invalid_format at stage request.
        self.assertEqual({('invalid_format','request')},{(row['error_code'],row['failure_stage']) for row in self.rows() if row['result']=='error'})
        for argv,text,option in ((['list',*base,'--json',str(anyfile),'--stdin'],'{}','--stdin'),(['list',*base,'--stdin'],'[]','--stdin'),
                                 (['list',*base,'--stdin'],'not json','--stdin'),(['list',*base,'--stdin','--key','a'],'{"key":"b"}','--key')):
            error=io.StringIO()
            with contextlib.redirect_stderr(error),contextlib.redirect_stdout(io.StringIO()),patch('sys.stdin',io.StringIO(text)):
                self.assertEqual(2,activity_cli.main('task',argv))
            self.assertEqual(('invalid_request',option),tuple(json.loads(error.getvalue())[k] for k in ('error','option')))
    def test_an_unknown_id_names_the_full_id_only_for_a_unique_readable_prefix(self):
        base=['--root',str(self.realm),'--scope',self.scope]
        code,published=self.call(['retain',*base,'--title','Result','--wait','--idempotency-key','prefix'],{'body':'Local result.'})
        self.assertEqual(code,0,published)
        record=published['result_reference']['id']
        argv=['fetch','--root',str(self.realm),'--scope',self.scope,'--id',record[:8]]
        code,error=self.call(argv)
        self.assertEqual(2,code,error)
        self.assertEqual(('invalid_request','unknown_id','--id',[record]),(error['error'],error['refusal'],error['option'],error['record_ids']))
        self.assertNotIn("'",error['message'])  # no KeyError quoting
        self.assertIn(record,error['message'])
        self.assertEqual('ekk '+shlex.join(argv[:-1]+[record]),error['next'])  # the same command with only the ID replaced
        code,read=self.call(shlex.split(error['next'])[1:])
        self.assertEqual((0,record),(code,read['reference']['id']),read)
        code,wrapped=self.call(argv,{'request_id':'prefix','operation':'fetch'})
        self.assertEqual((2,'unknown_id',[record]),(code,wrapped['data']['refusal'],wrapped['data']['record_ids']))
        # read-source keeps its own command, and option=value is replaced in place.
        code,captured=self.call(['capture',*base,'--wait','--idempotency-key','prefix-source'],{'body':'source bytes','title':'Source'})
        source=captured['source_references'][0]['id']
        argv=['read-source','--root',str(self.realm),'--scope',self.scope,'--id='+source[:12]]
        code,error=self.call(argv)
        self.assertEqual(('unknown_id',[source],'ekk '+shlex.join(argv[:-1]+['--id='+source])),(error['refusal'],error['record_ids'],error['next']))
        code,read=self.call(shlex.split(error['next'])[1:])
        self.assertEqual(0,code,read)
        # Too short or matching nothing: the plain refusal.
        for value in (record[:7],'nothing-starts-with-this'):
            code,error=self.call(['fetch',*base,'--id',value])
            self.assertEqual((2,'invalid_request','unknown_id',f'Record unavailable in selected contexts: {value}'),
                             (code,error['error'],error['refusal'],error['message']))
            self.assertNotIn('record_ids',error);self.assertNotIn('next',error)
    def test_an_ambiguous_or_unreadable_prefix_names_no_id(self):
        base=['--root',str(self.realm),'--scope',self.scope]
        first,second=self.note('sharedpfx-one'),self.note('sharedpfx-two')
        code,error=self.call(['fetch',*base,'--id','sharedpfx'])
        self.assertEqual((2,'invalid_request','unknown_id'),(code,error['error'],error['refusal']))
        self.assertIn('2 records',error['message'])
        self.assertNotIn('record_ids',error);self.assertNotIn('next',error)
        self.assertNotIn(first,json.dumps(error));self.assertNotIn(second,json.dumps(error))
        # A record that also lies in a context not selected is never named, although it starts with the value.
        private=self.app._meta('context','Private',['context:private'],context={'purpose':'Private','concepts':[],'relations':[],'basis':[]})
        private['id']='context:private'
        self.app.apply(self.app.propose({'contexts/context:private.md':self.app.codec.encode(private,'Private context.\n')}),idempotency_key='private-context')
        hidden=self.note('hiddenpfx-spans-private',[self.scope,'context:private'])
        code,error=self.call(['fetch',*base,'--id','hiddenpfx'])
        self.assertEqual((2,'unknown_id'),(code,error['refusal']))
        self.assertNotIn(hidden,json.dumps(error));self.assertNotIn('record_ids',error)
        code,error=self.call(['fetch',*base,'--id',hidden])  # exact: refused by current access, as before
        self.assertEqual((2,'access_denied'),(code,error['error']),error)
    def test_decide_names_the_option_whose_id_is_unknown(self):
        base=['--root',str(self.realm),'--scope',self.scope]
        statement=self.root/'decision.md';statement.write_text('A decision.\n')
        target=self.note('groundpfx-target')
        for option in ('--supersedes','--ground'):
            argv=['decide',*base,'--title','T','--result-file',str(statement),'--stated-by','agent',option,'groundpfx']
            code,error=self.call(argv)
            self.assertEqual((2,'invalid_request','unknown_id',option,[target]),(code,error['error'],error['refusal'],error['option'],error['record_ids']))
            self.assertEqual('ekk '+shlex.join(argv[:-1]+[target]),error['next'])
        argv=['decide',*base,'--title','T','--result-file',str(statement),'--stated-by','agent','--ground',target,'--ground=groundpfx']
        self.assertEqual('ekk '+shlex.join(argv[:-1]+['--ground='+target]),self.call(argv)[1]['next'])
