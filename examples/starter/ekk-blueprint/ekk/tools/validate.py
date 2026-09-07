#!/usr/bin/env python3
"""Read-only file-profile validation. This is neither the EKK runtime nor an ACL."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

SCHEMAS = Path(__file__).resolve().parents[1] / 'spec' / 'schemas'
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
KNOWN_KINDS = {'context', 'note', 'source', 'observation', 'claim', 'question',
               'decision', 'policy', 'action', 'outcome'}


class InvalidDocument(ValueError):
    """An unsafe or ambiguous input document."""


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader: UniqueSafeLoader, node: Any, deep: bool = False) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise InvalidDocument('YAML keys must be strings')
        if key in mapping:
            raise InvalidDocument(f'Duplicate YAML key: {key}')
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse_yaml(text: str) -> dict:
    if len(text.encode('utf-8')) > MAX_DOCUMENT_BYTES:
        raise InvalidDocument('Document exceeds the 2 MiB limit')
    for event in yaml.parse(text):
        if isinstance(event, yaml.AliasEvent):
            raise InvalidDocument('The file profile does not support YAML aliases')
    data = yaml.load(text, Loader=UniqueSafeLoader)
    if not isinstance(data, dict):
        raise InvalidDocument('Expected a YAML object')
    return data


def read_text(path: Path) -> str:
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise InvalidDocument(f'Text document is too large: {path.name}')
    return path.read_text(encoding='utf-8')


def parse_record(path: Path) -> dict:
    lines = read_text(path).splitlines()
    if not lines or lines[0] != '---':
        raise InvalidDocument('Missing YAML frontmatter')
    try:
        closing = lines.index('---', 1)
    except ValueError as exc:
        raise InvalidDocument('Unterminated YAML frontmatter') from exc
    return parse_yaml('\n'.join(lines[1:closing]))


def safe_path(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or '..' in rel.parts or '.git' in rel.parts:
        raise InvalidDocument(f'Invalid relative path: {relative}')
    cursor = root
    for component in rel.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise InvalidDocument(f'Symlink in path: {relative}')
    if not cursor.resolve().is_relative_to(root.resolve()):
        raise InvalidDocument(f'Path escapes realm: {relative}')
    return cursor


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def schema_errors(name: str, data: dict) -> list[str]:
    schema = json.loads((SCHEMAS / f'{name}.schema.json').read_text(encoding='utf-8'))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [f'{".".join(map(str, e.path)) or "$"}: {e.message}'
            for e in sorted(validator.iter_errors(data), key=lambda e: str(list(e.path)))]


def validate_realm(root: Path) -> dict:
    root = root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    entries: dict[str, tuple[Path, dict]] = {}
    checked_sources = 0
    checked_receipts = 0
    manifest: dict = {}

    def report() -> dict:
        return {'structural_valid': not errors, 'record_count': len(entries),
                'source_bytes_verified': checked_sources,
                'current_receipt_content_bindings_verified': checked_receipts,
                'errors': errors, 'warnings': warnings,
                'guarantees_not_verified': ['authority', 'confidentiality', 'semantic_truth',
                    'historical_receipt_bytes', 'runtime_recovery', 'productivity']}

    try:
        manifest = parse_yaml(read_text(safe_path(root, '.ekk/realm.yaml')))
        problems = schema_errors('realm', manifest)
        if problems:
            errors.extend(f'realm.yaml: {p}' for p in problems)
            return report()
        # This checks governance syntax, not owner identity or authority.
        parse_yaml(read_text(safe_path(root, '.ekk/governance.yaml')))
        parse_yaml(read_text(safe_path(root, '.ekk/packs.lock.yaml')))
        record_roots = [safe_path(root, p) for p in manifest['storage']['record_roots']]
        source_root = safe_path(root, manifest['storage']['source_root'])
        receipts_root = safe_path(root, manifest['storage']['receipts_root'])
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors.append(f'manifest: {exc}')
        return report()

    visited: set[Path] = set()
    for directory in record_roots:
        if not directory.exists():
            continue
        if not directory.is_dir():
            errors.append(f'Record root is not a directory: {directory.name}')
            continue
        for path in sorted(directory.rglob('*')):
            if path.is_symlink():
                errors.append(f'Symlink in record root: {path.relative_to(root)}')
                continue
            if path.suffix != '.md' or not path.is_file() or path in visited:
                continue
            visited.add(path)
            try:
                safe_path(root, str(path.relative_to(root)))
                data = parse_record(path)
                problems = schema_errors('record', data)
                if problems:
                    errors.extend(f'{path.relative_to(root)}: {p}' for p in problems)
                    continue
                if data['id'] in entries:
                    errors.append(f'Duplicate ID: {data["id"]}')
                    continue
                entries[data['id']] = (path, data)
                if data['kind'] not in KNOWN_KINDS:
                    warnings.append(f'Unknown kind {data["kind"]}: document only, no execution')
            except (OSError, ValueError, yaml.YAMLError) as exc:
                errors.append(f'{path.relative_to(root)}: {exc}')

    contexts = {key for key, (_, data) in entries.items() if data['kind'] == 'context'}
    if manifest['default_context'] not in contexts:
        errors.append('default_context does not resolve to a local context record')
    for record_id, (path, data) in entries.items():
        for scope in data['scope']:
            if scope not in contexts:
                errors.append(f'{record_id}: unknown local scope {scope}')
        for relation in data.get('relations', []):
            external = relation.get('realm', manifest['id']) != manifest['id']
            if external:
                warnings.append(f'{record_id}: external reference was neither verified nor fetched')
            elif relation['target'] not in entries:
                errors.append(f'{record_id}: unresolved target {relation["target"]}')
        if data['kind'] == 'source':
            source = data['source']
            if 'uri' in source:
                warnings.append(f'{record_id}: external source was not fetched')
            for asset in source.get('assets', []):
                try:
                    source_path = safe_path(root, asset['path'])
                    if not source_path.resolve().is_relative_to(source_root.resolve()):
                        raise InvalidDocument('Asset is outside sources-root')
                    if not source_path.is_file():
                        raise InvalidDocument('Missing local asset')
                    if sha256(source_path) != asset['sha256']:
                        raise InvalidDocument('Source SHA-256 mismatch')
                    checked_sources += 1
                except (OSError, ValueError) as exc:
                    errors.append(f'{record_id}: {exc}')

    if receipts_root.exists():
        for path in sorted(receipts_root.rglob('*')):
            if path.is_symlink():
                errors.append('Symlink in receipts-root')
                continue
            if path.suffix != '.json' or not path.is_file():
                continue
            try:
                safe_path(root, str(path.relative_to(root)))
                # Duplicate JSON keys are also invalid.
                def pairs_hook(pairs: list) -> dict:
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise InvalidDocument(f'Duplicate JSON key: {key}')
                        result[key] = value
                    return result
                receipt = json.loads(read_text(path), object_pairs_hook=pairs_hook)
                problems = schema_errors('receipt', receipt)
                if problems:
                    errors.extend(f'{path.name}: {p}' for p in problems)
                    continue
                current = entries.get(receipt['record_id'])
                if current is None:
                    raise InvalidDocument('Receipt refers to an unknown record')
                current_path, current_record = current
                if receipt['record_revision'] < current_record['revision']:
                    warnings.append(f'{path.name}: historical receipt requires verification through the version store')
                elif receipt['record_revision'] > current_record['revision']:
                    raise InvalidDocument('Receipt refers to an absent future revision')
                elif receipt['record_sha256'] != sha256(current_path):
                    raise InvalidDocument('Accepted revision digest does not match its bytes')
                else:
                    checked_receipts += 1
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f'{path.name}: {exc}')
    return report()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('realm', type=Path, help='Demonstration realm root')
    args = parser.parse_args()
    result = validate_realm(args.realm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['structural_valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
