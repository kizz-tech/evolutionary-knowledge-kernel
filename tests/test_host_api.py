"""The declared host facade ekk.host-api/1, the release identity it reads and the installer's rollback guard."""
import ast
import contextlib
import dataclasses
import hashlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import ekk
from ekk import homes, host_api
from ekk.adapters import runtime_release
from ekk.adapters.command_line import AGENT_VIEW_RECORD_BUDGET, capture_once as cli_capture_once, main, service
from ekk.adapters.experience_store import ExperienceStore
from ekk.adapters.host_identity import SCRUB_VARIABLES
from ekk.adapters.operation_diagnostics import _WARNING
from ekk.adapters.retention import retain_once as direct_retain_once
from ekk.application import RealmService
from ekk.application.errors import RequestError
from ekk.model import IdempotencyConflict

REPOSITORY = Path(__file__).resolve().parent.parent
INSTALLER = REPOSITORY / 'tools/local_install.py'
DAY = 86400
# Runs in another process: the installer's own atomic switch, never activate() or rollback().
SWITCH = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('ekk_local_install', sys.argv[1])
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
installer.switch('#!/bin/sh\\n# test launcher\\n', sys.argv[2])
"""


def load_installer():
    spec = importlib.util.spec_from_file_location('ekk_local_install', INSTALLER)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    return installer


class SurfaceTests(unittest.TestCase):
    def test_signatures_are_pinned(self):
        """A change here is a new HOST_API version; the gateway checks it in preflight."""
        self.assertEqual('ekk.host-api/1', host_api.HOST_API)
        self.assertEqual(('HOST_API', 'OPERATIONS', 'Route', 'Release', 'dispatch', 'capture_once', 'retain_once', 'observed',
                          'error_code', 'record_schema', 'active_release', 'loaded_release'), host_api.__all__)
        self.assertEqual(frozenset({'enter', 'context', 'contexts', 'search', 'fetch', 'read-source', 'doctor', 'review', 'assurance'}),
                         host_api.OPERATIONS)
        signatures = {
            'dispatch': "(operation: 'str', request: 'Mapping[str, Any]', *, route: 'Route', caller: 'str | None', "
                        "brief: 'bool' = False, request_id: 'str | None' = None) -> 'dict'",
            'capture_once': "(data: 'bytes', *, route: 'Route', caller: 'str | None', title: 'str', filename: 'str', key: 'str', "
                            "expected_snapshot: 'str | None' = None) -> 'dict'",
            'retain_once': "(artifacts: 'Sequence[Mapping[str, Any]]', *, route: 'Route', caller: 'str | None', title: 'str', "
                           "body: 'str', key: 'str', expected_snapshot: 'str | None' = None, "
                           "repository_evidence: 'Mapping[str, Any] | None' = None) -> 'dict'",
            'observed': "(operation: 'str', callback: 'Callable[[], T]', *, caller: 'str | None', realm_id: 'str | None' = None, "
                        "key: 'str | None' = None) -> 'T'",
            'error_code': "(exc: 'BaseException') -> 'str'",
            'record_schema': "() -> 'dict'",
            'active_release': "() -> 'Release | None'",
            'loaded_release': "() -> 'Release'",
        }
        self.assertEqual(signatures, {name: str(inspect.signature(getattr(host_api, name))) for name in signatures})
        self.assertEqual([('profile', 'str'), ('realm', 'str'), ('realm_id', 'str'), ('scopes', 'tuple[str, ...]')],
                         [(field.name, field.type) for field in dataclasses.fields(host_api.Route)])
        self.assertEqual([('version', 'str | None'), ('wheel_sha256', 'str | None'), ('source_commit', 'str | None'),
                          ('path', 'str | None'), ('record', 'str | None')],
                         [(field.name, field.type) for field in dataclasses.fields(host_api.Release)])
        self.assertTrue(host_api.Route.__dataclass_params__.frozen and host_api.Release.__dataclass_params__.frozen)
        # The adapter's release dicts carry exactly the public fields.
        self.assertEqual([field.name for field in dataclasses.fields(host_api.Release)], list(runtime_release._release()))

    def test_the_facade_imports_no_adapter_at_module_level(self):
        tree = ast.parse((REPOSITORY / 'src/ekk/host_api.py').read_text())
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                top.add('.' * node.level + (node.module or ''))
        self.assertTrue(all(name.split('.')[0] in sys.stdlib_module_names or name in ('ekk.homes', '.homes') for name in top), top)
        lazy = set()
        for function in (node for node in tree.body if isinstance(node, ast.FunctionDef)):
            for node in ast.walk(function):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    lazy |= {node.module + '.' + alias.name for alias in node.names} if node.module == 'adapters' else {node.module}
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    self.fail('Only package-relative imports inside functions: ' + ast.dump(node))
        self.assertLessEqual(lazy, {'adapters.command_line', 'adapters.operation_diagnostics', 'adapters.retention', 'adapters.local_profile',
                                    'adapters.context_display', 'adapters.operation_journal', 'adapters.runtime_release', 'assets'})
        # Importing the facade loads nothing else of EKK.
        loaded = subprocess.run([sys.executable, '-I', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import ekk.host_api; '
                                 'print(sorted(m for m in sys.modules if m.startswith("ekk")))', str(REPOSITORY / 'src')],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(['ekk', 'ekk.host_api'], json.loads(loaded.replace("'", '"')))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'home'; (self.home / '.local/bin').mkdir(parents=True)
        env = patch.dict(os.environ, {'HOME': str(self.home), 'EKK_DATA_HOME': str(self.root / 'runtime'),
                                      'EKK_CONFIG_HOME': str(self.root / 'config'), 'EKK_CACHE_HOME': str(self.root / 'cache')})
        env.start(); self.addCleanup(env.stop)
        for name in SCRUB_VARIABLES: os.environ.pop(name, None)
        self.cli = self.root / 'cli'; (self.cli / 'releases').mkdir(parents=True)

    def release(self, name, *, build=None, manifest=None, raw=None):
        directory = self.cli / 'releases' / name
        (directory / 'venv/bin').mkdir(parents=True)
        (directory / 'venv/bin/python').write_text('#!/bin/sh\nexit 1\n')
        if build is not None: (directory / 'build.json').write_text(json.dumps(build))
        if manifest is not None: (directory / 'manifest.json').write_text(json.dumps(manifest))
        if raw is not None: (directory / 'build.json').write_bytes(raw)
        return directory

    def point(self, target):
        link = self.cli / 'current'
        if link.is_symlink() or link.exists(): link.unlink()
        os.symlink(target, link)

    def test_active_release_follows_a_switch_by_another_process(self):
        first = self.release('20261005-0.10.0-aaaaaaaaaaaa', build={'version': '0.10.0', 'wheel_sha256': 'a' * 64, 'source_commit': '1' * 40})
        second = self.release('20261010-0.10.1-bbbbbbbbbbbb', build={'version': '0.10.1', 'wheel_sha256': 'b' * 64, 'source_commit': '2' * 40})
        self.point(first)
        installer = load_installer()
        self.assertEqual((self.cli, self.cli, self.home / '.local/bin/ekk'), (homes.release_home(), installer.CLI, installer.LAUNCHER))
        self.assertEqual(host_api.Release('0.10.0', 'a' * 64, '1' * 40, str(first), 'build.json'), host_api.active_release())
        for target, digest in ((second, 'b' * 64), (first, 'a' * 64)):
            subprocess.run([sys.executable, '-I', '-c', SWITCH, str(INSTALLER), str(target)], env=dict(os.environ), check=True,
                           capture_output=True)
            self.assertEqual((digest, str(target)), (host_api.active_release().wheel_sha256, host_api.active_release().path))
        self.assertEqual('#!/bin/sh\n# test launcher\n', (self.home / '.local/bin/ekk').read_text())

    def test_active_release_records(self):
        self.assertIsNone(host_api.active_release())
        old = self.release('20260921-0.8.1-cccccccccccc', manifest={'version': '0.8.1', 'wheel_sha256': 'c' * 64,
                                                                     'source_commit': '3' * 40, 'state': 'active'})
        other = self.release('20260922-0.8.2-dddddddddddd', manifest={'version': '0.8.2', 'wheel_sha256': 'd' * 64, 'state': 'active'})
        # Both manifests say active; only the link counts.
        for target, version, digest in ((old, '0.8.1', 'c' * 64), (other, '0.8.2', 'd' * 64)):
            self.point(target)
            self.assertEqual(host_api.Release(version, digest, '3' * 40 if target == old else None, str(target), 'manifest.json'),
                             host_api.active_release())
        valid = {'version': '0.10.0', 'wheel_sha256': 'e' * 64}
        damaged = {
            'malformed': b'{"version": "0.10.0", ',
            'not an object': json.dumps([valid]).encode(),
            'oversized': json.dumps({**valid, 'padding': 'x' * 65536}).encode(),
        }
        for name, raw in damaged.items():
            with self.subTest(name):
                # A damaged build.json is not replaced by the manifest beside it.
                target = self.release(name.replace(' ', '-'), raw=raw, manifest=valid)
                self.point(target)
                self.assertEqual(host_api.Release(None, None, None, str(target), None), host_api.active_release())
        loose = self.release('loose', build={'version': 10, 'wheel_sha256': 'E' * 64, 'source_commit': ['x']})
        self.point(loose)
        self.assertEqual(host_api.Release(None, None, None, str(loose), 'build.json'), host_api.active_release())
        self.point(self.cli / 'releases/gone')
        self.assertEqual(host_api.Release(None, None, None, str(self.cli / 'releases/gone'), None), host_api.active_release())
        self.point('releases/20260921-0.8.1-cccccccccccc')
        self.assertEqual((str(old), 'c' * 64), (host_api.active_release().path, host_api.active_release().wheel_sha256))
        (self.cli / 'current').unlink(); (self.cli / 'current').mkdir()
        self.assertEqual(host_api.Release(None, None, None, str(self.cli / 'current'), None), host_api.active_release())

    def test_loaded_release_digest(self):
        digest = 'f' * 64
        cases = [
            (json.dumps({'url': 'file:///r/ekk.whl', 'archive_info': {'hash': 'sha256=' + digest, 'hashes': {'sha256': digest}}}), digest),
            (json.dumps({'url': 'file:///r/ekk.whl', 'archive_info': {'hash': 'sha256=' + digest}}), digest),
            (json.dumps({'url': 'file:///r', 'dir_info': {'editable': True}}), None),
            (json.dumps({'archive_info': {'hashes': {'sha256': digest.upper()}}}), None),
            (json.dumps({'archive_info': {'hash': 'md5=' + 'f' * 32}}), None),
            ('{"archive_info": ', None), ('[]', None), (None, None),
        ]
        for text, expected in cases:
            self.assertEqual(expected, runtime_release._direct_url_digest(text), text)
        # The editable test install: the version is the imported package's, whatever the metadata says.
        self.assertEqual(host_api.Release(ekk.__version__, None, None, None, None), host_api.loaded_release())

        class Distribution:
            def __init__(self, located): self.located = located
            def locate_file(self, path): return self.located
            def read_text(self, name): return json.dumps({'archive_info': {'hashes': {'sha256': digest}}})
        with patch('importlib.metadata.distribution', return_value=Distribution(Path(ekk.__file__))):
            self.assertEqual(host_api.Release(ekk.__version__, digest, None, None, 'direct_url.json'), host_api.loaded_release())
        with patch('importlib.metadata.distribution', return_value=Distribution(self.root / 'site-packages/ekk/__init__.py')):
            self.assertIsNone(host_api.loaded_release().wheel_sha256)

    # ------------------------------------------------------------ the rollback guard
    def rollback_setup(self, target_build, tag='0.10.0'):
        old = self.release(f'20261005-{tag}-aaaaaaaaaaaa', build=target_build)
        new = self.release(f'20261010-0.10.1-bbbbbbbbbbbb-from-{tag}', build={'version': '0.10.1', 'wheel_sha256': 'b' * 64},
                           manifest={'version': '0.10.1', 'wheel_sha256': 'b' * 64, 'state': 'active',
                                     'previous_current': str(old), 'previous_launcher': '#!/bin/sh\n# previous launcher\n'})
        self.point(new)
        installer = load_installer()
        self.assertEqual((self.cli, self.home / '.local/bin/ekk'), (installer.CLI, installer.LAUNCHER))
        return installer, old, new

    def observer(self):
        now = time.time()
        store = ExperienceStore(self.root / 'runtime/observed')
        try:
            common = dict(workspace='/work', realm='realm:x', host='codex', session='s1')
            store.save_episode('held-old', state='held', title='Diagnosis.', last_at=now - 40 * DAY, **common)
            store.save_episode('published-old', state='published', title='Done.', last_at=now - 31 * DAY, **common)
            store.save_episode('held-new', state='held', title='New.', last_at=now - DAY, **common)
            store.add_event(kind='correction', host='codex', profile=None, session='s1', turn='t', workspace='/work', realm=None,
                            at=now - 91 * DAY, text='Synthetic correction.', state='pending')
        finally:
            store.close()

    def rollback(self, installer, *flags):
        output = io.StringIO()
        with patch.object(installer, 'run', return_value='ekk 0.10.0\n') as run, contextlib.redirect_stdout(output):
            installer.main(['rollback', *flags])
        run.assert_called_once_with('ekk', '--version')
        return json.loads(output.getvalue())

    def test_rollback_to_a_runtime_without_explicit_expiry_names_what_it_would_delete(self):
        installer, old, new = self.rollback_setup({'version': '0.10.0', 'wheel_sha256': 'a' * 64})
        self.observer()
        with patch.object(installer, 'run') as run, self.assertRaises(SystemExit) as refused:
            installer.main(['rollback'])
        run.assert_not_called()
        message = str(refused.exception.code)
        self.assertIn('0.10.0', message)
        self.assertIn(json.dumps({'episodes_older_than_30_days': {'held': 1, 'published': 1}, 'corrections_older_than_90_days': 1}), message)
        self.assertIn('--accept-observer-loss', message)
        self.assertEqual(new, (self.cli / 'current').resolve())
        result = self.rollback(installer, '--accept-observer-loss')
        self.assertEqual((str(old), {'episodes_older_than_30_days': {'held': 1, 'published': 1}, 'corrections_older_than_90_days': 1}),
                         (result['active'], result['observer_loss_accepted']))
        self.assertEqual((old, '#!/bin/sh\n# previous launcher\n'), ((self.cli / 'current').resolve(), (self.home / '.local/bin/ekk').read_text()))

    def test_rollback_to_an_explicit_expiry_runtime_never_reads_the_observer(self):
        for version in ('0.10.1', '0.11.0', '1.0'):
            with self.subTest(version):
                installer, old, _ = self.rollback_setup({'version': version, 'wheel_sha256': 'a' * 64}, tag=version)
                with patch('ekk.adapters.experience_store.open_read_only', side_effect=AssertionError('read')):
                    self.assertEqual({'active': str(old), 'version': 'ekk 0.10.0'}, self.rollback(installer))

    def test_rollback_without_observer_state_passes_and_unknown_versions_are_guarded(self):
        installer, old, new = self.rollback_setup({'version': '0.10.0'})
        self.assertEqual({'active': str(old), 'version': 'ekk 0.10.0'}, self.rollback(installer))
        self.assertFalse((self.root / 'runtime/observed').exists())
        self.assertEqual([(0, 10, 0), (0, 10, 1), None, None, None],
                         [installer.version_key(value) for value in ('0.10.0', '0.10.1', '0.10.1rc1', None, '')])
        self.observer()
        for name, record in (('rc', {'version': '0.10.1rc1'}), ('no-version', {'wheel_sha256': 'a' * 64}), ('no-record', None)):
            with self.subTest(name):
                version, loss = installer.observer_loss(self.release(name, build=record))
                self.assertEqual({'held': 1, 'published': 1}, loss['episodes_older_than_30_days'])
        # State that cannot be read shows nothing safe: it is refused like a loss.
        (self.root / 'runtime/observed').chmod(0o755)
        self.assertEqual(('0.10.0', ['observer_unreadable']), (installer.observer_loss(old)[0], list(installer.observer_loss(old)[1])))
        self.point(new)
        with patch.object(installer, 'run') as run, self.assertRaisesRegex(SystemExit, 'observer_unreadable'):
            installer.main(['rollback'])
        run.assert_not_called()

    def activate(self, installer, release, *flags):
        output = io.StringIO()
        with patch.object(installer, 'running_cli', return_value=[]) as running, \
                patch.object(installer, 'run', return_value='ekk 0.10.0\n') as run, contextlib.redirect_stdout(output):
            installer.main(['activate', str(release), *flags])
        running.assert_called_once_with()
        run.assert_called_once_with('ekk', '--version')
        return json.loads(output.getvalue())

    def test_activate_of_a_runtime_without_explicit_expiry_is_guarded_like_rollback(self):
        wheel = b'synthetic wheel'
        build = {'version': '0.10.0', 'wheel': 'ekk-0.10.0-py3-none-any.whl', 'wheel_sha256': hashlib.sha256(wheel).hexdigest()}
        installer, old, new = self.rollback_setup(build)
        (old / build['wheel']).write_bytes(wheel)
        launcher = self.home / '.local/bin/ekk'
        launcher.write_text('#!/bin/sh\n# active launcher\n')
        self.observer()
        loss = {'episodes_older_than_30_days': {'held': 1, 'published': 1}, 'corrections_older_than_90_days': 1}
        with patch.object(installer, 'running_cli') as running, patch.object(installer, 'run') as run, \
                self.assertRaises(SystemExit) as refused:
            installer.main(['activate', str(old)])
        running.assert_not_called(); run.assert_not_called()
        message = str(refused.exception.code)
        self.assertIn('0.10.0', message); self.assertIn(json.dumps(loss), message)
        self.assertIn(f'tools/local_install.py activate {old} --accept-observer-loss', message)
        # Refused before anything is written.
        self.assertEqual((new, '#!/bin/sh\n# active launcher\n', False, False),
                         ((self.cli / 'current').resolve(), launcher.read_text(), (old / 'activation-backup').exists(), (old / 'manifest.json').exists()))
        result = self.activate(installer, old, '--accept-observer-loss')
        self.assertEqual((str(old), str(new), loss), (result['active'], result['previous'], result['observer_loss_accepted']))
        self.assertEqual((old, installer.LAUNCHER_TEXT.format(release=old)), ((self.cli / 'current').resolve(), launcher.read_text()))
        # A release with explicit expiry activates without reading the observer.
        later = self.release('20261011-0.10.1-cccccccccccc', build={**build, 'version': '0.10.1'})
        (later / build['wheel']).write_bytes(wheel)
        with patch('ekk.adapters.experience_store.open_read_only', side_effect=AssertionError('read')):
            result = self.activate(installer, later)
        self.assertEqual((str(later), False), (result['active'], 'observer_loss_accepted' in result))
        self.assertEqual(later, (self.cli / 'current').resolve())


class FacadeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.data = self.root / 'data'
        env = patch.dict(os.environ, {'EKK_DATA_HOME': str(self.data), 'EKK_CONFIG_HOME': str(self.root / 'config'),
                                      'EKK_CACHE_HOME': str(self.root / 'cache')})
        env.start(); self.addCleanup(env.stop)
        for name in SCRUB_VARIABLES: os.environ.pop(name, None)
        self.config = self.root / 'config'; (self.config / 'profiles').mkdir(parents=True, mode=0o700)
        self.realm = self.root / 'realm'
        app = service(self.realm)
        app.init('Test', realm_id=app.initial_realm_id, context_id='scope')
        self.realm_id = app.initial_realm_id
        other = {'schema': 'ekk.record/0.1', 'id': 'other', 'title': 'Other context', 'kind': 'context', 'context': {'purpose': 'Second'},
                 'scope': ['other'], 'revision': 1, 'created_at': '2026-10-10T00:00:00Z', 'created_by': app.principal}
        app.apply(app.propose({'records/other.md': app.codec.encode(other, '')}), idempotency_key='fixture-other')
        app.apply(app.capture(b'Synthetic source about lantern maintenance.\n', title='Lantern source', scope=['scope'],
                              filename='lantern.md'), idempotency_key='fixture-source')
        self.app = app
        (self.config / 'profiles/test.yaml').write_text(json.dumps({'schema': 'ekk.profile/0.1', 'uid': os.getuid(),
                                                                     'realms': {'main': {'id': self.realm_id, 'path': str(self.realm)}}}))
        self.route = host_api.Route('test', 'main', self.realm_id, ('scope',))

    def reference(self):
        return self.app.search_records(['scope'], query='lantern')['results'][0]['reference']

    def runtime_files(self):
        """Every file of the runtime home but the operation journal, with its size and modification time."""
        return {str(path.relative_to(self.data)): (path.stat().st_size, path.stat().st_mtime_ns) for path in self.data.rglob('*')
                if path.is_file() and path.relative_to(self.data).parts[0] != 'operations'}

    def cli(self, args, body):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), patch('sys.stdin', io.StringIO(json.dumps(body))):
            code = main(args + ['--stdin'])
        self.assertEqual(0, code, error.getvalue())
        return json.loads(output.getvalue())

    def rows(self):
        path = self.data / 'operations/operations.jsonl'
        return [row for row in map(json.loads, path.read_text().splitlines()) if 'attempt_id' in row]

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.realm), *args], capture_output=True, text=True, check=True).stdout

    def test_dispatch_matches_the_cli_envelope_and_writes_nothing(self):
        reference = self.reference()
        before = (self.git('for-each-ref'), self.git('status', '--porcelain'), self.runtime_files())
        route = ['--profile', 'test', '--realm', 'main', '--scope', 'scope', '--cwd', '/']
        for operation, request in (('context', {'task': 'lantern maintenance'}), ('search', {'query': 'lantern'}),
                                   ('fetch', {'reference': reference})):
            with self.subTest(operation):
                envelope = host_api.dispatch(operation, request, route=self.route, caller=None, request_id='r-1')
                self.assertEqual(json.loads(json.dumps(envelope)), envelope)  # plain values only
                shown = self.cli([operation, *route], {'request_id': 'r-1', 'operation': operation, **request})
                if operation == 'context':  # the one clock reading of the two assemblies
                    shown['data']['manifest']['freshness']['assembled_at'] = envelope['data']['manifest']['freshness']['assembled_at']
                self.assertEqual(shown, envelope)
                self.assertEqual(('ekk.result/0.1', 'r-1', operation, 'completed'),
                                 (envelope['schema'], envelope['request_id'], envelope['operation'], envelope['status']))
        source = host_api.dispatch('fetch', {'reference': reference}, route=self.route, caller=None)['data']
        requests = {'enter': {'task': 'lantern'}, 'context': {'task': 'lantern'}, 'contexts': {}, 'search': {'query': 'lantern'},
                    'fetch': {'reference': reference}, 'read-source': {'reference': source['reference']}, 'doctor': {}, 'review': {},
                    'assurance': {}}
        self.assertEqual(host_api.OPERATIONS, set(requests))
        for operation, request in requests.items():
            with self.subTest(operation):
                envelope = host_api.dispatch(operation, request, route=self.route, caller=None)
                self.assertEqual(('ekk.result/0.1', operation, 'completed'), (envelope['schema'], envelope['operation'], envelope['status']))
        # Reads only: the store, its working tree and every runtime file keep their state; only the journal is new.
        # Projection, discovery, history and parsed caches go to the cache home as the CLI writes them; they are disposable.
        self.assertEqual(before, (self.git('for-each-ref'), self.git('status', '--porcelain'), self.runtime_files()))
        self.assertFalse((self.data / 'observed').exists())

    def test_brief_selects_with_the_agent_view_budget(self):
        original, budgets = RealmService.context, []

        def spy(app, scopes, task='', budget=16000, **options):
            budgets.append(budget)
            return original(app, scopes, task=task, budget=budget, **options)
        with patch.object(RealmService, 'context', spy):
            for operation in ('enter', 'context'):
                brief = host_api.dispatch(operation, {'task': 'lantern'}, route=self.route, caller=None, brief=True)
                self.assertEqual('ekk.context-brief/0.3', brief['data']['schema'])
            host_api.dispatch('context', {'task': 'lantern'}, route=self.route, caller=None)
            host_api.dispatch('context', {'task': 'lantern', 'budget': 2000}, route=self.route, caller=None, brief=True)
        self.assertEqual([AGENT_VIEW_RECORD_BUDGET, AGENT_VIEW_RECORD_BUDGET, 16000, 2000], budgets)
        with self.assertRaisesRegex(ValueError, 'brief'):
            host_api.dispatch('search', {'query': 'lantern'}, route=self.route, caller=None, brief=True)
        self.assertFalse((self.data / 'observed').exists())

    def test_the_caller_is_declared_never_inferred(self):
        fleet = self.root / 'fleet.json'
        fleet.write_text(json.dumps({'schema_version': 'lifeos.codex-profile-fleet/1', 'profiles': {'alpha': {'home': str(self.root / 'alpha')}}}))
        registry = {'schema': 'ekk.callers/0.1', 'codex_profile_fleet': str(fleet), 'adapters': ['private-gateway'],
                    'environments': {'claude-code': {'CLAUDECODE': '1'}}}
        path = self.config / 'callers.yaml'; path.write_text(json.dumps(registry)); path.chmod(0o600)
        expected = []
        with patch.dict(os.environ, {'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'synthetic-session'}):
            for caller, attributed in ((None, 'unknown'), ('private-gateway', 'private-gateway'), ('claude-code', 'claude-code'),
                                       ('alpha', 'alpha'), ('forged', 'unknown'), ('unknown', 'unknown')):
                envelope = host_api.dispatch('contexts', {}, route=self.route, caller=caller)
                self.assertNotIn(_WARNING, envelope['warnings'])
                expected.append(attributed)
            with patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'alpha')}):
                self.assertEqual({'ok': True}, host_api.observed('context', lambda: {'ok': True}, caller=None))
                expected.append('unknown')
            fleet.write_text('{"schema_version": "other"}')
            for caller, attributed in (('alpha', 'unknown'), ('private-gateway', 'private-gateway')):
                envelope = host_api.dispatch('contexts', {}, route=self.route, caller=caller)
                self.assertEqual(attributed == 'unknown', _WARNING in envelope['warnings'], caller)
                expected.append(attributed)
            path.write_text('schema: another\n')
            envelope = host_api.dispatch('contexts', {}, route=self.route, caller='private-gateway')
            self.assertEqual(('completed', 1), (envelope['status'], envelope['warnings'].count(_WARNING)))
            expected.append('unknown')
        self.assertEqual(expected, [row['caller_profile'] for row in self.rows()])
        called = []
        with self.assertRaises(ValueError):
            host_api.observed('not-an-op', lambda: called.append(True), caller=None)
        self.assertEqual([], called)
        self.assertEqual(len(expected), len(self.rows()))

    def test_route_and_request_refusals(self):
        for options in ({'scopes': ()}, {'scopes': ('scope', 'scope')}, {'scopes': ['scope']}, {'scopes': ('',)},
                        {'profile': '../test'}, {'realm': ''}, {'realm_id': None}):
            with self.subTest(options), self.assertRaises(ValueError):
                host_api.Route(**{'profile': 'test', 'realm': 'main', 'realm_id': self.realm_id, 'scopes': ('scope',), **options})
        changed = host_api.Route('test', 'main', 'urn:uuid:00000000-0000-4000-8000-000000000000', ('scope',))
        with patch('ekk.adapters.command_line.service', side_effect=AssertionError('a service was opened')):
            with self.assertRaisesRegex(PermissionError, 'realm identity changed'):
                host_api.dispatch('context', {}, route=changed, caller=None)
            with self.assertRaisesRegex(PermissionError, 'realm identity changed'):
                host_api.capture_once(b'x', route=changed, caller=None, title='T', filename='x.md', key='refused')
            for key in ('root', 'profile', 'realm', 'target_realm', 'target_scope', 'principal', 'scopes', 'workspace_id', 'payload',
                        'operation', 'caller', 'caller_profile', 'personal', 'resume'):
                with self.subTest(key), self.assertRaises(PermissionError):
                    host_api.dispatch('context', {key: 'x'}, route=self.route, caller=None)
            for operation in ('propose', 'apply', 'accept', 'decide', 'export', 'capture', 'retain', 'init', 'recover'):
                with self.subTest(operation), self.assertRaises(ValueError):
                    host_api.dispatch(operation, {}, route=self.route, caller=None)
        for artifact in ({'data': b'x', 'filename': 'x.md', 'title': None}, {'data': b'x', 'filename': 'x.md', 'extra': 'y'},
                         {'data': 'x', 'filename': 'x.md'}, {'filename': 'x.md'}, {'data': b'x'}):
            with self.subTest(artifact), self.assertRaisesRegex(ValueError, 'exactly'):
                host_api.retain_once([artifact], route=self.route, caller=None, title='T', body='B', key='refused')
        self.assertFalse((self.data / 'capture-requests').exists())
        self.assertEqual(('access_denied', 'invalid_request'), (host_api.error_code(PermissionError('x')), host_api.error_code(RequestError('x'))))
        self.assertEqual(json.loads((REPOSITORY / 'spec/schemas/record.schema.json').read_text()), host_api.record_schema())

    def test_idempotency_is_compatible_with_pre_facade_keys(self):
        """Retries of keys the 0.8 gateway wrote replay; another scope order or a None key is another request."""
        app = service(self.realm, realm_id=self.realm_id, allowed_scopes=['scope', 'other'])
        route = host_api.Route('test', 'main', self.realm_id, ('scope', 'other'))
        reversed_route = host_api.Route('test', 'main', self.realm_id, ('other', 'scope'))
        artifact = {'data': b'exact\r\nbytes\x00\xff', 'filename': 'result.bin'}
        first = direct_retain_once(app, [artifact], title='Result', body='Synthetic result.', scopes=['scope', 'other'], key='k')
        records = self.app.doctor()['records']
        retained = host_api.retain_once([artifact], route=route, caller='private-gateway', title='Result', body='Synthetic result.', key='k')
        self.assertEqual(('k', 'completed', first), (retained['request_id'], retained['status'], retained['data']))
        self.assertEqual(('ekk.result/0.1', json.loads(json.dumps(retained))), (retained['schema'], retained))  # plain values only
        with self.assertRaises(IdempotencyConflict):
            host_api.retain_once([artifact], route=reversed_route, caller=None, title='Result', body='Synthetic result.', key='k')
        with self.assertRaises(IdempotencyConflict):
            direct_retain_once(app, [{**artifact, 'title': None}], title='Result', body='Synthetic result.', scopes=['scope', 'other'], key='k')
        captured = cli_capture_once(app, b'Original source.\n', title='Source', scopes=['scope', 'other'], filename='source.md', key='c')
        replayed = host_api.capture_once(b'Original source.\n', route=route, caller=None, title='Source', filename='source.md', key='c')
        self.assertEqual(('c', captured), (replayed['request_id'], replayed['data']))
        self.assertEqual(('ekk.result/0.1', json.loads(json.dumps(replayed))), (replayed['schema'], replayed))
        with self.assertRaises(IdempotencyConflict):
            host_api.capture_once(b'Original source.\n', route=reversed_route, caller=None, title='Source', filename='source.md', key='c')
        self.assertEqual(records + 1, self.app.doctor()['records'])  # the capture only; every replay wrote nothing


if __name__ == '__main__': unittest.main()
