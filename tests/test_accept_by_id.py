"""Acceptance by ID (0.10.1): the owner's words as a host-chat statement, current exact references and named refusals."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.command_line import main, service
from ekk.adapters.git_store import GitStore
from ekk.adapters.host_identity import SCRUB_VARIABLES
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.application.errors import RequestError
from ekk.application.experience import STATEMENT_WORDS, host_chat_statement
from ekk.application.service import AcceptanceRefused, acceptance_key, acceptance_statement
from ekk.model import Conflict, digest

AT = '2026-10-10T12:00:00Z'
STATEMENT = {'by': 'owner', 'via': 'host_chat', 'host': 'claude-code', 'session': 's-1', 'at': AT, 'words': 'Yes, accept it.'}
# The receipt as 0.10.0 writes it; a statement is the only optional key.
RECEIPT_KEYS = {'schema', 'id', 'record_id', 'record_revision', 'record_sha256', 'adopted_at', 'actor', 'governance_sha256',
                'policy_version', 'authority_basis', 'base', 'supersedes', 'statement'}
# operation_journal.ERROR_CODES of 0.10.0 and of the gateway's 0.8.0, which count any other code as damage.
FROZEN_ERROR_CODES = {'access_denied', 'recovery_required', 'stale_snapshot', 'source_unavailable', 'unsupported_capability',
                      'unresolved_binding', 'invalid_format', 'cancelled', 'internal_error', 'dirty_working_tree',
                      'idempotency_conflict', 'lock_busy'}
DECISION = {'schema': 'ekk.decision/0.1', 'stated_by': 'agent', 'source': {'host': 'unknown', 'at': '2026-10-10'}}


class HostChatStatementTests(unittest.TestCase):
    def build(self, words, **given):
        return host_chat_statement(words, **{'host': 'claude-code', 'session': 's-1', 'at': AT, **given})

    def test_words_are_stripped_kept_verbatim_and_bounded(self):
        statement, sha256, chars = self.build('  \u0414\u0430, \u043f\u0440\u0438\u043d\u044f\u0442\u044c:\n  «\u043a\u0430\u043a \u0435\u0441\u0442\u044c».\t\n'.encode())
        self.assertEqual({**STATEMENT, 'words': '\u0414\u0430, \u043f\u0440\u0438\u043d\u044f\u0442\u044c:\n  «\u043a\u0430\u043a \u0435\u0441\u0442\u044c».'}, statement)
        self.assertEqual((hashlib.sha256('  \u0414\u0430, \u043f\u0440\u0438\u043d\u044f\u0442\u044c:\n  «\u043a\u0430\u043a \u0435\u0441\u0442\u044c».\t\n'.encode()).hexdigest(), 26), (sha256, chars))
        self.assertEqual(statement, acceptance_statement(statement))  # within the closed keys and bounds, unchanged
        exact = 'w' * STATEMENT_WORDS
        self.assertEqual(exact, self.build(exact.encode())[0]['words'])
        with self.assertRaises(RequestError) as raised:
            self.build(('w' * 601).encode())
        self.assertEqual(('words_too_long', '--words'), (raised.exception.refusal, raised.exception.option))
        self.assertIn('601', str(raised.exception)); self.assertIn('600', str(raised.exception))
        statement, sha256, chars = self.build(b' ' + b'w' * 700 + b'\n', overflow='excerpt')
        self.assertEqual(('w' * 600, hashlib.sha256(b' ' + b'w' * 700 + b'\n').hexdigest(), 700), (statement['words'], sha256, chars))

    def test_refusals_name_their_option_and_words_come_first(self):
        for words, given, refusal in ((b' \n\t', {}, 'words_missing'), (b'\xff\xfe yes', {}, 'words_unreadable'),
                                      (b'', {'session': None}, 'words_missing'), (b'Yes', {'session': None}, 'session_identity_missing'),
                                      (b'Yes', {'session': '', 'host': 'unknown'}, 'session_identity_missing')):
            with self.subTest(words=words, given=given), self.assertRaises(RequestError) as raised:
                self.build(words, option='--owner-words', **given)
            self.assertEqual((refusal, '--owner-words'), (raised.exception.refusal, raised.exception.option))

    def test_an_unknown_host_is_omitted(self):
        for host in ('unknown', None):
            self.assertNotIn('host', self.build(b'Yes', host=host)[0])
        self.assertEqual('codex', self.build(b'Yes', host='codex')[0]['host'])


class AcceptCurrentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = GitStore(root / 'realm', root / 'runtime')
        self.runtime = root / 'runtime'
        self.codec = MarkdownCodec()
        self.app = RealmService(self.store, 'owner', lambda: '2026-10-10T00:00:00Z', codec=self.codec)
        self.app.init('Synthetic', realm_id='realm:test', context_id='scope')
        proposal = self.app.capture(b'The owner said so.\n', title='Source', scope=['scope'], filename='original.txt')
        self.app.apply(proposal, idempotency_key='capture-source')
        self.source = next(hit['reference'] for hit in self.app.search_records(['scope'])['results'] if hit['kind'] == 'source')

    def add(self, key, *, revision=1, scopes=None, kind='decision', supersedes=None, **extra):
        extra.update({'basis': [self.source]} if kind in ('decision', 'policy') else {})
        if supersedes:
            extra['supersedes'] = [{k: ref[k] for k in ('id', 'revision', 'digest')} for ref in supersedes]
        metadata = {'schema': 'ekk.record/0.1', 'id': key, 'kind': kind, 'title': key, 'scope': scopes or ['scope'], 'revision': revision,
                    'created_at': '2026-10-10T00:00:00Z', 'created_by': 'owner', **extra}
        raw = self.codec.encode(metadata, f'{kind} {key}.\n')
        self.app.apply(self.app.propose({f'records/{key}.md': raw}), idempotency_key=f'{key}-{revision}')
        return {'realm': 'realm:test', 'id': key, 'revision': revision, 'digest': 'sha256:' + digest(raw)}

    def receipts(self):
        return {path: raw for path, raw in self.store.snapshot()['files'].items() if path.startswith('governance/receipts/')}

    def refused(self, scopes, ids, error=AcceptanceRefused, **given):
        before = self.store.snapshot()['revision']
        with self.assertRaises(error) as raised:
            self.app.accept_current(scopes, ids, statement=STATEMENT, **given)
        self.assertEqual(before, self.store.snapshot()['revision'])  # nothing is written
        return raised.exception

    def test_one_decision_is_accepted_at_its_current_version_and_again_is_already_accepted(self):
        self.add('decision-one')
        current = self.add('decision-one', revision=2)
        result = self.app.accept_current(['scope'], ['decision-one'], statement=STATEMENT)
        self.assertEqual(('accepted', [current], [current], STATEMENT), (result['state'], result['references'], result['written'], result['statement']))
        (path, raw), = self.receipts().items()
        receipt = json.loads(raw)
        self.assertEqual((RECEIPT_KEYS, STATEMENT, 2), (set(receipt), receipt['statement'], receipt['record_revision']))
        revision = self.store.snapshot()['revision']
        # Other words later write nothing: the receipt keeps the words it was accepted with.
        again = self.app.accept_current(['scope'], ['decision-one'], statement={**STATEMENT, 'words': 'Other words.', 'at': '2026-10-11T00:00:00Z'})
        self.assertEqual(('already_accepted', [current], [], STATEMENT), (again['state'], again['references'], again['written'], again['statement']))
        self.assertEqual(({path: raw}, revision), (self.receipts(), self.store.snapshot()['revision']))
        self.assertIn('decision-one', self.app.doctor()['accepted'])

    def test_the_derived_key_is_stable_for_the_same_words_and_replays(self):
        reference = self.add('decision-one')
        base = self.store.snapshot()['revision']
        keys = []
        original = self.app.accept_records
        def recording(scopes, references, **given):
            keys.append(given['idempotency_key']); return original(scopes, references, **given)
        with patch.object(self.app, 'accept_records', side_effect=recording):
            first = self.app.accept_current(['scope'], ['decision-one'], statement=STATEMENT)
        expected = acceptance_key('realm:test', ['scope'], reference, {**STATEMENT, 'at': '2026-10-12T00:00:00Z'})
        self.assertEqual([expected], keys)  # the time is not part of the key
        self.assertTrue((self.runtime / 'journals' / (digest(expected.encode()) + '.json')).exists())
        self.assertNotEqual(expected, acceptance_key('realm:test', ['scope'], reference, {**STATEMENT, 'words': 'Other.'}))
        # A retry that raced the first write, with the same words at another time, replays its receipt.
        revision = self.store.snapshot()['revision']
        replay = self.app.accept_records(['scope'], [reference], expected_snapshot=base, idempotency_key=expected,
                                         statement={**STATEMENT, 'at': '2026-10-12T00:00:00Z'})
        self.assertEqual((STATEMENT, revision), (replay['statement'], self.store.snapshot()['revision']))
        self.assertEqual(first['publications'][0], replay)

    def test_a_given_key_names_each_record_of_the_chain_by_its_place(self):
        first = self.add('decision-one')
        self.add('decision-two', supersedes=[first])
        keys = []
        original = self.app.accept_records
        def recording(scopes, references, **given):
            keys.append(given['idempotency_key']); return original(scopes, references, **given)
        with patch.object(self.app, 'accept_records', side_effect=recording):
            self.app.accept_current(['scope'], ['decision-two', 'decision-one'], statement=STATEMENT, idempotency_key='owner-yes')
        self.assertEqual(['owner-yes', 'owner-yes-1'], keys)

    def test_a_chain_is_named_whole_and_written_predecessors_first(self):
        first = self.add('decision-one')
        second = self.add('decision-two', supersedes=[first])
        refused = self.refused(['scope'], ['decision-one'])
        self.assertEqual(('superseded_target', '--id', ('decision-two',), None), (refused.refusal, refused.option, refused.record_ids, refused.next))
        refused = self.refused(['scope'], ['decision-two'])
        self.assertEqual(('predecessor_blocks', 'unaccepted', ('decision-one',), None), (refused.refusal, refused.reason, refused.record_ids, refused.next))
        self.assertEqual(set(), set(self.receipts()))
        result = self.app.accept_current(['scope'], ['decision-two', 'decision-one'], statement=STATEMENT)
        self.assertEqual(([first, second], [first, second]), (result['references'], result['written']))
        receipts = {json.loads(raw)['record_id']: json.loads(raw) for raw in self.receipts().values()}
        self.assertEqual({'decision-one': STATEMENT, 'decision-two': STATEMENT}, {key: receipt['statement'] for key, receipt in receipts.items()})
        # One acceptance per record, the predecessor first: the successor's base is the predecessor's write.
        self.assertEqual(result['publications'][0]['revision'], receipts['decision-two']['base'])
        listed = self.app.card_view(['scope'])
        self.assertIn('decision-two', listed); self.assertNotIn('decision-one', listed)
        # A chain partly accepted already writes only what is missing.
        third = self.add('decision-three', supersedes=[second])
        result = self.app.accept_current(['scope'], ['decision-two', 'decision-three'], statement=STATEMENT)
        self.assertEqual(('accepted', [second, third], [third]), (result['state'], result['references'], result['written']))

    def test_predecessors_that_cannot_be_accepted_block_with_a_reason(self):
        outcome = self.add('outcome-one', kind='outcome')
        self.add('decision-over-outcome', supersedes=[outcome])
        refused = self.refused(['scope'], ['decision-over-outcome'])
        self.assertEqual(('predecessor_blocks', 'not_acceptable_kind', ('outcome-one',)), (refused.refusal, refused.reason, refused.record_ids))
        self.assertIn('outcome', str(refused))
        old = self.add('decision-old')
        self.add('decision-old', revision=2)
        self.add('decision-pinned', supersedes=[old])
        refused = self.refused(['scope'], ['decision-pinned', 'decision-old'])
        self.assertEqual(('predecessor_blocks', 'not_current', ('decision-old',)), (refused.refusal, refused.reason, refused.record_ids))
        self.add('other', kind='context', scopes=['other'], context={'purpose': 'Other'})
        narrow = self.add('decision-narrow')
        self.add('decision-wide', scopes=['scope', 'other'], supersedes=[narrow])
        refused = self.refused(['scope', 'other'], ['decision-wide', 'decision-narrow'])
        self.assertEqual(('predecessor_blocks', 'other_scopes', ('decision-narrow',)), (refused.refusal, refused.reason, refused.record_ids))
        # From the narrower context, the wider successor is outside it and is not named.
        refused = self.refused(['scope'], ['decision-narrow'])
        self.assertEqual(('superseded_target', ()), (refused.refusal, refused.record_ids))
        self.assertNotIn('decision-wide', str(refused))

    def test_unknown_unreadable_and_other_records_are_refused_by_name(self):
        self.add('note-plain', kind='note')
        refused = self.refused(['scope'], ['note-plain'])
        self.assertEqual(('not_a_decision', ('note-plain',)), (refused.refusal, refused.record_ids))
        self.add('decision-unique-name')
        for given, named in (('decision-unique', ('decision-unique-name',)), ('decision', ('decision-unique-name',)), ('decisio', ()), ('missing-record-id', ())):
            refused = self.refused(['scope'], [given], RequestError)
            self.assertEqual(('unknown_id', '--id', named, given), (refused.refusal, refused.option, refused.record_ids, refused.value))
        self.add('other', kind='context', scopes=['other'], context={'purpose': 'Other'})
        self.add('decision-elsewhere', scopes=['scope', 'other'])
        self.assertEqual((), self.refused(['scope'], ['decision-elsew'], RequestError).record_ids)  # never named outside the contexts
        self.refused(['scope'], ['decision-elsewhere'], PermissionError)
        self.assertEqual(['decision-elsewhere'], self.app.readable_prefix_matches(['scope', 'other'], 'decision-elsew'))
        self.assertEqual([], self.app.readable_prefix_matches(['scope'], 'decision-elsew'))
        self.assertEqual([], self.app.readable_prefix_matches(['scope'], 'decision'[:7]))
        for ids in ([], ['decision-unique-name', 'decision-unique-name']):
            self.assertEqual('--id', self.refused(['scope'], ids, RequestError).option)

    def test_refusals_name_the_callers_option(self):
        # A review page names its records with marks: no refusal tells its reader to use --id.
        first = self.add('decision-one')
        self.add('decision-two', supersedes=[first])
        self.add('note-plain', kind='note')
        mark = '[x] on the review page'
        for ids, refusal in ((['decision-one'], 'superseded_target'), (['decision-two'], 'predecessor_blocks'), (['note-plain'], 'not_a_decision'),
                             (['decision-on'], 'unknown_id'), ([], None), (['decision-one', 'decision-one'], None)):
            with self.subTest(ids=ids):
                refused = self.refused(['scope'], ids, RequestError, option=mark)
                self.assertEqual((refusal, mark), (refused.refusal, refused.option))
                self.assertNotIn('--id', str(refused))
        self.assertIn(f'name it with {mark} as well', str(self.refused(['scope'], ['decision-two'], option=mark)))
        self.assertIn('name it with --id as well', str(self.refused(['scope'], ['decision-two'])))

    def test_a_moved_snapshot_is_resolved_again_once(self):
        reference = self.add('decision-one')
        calls = []
        original = self.app.accept_records
        def racing(scopes, references, **given):
            calls.append(given['expected_snapshot'])
            if len(calls) == 1:
                self.add('note-meanwhile', kind='note')  # a queue worker publishes in between
            return original(scopes, references, **given)
        with patch.object(self.app, 'accept_records', side_effect=racing):
            result = self.app.accept_current(['scope'], ['decision-one'], statement=STATEMENT)
        self.assertEqual((2, [reference]), (len(calls), result['written']))
        self.assertNotEqual(calls[0], calls[1])
        self.assertIn('decision-one', self.app.doctor()['accepted'])

    def test_a_record_revised_meanwhile_is_target_changed_and_nothing_is_written(self):
        self.add('decision-one')
        original = self.app.accept_records
        def revising(scopes, references, **given):
            self.add('decision-one', revision=2)
            return original(scopes, references, **given)
        with patch.object(self.app, 'accept_records', side_effect=revising), self.assertRaises(AcceptanceRefused) as raised:
            self.app.accept_current(['scope'], ['decision-one'], statement=STATEMENT)
        self.assertEqual(('target_changed', ('decision-one',)), (raised.exception.refusal, raised.exception.record_ids))
        self.assertIn('revision 1 is now revision 2', str(raised.exception))
        self.assertFalse(hasattr(raised.exception, 'accepted_so_far'))
        self.assertEqual({}, self.receipts())

    def test_a_chain_failing_after_its_first_write_reports_what_was_accepted(self):
        first = self.add('decision-one')
        self.add('decision-two', supersedes=[first])
        original = self.app.accept_records
        def revising(scopes, references, **given):
            if references[0]['id'] == 'decision-two':
                self.add('decision-two', revision=2, supersedes=[first])
            return original(scopes, references, **given)
        with patch.object(self.app, 'accept_records', side_effect=revising), self.assertRaises(AcceptanceRefused) as raised:
            self.app.accept_current(['scope'], ['decision-one', 'decision-two'], statement=STATEMENT)
        self.assertEqual(('target_changed', [first]), (raised.exception.refusal, raised.exception.accepted_so_far))
        self.assertEqual(['decision-one'], [json.loads(raw)['record_id'] for raw in self.receipts().values()])

    def test_receipts_of_every_shape_validate_together(self):
        shapes = {'decision-none': None, 'decision-cli': {'by': 'owner', 'via': 'cli', 'at': '2026-10-02T10:00:00Z', 'words': 'Yes'},
                  'decision-page': {'by': 'owner', 'via': 'review_page', 'at': '2026-10-02T10:00:00Z'}}
        for key, statement in shapes.items():
            reference = self.add(key)
            self.app.accept_records(['scope'], [reference], expected_snapshot=self.store.snapshot()['revision'], idempotency_key='a-' + key, statement=statement)
        self.add('decision-chat')
        self.app.accept_current(['scope'], ['decision-chat'], statement=STATEMENT)
        report = self.app.doctor()
        self.assertTrue(report['ok'], report)
        self.assertEqual(set(shapes) | {'decision-chat'}, set(report['accepted']))
        receipts = {json.loads(raw)['record_id']: json.loads(raw) for raw in self.receipts().values()}
        self.assertEqual(RECEIPT_KEYS - {'statement'}, set(receipts['decision-none']))
        self.assertTrue(all(set(receipt) == RECEIPT_KEYS for key, receipt in receipts.items() if key != 'decision-none'))
        self.assertEqual(receipts['decision-chat']['statement'], acceptance_statement(receipts['decision-chat']['statement']))
        accepted = self.app._acceptances(self.store.snapshot(), self.app._query_view(['scope'])[3])
        self.assertEqual(set(shapes) | {'decision-chat'}, set(accepted))


class AcceptByIdCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve(); self.realm = self.root / 'realm'
        environment = {k: v for k, v in os.environ.items() if not k.startswith(('EKK_', 'GIT_')) and k not in SCRUB_VARIABLES}
        environment.update(EKK_DATA_HOME=str(self.root / 'data'), EKK_CONFIG_HOME=str(self.root / 'config'), EKK_CACHE_HOME=str(self.root / 'cache'))
        env = patch.dict(os.environ, environment, clear=True); env.start(); self.addCleanup(env.stop)
        clock = patch('ekk.adapters.command_line._now', return_value=AT); clock.start(); self.addCleanup(clock.stop)
        code, data = self.call(['init', '--root', str(self.realm), '--title', 'Example'])
        self.assertEqual(code, 0, data)
        self.app = service(self.realm)
        self.scope = self.app.codec.load_yaml(self.app.store.snapshot()['files']['.ekk/realm.yaml'])['default_context']
        self.base = ['--root', str(self.realm), '--scope', self.scope]
        self.words = self.words_file('words.txt', '  Yes, accept it.\n')

    def call(self, args, body=None, environment=None):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), patch('sys.stdin', io.StringIO(json.dumps(body))), \
                patch.dict(os.environ, environment or {}):
            code = main(args + (['--stdin'] if body is not None else []))
        return code, json.loads(output.getvalue() or error.getvalue())

    def words_file(self, name, text):
        path = self.root / name
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return path

    def decide(self, title, supersedes=None, kind=None):
        if kind:
            metadata = self.app._meta(kind, title, [self.scope])
            self.app.apply(self.app.propose({f"records/{metadata['id']}.md": self.app.codec.encode(metadata, title + '.\n')}), idempotency_key='make-' + title)
        else:
            proposal = self.app.decide(title + '.', title=title, scope=[self.scope], decision=DECISION,
                                       supersedes=[{k: ref[k] for k in ('id', 'revision', 'digest')} for ref in supersedes or ()] or None)
            self.app.apply(proposal, idempotency_key='decide-' + title)
        snapshot, realm, _, records = self.app._query_view([self.scope])
        return self.app._query_reference(realm['id'], next(row for row in records.values() if row['metadata']['title'] == title))

    def receipts(self):
        return {path: raw for path, raw in self.app.store.snapshot()['files'].items() if path.startswith('governance/receipts/')}

    def accept(self, *ids, words=None, environment=None, extra=(), body=None):
        argv = ['accept', *self.base, *[part for key in ids for part in ('--id', key)], *(['--words', str(words)] if words else []), *extra]
        return self.call(argv, body, {'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 's-1'} if environment is None else environment)

    def test_accept_records_the_owners_words_with_the_host_session_and_the_runtime_clock(self):
        decision = self.decide('BM25 stays')
        code, result = self.accept(decision['id'], words=self.words)
        self.assertEqual(0, code, result)
        self.assertEqual(('accepted', [decision], STATEMENT), (result['state'], result['written'], result['statement']))
        receipt = json.loads(*self.receipts().values())
        self.assertEqual((STATEMENT, RECEIPT_KEYS), (receipt['statement'], set(receipt)))
        report = self.app.doctor()
        self.assertTrue(report['ok'], report); self.assertIn(decision['id'], report['accepted'])
        # Again with other words: nothing is written and the first words are returned.
        receipts, revision = self.receipts(), self.app.store.snapshot()['revision']
        code, again = self.accept(decision['id'], words=self.words_file('other.txt', 'Other words.'))
        self.assertEqual((0, 'already_accepted', STATEMENT), (code, again['state'], again['statement']), again)
        self.assertEqual((receipts, revision), (self.receipts(), self.app.store.snapshot()['revision']))

    def test_the_session_comes_from_the_hosts_declared_variables_only(self):
        cases = (({'CLAUDECODE': '1', 'CLAUDE_SESSION_ID': 'old-name'}, 'claude-code', 'old-name'),
                 ({'CLAUDECODE': '1', 'CLAUDE_SESSION_ID': 'old-name', 'CLAUDE_CODE_SESSION_ID': 's-2'}, 'claude-code', 's-2'),
                 ({'CODEX_HOME': str(self.root / '.codex'), 'CODEX_THREAD_ID': 'thread-1', 'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 's-3'}, 'codex', 'thread-1'))
        for index, (environment, host, session) in enumerate(cases):
            with self.subTest(environment=environment):
                decision = self.decide(f'Decision {index}')
                code, result = self.accept(decision['id'], words=self.words, environment=environment)
                self.assertEqual(0, code, result)
                self.assertEqual({**STATEMENT, 'host': host, 'session': session}, result['statement'])
        decision = self.decide('Never the host session')
        for environment in ({'CLAUDECODE': '1', 'CLAUDE_CODE_HOST_SESSION_ID': 'host-1', 'CLAUDE_CODE_CHILD_SESSION': '1'}, {},
                            {'CODEX_HOME': str(self.root / '.codex'), 'CLAUDE_CODE_SESSION_ID': 's-1'}):
            with self.subTest(environment=environment):
                code, error = self.accept(decision['id'], words=self.words, environment=environment)
                self.assertEqual((2, 'invalid_request', 'session_identity_missing', '--words'), (code, error['error'], error['refusal'], error['option']), error)
        self.assertNotIn('host-1', json.dumps([json.loads(raw) for raw in self.receipts().values()]))

    def test_each_refusal_is_named_with_its_option_and_the_command_to_run(self):
        decision = self.decide('A decision')
        full = decision['id']
        note = self.decide('A note', kind='note')
        route = '--cwd ' + shlex.quote(str(Path.cwd())) + ' --root ' + shlex.quote(str(self.realm)) + ' --scope ' + shlex.quote(self.scope)
        cases = [
            ((full,), None, (), None, 'words_missing', '--words', f'ekk accept {route} --id {full} --words FILE'),
            ((full,), self.words_file('blank.txt', ' \n\t\n'), (), None, 'words_missing', '--words', None),
            ((full,), self.root / 'Yes, accept it.', (), None, 'words_unreadable', '--words', None),
            ((full,), self.words_file('latin1.txt', 'Oui, acceptée.'.encode('latin-1')), (), None, 'words_unreadable', '--words', None),
            ((full,), self.words_file('long.txt', 'w' * 601), (), None, 'words_too_long', '--words', None),
            (('missing-record-id',), self.words, (), None, 'unknown_id', '--id', None),
            ((full[:8],), self.words, (), None, 'unknown_id', '--id',
             'ekk ' + shlex.join(['accept', *self.base, '--id', full, '--words', str(self.words)])),
            ((note['id'],), self.words, (), None, 'not_a_decision', '--id', None),
        ]
        for ids, words, extra, body, refusal, option, command in cases:
            with self.subTest(refusal=refusal, words=words):
                code, error = self.accept(*ids, words=words, extra=extra, body=body)
                self.assertEqual((2, 'invalid_request', refusal, option), (code, error['error'], error.get('refusal'), error.get('option')), error)
                self.assertEqual(command, error.get('next'))
        self.assertIn('takes the path of a file', self.accept(full, words=self.root / 'Yes, accept it.')[1]['message'])
        self.assertEqual([full], self.accept(full[:8], words=self.words)[1]['record_ids'])
        self.assertEqual({}, self.receipts())
        # Conflicting forms name the option at fault.
        statement_file = self.words_file('statement.json', json.dumps({'by': 'owner', 'via': 'cli', 'at': AT}))
        retain = ['retain', *self.base, '--title', 'T', '--words', str(self.words)]
        for argv, body, option in ((['accept', *self.base, '--id', full, '--words', str(self.words)], {'references': [decision]}, '--id'),
                                   (['accept', *self.base, '--id', full, '--words', str(self.words)], {'expected_snapshot': 'a' * 40}, '--id'),
                                   (['accept', *self.base, '--id', full, '--words', str(self.words), '--statement-file', str(statement_file)], None, '--words'),
                                   (['accept', *self.base, '--id', full, '--statement-file', str(statement_file)], {'statement': {}}, '--statement-file'),
                                   (['accept', *self.base, '--words', str(self.words)], {'references': [decision], 'statement': {}}, '--words'),
                                   (retain, {'body': 'x'}, '--words'),
                                   (['decide', *self.base, '--title', 'T', '--words', str(self.words)], {'body': 'x'}, '--words'),
                                   (['accept', *self.base], {}, 'references'),
                                   (['accept', *self.base], {'references': [decision]}, 'expected_snapshot'),
                                   (['accept', *self.base], {'references': [decision], 'expected_snapshot': 'a' * 40}, 'idempotency_key')):
            with self.subTest(argv=argv, body=body):
                code, error = self.call(argv, body)
                self.assertEqual((2, 'invalid_request', option), (code, error['error'], error['option']), error)
        code, error = self.call(['accept', *self.base], {})
        self.assertIn('references, expected_snapshot, idempotency_key', error['message']); self.assertIn('--id', error['message'])
        self.assertEqual({}, self.receipts())

    def test_the_prefix_help_names_only_records_the_selected_contexts_can_read(self):
        # A decision in the selected context that rests on a note in another one: every read from the selected context hides it.
        def put(key, kind, scope, body, **extra):
            raw = self.app.codec.encode(dict(self.app._meta(kind, key, [scope], **extra), id=key), body)
            self.app.apply(self.app.propose({f'records/{key}.md': raw}), idempotency_key='put-' + key)
            return {'id': key, 'revision': 1, 'digest': 'sha256:' + digest(raw)}
        put('context-other', 'context', 'context-other', '', context={'purpose': 'Other'})
        note = put('note-in-other', 'note', 'context-other', 'Elsewhere.\n')
        full = put('decision-resting-on-other-0001', 'decision', self.scope, 'Decision.\n', basis=[note])['id']
        fetch = ['fetch', *self.base, '--id']
        for code, error in (self.call([*fetch, full]), self.accept(full, words=self.words)):
            self.assertEqual((2, 'access_denied'), (code, error['error']), error)
        for code, error in (self.call([*fetch, 'decision-resting']), self.accept('decision-resting', words=self.words)):
            self.assertEqual((2, 'invalid_request', 'unknown_id', '--id'), (code, error['error'], error['refusal'], error['option']), error)
            self.assertEqual(set(), {'record_ids', 'next'} & set(error), error)
            self.assertNotIn(full, error['message'])
        # Selected together with the other context, the decision is readable and its prefix is named.
        both = ['fetch', '--root', str(self.realm), '--scope', self.scope, '--scope', 'context-other', '--id']
        code, error = self.call([*both, 'decision-resting'])
        self.assertEqual((2, [full], 'ekk ' + shlex.join([*both, full])), (code, error.get('record_ids'), error.get('next')), error)
        self.assertEqual({}, self.receipts())

    def test_a_chain_is_accepted_by_naming_it_and_refusals_name_the_whole_chain(self):
        first = self.decide('First')
        second = self.decide('Second', supersedes=[first])
        code, error = self.accept(first['id'], words=self.words)
        self.assertEqual((2, 'superseded_target', [second['id']]), (code, error['refusal'], error['record_ids']), error)
        # No command is offered: whether the owner's words cover the other record is the owner's to say.
        self.assertNotIn('next', error); self.assertIn('ask the owner', error['message'])
        code, error = self.accept(second['id'], words=self.words)
        self.assertEqual((2, 'predecessor_blocks', [first['id']]), (code, error['refusal'], error['record_ids']), error)
        self.assertIn('(unaccepted)', error['message']); self.assertNotIn('next', error)
        self.assertEqual({}, self.receipts())
        code, result = self.accept(second['id'], first['id'], words=self.words)
        self.assertEqual((0, [first, second]), (code, result['written']), result)
        self.assertEqual({first['id'], second['id']}, {json.loads(raw)['record_id'] for raw in self.receipts().values()})
        listed = self.app.card_view([self.scope])
        self.assertIn(second['id'], listed); self.assertNotIn(first['id'], listed)
        outcome = self.decide('An outcome', kind='outcome')
        over = self.decide('Over the outcome', supersedes=[outcome])
        code, error = self.accept(over['id'], words=self.words)
        self.assertEqual((2, 'predecessor_blocks', [outcome['id']]), (code, error['refusal'], error['record_ids']), error)
        self.assertIn('(not_acceptable_kind)', error['message']); self.assertNotIn('next', error)

    def test_the_json_form_is_unchanged_and_takes_words_too(self):
        decision = self.decide('A decision')
        request = {'references': [decision], 'expected_snapshot': self.app.store.snapshot()['revision'], 'idempotency_key': 'json-words'}
        code, result = self.accept(words=self.words, body=request)
        self.assertEqual((0, 'published', STATEMENT), (code, result['state'], result['statement']), result)
        self.assertEqual(STATEMENT, json.loads(*self.receipts().values())['statement'])

    def test_a_failure_after_the_first_write_names_what_was_accepted(self):
        first = self.decide('First')
        second = self.decide('Second', supersedes=[first])
        original = RealmService.accept_records
        def revising(app, scopes, references, **given):
            if references[0]['id'] == second['id']:
                metadata = dict(app._query_view(scopes)[3][second['id']]['metadata'], revision=2)
                app.apply(app.propose({f"records/{second['id']}.md": app.codec.encode(metadata, 'Second, revised.\n')}), idempotency_key='revise')
            return original(app, scopes, references, **given)
        with patch.object(RealmService, 'accept_records', autospec=True, side_effect=revising):
            code, error = self.accept(first['id'], second['id'], words=self.words)
        self.assertEqual((2, 'target_changed', [second['id']], [first]), (code, error['refusal'], error['record_ids'], error['accepted_so_far']), error)
        self.assertNotIn('next', error)

    def test_journal_rows_of_refusals_keep_the_codes_older_readers_know(self):
        decision = self.decide('A decision')
        note = self.decide('A note', kind='note')
        self.accept(decision['id'])
        self.accept(decision['id'], words=self.root / 'missing.txt')
        self.accept(note['id'], words=self.words)
        self.accept(decision['id'][:8], words=self.words)
        self.accept(decision['id'], words=self.words, environment={})
        self.call(['accept', *self.base], {})
        rows = [json.loads(line) for line in (self.root / 'data/operations/operations.jsonl').read_text().splitlines()]
        failed = [row for row in rows if row.get('result') == 'error']
        self.assertEqual(6, len(failed))
        self.assertEqual({('invalid_format', 'request')}, {(row['error_code'], row['failure_stage']) for row in failed})
        self.assertTrue(all(row['error_code'] in FROZEN_ERROR_CODES for row in rows if row.get('error_code')))
        from ekk.adapters.operation_diagnostics import journal
        self.assertEqual(0, journal().report()['coverage']['damaged_records'])


if __name__ == '__main__':
    unittest.main()
