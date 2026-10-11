"""Explicit, counted expiry of observer state (`ekk.observer-expiry/1`), driven by the clock.

Nothing the owner has not judged is deleted before it is a counted tombstone, judged
and terminal rows keep a text-free row for 365 days, and every deletion is counted.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters import experience_store, observe_cli
from ekk.adapters.experience_store import DAY, EXPIRED, ExperienceStore, expires_at, horizons

T0 = 1790000000.0  # 2026-09-21, a synthetic clock
REF = {'realm': 'realm:test', 'id': 'record:test', 'revision': 1, 'digest': 'sha256:' + 'a' * 64}
RULE = 'ekk.episode-rule/2'
EPISODE_STATES = ('held', 'composed', 'queued', 'failed', 'published', 'rejected', 'skipped', 'linked', 'not_owner_work', 'future_x')
CORRECTION_STATES = ('pending', 'review_dialogue', 'confirmed', 'rejected', 'not_owner_work', 'future_x')


def utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()


def request(title='Diagnosis.'):
    return json.dumps({'title': title, 'body': 'Report.', 'experience': {'schema': 'ekk.experience/0.1', 'rule': RULE}})


class ObserverExpiryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.root / 'data'), 'EKK_CONFIG_HOME': str(self.root / 'config')})
        env.start(); self.addCleanup(env.stop)
        self.store = ExperienceStore()
        self.addCleanup(self.store.close)

    def episode(self, key, state, at=T0, **fields):
        self.store.save_episode(key, workspace='/work', realm=REF['realm'], host='codex', session='s1', first_at=at - 60, last_at=at,
                                state=state, **{'title': key, 'request': request(key), **fields})

    def correction(self, state, at=T0, text='no, the other one', session='s1'):
        return self.store.add_event(kind='correction', host='codex', profile=None, session=session, turn=state, workspace='/work',
                                    realm=REF['realm'], at=at, text=text, state=state)

    def episodes_by_key(self):
        return {episode['key']: episode for episode in self.store.episodes()}

    def counters(self, prefix):
        return {name: value for name, value in self.store.stats().items() if name.startswith(prefix)}

    def uncounted(self, now):
        """(episodes deleted, episodes created) without a count, from the ledger."""
        expiry = self.store.expiry_state(now)
        return expiry['episodes_deleted_uncounted'], expiry['episodes_created_uncounted']

    def test_the_table_is_the_one_source_of_every_horizon(self):
        self.assertEqual('ekk.observer-expiry/1', experience_store.EXPIRY_POLICY)
        self.assertEqual(((60, 365), (60, 365), (30, 365), (14, 365), (None, 365), (60, 365)),
                         tuple(horizons(state) for state in ('held', 'composed', 'published', 'skipped', EXPIRED, 'future_x')))
        self.assertEqual(((90, 365), (90, 365), (90, 365), (60, 365)),
                         tuple(horizons(state, 'correction') for state in ('pending', 'review_dialogue', 'confirmed', 'future_x')))
        self.assertEqual((T0 + 60 * DAY, T0 + 90 * DAY, None, None),
                         (expires_at('held', T0), expires_at('pending', T0, kind='correction'), expires_at(EXPIRED, T0), expires_at('held', None)))

    def test_episodes_become_tombstones_or_text_free_rows_and_are_deleted_at_365_days(self):
        for state in EPISODE_STATES:
            self.episode(state, state)
        self.store.db.execute("UPDATE episodes SET rule=NULL")  # a row 0.10.0 rewrote: the rule is copied before any text goes
        for days in (13, 15, 31, 59):
            self.store.expire(T0 + days * DAY)
        rows = self.episodes_by_key()
        texts = {key: (row['title'], row['request']) for key, row in rows.items()}
        self.assertEqual({'held', 'composed', 'future_x'}, {key for key, text in texts.items() if text != (None, None)})
        self.assertEqual({'episodes_created': 10, 'episodes_text_cleared': 7}, self.counters('episodes'))
        self.assertEqual(10, self.store.db.execute('SELECT count(*) FROM episode_keys').fetchone()[0])
        self.assertEqual({state: state for state in EPISODE_STATES}, {key: row['state'] for key, row in rows.items()})
        deltas = self.store.expire(T0 + 61 * DAY)
        self.assertEqual({'episodes_expired_held': 1, 'episodes_expired_composed': 1, 'episodes_text_cleared_unknown_state': 1}, deltas)
        rows = self.episodes_by_key()
        for prior in ('held', 'composed'):
            self.assertEqual((EXPIRED, prior, T0 + 61 * DAY, None, None, RULE, T0),
                             tuple(rows[prior][k] for k in ('state', 'expired_from', 'expired_at', 'title', 'request', 'rule', 'last_at')))
        self.assertEqual(('future_x', None, None, RULE), tuple(rows['future_x'][k] for k in ('state', 'title', 'request', 'rule')))
        self.assertEqual((0, 0), self.uncounted(T0 + 61 * DAY))  # tombstones keep their row and their key
        self.assertEqual({}, self.store.expire(T0 + 364 * DAY))  # nothing counted twice; every row is still there
        self.assertEqual(10, len(self.store.episodes()))
        self.assertEqual({'episodes_deleted': 9, 'episodes_deleted_unknown_state': 1}, self.store.expire(T0 + 366 * DAY))
        self.assertEqual(([], (0, 0)), (self.store.episodes(), self.uncounted(T0 + 366 * DAY)))
        self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM episode_keys').fetchone()[0])  # each counted deletion left the ledger

    def test_pending_corrections_become_tombstones_at_90_days_and_judged_ones_stay_text_free(self):
        ids = {state: self.correction(state, text='' if state in ('confirmed', 'rejected') else f'{state}: no') for state in CORRECTION_STATES}
        self.store.add_event(kind='report', host='codex', profile=None, session='s1', turn='r', workspace='/work', realm=None, at=T0, text='Done.')
        def rows():
            return {event['turn']: event for event in self.store.events(kind='correction')}
        self.assertEqual({'events_expired': 1}, self.store.expire(T0 + 31 * DAY))  # the report only
        self.assertEqual({'corrections_text_cleared_unknown_state': 1}, self.store.expire(T0 + 61 * DAY))
        self.assertEqual({}, self.store.expire(T0 + 89 * DAY))
        self.assertEqual(('pending', 'pending: no', None), tuple(rows()['pending'][k] for k in ('state', 'text', 'expired_from')))
        deltas = self.store.expire(T0 + 91 * DAY)
        self.assertEqual({'corrections_expired_pending': 1, 'corrections_expired_review_dialogue': 1, 'corrections_text_cleared': 1}, deltas)
        current = rows()
        for prior in ('pending', 'review_dialogue'):
            self.assertEqual((EXPIRED, prior, T0 + 91 * DAY, ''), tuple(current[prior][k] for k in ('state', 'expired_from', 'expired_at', 'text')))
        self.assertEqual({'confirmed': 'confirmed', 'rejected': 'rejected', 'not_owner_work': 'not_owner_work', 'future_x': 'future_x'},
                         {turn: row['state'] for turn, row in current.items() if row['state'] != EXPIRED})
        self.assertEqual({''}, {row['text'] for row in current.values()})
        self.assertEqual(ids['pending'], current['pending']['id'])
        self.assertEqual({}, self.store.expire(T0 + 364 * DAY))
        self.assertEqual({'corrections_deleted': 5, 'corrections_deleted_unknown_state': 1}, self.store.expire(T0 + 366 * DAY))
        self.assertEqual([], self.store.events())

    def test_nothing_is_deleted_without_a_count(self):
        caps = {'MAX_DELIVERIES': 5, 'MAX_READINGS': 3, 'MAX_SEEN_TASKS': 2}
        for name, value in caps.items():
            limit = patch.object(experience_store, name, value)
            limit.start(); self.addCleanup(limit.stop)
        for age in (0, 20, 45, 80, 100, 300, 400):
            at = T0 - age * DAY
            for state in EPISODE_STATES + (EXPIRED,):
                self.episode(f'{state}-{age}', state, at=at, **({'expired_from': 'held', 'title': None, 'request': None} if state == EXPIRED else {}))
            for state in CORRECTION_STATES:
                self.correction(state, at=at, session=f's{age}')
            self.store.add_event(kind='report', host='codex', profile=None, session=f's{age}', turn='r', workspace='/work', realm=None,
                                 at=at, text='Done.')
            delivery = self.store.note_delivery(workspace='/work', realm=REF['realm'], task=f'task {age}', snapshot='s', items=[REF],
                                                host='codex', session=f's{age}', at=at)
            if age in (80, 300):
                self.store.label_delivery(delivery, {'0': True})
            self.store.note_reading(reference=REF, operation='fetch', workspace='/work', host='codex', session=f's{age}', at=at + 1)
            self.store.label(f'target-{age}', 'episode', True)
            self.store.note_advice(f'target-{age}', 'triage', 'model', 'keep', {})
            self.store.observe_task(REF['realm'], ['payout'], f'task {age}')
            self.store.db.execute('INSERT INTO review_applications(id,at,declared) VALUES (?,?,?)', (f'review-{age}', at, 'relayed'))
            for table in ('labels', 'advice'):
                self.store.db.execute(f'UPDATE {table} SET at=? WHERE target=?', (at, f'target-{age}'))
        tables = {'episodes': ('episodes_deleted', 'episodes_deleted_unknown_state'), 'deliveries': ('deliveries_expired',),
                  'readings': ('readings_expired',), 'labels': ('labels_expired',), 'advice': ('advice_expired',),
                  'task_seen': ('task_seen_dropped',), 'review_applications': ('review_applications_expired',), 'task_terms': ()}
        deletions = {**tables, 'corrections': ('corrections_deleted', 'corrections_deleted_unknown_state'), 'other events': ('events_expired',)}
        def snapshot():
            counts = {table: self.store.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in (*tables, 'stats')}
            counts['corrections'] = self.store.db.execute("SELECT count(*) FROM events WHERE kind='correction'").fetchone()[0]
            counts['other events'] = self.store.db.execute("SELECT count(*) FROM events WHERE kind!='correction'").fetchone()[0]
            for state in ('held', 'composed'):
                counts[state] = self.store.db.execute('SELECT count(*) FROM episodes WHERE state=?', (state,)).fetchone()[0]
            for state in ('pending', 'review_dialogue'):
                counts[state] = self.store.db.execute("SELECT count(*) FROM events WHERE kind='correction' AND state=?", (state,)).fetchone()[0]
            return counts
        exercised = set()
        for days in (0, 1, 15, 31, 61, 91, 200, 366, 500, 800):
            now = T0 + days * DAY
            before, stats = snapshot(), self.store.stats()
            deltas = self.store.expire(now)
            exercised |= set(deltas)
            after, counted = snapshot(), self.store.stats()
            self.assertEqual({name: counted[name] - stats.get(name, 0) for name in counted if counted[name] != stats.get(name, 0)}, deltas, days)
            for table, names in deletions.items():
                self.assertEqual(before[table] - after[table], sum(deltas.get(name, 0) for name in names), (days, table))
            for kind, state in (('episodes', 'held'), ('episodes', 'composed'), ('corrections', 'pending'), ('corrections', 'review_dialogue')):
                # An unjudged row leaves its state only as a counted tombstone, even one deleted in the same pass.
                self.assertEqual(before[state] - after[state], deltas.get(f'{kind}_expired_{state}', 0), (days, state))
            self.assertEqual((0, 0), self.uncounted(now), days)
            self.assertGreaterEqual(after['stats'], before['stats'])
        self.assertEqual((0, 0), (after['episodes'], after['corrections']))
        self.assertEqual(set(), set(experience_store.EXPIRY_COUNTERS) - exercised - {'readings_delivery_expired'})

    def test_the_agent_path_prunes_inside_the_reading_transaction_and_leaves_episodes_alone(self):
        now = T0
        self.episode('old-held', 'held', at=now - 70 * DAY)
        self.episode('old-published', 'published', at=now - 400 * DAY)
        self.correction('pending', at=now - 100 * DAY)
        self.store.add_event(kind='report', host='codex', profile=None, session='s1', turn='r', workspace='/work', realm=None,
                             at=now - 40 * DAY, text='Done.')
        edge = now - 60 * DAY + 3600  # inside the horizon at the entry, outside it at the opening two hours later
        self.store.note_delivery(workspace='/work', realm=REF['realm'], task='old', snapshot='s', items=[REF], host='codex', session='s1', at=edge)
        self.store.note_reading(reference=REF, operation='fetch', workspace='/work', host='codex', session='s1', at=edge + 1)
        self.store.note_delivery(workspace='/work', realm=REF['realm'], task='new', snapshot='s', items=[REF], host='codex', session='s1', at=now)
        self.assertEqual((2, 1), (len(self.store.deliveries()), len(self.store.readings())))
        identity = self.store.note_reading(reference=REF, operation='fetch', workspace='/work', host='codex', session='s1', at=now + 7200)
        self.assertFalse(self.store.db.in_transaction)  # the savepoint was released and the reading committed
        self.assertEqual([(identity, 'linked')], [(row['id'], row['link_state']) for row in self.store.readings()])
        self.assertEqual({'deliveries_expired': 1, 'readings_expired': 1}, {k: v for k, v in self.store.stats().items() if 'expired' in k})
        self.assertEqual({'old-held': ('held', 'old-held'), 'old-published': ('published', 'old-published')},
                         {key: (row['state'], row['title']) for key, row in self.episodes_by_key().items()})
        self.assertEqual([('correction', 'pending'), ('report', 'new')], [(event['kind'], event['state']) for event in self.store.events()])

    def test_owner_labelled_deliveries_are_kept_outside_the_cap_until_365_days(self):
        with patch.object(experience_store, 'MAX_DELIVERIES', 2):
            def deliver(at):
                return self.store.note_delivery(workspace='/work', realm=REF['realm'], task=f'task {at}', snapshot='s', items=[REF],
                                                host='codex', session='s1', at=at)
            labelled = deliver(T0)
            self.store.label_delivery(labelled, {'0': True})
            self.store.note_reading(reference=REF, operation='fetch', workspace='/work', host='codex', session='s1', at=T0 + 1)
            unlabelled = [deliver(T0 + offset) for offset in (2, 3, 4, 5)]
            self.assertEqual({labelled, *unlabelled[-2:]}, {row['id'] for row in self.store.deliveries()})
            self.assertEqual(2, self.store.stats()['deliveries_expired'])
            self.assertEqual(labelled, self.store.readings()[0]['delivery_id'])  # its link stays live while it is kept
            self.assertEqual({'deliveries_expired': 2, 'readings_expired': 1}, self.store.expire(T0 + 61 * DAY))
            self.assertEqual([labelled], [row['id'] for row in self.store.deliveries()])
            self.assertEqual({}, self.store.expire(T0 + 364 * DAY))
            self.assertEqual({'deliveries_expired': 1}, self.store.expire(T0 + 366 * DAY))
            self.assertEqual([], self.store.deliveries())

    def test_status_names_the_next_expiry_of_unjudged_material_only(self):
        held, published, pending = utc('2026-10-02T16:41:52Z'), utc('2026-10-02T16:27:00Z'), utc('2026-10-02T16:04:00Z')
        self.episode('episode-held', 'held', at=held)
        self.episode('episode-published', 'published', at=published, request=None)
        self.correction('pending', at=pending)
        status = observe_cli.status(now=utc('2026-10-17T12:00:00Z'))
        self.assertEqual('ekk.observer-status/0.2', status['schema'])
        expiry = status['expiry']
        # Acceptance 4: the next loss of unjudged material is after 2026-11-01; a published title's clearing loses nothing.
        self.assertEqual(('2026-12-01T16:41:52Z', '2026-11-01T16:27:00Z', 0, 0),
                         (expiry['next_expiry'], expiry['next_text_clearing'], expiry['episodes_deleted_uncounted'],
                          expiry['episodes_created_uncounted']))
        self.assertEqual({'count': 1, 'oldest': '2026-10-02T16:41:52Z', 'next_expiry': '2026-12-01T16:41:52Z', 'within_14_days': 0},
                         expiry['unjudged']['held'])
        self.assertEqual(('2026-12-31T16:04:00Z', 0), (expiry['unjudged']['pending']['next_expiry'], expiry['unjudged']['composed']['count']))
        self.assertEqual({'corrections': 1, 'held_results': 1, 'oldest': '2026-10-02T16:04:00Z', 'next_expiry': '2026-12-01T16:41:52Z'},
                         status['waiting_for_review'])
        self.assertEqual([], status['attention'])
        later = observe_cli.status(now=utc('2026-11-20T00:00:00Z'))
        self.assertEqual(['1 held result(s) expire unreviewed from 2026-12-01: ekk observe review'], later['attention'])
        self.store.expire(utc('2026-12-02T00:00:00Z'))
        after = observe_cli.status(now=utc('2026-12-02T00:00:00Z'))
        self.assertEqual({'episodes': {'held': 1}, 'corrections': {}}, after['expiry']['expired_unreviewed'])
        self.assertEqual({'episodes': 1, 'corrections': 0}, after['expiry']['text_free_rows'])
        self.assertEqual((1, 1, 1), (after['expiry']['counters']['episodes_expired_held'], after['expiry']['counters']['episodes_text_cleared'],
                                     after['episodes'][EXPIRED]))
        self.assertEqual(['1 item(s) expired unreviewed'], after['attention'])
        self.assertEqual('2026-12-31T16:04:00Z', after['expiry']['next_expiry'])


if __name__ == '__main__':
    unittest.main()
