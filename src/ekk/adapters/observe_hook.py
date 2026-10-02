"""Host hook entry: `ekk observe --event NAME` with the hook's JSON on stdin.

Runs on every prompt and turn end of a coding agent, so it imports only the
standard library and the frozen observation rules, never blocks the host and
never fails it: any problem ends with exit status 0 and at most a line in the
private error log. It writes one bounded, redacted event file to a private
spool; the background observer turns events into records. Nothing is captured
outside a bound project that can own a record, from a subagent, or while
observation is switched off.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from .. import observation
from ..homes import cache_home, config_home, data_home

EVENTS = {'SessionStart', 'UserPromptSubmit', 'Stop', 'SessionEnd'}
MAX_REPOSITORIES = 16
MAX_CARD_CHARS = 6000
_OPT_OUT = re.compile(r'^\s*["\']?observe["\']?\s*:\s*["\']?(false|no|off)["\']?\s*,?\s*(#.*)?$', re.MULTILINE | re.IGNORECASE)
_BINDING = re.compile(r'realm_id')
_CODEX_HOME = re.compile(r'/\.codex(?:-([\w.-]+))?/')


def observed_home():
    return data_home() / 'observed'


def switched_off():
    return os.environ.get('EKK_OBSERVE') == '0' or (config_home() / 'observe-off').exists()


def bound_workspace(cwd):
    """(root, routable) of the single binding enclosing cwd, or None.

    The walk is the one entry uses. ``routable`` is false when the project opted
    out of observation or binds several realms: no single owner can take a record
    then, so nothing is captured and the agent is told to retain by hand.
    """
    path = Path(cwd).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return None
    found = []
    for root in (path, *path.parents):
        candidate = root / '.ekk/workspace.yaml'
        if candidate.is_file():
            found.append((root, candidate))
        if (root / '.git').exists():
            break
    if len(found) != 1:
        return None
    root, binding = found[0]
    try:
        text = binding.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    try:  # a binding written as JSON is read exactly; YAML is read by its two decisive lines
        document = json.loads(text)
        bindings = document.get('bindings') if isinstance(document, dict) else None
        return root, isinstance(bindings, list) and len(bindings) == 1 and document.get('observe') is not False
    except ValueError:
        return root, not _OPT_OUT.search(text) and len(_BINDING.findall(text)) == 1


def workspace_of(cwd):
    """The bound, observed workspace enclosing cwd, or None."""
    found = bound_workspace(cwd)
    return found[0] if found and found[1] else None


def _git_directory(repository):
    """(git directory, common directory) of a checkout or a linked worktree."""
    marker = repository / '.git'
    if marker.is_dir():
        return marker, marker
    try:
        text = marker.read_text().strip()
        if not text.startswith('gitdir:'):
            return None
        directory = (repository / text[7:].strip()).resolve()
        common = directory / 'commondir'
        return directory, (directory / common.read_text().strip()).resolve() if common.is_file() else directory
    except OSError:
        return None


def repositories(workspace):
    """The workspace repository and the repositories directly inside it, by name."""
    workspace = Path(workspace)
    found = [('.', workspace)] if (workspace / '.git').exists() else []
    try:
        found += sorted((child.name, child) for child in workspace.iterdir() if child.is_dir() and (child / '.git').exists())
    except OSError:
        pass
    return found[:MAX_REPOSITORIES]


def heads(workspace):
    """Current commit of each repository, read from Git's files without starting a process."""
    result = {}
    for name, repository in repositories(workspace):
        try:
            directories = _git_directory(repository)
            if directories is None:
                continue
            directory, common = directories
            value = (directory / 'HEAD').read_text().strip()
            if value.startswith('ref: '):
                reference = value[5:]
                loose = next((base / reference for base in (directory, common) if (base / reference).is_file()), None)
                if loose is not None:
                    value = loose.read_text().strip()
                else:
                    packed = (common / 'packed-refs').read_text().splitlines()
                    value = next((line.split()[0] for line in packed if line.endswith(' ' + reference)), '')
            if re.fullmatch(r'[0-9a-f]{40}', value):
                result[name] = value
        except OSError:
            continue
    return result


def main_checkout(workspace):
    """The primary checkout of a linked worktree, or the workspace itself."""
    directories = _git_directory(Path(workspace))
    if directories and directories[0] != directories[1] and directories[1].name == '.git':
        return directories[1].parent
    return Path(workspace)


def card_path(workspace):
    return cache_home() / 'observed' / 'cards' / (hashlib.sha256(str(workspace).encode()).hexdigest() + '.txt')


def host_of(payload):
    """(host, profile) from what the host itself sent, falling back to its environment."""
    transcript = payload.get('transcript_path') if isinstance(payload.get('transcript_path'), str) else ''
    if '/.claude/' in transcript:
        return 'claude-code', None
    codex = _CODEX_HOME.search(transcript)
    if codex:
        return 'codex', codex.group(1)
    if 'turn_id' in payload:
        home = os.environ.get('CODEX_HOME')
        return 'codex', (_CODEX_HOME.search(home + '/') or [None, None])[1] if home else None
    if os.environ.get('CLAUDECODE') == '1':
        return 'claude-code', None
    if os.environ.get('CODEX_HOME'):
        return 'codex', Path(os.environ['CODEX_HOME']).name.removeprefix('.codex-') or None
    return 'unknown', None


def _private_directory(path):
    # mkdir applies the mode to the last component only; the observer home must be private too.
    observed_home().mkdir(parents=True, exist_ok=True, mode=0o700)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _spool(document):
    directory = _private_directory(observed_home() / 'spool')
    name = f'{time.time_ns()}-{os.getpid()}'
    temporary = directory / (name + '.tmp')  # the observer reads only *.json
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(document, stream, ensure_ascii=False)
    os.replace(temporary, directory / (name + '.json'))


def _start_observer():
    if os.environ.get('EKK_OBSERVE_WORKER') == '0':
        return
    import subprocess
    log = _private_directory(observed_home()) / 'observer.log'
    if log.exists() and log.stat().st_size > 256 * 1024:
        log.unlink()
    descriptor = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'ab') as stream:
        subprocess.Popen([sys.executable, '-I', '-B', '-m', 'ekk', 'observe', 'drain', '--background'],
                         stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, close_fds=True, start_new_session=True)


def _note_error(reason):
    try:
        path = _private_directory(observed_home()) / 'hook-errors.log'
        if path.exists() and path.stat().st_size > 256 * 1024:
            return
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a', encoding='utf-8') as stream:
            stream.write(f'{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} {reason}\n')
    except OSError:
        pass


def _session_card(workspace, routable):
    if not routable:
        return observation.CONTRACT_MANUAL
    for candidate in (workspace, main_checkout(workspace)):
        try:
            return card_path(candidate).read_text(encoding='utf-8')[:MAX_CARD_CHARS]
        except OSError:
            continue
    return observation.CONTRACT


def _text(value, limit):
    """Bound, redact, bound: the bound comes first so that redaction never scans an unbounded input."""
    text, _ = observation.bounded(value.strip(), limit + 2000)
    return observation.bounded(observation.redact(text), limit)


def observe(event, raw):
    """Returns (stdout document or None, spool document or None)."""
    if event not in EVENTS or switched_off():
        return None, None
    if len(raw) > observation.MAX_EVENT_BYTES:
        _note_error(f'{event} oversize')
        return None, None
    payload = json.loads(raw.decode('utf-8', errors='replace') or '{}')
    if not isinstance(payload, dict) or payload.get('agent_id'):
        return None, None  # a subagent's turn belongs to its parent's report
    found = bound_workspace(payload.get('cwd') or os.getcwd())
    if found is None:
        return None, None
    workspace, routable = found
    output = None
    # A resumed session still holds the card it was given; a new, cleared or compacted one does not.
    if event == 'SessionStart' and payload.get('source') != 'resume':
        output = {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': _session_card(workspace, routable)}}
    if not routable:
        return output, None
    host, profile = host_of(payload)
    document = {'schema': 'ekk.observed-event/0.2', 'event': event, 'host': host, 'profile': profile,
                'session': str(payload.get('session_id') or ''), 'turn': payload.get('turn_id') or payload.get('prompt_id'),
                'at': time.time(), 'workspace': str(workspace)}
    if event == 'UserPromptSubmit':
        # Every prompt marks a turn in progress; its text is kept only when it reads as a correction.
        text = observation.owner_text(payload.get('prompt') or payload.get('user_input'))
        if observation.is_correction(text):
            document['text'] = observation.redact(text)
        return output, document
    if event == 'Stop':
        report = payload.get('last_assistant_message')
        if isinstance(report, str) and report.strip():
            document['text'], document['truncated'] = _text(report, observation.MAX_REPORT_CHARS)
        elif 'last_assistant_message' not in payload and isinstance(payload.get('transcript_path'), str):
            document['transcript'] = payload['transcript_path']  # an older host: read once it has flushed the turn
    if event == 'SessionStart':
        document['source'] = payload.get('source')
    if event == 'SessionEnd':
        document['reason'] = payload.get('reason')
    document['heads'] = heads(workspace)
    return output, document


def main(argv):
    """argv is ['--event', NAME]. Always succeeds from the host's point of view."""
    try:
        event = argv[1] if len(argv) > 1 and argv[0] == '--event' else ''
        output, document = observe(event, sys.stdin.buffer.read(observation.MAX_EVENT_BYTES + 1))
        if output is not None:  # the contract reaches the agent even when capture below fails
            sys.stdout.write(json.dumps(output, ensure_ascii=False))
            sys.stdout.flush()
        record(document)
    except BaseException as exc:  # the host must never see a hook failure
        _note_error(type(exc).__name__)
    return 0


def record(document):
    """Spool one event and wake the observer; a prompt only marks activity, so it wakes nothing."""
    if document is None:
        return
    _spool(document)
    if document['event'] != 'UserPromptSubmit':
        _start_observer()
