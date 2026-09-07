"""Inert method contracts and applicability. No instruction here can execute code."""
from copy import deepcopy
import hashlib
import json
from . import validate_reference, validate_identifier, ValidationError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def validate_method(value):
    if not isinstance(value, dict) or value.get('schema') != 'ekk.method/0.1':
        raise ValidationError('method contract required')
    required = {'schema', 'adapter', 'adapter_version', 'artifact_digest', 'applicability',
                'privileges', 'rollback', 'reconsider_when', 'limitations'}
    if set(value) != required:
        raise ValidationError('complete bounded method contract required')
    for field in ('adapter', 'adapter_version', 'rollback'):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValidationError('method ' + field + ' required')
    if (not isinstance(value['artifact_digest'], str) or len(value['artifact_digest']) != 64
            or any(c not in '0123456789abcdef' for c in value['artifact_digest'])):
        raise ValidationError('method artifact SHA-256 required')
    applicability = value['applicability']
    if not isinstance(applicability, dict) or set(applicability) != {'task_family', 'environment', 'model'}:
        raise ValidationError('explicit task, environment and model applicability required')
    for values in (*applicability.values(), value['privileges'], value['reconsider_when'], value['limitations']):
        if not isinstance(values, list) or any(not isinstance(x, str) or not x.strip() for x in values):
            raise ValidationError('method conditions must be explicit string lists')
        if len(values) != len(set(values)):
            raise ValidationError('duplicate method condition')
    if any(not values for values in applicability.values()) or not value['reconsider_when'] or not value['limitations']:
        raise ValidationError('applicability, reconsideration and limitations cannot be empty')
    return deepcopy(value)


def applicable(spec, facts):
    validate_method(spec)
    return (isinstance(facts, dict) and all(isinstance(facts.get(field), str)
            and ('*' in allowed or facts[field] in allowed)
            for field, allowed in spec['applicability'].items()))


def method_reference(record):
    return {'id': record['metadata']['id'], 'revision': record['metadata']['revision'],
            'digest': 'sha256:' + record['digest']}


def exact_reference(value):
    validate_reference(value, pinned=True)
    if not isinstance(value, dict) or not value.get('revision') or not value.get('digest'):
        raise ValidationError('method identity requires exact revision and digest')
    return deepcopy(value)
