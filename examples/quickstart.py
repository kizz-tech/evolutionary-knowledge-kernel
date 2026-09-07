"""Run a disposable EKK CLI cycle; no existing EKK profile is used."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ekk', default='ekk', help='Installed ekk executable')
    args = parser.parse_args()
    executable = shutil.which(args.ekk)
    if not executable:
        parser.error('Install EKK first, or pass --ekk /path/to/venv/bin/ekk')
    executable = str(Path(executable).absolute())
    with tempfile.TemporaryDirectory(prefix='ekk-quickstart-') as temporary:
        root = Path(temporary).resolve()
        env = {key: value for key, value in os.environ.items() if not key.startswith('EKK_')}
        env.update(EKK_CONFIG_HOME=str(root / 'config'),
                   EKK_DATA_HOME=str(root / 'runtime'),
                   EKK_CACHE_HOME=str(root / 'cache'))
        realm, workspace = root / 'realm', root / 'workspace'
        workspace.mkdir()

        def call(operation, *options, request=None):
            command = [executable, operation, *map(str, options)]
            if request is not None:
                command.append('--stdin')
            result = subprocess.run(command, input=json.dumps(request) if request is not None else None,
                                    text=True, capture_output=True, env=env, cwd=root)
            if result.returncode:
                raise RuntimeError(f'{operation} failed ({result.returncode}): {result.stderr or result.stdout}')
            return json.loads(result.stdout)

        initialized = call('init', '--root', realm, '--title', 'Disposable quickstart',
                           request={'context_id': 'context:quickstart'})
        assert initialized['doctor']['ok']
        scope = 'context:quickstart'
        # JSON is valid YAML; use stdlib only in this example driver.
        profile = {'schema': 'ekk.profile/0.1', 'uid': os.getuid(),
                   'realms': {'demo': {'id': initialized['realm_id'], 'path': str(realm)}}}
        profiles = root / 'config' / 'profiles'
        profiles.mkdir(parents=True)
        (profiles / 'quickstart.yaml').write_text(json.dumps(profile), encoding='utf-8')
        call('init', '--workspace', '--cwd', workspace, '--profile', 'quickstart',
             '--realm', 'demo', '--scope', scope)
        route = ['--cwd', workspace]  # The portable binding selects profile and scope.
        first = call('enter', *route, '--task', 'Summarize a local observation')
        assert not first['blocked'] and not first['manifest']['incomplete']

        source_bytes = b'The demo completed three local checks. Production behavior is unknown.\n'
        source = root / 'observation.txt'
        source.write_bytes(source_bytes)
        capture_options = [*route, '--file', source, '--title', 'Demo observation',
                           '--idempotency-key', 'quickstart-source-1']
        captured = call('capture', *capture_options)
        assert captured['state'] == 'published'
        assert call('capture', *capture_options) == captured
        sources = list((realm / 'sources').rglob('observation.txt'))
        assert len(sources) == 1 and sources[0].read_bytes() == source_bytes
        context = call('context', *route, '--task', 'Record what the demo actually established')
        source_record = next(record for record in context['records'] if record['metadata']['kind'] == 'source')
        base = context['manifest']['snapshots'][0]['revision']
        metadata = {'schema': 'ekk.record/0.1', 'id': 'note:quickstart-result', 'kind': 'note',
                    'title': 'Demo result', 'scope': [scope], 'revision': 1,
                    'created_at': datetime.now(timezone.utc).isoformat(), 'created_by': 'quickstart-example',
                    'basis': [{'id': source_record['id'], 'revision': source_record['metadata']['revision'],
                               'digest': 'sha256:' + source_record['digest']}]}
        record = '---\n' + json.dumps(metadata, indent=2) + '\n---\nThe source reports three local checks. This note does not establish production behavior.\n'
        prepared = call('propose', *route, request={
            'request_id': 'quickstart-propose-1', 'operation': 'propose',
            'expected_snapshot': base,
            'payload': {'changes': {'records/quickstart-result.md': record},
                        'explanation': 'Keep the interpretation separate from the exact source.'}})
        assert prepared['status'] == 'completed'
        assert not (realm / 'records' / 'quickstart-result.md').exists()
        # Common-envelope responses place the encoded proposal in data.
        applied = call('apply', *route, request={
            'request_id': 'quickstart-apply-1', 'operation': 'apply', 'expected_snapshot': base,
            'payload': {'proposal': prepared['data'], 'idempotency_key': 'quickstart-apply-1'}})
        assert applied['status'] == 'completed' and applied['data']['state'] == 'published'
        final = call('enter', *route, '--task', 'Read the captured evidence and resulting note')
        assert not final['blocked'] and not final['manifest']['incomplete']
        assert any(record['id'] == 'note:quickstart-result' for record in final['records'])
        assert call('doctor', *route)['ok']
        print('PASS: isolated init, profile, workspace binding, enter, exact-byte capture, retry, context, propose, apply, enter, doctor')
        print('The disposable realm, local profile, runtime journal and cache are removed on exit.')


if __name__ == '__main__':
    main()
