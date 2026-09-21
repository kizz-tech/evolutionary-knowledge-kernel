"""Small installed read-only methods for the runnable transfer demonstration.

The methods construct a handoff artifact. They never send it. The independent
fixture evaluator tests completeness and prohibited excerpts. Neither answers
nor fixtures are stored in transferred method packages.
"""
import json
from .method_execution import MethodAdapter
from ekk.model.methods import sha

EXCERPT = b'{"format":"ekk.handoff-method/1","mode":"excerpt"}\n'
REFERENCE = b'{"format":"ekk.handoff-method/1","mode":"reference"}\n'


def handoff(artifact, request):
    if artifact not in (EXCERPT, REFERENCE):
        raise ValueError('unknown installed handoff artifact')
    required = {'question', 'source_id', 'source_text', 'source_disclosure'}
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError('bounded handoff input required')
    if type(request['source_disclosure']) is not bool or any(not isinstance(request[k], str)
            or not request[k] or len(request[k].encode()) > 64000 for k in required - {'source_disclosure'}):
        raise ValueError('bounded source input required')
    result = {'question': request['question'], 'source_id': request['source_id'],
              'source_digest': sha(request['source_text'].encode()), 'delivery': 'prepared_not_sent'}
    if json.loads(artifact)['mode'] == 'excerpt':
        result['excerpt'] = request['source_text']
    return result


def _evaluate(output, case):
    request = case['input']
    return (output.get('question') == request['question']
            and output.get('source_id') == request['source_id']
            and output.get('source_digest') == sha(request['source_text'].encode())
            and output.get('delivery') == 'prepared_not_sent'
            and (request['source_disclosure'] or 'excerpt' not in output))


CASES = {
    'public-training': {'input': {'question': 'What does retry mean?', 'source_id': 'public:retry-spec',
        'source_text': 'Reuse the same request ID after a lost receipt.', 'source_disclosure': True}},
    'public-transfer': {'input': {'question': 'How does a new contributor continue?', 'source_id': 'public:continuation-spec',
        'source_text': 'Read the accepted revision and preserve unresolved questions.', 'source_disclosure': True}},
    'private-change': {'input': {'question': 'Can the recipient verify the source identity?', 'source_id': 'permitted:opaque-reference',
        'source_text': 'SYNTHETIC_PRIVATE_EXCERPT_MUST_NOT_TRANSFER', 'source_disclosure': False}},
}


def registry():
    from .practical_methods import registry as practical
    return {'builtin:handoff': MethodAdapter('builtin:handoff', '1', 'handoff-fixtures/1', (),
             lambda artifact: artifact in (EXCERPT, REFERENCE), handoff, CASES, _evaluate), **practical()}


def spec(artifact):
    return {'schema':'ekk.method/0.1', 'adapter':'builtin:handoff', 'adapter_version':'1',
            'artifact_digest':sha(artifact), 'applicability':{'task_family':['handoff'],
                'environment':['synthetic-local'], 'model':['*']}, 'privileges':[],
            'rollback':'Quarantine and retire the local admission; retain evidence and prior source bytes.',
            'reconsider_when':['Disclosure conditions or handoff requirements change.'],
            'limitations':['Builds a draft artifact only; never delivers it.',
                'Deterministic mechanism example; no human or model effectiveness measured.']}
