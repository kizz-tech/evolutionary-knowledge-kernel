from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml
from ekk.integration import bind_project, enter_project, load_config, global_root
from ekk.kernel import Kernel, KernelError


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.config = self.base/'config.yaml'
        self.root = self.base/'knowledge'
        Kernel(self.root).init()
        self.config.write_text(yaml.safe_dump(dict(schema='ekk.integration/1', root=str(self.root), projects=[])))
        self.env = patch.dict(os.environ, {'EKK_CONFIG':str(self.config)})
        self.env.start(); self.addCleanup(self.env.stop)
        self.project = self.base/'project'; self.project.mkdir()
        subprocess.run(['git','init','-q',str(self.project)],check=True)

    def test_unbound_entry_does_not_mutate_registry_or_knowledge(self):
        before = self.config.read_bytes()
        self.assertEqual(enter_project(self.project)['status'], 'unbound')
        self.assertEqual(before,self.config.read_bytes())
        self.assertEqual(Kernel(self.root).check()['records'],0)

    def test_binding_stable_across_calls_and_subdirectories(self):
        first = bind_project(self.project)
        self.assertEqual(bind_project(self.project)['binding'],first['binding'])
        sub = self.project/'src';sub.mkdir()
        self.assertEqual(enter_project(sub)['binding'], first['binding'])
        self.assertEqual(global_root(), self.root)

    def test_nested_repo_does_not_inherit_parent_binding(self):
        bind_project(self.project)
        nested = self.project/'vendor';nested.mkdir()
        subprocess.run(['git','init','-q',str(nested)],check=True)
        self.assertEqual(enter_project(nested)['status'],'unbound')
        sub = nested/'src';sub.mkdir()
        self.assertEqual(enter_project(sub)['status'],'unbound')

    def test_other_project_gets_no_scope(self):
        bind_project(self.project)
        other=self.base/'other';other.mkdir()
        self.assertIsNone(enter_project(other)['context'])

    def test_explicit_wrong_root_fails(self):
        bind_project(self.project)
        with self.assertRaisesRegex(KernelError,'differs'):
            enter_project(self.project,root=self.base/'other')

    def test_refuse_audience_expansion_and_binding_reassignment(self):
        with self.assertRaises(KernelError):bind_project(self.project,audience='company')
        bind_project(self.project,scopes=['project:a'])
        with self.assertRaises(KernelError):bind_project(self.project,scopes=['project:b'])

    def test_unknown_config_and_duplicate_binding_fail(self):
        bind_project(self.project)
        cfg=yaml.safe_load(self.config.read_text());cfg['projects']*=2
        self.config.write_text(yaml.safe_dump(cfg))
        with self.assertRaisesRegex(KernelError,'Duplicate'):load_config()
        cfg['schema']='ekk.integration/99';self.config.write_text(yaml.safe_dump(cfg))
        with self.assertRaisesRegex(KernelError,'Unsupported'):load_config()

    def test_scoped_context_excludes_other_project(self):
        bind_project(self.project,scopes=['project:a'])
        source=self.base/'note.md';source.write_text('private project B')
        Kernel(self.root).observe(source,'B',['project:b'],'human')
        self.assertEqual(enter_project(self.project)['context']['records'],[])

    def test_cli_full_project_entry_from_another_directory(self):
        import json
        import sys
        env=dict(os.environ);env.pop('EKK_ROOT',None)
        def cli(*args):
            result=subprocess.run([sys.executable,'-m','ekk',*args],cwd=self.project,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(cli('enter')['status'],'unbound')
        binding=cli('project-bind','--path',str(self.project),'--audience','self','--retention','significant')['binding']
        source=self.base/'thought.md';source.write_text('Meaningful input')
        captured=cli('observe',str(source),'--title','Thought','--author','human','--scope',binding['scopes'][0])
        context=cli('enter','--task','Thought')
        self.assertEqual(context['status'],'ready')
        self.assertIn(captured['id'],[r['id'] for r in context['context']['records']])
        self.assertEqual(cli('--root',str(self.root),'check')['status'],'valid')

    def test_cli_global_route_rejects_unbound_other_scope_and_readonly_writes(self):
        import sys
        env=dict(os.environ);env.pop('EKK_ROOT',None)
        def cli(*args):
            return subprocess.run([sys.executable,'-m','ekk',*args],cwd=self.project,env=env,capture_output=True,text=True)
        source=self.base/'note.md';source.write_text('private')
        result=cli('compile','--scope','project:a')
        self.assertEqual(result.returncode,2);self.assertIn('Unbound',result.stderr)
        bind_project(self.project,scopes=['project:a'],retention='read-only')
        result=cli('observe',str(source),'--title','No','--author','human','--scope','project:a')
        self.assertEqual(result.returncode,2);self.assertIn('read-only',result.stderr)
        result=cli('compile','--scope','project:b')
        self.assertEqual(result.returncode,2);self.assertIn('outside',result.stderr)
        self.assertEqual(Kernel(self.root).check()['records'],0)
        captured=Kernel(self.root).observe(source,'Other',['project:b'],'human')
        result=cli('get',captured['id'])
        self.assertEqual(result.returncode,2);self.assertIn('outside',result.stderr)
        result=cli('--root',str(self.root),'check')
        self.assertEqual(result.returncode,0,result.stderr)
