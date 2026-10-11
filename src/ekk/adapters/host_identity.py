"""One host identity for the hook, the CLI and the operation journal.

The core is standard library only, because the host hook imports it on every
prompt: from a hook payload and the environment it reads the host, the raw Codex
home and the session. The registry layer (`load_registry`, `resolve`,
`profile_lookup`) reads the owner's caller registry, `callers.yaml` with schema
ekk.callers/0.1, and the Codex profile fleet it names; it imports YAML and is
never loaded on the hook path.

- host: 'codex', 'claude-code', a registered environment ID, or 'unknown'.
- profile: the fleet registry key of the resolved Codex home; None for an
  unregistered home and for every other host. Never a directory name.
- session: text of at most 256 characters, or None. An overlong value is absent,
  never cut, so it cannot link to another session.
- caller: the journal's registered caller (the fleet key, or the environment
  ID), or None.

Nothing here authenticates anyone or grants access.
"""
import collections
import os
from pathlib import Path
import re

from ..homes import config_home

HOST_MARKERS = ('CODEX_HOME', 'CLAUDECODE')
# Built-in declarations; an additive `sessions:` map in the caller registry overrides a host.
SESSION_VARIABLES = {'codex': ('CODEX_THREAD_ID',), 'claude-code': ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_SESSION_ID')}
# Never read: the host session ID is not the conversation, and the child marker is set in top-level desktop sessions too.
UNREAD_VARIABLES = ('CLAUDE_CODE_HOST_SESSION_ID', 'CLAUDE_CODE_CHILD_SESSION')
# What isolated tests and the hook-started observer drain remove from their environment.
SCRUB_VARIABLES = HOST_MARKERS + tuple(dict.fromkeys(name for names in SESSION_VARIABLES.values() for name in names)) + UNREAD_VARIABLES
# Markers that name a host without a registry, or when no registered environment matches.
ENVIRONMENTS = {'claude-code': {'CLAUDECODE': '1'}}
MAX_SESSION_CHARS = 256
MAX_PATH_CHARS = 4096
_CODEX_HOME = re.compile(r'/\.codex(?:-[\w.-]+)?/')
_ENVIRONMENT_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}\Z')

HostIdentity = collections.namedtuple('HostIdentity', 'host profile session caller')


# --------------------------------------------------------------------- the core
def bounded(value, limit):
    """Text of 1..limit characters, or None."""
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def payload_host(payload):
    """The host a hook payload itself names, by its transcript path, then by a Codex turn ID; None otherwise."""
    transcript = payload.get('transcript_path') if isinstance(payload.get('transcript_path'), str) else ''
    if '/.claude/' in transcript:
        return 'claude-code'
    if _CODEX_HOME.search(transcript) or 'turn_id' in payload:
        return 'codex'
    return None


def environment_host(environ, environments=ENVIRONMENTS):
    """CODEX_HOME gives codex, otherwise exactly one matching marker set; else 'unknown'.

    A Codex process started from Claude Code inherits CLAUDECODE, so with both
    markers the host is codex.
    """
    if environ.get('CODEX_HOME'):
        return 'codex'
    matches = [name for name, markers in environments.items()
               if all(environ.get(variable) == value for variable, value in markers.items())]
    return matches[0] if len(matches) == 1 else 'unknown'


def session_of(host, environ, variables=SESSION_VARIABLES):
    """The first of the host's declared session variables that holds valid text, or None."""
    for name in variables.get(host, ()):
        value = bounded(environ.get(name), MAX_SESSION_CHARS)
        if value:
            return value
    return None


def hook_identity(payload, environ=None):
    """(host, codex_home, session) for the hook, without the registry.

    Payload facts come first: the host from the transcript path or turn ID, the
    session from session_id. codex_home is the raw CODEX_HOME of a Codex host;
    the observer maps it to the profile at ingest.
    """
    environ = os.environ if environ is None else environ
    host = payload_host(payload) or environment_host(environ)
    codex_home = bounded(environ.get('CODEX_HOME'), MAX_PATH_CHARS) if host == 'codex' else None
    return host, codex_home, bounded(payload.get('session_id'), MAX_SESSION_CHARS) or session_of(host, environ)


def transcript_home(path):
    """The Codex home (`…/.codex` or `…/.codex-NAME`) a transcript lies in, or None."""
    found = _CODEX_HOME.search(path) if isinstance(path, str) else None
    return path[:found.end() - 1] if found else None


# ------------------------------------------------------------ the registry layer
def _session_variables(value):
    """Built-in session variables with the registry's per-host overrides.

    A malformed entry gives that host no session; a `sessions` value that is not a
    map gives every host none. Neither raises.
    """
    if value is None:
        return dict(SESSION_VARIABLES)
    if not isinstance(value, dict):
        return {}
    variables = dict(SESSION_VARIABLES)
    for host, names in value.items():
        if isinstance(host, str):
            valid = isinstance(names, list) and 0 < len(names) <= 8 and all(
                isinstance(name, str) and _ENVIRONMENT_NAME.fullmatch(name) and name not in UNREAD_VARIABLES for name in names)
            variables[host] = tuple(names) if valid else ()
    return variables


class Registry:
    """The owner's caller registry, checked as the journal has always checked it."""

    def __init__(self, config):
        from .operation_journal import TrustedCallerProfile
        if not isinstance(config, dict) or config.get('schema') != 'ekk.callers/0.1':
            raise ValueError('Unknown caller configuration')
        adapters = config.get('adapters', [])
        if not isinstance(adapters, list) or any(not isinstance(item, str) for item in adapters):
            raise ValueError('Caller adapters must be registered identifiers')
        for item in adapters:
            TrustedCallerProfile(item)
        environments = config.get('environments', {})
        if not isinstance(environments, dict) or any(
                not isinstance(markers, dict) or not markers or any(
                    not isinstance(name, str) or not _ENVIRONMENT_NAME.fullmatch(name)
                    or not isinstance(value, str) or not 0 < len(value) <= 256
                    for name, value in markers.items())
                for markers in environments.values()):
            raise ValueError('Caller environments must map registered identifiers to environment markers')
        for item in environments:
            TrustedCallerProfile(item)
        self.adapters, self.environments = tuple(adapters), environments
        self.fleet_path = config.get('codex_profile_fleet')
        self.sessions = _session_variables(config.get('sessions'))
        self._fleet = None

    def _profiles(self):
        """[(fleet key, resolved home)] of the Codex profile fleet; empty without one. An unreadable or unknown fleet raises."""
        if not self.fleet_path:
            return []
        if self._fleet is None:
            from .local_profile import read_yaml
            fleet = read_yaml(Path(self.fleet_path).expanduser())
            if not isinstance(fleet, dict) or fleet.get('schema_version') != 'lifeos.codex-profile-fleet/1' or not isinstance(fleet.get('profiles'), dict):
                raise ValueError('Unknown caller fleet registry')
            self._fleet = [(key, Path(row['home']).expanduser().resolve()) for key, row in fleet['profiles'].items()
                           if isinstance(row, dict) and row.get('home')]
        return self._fleet

    def codex_profile(self, home):
        """The fleet key whose home resolves to `home`; None without a fleet or a single match.

        An unreadable or unknown fleet raises.
        """
        if not home or not self.fleet_path:
            return None
        actual = Path(home).expanduser().resolve()
        matches = [key for key, path in self._profiles() if path == actual]
        return matches[0] if len(matches) == 1 else None

    def registered(self, caller):
        """Whether `caller` is an ID this registry attributes: an adapter, an environment or a Codex fleet key.

        An unreadable or unknown fleet raises.
        """
        return isinstance(caller, str) and (caller in self.adapters or caller in self.environments
                                            or any(key == caller for key, _ in self._profiles()))


def load_registry():
    """The caller registry, or None when there is none; raises on one that is not private or not understood."""
    from .local_profile import read_yaml
    path = config_home() / 'callers.yaml'
    if not path.exists():
        return None
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 65536:
        raise PermissionError('Caller configuration must be private to the OS owner')
    return Registry(read_yaml(path))


def resolve(environ=None, *, strict=False):
    """The calling process's HostIdentity, from its environment.

    CODEX_HOME gives codex, whose profile and caller are the fleet key of the
    resolved home. Otherwise exactly one registered environment gives the host
    and the caller; several stay unknown; with none, the built-in markers give
    the host only. Strict resolution, the journal's, raises on a registry it
    cannot read. Otherwise such a registry counts as absent, so recording an
    identity never fails the caller's command.
    """
    environ = os.environ if environ is None else environ
    try:
        registry = load_registry()
    except Exception:
        if strict:
            raise
        registry = None
    variables = registry.sessions if registry is not None else SESSION_VARIABLES
    if environ.get('CODEX_HOME'):
        profile = None
        if registry is not None:
            try:
                profile = registry.codex_profile(environ['CODEX_HOME'])
            except Exception:
                if strict:
                    raise
        return HostIdentity('codex', profile, session_of('codex', environ, variables), profile)
    matches = [name for name, markers in (registry.environments if registry is not None else {}).items()
               if all(environ.get(variable) == value for variable, value in markers.items())]
    if len(matches) == 1:
        host, caller = matches[0], matches[0]
    else:
        host, caller = ('unknown' if matches else environment_host(environ)), None
    return HostIdentity(host, None, session_of(host, environ, variables), caller)


def profile_lookup():
    """A memoized map from a Codex home to its fleet key for one observer pass; never raises."""
    try:
        registry = load_registry()
    except Exception:
        registry = None
    found = {}

    def lookup(home):
        if home not in found:
            try:
                found[home] = registry.codex_profile(home) if registry is not None and home else None
            except Exception:
                found[home] = None
        return found[home]
    return lookup
