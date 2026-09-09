"""Prepare an English source edition from an explicit, hash-pinned local plan.

This tool does not install, publish, build distributions, or modify its inputs.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import tokenize
import tomllib


SCHEMA = 'ekk.release-preparation-plan/1'
CYRILLIC = re.compile(r'[\u0400-\u04ff]')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def relative(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name:
        raise ValueError('Unsafe relative path: ' + name)
    return name


def read(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('Missing or linked input: ' + str(path))
    return path.read_bytes()


def pinned(spec, base, inputs):
    if set(spec) != {'path', 'sha256'}:
        raise ValueError('Expected a pinned path and sha256')
    path = (base / spec['path']).absolute()
    data = read(path)
    if sha(data) != spec['sha256']:
        raise ValueError('Input hash mismatch: ' + str(path))
    inputs[str(path)] = sha(data)
    return data


def snapshot(spec, base, inputs):
    if set(spec) != {'root', 'receipt'}:
        raise ValueError('Expected snapshot root and pinned receipt')
    root = (base / spec['root']).absolute()
    receipt = json.loads(pinned(spec['receipt'], base, inputs))
    if receipt.get('schema') != 'ekk.reference-export/2' or not isinstance(receipt.get('files'), dict):
        raise ValueError('Unsupported snapshot receipt')
    files = {}
    for name, digest in receipt['files'].items():
        data = read(root / relative(name))
        if sha(data) != digest:
            raise ValueError('Snapshot hash mismatch: ' + name)
        files[name] = data
    return root, files


def verify_prior(raw, english, mappings):
    provenance = json.loads(english['translation-manifest.json'])
    if provenance.get('schema') != 'ekk.translation-provenance/0.1':
        raise ValueError('Unsupported prior translation provenance')
    rows = {}
    for row in provenance['files']:
        name = row['original_path']
        if name in rows or name not in raw or row['path'] not in english:
            raise ValueError('Invalid prior translation path: ' + name)
        if sha(raw[name]) != row['original_sha256'] or sha(english[row['path']]) != row['sha256']:
            raise ValueError('Prior translation hash mismatch: ' + name)
        rows[name] = row
    for name, data in raw.items():
        target = mappings.get(name, name)
        if target not in english:
            raise ValueError('Prior English snapshot missing: ' + target)
        if data != english[target] or name != target:
            if name not in rows or rows[name]['path'] != target:
                raise ValueError('Prior translation lacks provenance: ' + name)


def load_exporter(source):
    spec = importlib.util.spec_from_file_location('release_exporter', source / 'src/ekk/reference_export.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(plan_path):
    plan_path = Path(plan_path).absolute()
    plan_bytes = read(plan_path)
    plan = json.loads(plan_bytes)
    required = {'schema', 'version', 'source', 'output', 'prior_raw', 'prior_english',
                'path_mappings', 'extra_files', 'translations', 'replacements',
                'synthetic_assets', 'manifests'}
    if set(plan) != required or plan['schema'] != SCHEMA or not re.fullmatch(r'\d+\.\d+\.\d+', plan['version']):
        raise ValueError('Unsupported preparation plan; see docs/releasing.md')
    base = plan_path.parent
    source = (base / plan['source']).absolute()
    output = (base / plan['output']).absolute()
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('Output must not traverse symlinks')
    inputs = {str(plan_path): sha(plan_bytes)}
    prior_raw_root, prior_raw = snapshot(plan['prior_raw'], base, inputs)
    prior_en_root, prior_en = snapshot(plan['prior_english'], base, inputs)
    protected = (source.resolve(), prior_raw_root.resolve(), prior_en_root.resolve())
    if output.exists() or any(output.resolve().is_relative_to(p) or p.is_relative_to(output.resolve()) for p in protected):
        raise ValueError('Use a new output outside all input trees')
    exporter = load_exporter(source)
    if (source / exporter.EDITION_FILE).exists():
        raise ValueError('Preparation requires original source, not an English edition')
    mappings = plan['path_mappings']
    expected_mappings = {name: name.replace('.ru.md', '.md') for name in exporter.FILES if '.ru.md' in name}
    if mappings != expected_mappings:
        raise ValueError('Plan must explicitly map every reviewed original language path')
    verify_prior(prior_raw, prior_en, mappings)
    extra_files = plan['extra_files']
    if set(extra_files) != set(exporter.EDITION_EXTRAS) - {'translation-manifest.json'}:
        raise ValueError('Plan must name the reviewed English edition extras')
    translations = plan['translations']
    if set(translations) - set(exporter.FILES):
        raise ValueError('Translation is outside the source allowlist')
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.ekk-prepare-', dir=output.parent))
    try:
        raw_root = staging / 'originals'
        raw_receipt = exporter.prepare(source, raw_root)
        originals = {name: read(raw_root / name) for name in raw_receipt['files']}
        candidate = staging / 'candidate'
        candidate.mkdir()
        methods = {}
        files = {}
        for name, original in originals.items():
            target = mappings.get(name, name)
            data = original
            method = 'current_original'
            # The exporter is never rewritten or replaced by an older edition.
            if name != 'src/ekk/reference_export.py' and prior_raw.get(name) == original:
                data = prior_en[target]
                method = 'reused_verified_english'
            if name in translations:
                translation = translations[name]
                if set(translation) != {'original_sha256', 'input'} or translation['original_sha256'] != sha(original):
                    raise ValueError('Translation original hash mismatch: ' + name)
                data = pinned(translation['input'], base, inputs)
                method = 'explicit_translation'
            if name == 'src/ekk/reference_export.py' and data != original:
                raise ValueError('Exporter source must stay unchanged')
            text = data.decode('utf-8')
            if CYRILLIC.search(text) and name.endswith('.py'):
                if any(token.type != tokenize.STRING and CYRILLIC.search(token.string)
                       for token in tokenize.generate_tokens(io.StringIO(text).readline)):
                    raise ValueError('Non-English Python prose needs explicit translation: ' + name)
                escaped = CYRILLIC.sub(lambda match: '\\u' + format(ord(match[0]), '04x'), text)
                try:
                    identical = ast.dump(ast.parse(text)) == ast.dump(ast.parse(escaped))
                except SyntaxError:
                    identical = False
                if not identical:
                    raise ValueError('Non-English Python prose needs explicit translation: ' + name)
                data = escaped.encode()
                method = 'unicode_escape_identical_ast'
            files[target] = data
            methods[name] = [method]
        for name, spec in extra_files.items():
            files[relative(name)] = pinned(spec, base, inputs)
        for replacement in plan['replacements']:
            if set(replacement) != {'path', 'old', 'new', 'count'}:
                raise ValueError('Replacement requires path, old, new and count')
            name = relative(replacement['path'])
            if name == 'src/ekk/reference_export.py':
                raise ValueError('Exporter source must stay unchanged')
            text = files[name].decode('utf-8')
            old, new, count = replacement['old'], replacement['new'], replacement['count']
            if not old or old == new or not isinstance(count, int) or count < 1 or text.count(old) != count:
                raise ValueError('Replacement count mismatch: ' + name)
            files[name] = text.replace(old, new).encode()
            original_name = next((key for key in originals if mappings.get(key, key) == name), None)
            if original_name:
                methods[original_name].append('explicit_literal_replacement')
        # This gate detects the known original-language scripts, not all languages.
        # Human English review remains mandatory.
        for name, data in files.items():
            if CYRILLIC.search(data.decode('utf-8')):
                raise ValueError('Non-English prose needs explicit translation: ' + name)
            target = candidate / relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if 'pyproject.toml' in files:
            metadata = tomllib.loads(files['pyproject.toml'].decode())
            if metadata['project']['version'] != plan['version']:
                raise ValueError('Plan version does not match package metadata')
        repin_synthetic(candidate, plan['synthetic_assets'])
        refresh_manifests(candidate, plan['manifests'])
        rows = []
        for name, original in originals.items():
            target = mappings.get(name, name)
            translated = read(candidate / target)
            if translated != files[target]:
                methods[name].append('explicit_synthetic_asset_or_manifest_refresh')
            if original != translated or name != target:
                rows.append({'original_path': name, 'original_sha256': sha(original),
                             'path': target, 'sha256': sha(translated),
                             'method': '+'.join(methods[name])})
        provenance = {'schema': 'ekk.translation-provenance/0.1', 'language': 'en',
                      'edition': plan['version'], 'original_release': 'preserved_originals',
                      'note': 'Exact original bytes accompany the private preparation receipt. '
                              'Only reviewed synthetic fixtures are re-pinned; no active realm is rewritten.',
                      'files': rows}
        (candidate / 'translation-manifest.json').write_bytes(encoded(provenance))
        edition = {'schema': 'ekk.release-edition/1', 'language': 'en',
                   'path_mappings': mappings, 'extra_files': list(exporter.EDITION_EXTRAS)}
        (candidate / exporter.EDITION_FILE).write_bytes(encoded(edition))
        public_receipt = exporter.prepare(candidate, staging / 'source-export')
        # Catch source or pinned-input changes during preparation, before committing output.
        for name, original in originals.items():
            if read(source / name) != original:
                raise ValueError('Source changed during preparation: ' + name)
        for path, digest in inputs.items():
            if sha(read(path)) != digest:
                raise ValueError('Pinned input changed during preparation: ' + path)
        receipt = {'schema': 'ekk.release-preparation-receipt/1', 'version': plan['version'],
                   'state': 'prepared_for_review', 'published': False,
                   'plan_sha256': sha(plan_bytes), 'inputs': inputs,
                   'source': str(source), 'originals': raw_receipt,
                   'export': public_receipt,
                   'files': [{'original_path': name, 'original_sha256': sha(original),
                              'path': mappings.get(name, name),
                              'sha256': public_receipt['files'][mappings.get(name, name)],
                              'methods': methods[name]} for name, original in originals.items()]}
        (staging / 'plan.json').write_bytes(plan_bytes)
        (staging / 'receipt.json').write_bytes(encoded(receipt))
        shutil.rmtree(candidate)
        os.rename(staging, output)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def repin_synthetic(root, entries):
    if not entries:
        return
    import yaml
    for entry in entries:
        if set(entry) != {'record', 'realm'}:
            raise ValueError('Synthetic asset entry requires record and realm')
        record, realm = relative(entry['record']), relative(entry['realm'])
        if not realm.startswith('examples/starter/ekk-blueprint/') or not record.startswith(realm + '/'):
            raise ValueError('Only explicit synthetic starter assets may be re-pinned')
        path = root / record
        text = read(path).decode()
        metadata = yaml.safe_load(text.split('---', 2)[1])
        if metadata.get('kind') != 'source':
            raise ValueError('Synthetic record must be a source')
        for asset in metadata['source']['assets']:
            digest = sha(read(root / realm / relative(asset['path'])))
            text = text.replace(asset['sha256'], digest)
        path.write_text(text, encoding='utf-8')


def refresh_manifests(root, entries):
    allowed = {'examples/starter/ekk-blueprint/MANIFEST.sha256.json': 'map',
               'archive/runtime-0.4/MANIFEST.sha256.json': 'rows'}
    if entries != allowed:
        raise ValueError('Plan must name both preserved fixture manifests and their formats')
    for name, kind in entries.items():
        path = root / name
        manifest = json.loads(read(path))
        if kind == 'map':
            manifest = {key: sha(read(path.parent / relative(key))) for key in manifest}
        else:
            for row in manifest['files']:
                row['sha256'] = sha(read(path.parent / relative(row['path'])))
        path.write_bytes(encoded(manifest))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.plan)
    except (ValueError, KeyError, OSError, UnicodeError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps({'state': result['state'], 'version': result['version'],
                      'files': len(result['export']['files']), 'published': False}, indent=2))
