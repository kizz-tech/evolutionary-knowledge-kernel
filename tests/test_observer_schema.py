"""Observer state schema: the one step from 0.10.0, 0.10.0's writers on it, a newer schema, and the read-only accessor.

0.10.0 is the rollback target and shares this database, so its store module is kept
exactly as released in tests/fixtures/experience_store_0_10_0.py
(`git show c1b132a:src/ekk/adapters/experience_store.py`).
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import ekk.adapters  # noqa: F401  (the frozen module imports ..homes from this package)
from ekk import __version__
from ekk.adapters import observe_cli
from ekk.adapters.experience_store import SCHEMA_VERSION, ExperienceStore, UnknownObserverSchema, open_read_only

DAY = 86400
REF = {'realm': 'realm:test', 'id': 'record:test', 'revision': 1, 'digest': 'sha256:' + 'a' * 64}
ADDED = {'events': {'runtime', 'transcript_path', 'expired_from', 'expired_at'},
         'episodes': {'profile', 'runtime', 'rule', 'shadow', 'expired_from', 'expired_at'},
         'deliveries': {'runtime', 'labels_application'}, 'readings': {'runtime'}, 'labels': {'runtime', 'application'},
         'advice': {'runtime'}, 'task_terms': set(), 'task_seen': set(), 'stats': set()}


def released_store():
    spec = importlib.util.spec_from_file_location('ekk.adapters.experience_store_0_10_0',
                                                  Path(__file__).resolve().parent / 'fixtures/experience_store_0_10_0.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V0_10_0 = released_store()


def installer():
    """tools/local_install.py, whose rollback guard reads the observer of the runtime home."""
    spec = importlib.util.spec_from_file_location('ekk_local_install', Path(__file__).resolve().parent.parent / 'tools/local_install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(rule):
    return json.dumps({'title': 'Diagnosis.', 'body': 'Report.', 'experience': {'schema': 'ekk.experience/0.1', 'rule': rule}})


def seed(store, now):
    """Rows in every table, through the store's own writers."""
    common = dict(host='codex', profile='research', session='s1', workspace='/work', realm=REF['realm'])
    store.add_event(kind='report', turn='t1', at=now - 10, text='Report.', **common)
    store.add_event(kind='correction', turn='t2', at=now - 9, text='no, the other one', state='pending', **common)
    episode = dict(workspace='/work', realm=REF['realm'], host='codex', session='s1', first_at=now - 20, last_at=now - 10, covers='[]')
    store.save_episode('episode-held', state='held', title='Diagnosis.', request=request('ekk.episode-rule/2'), reason='substantial_report', **episode)
    store.save_episode('episode-unknown-rule', state='held', title='Other.', request=request(7), **episode)
    store.save_episode('episode-broken', state='composed', title='Broken.', request='{"half": ', **episode)
    store.save_episode('episode-published', state='published', title='Done.', request=None, **episode)
    delivery = store.note_delivery(workspace='/work', realm=REF['realm'], task='payout', snapshot='s', items=[REF],
                                   host='codex', session='s1', at=now - 5)
    store.note_reading(reference=REF, operation='fetch', workspace='/work', host='codex', session='s1', at=now - 4)
    store.label_delivery(delivery, {'1': 'relevant'})
    store.label('episode-held', 'episode', True)
    store.observe_task(REF['realm'], ['payout'], 'payout minimum')
    store.note_advice('episode-held', 'triage', 'model', 'keep', {'keep': 0.9})
    store.count('episodes_held', 2)


def ordered(rows):
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def table_rows(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return ({table: ordered(dict(row) for row in db.execute(f'SELECT * FROM {table}')) for table in tables},
                db.execute('PRAGMA user_version').fetchone()[0])
    finally:
        db.close()


def file_state(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


class ObserverSchemaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve() / 'runtime home'  # a space, as in "Application Support"
        env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root / 'data'), 'EKK_CONFIG_HOME': str(self.root / 'config')})
        env.start(); self.addCleanup(env.stop)

    def store(self, directory):
        store = ExperienceStore(directory)
        self.addCleanup(store.close)
        return store

    def test_a_0_10_0_database_copy_migrates_in_one_step_without_changing_a_value(self):
        now = time.time()
        live = self.root / 'live/observed'
        old = V0_10_0.ExperienceStore(live)
        seed(old, now)
        old.close()  # the last connection checkpoints the WAL into the main file
        copy = self.root / 'copy/observed'; copy.mkdir(parents=True, mode=0o700)
        shutil.copy2(live / 'state.sqlite', copy / 'state.sqlite')
        before, version = table_rows(copy / 'state.sqlite')
        self.assertEqual(0, version)
        self.store(copy).close()
        after, version = table_rows(copy / 'state.sqlite')
        self.assertEqual(SCHEMA_VERSION, version)
        self.assertEqual(set(before) | {'review_applications', 'episode_keys'}, set(after))
        self.assertEqual([], after['review_applications'])
        # The ledger starts with the episodes present at the step, in its transaction.
        self.assertEqual(ordered({'key': row['key']} for row in before['episodes']), after['episode_keys'])
        for table, rows in before.items():
            names = set(rows[0])  # the seed writes every table
            self.assertEqual(ADDED[table], set(after[table][0]) - names, table)
            self.assertEqual(rows, ordered({k: row[k] for k in names} for row in after[table]), table)
            self.assertTrue(all(row[k] is None for row in after[table] for k in ADDED[table] - {'rule'}), table)
        # The rule is copied from the stored request when the column is added; an unknown one stays NULL, never guessed.
        rules = {row['key']: row['rule'] for row in after['episodes']}
        self.assertEqual({'episode-held': 'ekk.episode-rule/2', 'episode-unknown-rule': None, 'episode-broken': None,
                          'episode-published': None}, rules)
        db = sqlite3.connect(copy / 'state.sqlite')
        self.assertEqual([('episodes', 'CREATE INDEX episodes_state ON episodes(state, last_at)')],
                         db.execute("SELECT tbl_name,sql FROM sqlite_master WHERE name='episodes_state'").fetchall())
        db.close()
        self.assertEqual((before, 0), table_rows(live / 'state.sqlite'))  # only the copy was migrated
        # Opening again changes nothing, and a fresh database has an empty ledger and no stats.
        self.store(copy).close()
        self.assertEqual((after, SCHEMA_VERSION), table_rows(copy / 'state.sqlite'))
        fresh = self.store(self.root / 'fresh/observed')
        self.assertEqual(({}, []), (fresh.stats(), fresh.db.execute('SELECT key FROM episode_keys').fetchall()))
        self.assertEqual(SCHEMA_VERSION, fresh.db.execute('PRAGMA user_version').fetchone()[0])
        # A database already at version 1 without the ledger gets it, seeded, through the same presence check.
        db = sqlite3.connect(copy / 'state.sqlite'); db.execute('DROP TABLE episode_keys'); db.commit(); db.close()
        self.store(copy).close()
        self.assertEqual((after, SCHEMA_VERSION), table_rows(copy / 'state.sqlite'))

    def test_0_10_0_writers_still_work_on_the_migrated_schema(self):
        directory = self.root / 'observed'
        current = ExperienceStore(directory)
        current.save_episode('episode-a', workspace='/work', realm=REF['realm'], host='codex', profile='main', session='s1',
                             state='held', title='A.', request=request('r'), rule='r', last_at=time.time())
        application = current.start_review_application(page='/review.md', page_sha256='a' * 64, declared='owner_marked_page', host='codex',
                                                       profile='main', session=None)
        current.label('episode-a', 'episode', True, application=application)
        labelled = current.note_delivery(workspace='/work', realm=REF['realm'], task='t', snapshot='s', items=[REF], host='codex', session='s1')
        current.label_delivery(labelled, {'0': True}, application=application)
        current.note_advice('episode-a', 'triage', 'model', 'keep', {})
        self.assertEqual(('main', 'r', __version__), tuple(current.episode('episode-a')[k] for k in ('profile', 'rule', 'runtime')))
        self.assertEqual([(application, application)], [tuple(row) for row in current.db.execute(
            "SELECT labels.application,deliveries.labels_application FROM labels,deliveries WHERE target='episode-a' AND id=?", (labelled,))])
        current.close()
        old = V0_10_0.ExperienceStore(directory)  # its executescript and column check run on the migrated file
        now = time.time()
        seed(old, now)
        old.save_episode('episode-a', state='queued')
        old.label('episode-a', 'episode', False)  # INSERT OR REPLACE: the row it writes names no application
        old.label_delivery(labelled, {'0': False})  # UPDATE deliveries SET labels: the application column is left as it was
        old.note_advice('episode-a', 'triage', 'model', 'drop', {})
        old.expire(now)
        old.close()
        rows, version = table_rows(directory / 'state.sqlite')
        self.assertEqual(SCHEMA_VERSION, version)
        # 0.10.0 replaces whole rows: what it rewrites loses the new columns. NULL means unstamped, never a version.
        episode = next(row for row in rows['episodes'] if row['key'] == 'episode-a')
        self.assertEqual(('queued', None, None, None), (episode['state'], episode['profile'], episode['rule'], episode['runtime']))
        self.assertEqual([('false', None, None)], [(row['value'], row['runtime'], row['application']) for row in rows['labels'] if row['target'] == 'episode-a'])
        self.assertEqual([('{"0": false}', application)], [(row['labels'], row['labels_application']) for row in rows['deliveries'] if row['id'] == labelled])
        self.assertEqual([(application, None)], [(row['id'], row['counts']) for row in rows['review_applications']])  # 0.10.0 leaves the table alone
        self.assertEqual([('drop', None)], [(row['label'], row['runtime']) for row in rows['advice'] if row['target'] == 'episode-a'])
        for table in ('events', 'deliveries', 'readings'):
            self.assertTrue(rows[table])
            self.assertEqual({None}, {row['runtime'] for row in rows[table] if row['id'] != labelled}, table)
        reopened = self.store(directory)
        self.assertEqual('linked', reopened.readings()[0]['link_state'])
        reopened.save_episode('episode-a', state='published', request=None)
        self.assertEqual(('published', __version__), (reopened.episode('episode-a')['state'], reopened.episode('episode-a')['runtime']))

    def test_upserts_keep_the_columns_a_save_does_not_name(self):
        store = self.store(self.root / 'observed')
        store.save_episode('k', workspace='/work', state='held', title='T.', rule='r', profile='main')
        store.db.execute("UPDATE episodes SET shadow='s', expired_at=1 WHERE key='k'")
        store.save_episode('k', state='queued', reason='kept_by_owner')
        self.assertEqual(('queued', 'kept_by_owner', 'T.', 'r', 'main', 's', 1, __version__),
                         tuple(store.episode('k')[k] for k in ('state', 'reason', 'title', 'rule', 'profile', 'shadow', 'expired_at', 'runtime')))
        self.assertEqual(1, store.stats()['episodes_created'])
        with self.assertRaises(ValueError):
            store.save_episode('k', unknown='x')
        self.assertEqual([('k',)], [tuple(row) for row in store.db.execute('SELECT key FROM episode_keys')])  # a re-save adds no key
        store.label('t', 'episode', True)
        store.db.execute("UPDATE labels SET application='review-1'")
        store.label('t', 'episode', False)
        self.assertEqual([('false', 'review-1', __version__)], [tuple(row) for row in store.db.execute('SELECT value,application,runtime FROM labels')])

    def test_a_new_episode_is_written_with_its_ledger_key_and_count_or_not_at_all(self):
        store = self.store(self.root / 'observed')
        store.save_episode('e-1', workspace='/work', state='held')
        def count(name, amount=1):
            if name == 'episodes_created':
                raise sqlite3.OperationalError('database is locked')
        with patch.object(store, 'count', side_effect=count), self.assertRaises(sqlite3.OperationalError):
            store.save_episode('e-2', workspace='/work', state='held')
        self.assertFalse(store.db.in_transaction)
        self.assertEqual((['e-1'], [('e-1',)], 1), ([e['key'] for e in store.episodes()], [tuple(row) for row in store.db.execute(
            'SELECT key FROM episode_keys')], store.stats()['episodes_created']))
        state = store.expiry_state()
        self.assertEqual((0, 0), (state['episodes_deleted_uncounted'], state['episodes_created_uncounted']))
        store.save_episode('e-2', workspace='/work', state='held')  # the retry counts it once
        self.assertEqual(2, store.stats()['episodes_created'])

    def test_a_newer_schema_keeps_its_version_and_accepts_writes(self):
        directory = self.root / 'observed'
        ExperienceStore(directory).close()
        db = sqlite3.connect(directory / 'state.sqlite')
        db.execute('ALTER TABLE episodes ADD COLUMN future TEXT'); db.execute('PRAGMA user_version = 2'); db.commit(); db.close()
        store = self.store(directory)
        store.save_episode('k', workspace='/work', state='held')
        store.note_delivery(workspace='/work', realm=REF['realm'], task='t', snapshot='s', items=[REF], host='codex', session='s1')
        store.label('k', 'episode', True)
        self.assertEqual(2, store.db.execute('PRAGMA user_version').fetchone()[0])
        self.assertEqual((None, __version__), (store.episode('k')['future'], store.episode('k')['runtime']))
        self.assertNotIn('future', store.deliveries()[0])

    def test_the_lock_is_taken_only_while_part_of_the_step_is_missing(self):
        directory = self.root / 'observed'
        ExperienceStore(directory).close()
        partial = self.root / 'partial/observed'
        V0_10_0.ExperienceStore(partial).close()
        db = sqlite3.connect(partial / 'state.sqlite'); db.execute('PRAGMA user_version = 1'); db.commit(); db.close()
        for path, opens in ((directory, True), (partial, False)):
            writer = sqlite3.connect(path / 'state.sqlite', isolation_level=None)
            writer.execute('BEGIN IMMEDIATE')
            try:
                if opens:
                    ExperienceStore(path, timeout=0.05).close()  # complete: no write lock, so a busy observer never delays the agent
                else:
                    with self.assertRaises(sqlite3.OperationalError):
                        ExperienceStore(path, timeout=0.05)
            finally:
                writer.execute('ROLLBACK'); writer.close()
        store = self.store(partial)
        self.assertIn('runtime', {row[1] for row in store.db.execute('PRAGMA table_info(episodes)')})
        self.assertEqual(1, store.db.execute('PRAGMA user_version').fetchone()[0])

    def test_0_10_0_expiry_deletes_tombstones_and_text_free_rows_without_a_count(self):
        """Why the installer's rollback guard exists: 0.10.0 deletes, uncounted, what this runtime keeps."""
        now, directory = time.time(), self.root / 'data/observed'  # the runtime home's, which status reads
        store = self.store(directory)
        common = dict(workspace='/work', realm=REF['realm'], host='codex', session='s1')
        store.save_episode('episode-held', state='held', title='Diagnosis.', request=request('ekk.episode-rule/2'), last_at=now - 61 * DAY, **common)
        store.save_episode('episode-published', state='published', title='Done.', last_at=now - 31 * DAY, **common)
        store.save_episode('episode-new', state='held', title='New.', request=request('ekk.episode-rule/2'), last_at=now - DAY, **common)
        store.add_event(kind='correction', host='codex', profile=None, session='s1', turn='t', workspace='/work', realm=None,
                        at=now - 91 * DAY, text='no', state='pending')
        labelled = store.note_delivery(workspace='/work', realm=REF['realm'], task='t', snapshot='s', items=[REF], host='codex',
                                       session='s1', at=now - 61 * DAY)
        store.label_delivery(labelled, {'0': True})  # kept to 365 days here; 0.10.0 deletes every delivery at 60
        self.assertEqual({'episodes_expired_held': 1, 'episodes_text_cleared': 1, 'corrections_expired_pending': 1}, store.expire(now))
        state = store.expiry_state(now)
        self.assertEqual((0, 0), (state['episodes_deleted_uncounted'], state['episodes_created_uncounted']))
        store.close()
        with open_read_only(self.root / 'data') as reader:  # what the rollback guard reads: exactly what 0.10.0 would delete
            self.assertEqual(({'expired_unreviewed': 1, 'published': 1}, 1, 1, 0),
                             (reader.episodes_older_than(30, now), reader.corrections_older_than(90, now),
                              reader.labelled_deliveries_beyond(60, 2000, now), reader.expiry_state(now)['episodes_deleted_uncounted']))
            self.assertEqual((0, 1), (reader.labelled_deliveries_beyond(62, 2000, now), reader.labelled_deliveries_beyond(62, 0, now)))
        target = self.root / 'releases/20261005-0.10.0'; target.mkdir(parents=True)
        (target / 'build.json').write_text(json.dumps({'version': '0.10.0'}))
        self.assertEqual(('0.10.0', {'episodes_older_than_30_days': {'expired_unreviewed': 1, 'published': 1}, 'corrections_older_than_90_days': 1,
                                     'labelled_deliveries_older_than_60_days_or_past_the_cap': 1}), installer().observer_loss(target))
        old = V0_10_0.ExperienceStore(directory)
        old.add_event(kind='report', host='codex', profile=None, session='s2', turn='t', workspace='/work', realm=None, at=now, text='Report.')
        for key in ('episode-0-10-0-a', 'episode-0-10-0-b'):  # created without a count
            old.save_episode(key, workspace='/work', state='held', title='Later.', last_at=now)
        old.expire(now)
        old.close()
        reopened = self.store(directory)
        self.assertEqual((['episode-0-10-0-a', 'episode-0-10-0-b', 'episode-new'], [], []),
                         (sorted(e['key'] for e in reopened.episodes()), reopened.events(kind='correction'), reopened.deliveries()))
        self.assertEqual(['report'], [event['kind'] for event in reopened.events()])  # its insert into the migrated schema
        state = reopened.expiry_state(now)
        # The tombstone and the text-free row went without a count, and two creations do not hide them.
        self.assertEqual((2, 2, {'held': 0}), (state['episodes_deleted_uncounted'], state['episodes_created_uncounted'],
                                               {'held': state['counters']['episodes_deleted']}))
        status = observe_cli.status(now=now)
        self.assertEqual((2, 2), (status['expiry']['episodes_deleted_uncounted'], status['expiry']['episodes_created_uncounted']))
        self.assertTrue(any(line.startswith('2 episode(s) deleted without a count') for line in status['attention']))

    def test_the_read_only_accessor_changes_and_creates_nothing(self):
        now = time.time()
        store = ExperienceStore(self.root / 'observed')
        store.save_episode('old', workspace='/work', state='held', last_at=now - 40 * DAY)
        store.save_episode('new', workspace='/work', state='held', last_at=now - DAY)
        store.save_episode('done', workspace='/work', state='published', last_at=now - 31 * DAY)
        store.add_event(kind='correction', host='codex', profile=None, session='s', turn=None, workspace='/work', realm=None,
                        at=now - 91 * DAY, text='no', state='pending')
        store.close()
        main = self.root / 'observed/state.sqlite'
        before = file_state(main)
        with open_read_only(self.root) as reader:
            self.assertEqual((True, SCHEMA_VERSION, {}), (reader.present, reader.schema_version, reader.unknown_columns))
            self.assertEqual({'held': 1, 'published': 1}, reader.episodes_older_than(30, now))
            self.assertEqual((1, 0), (reader.corrections_older_than(90, now), reader.corrections_older_than(92, now)))
            for statement in ('CREATE TABLE x(a)', "INSERT INTO stats(name,value) VALUES ('x',1)", 'PRAGMA user_version = 3'):
                with self.assertRaises(sqlite3.OperationalError):
                    reader.db.execute(statement)
        self.assertEqual(before, file_state(main))  # SQLite may add -wal/-shm sidecars; the main file is untouched
        db = sqlite3.connect(main)
        db.execute('ALTER TABLE episodes ADD COLUMN future TEXT'); db.execute('PRAGMA user_version = 2'); db.commit(); db.close()
        before = file_state(main)
        with self.assertRaises(UnknownObserverSchema):
            open_read_only(self.root)
        with open_read_only(self.root, strict=False) as reader:  # the installer's rollback guard
            self.assertEqual((2, {'episodes': ['future']}), (reader.schema_version, reader.unknown_columns))
            self.assertEqual({'held': 1, 'published': 1}, reader.episodes_older_than(30, now))
        self.assertEqual(before, file_state(main))

    def test_the_read_only_accessor_reads_0_10_0_and_reports_absent_state(self):
        old = V0_10_0.ExperienceStore(self.root / 'observed')
        old.save_episode('old', workspace='/work', state='held', last_at=time.time() - 40 * DAY)
        old.close()
        with open_read_only(self.root) as reader:
            self.assertEqual((0, {}, {'held': 1}), (reader.schema_version, reader.unknown_columns, reader.episodes_older_than(30)))
            state = reader.expiry_state()  # no ledger before the step: what went uncounted is unknown, not a number
            self.assertEqual((1, {}, None, None), (state['unjudged']['held']['count'], state['expired_unreviewed'],
                                                   state['episodes_deleted_uncounted'], state['episodes_created_uncounted']))
        for home in (self.root / 'absent', self.root / 'empty'):
            if home.name == 'empty':
                (home / 'observed').mkdir(parents=True, mode=0o700)
            with open_read_only(home) as reader:
                self.assertEqual((False, None, {}, 0, None), (reader.present, reader.schema_version, reader.episodes_older_than(30),
                                                              reader.corrections_older_than(90), reader.expiry_state()))
        self.assertFalse((self.root / 'absent').exists())
        self.assertEqual([], list((self.root / 'empty/observed').iterdir()))
        with patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root / 'default')}):
            self.assertFalse(open_read_only().present)
        self.assertFalse((self.root / 'default').exists())


if __name__ == '__main__':
    unittest.main()
