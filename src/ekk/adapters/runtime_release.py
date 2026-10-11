"""Release identity: which EKK runtime is active on this machine and which one is loaded.

The installer (tools/local_install.py) owns the file contract this module reads.
`homes.release_home()/current` is a symlink to one release directory, switched
atomically, and that directory's build.json is its record; releases built before
build.json existed carry only manifest.json. Release directories are written once.
The `state` key of manifest.json is not authoritative (activation never clears it)
and is never read.

A release is a dict of plain values: version, wheel_sha256, source_commit, path
and record (the file they were read from, or None when there is no usable record).

A runtime is current iff both digests are non-None and equal:
``active_release()['wheel_sha256'] == loaded_release()['wheel_sha256'] is not None``.
Never compare by version: several builds share one version, and a missing digest
(an editable install, a damaged record) never compares equal.
"""
import errno
import json
import os
from pathlib import Path
import re

from .. import __version__
from ..homes import release_home

RECORDS = ('build.json', 'manifest.json')
MAX_RECORD_BYTES = 65536
DISTRIBUTION = 'evolutionary-knowledge-kernel'
_DIGEST = re.compile(r'[0-9a-f]{64}')


def _release(version=None, wheel_sha256=None, source_commit=None, path=None, record=None):
    return {'version': version, 'wheel_sha256': wheel_sha256, 'source_commit': source_commit, 'path': path, 'record': record}


def _text(value):
    return value if isinstance(value, str) and value else None


def _digest(value):
    return value if isinstance(value, str) and _DIGEST.fullmatch(value) else None


def release_record(directory):
    """The release in ``directory`` as its record states it; no hashing, no writes.

    build.json comes first, of at most 64 KiB, holding a JSON object. manifest.json
    is read only when build.json is absent, as in releases built before 0.8.3. A
    damaged build.json, or no record at all, gives only the path, with record None.
    """
    directory = Path(directory)
    for name in RECORDS:
        try:
            with open(directory / name, 'rb') as stream:
                raw = stream.read(MAX_RECORD_BYTES + 1)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            break
        try:
            value = json.loads(raw) if len(raw) <= MAX_RECORD_BYTES else None
        except ValueError:
            value = None
        if not isinstance(value, dict):
            break
        return _release(_text(value.get('version')), _digest(value.get('wheel_sha256')), _text(value.get('source_commit')),
                        str(directory), name)
    return _release(path=str(directory))


def active_release():
    """The release `cli/current` names now, read from the files on every call; None without the link.

    The link is read once and its target, relative to the release home or
    absolute, resolved once, so each answer is internally consistent and a switch
    by another process shows on the next call. No cache, subprocess, lock or write.
    A `current` that is not a symlink, or a dangling one, gives the path with
    record None.
    """
    link = release_home() / 'current'
    try:
        target = os.readlink(link)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        if exc.errno != errno.EINVAL:
            raise
        return _release(path=str(link))
    return release_record(os.path.realpath(os.path.join(link.parent, target)))


def _direct_url_digest(text):
    """The wheel's sha256 from pip's direct_url.json text (PEP 610 archive_info), or None."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    info = value.get('archive_info') if isinstance(value, dict) else None
    if not isinstance(info, dict):
        return None
    hashes = info.get('hashes')
    if isinstance(hashes, dict) and 'sha256' in hashes:
        return _digest(hashes['sha256'])
    legacy = info.get('hash')
    return _digest(legacy[len('sha256='):]) if isinstance(legacy, str) and legacy.startswith('sha256=') else None


def loaded_release():
    """The runtime this process imported: its version from ekk.__version__, never from distribution metadata.

    The digest is the installed wheel's, from direct_url.json, and only when that
    distribution's files are the imported ekk package; an editable or source
    install gives None.
    """
    from importlib import metadata
    package = Path(__file__).resolve().parent.parent / '__init__.py'
    digest = None
    try:
        distribution = metadata.distribution(DISTRIBUTION)
        if Path(distribution.locate_file('ekk/__init__.py')).resolve() == package:
            digest = _direct_url_digest(distribution.read_text('direct_url.json'))
    except (metadata.PackageNotFoundError, OSError, ValueError, TypeError):
        digest = None
    return _release(version=__version__, wheel_sha256=digest, record='direct_url.json' if digest else None)
