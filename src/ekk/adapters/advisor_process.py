"""A replaceable local advisor model, run as a separate process.

The model runtime (PyTorch, MLX, ...) lives outside the EKK environment. EKK
starts the configured command once per request, writes one JSON request to its
standard input and reads one JSON response from its standard output. Swapping
the model means swapping the command and the pinned identity in the config.

Config (private file, default ``config_home()/advisor.json``)::

    {"schema": "ekk.advisor/0.1",
     "command": ["/abs/interpreter", "/abs/script", "arg", ...],
     "model": {"id": "...", "revision": "..."},
     "timeout_seconds": 180, "max_batch": 32}

The config is refused when it is a symlink, not a regular file, not owned by
the current user, or writable by group or others: it names a program to run.

Process contract. Request::

    {"schema": "ekk.advisor-request/0.1",
     "operation": "relevance" | "triage",
     "task": "..." | null,
     "labels": {label: one-line description},
     "items": [{"id": "...", "text": "..."}]}

``labels`` carries the rubric so the process holds no EKK semantics. For
``relevance`` an item text is the candidate title, a newline and its excerpt.
Response::

    {"schema": "ekk.advisor-response/0.1",
     "model": {"id": "...", "revision": "..."},
     "results": [{"id": "...", "label": "...", "probabilities": {label: p}}],
     "distribution": "model" | "top_label_only",   (optional, default "model")
     "truncated": 0,                               (optional item count)
     "identity_verified": true | false,            (optional, default false)
     "diagnostics": {name: number}}                (optional)

Exactly one result per item; probabilities cover every label, are finite, lie
in [0, 1], sum to 1 +/- 0.01, and the label is their argmax. The model identity
must equal the configured one. That comparison alone only shows the process
repeats the config; ``identity_verified`` is true when the process itself
checked the loaded weights against that identity, and the advice carries the
flag so stored shadow output shows which kind it is.

The process gets no shell and a minimal environment (PATH, HOME,
HF_HUB_OFFLINE=1, TOKENIZERS_PARALLELISM=false). A timeout, a non-zero exit,
output over MAX_RESPONSE_BYTES (the process group is killed as soon as the
bound is passed) and malformed or incomplete output of any shape all raise
AdvisorUnavailable; standard error is discarded and never becomes result text.
"""
import json
import math
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import threading
import time

from ..application.semantic_shadow import ADVICE_SCHEMA as RELEVANCE_ADVICE_SCHEMA
from ..application.triage_shadow import ADVICE_SCHEMA as TRIAGE_ADVICE_SCHEMA, RUBRIC
from .local_profile import config_home


CONFIG_SCHEMA = 'ekk.advisor/0.1'
REQUEST_SCHEMA = 'ekk.advisor-request/0.1'
RESPONSE_SCHEMA = 'ekk.advisor-response/0.1'
CONFIG_NAME = 'advisor.json'
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_MAX_BATCH = 32
MAX_CONFIG_BYTES = 65536
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_DIAGNOSTIC_NUMBER = 1e15
DISTRIBUTIONS = ('model', 'top_label_only')
RELEVANCE_LABELS = {
    'primary': 'The candidate directly answers or governs the task.',
    'supporting': 'The candidate gives evidence or detail that helps the task.',
    'background': 'The candidate is on the same topic but is not needed for the task.',
    'irrelevant': 'The candidate does not bear on the task.',
}


class AdvisorUnavailable(RuntimeError):
    """The advisor could not give a valid answer. Carries no child output."""


class AdvisorConfigError(AdvisorUnavailable):
    """The advisor config is unsafe or invalid."""


def default_config_path():
    return config_home() / CONFIG_NAME


def _read_private(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise AdvisorConfigError('Advisor config is a symlink or unreadable') from None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise AdvisorConfigError('Advisor config must be a regular file')
        if status.st_uid != os.getuid():
            raise AdvisorConfigError('Advisor config must be owned by the current user')
        if status.st_mode & 0o022:
            raise AdvisorConfigError('Advisor config must not be group- or world-writable')
        if status.st_size > MAX_CONFIG_BYTES:
            raise AdvisorConfigError('Advisor config is too large')
        return os.read(descriptor, MAX_CONFIG_BYTES + 1)
    finally:
        os.close(descriptor)


def _identity(value, error):
    if (not isinstance(value, dict) or set(value) != {'id', 'revision'}
            or any(not isinstance(v, str) or not v or len(v) > 256 for v in value.values())):
        raise error
    return {'id': value['id'], 'revision': value['revision']}


def _config(raw):
    try:
        value = json.loads(raw)
    except ValueError:
        raise AdvisorConfigError('Advisor config is not valid JSON') from None
    allowed = {'schema', 'command', 'model', 'timeout_seconds', 'max_batch'}
    if not isinstance(value, dict) or value.get('schema') != CONFIG_SCHEMA or set(value) - allowed:
        raise AdvisorConfigError('Unsupported advisor config')
    command = value.get('command')
    if (not isinstance(command, list) or len(command) < 2
            or any(not isinstance(part, str) or not part or '\0' in part for part in command)
            or not all(os.path.isabs(part) for part in command[:2])):
        raise AdvisorConfigError('Advisor command must name an absolute interpreter and script')
    model = _identity(value.get('model'), AdvisorConfigError('Exact advisor model identity required'))
    timeout = value.get('timeout_seconds', DEFAULT_TIMEOUT_SECONDS)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise AdvisorConfigError('Invalid advisor timeout')
    max_batch = value.get('max_batch', DEFAULT_MAX_BATCH)
    if type(max_batch) is not int or not 1 <= max_batch <= 256:
        raise AdvisorConfigError('Invalid advisor batch bound')
    return {'command': list(command), 'model': model, 'timeout_seconds': float(timeout),
            'max_batch': max_batch}


def _child_environment():
    return {'PATH': os.environ.get('PATH') or '/usr/bin:/bin',
            'HOME': os.environ.get('HOME') or str(Path.home()),
            'HF_HUB_OFFLINE': '1', 'TOKENIZERS_PARALLELISM': 'false'}


def _probabilities(value, labels):
    if not isinstance(value, dict) or set(value) != set(labels):
        raise AdvisorUnavailable('Advisor output is invalid')
    result = {}
    for label in labels:
        probability = value[label]
        # The range test comes first: it is false for NaN and safe for an
        # integer too large to convert to float.
        if type(probability) not in (int, float) or not 0.0 <= probability <= 1.0:
            raise AdvisorUnavailable('Advisor output is invalid')
        result[label] = float(probability)
    if abs(sum(result.values()) - 1.0) > 0.01:
        raise AdvisorUnavailable('Advisor output is invalid')
    return result


class ProcessAdvisor:
    """SemanticAdvisor and TriageAdvisor over one configured child process."""

    def __init__(self, config_path=None):
        self.config_path = Path(config_path) if config_path is not None else default_config_path()
        self._settings = _config(_read_private(self.config_path))

    @property
    def model(self):
        return dict(self._settings['model'])

    @property
    def max_batch(self):
        return self._settings['max_batch']

    def advise(self, *, task, candidates):
        items = [{'id': row['candidate_id'],
                  'text': row['title'] + ('\n' + row['excerpt'] if row.get('excerpt') else '')}
                 for row in candidates]
        outcome = self._run('relevance', task, RELEVANCE_LABELS, items)
        return {'schema': RELEVANCE_ADVICE_SCHEMA, **outcome['extra'],
                'decisions': [{'candidate_id': item_id, **row} for item_id, row in outcome['results']]}

    def triage(self, *, items):
        sent = [{'id': row['item_id'], 'text': row['text']} for row in items]
        outcome = self._run('triage', None, RUBRIC, sent)
        return {'schema': TRIAGE_ADVICE_SCHEMA, **outcome['extra'],
                'decisions': [{'item_id': item_id, **row} for item_id, row in outcome['results']]}

    def _run(self, operation, task, labels, items):
        settings = self._settings
        if not items or len(items) > settings['max_batch']:
            raise ValueError('Advisor item count must be between 1 and ' + str(settings['max_batch']))
        request = json.dumps({'schema': REQUEST_SCHEMA, 'operation': operation, 'task': task,
                              'labels': labels, 'items': items}, ensure_ascii=False).encode()
        started = time.monotonic()
        stdout = self._exchange(request, settings)
        seconds = time.monotonic() - started
        try:
            return self._checked(stdout, settings, labels, items, seconds)
        except AdvisorUnavailable:
            raise
        except Exception:
            # No shape of child output may surface as another error type.
            raise AdvisorUnavailable('Advisor output is invalid') from None

    @staticmethod
    def _checked(stdout, settings, labels, items, seconds):
        try:
            response = json.loads(stdout)
        except (ValueError, RecursionError):
            raise AdvisorUnavailable('Advisor output is not valid JSON') from None
        if not isinstance(response, dict) or response.get('schema') != RESPONSE_SCHEMA:
            raise AdvisorUnavailable('Advisor output is invalid')
        invalid = AdvisorUnavailable('Advisor output is invalid')
        if _identity(response.get('model'), invalid) != settings['model']:
            raise AdvisorUnavailable('Advisor model identity differs from the configured one')
        distribution = response.get('distribution', 'model')
        if distribution not in DISTRIBUTIONS:
            raise invalid
        rows = response.get('results')
        if not isinstance(rows, list) or len(rows) != len(items):
            raise AdvisorUnavailable('Advisor output is incomplete')
        by_id = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'id', 'label', 'probabilities'}:
                raise invalid
            if not isinstance(row['id'], str) or row['id'] in by_id:
                raise invalid
            if not isinstance(row['label'], str) or row['label'] not in labels:
                raise invalid
            probabilities = _probabilities(row['probabilities'], labels)
            if probabilities[row['label']] != max(probabilities.values()):
                raise invalid
            by_id[row['id']] = {'label': row['label'], 'probabilities': probabilities}
        if set(by_id) != {item['id'] for item in items}:
            raise AdvisorUnavailable('Advisor output is incomplete')
        diagnostics = {'seconds': round(seconds, 3)}
        truncated = response.get('truncated', 0)
        if type(truncated) is int and 0 <= truncated <= len(items):
            diagnostics['truncated'] = truncated
        reported = response.get('diagnostics')
        if isinstance(reported, dict):
            # Numbers only: free text from the child must not travel in results.
            for name in ('load_seconds', 'inference_seconds', 'peak_rss_bytes', 'token_limit'):
                number = reported.get(name)
                if type(number) in (int, float) and 0 <= number <= MAX_DIAGNOSTIC_NUMBER:
                    diagnostics[name] = number
        return {'extra': {'model': dict(settings['model']),
                          'identity_verified': response.get('identity_verified') is True,
                          'distribution': distribution, 'diagnostics': diagnostics},
                'results': [(item['id'], by_id[item['id']]) for item in items]}

    @staticmethod
    def _exchange(request, settings):
        try:
            process = subprocess.Popen(
                settings['command'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=_child_environment(), cwd='/',
                shell=False, close_fds=True, start_new_session=True)
        except OSError:
            raise AdvisorUnavailable('Advisor process could not start') from None
        # The request is written from a thread so that a child which fills its
        # output before reading its input cannot block the exchange.
        writer = threading.Thread(target=_send, args=(process.stdin, request), daemon=True)
        deadline = time.monotonic() + settings['timeout_seconds']
        chunks, size = [], 0
        try:
            try:
                writer.start()
                selector = selectors.DefaultSelector()
            except (OSError, RuntimeError):  # no thread or descriptor left: not the child's doing, same contract
                raise AdvisorUnavailable('Advisor exchange could not start') from None
            descriptor = process.stdout.fileno()
            with selector:
                selector.register(descriptor, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(settings['command'], 0)
                    if not selector.select(remaining):
                        continue
                    chunk = os.read(descriptor, 65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise AdvisorUnavailable('Advisor output is too large')  # the handler below stops the child
                    chunks.append(chunk)
            process.wait(timeout=max(deadline - time.monotonic(), 0))
        except subprocess.TimeoutExpired:
            _stop(process)
            raise AdvisorUnavailable('Advisor process timed out') from None
        except BaseException:
            _stop(process)
            raise
        finally:
            process.stdout.close()
            if writer.is_alive():
                writer.join(timeout=1)
        if process.returncode != 0:
            raise AdvisorUnavailable('Advisor process failed')
        return b''.join(chunks)


def _send(stream, request):
    try:
        stream.write(request)
        stream.close()
    except (OSError, ValueError):
        pass


def _stop(process):
    # The child leads its own session, so its helpers end with it. Its output
    # is not read again: whatever it still holds is dropped with the pipe.
    if process.returncode is not None:
        return  # already reaped; its pid may belong to someone else by now
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()
    try:
        process.wait(timeout=5)
    except Exception:
        pass


def load_advisor(config_path=None):
    """Return the configured advisor, or None when no config exists.

    An existing but unsafe or invalid config raises AdvisorConfigError.
    """
    path = Path(config_path) if config_path is not None else default_config_path()
    if not os.path.lexists(path):
        return None
    return ProcessAdvisor(path)
