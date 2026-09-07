"""Installed CLI boundary: JSON arguments reach the lifecycle with no implicit adoption."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from ekk.adapters.builtin_methods import spec, REFERENCE


class MethodCliTests(unittest.TestCase):
    def test_json_lifecycle_and_quarantine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {k:v for k,v in os.environ.items() if not k.startswith('EKK_')}
            env.update(EKK_CONFIG_HOME=str(root/'config'), EKK_DATA_HOME=str(root/'runtime'))
            def call(args, request=None, expected=0):
                result = subprocess.run([sys.executable, '-m', 'ekk', *args],
                    input=json.dumps(request) if request is not None else None,
                    text=True, capture_output=True, cwd=root, env=env)
                self.assertEqual(result.returncode, expected, result.stderr)
                return json.loads(result.stdout if expected == 0 else result.stderr)
            call(['init', '--root', str(root/'realm'), '--title', 'CLI fixture'])
            def method(operation, request, expected=0):
                return call(['method', operation, '--root', str(root/'realm')], request, expected)
            candidate = method('propose', {'method_id':'method:cli', 'title':'CLI method',
                'spec':spec(REFERENCE), 'artifact_base64':base64.b64encode(REFERENCE).decode(),
                'explanation':'Check the public CLI boundary.', 'key':'candidate'})
            reference = candidate['method']
            facts = {'task_family':'handoff','environment':'synthetic-local','model':'none'}
            use = {'reference':reference, 'request':{'question':'Continue?', 'source_id':'fixture:one',
                   'source_text':'Synthetic text', 'source_disclosure':False},'facts':facts,'key':'run'}
            self.assertEqual(method('use', use, 2)['error'], 'method_request_failed')
            evaluation = method('evaluate', {'reference':reference,'facts':facts,'case_id':'private-change','key':'evaluation'})
            method('admit', {'reference':reference,'evidence':evaluation['evidence'],
                'explanation':'Accept independently evaluated fixture.', 'key':'admit'})
            result = method('use', use)
            self.assertNotIn('excerpt', result['output'])
            self.assertTrue(method('inspect', {'reference':reference})['local_admission']['active'])
            method('quarantine', {'reference':reference,'reason':'End the fixture admission.'})
            method('use', use, 2)


if __name__ == '__main__':
    unittest.main()
