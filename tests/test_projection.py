"""Documents as projections: the decision table is rendered from the realm's records."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters import projection_cli
from ekk.adapters.command_line import service
from ekk.application import projection
from ekk.cli import main
from ekk.model import digest

QUEUED = ('Writes are queued and published in the background.\n\n'
          '**Reason, rejected alternative:** Synchronous publication blocked agents; the queue already guaranteed recovery.\n\n'
          '**Revisit when:** A host needs the receipt in its critical path\n\n'
          'Recorded from the planning table on 2026-09-01.')
WAITED = ('Retention waits for the receipt | never.\n\n'
          '**Reason, rejected alternative:** Hosts asked for it.\n\n'
          '**Revisit when:** The queue is removed')
EXPECTED = (
    "Generated from the realm's decision records on 2026-10-02 by ekk project decisions; edit the records, not this table.\n"
    '\n'
    '| ID | Decision | Reason / rejected alternative | Revisit when | State |\n'
    '| --- | --- | --- | --- | --- |\n'
    '| D-1.0-2 | Writes are queued and published in the background. | Synchronous publication blocked agents; the queue already '
    'guaranteed recovery. | A host needs the published receipt | superseded by D-1.0-10 |\n'
    '| D-1.0-10 | Retention waits for the receipt \\| never. | Hosts asked for it. | The queue is removed | accepted |\n'
    '| decision:open | Entry shows the head of a chain. History on request. | A superseded record is never shown alone. | '
    'A fork appears; A cycle appears | proposed |\n')


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.realm = self.root / 'realm'
        env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root / 'data'), 'EKK_CONFIG_HOME': str(self.root / 'config'),
                                      'EKK_CACHE_HOME': str(self.root / 'cache')})
        env.start(); self.addCleanup(env.stop)
        code, output = self.call(['init', '--root', str(self.realm), '--title', 'Synthetic'])
        self.assertEqual(code, 0, output)
        self.app = service(self.realm)
        self.scope = self.app.codec.load_yaml(self.app.store.snapshot()['files']['.ekk/realm.yaml'])['default_context']
        self.sequence = 0

    def call(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), \
                patch('ekk.adapters.projection_cli.today', return_value='2026-10-02'):
            code = main(args)
        return code, output.getvalue() or error.getvalue()

    def add(self, key, body, *, created_at, revision=1, kind='decision', **extra):
        self.sequence += 1
        metadata = {'schema': 'ekk.record/0.1', 'id': key, 'kind': kind, 'title': key, 'scope': [self.scope],
                    'revision': revision, 'created_at': created_at, 'created_by': self.app.principal, **extra}
        raw = self.app.codec.encode(metadata, body)
        self.app.apply(self.app.propose({f'records/{key}.md': raw}), idempotency_key=f'record-{self.sequence}')
        return {'realm': self.app.initial_realm_id, 'id': key, 'revision': revision, 'digest': 'sha256:' + digest(raw)}

    def grounds(self):
        # Acceptance requires a pinned basis; a decision table never shows the note itself.
        return [self.add('note:grounds', 'The measurement behind the decision.', created_at='2026-08-31T12:00:00Z', kind='note')]

    def accept(self, reference):
        self.sequence += 1
        self.app.accept_records([self.scope], [reference], expected_snapshot=self.app.store.snapshot()['revision'],
                                idempotency_key=f'accept-{self.sequence}')

    def test_decision_table_is_rendered_from_the_records_in_natural_order(self):
        # Metadata wins where it exists: review.when over the body's revisit paragraph,
        # decision.reason over the body's reason paragraph; the body supplies the rest.
        grounds = self.grounds()
        old = self.add('decision:old', QUEUED, created_at='2026-09-01T12:00:00Z', aliases=['D-1.0-2'],
                       basis=grounds, review={'when': ['A host needs the published receipt']})
        self.accept(old)
        new = self.add('decision:new', WAITED, created_at='2026-09-02T12:00:00Z', aliases=['D-1.0-10', 'later alias'],
                       basis=grounds, supersedes=[old])
        self.accept(new)
        self.add('decision:open', 'Entry shows the head of a chain.\n\nHistory on request.', created_at='2026-09-03T12:00:00Z',
                 decision={'reason': 'A superseded record is never shown alone.'}, review={'when': ['A fork appears', 'A cycle appears']})
        before = self.app.store.snapshot()['revision']
        code, text = self.call(['project', 'decisions', '--root', str(self.realm), '--scope', self.scope])
        self.assertEqual(code, 0, text)
        self.assertEqual(text, EXPECTED)
        self.assertEqual(self.app.store.snapshot()['revision'], before)
        self.assertEqual([row['record_id'] for row in projection.decision_rows(self.app, [self.scope])],
                         ['decision:old', 'decision:new', 'decision:open'])

    def test_an_unaccepted_claim_leaves_the_accepted_decision_in_force(self):
        rule = self.add('decision:rule', 'Keep the ledger immutable.', created_at='2026-09-01T12:00:00Z', basis=self.grounds())
        self.accept(rule)
        self.add('decision:claim', 'Allow corrections to the ledger.', created_at='2026-09-02T12:00:00Z', supersedes=[rule])
        rows = projection.decision_rows(self.app, [self.scope])
        self.assertEqual([(row['id'], row['state']) for row in rows], [('decision:claim', 'proposed'), ('decision:rule', 'accepted')])

    def test_a_replaced_record_releases_its_alias_and_a_contested_alias_names_nobody(self):
        first = self.add('decision:v1', 'First wording.', created_at='2026-09-01T12:00:00Z', aliases=['D-7'])
        self.add('decision:v2', 'Revised wording.', created_at='2026-09-02T12:00:00Z', aliases=['D-7'], supersedes=[first])
        self.add('decision:other', 'Unrelated.', created_at='2026-09-03T12:00:00Z', aliases=['D-8'])
        self.add('decision:fake', 'Claims the same number.', created_at='2026-08-01T12:00:00Z', aliases=['D-8'])
        rows = {row['record_id']: (row['id'], row['state']) for row in projection.decision_rows(self.app, [self.scope])}
        self.assertEqual(('D-7', 'proposed'), rows['decision:v2'])  # the current record holds the alias
        self.assertEqual(('decision:v1', 'superseded by D-7'), rows['decision:v1'])
        self.assertEqual(('decision:other', 'proposed'), rows['decision:other'])  # contested: both fall back to their ids
        self.assertEqual(('decision:fake', 'proposed'), rows['decision:fake'])

    def test_a_reference_to_an_earlier_version_supersedes_nothing(self):
        first = self.add('decision:a', 'First wording.', created_at='2026-09-01T12:00:00Z')
        self.add('decision:b', 'Second wording.', created_at='2026-09-02T12:00:00Z', supersedes=[first])
        self.assertEqual({row['id']: row['state'] for row in projection.decision_rows(self.app, [self.scope])},
                         {'decision:a': 'superseded by decision:b', 'decision:b': 'proposed'})
        self.add('decision:a', 'First wording, revised.', created_at='2026-09-01T12:00:00Z', revision=2)
        self.assertEqual({row['id']: row['state'] for row in projection.decision_rows(self.app, [self.scope])},
                         {'decision:a': 'proposed', 'decision:b': 'proposed'})

    def test_out_writes_the_printed_document_through_the_bound_route(self):
        self.add('decision:one', QUEUED, created_at='2026-09-01T12:00:00Z', aliases=['D-1.0-01'])
        profiles = self.root / 'config/profiles'; profiles.mkdir(parents=True)
        (profiles / 'test.yaml').write_text(json.dumps({'schema': 'ekk.profile/0.1', 'uid': os.getuid(),
            'realms': {'project': {'id': self.app.initial_realm_id, 'path': str(self.realm)}}}))
        workspace = self.root / 'workspace'; (workspace / '.ekk').mkdir(parents=True)
        (workspace / '.ekk/workspace.yaml').write_text(json.dumps({'schema': 'ekk.workspace/0.1', 'workspace_id': 'workspace:test',
            'profile': 'test', 'bindings': [{'realm_alias': 'project', 'realm_id': self.app.initial_realm_id, 'contexts': [self.scope]}]}))
        code, printed = self.call(['project', 'decisions', '--cwd', str(workspace)])
        self.assertEqual(code, 0, printed)
        self.assertIn('| D-1.0-01 | Writes are queued and published in the background. |', printed)
        out = workspace / 'docs/decisions.md'
        code, receipt = self.call(['project', 'decisions', '--cwd', str(workspace), '--out', str(out)])
        self.assertEqual(code, 0, receipt)
        receipt = json.loads(receipt)
        self.assertEqual((receipt['schema'], receipt['document'], receipt['rows'], receipt['path'], receipt['scopes']),
                         ('ekk.projection/0.1', 'decisions', 1, str(out), [self.scope]))
        self.assertEqual((receipt['realm'], receipt['snapshot']), (self.app.initial_realm_id, self.app.store.snapshot()['revision']))
        self.assertEqual(out.read_text(encoding='utf-8'), printed)
        self.assertEqual([path.name for path in out.parent.iterdir()], ['decisions.md'])

    def test_an_interrupted_write_leaves_the_previous_document_intact(self):
        out = self.root / 'decisions.md'; out.write_text('previous\n')
        with patch('os.replace', side_effect=OSError('interrupted')), self.assertRaises(OSError):
            projection_cli.write_atomically(out, 'next\n')
        self.assertEqual(out.read_text(), 'previous\n')
        self.assertEqual([path.name for path in self.root.iterdir() if path.name.startswith('.')], [])
        projection_cli.write_atomically(out, 'next\n')
        self.assertEqual(out.read_text(), 'next\n')


if __name__ == '__main__':
    unittest.main()
