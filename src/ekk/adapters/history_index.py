"""Per-commit record changes for historical reference resolution.

A published commit, the commit before it and the code that loads them fix which
record versions the commit added, changed or removed, so an entry never goes
stale. An entry is derived only from one complete, validated load of that commit.
It is an index, not a record: the record itself is decoded again from its exact
bytes. A missing, corrupt or foreign entry is a miss. Storing changes instead of
whole listings keeps the index proportional to what was published.
"""
import hashlib
from importlib import metadata
import inspect
import json
from pathlib import Path

import yaml

from .derived_cache import DerivedCache


def _distribution_version(name):
    # About 30 ms per process for the metadata scan; the module attribute is deprecated in jsonschema.
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return 'absent'


def loader_fingerprint():
    """Exactly the inputs that decide whether and how a historical commit loads.

    The loader itself (``RealmService._load`` and ``_roots``), the control file
    names it reads, the delta derivation that fills the index, the envelope and
    method rules it applies, the codec, the schemas and the parsing and
    validating libraries. The rest of the application service is not an input:
    a change to ranking or entry keeps the index warm.
    """
    from ..application.service import CONTROL, RealmService
    from ..assets import schema_directory
    package = Path(__file__).resolve().parent.parent
    value = hashlib.sha256(json.dumps({
        'yaml': yaml.__version__,
        # jsonschema checks date-time only when its format validator is installed.
        **{name: _distribution_version(name) for name in ('jsonschema', 'rfc3339-validator')},
    }, sort_keys=True).encode())
    value.update(b'\0CONTROL\0' + json.dumps(list(CONTROL)).encode())
    for name in ('_load', '_roots', '_record_versions'):
        try:
            source = inspect.getsource(getattr(RealmService, name)).encode()
        except (OSError, TypeError):
            # No source for this loader: the whole module stands in for it.
            source = (package / 'application/service.py').read_bytes()
        value.update(b'\0' + name.encode() + b'\0' + source)
    parts = [package / 'model/__init__.py', package / 'model/methods.py', package / 'adapters/markdown.py']
    parts += sorted(Path(schema_directory()).rglob('*.json'))
    for path in parts:
        value.update(b'\0' + str(path.relative_to(package) if package in path.parents else path.name).encode()
                     + b'\0' + path.read_bytes())
    return value.hexdigest()


class HistoryIndex:
    def __init__(self, directory):
        self.cache = DerivedCache(directory, 'ekk.history-index/0.2:' + loader_fingerprint())

    @staticmethod
    def _input(revision, against):
        return f'{revision}:{against or ""}'.encode()

    def delta(self, revision, against, allow_aliases):
        """Records a commit changed or removed relative to ``against``, or None."""
        value = self.cache.get('delta', self._input(revision, against))
        if (not isinstance(value, dict) or not isinstance(value.get('changed'), dict)
                or not isinstance(value.get('removed'), list) or type(value.get('aliases')) is not bool):
            return None
        # A strict load accepts a subset of what a historical load accepts and
        # yields the same records, so it also answers for the historical reading.
        if value['aliases'] and not allow_aliases:
            return None
        return value

    def put_delta(self, revision, against, allow_aliases, delta):
        self.cache.put('delta', self._input(revision, against), {**delta, 'aliases': bool(allow_aliases)})
