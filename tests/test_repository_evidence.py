"""Current project checks use owner-configured paths, never retrieved paths."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.repository_evidence import check_repository


class RepositoryEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.source=self.root/'contract.py'; self.source.write_bytes(b'current bytes\n')
        self.digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.binding={'workspace_id':'workspace:test','evidence_checks':[{'id':'contract','path':'contract.py'}]}
        self.metadata={'id':'result:test','kind':'outcome','title':'Result','revision':1,
            'repository_evidence':{'workspace_id':'workspace:test','files':[{'check':'contract','sha256':self.digest}]}}
        self.context={'manifest':{'realm_id':'realm:test'},'records':[{'id':'result:test','digest':'a'*64,'metadata':self.metadata}]}

    def test_exact_bytes_then_changed_bytes_are_observations_not_truth(self):
        first=check_repository(self.context,self.root,self.binding)
        self.assertEqual('matches',first['checks'][0]['status'])
        self.assertEqual('not_inferred',first['claim_truth'])
        self.source.write_bytes(b'changed bytes\n')
        second=check_repository(self.context,self.root,self.binding)
        self.assertEqual('changed',second['checks'][0]['status'])
        self.assertEqual(self.digest,second['checks'][0]['expected_sha256'])
        self.assertTrue(second['checks'][0]['checked_at'])
        self.assertEqual('none',second['authority_effect'])

    def test_unconfigured_check_and_foreign_workspace_do_not_read_or_echo_paths(self):
        self.metadata['repository_evidence']['files']=[{'check':'../../secret','sha256':self.digest}]
        result=check_repository(self.context,self.root,self.binding)
        self.assertTrue(result['incomplete']); self.assertEqual([],result['checks'])
        self.assertNotIn('secret',json.dumps(result))
        self.metadata['repository_evidence']['workspace_id']='workspace:foreign'
        self.assertEqual([],check_repository(self.context,self.root,self.binding)['checks'])

    def test_missing_or_symlinked_configured_source_is_unknown(self):
        self.source.unlink()
        result=check_repository(self.context,self.root,self.binding)
        self.assertEqual('unavailable',result['checks'][0]['status'])
        outside=self.root/'outside'; outside.write_bytes(b'private')
        self.source.symlink_to(outside)
        result=check_repository(self.context,self.root,self.binding)
        self.assertIsNone(result['checks'][0]['observed_sha256'])
        self.assertNotIn('private',json.dumps(result))

    def test_intermediate_directory_swap_cannot_read_outside_configured_root(self):
        reports = self.root / 'reports'; reports.mkdir()
        self.source.rename(reports / 'contract.py')
        self.binding['evidence_checks'][0]['path'] = 'reports/contract.py'
        outside = self.root / 'outside'; outside.mkdir()
        (outside / 'contract.py').write_bytes(b'outside fixture')
        open_file = os.open
        def swap(component, flags, *args, **kwargs):
            if component == 'reports':
                reports.rename(self.root / 'original-reports')
                reports.symlink_to(outside, target_is_directory=True)
            return open_file(component, flags, *args, **kwargs)
        with patch('ekk.adapters.repository_evidence.os.open', side_effect=swap):
            result = check_repository(self.context, self.root, self.binding)
        self.assertTrue(result['incomplete'])
        self.assertEqual('unavailable', result['checks'][0]['status'])
        self.assertIsNone(result['checks'][0]['observed_sha256'])

    def test_no_declaration_leaves_current_world_unknown(self):
        del self.metadata['repository_evidence']
        result=check_repository(self.context,self.root,self.binding)
        self.assertEqual([],result['checks'])
        self.assertEqual('no applicable repository checks observed',result['coverage'])

    def test_owner_configuration_cannot_traverse_outside_project(self):
        self.binding['evidence_checks'][0]['path']='../secret'
        result=check_repository(self.context,self.root,self.binding)
        self.assertTrue(result['incomplete']); self.assertEqual([],result['checks'])


if __name__=='__main__': unittest.main()
