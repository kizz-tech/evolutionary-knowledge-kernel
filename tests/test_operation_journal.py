import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import ekk.adapters.operation_journal as operation_journal

from ekk.adapters.operation_journal import (
    ERROR_CODES, JournalCapacityError, JournalCorruptError, OperationJournal,
    OperationJournalError, TrustedCallerProfile,
)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def concurrent_writer(directory, count):
    journal = OperationJournal(directory)
    for _ in range(count):
        attempt = journal.begin('capture', realm_id='shared', principal='test', idempotency_key='same-logical-request')
        journal.finish(attempt, result='completed', replayed=True, duration_ms=1)


def crash_writer(directory):
    OperationJournal(directory).begin('capture', realm_id='test-realm')
    os._exit(0)


class OperationJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / 'runtime'
        self.clock = Clock()
        self.start = self.clock.now
        self.journal = OperationJournal(self.directory, clock=self.clock)

    def report(self, **kwargs):
        return self.journal.report(since=kwargs.pop('since', self.start), **kwargs)

    def rows(self):
        return [json.loads(line) for line in self.journal.path.read_text().splitlines()][1:]

    def overwrite_rows(self, rows, *, preserve_integrity=True):
        header = json.loads(self.journal.path.read_text().splitlines()[0])
        data = b''.join(json.dumps(row, separators=(',', ':')).encode() + b'\n' for row in rows)
        if preserve_integrity:
            header['entries'] = len(rows)
            header['records_sha256'] = hashlib.sha256(data).hexdigest()
        self.journal.path.write_bytes(json.dumps(header).encode() + b'\n' + data)

    def test_failure_before_store_is_counted_without_a_realm_or_payload(self):
        attempt = self.journal.begin('capture')
        self.clock.advance(seconds=1)
        result = self.journal.finish(attempt, result='error', failure_stage='request', duration_ms=12)
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['cohort']['attempts'], 1)
        self.assertEqual(report['cohort']['failed_attempts'], 1)
        self.assertEqual(report['cohort']['failure_stages']['request'], 1)
        self.assertEqual(report['cohort']['duration_ms'], {'count': 1, 'sum': 12, 'mean': 12, 'max': 12})
        self.assertIsNone(result['realm_digest'])
        self.assertEqual(result['caller_profile'], 'unknown')
        self.assertEqual(report['cohort']['logical_mutations'], 0)

    def test_older_writer_preserves_newer_operation_labels_across_upgrade_and_rollback(self):
        older = operation_journal.OPERATIONS - {'assess'}
        with patch.object(operation_journal, 'OPERATIONS', older):
            self.journal.finish(self.journal.begin('enter'), result='completed')
        with patch.object(operation_journal, 'OPERATIONS', older | {'assess'}):
            self.journal.finish(self.journal.begin('assess'), result='completed')
        newer_row = self.rows()[-1]
        with patch.object(operation_journal, 'OPERATIONS', older):
            self.journal.finish(self.journal.begin('retain'), result='completed')
            with self.assertRaises(OperationJournalError):
                self.journal.begin('assess')
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['cohort']['attempts'], 3)
        self.assertEqual(report['by_operation']['assess']['attempts'], 1)
        self.assertEqual(self.rows()[1], newer_row)

    def test_future_operation_label_is_read_only_and_structural_validation_stays_strict(self):
        self.journal.finish(self.journal.begin('enter'), result='completed')
        original = self.rows()[0]
        future = {**original, 'operation': 'future.operation-v2'}
        self.overwrite_rows([future])
        self.clock.advance(seconds=1)
        self.assertEqual(self.report()['status'], 'complete')
        with self.assertRaises(OperationJournalError):
            self.journal.begin('future.operation-v2')
        for operation in ('', 'a' * 65, '../private', 'task text', 'é', 'a\n', [], 'x..y'):
            with self.subTest(operation=operation):
                self.overwrite_rows([{**original, 'operation': operation}])
                raw = self.journal.path.read_bytes()
                with self.assertRaises(JournalCorruptError):
                    self.journal.begin('enter')
                self.assertEqual(self.journal.path.read_bytes(), raw)
        for updates in ({'schema': 'ekk.operation-attempt/9.0'}, {'result': 'future-result'},
                        {'logical_id': 'invalid'}, {'unknown_required': True}):
            with self.subTest(updates=updates):
                self.overwrite_rows([{**future, **updates}])
                with self.assertRaises(JournalCorruptError):
                    self.journal.begin('enter')
        self.overwrite_rows([future], preserve_integrity=False)
        with self.assertRaises(JournalCorruptError):
            self.journal.begin('enter')

    def test_repeat_retry_and_replay_have_explicit_separate_denominators(self):
        first = self.journal.begin('capture', realm_id='realm', principal='one', idempotency_key='key')
        self.clock.advance(seconds=1)
        child = self.journal.retry(first)
        self.journal.finish(child, result='conflict', failure_stage='store', duration_ms=4)
        child2 = self.journal.retry(child)
        self.journal.finish(child2, result='completed', mutated=True, duration_ms=3)
        self.journal.finish(first, result='completed', mutated=True, duration_ms=10)
        self.clock.advance(seconds=1)
        replay = self.journal.begin('capture', realm_id='realm', principal='one', idempotency_key='key')
        self.journal.finish(replay, result='completed', replayed=True, duration_ms=2)
        self.clock.advance(seconds=1)
        self.assertEqual({a.logical_id for a in (first, child, child2, replay)}, {first.logical_id})
        cohort = self.report()['cohort']
        self.assertEqual(cohort['attempts'], 4)
        self.assertEqual(cohort['request_attempts'], 2)
        self.assertEqual(cohort['child_attempts'], 2)
        self.assertEqual(cohort['logical_operations'], 1)
        self.assertEqual(cohort['repeated_request_attempts'], 1)
        self.assertEqual(cohort['failed_attempts'], 1)
        self.assertEqual(cohort['replayed_attempts'], 1)
        self.assertEqual(cohort['confirmed_mutation_attempts'], 2)
        self.assertEqual(cohort['logical_mutations'], 1)
        self.assertEqual(cohort['logical_results']['completed'], 1)
        self.assertEqual(cohort['logical_failed'], 0)
        self.assertEqual(cohort['duration_ms']['count'], 4)
        self.assertEqual(cohort['duration_ms']['sum'], 19)
        with self.assertRaises(OperationJournalError):
            self.journal.finish(replay, result='completed', replayed=True, mutated=True)

    def test_logical_identity_is_scope_keyed_and_keyless_reads_are_independent(self):
        kwargs = {'realm_id': 'r', 'principal': 'p', 'idempotency_key': 'k'}
        first = self.journal.begin('capture', **kwargs)
        repeated = self.journal.begin('capture', **kwargs)
        self.assertEqual(first.logical_id, repeated.logical_id)
        variants = [
            self.journal.begin('capture', **{**kwargs, 'realm_id': 'r2'}),
            self.journal.begin('capture', **{**kwargs, 'principal': 'p2'}),
            self.journal.begin('capture', **{**kwargs, 'idempotency_key': 'k2'}),
            self.journal.begin('apply', **kwargs),
        ]
        self.assertEqual(len({first.logical_id, *(v.logical_id for v in variants)}), 5)
        self.assertNotEqual(self.journal.begin('context').logical_id, self.journal.begin('context').logical_id)
        again = OperationJournal(self.directory, clock=self.clock).begin('capture', **kwargs)
        self.assertEqual(first.logical_id, again.logical_id)

    def test_vetted_profile_fixtures_and_unknown_are_provenance_only(self):
        labels = ('afla', 'work1', 'work2', 'personal', 'future_host')
        handles = [self.journal.begin('context', caller=TrustedCallerProfile(label)) for label in labels]
        handles.append(self.journal.begin('context'))
        for attempt in handles:
            self.journal.finish(attempt, result='completed', duration_ms=1)
        self.clock.advance(seconds=1)
        self.assertEqual(set(self.report()['by_caller_profile']), set(labels) | {'unknown'})
        for label in labels:
            self.assertEqual(self.report()['by_caller_profile'][label]['request_attempts'], 1)
        with self.assertRaises(OperationJournalError):
            self.journal.begin('context', caller={'profile': 'work1'})
        with self.assertRaises(OperationJournalError):
            self.journal.begin('context', caller='work1')
        for label in ('unknown', '../work1', '/private/home', 'a' * 49, 'contains spaces', ''):
            with self.subTest(label=label), self.assertRaises(OperationJournalError):
                TrustedCallerProfile(label)

    def test_no_private_sentinel_bytes_in_diagnostics_or_report(self):
        private = {
            'realm_id': 'PRIVATE_REALM:/secret/project',
            'principal': 'PRIVATE_PRINCIPAL_CREDENTIAL',
            'idempotency_key': 'PRIVATE_RAW_IDEMPOTENCY_KEY',
            'attempted_base': 'PRIVATE_TASK_TRANSCRIPT_BASE',
            'current_snapshot': 'PRIVATE_SOURCE_TITLE_PATH',
        }
        attempt = self.journal.begin('apply', **private)
        self.journal.annotate(attempt, current_snapshot='PRIVATE_UPDATED_SNAPSHOT')
        row = self.journal.finish(attempt, result='completed', mutated=True,
                                  final_snapshot='PRIVATE_FINAL_SNAPSHOT', duration_ms=2)
        self.clock.advance(seconds=1)
        raw = b''.join(p.read_bytes() for p in self.directory.iterdir() if p.is_file())
        output = json.dumps(self.report()).encode()
        for sentinel in [*private.values(), 'PRIVATE_UPDATED_SNAPSHOT', 'PRIVATE_FINAL_SNAPSHOT']:
            self.assertNotIn(sentinel.encode(), raw)
            self.assertNotIn(sentinel.encode(), output)
        for key in ('realm_digest', 'principal_digest', 'attempted_base', 'current_snapshot', 'final_snapshot'):
            self.assertRegex(row[key], r'^[0-9a-f]{64}$')
        self.assertNotIn('idempotency_key', self.rows()[0])
        self.assertNotIn('principal', self.rows()[0])
        self.assertNotIn('realm_id', self.rows()[0])
        with self.assertRaises(TypeError):
            self.journal.begin('capture', task='PRIVATE_RAW_TASK')
        with self.assertRaises(TypeError):
            self.journal.finish(attempt, result='error', exception='PRIVATE_EXCEPTION_TEXT')

    def test_atomic_private_permissions_and_symlink_guards(self):
        attempt = self.journal.begin('doctor')
        self.journal.finish(attempt, result='completed')
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        for path in self.directory.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse((self.directory / '.operations.pending').exists())
        target = Path(self.temporary.name) / 'target'
        target.mkdir()
        link = Path(self.temporary.name) / 'linked'
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OperationJournalError):
            OperationJournal(link)
        self.journal.path.unlink()
        secret = target / 'secret'
        secret.write_text('private')
        self.journal.path.symlink_to(secret)
        with self.assertRaises(OperationJournalError):
            self.journal.begin('doctor')
        self.assertEqual(secret.read_text(), 'private')

    def test_runtime_directory_cannot_be_under_code_or_a_forbidden_realm(self):
        # Loaded code can live in site-packages, separately from this test tree.
        code = Path(operation_journal.__file__).resolve().parent
        with self.assertRaises(OperationJournalError):
            OperationJournal(code / 'runtime')
        checkout = Path(self.temporary.name) / 'code-checkout'
        (checkout / '.git').mkdir(parents=True)
        with self.assertRaises(OperationJournalError):
            OperationJournal(checkout / 'runtime')
        self.assertFalse((checkout / 'runtime').exists())
        root = Path(self.temporary.name) / 'realm'
        with self.assertRaises(OperationJournalError):
            OperationJournal(root / 'runtime', forbidden_roots=[root])
        (root / '.ekk').mkdir(parents=True)
        (root / '.ekk/realm.yaml').write_text('id: test')
        with self.assertRaises(OperationJournalError):
            OperationJournal(root / 'runtime')
        self.assertFalse((root / 'runtime').exists())

    def test_concurrent_processes_do_not_lose_attempts(self):
        context = multiprocessing.get_context('spawn')
        processes = [context.Process(target=concurrent_writer, args=(str(self.directory), 12)) for _ in range(4)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
        report = OperationJournal(self.directory).report(since=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(report['coverage']['metadata_integrity_verified'])
        self.assertEqual(report['cohort']['attempts'], 48)
        self.assertEqual(report['cohort']['replayed_attempts'], 48)
        self.assertEqual(report['cohort']['logical_operations'], 1)
        self.assertEqual(report['cohort']['logical_mutations'], 0)
        self.assertEqual(len({row['attempt_id'] for row in self.rows()}), 48)

    def test_process_exit_after_begin_remains_pending(self):
        process = multiprocessing.get_context('spawn').Process(target=crash_writer, args=(str(self.directory),))
        process.start()
        process.join(15)
        self.assertEqual(process.exitcode, 0)
        report = OperationJournal(self.directory).report(since=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(report['cohort']['pending_now'], 1)
        self.assertEqual(report['cohort']['finished_attempts'], 0)
        self.assertEqual(report['cohort']['results']['completed'], 0)
        self.assertTrue(report['coverage']['pending_attempt_count_known'])

    def test_start_window_and_completion_window_are_half_open(self):
        first = self.journal.begin('context')
        self.clock.advance(seconds=10)
        second = self.journal.begin('context')
        self.clock.advance(seconds=10)
        boundary = self.clock.now
        self.journal.finish(first, result='completed', duration_ms=20)
        third = self.journal.begin('context')
        self.clock.advance(seconds=10)
        self.journal.finish(second, result='error', duration_ms=20)
        self.clock.advance(seconds=10)
        old = self.report(until=boundary)
        self.assertEqual(old['cohort']['attempts'], 2)
        self.assertEqual(old['cohort']['finished_attempts'], 0)
        self.assertEqual(old['cohort']['pending_at_window_end'], 2)
        self.assertEqual(old['cohort']['pending_now'], 0)
        self.assertEqual(old['cohort']['finished_after_window'], 2)
        self.assertEqual(old['completions_in_window']['attempts'], 0)
        later = self.report(since=boundary)
        self.assertEqual(later['cohort']['attempts'], 1)
        self.assertEqual(later['cohort']['pending_now'], 1)
        self.assertEqual(later['completions_in_window']['attempts'], 2)
        self.assertEqual(later['completions_in_window']['started_before_window'], 2)
        self.assertEqual(later['completions_in_window']['duration_ms']['count'], 2)
        self.assertNotEqual(second.attempt_id, third.attempt_id)

    def test_age_retention_uses_completion_time_preserves_pending_and_exact_cutoff(self):
        self.journal = OperationJournal(self.directory, retention_days=1, clock=self.clock)
        pending = self.journal.begin('capture')
        old = self.journal.begin('context')
        self.journal.finish(old, result='completed', duration_ms=1)
        self.clock.advance(days=1)
        self.assertEqual(self.report()['coverage']['retained_attempts'], 2)
        self.clock.advance(microseconds=1)
        report = self.report()
        self.assertEqual(report['coverage']['retained_attempts'], 1)
        self.assertEqual(report['coverage']['retention']['pruned_age'], 1)
        self.assertIn('pruned_start_cohort', report['coverage']['limitations'])
        self.assertIn('pruned_completions', report['coverage']['limitations'])
        self.journal.finish(pending, result='completed', duration_ms=86400001)
        self.clock.advance(seconds=1)
        self.assertEqual(self.report()['coverage']['retained_attempts'], 1)
        self.assertEqual(self.report()['cohort']['results']['completed'], 1)

    def test_capacity_evicts_completed_attempts_but_never_pending(self):
        self.journal = OperationJournal(self.directory, max_entries=2, clock=self.clock)
        pending = self.journal.begin('capture')
        old = self.journal.begin('context')
        self.journal.finish(old, result='completed', duration_ms=1)
        self.clock.advance(seconds=1)
        newest = self.journal.begin('context')
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['coverage']['retention']['pruned_capacity'], 1)
        self.assertEqual({r['attempt_id'] for r in self.rows()}, {pending.attempt_id, newest.attempt_id})
        with self.assertRaises(JournalCapacityError):
            self.journal.begin('context')
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['coverage']['retention']['refused_attempts'], 1)
        self.assertIn('refused_attempts_in_window', report['coverage']['limitations'])
        self.assertEqual(report['cohort']['pending_now'], 2)
        self.journal.finish(pending, result='completed', duration_ms=1)
        another = self.journal.begin('context')
        self.assertIn(another.attempt_id, {r['attempt_id'] for r in self.rows()})

    def test_byte_capacity_reserves_finish_space_and_atomic_replacement(self):
        self.journal = OperationJournal(self.directory, max_bytes=8192, clock=self.clock)
        pending = self.journal.begin('capture')
        with self.assertRaises(JournalCapacityError):
            self.journal.begin('context')
        self.journal.finish(pending, result='completed', duration_ms=1,
                            attempted_base='base', current_snapshot='current', final_snapshot='final')
        self.assertLessEqual(self.journal.path.stat().st_size, 4096)
        self.clock.advance(seconds=1)
        policy = self.report()['policy']
        self.assertEqual(policy['snapshot_byte_limit'] + policy['atomic_reserve_bytes'], 8192)
        new = self.journal.begin('context')
        self.journal.finish(new, result='completed', duration_ms=1)
        self.assertLessEqual(sum(p.stat().st_size for p in self.directory.iterdir()), 8192)

    def test_old_evictions_outside_window_do_not_claim_a_current_gap(self):
        self.journal = OperationJournal(self.directory, retention_days=1, clock=self.clock)
        old = self.journal.begin('context')
        self.journal.finish(old, result='completed', duration_ms=1)
        self.clock.advance(days=2)
        boundary = self.clock.now
        current = self.journal.begin('context')
        self.journal.finish(current, result='completed', duration_ms=1)
        self.clock.advance(seconds=1)
        report = self.report(since=boundary)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['coverage']['retention']['pruned_age'], 1)

    def test_corrupt_record_is_excluded_and_original_bytes_are_preserved(self):
        first = self.journal.begin('context')
        self.journal.finish(first, result='completed', duration_ms=1)
        second = self.journal.begin('capture')
        self.journal.finish(second, result='error', duration_ms=1)
        rows = self.rows()
        rows[0]['payload'] = 'PRIVATE_CORRUPTED_PAYLOAD'
        self.overwrite_rows(rows)
        original = self.journal.path.read_bytes()
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['status'], 'incomplete')
        self.assertFalse(report['coverage']['metadata_integrity_verified'])
        self.assertEqual(report['coverage']['damaged_records'], 1)
        self.assertEqual(report['cohort']['results']['completed'], 0)
        self.assertEqual(report['cohort']['results']['error'], 1)
        self.assertNotIn('PRIVATE_CORRUPTED_PAYLOAD', json.dumps(report))
        with self.assertRaises(JournalCorruptError):
            self.journal.begin('context')
        self.assertEqual(self.journal.path.read_bytes(), original)

    def test_partial_tail_and_line_boundary_truncation_are_detected(self):
        for cut in ('partial', 'whole'):
            with self.subTest(cut=cut):
                directory = Path(self.temporary.name) / cut
                journal = OperationJournal(directory, clock=self.clock)
                journal.begin('capture')
                journal.begin('context')
                lines = journal.path.read_bytes().splitlines(keepends=True)
                journal.path.write_bytes(b''.join(lines[:-1]) + (lines[-1][:-9] if cut == 'partial' else b''))
                self.clock.advance(seconds=1)
                report = journal.report(since=self.start)
                self.assertFalse(report['coverage']['metadata_integrity_verified'])
                self.assertIn('integrity_mismatch', report['coverage']['limitations'])
                self.assertFalse(report['coverage']['pending_attempt_count_known'])
                with self.assertRaises(JournalCorruptError):
                    journal.begin('context')

    def test_damaged_header_and_duplicate_attempts_never_claim_complete_evidence(self):
        self.journal.begin('context')
        rows = self.rows()
        self.overwrite_rows(rows + rows)
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['cohort']['attempts'], 0)
        self.assertEqual(report['coverage']['damaged_records'], 2)
        self.journal.path.write_bytes(b'not-json\n')
        report = self.report()
        self.assertEqual(report['status'], 'incomplete')
        self.assertIsNone(report['coverage']['retention'])
        self.assertEqual(report['cohort']['results']['completed'], 0)

    def test_interrupted_atomic_write_is_bounded_visible_and_blocks_overwrite(self):
        attempt = self.journal.begin('capture')
        with patch('ekk.adapters.operation_journal.os.replace', side_effect=OSError('PRIVATE_OS_ERROR')):
            with self.assertRaises(OperationJournalError) as caught:
                self.journal.finish(attempt, result='completed', mutated=True, duration_ms=1)
        self.assertNotIn('PRIVATE_OS_ERROR', str(caught.exception))
        self.clock.advance(seconds=1)
        before = (self.directory / '.operations.pending').read_bytes()
        report = self.report()
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['cohort']['pending_now'], 1)
        self.assertEqual(report['cohort']['logical_mutations'], 0)
        self.assertIn('interrupted_atomic_write', report['coverage']['limitations'])
        with self.assertRaises(JournalCorruptError):
            self.journal.begin('context')
        self.assertEqual((self.directory / '.operations.pending').read_bytes(), before)
        self.assertLessEqual(sum(p.stat().st_size for p in self.directory.iterdir()), self.journal.max_bytes)

    def test_finish_is_idempotent_but_cannot_rewrite_a_result(self):
        attempt = self.journal.begin('capture')
        first = self.journal.finish(attempt, result='completed', mutated=True, duration_ms=2)
        self.clock.advance(seconds=1)
        self.assertEqual(self.journal.finish(attempt, result='completed', mutated=True), first)
        with self.assertRaises(OperationJournalError):
            self.journal.finish(attempt, result='error')
        with self.assertRaises(OperationJournalError):
            self.journal.annotate(attempt, final_snapshot='different')
        self.assertEqual(self.report()['cohort']['attempts'], 1)

    def test_logical_terminal_result_tracks_a_retry_even_at_equal_timestamps(self):
        failed = self.journal.begin('capture', idempotency_key='key')
        self.journal.finish(failed, result='conflict', duration_ms=1)
        retry = self.journal.retry(failed)
        self.journal.finish(retry, result='completed', mutated=True, duration_ms=1)
        self.clock.advance(seconds=1)
        cohort = self.report()['cohort']
        self.assertEqual(cohort['results']['conflict'], 1)
        self.assertEqual(cohort['results']['completed'], 1)
        self.assertEqual(cohort['logical_results']['completed'], 1)
        self.assertEqual(cohort['logical_finished'], 1)
        self.assertEqual(cohort['logical_failed'], 0)
        unfinished = self.journal.retry(failed)
        self.clock.advance(seconds=1)
        self.assertEqual(self.report()['cohort']['logical_pending'], 1)
        self.journal.finish(unfinished, result='error', duration_ms=1)
        self.clock.advance(seconds=1)
        self.assertEqual(self.report()['cohort']['logical_failed'], 1)

    def test_parent_completed_after_child_wins_equal_completion_timestamp(self):
        parent = self.journal.begin('capture')
        child = self.journal.retry(parent)
        self.journal.finish(child, result='conflict', duration_ms=1)
        self.journal.finish(parent, result='completed', duration_ms=2)
        self.clock.advance(seconds=1)
        self.assertEqual(self.report()['cohort']['logical_results']['completed'], 1)

    def test_release_operation_symbols_are_validated(self):
        for operation in ('retain', 'diagnostics', 'backup', 'restore'):
            self.journal.finish(self.journal.begin(operation), result='completed', duration_ms=1)
        self.clock.advance(seconds=1)
        self.assertEqual(set(self.report()['by_operation']), {'retain', 'diagnostics', 'backup', 'restore'})

    def test_confirmed_publication_is_distinct_from_later_response_failure(self):
        attempt = self.journal.begin('apply')
        self.journal.finish(attempt, result='error', failure_stage='response', mutated=True, duration_ms=1)
        self.clock.advance(seconds=1)
        cohort = self.report()['cohort']
        self.assertEqual(cohort['failed_attempts'], 1)
        self.assertEqual(cohort['logical_mutations'], 1)

    def test_clock_regression_is_visible_and_duration_stays_independent(self):
        attempt = self.journal.begin('context')
        self.clock.advance(seconds=-1)
        row = self.journal.finish(attempt, result='completed', duration_ms=123)
        self.clock.advance(seconds=2)
        report = self.report()
        self.assertTrue(row['clock_regressed'])
        self.assertIn('clock_anomaly', report['coverage']['limitations'])
        self.assertEqual(report['cohort']['duration_ms']['sum'], 123)

    def test_strict_symbols_bounds_and_timestamps_do_not_write_bad_metadata(self):
        for operation in ('PRIVATE_TASK', 'capture; echo secret', '', {}, None):
            with self.subTest(operation=operation), self.assertRaises(OperationJournalError):
                self.journal.begin(operation)
        for identity in ('', 'x' * 4097, 'é' * 3000, '\ud800', {}, False):
            with self.subTest(identity=repr(identity)[:30]), self.assertRaises(OperationJournalError):
                self.journal.begin('capture', idempotency_key=identity)
        attempt = self.journal.begin('context')
        for duration in (math.inf, math.nan, -1, True, 10**16, '1'):
            with self.subTest(duration=duration), self.assertRaises(OperationJournalError):
                self.journal.finish(attempt, result='completed', duration_ms=duration)
        with self.assertRaises(OperationJournalError):
            self.journal.finish(attempt, result='PRIVATE_EXCEPTION')
        with self.assertRaises(OperationJournalError):
            self.journal.finish(attempt, result='error', failure_stage='PRIVATE_TRACEBACK')
        self.clock.advance(seconds=1)
        with self.assertRaises(OperationJournalError):
            self.journal.report(since=datetime(2026, 9, 1))
        with self.assertRaises(OperationJournalError):
            self.journal.report(since=self.start, until=self.clock.now + timedelta(seconds=1))
        with self.assertRaises(OperationJournalError):
            self.journal.report(since=self.clock.now, until=self.start)
        self.assertEqual(self.report()['cohort']['pending_now'], 1)

    def test_empty_report_and_pre_journal_window_are_explicit(self):
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['status'], 'incomplete')
        self.assertIn('window_predates_journal', report['coverage']['limitations'])
        self.assertEqual(report['cohort']['duration_ms']['count'], 0)
        self.assertIsNone(report['cohort']['duration_ms']['mean'])
        self.assertTrue(report['coverage']['metadata_integrity_verified'])

    def test_runtime_version_is_installed_provenance_and_retry_uses_current_runtime(self):
        with patch('ekk.__version__', '0.6.0'):
            attempt = self.journal.begin('capture', idempotency_key='stable')
            self.journal.finish(attempt, result='conflict', error_code='stale_snapshot', duration_ms=1)
        with patch('ekk.__version__', '0.6.1-rc.1+build.2'):
            retry = self.journal.retry(attempt)
            self.journal.finish(retry, result='completed', duration_ms=1)
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['cohort']['runtime_versions'], {'0.6.0': 1, '0.6.1-rc.1+build.2': 1})
        self.assertEqual(set(report['by_runtime_version']), {'0.6.0', '0.6.1-rc.1+build.2'})
        self.assertEqual(report['cohort']['logical_operations'], 1)
        self.assertEqual(report['cohort']['logical_results']['completed'], 1)
        with self.assertRaises(TypeError):
            self.journal.begin('capture', runtime_version='caller-provided')
        with self.assertRaises(TypeError):
            self.journal.finish(retry, result='completed', runtime_version='caller-provided')

    def test_earlier_06_rows_missing_additive_fields_remain_unknown_and_writable(self):
        with patch('ekk.__version__', '0.6.0'):
            old_error = self.journal.begin('capture')
            self.journal.finish(old_error, result='error', duration_ms=1)
            old_pending = self.journal.begin('context')
        rows = self.rows()
        for row in rows:
            del row['runtime_version']
            del row['error_code']
        self.overwrite_rows(rows)
        original = self.journal.path.read_bytes()
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['coverage']['metadata_integrity_verified'])
        self.assertEqual(report['cohort']['runtime_versions'], {'unknown': 2})
        self.assertEqual(report['by_runtime_version']['unknown']['attempts'], 2)
        self.assertEqual(report['cohort']['error_codes']['unspecified'], 1)
        self.assertEqual(self.journal.path.read_bytes(), original)
        with patch('ekk.__version__', '0.6.1'):
            child = self.journal.retry(old_error)
            self.journal.finish(child, result='completed', duration_ms=1)
            self.journal.finish(old_pending, result='completed', duration_ms=1)
        stored = {row['attempt_id']: row for row in self.rows()}
        self.assertEqual(stored[old_error.attempt_id]['runtime_version'], 'unknown')
        self.assertEqual(stored[old_pending.attempt_id]['runtime_version'], 'unknown')
        self.assertEqual(stored[child.attempt_id]['runtime_version'], '0.6.1')
        self.assertIsNone(stored[child.attempt_id]['error_code'])

    def test_runtime_version_shape_and_bound_reject_invalid_installed_values(self):
        bad_versions = ('PRIVATE_RUNTIME_CREDENTIAL', '0.6', '01.6.0', '0.6.0-01',
                        '0.6.0;PRIVATE_PAYLOAD', '0.6.0+' + 'a' * 59, None, {}, 6)
        for version in bad_versions:
            with self.subTest(version=version), patch('ekk.__version__', version):
                with self.assertRaises(OperationJournalError):
                    self.journal.begin('context')
        self.assertFalse(self.journal.path.exists())
        with patch('ekk.__version__', '0.6.0+' + 'a' * 58):
            attempt = self.journal.begin('context')
        self.assertEqual(len(self.rows()[0]['runtime_version']), 64)
        self.journal.finish(attempt, result='completed', duration_ms=1)
        rows = self.rows()
        rows[0]['runtime_version'] = 'PRIVATE_CORRUPT_RUNTIME'
        self.overwrite_rows(rows)
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['coverage']['damaged_records'], 1)
        self.assertNotIn('PRIVATE_CORRUPT_RUNTIME', json.dumps(report))

    def test_error_code_aggregates_use_fixed_symbols_and_exclude_pending_success(self):
        for code in sorted(ERROR_CODES):
            attempt = self.journal.begin('capture')
            self.journal.finish(attempt, result='error', error_code=code, duration_ms=1)
        unspecified = self.journal.begin('capture')
        self.journal.finish(unspecified, result='error', duration_ms=1)
        success = self.journal.begin('capture')
        self.journal.finish(success, result='completed', duration_ms=1)
        self.journal.begin('capture')
        self.clock.advance(seconds=1)
        report = self.report()
        self.assertEqual(report['cohort']['error_codes'], {**{code: 1 for code in ERROR_CODES}, 'unspecified': 1})
        self.assertEqual(set(report['by_error_code']), ERROR_CODES | {'unspecified'})
        self.assertEqual(report['by_error_code']['access_denied']['finished_attempts'], 1)
        self.assertEqual(sum(report['cohort']['error_codes'].values()), report['cohort']['failed_attempts'])

    def test_error_codes_reject_free_text_without_mutating_or_leaking_bytes(self):
        attempt = self.journal.begin('capture')
        before = self.journal.path.read_bytes()
        for value in ('PRIVATE_RAW_ERROR_MESSAGE', 'access_denied: PRIVATE_SECRET', '', {}, 1):
            with self.subTest(value=value), self.assertRaises(OperationJournalError):
                self.journal.finish(attempt, result='error', error_code=value)
        with self.assertRaises(OperationJournalError):
            self.journal.finish(attempt, result='completed', error_code='internal_error')
        self.assertEqual(self.journal.path.read_bytes(), before)
        row = self.journal.finish(attempt, result='error', error_code='access_denied', duration_ms=1)
        self.assertEqual(self.journal.finish(attempt, result='error', error_code='access_denied'), row)
        with self.assertRaises(OperationJournalError):
            self.journal.finish(attempt, result='error', error_code='internal_error')
        self.clock.advance(seconds=1)
        self.assertNotIn('PRIVATE', self.journal.path.read_text())
        self.assertNotIn('PRIVATE', json.dumps(self.report()))


if __name__ == '__main__':
    unittest.main()
