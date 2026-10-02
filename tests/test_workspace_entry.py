import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.application.workspace import WorkspaceService, exact_reference
from ekk.adapters.local_profile import LocalProfile
from ekk.adapters.command_line import dispatch, parser

def isolate(test):
    """CLI dispatch journals every call; keep it out of the owner's EKK state."""
    home=tempfile.TemporaryDirectory();test.addCleanup(home.cleanup)
    env=patch.dict(os.environ,{'EKK_DATA_HOME':home.name+'/data','EKK_CONFIG_HOME':home.name+'/config','EKK_CACHE_HOME':home.name+'/cache'})
    env.start();test.addCleanup(env.stop)
    for marker in ('CODEX_HOME','CLAUDECODE'):os.environ.pop(marker,None)

class WorkspaceEntryTests(unittest.TestCase):
    def setUp(self):
        isolate(self)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.store=GitStore(self.root/'realm',self.root/'runtime')
        self.codec=MarkdownCodec()
        self.app=RealmService(self.store,'owner',lambda:'2026-09-07T12:00:00Z',codec=self.codec)
        self.app.init('Synthetic',context_id='scope',realm_id='realm:test')

    def add(self, key, body, revision=1, scope='scope', **extra):
        m=dict(schema='ekk.record/0.1',id=key,title=key,kind='note',scope=[scope],revision=revision,created_at='2026-09-07T10:00:00Z',created_by='owner',**extra)
        self.app.apply(self.app.propose({f'records/{key}.md':self.codec.encode(m,body)}),idempotency_key=key+str(revision))
        r=self.app._load(self.store.snapshot())[-1][key]
        return {'realm':'realm:test','id':key,'revision':revision,'digest':'sha256:'+r['digest']}

    def test_exact_historical_focus_and_dependency_budget(self):
        dep=self.add('basis','old evidence')
        ref=self.add('subject','old intention',depends_on=[dep])
        self.add('subject','new intention',revision=2)
        before=self.store.snapshot()['revision']
        result=self.app.context(['scope'],task='unmatched',focus=[ref])
        self.assertFalse(result['blocked'])
        self.assertEqual({r['body'] for r in result['records']},{'old intention','old evidence'})
        self.assertEqual(result['manifest']['forced_refs'],[ref])
        self.assertEqual(next(r for r in result['records'] if r['id']=='subject')['metadata']['revision'],1)
        self.assertEqual(self.store.snapshot()['revision'],before)
        self.assertTrue(self.app.context(['scope'],task='unmatched',focus=[ref],budget=1)['blocked'])
        self.assertEqual(self.app.context(['scope'],task='unmatched',focus=[ref],budget=1)['records'],[])

    def test_resume_rejects_wrong_realm_digest_scope_and_revision(self):
        ref=self.add('subject','bytes')
        for bad in [{**ref,'realm':'realm:other'},{**ref,'digest':'0'*64},{**ref,'revision':2}]:
            with self.assertRaises(ValueError):self.app.context(['scope'],focus=[bad])
        raw={**ref,'digest':ref['digest'].removeprefix('sha256:')}
        self.assertEqual(exact_reference(raw),ref)
        with self.assertRaises(ValueError):exact_reference({'id':'subject'})
        with self.assertRaises(ValueError):exact_reference({**ref,'revision':True})
        m=dict(schema='ekk.record/0.1',id='other',title='other',kind='context',context={'purpose':'other'},scope=['other'],revision=1,created_at='2026-09-07T10:00:00Z',created_by='owner')
        self.app.apply(self.app.propose({'records/other.md':self.codec.encode(m,'')}),idempotency_key='other')
        forbidden=self.add('private','private bytes',scope='other')
        self.add('private','now within scope',revision=2)
        with self.assertRaises(PermissionError):self.app.context(['scope'],focus=[forbidden])
        restricted=RealmService(self.store,'owner',codec=self.codec,allowed_scopes=['scope'])
        with self.assertRaises(PermissionError):restricted.context(['other'],focus=[forbidden])

    def test_profile_home_explicit_identity_and_no_implicit_default(self):
        profile_doc={'schema':'ekk.profile/0.1','uid':os.getuid(),'realms':{}}
        p=self.root/'personal.yaml';p.write_text(yaml.safe_dump(profile_doc))
        self.assertIsNone(LocalProfile('personal',directory=self.root).home())
        profile_doc['home']={'realm_alias':'personal','realm_id':'realm:test','contexts':['scope']}
        p.write_text(yaml.safe_dump(profile_doc))
        with patch.object(LocalProfile,'resolve',return_value=(self.root,{'id':'realm:test'})):
            home=LocalProfile('personal',directory=self.root).home()
            self.assertEqual(home['scopes'],['scope'])
        with patch.object(LocalProfile,'resolve',return_value=(self.root,{'id':'realm:wrong'})):
            with self.assertRaises(ValueError):LocalProfile('personal',directory=self.root).home()

    def test_workspace_read_only_separate_owner_projections(self):
        calls=[]
        def context(scopes,**kwargs):
            calls.append(kwargs)
            return {'manifest':{'realm_id':'realm:test'},'records':[]}
        service=WorkspaceService(lambda:[{'realm_id':'realm:test','realm_alias':'personal','owner_projection':'personal','scopes':['scope'],'context':context}])
        result=service.start(task='develop my idea')
        self.assertEqual(result['contexts'][0]['owner_projection'],'personal')
        self.assertEqual(result['entry']['mutations'],0)
        self.assertFalse(result['entry']['retained'])
        self.assertEqual(calls[0]['task'],'develop my idea')
        self.assertEqual(WorkspaceService(lambda:[]).start()['status'],'unbound')
        with self.assertRaises(ValueError):WorkspaceService(lambda:[]).start(resume={'realm':'realm:test','id':'x','revision':1,'digest':'0'*64})

    def test_working_entries_are_pinned_reading_material_without_acceptance(self):
        ref = self.add('working', 'The selected prior result.')
        self.add('working', 'The newer result.', revision=2)
        route = {'realm_id':'realm:test', 'realm_alias':'personal', 'owner_projection':'personal',
                 'scopes':['scope'], 'context':self.app.context, 'working_entries':[ref]}
        result = WorkspaceService(lambda:[route]).start(task='unmatched')
        context = result['contexts'][0]
        self.assertEqual([ref], [x['reference'] for x in context['work_view']['selected_material']])
        self.assertFalse(context['work_view']['accepted_commitments'])
        self.assertFalse(context['records'][0]['governs'])
        self.assertTrue(WorkspaceService(lambda:[route]).start(budget=1)['blocked'])
        route['working_entries'] = [{**ref, 'realm':'realm:other'}]
        with self.assertRaises(ValueError): WorkspaceService(lambda:[route]).start()

    def test_historical_working_entry_uses_matching_snapshot_for_unpinned_grounds(self):
        self.add('basis', 'Original evidence.')
        old = self.add('subject', 'Original subject.', depends_on=['basis'])
        self.add('subject', 'New subject.', revision=2, depends_on=['basis'])
        self.add('basis', 'New evidence.', revision=2)
        result = self.app.context(['scope'],task='unmatched',focus=[old])
        self.assertFalse(result['blocked'])
        self.assertEqual({'Original evidence.','Original subject.'}, {r['body'] for r in result['records']})
        self.assertTrue(result['manifest']['incomplete'])
        self.assertIn('initial publication is not identified', result['warnings'][0])

    def test_unpinned_grounds_are_not_a_claim_about_first_publication(self):
        self.add('basis', 'First evidence.')
        old = self.add('subject', 'First subject.', depends_on=['basis'])
        self.add('basis', 'Later evidence.', revision=2)
        self.add('subject', 'Later subject.', revision=2)
        result = self.app.context(['scope'], task='unmatched', focus=[old])
        self.assertFalse(result['blocked'])
        self.assertEqual({'First subject.','Later evidence.'}, {r['body'] for r in result['records']})
        self.assertTrue(result['manifest']['incomplete'])
        self.assertIn('initial publication is not identified', result['warnings'][0])

    def test_history_index_resolves_like_a_full_historical_load(self):
        from unittest.mock import patch
        from ekk.adapters.history_index import HistoryIndex
        self.add('basis', 'Original evidence.')
        old = self.add('subject', 'Original subject.', depends_on=['basis'])
        self.add('subject', 'New subject.', revision=2, depends_on=['basis'])
        self.add('basis', 'New evidence.', revision=2)
        unindexed = self.app.context(['scope'], task='unmatched', focus=[old])
        def indexed():
            return RealmService(self.store, 'owner', lambda: '2026-09-07T12:00:00Z', codec=self.codec,
                                history_index=HistoryIndex(self.root / 'history'))
        first = indexed()
        self.assertEqual(unindexed, first.context(['scope'], task='unmatched', focus=[old]))
        # A later process resolves the pinned version without loading any past commit.
        later = indexed()
        current = later._load(self.store.snapshot())[-1]
        loaded = []
        original = RealmService._load
        def counting(service, snapshot, *, historical=False):
            loaded.append(snapshot['revision'])
            return original(service, snapshot, historical=historical)
        with patch.object(RealmService, '_load', counting):
            target = later._reference(old, current)
        self.assertEqual([], loaded)
        self.assertEqual(target, self.app._reference(old, self.app._load(self.store.snapshot())[-1]))
        self.assertEqual(unindexed, later.context(['scope'], task='unmatched', focus=[old]))

    def test_record_versions_follow_removal_and_recreation(self):
        from ekk.adapters.history_index import HistoryIndex
        first = self.add('subject', 'First.')
        second = self.add('subject', 'Second.', revision=2)
        self.add('other', 'Other.')
        path = self.app._load(self.store.snapshot())[-1]['subject']['path']
        self.app.apply(self.app.propose({path: None}), idempotency_key='remove')
        services = [RealmService(self.store, 'owner', lambda: '2026-09-07T12:00:00Z', codec=self.codec, **options)
                    for options in ({}, {'history_index': HistoryIndex(self.root / 'history')})]
        for service in services:
            current = service._load(self.store.snapshot())[-1]
            self.assertNotIn('subject', current)
            for ref, body in ((first, 'First.'), (second, 'Second.')):
                self.assertEqual(body, service._reference(ref, current)['body'].strip())
            self.assertEqual(services[0]._reference(second, current), service._reference(second, current))
            # A removed ID continues its history: the next revision is 3.
            stale = dict(schema='ekk.record/0.1', id='subject', title='subject', kind='note', scope=['scope'],
                         revision=1, created_at='2026-09-07T10:00:00Z', created_by='owner')
            with self.assertRaises(ValueError) as caught:
                service.apply(service.propose({'records/subject.md': self.codec.encode(stale, 'Again.')}), idempotency_key='stale')
            self.assertIn('recreated ID requires next historical revision', str(caught.exception))
        versions = services[1]._record_versions()
        self.assertEqual([1, 2], [row[0] for _, _, row in versions.ranges['subject']])
        self.assertFalse(versions.broken)
        services[1].apply(services[1].propose({'records/subject.md': self.codec.encode({**stale, 'revision': 3}, 'Again.')}), idempotency_key='again')
        self.assertEqual('Again.', self.app._load(self.store.snapshot())[-1]['subject']['body'].strip())

    def test_history_index_fingerprint_follows_the_loader_and_nothing_else(self):
        from ekk.adapters import history_index
        fingerprint = history_index.loader_fingerprint()
        self.assertEqual(fingerprint, history_index.loader_fingerprint())
        # Ranking, entry and every other method of the service leave the index warm.
        def context(self, scopes, **options): return 'another ranking'
        def apply(self, proposal, **options): return 'another write path'
        with patch.object(RealmService, 'context', context), patch.object(RealmService, 'apply', apply):
            self.assertEqual(fingerprint, history_index.loader_fingerprint())
        # What decides whether and how a historical commit loads makes it cold.
        original = RealmService._load
        def _load(self, snapshot, *, historical=False): return original(self, snapshot, historical=historical)
        with patch.object(RealmService, '_load', _load):
            self.assertNotEqual(fingerprint, history_index.loader_fingerprint())
        with patch.object(RealmService, '_roots', staticmethod(lambda realm: realm.get('storage', {}))):
            self.assertNotEqual(fingerprint, history_index.loader_fingerprint())
        read = Path.read_bytes
        for module in ('model/methods.py', 'model/__init__.py', 'adapters/markdown.py'):
            def edited(path, module=module):
                return read(path) + (b'\n# changed rule\n' if path.as_posix().endswith('ekk/' + module) else b'')
            with self.subTest(module=module), patch.object(Path, 'read_bytes', edited):
                self.assertNotEqual(fingerprint, history_index.loader_fingerprint())
        for library in ('jsonschema', 'rfc3339-validator'):
            versions = lambda name, library=library: 'other' if name == library else 'same'
            with self.subTest(library=library), patch.object(history_index, '_distribution_version', versions):
                with_other = history_index.loader_fingerprint()
            with patch.object(history_index, '_distribution_version', lambda name: 'same'):
                self.assertNotEqual(with_other, history_index.loader_fingerprint())
        self.assertEqual(fingerprint, history_index.loader_fingerprint())

    def test_alias_search_returns_all_readable_ids_and_rename_keeps_identity(self):
        first = self.add('first', 'body', aliases=['unique-alias'])
        second = self.add('second', 'body', aliases=['unique-alias'])
        hits = self.app.search_records(['scope'], query='unique-alias')['results']
        self.assertCountEqual([first, second], [hit['reference'] for hit in hits])
        self.assertCountEqual(['first','second'], [r['id'] for r in self.app.context(['scope'],task='unique-alias')['records']])
        metadata = self.app.fetch_record(['scope'], first)['metadata']
        self.app.apply(self.app.propose({'records/first.md':None, 'records/renamed.md':self.codec.encode(metadata,'body')}), idempotency_key='rename')
        self.assertEqual('records/renamed.md', self.app.fetch_record(['scope'], first)['path'])

    def test_home_cwd_restriction_and_denied_binding_never_becomes_personal(self):
        doc = {'schema':'ekk.profile/0.1','uid':os.getuid(),'realms':{},
               'home':{'realm_alias':'personal','realm_id':'realm:test','contexts':['scope'],
                       'cwd_roots':[str(self.root/'personal')]}}
        (self.root/'personal.yaml').write_text(yaml.safe_dump(doc))
        with patch.object(LocalProfile,'resolve',return_value=(self.root,{'id':'realm:test'})):
            profile = LocalProfile('personal',directory=self.root)
            self.assertIsNone(profile.home(cwd=self.root/'company'))
            self.assertIsNotNone(profile.home(cwd=self.root/'personal'/'ideas'))
            self.assertIsNotNone(profile.home(cwd=self.root/'company',explicit=True))
        with patch('ekk.adapters.command_line.binding',return_value=(self.root,{})), patch('ekk.adapters.command_line._routes',side_effect=PermissionError('denied')), patch('ekk.adapters.command_line.LocalProfile') as factory:
            with self.assertRaises(PermissionError):dispatch(parser().parse_args(['enter','--personal']),{})
            factory.assert_not_called()

    def test_cli_home_only_unbound_or_explicit_personal(self):
        class Profile:
            def __init__(self,*args):pass
            def home(inner, **kwargs):return {'path':self.root,'alias':'personal','manifest':{'id':'realm:test'},'scopes':['scope']}
            def workspace(inner, cwd):raise ValueError('Workspace binding absent')
        def parse(*extra):return parser().parse_args(['enter','--cwd',str(self.root),'--task','idea',*extra])
        with patch('ekk.adapters.command_line.LocalProfile',Profile),patch('ekk.adapters.command_line.binding',return_value=None),patch('ekk.adapters.command_line.service',return_value=self.app):
            result=dispatch(parse(),{})
            self.assertEqual(result['contexts'][0]['owner_projection'],'personal')
            ref=self.add('continue','prior intention')
            import json
            resumed=dispatch(parse('--resume',json.dumps(ref)),{})
            self.assertEqual(resumed['contexts'][0]['manifest']['forced_refs'],[ref])
        route={'path':self.root,'alias':'work','scopes':['scope']}
        with patch('ekk.adapters.command_line.LocalProfile',Profile),patch('ekk.adapters.command_line.binding',return_value=(self.root,{})),patch('ekk.adapters.command_line._routes',return_value=[dict(route)]),patch('ekk.adapters.command_line.service',return_value=self.app),patch('ekk.adapters.command_line.cache_context',return_value={}):
            result=dispatch(parse(),{})
            self.assertEqual(result['schema'],'ekk.context/0.1')
            result=dispatch(parse('--personal'),{})
            self.assertEqual([r['owner_projection'] for r in result['contexts']],['shared','personal'])

class WorkspaceOptionTests(unittest.TestCase):
    def setUp(self):
        isolate(self)

    def test_resume_and_personal_options_fail_before_mutation(self):
        for options in [['init','--personal'],['enter','--resume','null'],['enter','--resume','']]:
            args=parser().parse_args(options)
            with patch('ekk.adapters.command_line.service') as factory, self.assertRaises(ValueError):
                dispatch(args,{})
            factory.assert_not_called()

    def test_unbound_without_home_does_not_open_store(self):
        with patch('ekk.adapters.command_line.binding',return_value=None), patch('ekk.adapters.command_line.LocalProfile') as profile, patch('ekk.adapters.command_line.service') as factory:
            profile.return_value.home.return_value=None
            result=dispatch(parser().parse_args(['enter','--task','new idea']),{})
            self.assertEqual(result['status'],'unbound')
            factory.assert_not_called()

if __name__=='__main__':unittest.main()
