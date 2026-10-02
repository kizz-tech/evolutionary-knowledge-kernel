import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from ekk.adapters.advisor_process import (
    AdvisorConfigError, AdvisorUnavailable, ProcessAdvisor, RELEVANCE_LABELS, load_advisor)
from ekk.application.semantic_shadow import semantic_shadow
from ekk.application.triage_shadow import RUBRIC, triage_shadow


MODEL = {'id': 'local/fake-advisor', 'revision': 'rev-1'}
FAKE = r'''
import json, os, sys, time
mode, side = sys.argv[1], sys.argv[2]
if mode == 'flood-unread':
    with open(side, 'w') as handle:
        json.dump({'pid': os.getpid()}, handle)
    while True:
        sys.stdout.write('x' * 65536)
request = json.loads(sys.stdin.read())
with open(side, 'w') as handle:
    json.dump({'request': request, 'env': dict(os.environ), 'cwd': os.getcwd(),
               'pid': os.getpid()}, handle)
labels = list(request['labels'])
def row(item, top=0):
    rest = 0.1 / (len(labels) - 1)
    return {'id': item['id'], 'label': labels[top],
            'probabilities': {name: 0.9 if i == top else rest for i, name in enumerate(labels)}}
results = [row(item, index % len(labels)) for index, item in enumerate(request['items'])]
response = {'schema': 'ekk.advisor-response/0.1',
            'model': {'id': 'local/fake-advisor', 'revision': 'rev-1'}, 'results': results}
if mode == 'timeout':
    time.sleep(30)
elif mode == 'exit':
    sys.stderr.write('private failure detail')
    print(json.dumps(response))
    sys.exit(3)
elif mode == 'malformed':
    print('private failure detail {not json')
    sys.exit(0)
elif mode == 'missing':
    response['results'] = results[:-1]
elif mode == 'duplicate':
    response['results'] = results[:-1] + [results[0]]
elif mode == 'bad-sum':
    results[0]['probabilities'] = {name: 0.9 for name in labels}
elif mode == 'bad-argmax':
    results[0]['label'] = labels[1]
elif mode == 'bad-label':
    results[0]['label'] = 'authoritative'
elif mode == 'nan':
    results[0]['probabilities'][labels[0]] = float('nan')
elif mode == 'wrong-model':
    response['model']['revision'] = 'rev-2'
elif mode == 'bad-schema':
    response['schema'] = 'other/0.1'
elif mode == 'list-label':
    results[0]['label'] = [labels[0]]
elif mode == 'dict-id':
    results[0]['id'] = {'id': 'i0'}
elif mode == 'huge-probability':
    results[0]['probabilities'][labels[0]] = 10 ** 400
elif mode == 'text-probability':
    results[0]['probabilities'][labels[0]] = '0.9'
elif mode == 'list-distribution':
    response['distribution'] = ['model']
elif mode == 'list-model':
    response['model'] = [response['model']]
elif mode == 'deep':
    print('[' * 200000 + ']' * 200000)
    sys.exit(0)
elif mode == 'not-utf8':
    sys.stdout.buffer.write(b'\xff\xfe{')
    sys.exit(0)
elif mode == 'flood':
    while True:
        sys.stdout.write('x' * 65536)
elif mode == 'huge-diagnostic':
    response.update(truncated=10 ** 400, identity_verified='yes', diagnostics={
        'load_seconds': 10 ** 400, 'inference_seconds': float('inf'),
        'peak_rss_bytes': [1], 'token_limit': 512})
elif mode == 'verified':
    response['identity_verified'] = True
elif mode == 'extras':
    sys.stderr.write('library banner')
    response.update(distribution='top_label_only', truncated=1,
                    diagnostics={'load_seconds': 1.5, 'note': 'private failure detail'})
print(json.dumps(response))
'''


def reference(index):
    return {'realm': 'realm:synthetic', 'id': 'candidate:' + str(index),
            'revision': 1, 'digest': 'sha256:' + format(index + 1, '064x')}


def candidates(count=3):
    return [{'reference': reference(i), 'title': 'Title ' + str(i),
             'excerpt': 'Excerpt ' + str(i) if i else ''} for i in range(count)]


class ProcessAdvisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ekk-advisor-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.script = self.root / 'fake_advisor.py'
        self.script.write_text(FAKE)
        self.side = self.root / 'seen.json'

    def config(self, mode='ok', name='advisor.json', **extra):
        path = self.root / name
        path.write_text(json.dumps({
            'schema': 'ekk.advisor/0.1',
            'command': [sys.executable, str(self.script), mode, str(self.side)],
            'model': MODEL, **extra}))
        path.chmod(0o600)
        return path

    def advisor(self, mode='ok', **extra):
        return ProcessAdvisor(self.config(mode, **extra))

    def seen(self):
        return json.loads(self.side.read_text())

    def test_relevance_serves_the_semantic_shadow(self):
        supplied = candidates()
        result = semantic_shadow('Find the material', supplied, self.advisor())
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['model'], MODEL)
        self.assertEqual(result['baseline'], supplied)
        self.assertEqual([row['label'] for row in result['decisions']],
                         ['primary', 'supporting', 'background'])
        request = self.seen()['request']
        self.assertEqual(request['schema'], 'ekk.advisor-request/0.1')
        self.assertEqual(request['operation'], 'relevance')
        self.assertEqual(request['task'], 'Find the material')
        self.assertEqual(request['labels'], RELEVANCE_LABELS)
        self.assertEqual(request['items'], [{'id': 'c0', 'text': 'Title 0'},
                                            {'id': 'c1', 'text': 'Title 1\nExcerpt 1'},
                                            {'id': 'c2', 'text': 'Title 2\nExcerpt 2'}])
        self.assertNotIn('realm:synthetic', json.dumps(request))

    def test_triage_serves_the_triage_shadow(self):
        items = [{'id': 'prompt:' + str(i), 'text': 'Text ' + str(i)} for i in range(5)]
        result = triage_shadow(items, self.advisor())
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['model'], MODEL)
        self.assertEqual([row['id'] for row in result['decisions']],
                         [row['id'] for row in items])
        self.assertEqual([row['label'] for row in result['decisions']],
                         ['correction', 'decision', 'finding', 'noise', 'correction'])
        request = self.seen()['request']
        self.assertEqual(request['operation'], 'triage')
        self.assertIsNone(request['task'])
        self.assertEqual(request['labels'], RUBRIC)
        self.assertEqual(request['items'][0], {'id': 'i0', 'text': 'Text 0'})

    def test_child_gets_a_minimal_environment_and_no_shell(self):
        os.environ['EKK_ADVISOR_TEST_SECRET'] = 'secret'
        self.addCleanup(os.environ.pop, 'EKK_ADVISOR_TEST_SECRET', None)
        self.advisor().triage(items=[{'item_id': 'i0', 'text': 'x; echo $HOME'}])
        seen = self.seen()
        self.assertLessEqual(set(seen['env']) - {'__CF_USER_TEXT_ENCODING', 'LC_CTYPE'},
                             {'PATH', 'HOME', 'HF_HUB_OFFLINE', 'TOKENIZERS_PARALLELISM'})
        self.assertEqual(seen['env']['HF_HUB_OFFLINE'], '1')
        self.assertEqual(seen['env']['TOKENIZERS_PARALLELISM'], 'false')
        self.assertEqual(seen['request']['items'][0]['text'], 'x; echo $HOME')

    def test_timeout_is_unavailable_and_stops_the_child(self):
        advisor = self.advisor('timeout', timeout_seconds=0.5)
        started = time.monotonic()
        with self.assertRaises(AdvisorUnavailable):
            advisor.triage(items=[{'item_id': 'i0', 'text': 'x'}])
        self.assertLess(time.monotonic() - started, 15)

    def test_process_failures_are_one_error_without_child_text(self):
        for mode in ('exit', 'malformed', 'missing', 'duplicate', 'bad-sum', 'bad-argmax',
                     'bad-label', 'nan', 'wrong-model', 'bad-schema', 'list-label',
                     'dict-id', 'huge-probability', 'text-probability', 'list-distribution',
                     'list-model', 'deep', 'not-utf8'):
            with self.subTest(mode=mode):
                advisor = self.advisor(mode)
                with self.assertRaises(AdvisorUnavailable) as caught:
                    advisor.advise(task='Find', candidates=[
                        {'candidate_id': 'c0', 'title': 'A', 'excerpt': ''},
                        {'candidate_id': 'c1', 'title': 'B', 'excerpt': ''}])
                self.assertNotIn('private failure detail', str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                shadow = semantic_shadow('Find', candidates(2), advisor)
                self.assertEqual(shadow['status'], 'unavailable')
                self.assertNotIn('private failure detail', repr(shadow))
                self.assertEqual(triage_shadow([{'id': 'a', 'text': 'x'}, {'id': 'b', 'text': 'y'}],
                                               advisor)['status'], 'unavailable')

    def test_output_over_the_bound_stops_the_child_while_reading(self):
        # 'flood-unread' never reads its input: a request larger than a pipe
        # buffer must not block the exchange either.
        for mode, text in (('flood', 'x'), ('flood-unread', 'x' * 300000)):
            with self.subTest(mode=mode):
                advisor = self.advisor(mode, timeout_seconds=60)
                started = time.monotonic()
                with self.assertRaises(AdvisorUnavailable) as caught:
                    advisor.triage(items=[{'item_id': 'i0', 'text': text}])
                self.assertEqual(str(caught.exception), 'Advisor output is too large')
                self.assertLess(time.monotonic() - started, 30)
                with self.assertRaises(ProcessLookupError):
                    os.kill(self.seen()['pid'], 0)

    def test_unusable_optional_values_are_dropped_not_raised(self):
        advice = self.advisor('huge-diagnostic').triage(items=[{'item_id': 'i0', 'text': 'x'}])
        self.assertEqual(set(advice['diagnostics']), {'seconds', 'token_limit'})
        self.assertIs(advice['identity_verified'], False)

    def test_identity_verification_flag_reaches_the_shadow(self):
        items = [{'id': 'a', 'text': 'x'}]
        for mode, expected in (('ok', False), ('verified', True)):
            with self.subTest(mode=mode):
                advisor = self.advisor(mode)
                self.assertIs(advisor.triage(items=[{'item_id': 'i0', 'text': 'x'}])
                              ['identity_verified'], expected)
                self.assertIs(advisor.advise(task='Find', candidates=[
                    {'candidate_id': 'c0', 'title': 'A', 'excerpt': ''}])
                    ['identity_verified'], expected)
                self.assertIs(triage_shadow(items, advisor)['identity_verified'], expected)

    def test_missing_program_is_unavailable(self):
        path = self.config()
        value = json.loads(path.read_text())
        value['command'][0] = str(self.root / 'no-such-interpreter')
        path.write_text(json.dumps(value))
        with self.assertRaises(AdvisorUnavailable):
            ProcessAdvisor(path).triage(items=[{'item_id': 'i0', 'text': 'x'}])

    def test_optional_response_fields_pass_only_as_checked_values(self):
        advice = self.advisor('extras').triage(items=[{'item_id': 'i0', 'text': 'x'}])
        self.assertEqual(advice['distribution'], 'top_label_only')
        self.assertEqual(advice['diagnostics']['truncated'], 1)
        self.assertEqual(advice['diagnostics']['load_seconds'], 1.5)
        self.assertNotIn('private failure detail', repr(advice))
        self.assertNotIn('library banner', repr(advice))
        shadow = triage_shadow([{'id': 'a', 'text': 'x'}], self.advisor('extras'))
        self.assertEqual(shadow['distribution'], 'top_label_only')

    def test_request_larger_than_max_batch_is_refused_before_the_process(self):
        advisor = self.advisor(max_batch=2)
        with self.assertRaises(ValueError):
            advisor.triage(items=[{'item_id': 'i' + str(i), 'text': 'x'} for i in range(3)])
        self.assertFalse(self.side.exists())

    def test_unsafe_config_is_refused(self):
        real = self.config()
        link = self.root / 'link.json'
        link.symlink_to(real)
        with self.assertRaises(AdvisorConfigError):
            ProcessAdvisor(link)
        with self.assertRaises(AdvisorConfigError):
            load_advisor(link)
        for mode in (0o666, 0o620, 0o602):
            with self.subTest(mode=oct(mode)):
                real.chmod(mode)
                with self.assertRaises(AdvisorConfigError):
                    ProcessAdvisor(real)
        real.chmod(0o644)
        self.assertEqual(ProcessAdvisor(real).model, MODEL)
        with self.assertRaises(AdvisorConfigError):
            ProcessAdvisor(self.root)

    def test_invalid_config_is_refused(self):
        good = json.loads(self.config().read_text())
        invalid = [
            {**good, 'schema': 'ekk.advisor/9'},
            {**good, 'command': 'python script'},
            {**good, 'command': [sys.executable]},
            {**good, 'command': ['python', str(self.script)]},
            {**good, 'command': [sys.executable, 'script.py']},
            {**good, 'model': {'id': 'x'}},
            {**good, 'timeout_seconds': 0},
            {**good, 'max_batch': 0},
            {**good, 'shell': True},
        ]
        path = self.root / 'bad.json'
        for value in invalid:
            with self.subTest(value=value):
                path.write_text(json.dumps(value))
                path.chmod(0o600)
                with self.assertRaises(AdvisorConfigError):
                    ProcessAdvisor(path)
        path.write_text('{not json')
        with self.assertRaises(AdvisorConfigError):
            ProcessAdvisor(path)

    def test_load_advisor_returns_none_without_config(self):
        self.assertIsNone(load_advisor(self.root / 'absent.json'))
        self.assertIsNone(load_advisor())
        self.assertEqual(load_advisor(self.config()).model, MODEL)

    def test_default_config_lives_in_the_config_home(self):
        home = self.root / 'config-home'
        home.mkdir()
        previous = os.environ.get('EKK_CONFIG_HOME')
        os.environ['EKK_CONFIG_HOME'] = str(home)
        try:
            self.assertIsNone(load_advisor())
            self.config(name='config-home/advisor.json')
            self.assertEqual(load_advisor().model, MODEL)
        finally:
            if previous is None:
                os.environ.pop('EKK_CONFIG_HOME', None)
            else:
                os.environ['EKK_CONFIG_HOME'] = previous


class GlinerIdentityTests(unittest.TestCase):
    """The model script's identity check; it needs neither torch nor weights."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / 'tools' / 'advisors' / 'gliner_decide.py'
        spec = importlib.util.spec_from_file_location('gliner_decide_under_test', path)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ekk-advisor-weights-')
        self.addCleanup(self.temp.cleanup)
        self.weights = Path(self.temp.name)
        stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')
        self.addCleanup(lambda: (sys.stderr.close(), setattr(sys, 'stderr', stderr)))

    def verify(self, provenance=None, **options):
        if provenance is not None:
            (self.weights / 'download-provenance.json').write_text(
                provenance if isinstance(provenance, str) else json.dumps(provenance))
        return self.script.verify_identity(self.weights, 'org/model', 'rev-1', **options)

    def test_matching_provenance_verifies(self):
        self.assertIs(self.verify({'repo': 'org/model', 'revision': 'rev-1'}), True)
        self.assertIs(self.verify({'repo': 'org/model', 'revision': 'rev-1'},
                                  allow_unverified=True), True)

    def test_different_repository_or_revision_always_fails(self):
        for provenance in ({'repo': 'org/other', 'revision': 'rev-1'},
                           {'repo': 'org/model', 'revision': 'rev-2'},
                           {'repo': 'org/other'}, {'revision': 'rev-2'}):
            for allow in (False, True):
                with self.subTest(provenance=provenance, allow=allow):
                    with self.assertRaises(SystemExit):
                        self.verify(provenance, allow_unverified=allow)

    def test_missing_or_unusable_provenance_needs_the_explicit_flag(self):
        cases = (None, '{not json', '[]', '"text"', '[' * 100000, {},
                 {'revision': 'rev-1'}, {'repo': 'org/model'},
                 {'repo': 'org/model', 'revision': None},
                 {'repo': ['org/model'], 'revision': 'rev-1'})
        for provenance in cases:
            with self.subTest(provenance=str(provenance)[:40]):
                with self.assertRaises(SystemExit):
                    self.verify(provenance)
                self.assertIs(self.verify(provenance, allow_unverified=True), False)

    def test_unreadable_provenance_needs_the_explicit_flag(self):
        (self.weights / 'download-provenance.json').mkdir()
        with self.assertRaises(SystemExit):
            self.verify()
        self.assertIs(self.verify(allow_unverified=True), False)


if __name__ == '__main__':
    unittest.main()
