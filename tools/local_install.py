#!/usr/bin/env python3
"""Build, activate and roll back the local EKK CLI from a committed source.

Releases live side by side under <EKK home>/cli/releases/<date>-<version>-<wheel
sha12>; `cli/current` and the `ekk` launcher point at the active one. A release
is built from `git archive` of one commit, reuses the dependency environment of the
active release (pins unchanged, wheel installed without dependencies) and keeps
the previous launcher and `current` target in its manifest for rollback. Older
release directories are never removed: running processes and the gateway may
still use them. Nothing is downloaded; the build interpreter must already have
setuptools and wheel.

A new release verifies stores with new code and may read history with a new
loader, so its first write would audit every operation and its first historical
reference would load every commit. `warm` does both ahead of time, with the
active release, for every store named in the owner's profiles.

    tools/local_install.py build --build-python PY [--commit HEAD]
    tools/local_install.py activate RELEASE_DIR
    tools/local_install.py warm
    tools/local_install.py rollback
    tools/local_install.py status
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from ekk.adapters.local_profile import config_home, data_home  # noqa: E402

CLI = data_home().expanduser().resolve().parent / 'cli'
LAUNCHER = Path.home() / '.local/bin/ekk'
HANDBOOK_PAGES = ('agent-contract.md',)
LAUNCHER_TEXT = """#!/bin/sh
set -eu
export EKK_PACK_DIRECTORY='{release}/original-packs'
exec '{release}/venv/bin/python' -I -B -m ekk "$@"
"""
# Runs in the active release: the audit that writes otherwise repeat, then the
# record version index. Each half reports for itself.
WARM_SCRIPT = """
import json, sys, time
from ekk.adapters.command_line import service
app = service(sys.argv[1])
result = {}
for name, step in (('audit', lambda: app.store.recover()), ('index', lambda: app._record_versions())):
    started = time.monotonic()
    try:
        value = step()
        result[name] = 'ok'
        if name == 'index':
            result['commits'], result['unloadable_commits'] = len(value.seq), len(value.broken)
    except Exception as exc:
        result[name] = type(exc).__name__ + ': ' + str(exc)
    result[name + '_s'] = round(time.monotonic() - started, 1)
print(json.dumps(result))
"""


def run(*argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, text=True, **kwargs).stdout


def current():
    return (CLI / 'current').resolve()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(args):
    commit = run('git', '-C', str(ROOT), 'rev-parse', args.commit).strip()
    active = current()
    with tempfile.TemporaryDirectory(prefix='ekk-build-') as temp:
        source, dist = Path(temp) / 'src', Path(temp) / 'dist'
        archive = subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=tar', commit],
                                 check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter='data')
        run(args.build_python, '-m', 'pip', 'wheel', '-q', '--no-deps', '--no-build-isolation', '-w', str(dist), '.',
            cwd=source)
        [wheel] = dist.glob('*.whl')
        version = wheel.name.split('-')[1]
        digest = sha256(wheel)
        release = CLI / 'releases' / f"{datetime.now(timezone.utc):%Y%m%d}-{version}-{digest[:12]}"
        release.mkdir(parents=False)
        shutil.copy2(wheel, release / wheel.name)
        shutil.copytree(active / 'venv', release / 'venv', symlinks=True)
        shutil.copytree(active / 'original-packs', release / 'original-packs', symlinks=True)
        shutil.copytree(active / 'handbook', release / 'handbook', symlinks=True)
        # Every handbook page that the commit still owns, plus its release notes.
        for page in sorted((release / 'handbook').glob('*.md')):
            if (source / 'docs' / page.name).is_file():
                shutil.copy2(source / 'docs' / page.name, page)
        for notes in (source / 'docs').glob('release-notes-*.md'):
            shutil.copy2(notes, release / 'handbook' / notes.name)
        for page in HANDBOOK_PAGES:  # pages added after the first installed handbook
            if (source / 'docs' / page).is_file():
                shutil.copy2(source / 'docs' / page, release / 'handbook' / page)
    python = release / 'venv/bin/python'
    run(str(python), '-m', 'pip', 'install', '-q', '--no-deps', '--no-index', '--force-reinstall',
        str(release / wheel.name))
    run(str(python), '-m', 'pip', 'check')
    reported = run(str(python), '-I', '-B', '-m', 'ekk', '--version').strip()
    if version not in reported:
        raise SystemExit(f'built runtime reports {reported!r}, expected {version}')
    pins = (active / 'requirements.lock').read_text().splitlines()[1:]
    (release / 'requirements.lock').write_text('\n'.join([f'./{wheel.name} --hash=sha256:{digest}', *pins]) + '\n')
    (release / 'build.json').write_text(json.dumps({
        'version': version, 'wheel': wheel.name, 'wheel_sha256': digest, 'source_commit': commit,
        'built_from': 'git archive of source_commit', 'build_python': args.build_python,
        'environment': f'venv copied from {active.name}; wheel installed with --no-deps',
        'built_at': datetime.now(timezone.utc).isoformat()}, indent=2) + '\n')
    print(json.dumps({'release': str(release), 'version': version, 'wheel_sha256': digest, 'source_commit': commit}))


def running_cli():
    rows = run('ps', '-axo', 'pid=,command=').splitlines()
    return [row.strip() for row in rows if ' -m ekk' in row and 'ekk_gateway' not in row]


def activate(args):
    release = Path(args.release).resolve()
    built = json.loads((release / 'build.json').read_text())
    if release.parent != (CLI / 'releases').resolve() or sha256(release / built['wheel']) != built['wheel_sha256']:
        raise SystemExit('not a staged release with its recorded wheel')
    busy = running_cli()
    if busy and not args.allow_running:
        raise SystemExit('ekk processes are running; they keep their release, rerun with --allow-running:\n'
                         + '\n'.join(busy))
    previous = current()
    backup = release / 'activation-backup'
    backup.mkdir(exist_ok=True)
    shutil.copy2(LAUNCHER, backup / 'previous-launcher.sh')
    manifest = {**built, 'release': str(release), 'state': 'active',
                'activated_at': datetime.now(timezone.utc).isoformat(),
                'previous_launcher': LAUNCHER.read_text(), 'previous_current': str(previous),
                'rollback': 'tools/local_install.py rollback, or write previous_launcher back to the launcher '
                            'and point cli/current at previous_current.'}
    (release / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    switch(LAUNCHER_TEXT.format(release=release), release)
    print(json.dumps({'active': str(release), 'previous': str(previous), 'version': run('ekk', '--version').strip(),
                      'next': 'tools/local_install.py warm: audit the stores and build their version index now, '
                              'not in the first write and the first historical reference.'}))


def profile_stores():
    """Every store path named by a role profile of this owner, once."""
    import yaml
    paths = []
    for profile in sorted((config_home() / 'profiles').glob('*.yaml')):
        try:
            realms = yaml.safe_load(profile.read_text()).get('realms', {})
            entries = [entry.get('path') for entry in realms.values() if isinstance(entry, dict)]
        except (OSError, AttributeError, yaml.YAMLError) as exc:
            print(json.dumps({'profile': profile.name, 'error': f'{type(exc).__name__}: {exc}'}))
            continue
        for path in entries:
            if isinstance(path, str) and path and Path(path).expanduser() not in paths:
                paths.append(Path(path).expanduser())
    return paths


def warm(args):
    release = current()
    environment = {**os.environ, 'EKK_PACK_DIRECTORY': str(release / 'original-packs')}
    failed = False
    for path in profile_stores():
        done = subprocess.run([str(release / 'venv/bin/python'), '-I', '-B', '-c', WARM_SCRIPT, str(path)],
                              capture_output=True, text=True, env=environment)
        try:
            row = json.loads(done.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            row = {'error': (done.stderr.strip().splitlines() or ['no result'])[-1]}
        failed = failed or 'error' in row or row.get('audit') != 'ok' or row.get('index') != 'ok'
        print(json.dumps({'store': str(path), **row}), flush=True)
    # Every store was attempted; the exit status only says whether all of them passed.
    if failed:
        raise SystemExit(1)


def switch(launcher_text, target):
    temp = LAUNCHER.with_name(f'.ekk.{os.getpid()}')
    temp.write_text(launcher_text)
    temp.chmod(0o755)
    os.replace(temp, LAUNCHER)
    link = CLI / f'.current.{os.getpid()}'
    link.symlink_to(target)
    os.replace(link, CLI / 'current')


def rollback(args):
    manifest = json.loads((current() / 'manifest.json').read_text())
    previous = Path(manifest['previous_current'])
    if not (previous / 'venv/bin/python').exists():
        raise SystemExit(f'previous release is missing: {previous}')
    switch(manifest['previous_launcher'], previous)
    print(json.dumps({'active': str(previous), 'version': run('ekk', '--version').strip()}))


def status(args):
    active = current()
    manifest = json.loads((active / 'manifest.json').read_text()) if (active / 'manifest.json').exists() else {}
    print(json.dumps({'active': str(active), 'version': manifest.get('version'),
                      'source_commit': manifest.get('source_commit'), 'previous': manifest.get('previous_current'),
                      'releases': sorted(p.name for p in (CLI / 'releases').iterdir() if p.is_dir())}, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    b = commands.add_parser('build')
    b.add_argument('--commit', default='HEAD')
    b.add_argument('--build-python', required=True, help='Interpreter with setuptools and wheel installed')
    a = commands.add_parser('activate')
    a.add_argument('release')
    a.add_argument('--allow-running', action='store_true')
    commands.add_parser('rollback')
    commands.add_parser('status')
    commands.add_parser('warm')
    args = parser.parse_args(argv)
    {'build': build, 'activate': activate, 'rollback': rollback, 'status': status, 'warm': warm}[args.command](args)


if __name__ == '__main__':
    main()
