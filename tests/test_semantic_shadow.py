import copy
import unittest

from ekk.application.semantic_shadow import semantic_shadow


def reference(index):
    return {'realm': 'realm:synthetic', 'id': 'candidate:' + str(index),
            'revision': 1, 'digest': 'sha256:' + format(index + 1, '064x')}


def candidates():
    return [
        {'reference': reference(0), 'title': 'Primary candidate',
         'excerpt': 'The task directly matches this material.', 'lexical_score': 3},
        {'reference': reference(1), 'title': 'Background candidate',
         'excerpt': 'Some shared words but different intent.', 'lexical_score': 2},
    ]


def decision(candidate_id, label, probabilities=None):
    probabilities = probabilities or {
        'primary': 0.8 if label == 'primary' else 0.05,
        'supporting': 0.1 if label == 'primary' else 0.05,
        'background': 0.05 if label == 'primary' else 0.1,
        'irrelevant': 0.05 if label == 'primary' else 0.8,
    }
    return {'candidate_id': candidate_id, 'label': label,
            'probabilities': probabilities}


class Advisor:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def advise(self, *, task, candidates):
        self.calls.append((task, copy.deepcopy(candidates)))
        if self.error:
            raise self.error
        return self.response


def valid_response():
    return {'schema': 'ekk.semantic-advice/0.1',
            'model': {'id': 'local/laya-ekk', 'revision': 'sha256:checkpoint'},
            'decisions': [decision('c0', 'primary'), decision('c1', 'irrelevant')]}


class SemanticShadowTests(unittest.TestCase):
    def test_valid_advice_is_visible_but_never_applied(self):
        supplied = candidates()
        before = copy.deepcopy(supplied)
        advisor = Advisor(valid_response())
        result = semantic_shadow('Find the relevant material', supplied, advisor)
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['baseline'], before)
        self.assertEqual(supplied, before)
        self.assertFalse(result['applied'])
        self.assertEqual(result['authority_effect'], 'none')
        self.assertTrue(result['agent_recheck']['required'])
        self.assertEqual([row['reference'] for row in result['decisions']],
                         [row['reference'] for row in before])

    def test_advisor_receives_only_bounded_opaque_summaries(self):
        advisor = Advisor(valid_response())
        semantic_shadow('Find the relevant material', candidates(), advisor)
        sent = advisor.calls[0][1]
        self.assertEqual(set(sent[0]), {'candidate_id', 'title', 'excerpt'})
        self.assertEqual([row['candidate_id'] for row in sent], ['c0', 'c1'])
        self.assertNotIn('realm:synthetic', repr(sent))
        self.assertNotIn('sha256:', repr(sent))
        self.assertNotIn('lexical_score', repr(sent))

    def test_advisor_failure_preserves_baseline(self):
        supplied = candidates()
        result = semantic_shadow('Find the relevant material', supplied,
                                 Advisor(error=RuntimeError('private failure detail')))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['baseline'], supplied)
        self.assertNotIn('private failure detail', repr(result))
        self.assertNotIn('decisions', result)

    def test_unknown_or_duplicate_candidate_is_contained(self):
        for rows in ([decision('c0', 'primary'), decision('c0', 'irrelevant')],
                     [decision('c0', 'primary'), decision('c9', 'irrelevant')]):
            with self.subTest(rows=rows):
                response = valid_response()
                response['decisions'] = rows
                result = semantic_shadow('Find material', candidates(), Advisor(response))
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['baseline'], candidates())

    def test_invalid_probabilities_and_label_are_contained(self):
        invalid = [
            decision('c0', 'primary', {'primary': .9, 'supporting': .9,
                                       'background': 0, 'irrelevant': 0}),
            decision('c0', 'primary', {'primary': .1, 'supporting': .8,
                                       'background': .05, 'irrelevant': .05}),
            {'candidate_id': 'c0', 'label': 'authoritative', 'probabilities': {
                'primary': .25, 'supporting': .25, 'background': .25, 'irrelevant': .25}},
        ]
        for first in invalid:
            with self.subTest(first=first):
                response = valid_response()
                response['decisions'][0] = first
                result = semantic_shadow('Find material', candidates(), Advisor(response))
                self.assertEqual(result['status'], 'unavailable')

    def test_caller_input_is_bounded_before_advisor_call(self):
        advisor = Advisor(valid_response())
        with self.assertRaises(ValueError):
            semantic_shadow('x' * 2001, candidates(), advisor)
        with self.assertRaises(ValueError):
            semantic_shadow('task', candidates() * 17, advisor)
        with self.assertRaises(ValueError):
            semantic_shadow('task', [{**candidates()[0], 'excerpt': 'x' * 2001}], advisor)
        self.assertEqual(advisor.calls, [])


if __name__ == '__main__':
    unittest.main()
