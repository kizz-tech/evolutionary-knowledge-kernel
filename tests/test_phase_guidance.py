"""Optional phase guidance boundaries; these checks do not establish field benefit."""
import base64
from contextlib import redirect_stdout
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ekk.application.practices import PRACTICES, PHASES, practice
from ekk.adapters import activity_cli
from ekk.adapters.practical_methods import artifact, registry, spec


class PhaseGuidanceTests(unittest.TestCase):
    def test_each_phase_is_independent_of_domain_and_not_a_pipeline(self):
        for domain in PRACTICES:
            for phase in PHASES:
                with self.subTest(domain=domain, phase=phase):
                    guide=practice(domain, {'local_edit':True, 'context_sufficient':True}, phase=phase)
                    self.assertEqual((domain, phase), (guide['domain'], guide['phase']))
                    self.assertEqual('direct_local_work', guide['route'])
                    self.assertEqual(0, guide['ekk_calls_required'])
                    self.assertFalse(guide['pipeline_required'])
                    self.assertFalse(guide['retention_required'])
                    self.assertEqual('unknown', guide['observed_benefit'])
                    self.assertEqual({'decision','output','experience_use','evidence','stop_when'},
                                     set(guide['phase_guidance']))

    def test_original_guides_and_method_artifact_identities_remain_exact(self):
        digests={'software':'63f22e00e478b7d15aabb077837d088f6f589b1adcfdfa8442055b69d24a8854',
                 'research':'fabfd54d9db91a20c3f6c7e355819187be328cd27533aae2385c7037644bd5d3',
                 'personal':'203fe6323bca9095bc79d746c5aa865451c7bbbce2353f50705b077156f5b76c'}
        for domain, digest in digests.items():
            guide=practice(domain)
            self.assertNotIn('phase', guide)
            self.assertNotIn('phase_guidance', guide)
            self.assertEqual(digest, spec(domain)['artifact_digest'])
            self.assertEqual('1', spec(domain)['adapter_version'])
            self.assertEqual([], spec(domain)['privileges'])
            self.assertEqual(guide, registry()['builtin:'+domain+'-work'].run(artifact(domain), {}))

    def test_guidance_results_do_not_mutate_shared_definitions(self):
        guide=practice('personal', phase='design')
        guide['phase_guidance']['evidence'].clear()
        self.assertTrue(practice('personal', phase='design')['phase_guidance']['evidence'])

    def test_unknown_phase_and_phase_in_request_are_rejected(self):
        with self.assertRaises(ValueError):practice('software', phase='deploy')
        with self.assertRaises(ValueError):practice('software', {'phase':'planning'})

    def test_cli_phase_show_never_resolves_a_realm(self):
        output=io.StringIO()
        with patch.object(activity_cli,'resolve',side_effect=AssertionError('Unexpected realm lookup')), \
             patch('ekk.adapters.operation_diagnostics.observed_call',side_effect=lambda name, call, **kw:call()), \
             redirect_stdout(output):
            self.assertEqual(0, activity_cli.main('guide',['show','--domain','personal','--phase','research']))
        result=json.loads(output.getvalue())
        self.assertEqual(('personal','research',0), (result['domain'],result['phase'],result['ekk_calls_required']))

    def test_list_exposes_domains_and_phases_without_package_identity_change(self):
        listed=activity_cli.execute('guide',SimpleNamespace(operation='list',phase=None),{})
        self.assertEqual(list(PRACTICES),listed['domains'])
        self.assertEqual(list(PHASES),listed['phases'])
        for domain in PRACTICES:
            args=SimpleNamespace(operation='package',domain=domain,phase=None)
            package=activity_cli.execute('guide',args,{})
            self.assertEqual(artifact(domain),base64.b64decode(package['artifact_base64']))
            self.assertEqual(spec(domain),package['spec'])
            args.phase='design'
            with self.assertRaises(ValueError):activity_cli.execute('guide',args,{})


if __name__=='__main__':unittest.main()
