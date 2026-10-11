"""Declared-package assembly and readback use disposable files and real stores."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.command_line import content_key, retention_payload, service
from ekk.adapters.retention import retain_once
from ekk.adapters.result_manifest import assemble_manifest, preflight_payload, verify_manifest


class ResultManifestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root / 'data'),
            'EKK_CONFIG_HOME': str(self.root / 'config'), 'EKK_CACHE_HOME': str(self.root / 'cache')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.manifest = self.root / 'manifest.json'
        (self.root / 'result.md').write_bytes('Exact result\r\n\u0420\u0443\u0441\u0441\u043a\u0438\u0439 \u0442\u0435\u043a\u0441\u0442\n'.encode())
        (self.root / 'original.bin').write_bytes(b'exact\x00\xff\r\n')
        self.document = {'schema': 'ekk.result-manifest/0.1', 'title': 'Research result',
                         'result_file': 'result.md', 'artifacts': [{'path': 'original.bin'}]}
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.document))

    def payload(self, package):
        return retention_payload(package['artifacts'], title=package['title'], body=package['body'])

    def test_exact_bytes_relative_paths_inventory_and_content_identity(self):
        package = assemble_manifest(self.manifest)
        self.assertEqual(package['body'].encode(), (self.root / 'result.md').read_bytes())
        self.assertEqual(package['artifacts'], [{'data': b'exact\x00\xff\r\n', 'filename': 'original.bin'}])
        self.assertEqual(package['inventory'][1]['sha256'], 'sha256:' + hashlib.sha256(b'exact\x00\xff\r\n').hexdigest())
        payload = self.payload(package)
        first = content_key('retain', 'realm', ['scope'], payload)
        self.assertEqual(first, content_key('retain', 'realm', ['scope'], self.payload(assemble_manifest(self.manifest))))
        (self.root / 'original.bin').write_bytes(b'changed')
        self.assertNotEqual(first, content_key('retain', 'realm', ['scope'], self.payload(assemble_manifest(self.manifest))))
        self.assertEqual(package['artifacts'][0]['data'], b'exact\x00\xff\r\n')
        self.assertEqual(package['inventory'][1]['size'], 9)

    def test_missing_directory_and_symlink_rejected(self):
        for path in ('missing', 'directory', 'link', 'parent-link/original.bin'):
            with self.subTest(path=path):
                (self.root / 'directory').mkdir(exist_ok=True)
                if not (self.root / 'link').exists():
                    (self.root / 'link').symlink_to(self.root / 'original.bin')
                    (self.root / 'parent-link').symlink_to(self.root, target_is_directory=True)
                self.document['artifacts'] = [{'path': path}]; self.write_manifest()
                with self.assertRaises((OSError, ValueError)):
                    assemble_manifest(self.manifest)

    def test_invalid_manifest_cannot_control_route_or_commands(self):
        for field, value in [('realm', 'other'), ('scope', ['other']), ('command', 'execute'),
                             ('schema', 'ekk.result-manifest/99'), ('artifacts', [{'path': '*.bin'}])]:
            document = copy.deepcopy(self.document)
            document[field] = value
            self.manifest.write_text(json.dumps(document))
            with self.subTest(field=field), self.assertRaises(ValueError):
                assemble_manifest(self.manifest)
        self.manifest.write_text('{"schema":"ekk.result-manifest/0.1","schema":"other"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            assemble_manifest(self.manifest)

    def test_duplicate_paths_names_and_hardlinks_rejected(self):
        (self.root / 'hardlink').hardlink_to(self.root / 'original.bin')
        (self.root / 'other.bin').write_bytes(b'other')
        cases = [ [{'path': 'original.bin'}, {'path': './original.bin', 'filename': 'alias'}],
                  [{'path': 'original.bin'}, {'path': 'other.bin', 'filename': 'original.bin'}],
                  [{'path': 'original.bin'}, {'path': 'hardlink'}] ]
        for artifacts in cases:
            self.document['artifacts'] = artifacts; self.write_manifest()
            with self.subTest(artifacts=artifacts), self.assertRaisesRegex(ValueError, 'Duplicate'):
                assemble_manifest(self.manifest)

    def test_change_during_assembly_rejected_before_any_writer(self):
        from ekk.adapters import result_manifest
        original = result_manifest._read_regular
        def changed(path, **kwargs):
            result = original(path, **kwargs)
            if path.name == 'original.bin':
                (self.root / 'result.md').write_bytes(b'changed after first read')
            return result
        with patch.object(result_manifest, '_read_regular', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed during assembly'):
                assemble_manifest(self.manifest)

    def test_change_while_reading_and_result_symlink_rejected(self):
        from ekk.adapters import result_manifest
        original = os.fstat
        calls = []
        def mutate(fd):
            calls.append(fd)
            if len(calls) == 2:
                (self.root / 'original.bin').write_bytes(b'replaced during read')
            return original(fd)
        with patch.object(result_manifest.os, 'fstat', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed while reading'):
                result_manifest._read_regular(self.root / 'original.bin')
        (self.root / 'result-link').symlink_to(self.root / 'result.md')
        self.document['result_file'] = 'result-link'; self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'regular'):
            assemble_manifest(self.manifest)

    def test_count_utf8_body_and_capacity_limits(self):
        self.document['artifacts'] = [{'path': 'original.bin'}] * 33; self.write_manifest()
        with self.assertRaisesRegex(ValueError, '32'):
            assemble_manifest(self.manifest)
        self.document['artifacts'] = []; self.write_manifest()
        (self.root / 'result.md').write_bytes(b'\xff')
        with self.assertRaisesRegex(ValueError, 'UTF-8'):
            assemble_manifest(self.manifest)
        (self.root / 'result.md').write_bytes(b'x' * (2 * 1048576 + 1))
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            assemble_manifest(self.manifest)
        payload = {'title': 'Result', 'body': 'Result', 'artifacts': [{'base64': 'x' * (16 * 1048576)}]}
        with self.assertRaisesRegex(ValueError, '--wait'):
            preflight_payload(payload, route={'realm': 'exact'})
        self.assertEqual(preflight_payload(payload, wait=True)['mode'], 'synchronous')
        with self.assertRaisesRegex(ValueError, 'route'):
            preflight_payload(payload)

    def app_and_receipt(self, package):
        app = service(self.root / 'realm')
        app.init('Test', realm_id=app.initial_realm_id, context_id='scope')
        receipt = retain_once(app, package['artifacts'], title=package['title'], body=package['body'],
                              scopes=['scope'], key='declared-package')
        return app, receipt

    def verify(self, app, package, receipt, **ports):
        return verify_manifest(package, receipt,
            read_source=ports.get('read_source', lambda ref, **kwargs: app.read_source(['scope'], ref, **kwargs)),
            fetch_result=ports.get('fetch_result', lambda ref: app.fetch_record(['scope'], ref, max_bytes=1048576)))

    def test_real_writer_all_declared_bytes_readback_and_frozen_source(self):
        # No implicit source for the result body, and unrelated files stay outside.
        (self.root / 'unrelated-secret').write_bytes(b'not selected')
        (self.root / 'large.bin').write_bytes(b'chunk' * 60000)
        self.document['artifacts'].append({'path': 'large.bin', 'title': 'Exact log'}); self.write_manifest()
        package = assemble_manifest(self.manifest)
        (self.root / 'original.bin').unlink()
        app, receipt = self.app_and_receipt(package)
        receipt['source_references'].reverse()  # Receipt order is not declaration order.
        result = self.verify(app, package, receipt)
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(result['verified'], 3)
        self.assertEqual(len(receipt['source_references']), 2)
        self.assertEqual([item['state'] for item in result['inventory']], ['verified'] * 3)
        self.assertNotIn(b'not selected', app.store.snapshot()['files'].values())

    def test_pending_partial_and_bad_digest_never_claim_complete(self):
        package = assemble_manifest(self.manifest)
        pending = verify_manifest(package, {'state': 'local_pending'},
                                  read_source=lambda *a, **k: self.fail('Not published'),
                                  fetch_result=lambda *a: self.fail('Not published'))
        self.assertEqual(pending['state'], 'pending')
        app, receipt = self.app_and_receipt(package)
        with patch.object(app, 'read_source', side_effect=PermissionError('Current access unavailable')):
            partial = self.verify(app, package, receipt)
        self.assertEqual(partial['state'], 'partial')
        self.assertEqual(partial['inventory'][1]['state'], 'pending')
        self.assertEqual(partial['unavailable_sources'][0]['error'], 'Current access unavailable')
        changed = copy.deepcopy(package); changed['inventory'][1]['sha256'] = 'sha256:' + '0' * 64
        self.assertEqual(self.verify(app, changed, receipt)['inventory'][1]['state'], 'unavailable')
        def wrong_body(ref):
            row = app.fetch_record(['scope'], ref)
            return {**row, 'body': 'wrong'}
        self.assertEqual(self.verify(app, package, receipt, fetch_result=wrong_body)['state'], 'partial')


if __name__ == '__main__':
    unittest.main()
