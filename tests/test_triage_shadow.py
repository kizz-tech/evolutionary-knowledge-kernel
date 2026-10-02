import copy
import unittest

from ekk.application.triage_shadow import LABELS, RUBRIC_VERSION, triage_shadow


def items():
    return [{'id': 'session:1/turn:4', 'text': 'No, we use pnpm here, not npm.'},
            {'id': 'session:1/turn:5', 'text': 'ok, thanks'}]


def decision(item_id, label, probabilities=None):
    probabilities = probabilities or {
        name: 0.85 if name == label else 0.05 for name in LABELS}
    return {'item_id': item_id, 'label': label, 'probabilities': probabilities}


class Advisor:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def triage(self, *, items):
        self.calls.append(copy.deepcopy(items))
        if self.error:
            raise self.error
        return self.response


def valid_response():
    return {'schema': 'ekk.triage-advice/0.1',
            'model': {'id': 'local/advisor', 'revision': 'sha256:checkpoint'},
            'decisions': [decision('i1', 'noise'), decision('i0', 'correction')]}


class TriageShadowTests(unittest.TestCase):
    def test_valid_advice_is_visible_but_never_applied(self):
        supplied = items()
        before = copy.deepcopy(supplied)
        result = triage_shadow(supplied, Advisor(valid_response()))
        self.assertEqual(supplied, before)
        self.assertEqual(result['schema'], 'ekk.triage-shadow/0.1')
        self.assertEqual(result['rubric'], RUBRIC_VERSION)
        self.assertEqual(result['rubric'], 'ekk.triage-rubric/1')
        self.assertEqual(result['mode'], 'shadow')
        self.assertFalse(result['applied'])
        self.assertEqual(result['authority_effect'], 'none')
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['model'], {'id': 'local/advisor', 'revision': 'sha256:checkpoint'})
        self.assertEqual(result['distribution'], 'model')
        self.assertEqual([(row['id'], row['label']) for row in result['decisions']],
                         [('session:1/turn:4', 'correction'), ('session:1/turn:5', 'noise')])
        for row in result['decisions']:
            self.assertEqual(set(row['probabilities']), set(LABELS))
            self.assertAlmostEqual(sum(row['probabilities'].values()), 1.0, delta=0.01)

    def test_labels_are_the_versioned_rubric(self):
        self.assertEqual(LABELS, ('correction', 'decision', 'finding', 'noise'))

    def test_advisor_receives_only_opaque_ids_and_text(self):
        advisor = Advisor(valid_response())
        triage_shadow(items(), advisor)
        self.assertEqual(advisor.calls, [[
            {'item_id': 'i0', 'text': 'No, we use pnpm here, not npm.'},
            {'item_id': 'i1', 'text': 'ok, thanks'}]])
        self.assertNotIn('session:1', repr(advisor.calls))

    def test_advisor_failure_is_contained(self):
        result = triage_shadow(items(), Advisor(error=RuntimeError('private failure detail')))
        self.assertEqual(result['status'], 'unavailable')
        self.assertFalse(result['applied'])
        self.assertEqual(result['authority_effect'], 'none')
        self.assertNotIn('private failure detail', repr(result))
        self.assertNotIn('decisions', result)
        self.assertNotIn('model', result)

    def test_absent_advisor_is_contained(self):
        self.assertEqual(triage_shadow(items(), None)['status'], 'unavailable')

    def test_unknown_duplicate_or_missing_item_is_contained(self):
        for rows in ([decision('i0', 'correction'), decision('i0', 'noise')],
                     [decision('i0', 'correction'), decision('i9', 'noise')],
                     [decision('i0', 'correction')]):
            with self.subTest(rows=rows):
                response = valid_response()
                response['decisions'] = rows
                self.assertEqual(triage_shadow(items(), Advisor(response))['status'],
                                 'unavailable')

    def test_invalid_probabilities_label_model_and_schema_are_contained(self):
        even = {name: .25 for name in LABELS}
        invalid_first = [
            decision('i1', 'noise', {**even, 'noise': .9, 'finding': .9}),
            decision('i1', 'noise', {**even, 'noise': .1, 'finding': .4}),
            decision('i1', 'noise', {'noise': 1.0}),
            decision('i1', 'noise', {**even, 'noise': float('nan')}),
            decision('i1', 'noise', {**even, 'noise': True}),
            {'item_id': 'i1', 'label': 'preference', 'probabilities': even},
            {'item_id': 'i1', 'label': 'noise', 'probabilities': even, 'apply': True},
        ]
        responses = []
        for first in invalid_first:
            response = valid_response()
            response['decisions'][0] = first
            responses.append(response)
        responses.append({**valid_response(), 'schema': 'ekk.semantic-advice/0.1'})
        responses.append({**valid_response(), 'model': {'id': 'local/advisor'}})
        responses.append({**valid_response(), 'distribution': 'guess'})
        responses.append('not an object')
        for response in responses:
            with self.subTest(response=response):
                self.assertEqual(triage_shadow(items(), Advisor(response))['status'],
                                 'unavailable')

    def test_top_label_only_distribution_is_reported(self):
        response = {**valid_response(), 'distribution': 'top_label_only'}
        self.assertEqual(triage_shadow(items(), Advisor(response))['distribution'],
                         'top_label_only')

    def test_identity_verification_is_reported_and_defaults_to_false(self):
        self.assertIs(triage_shadow(items(), Advisor(valid_response()))['identity_verified'],
                      False)
        for value in (True, False):
            response = {**valid_response(), 'identity_verified': value}
            self.assertIs(triage_shadow(items(), Advisor(response))['identity_verified'], value)
        for value in ('true', 1, None):
            response = {**valid_response(), 'identity_verified': value}
            self.assertEqual(triage_shadow(items(), Advisor(response))['status'], 'unavailable')

    def test_caller_input_is_bounded_before_advisor_call(self):
        advisor = Advisor(valid_response())
        invalid = [
            [],
            'text',
            [{'id': 'a' + str(i), 'text': 'x'} for i in range(33)],
            [{'id': 'a', 'text': 'x' * 2001}],
            [{'id': 'a', 'text': ''}],
            [{'id': '', 'text': 'x'}],
            [{'id': 'a', 'text': 'x'}, {'id': 'a', 'text': 'y'}],
            [{'id': 'a', 'text': 'x', 'role': 'owner'}],
            [{'id': 'a'}],
            ['x'],
        ]
        for supplied in invalid:
            with self.subTest(supplied=supplied):
                with self.assertRaises(ValueError):
                    triage_shadow(supplied, advisor)
        self.assertEqual(advisor.calls, [])


if __name__ == '__main__':
    unittest.main()
