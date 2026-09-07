import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from ekk.realm_registry import RealmRegistry
from ekk.realm_cli import main as realm_main
from ekk.cli import main
from ekk.realms import RealmStore, Grant
from ekk.kernel import KernelError

class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name).resolve()
        self.registry=RealmRegistry(self.p/'registry.yaml');self.registry.initialize('owner')
        self.store=RealmStore.create(self.p/'store','fixture:one',grants=[Grant('owner',('*',),audiences=('*',))])
        self.registry.register(self.p/'store');(self.p/'project').mkdir()
        self.registry.bind(self.p/'project','fixture:one',['fixture:work'])
    def tearDown(self):self.tmp.cleanup()
    def test_location_identity_and_no_implicit_union(self):
        ref=self.store.session('owner').contribute('one',scopes=['fixture:work'])
        shutil.move(self.p/'store',self.p/'moved');self.registry.relocate('fixture:one',self.p/'moved')
        session,binding=self.registry.route(self.p/'project')
        self.assertEqual(session.view(scopes=binding['scopes']).get(ref)['body'],'one')
        (self.p/'unknown').mkdir();self.assertIsNone(self.registry.route(self.p/'unknown'))
    def test_local_os_identity_not_client_principal(self):
        with patch('ekk.realm_registry.os.getuid',return_value=os.getuid()+1):
            with self.assertRaises(KernelError):self.registry.route(self.p/'project')
    def test_cli_routes_governed_and_denies_legacy_fallback(self):
        with patch.dict(os.environ,{'EKK_REALM_REGISTRY':str(self.registry.path),'EKK_CONFIG':str(self.p/'no-legacy')}):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['enter','--cwd',str(self.p/'project')]),0)
            self.assertEqual(json.loads(out.getvalue())['runtime'],'governed/3')
            original=Path.cwd()
            try:
                os.chdir(self.p/'project')
                with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(main(['compile','--scope','fixture:work']),2)
            finally:os.chdir(original)
    def test_malformed_registry_fails_closed(self):
        for value in ('invalid: [', 'schema: ekk.realm-registry/1\nrealms: {}\nprojects: []\nidentity: nope\n'):
            self.registry.path.write_text(value)
            with self.assertRaises(KernelError):self.registry.route(self.p/'project')

    def test_cli_contribution_and_adoption(self):
        f=self.p/'input.md';f.write_text('rule')
        prefix=['--registry',str(self.registry.path)]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(realm_main(prefix+['contribute','--cwd',str(self.p/'project'),str(f)]),0)
        ref=json.loads(out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(realm_main(prefix+['adopt','--cwd',str(self.p/'project'),'--ref',json.dumps(ref),'--predicate','standard']),0)
        cfg=self.registry.load();cfg['projects'][0]['retention']='read-only';self.registry._write(cfg)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(realm_main(prefix+['contribute','--cwd',str(self.p/'project'),str(f)]),2)

if __name__=='__main__':unittest.main()
