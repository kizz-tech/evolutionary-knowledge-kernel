"""Private exact openings are distinct from delivery, application and legacy use."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ekk import __version__
from ekk.adapters.command_line import note_delivery, note_use
from ekk.adapters.experience_store import DELIVERY_DAYS, ExperienceStore, MAX_READINGS, READING_DAYS


REF = {'realm': 'realm:test', 'id': 'record:test', 'revision': 1, 'digest': 'sha256:' + 'a' * 64}


class ExactReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'observed'
        self.store = ExperienceStore(self.directory)
        self.addCleanup(self.store.close)
        # The caller registry the CLI resolves a Codex profile from: ~/.codex-personal is the fleet's 'personal'.
        self.config = Path(self.temp.name).resolve() / 'config'; self.config.mkdir(mode=0o700)
        (self.config / 'fleet.json').write_text(json.dumps({'schema_version': 'lifeos.codex-profile-fleet/1',
                                                            'profiles': {'personal': {'home': '/private/.codex-personal'}}}))
        callers = self.config / 'callers.yaml'
        callers.write_text(json.dumps({'schema': 'ekk.callers/0.1', 'codex_profile_fleet': str(self.config / 'fleet.json')}))
        callers.chmod(0o600)

    @contextlib.contextmanager
    def observed(self, **environment):
        """The CLI's notes in an observed project, into this store, with only the given host variables."""
        with patch('ekk.adapters.observe_hook.workspace_of', return_value=Path('/work')), \
             patch('ekk.adapters.observe_hook.switched_off', return_value=False), \
             patch('ekk.adapters.experience_store.ExperienceStore', return_value=self.store), \
             patch.object(self.store, 'close'), \
             patch.dict(os.environ, {'EKK_CONFIG_HOME': str(self.config), 'EKK_DATA_HOME': self.temp.name + '/data',
                                     **environment}, clear=True):
            yield

    def delivery(self, *, session='session:a', ref=None, host='codex', workspace='/work', at=100, **extra):
        return self.store.note_delivery(workspace=workspace, realm='realm:test', task='some task', snapshot='snapshot',
                                        items=[REF if ref is None else ref], host=host, session=session, at=at, **extra)

    def reading(self, *, session='session:a', ref=None, host='codex', workspace='/work', at=101, **extra):
        return self.store.note_reading(reference=REF if ref is None else ref, operation='fetch', host=host,
                                       session=session, workspace=workspace, at=at, **extra)

    def test_unique_exact_opening_links_only_its_session(self):
        other = self.delivery(session='session:b')
        selected = self.delivery(at=100.1)
        self.reading()
        row = self.store.readings()[0]
        self.assertEqual((selected, 'linked', 'fetch'), (row['delivery_id'], row['link_state'], row['operation']))
        self.assertEqual([], self.store.readings(delivery_id=other))
        self.assertEqual([], self.store.deliveries()[0]['used'])
        self.assertEqual((REF['revision'], REF['digest']), (row['revision'], row['digest']))

    def test_version_host_workspace_realm_and_session_must_match(self):
        self.delivery()
        variations = [dict(ref={**REF, 'revision': 2}), dict(ref={**REF, 'digest': 'sha256:' + 'b' * 64}),
                      dict(host='claude-code'), dict(workspace='/other'), dict(session='session:b'),
                      dict(ref={**REF, 'realm': 'other'})]
        for i, values in enumerate(variations):
            self.reading(at=101 + i, **values)
        self.assertEqual({'no_matching_delivery'}, {r['link_state'] for r in self.store.readings()})
        self.assertTrue(all(r['delivery_id'] is None for r in self.store.readings()))

    def test_unknown_identity_or_reference_stays_unknown(self):
        self.delivery()
        self.reading(session=None)
        self.reading(host='unknown', at=102)
        self.reading(workspace=None, at=103)
        self.reading(ref={'realm': REF['realm'], 'id': REF['id']}, at=104)
        rows = self.store.readings()
        self.assertEqual(['unknown_identity'] * 3 + ['unknown_reference'], [r['link_state'] for r in rows])
        self.assertTrue(all(r['delivery_id'] is None for r in rows))

    def test_ambiguous_is_not_latest_and_future_or_old_not_matching(self):
        self.delivery(at=90)
        self.delivery(at=100)
        self.reading()
        self.assertEqual('ambiguous_delivery', self.store.readings()[0]['link_state'])
        self.reading(at=80)
        self.reading(at=100 + 86401)
        self.assertEqual(['no_matching_delivery', 'ambiguous_delivery', 'no_matching_delivery'],
                         [r['link_state'] for r in self.store.readings()])

    def test_profile_is_observed_but_no_profile_is_inferred(self):
        self.delivery(profile='personal')
        self.reading(profile='personal')
        self.assertEqual('personal', self.store.readings()[0]['profile'])
        self.assertEqual('personal', self.store.deliveries()[0]['profile'])
        self.reading(profile='other', at=102)
        self.assertEqual('no_matching_delivery', self.store.readings()[-1]['link_state'])

    def test_source_opening_and_unknown_legacy_api_do_not_create_used_marks(self):
        delivery = self.delivery()
        self.store.note_reading(reference=REF, operation='read-source', host='codex', session='session:a',
                                workspace='/work', at=102)
        self.assertEqual(delivery, self.store.readings()[0]['delivery_id'])
        with patch('ekk.adapters.experience_store.time.time', return_value=103):
            self.store.note_use(REF['realm'], REF['id'])
        self.assertEqual('unknown_reference', self.store.readings()[-1]['link_state'])
        self.assertEqual([], self.store.deliveries()[0]['legacy_used'])

    def test_additive_migration_does_not_reinterpret_old_marks(self):
        path = Path(self.temp.name) / 'legacy'; path.mkdir(mode=0o700)
        db = sqlite3.connect(path / 'state.sqlite')
        db.execute('CREATE TABLE deliveries(id TEXT PRIMARY KEY,at REAL NOT NULL,workspace TEXT,realm TEXT,task TEXT,snapshot TEXT,'
                   "items TEXT NOT NULL,baseline TEXT NOT NULL DEFAULT '[]',used TEXT NOT NULL DEFAULT '[]',labels TEXT)")
        db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?,?,?)',
                   ('old', 100, '/work', REF['realm'], 'task', 's', json.dumps([REF]), '[]', json.dumps([REF['id']]), None))
        db.commit(); db.close()
        legacy = ExperienceStore(path); self.addCleanup(legacy.close)
        row = legacy.deliveries()[0]
        self.assertEqual(1, row['reading_schema'])
        self.assertEqual([REF['id']], row['legacy_used'])
        self.assertEqual('legacy_id_only_not_exact_reading', row['used_semantics'])
        legacy.note_reading(reference=REF, operation='fetch', host='codex', session='session:a', workspace='/work', at=101)
        self.assertEqual('no_matching_delivery', legacy.readings()[0]['link_state'])
        self.assertEqual([REF['id']], legacy.deliveries()[0]['used'])

    def test_expiry_bounds_rows_and_drops_expired_delivery_link(self):
        self.delivery()
        self.reading()
        self.store.db.execute('DELETE FROM deliveries')
        self.assertEqual({'readings_delivery_expired': 1}, self.store.expire(102))
        self.assertEqual((None, 'delivery_expired'),
                         (self.store.readings()[0]['delivery_id'], self.store.readings()[0]['link_state']))
        self.store.db.executemany('INSERT INTO readings(id,at,operation,link_state) VALUES (?,?,?,?)',
                                 [(str(i), 1000 + i, 'fetch', 'unknown_reference') for i in range(MAX_READINGS + 1)])
        self.assertEqual({'readings_expired': 2}, self.store.expire(1000 + MAX_READINGS))  # the cap, counted
        self.assertEqual(MAX_READINGS, len(self.store.readings()))
        self.assertEqual({'readings_expired': MAX_READINGS}, self.store.expire(1000 + MAX_READINGS + READING_DAYS * 86400 + 1))
        self.assertEqual([], self.store.readings())
        self.delivery(at=200)
        self.assertEqual({}, self.store.expire(200 + DELIVERY_DAYS * 86400 - 1))
        self.assertEqual({'deliveries_expired': 1}, self.store.expire(200 + DELIVERY_DAYS * 86400 + 1))
        self.assertEqual([], self.store.deliveries())
        self.assertEqual((MAX_READINGS + 2, 1, 1), tuple(self.store.stats()[name] for name in
                                                         ('readings_expired', 'deliveries_expired', 'readings_delivery_expired')))

    def test_cli_observed_markers_and_nonblocking_failure(self):
        args = argparse.Namespace(operation='fetch', cwd='/work')
        result = {'reference': REF, 'incomplete': False}
        with self.observed(CODEX_HOME='/private/.codex-personal', CODEX_THREAD_ID='session:a'):
            self.delivery(profile='personal', at=__import__('time').time())
            note_use(args, result, REF['id'])
            self.assertEqual('linked', self.store.readings()[0]['link_state'])
            self.assertEqual('session:a', self.store.readings()[0]['session'])
            with patch.object(self.store, 'note_reading', side_effect=sqlite3.OperationalError('locked')):
                note_use(args, result, REF['id'])  # a telemetry failure never fails a read
            note_use(args, {**result, 'incomplete': True}, REF['id'])
            self.assertEqual(1, len(self.store.readings()))

    def test_cli_delivery_carries_exact_realm_and_observed_identity(self):
        args = argparse.Namespace(operation='enter', cwd='/work')
        brief = {'schema': 'ekk.context-brief/0.1', 'realm': REF['realm'], 'task': 'test',
                 'items': [{'ref': REF, 'title': 'Evidence', 'kind': 'outcome'}]}
        with self.observed(CODEX_HOME='/private/.codex-personal', CODEX_THREAD_ID='session:a'):
            note_delivery(args, {}, brief)
        row = self.store.deliveries()[0]
        self.assertEqual(('codex', 'personal', 'session:a'), (row['host'], row['profile'], row['session']))
        self.assertEqual(REF['realm'], row['items'][0]['realm'])
        self.assertEqual(REF['digest'], row['items'][0]['digest'])
        self.assertEqual(__version__, row['runtime'])
        with self.observed(CODEX_HOME='/private/.codex-unregistered', CODEX_THREAD_ID='session:a'):
            note_delivery(args, {}, brief)
        self.assertEqual(('codex', None), (self.store.deliveries()[0]['host'], self.store.deliveries()[0]['profile']))  # never a directory name

    def test_claude_code_openings_link_to_their_entry(self):
        enter = argparse.Namespace(operation='enter', cwd='/work')
        fetch = argparse.Namespace(operation='fetch', cwd='/work')
        brief = {'schema': 'ekk.context-brief/0.1', 'realm': REF['realm'], 'task': 'test',
                 'items': [{'ref': REF, 'title': 'Evidence', 'kind': 'outcome'}]}
        for number, (environment, session) in enumerate([
                ({'CLAUDE_CODE_SESSION_ID': 's1'}, 's1'),
                ({'CLAUDE_SESSION_ID': 's2'}, 's2'),  # the earlier variable, still read as a fallback
                ({'CLAUDE_CODE_SESSION_ID': 's3', 'CLAUDE_SESSION_ID': 'other'}, 's3'),
                # Never read: the host session is not the conversation, and the child marker says nothing about it.
                ({'CLAUDE_CODE_HOST_SESSION_ID': 'local_x', 'CLAUDE_CODE_CHILD_SESSION': '1'}, None)]):
            with self.observed(CLAUDECODE='1', **environment):
                note_delivery(enter, {}, brief)
                note_use(fetch, {'reference': REF, 'incomplete': False}, REF['id'])
            delivery, reading = self.store.deliveries()[0], self.store.readings()[-1]
            self.assertEqual(('claude-code', None, session), (delivery['host'], delivery['profile'], delivery['session']))
            self.assertEqual(('linked', delivery['id']) if session else ('unknown_identity', None),
                             (reading['link_state'], reading['delivery_id']), number)
            self.assertEqual(session, reading['session'])


if __name__ == '__main__':
    unittest.main()
