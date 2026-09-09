"""Publication, uncertainty and discovery contracts on disposable real stores."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.command_line import capture_once, dispatch, parser, service
from ekk.adapters.retention import retain_once
from ekk.adapters.operation_diagnostics import journal
from ekk.model import Conflict, DirtyWorkingTree, IdempotencyConflict, RecoveryConflict


class RetentionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root/'data'),
            'EKK_CONFIG_HOME': str(self.root/'config'), 'EKK_CACHE_HOME': str(self.root/'cache')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.app = service(self.root/'realm')
        self.app.init('Test', realm_id=self.app.initial_realm_id, context_id='scope')

    def capture(self, key='capture', **kwargs):
        return capture_once(self.app, b'exact\r\nsource\x00\xff', title='Synthetic source',
                            scopes=['scope'], filename='original.bin', key=key, **kwargs)

    def test_additive_stale_base_preserves_ids_bytes_competing_write_and_key(self):
        original = self.app.apply
        attempted = []
        competing = self.app.capture(b'concurrent', title='Concurrent', scope=['scope'])
        def interleaved(proposal, **kwargs):
            attempted.append(proposal)
            if len(attempted) == 1:
                original(competing, idempotency_key='competing')
            return original(proposal, **kwargs)
        with patch.object(self.app, 'apply', side_effect=interleaved):
            receipt = self.capture()
        self.assertEqual(2, len(attempted))
        self.assertEqual(attempted[0]['changes'], attempted[1]['changes'])
        self.assertNotEqual(attempted[0]['base'], attempted[1]['base'])
        self.assertEqual('read_back_and_discoverable', receipt['retention']['state'])
        self.assertEqual(3, self.app.doctor()['records'])
        self.assertEqual(receipt, self.capture())
        report = journal().report()
        self.assertGreaterEqual(report['cohort']['attempts'], 3)

    def test_legacy_stale_request_is_completed_without_new_identity(self):
        data = b'exact\r\nsource\x00\xff'; key = 'capture'
        identity = {'realm_id': self.app.initial_realm_id, 'principal': self.app.principal, 'key': key}
        name = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        proposal = self.app.capture(data, title='Synthetic source', scope=['scope'], filename='original.bin')
        request_digest = hashlib.sha256(json.dumps([identity, 'Synthetic source', ['scope'], 'original.bin',
            hashlib.sha256(data).hexdigest()], sort_keys=True).encode()).hexdigest()
        directory = self.root/'data/capture-requests'; directory.mkdir(mode=0o700, parents=True)
        (directory/(name+'.json')).write_text(json.dumps({'request_digest': request_digest, 'proposal': proposal}))
        other = self.app.capture(b'later', title='Later', scope=['scope'])
        self.app.apply(other, idempotency_key='later')
        receipt = self.capture()
        row = json.loads((directory/(name+'.json')).read_text())
        self.assertEqual(proposal['changes'], row['proposal']['changes'])
        self.assertEqual(receipt, self.capture())

    def test_lost_response_replayed_in_a_fresh_process(self):
        original = self.app.apply
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('synthetic lost response')
        with patch.object(self.app, 'apply', side_effect=lost):
            with self.assertRaises(OSError): self.capture()
        head = self.app.store.snapshot()['revision']
        script = """import json,sys
from ekk.adapters.command_line import service,capture_once
app=service(sys.argv[1])
print(json.dumps(capture_once(app,b'exact\\r\\nsource\\x00\\xff',title='Synthetic source',scopes=['scope'],filename='original.bin',key='capture')))
"""
        completed = subprocess.run([sys.executable, '-c', script, str(self.root/'realm')],
                                   check=True, capture_output=True, text=True)
        receipt = json.loads(completed.stdout)
        self.assertEqual(head, receipt['revision'])
        self.assertEqual('read_back_and_discoverable', receipt['retention']['state'])
        self.assertEqual(2, self.app.doctor()['records'])

    def test_explicit_snapshot_and_non_retryable_conflicts_never_rebase(self):
        base = self.app.store.snapshot()['revision']
        self.capture('advance')
        with self.assertRaises(Conflict): self.capture(expected_snapshot=base)
        for exception in (DirtyWorkingTree, IdempotencyConflict, RecoveryConflict):
            with patch.object(self.app, 'apply', side_effect=exception('synthetic')) as apply:
                with self.assertRaises(exception): self.capture(key=exception.__name__)
                self.assertEqual(1, apply.call_count)

    def test_control_change_blocks_automatic_rebase(self):
        original = self.app.apply
        def interleaved(proposal, **kwargs):
            snapshot = self.app.store.snapshot()
            policy = self.app.codec.load_yaml(snapshot['files']['.ekk/governance.yaml'])
            policy['version'] += 1
            self.app.configure({'.ekk/governance.yaml': self.app.codec.dump_yaml(policy)},
                base=snapshot['revision'], idempotency_key='policy-change')
            return original(proposal, **kwargs)
        with patch.object(self.app, 'apply', side_effect=interleaved):
            with self.assertRaises(Conflict): self.capture()
        self.assertEqual(1, self.app.doctor()['records'])

    def test_confirmed_publication_survives_readback_failure_then_verifies(self):
        with patch.object(self.app, 'verify_retention', side_effect=OSError('unavailable')):
            first = self.capture()
        self.assertEqual('published', first['state'])
        self.assertEqual('published_verification_pending', first['retention']['state'])
        self.assertTrue(first['incomplete'])
        again = self.capture()
        self.assertEqual(first['revision'], again['revision'])
        self.assertTrue(again['retention']['read_back'])

    def test_result_and_exact_sources_are_one_publication_and_discoverable(self):
        # Even valid source-shaped frontmatter remains inert bytes inside an asset.
        misleading = self.app.codec.encode(self.app._meta('source', 'Embedded source', ['scope'],
                                                          source={'uri': 'https://example.invalid'}))
        artifacts = [{'data': misleading, 'filename': 'original.md'},
                     {'data': b'\x00\xffbinary', 'filename': 'evidence.bin'}]
        kwargs = {'title': 'Finished integration', 'body': 'Tests were recorded; benefit remains unmeasured.',
                  'scopes': ['scope'], 'key': 'retained'}
        receipt = retain_once(self.app, artifacts, **kwargs)
        self.assertEqual(2, len(receipt['source_references']))
        result = self.app.fetch_record(['scope'], receipt['result_reference'])
        self.assertEqual('outcome', result['metadata']['kind'])
        self.assertEqual(2, len(result['metadata']['basis']))
        self.assertEqual(receipt, retain_once(self.app, artifacts, **kwargs))
        for source in receipt['source_references']:
            raw = self.app.read_source(['scope'], source)
            self.assertIn(base64.b64decode(raw['base64']), [a['data'] for a in artifacts])
        view = self.app.context(['scope'], task='Finished integration')
        self.assertFalse(next(r for r in view['records'] if r['id']==result['reference']['id'])['governs'])

    def test_capture_key_payload_changes_and_revoked_access_are_rejected(self):
        receipt = self.capture()
        with self.assertRaises(IdempotencyConflict):
            capture_once(self.app, b'different', title='Synthetic source', scopes=['scope'], filename='original.bin', key='capture')
        old = self.app.principal; self.app.principal = 'different-principal'
        with self.assertRaises(PermissionError): self.capture()
        self.app.principal = old
        self.assertEqual(receipt['revision'], self.app.store.snapshot()['revision'])

    def test_failure_before_store_journal_is_visible(self):
        args = parser().parse_args(['capture', '--root', str(self.root/'realm'), '--scope', 'scope'])
        with self.assertRaises(ValueError): dispatch(args, {'body': 'missing key'})
        rows = [json.loads(line) for line in (self.root/'data/operations/operations.jsonl').read_text().splitlines()]
        failures = [row for row in rows if row.get('result') == 'error']
        self.assertEqual(1, len(failures))
        self.assertFalse(failures[0]['mutated'])
        self.assertNotIn('missing key', json.dumps(rows))


if __name__ == '__main__': unittest.main()
