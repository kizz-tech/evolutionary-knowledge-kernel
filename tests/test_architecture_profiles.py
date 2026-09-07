import os
from pathlib import Path
import tempfile
import unittest
import yaml
from ekk.adapters.local_profile import LocalProfile, binding
from ekk.adapters.sqlite_index import SQLiteIndex,index_key

class ProfilesTests(unittest.TestCase):
    def test_role_alias_and_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);r=p/'store';(r/'.ekk').mkdir(parents=True)
            (r/'.ekk/realm.yaml').write_text('id: personal-id\n')
            (p/'company.yaml').write_text(yaml.safe_dump({'schema':'ekk.profile/0.1','uid':os.getuid(),'realms':{'company':{'id':'company-id','path':str(r)}}}))
            role=LocalProfile('company',directory=p)
            with self.assertRaisesRegex(ValueError,'unavailable'):role.resolve('personal')
            with self.assertRaisesRegex(ValueError,'identity'):role.resolve('company')
    def test_nested_bindings_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);child=root/'child'
            for r in [root,child]:
                (r/'.ekk').mkdir(parents=True)
                (r/'.ekk/workspace.yaml').write_text('schema: ekk.workspace/0.1\n')
            with self.assertRaisesRegex(ValueError,'Ambiguous'):binding(child)
    def test_index_rebuild_and_permission_snapshot_key(self):
        with tempfile.TemporaryDirectory() as d:
            idx=SQLiteIndex(Path(d)/'index.sqlite')
            key=index_key(realm='r',grant='g',snapshot='one',policy='p',packs=[])
            idx.rebuild([{'id':'r1','title':'hello','body':'world'}],key=key)
            self.assertEqual(idx.search('world',key=key),['r1'])
            with self.assertRaisesRegex(ValueError,'stale'):idx.search('world',key='different-policy')
            idx.path.unlink()
            idx.rebuild([{'id':'r1','title':'hello','body':'world'}],key=key)
            self.assertEqual(idx.search('world',key=key),['r1'])
    def test_nested_git_project_does_not_inherit_parent_binding(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();child=root/'child'
            (root/'.ekk').mkdir();(root/'.ekk/workspace.yaml').write_text('schema: ekk.workspace/0.1\n')
            (child/'.git').mkdir(parents=True)
            self.assertIsNone(binding(child))
    def test_published_contained_identity_resolves_repeatedly(self):
        import subprocess
        from unittest.mock import patch
        from ekk.adapters.command_line import service
        from ekk.adapters.local_profile import published_manifest
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();repo=root/'repo';realm=repo/'knowledge'
            repo.mkdir();(realm/'.ekk').mkdir(parents=True)
            (realm/'.ekk/realm.yaml').write_text('id: contained-identity\n')
            for args in [('init',),('config','user.name','Test'),('config','user.email','test@example.invalid'),('add','knowledge'),('commit','-m','Reviewed baseline')]:
                subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
            with patch.dict(os.environ,{'EKK_DATA_HOME':str(root/'runtime')}):
                first=service(realm).store.snapshot()
                second=service(realm).store.snapshot()
                self.assertEqual(first,second)
                self.assertEqual(published_manifest(realm)['id'],'contained-identity')
                (realm/'.ekk/realm.yaml').write_text('id: forged-identity\n')
                with self.assertRaisesRegex(ValueError,'published identity'):published_manifest(realm)
