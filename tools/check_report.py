#!/usr/bin/env python3
"""Explicit POSIX host check producer; this is never invoked by ``ekk assess``.

Run from a source checkout with EKK installed::

    python tools/check_report.py --cwd PROJECT --check unit -- python -m unittest

The command runs in a disposable local clone of the exact committed tree. This
is not a sandbox: explicitly supplied commands retain the caller's environment
and OS permissions. Dependencies, external services and descendants that escape
the process group are outside the claim. Submodules and tracked symlinks are
unsupported and yield unknown. No output is retained. The owner-configured report
parent must already exist. Binding validation selects report ownership; it does
not access a knowledge realm or authenticate the producer. Exit codes: 0 passed, 1 failed, 2 unknown/error.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time
import uuid

from ekk.adapters.markdown import MarkdownCodec
from ekk.adapters.repository_evidence import configured_checks, read_configured_bytes
from ekk.model import validate_identifier

REPORT_SCHEMA = 'ekk.configured-check-report/0.1'
MAX_REPORT_BYTES = 65536
MAX_TRACKED_BYTES = 16 * 1024 * 1024
_COMMIT = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class Uncertain(ValueError):
    """A fixed diagnostic code, never command text or captured output."""


def _environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS='1', GIT_OPTIONAL_LOCKS='0', GIT_ATTR_NOSYSTEM='1')
    return env


def _git(root, *args):
    result = subprocess.run(['git', '--literal-pathspecs', '-C', str(root), '-c', 'core.fsmonitor=false',
        '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.autocrlf=false',
        '-c', 'core.attributesFile=' + os.devnull, *args],
        env=_environment(), stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    if result.returncode or len(result.stdout) > MAX_TRACKED_BYTES:
        raise Uncertain('git_unavailable')
    return result.stdout


def _head(root):
    actual_root = os.fsdecode(_git(root, 'rev-parse', '--show-toplevel')).strip()
    if Path(actual_root) != root:
        raise Uncertain('binding_is_not_git_root')
    head = _git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode('ascii').strip()
    if not _COMMIT.fullmatch(head):
        raise Uncertain('git_commit_unavailable')
    return head


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode,
            info.st_mtime_ns, info.st_ctime_ns)


def _binding(root):
    before = (root / '.ekk/workspace.yaml').lstat()
    raw = read_configured_bytes(root, '.ekk/workspace.yaml', max_bytes=MAX_REPORT_BYTES)
    after = (root / '.ekk/workspace.yaml').lstat()
    if _stamp(before) != _stamp(after):
        raise Uncertain('source_changed')
    document = MarkdownCodec().load_yaml(raw)
    if not isinstance(document, dict) or document.get('schema') != 'ekk.workspace/0.1':
        raise Uncertain('invalid_workspace_binding')
    validate_identifier(document.get('workspace_id'))
    routes = document.get('bindings')
    if not isinstance(routes, list) or len(routes) != 1 or not isinstance(routes[0], dict):
        raise Uncertain('one_workspace_route_required')
    route = routes[0]
    validate_identifier(route.get('realm_id'))
    if not isinstance(route.get('realm_alias'), str) or not route['realm_alias']:
        raise Uncertain('invalid_workspace_binding')
    scopes = route.get('contexts')
    if not isinstance(scopes, list) or not scopes or len(set(scopes)) != len(scopes):
        raise Uncertain('invalid_workspace_binding')
    for scope in scopes:
        validate_identifier(scope)
    return (raw, _stamp(after)), document, configured_checks(document)


def _open_directory(path):
    if not path.is_absolute() or '..' in path.parts:
        raise Uncertain('unsafe_report_parent')
    descriptor = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for component in path.parts[1:]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class ReportWriter:
    """Pin an existing owner-selected directory; never follow a report symlink."""

    def __init__(self, root, relative):
        self.parent = root / relative.parent
        self.name = relative.name
        self.fd = _open_directory(self.parent)

    def close(self):
        os.close(self.fd)

    def _current(self):
        current = _open_directory(self.parent)
        try:
            before, after = os.fstat(self.fd), os.fstat(current)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise Uncertain('report_parent_changed')
        finally:
            os.close(current)
        try:
            info = os.stat(self.name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REPORT_BYTES:
            raise Uncertain('unsafe_report_file')

    def write(self, report):
        self._current()
        raw = (json.dumps(report, sort_keys=True, separators=(',', ':')) + '\n').encode()
        if len(raw) > MAX_REPORT_BYTES:
            raise Uncertain('report_exceeds_limit')
        temporary = '.ekk-check-' + uuid.uuid4().hex
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=self.fd)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._current()
            os.replace(temporary, self.name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass


def _manifest(root, commit):
    raw = _git(root, 'ls-tree', '-rz', '--full-tree', commit)
    rows = []
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, kind, object_id = metadata.split(b' ')
        path = Path(os.fsdecode(name))
        if (mode not in (b'100644', b'100755') or kind != b'blob'
                or path.is_absolute() or '..' in path.parts or '.git' in path.parts):
            raise Uncertain('unsupported_tracked_entry')
        rows.append((os.fsdecode(name), mode == b'100755', object_id.decode('ascii')))
    return rows


def _verify_tree(root, commit, rows):
    if (_head(root) != commit or _manifest(root, commit) != rows
            or _git(root, 'write-tree').strip() != _git(root, 'rev-parse', commit + '^{tree}').strip()):
        raise Uncertain('fixture_git_changed')
    algorithm = 'sha1' if len(commit) == 40 else 'sha256'
    stamps = []
    for relative, executable, expected in rows:
        raw = read_configured_bytes(root, relative, max_bytes=MAX_TRACKED_BYTES)
        digest = hashlib.new(algorithm, b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        info = (root / relative).lstat()
        if digest != expected or not stat.S_ISREG(info.st_mode) or bool(info.st_mode & 0o111) != executable:
            raise Uncertain('fixture_tracked_bytes_changed')
        stamps.append(_stamp(info))
    return stamps


def _checkout(root, destination, commit):
    # --local copies object files without a transport, upload-pack or source
    # hooks; --no-hardlinks avoids sharing mutable object inodes with the source.
    template = destination.parent / 'empty-template'
    template.mkdir()
    _git(root, 'clone', '--local', '--no-hardlinks', '--no-checkout',
         '--template=' + str(template), '--', str(root), str(destination))
    _git(destination, 'checkout', '--detach', '--force', commit, '--')


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return False
    try:
        process.wait(timeout=0.1)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(0.1)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        process.wait(timeout=5)
    return True


def _execute(command, root, timeout):
    # Output goes directly to /dev/null: neither receipts nor files retain it.
    process = subprocess.Popen(command, cwd=root, env=_environment(), shell=False,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    try:
        code = process.wait(timeout=timeout)
    except BaseException:
        _kill_group(process)
        raise
    try:
        descendants = _kill_group(process)
    except OSError as error:
        raise Uncertain('process_group_cleanup_uncertain') from error
    if descendants:
        raise Uncertain('command_left_descendants')
    return code


def produce(cwd, check, command, *, expected_head=None, timeout=300):
    """Produce one configured declaration from an explicit argv; no registry."""
    receipt = {'check_id': check, 'status': 'unknown', 'report_written': False,
               'producer_authenticated': False, 'reason': 'setup_unavailable'}
    writer = None
    report = None
    temporary = None
    try:
        if os.name != 'posix' or not command or not math.isfinite(timeout) or timeout <= 0:
            raise Uncertain('invalid_invocation')
        if expected_head is not None and not _COMMIT.fullmatch(expected_head):
            raise Uncertain('invalid_expected_head')
        root = Path(cwd).expanduser().absolute()
        # Secure read rejects symlinked roots as well as intermediate components.
        binding_raw, document, checks = _binding(root)
        if check not in checks:
            raise Uncertain('check_not_configured')
        relative = Path(checks[check])
        if relative == Path('.ekk/workspace.yaml'):
            raise Uncertain('report_overlaps_binding')
        commit = _head(root)
        if _git(root, 'ls-tree', '-rz', '--full-tree', commit, '--', relative.as_posix()):
            raise Uncertain('report_is_tracked_source')
        report = {'schema': REPORT_SCHEMA, 'workspace_id': document['workspace_id'],
                  'check_id': check, 'tested_commit': expected_head or commit,
                  'observed_at': datetime.now(timezone.utc).isoformat(), 'status': 'unknown'}
        writer = ReportWriter(root, relative)
        writer.write(report)  # Invalidate an earlier pass before any setup/run.
        receipt['report_written'] = True
        receipt['tested_commit'] = report['tested_commit']
        if expected_head is not None and expected_head != commit:
            raise Uncertain('expected_head_mismatch')
        rows = _manifest(root, commit)
        temporary = tempfile.TemporaryDirectory(prefix='ekk-check-')
        fixture = Path(temporary.name).resolve() / 'checkout'
        _checkout(root, fixture, commit)
        fixture_stamps = _verify_tree(fixture, commit, rows)
        if _head(root) != commit or _binding(root)[0] != binding_raw:
            raise Uncertain('source_changed')
        returncode = _execute(command, fixture, timeout)
        if _verify_tree(fixture, commit, rows) != fixture_stamps:
            raise Uncertain('fixture_tracked_bytes_changed')
        temporary.cleanup()
        temporary = None
        if _head(root) != commit or _binding(root)[0] != binding_raw:
            raise Uncertain('source_changed')
        report['status'] = 'passed' if returncode == 0 else 'failed'
        report['observed_at'] = datetime.now(timezone.utc).isoformat()
        writer.write(report)
        receipt.update(status=report['status'], reason='command_completed')
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, subprocess.SubprocessError,
            KeyboardInterrupt) as error:
        receipt['reason'] = str(error) if isinstance(error, Uncertain) else 'operation_uncertain'
        # The initial unknown normally remains. A final write may have replaced
        # it before a directory fsync failed; restore unknown on that path too.
        if writer is not None and report is not None and report['status'] != 'unknown':
            report['status'] = 'unknown'
            try:
                writer.write(report)
            except (OSError, ValueError):
                receipt['report_written'] = False
    finally:
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError:
                receipt.update(status='unknown', reason='cleanup_uncertain')
        if writer is not None:
            writer.close()
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--check', required=True)
    parser.add_argument('--expected-head')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else []
    receipt = produce(args.cwd, args.check, command, expected_head=args.expected_head, timeout=args.timeout)
    print(json.dumps(receipt, sort_keys=True))
    return {'passed': 0, 'failed': 1, 'unknown': 2}[receipt['status']]


if __name__ == '__main__':
    raise SystemExit(main())
