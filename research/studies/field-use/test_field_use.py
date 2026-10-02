"""Contract tests for the field-use collector on synthetic host logs."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import field_use  # noqa: E402

RECORD = '11111111-2222-4333-8444-555555555555'
OTHER = '99999999-2222-4333-8444-555555555555'
PUBLISHED = json.dumps({'state': 'published', 'result_reference': {'id': RECORD},
                        'retention': {'state': 'read_back_and_discoverable', 'read_back': True}}, indent=2)
QUEUED = json.dumps({'schema': 'ekk.retention-queued/0.1', 'key': 'retain-abc', 'state': 'local_pending'}, indent=2)
REALM = 'aaaaaaaa-2222-4333-8444-555555555555'
SOURCE = 'bbbbbbbb-2222-4333-8444-555555555555'
# Digest of the content of ekk.correction-rule/1 with ekk.field-use-collector/1.
RULE_1_DIGEST = 'sha256:778dca9ee5793bc15d55d2fb9ac4727f740b8c538e9119da1eecfa7a9a6ebd82'


def compact(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False)


def codex_line(kind, payload, stamp='2026-09-20T10:00:00Z'):
    return compact({'timestamp': stamp, 'type': kind, 'payload': payload})


def command(cmd, output, stamp, exit_code=0):
    return codex_line('event_msg', {'type': 'item_completed', 'item': {
        'type': 'CommandExecution', 'command': ['/bin/zsh', '-lc', cmd],
        'aggregated_output': output, 'exit_code': exit_code}}, stamp)


def codex_item(kind, stamp, **fields):
    return codex_line('event_msg', {'type': 'item_completed', 'item': {'type': kind, **fields}}, stamp)


def owner(text, stamp):
    return codex_item('UserMessage', stamp, content=[{'type': 'text', 'text': text}])


def done(text, stamp):
    return codex_line('event_msg', {'type': 'task_complete', 'turn_id': stamp, 'last_agent_message': text}, stamp)


def claude(kind, uuid, stamp, content, **extra):
    message = {'role': kind, 'content': content}
    if kind == 'assistant':
        message.update(model='claude-test', stop_reason=extra.pop('stop', 'tool_use'))
    return compact({'type': kind, 'uuid': uuid, 'timestamp': stamp, 'cwd': extra.pop('cwd'), 'message': message, **extra})


def tool(use_id, name, **given):
    return [{'type': 'tool_use', 'id': use_id, 'name': name, 'input': given}]


def result(use_id, output='ok', is_error=False):
    return [{'type': 'tool_result', 'tool_use_id': use_id, 'content': output, 'is_error': is_error}]


class FieldUseTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.project = self.root / 'project'
        (self.project / '.ekk').mkdir(parents=True)
        (self.project / '.ekk/workspace.yaml').write_text('schema: ekk.workspace/0.1\n')
        entry = json.dumps({'schema': 'ekk.context-brief/0.2', 'items': [
            {'title': 'Payout minimum', 'kind': 'outcome', 'summary': 'Raised to 3000.', 'ref': {'id': RECORD}}]})
        day = self.root / 'codex/sessions/2026/09/20'
        day.mkdir(parents=True)
        lines = [
            codex_line('session_meta', {'cwd': str(self.project), 'thread_source': 'user', 'timestamp': '2026-09-20T10:00:00Z'}),
            codex_line('turn_context', {'model': 'model-a'}),
            codex_line('response_item', {'role': 'user', 'content': [{'type': 'input_text', 'text': 'raise payout'}]}),
            command("ekk enter --cwd . --task 'payout minimum' --brief", entry, '2026-09-20T10:01:00Z'),
            command('ekk retain --cwd . --title x --wait', PUBLISHED, '2026-09-20T10:05:00Z'),
            command('ekk retain --help', 'usage', '2026-09-20T10:06:00Z'),
        ]
        (day / 'rollout-a.jsonl').write_text('\n'.join(lines) + '\n')
        later = [
            codex_line('session_meta', {'cwd': str(self.project), 'thread_source': 'subagent', 'timestamp': '2026-09-21T10:00:00Z'}),
            command("ekk enter --cwd . --task 'payout minimum'", entry, '2026-09-21T10:01:00Z'),
            command('ekk fetch --cwd . --id ' + RECORD, '{}', '2026-09-21T10:02:00Z'),
        ]
        (day / 'rollout-b.jsonl').write_text('\n'.join(later) + '\n')
        self.out = self.root / 'out'

    def run_tool(self, *extra, codex='codex/sessions/*/*/*/*.jsonl', claude='none/*.jsonl', command='run'):
        argv = [command, '--out', str(self.out), '--codex', str(self.root / codex),
                '--claude', str(self.root / claude), '--journal', str(self.root / 'missing.jsonl'), *extra]
        field_use.main(argv)
        return json.loads((self.out / 'report.json').read_text())

    def sessions(self):
        return {s['session']: s for s in field_use.read_jsonl(self.out / 'sessions.jsonl')}

    def test_episodes_and_report(self):
        report = self.run_tool()
        episodes = field_use.read_jsonl(self.out / 'episodes.jsonl')
        ops = [(e['op'], e['help']) for e in episodes]
        self.assertIn(('enter', False), ops)
        self.assertIn(('retain', True), ops)
        self.assertEqual(report['enter_calls'], {'total': 2, 'from_subagents': 1})
        self.assertEqual(report['reuse'], {'created_ids': 1, 'resurfaced_in_later_sessions': 1,
                                           'writes_without_record_id': 0})
        store = next(iter(field_use.tasks_by_project(self.out).values()))
        self.assertEqual((store['pairs'], store['writes_without_record_id']), ({('payout minimum', RECORD)}, 0))
        self.assertEqual(report['follow_up_after_enter']['followed_by_fetch_or_read'], 1)
        self.assertEqual(report['models']['model-a'], {'sessions': 1, 'with_ekk': 1})
        self.assertEqual(report['empty_content_share'], 0.0)
        project = next(k for k in report['adoption'] if k.startswith('project:'))
        self.assertTrue(project.endswith('project'))
        self.assertEqual(oct((self.out / 'episodes.jsonl').stat().st_mode & 0o777), '0o600')
        # The item delivered in the second session was fetched there; the first session never touched it.
        use = report['entry_use']['codex']
        self.assertEqual((use['enters'], use['delivered'], use['used'], use['by_signal']['fetch']), (2, 2, 1, 1))

    def test_journal_counts_operations_by_registered_caller(self):
        def row(caller, result, started):
            return json.dumps({'attempt_id': started, 'operation': 'enter', 'caller_profile': caller,
                               'result': result, 'started_at': started, 'duration_ms': 2000,
                               'runtime_version': '0.8.2'})
        journal = self.root / 'operations.jsonl'
        journal.write_text('\n'.join([json.dumps({'schema': 'header'}),
            row('claude-code', 'completed', '2026-09-20T10:00:00Z'),
            row('claude-code', 'error', '2026-09-20T11:00:00Z'),
            row('work2', 'completed', '2026-09-20T12:00:00Z'),
            row('unknown', 'completed', '2026-09-20T13:00:00Z')]) + '\n')
        report = self.run_tool('--journal', str(journal),
                               '--journal-exclude', '2026-09-20T12:30:00Z/2026-09-20T13:30:00Z')
        self.assertEqual(report['journal']['by_caller'],
                         {'claude-code': {'completed': 1, 'not_completed': 1}, 'work2': {'completed': 1}})
        self.assertIn("by caller: {'claude-code'", (self.out / 'report.md').read_text())

    def test_comparison_ignores_only_assembly_timestamps(self):
        a = {'manifest': {'freshness': {'assembled_at': '2026-10-01T22:35:27Z', 'revision': 'r1'}}, 'items': [1]}
        b = {'manifest': {'freshness': {'assembled_at': '2026-10-01T22:35:30Z', 'revision': 'r1'}}, 'items': [1]}
        self.assertEqual(field_use.normalized(a), field_use.normalized(b))
        b['manifest']['freshness']['revision'] = 'r2'
        self.assertNotEqual(field_use.normalized(a), field_use.normalized(b))
        requests = self.root / 'requests.json'
        requests.write_text(json.dumps([{'label': 'enter', 'argv': ['enter', '--task', 'x']}]))
        self.assertEqual('enter', field_use.requests_from(requests)[0]['label'])
        requests.write_text(json.dumps([{'label': 'enter'}]))
        with self.assertRaises(SystemExit):
            field_use.requests_from(requests)

    def test_invocation_parsing(self):
        rows = field_use.invocations("/x/.local/bin/ekk queue submit --cwd . && cat ~/.agents/skills/ekk-workflow/SKILL.md")
        self.assertEqual([r['op'] for r in rows], ['queue.submit'])
        rows = field_use.invocations("ekk --profile personal enter --task \"a b\" --compact")
        self.assertEqual((rows[0]['op'], rows[0]['task'], rows[0]['flags']), ('enter', 'a b', ['compact']))

    def test_a_mention_is_not_an_invocation(self):
        for mention in ('grep -rn "ekk enter" docs/',
                        'rg -n \'ekk retain\' ~/.agents/skills',
                        "cat > notes.md <<'EOF'\nRun this first:\nekk enter --task x\nEOF",
                        'echo "then run ekk retain --stdin"',
                        'python tools/check.py --binary ekk enter',
                        'rg -n "^## .*retain|ekk retain|idempotency" docs/using.md',
                        "pgrep -af '/x/.local/bin/ekk retain|ekk retain' || true",
                        "python3 - <<'PY'\nekk retain --cwd . --title unterminated",
                        'ls ~/Library/Application\\ Support/EKK/runtime && which ekk'):
            self.assertEqual(field_use.invocations(mention), [], mention)
        ops = lambda text: [r['op'] for r in field_use.invocations(text)]
        self.assertEqual(ops('cd repo && timeout 60 EKK_DATA_HOME=/tmp/x ~/.local/bin/ekk enter --task y'), ['enter'])
        self.assertEqual(ops("KEY=$(ekk retain --cwd . --stdin <<'EOF'\n{\"title\": \"ekk enter --task z\"}\nEOF\n)"), ['retain'])
        self.assertEqual(ops('ekk doctor\nekk queue status --key k; ekk fetch --id ' + RECORD), ['doctor', 'queue.status', 'fetch'])
        self.assertEqual(ops('echo "$(timeout 15s ekk enter --task \'a|b\' --brief)"'), ['enter'])
        self.assertEqual(field_use.invocations('ekk fetch --id ' + RECORD)[0]['arg_ids'], [RECORD])
        self.assertTrue(field_use.commits('git add -A && git -c user.name=x commit -m "fix: don\'t"'))
        self.assertFalse(field_use.commits("rg -n 'git commit' docs && git status"))
        self.assertFalse(field_use.commits("cat <<'EOF'\ngit commit -m x\nEOF"))

    def test_retention_is_judged_by_the_receipt(self):
        state = field_use.receipt_state
        self.assertEqual(state(PUBLISHED, 1), 'published')
        self.assertEqual(state(QUEUED, 0), 'queued')
        outbox = {'schema': 'ekk.outbox/0.1', 'operations': [{'key': 'k', 'state': 'publishing', 'error': None}]}
        self.assertEqual(state(json.dumps(outbox), 0), 'queued')
        outbox['operations'][0]['state'] = 'read_back_and_discoverable'
        self.assertEqual(state(json.dumps(outbox), 0), 'published')
        self.assertEqual(state(json.dumps({'state': 'published', 'retention': {'state': 'read_back'}}), 0), 'queued')
        self.assertEqual(state(json.dumps({'error': {'code': 'invalid_request'}}), 0), 'failed')
        self.assertEqual(state('Traceback (most recent call last):\n  File', 0), 'failed')
        self.assertEqual(state('', 143), 'failed')
        self.assertEqual(state('', 0), 'unknown')  # output redirected to a file
        self.assertEqual(field_use.parse_output('retain', PUBLISHED)['outcome'], 'published')
        self.assertNotIn('outcome', field_use.parse_output('search', PUBLISHED))

    def test_entry_items_include_work_view_anchors(self):
        output = json.dumps({'schema': 'ekk.federated-context/0.1', 'contexts': [{
            'records': [{'id': RECORD, 'metadata': {'kind': 'outcome', 'title': 'Payout minimum'}, 'body': 'text'}],
            'work_view': {'visible_results': [{'title': 'Payout minimum', 'reference': {'id': RECORD}},
                                              {'title': 'Referral cap decision', 'reference': {'id': OTHER}}]}}]})
        items = field_use.parse_output('enter', output)['items']
        self.assertEqual([(i['id'], i['content_chars']) for i in items], [(RECORD, 4), (OTHER, None)])
        # Output cut by `head`: the IDs that reached the agent still count as delivered; a realm ID is not a record.
        cut = '{\n "realm": "' + OTHER + '",\n "records": [\n  {\n   "id": "' + RECORD + '",\n   "metadata": {'
        self.assertEqual([i['id'] for i in field_use.parse_output('enter', cut)['items']], [RECORD])

    def thread_logs(self):
        """One Codex thread in two rollout segments plus a subagent, and an unrelated mention-only session."""
        day = self.root / 'thread/sessions/2026/09/22'
        day.mkdir(parents=True)
        meta = {'session_id': 'thread-1', 'cwd': str(self.project), 'timestamp': '2026-09-22T09:00:00Z'}
        entry = json.dumps({'work_view': {'visible_results': [
            {'title': 'Payout minimum raised to 3000', 'reference': {'id': RECORD}},
            {'title': 'Referral cap decision of August', 'reference': {'id': OTHER}}]}})
        first = [
            codex_line('session_meta', {**meta, 'id': 'thread-1', 'thread_source': 'user'}),
            owner('\u043d\u0435 \u0442\u0440\u043e\u0433\u0430\u0439 \u0442\u0435\u0441\u0442\u044b, \u043f\u043e\u0434\u043d\u0438\u043c\u0438 \u043c\u0438\u043d\u0438\u043c\u0443\u043c \u0432\u044b\u043f\u043b\u0430\u0442\u044b', '2026-09-22T09:00:10Z'),
            command('ekk enter --cwd . --task payout --compact', entry, '2026-09-22T09:01:00Z'),
            codex_item('FileChange', '2026-09-22T09:02:00Z', status='completed', changes={'/p/payout.py': {}}),
            codex_item('FileChange', '2026-09-22T09:02:30Z', status='failed', changes={'/p/other.py': {}}),
            done('Raised it. Applied "Payout minimum raised to 3000".', '2026-09-22T09:03:00Z'),
        ]
        second = [
            codex_line('session_meta', {**meta, 'id': 'thread-1', 'thread_source': 'user'}),
            owner('# Context\n<system-reminder>x</system-reminder>\n## My request for Codex:\n'
                  '\u043d\u0435\u0442, \u044f \u0436\u0435 \u0433\u043e\u0432\u043e\u0440\u0438\u043b: \u043c\u0438\u043d\u0438\u043c\u0443\u043c 3000, \u0430 \u043d\u0435 300', '2026-09-22T11:00:00Z'),
            command('git -C . commit -m fix', '[main 1234567] fix', '2026-09-22T11:02:00Z'),
            done('Fixed.', '2026-09-22T11:03:00Z'),
            owner('\u0442\u0435\u043f\u0435\u0440\u044c \u0434\u043e\u0431\u0430\u0432\u044c \u0442\u0435\u0441\u0442 \u043d\u0430 \u0433\u0440\u0430\u043d\u0438\u0446\u0443', '2026-09-22T11:05:00Z'),
            owner('<task-notification>\u043d\u0435 \u0442\u0430\u043a</task-notification>', '2026-09-22T11:06:00Z'),
        ]
        child = [
            codex_line('session_meta', {**meta, 'id': 'child-1', 'thread_source': 'subagent'}),
            command('ekk retain --cwd . --stdin < /tmp/r.json', QUEUED, '2026-09-22T11:02:30Z'),
            done('\u043d\u0435 \u0442\u0430\u043a, \u0432\u0435\u0440\u043d\u0438', '2026-09-22T11:02:40Z'),
        ]
        loose = [
            codex_line('session_meta', {'session_id': 'thread-2', 'id': 'thread-2', 'thread_source': 'user',
                                        'cwd': str(self.root / 'elsewhere'), 'timestamp': '2026-09-22T12:00:00Z'}),
            owner('\u043f\u043e\u0441\u043c\u043e\u0442\u0440\u0438 \u043b\u043e\u0433\u0438', '2026-09-22T12:00:10Z'),
            command('grep -rn "ekk retain" docs', 'docs/a.md: ekk retain', '2026-09-22T12:01:00Z'),
            command('ekk retain --cwd . --title y > /tmp/out.json', '', '2026-09-22T12:02:00Z'),
            command('ekk capture --cwd . --url u', json.dumps({'error': {'code': 'unavailable'}}), '2026-09-22T12:02:30Z'),
            codex_item('FileChange', '2026-09-22T12:03:00Z', status='completed', changes={'/e/a.py': {}}),
        ]
        (day / 'rollout-2026-09-22T09-00-00-thread-1.jsonl').write_text('\n'.join(first) + '\n')
        (day / 'rollout-2026-09-22T11-00-00-thread-1_seg-2.jsonl').write_text('\n'.join(second) + '\n')
        (day / 'rollout-2026-09-22T11-02-00-thread-1_child-1.jsonl').write_text('\n'.join(child) + '\n')
        (day / 'rollout-2026-09-22T12-00-00-thread-2.jsonl').write_text('\n'.join(loose) + '\n')
        return 'thread/sessions/*/*/*/*.jsonl'

    def test_codex_thread_spans_files_and_counts_changes_retention_and_corrections(self):
        report = self.run_tool(codex=self.thread_logs())
        sessions = self.sessions()
        self.assertEqual(sorted(sessions), ['thread-1', 'thread-2'])
        one, two = sessions['thread-1'], sessions['thread-2']
        self.assertEqual((one['files'], one['subagent'], one['file_changes'], one['commits']), (3, False, 1, 1))
        self.assertEqual((one['changed'], one['retained'], one['retain']), (True, True, {'queued': 1}))
        # The first message precedes any agent work; the injected notification is not the owner's.
        self.assertEqual((one['user_messages'], one['owner_after_report'], one['corrections'], one['repeated_corrections']),
                         (3, 2, 1, 1))
        # A mention is not a call; a redirected receipt and an error receipt do not count as retained.
        self.assertEqual((two['ekk_calls'], two['changed'], two['retained']), (2, True, False))
        self.assertEqual(two['retain'], {'unknown': 1, 'failed': 1})
        rows = report['retention']
        self.assertEqual(rows['host:codex'], {'sessions': 2, 'with_changes': 2, 'with_retained_outcome': 1,
                                              'with_unconfirmed_retain': 1, 'changed_with_retained_outcome': 1,
                                              'retained_share_of_changed': 0.5})
        bound = next(v for k, v in rows.items() if k.startswith('project:') and k.endswith('project'))
        self.assertEqual((bound['sessions'], bound['retained_share_of_changed']), (1, 1.0))
        self.assertEqual(rows['project:' + field_use.UNBOUND]['retained_share_of_changed'], 0.0)
        fixes = report['corrections']
        self.assertEqual(fixes['rule'], 'ekk.correction-rule/1')
        self.assertEqual(fixes['by_host']['codex'], {'owner_messages': 4, 'owner_messages_after_report': 2,
                                                     'corrections': 1, 'repeated_corrections': 1})
        week = [r for r in fixes['by_host_project_week'] if r['project'] != field_use.UNBOUND]
        self.assertEqual([(r['week'], r['corrections'], r['owner_messages']) for r in week], [('2026-W39', 1, 3)])
        # The title of one delivered item appears in a final report; the other item left no trace.
        use = report['entry_use']['codex']
        self.assertEqual((use['delivered'], use['used'], use['by_signal']['report_title']), (2, 1, 1))
        # The queued retain never shows its record: it is counted as unresolved, not as zero writes.
        self.assertEqual(report['reuse'], {'created_ids': 0, 'resurfaced_in_later_sessions': 0,
                                           'writes_without_record_id': 1})
        store = next(v for k, v in field_use.tasks_by_project(self.out).items() if k.endswith('project'))
        self.assertEqual((store['pairs'], store['writes_without_record_id']), (set(), 1))
        for name in ('report.json', 'report.md', 'messages.jsonl', 'sessions.jsonl'):
            self.assertNotIn('\u0433\u043e\u0432\u043e\u0440\u0438\u043b', (self.out / name).read_text(), name)

    def test_host_event_outcomes_merge_into_retention(self):
        logs = self.thread_logs()
        self.run_tool(codex=logs)
        pairs = self.root / 'host-events.json'
        pairs.write_text(json.dumps([{'host': 'codex', 'session': 'thread-2'}, {'host': 'claude', 'session': 'thread-1'}]))
        report = self.run_tool('--host-events', str(pairs), codex=logs, command='report')
        row = report['retention']['host:codex']
        self.assertEqual((report['host_event_pairs_matched'], report['host_event_pairs_unmatched']), (1, 1))
        self.assertEqual((row['with_automatic_outcome'], row['changed_with_any_outcome'], row['any_share_of_changed']), (1, 2, 1.0))
        self.assertEqual(row['retained_share_of_changed'], 0.5)

    def test_a_run_in_an_older_episode_format_is_not_counted_as_unresolved_writes(self):
        self.run_tool()
        run = json.loads((self.out / 'run.json').read_text())
        self.assertEqual(field_use.EPISODE_FORMAT, run['episode_format'])
        (self.out / 'run.json').write_text(json.dumps({k: v for k, v in run.items() if k != 'episode_format'}))
        report = self.run_tool(command='report')
        self.assertIsNone(report['reuse']['writes_without_record_id'])
        self.assertEqual((0, 0), (report['reuse']['created_ids'], report['reuse']['resurfaced_in_later_sessions']))
        self.assertTrue(any('older episode format' in limit for limit in report['limits']))
        with self.assertRaises(SystemExit):
            field_use.tasks_by_project(self.out)
        (self.out / 'run.json').write_text(json.dumps(run))
        self.assertIsNotNone(self.run_tool(command='report')['reuse']['writes_without_record_id'])

    def test_host_event_pairs_carry_the_runtime_host_labels(self):
        from ekk.adapters import observe_hook
        from ekk.application.experience import compose_outcome
        with mock.patch.dict(os.environ, {'CLAUDECODE': '1'}):
            host = observe_hook.host_of({})[0]
        experience = compose_outcome([{'at': 1790000000, 'text': 'Raised the payout minimum.'}], [], host=host, session='aaaa')[2]
        sessions = [field_use.new_session('claude', 'aaaa'), field_use.new_session('codex', 'thread-1'),
                    field_use.new_session('claude', 'twin'), field_use.new_session('codex', 'twin'),
                    field_use.new_session('claude', 'bbbb')]
        pairs = [{'host': experience['host'], 'session': experience['session']},
                 {'host': 'claude-code', 'session': 'aaaa'},  # the same pair again
                 {'host': 'unknown', 'session': 'thread-1'},  # a hook that could not name its host
                 {'host': 'unknown', 'session': 'twin'},      # ambiguous without a host
                 {'host': 'codex', 'session': 'gone'}]
        self.assertEqual(field_use.merge_host_events(sessions, pairs), {'matched': 2, 'unmatched': 2})
        self.assertEqual([s['automatic_outcome'] for s in sessions], [True, True, False, False, False])

    def test_measurement_children_do_not_observe(self):
        from ekk.adapters import observe_hook
        seen = {}

        def run(command, **options):
            seen.update(options['env'])
            return subprocess.CompletedProcess(command, 0, '{}', '')
        with mock.patch.dict(os.environ, {'EKK_OBSERVE': '1', 'EKK_CONFIG_HOME': str(self.root / 'config')}), \
                mock.patch.object(subprocess, 'run', run):
            field_use.run_cli(sys.executable, ['enter', '--cwd', '.', '--task', 'x', '--brief'], self.root / 'packs')
            self.assertFalse(observe_hook.switched_off())
            self.assertEqual(os.environ['EKK_OBSERVE'], '1')  # only the child is switched off
            # The runtime's own switch: with it, entry writes no delivery, use mark or task observation.
            with mock.patch.dict(os.environ, seen, clear=True):
                self.assertTrue(observe_hook.switched_off())
        self.assertEqual((seen['EKK_OBSERVE'], seen['EKK_PACK_DIRECTORY']), ('0', str(self.root / 'packs')))

    def test_title_only_entry_items_are_delivered_with_unknown_size(self):
        brief = json.dumps({'schema': 'ekk.context-brief/0.3', 'required_reading': [], 'items': [
            {'title': 'Payout minimum', 'kind': 'outcome', 'summary': 'Raised to 3000.', 'why': 'matches: payout',
             'ref': {'realm': 'urn:uuid:' + REALM, 'id': RECORD}},
            {'title': 'Working agreement', 'kind': 'preference', 'why': 'pinned', 'id': OTHER},
            {'title': 'Empty summary', 'kind': 'outcome', 'summary': '', 'ref': {'id': SOURCE}}]})
        items = field_use.parse_output('enter', brief)['items']
        self.assertEqual([(i['id'], i['content_chars']) for i in items], [(RECORD, 15), (OTHER, None), (SOURCE, 0)])
        day = self.root / 'pinned/sessions/2026/09/24'
        day.mkdir(parents=True)
        (day / 'rollout-p.jsonl').write_text('\n'.join([
            codex_line('session_meta', {'cwd': str(self.project), 'thread_source': 'user'}),
            command("ekk enter --cwd . --task 'payout' --brief", brief, '2026-09-24T10:01:00Z'),
            command('ekk fetch --cwd . --id ' + OTHER, '{}', '2026-09-24T10:02:00Z')]) + '\n')
        report = self.run_tool(codex='pinned/sessions/*/*/*/*.jsonl')
        use = report['entry_use']['codex']
        self.assertEqual((use['delivered'], use['used'], use['by_signal']['fetch']), (3, 1, 1))
        enter = next(e for e in field_use.read_jsonl(self.out / 'episodes.jsonl') if e['op'] == 'enter')
        self.assertEqual(enter['used'], {OTHER: 'fetch'})
        self.assertEqual(report['empty_content_share'], 0.5)  # the title-only item is not an empty item

    def test_created_records_come_from_receipts_and_queue_keys(self):
        reference = {'realm': 'urn:uuid:' + REALM, 'id': RECORD}
        waited = json.dumps({'state': 'published', 'revision': 'r1', 'result_reference': {**reference, 'id': OTHER},
                             'source_references': [{**reference, 'id': SOURCE}],
                             'retention': {'state': 'read_back_and_discoverable', 'query': OTHER}}, indent=2)
        facts = field_use.parse_output('retain', waited, 0)
        self.assertEqual((facts['created_ids'], facts['queue_keys']), ([OTHER, SOURCE], []))
        self.assertIn(REALM, facts['ids'])  # seen in the output, but not a created record
        status = json.dumps({'schema': 'ekk.outbox/0.1', 'realm': REALM, 'operations': [
            {'key': 'retain-abc', 'state': 'read_back_and_discoverable', 'error': None,
             'receipt': {'result_reference': reference, 'retention': {'state': 'read_back_and_discoverable'}}},
            {'key': 'retain-else', 'state': 'local_pending', 'receipt': None, 'error': None}]})
        facts = field_use.parse_output('queue.status', status, 0)
        self.assertEqual((facts['created_ids'], facts['published_keys']), ([], {'retain-abc': [RECORD]}))
        self.assertEqual(field_use.parse_output('retain', QUEUED, 0)['queue_keys'], ['retain-abc'])
        cut = waited[:waited.index('"source_references"')]  # receipt cut by `head`
        self.assertEqual(field_use.parse_output('retain', cut, 0)['created_ids'], [OTHER])
        self.assertNotIn('created_ids', field_use.parse_output('fetch', waited, 0))

        def episode(op, session, stamp, output):
            return {'op': op, 'session': session, 'ts': stamp, 'help': False, **field_use.parse_output(op, output, 0)}
        lost = QUEUED.replace('retain-abc', 'retain-lost')
        episodes = [episode('retain', 'one', '1', QUEUED), episode('capture', 'one', '2', lost),
                    episode('queue.status', 'two', '3', status), episode('retain', 'three', '4', waited),
                    episode('retain', 'three', '5', ''),  # receipt redirected: not a confirmed write
                    episode('work.update', 'three', '6', json.dumps({'id': SOURCE}))]
        writes, unresolved = field_use.created_records(episodes)
        self.assertEqual(writes, [('one', '1', [RECORD]), ('three', '4', [OTHER, SOURCE])])
        self.assertEqual(unresolved, 1)

    def fake_app(self, calls):
        def context(scopes, *, task, budget, focus):
            calls.append((app.task_terms, task))
            return {'records': [{'id': RECORD, 'selection': 'ranked'}, {'id': OTHER, 'mandatory': True}]}
        app = types.SimpleNamespace(task_terms=None, context=context, _validate=lambda snapshot: ({},),
                                    store=types.SimpleNamespace(snapshot=dict))
        return app

    def test_pipeline_row_measures_the_application_as_the_runtime_builds_it(self):
        tasks = sorted(f'task number{n} about subject{n}' for n in range(40))
        args = argparse.Namespace(pipeline=4, k=8)
        route, calls = {'scopes': ['personal']}, []
        app = self.fake_app(calls)
        row = field_use.pipeline(app, route, tasks, args, [(tasks[0], RECORD)])
        self.assertIsNone(app.task_terms)
        self.assertEqual((row['tasks'], row['query_weights_applied'], row['recall@8_per_target']), (4, False, 1))
        sample = [task for _, task in calls]
        self.assertEqual(sample, field_use.sampled(tasks, 4))
        # The weighted variant is its own row on a fresh application, with weights fitted outside the sample.
        fresh, loaded = self.fake_app(calls), []
        with mock.patch.object(field_use, 'load_store', lambda cwd: loaded.append(cwd) or (fresh, route, {}, {})):
            weighted = field_use.weighted_pipeline('/project', tasks, args, [(tasks[0], RECORD)])
            self.assertEqual((weighted['query_weights_applied'], weighted['weights_fitted_on_tasks']), (True, 36))
            self.assertEqual(loaded, ['/project'])
            self.assertIsNone(app.task_terms)
            self.assertLess(fresh.task_terms.weight('task'), 1.0)
            self.assertEqual(fresh.task_terms.weight(field_use.sampled(tasks, 4)[1].split()[1]), 1.0)  # unseen in the fit
            skipped = field_use.weighted_pipeline('/project', tasks[:30], args)
            self.assertEqual((skipped['query_weights_applied'], skipped['weights_fitted_on_tasks'], 'tasks' in skipped),
                             (False, 26, False))
            self.assertEqual(loaded, ['/project'])  # nothing was run for the unmeasurable condition

    def test_baseline_needs_a_closed_period_and_the_same_rule_content(self):
        self.assertEqual((field_use.observation.CORRECTION_RULE, field_use.COLLECTOR_RULE, field_use.rule_digest()),
                         ('ekk.correction-rule/1', 'ekk.field-use-collector/1', RULE_1_DIGEST),
                         'the correction rule content changed: bump its version and pin the new digest')
        today = dt.datetime.now(dt.timezone.utc).date()
        logs = self.thread_logs()
        self.run_tool('--since', '2026-09-01', codex=logs)  # no --until: the run ends at collection
        for until in (today.isoformat(), (today + dt.timedelta(days=400)).isoformat()):
            with self.assertRaises(SystemExit):
                self.run_tool('--since', '2026-09-22', '--until', until, command='baseline')
        self.run_tool('--since', '2026-09-01', '--until', today.isoformat(), codex=logs)
        with self.assertRaises(SystemExit):
            self.run_tool('--since', '2026-09-22', '--until', today.isoformat(), command='baseline')  # open day
        with self.assertRaises(SystemExit):
            self.run_tool('--since', '2026-09-23', '--until', '2026-09-22', command='baseline')
        run = json.loads((self.out / 'run.json').read_text())
        self.assertEqual(run['correction_rule_digest'], RULE_1_DIGEST)
        # The same rule name with other content: the baseline refuses, the report says so.
        (self.out / 'run.json').write_text(json.dumps({**run, 'correction_rule_digest': 'sha256:other'}))
        with self.assertRaises(SystemExit):
            self.run_tool('--since', '2026-09-22', '--until', '2026-09-22', command='baseline')
        report = self.run_tool(codex=logs, command='report')
        self.assertFalse(report['corrections']['rule_matches_code'])
        self.assertTrue(any('Collect again' in limit for limit in report['limits']))
        self.assertFalse((self.out / 'corrections-baseline.json').exists())
        (self.out / 'run.json').write_text(json.dumps(run))
        self.assertTrue(self.run_tool(codex=logs, command='report')['corrections']['rule_matches_code'])
        self.run_tool('--since', '2026-09-22', '--until', '2026-09-22', command='baseline')
        frozen = json.loads((self.out / 'corrections-baseline.json').read_text())
        self.assertEqual((frozen['rule_digest'], frozen['collected_at']), (RULE_1_DIGEST, run['created_at']))

    def test_baseline_freezes_correction_counts_for_a_period(self):
        self.run_tool('--since', '2026-09-01', '--until', '2026-10-02', codex=self.thread_logs())
        with self.assertRaises(SystemExit):
            self.run_tool('--since', '2026-08-01', '--until', '2026-09-30', command='baseline')  # not covered
        self.run_tool('--since', '2026-09-22', '--until', '2026-09-22', command='baseline')
        frozen = json.loads((self.out / 'corrections-baseline.json').read_text())
        self.assertEqual((frozen['schema'], frozen['rule']), ('ekk.field-use-corrections-baseline/0.1', 'ekk.correction-rule/1'))
        self.assertEqual((frozen['since'], frozen['until']), ('2026-09-22', '2026-09-22'))
        self.assertEqual(frozen['total'], {'owner_messages': 4, 'owner_messages_after_report': 2,
                                           'corrections': 1, 'repeated_corrections': 1})
        self.assertNotIn('\u0433\u043e\u0432\u043e\u0440\u0438\u043b', (self.out / 'corrections-baseline.json').read_text())
        self.assertEqual(oct((self.out / 'corrections-baseline.json').stat().st_mode & 0o777), '0o600')
        with self.assertRaises(SystemExit):
            self.run_tool('--since', '2026-09-22', '--until', '2026-09-22', command='baseline')  # frozen
        outside = field_use.corrections(field_use.read_jsonl(self.out / 'messages.jsonl'), '2026-09-23', '2026-09-30')
        self.assertEqual(outside['total']['owner_messages'], 0)

    def test_claude_replays_changes_corrections_and_entry_use(self):
        home = self.root / 'claude/proj'
        (home / 'aaaa/subagents').mkdir(parents=True)
        cwd = str(self.project)
        entry = json.dumps({'work_view': {'visible_results': [
            {'title': 'Payout minimum raised to 3000', 'reference': {'id': RECORD}},
            {'title': 'Referral cap decision of August', 'reference': {'id': OTHER}}]}})
        original = [
            claude('user', 'u1', '2026-09-21T10:00:00.000Z', "don't touch the tests, raise the payout minimum", cwd=cwd),
            claude('assistant', 'a1', '2026-09-21T10:00:10.000Z', tool('t1', 'Bash', command='ekk enter --cwd . --task payout'), cwd=cwd),
            claude('user', 'r1', '2026-09-21T10:00:20.000Z', result('t1', entry), cwd=cwd, toolUseResult='x'),
            claude('assistant', 'a2', '2026-09-21T10:01:00.000Z', tool('t2', 'Edit', file_path='/p/payout.py'), cwd=cwd),
            claude('user', 'r2', '2026-09-21T10:01:10.000Z', result('t2'), cwd=cwd, toolUseResult='x'),
            claude('assistant', 'a3', '2026-09-21T10:01:20.000Z', tool('t3', 'Write', file_path='/p/locked.py'), cwd=cwd),
            claude('user', 'r3', '2026-09-21T10:01:30.000Z', result('t3', 'denied', True), cwd=cwd, toolUseResult='x'),
            claude('assistant', 'a4', '2026-09-21T10:02:00.000Z',
                   tool('t4', 'Bash', command='git add -A && git commit -m "raise minimum"'), cwd=cwd),
            claude('user', 'r4', '2026-09-21T10:02:10.000Z', result('t4'), cwd=cwd, toolUseResult='x'),
            claude('assistant', 'a5', '2026-09-21T10:03:00.000Z',
                   [{'type': 'text', 'text': 'Done; see record 11111111 for the earlier decision.'}], cwd=cwd, stop='end_turn'),
            claude('user', 'u2', '2026-09-21T10:05:00.000Z', 'No, revert the rename', cwd=cwd),
            claude('user', 'n1', '2026-09-21T10:05:30.000Z', 'no, wrong', cwd=cwd, origin={'kind': 'task-notification'}),
            claude('user', 'm1', '2026-09-21T10:05:40.000Z', 'no, wrong', cwd=cwd, isMeta=True),
            claude('assistant', 'a6', '2026-09-21T10:06:00.000Z', [{'type': 'text', 'text': 'Reverted.'}], cwd=cwd, stop='end_turn'),
            claude('user', 'u3', '2026-09-21T10:07:00.000Z', 'you renamed it again, I said keep the name', cwd=cwd),
        ]
        (home / 'aaaa.jsonl').write_text('\n'.join(original) + '\n')
        agent = [
            claude('user', 's1', '2026-09-21T10:02:20.000Z', 'no, retain the outcome', cwd=cwd, isSidechain=True),
            claude('assistant', 's2', '2026-09-21T10:02:30.000Z', tool('t9', 'Bash', command='ekk retain --cwd . --stdin'),
                   cwd=cwd, isSidechain=True),
            claude('user', 's3', '2026-09-21T10:02:40.000Z', result('t9', QUEUED), cwd=cwd, isSidechain=True, toolUseResult='x'),
        ]
        (home / 'aaaa/subagents/agent-1.jsonl').write_text('\n'.join(agent) + '\n')
        # A resumed session replays every earlier record under its uuid, then continues.
        resumed = original + [
            claude('assistant', 'b1', '2026-09-23T09:00:00.000Z', tool('t5', 'Edit', file_path='/p/payout.py'), cwd=cwd),
            claude('user', 'b2', '2026-09-23T09:00:10.000Z', result('t5'), cwd=cwd, toolUseResult='x'),
            claude('user', 'b3', '2026-09-23T09:01:00.000Z', 'thanks, ship it', cwd=cwd),
        ]
        (home / 'bbbb.jsonl').write_text('\n'.join(resumed) + '\n')
        report = self.run_tool('--claude', str(self.root / 'claude/proj/*/subagents/*.jsonl'),
                               codex='none/*.jsonl', claude='claude/proj/*.jsonl')
        sessions = self.sessions()
        first, second = sessions['aaaa'], sessions['bbbb']
        self.assertEqual((first['files'], first['subagent'], first['file_changes'], first['commits']), (2, False, 1, 1))
        self.assertEqual((first['retained'], first['retain'], first['ekk_calls']), (True, {'queued': 1}, 2))
        self.assertEqual((first['user_messages'], first['owner_after_report'], first['corrections'], first['repeated_corrections']),
                         (3, 2, 2, 1))
        # Only the records written after the resume belong to the second session.
        self.assertEqual((second['file_changes'], second['commits'], second['ekk_calls'], second['user_messages'],
                          second['corrections'], second['start'][:10]), (1, 0, 0, 1, 0, '2026-09-23'))
        self.assertEqual(report['retention']['host:claude'], {
            'sessions': 2, 'with_changes': 2, 'with_retained_outcome': 1, 'with_unconfirmed_retain': 0,
            'changed_with_retained_outcome': 1, 'retained_share_of_changed': 0.5})
        self.assertEqual(report['corrections']['by_host']['claude'], {
            'owner_messages': 4, 'owner_messages_after_report': 2, 'corrections': 2, 'repeated_corrections': 1})
        use = report['entry_use']['claude']
        self.assertEqual((use['enters'], use['delivered'], use['used'], use['by_signal']['report_id']), (1, 2, 1, 1))
        self.assertEqual(report['enter_calls'], {'total': 1, 'from_subagents': 0})


if __name__ == '__main__':
    unittest.main()
