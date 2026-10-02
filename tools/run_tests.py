#!/usr/bin/env python3
"""Run the EKK verification suite in parallel, isolated from the owner's EKK state.

Each test module runs in its own process with temporary EKK homes and without
the host markers that attribute callers (CODEX_HOME, CLAUDECODE), so a run never
writes to the owner's operation journal and does not depend on the agent that
starts it. The original starter tests, the historical replay, the method-transfer
harness and the field-use tests run alongside.

Accepted failures, if any, are listed exactly. A run fails on any other failure
and when a listed failure starts passing, so the list cannot go stale. Logs and timings go to
work/test-runs/ (ignored by Git).

    .venv/bin/python tools/run_tests.py                       # everything
    .venv/bin/python tools/run_tests.py -k diagnostics store  # selected modules only
    .venv/bin/python tools/run_tests.py --jobs 1              # serial, for comparison
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / 'work' / 'test-runs'
TIMEOUT = 3600

# Exact names of failures accepted for now; empty means the whole suite must pass.
KNOWN_FAILURES = frozenset()
# Modules that assert wall-clock bounds; they run alone after the parallel part.
EXCLUSIVE = frozenset({'test_lock_contention', 'test_operation_journal'})
CHECKS = {
    'starter': ['-m', 'unittest', 'discover', '-s', 'examples/starter/ekk-blueprint/ekk/tests', '-p', 'test_files.py'],
    'method-transfer': ['-m', 'unittest', 'discover', '-s', 'research/studies/human-shared-method-transfer',
                        '-p', 'test_harness.py'],
    'field-use': ['-m', 'unittest', 'discover', '-s', 'research/studies/field-use', '-p', 'test_*.py'],
    'replay': ['research/replay.py'],
}
FAILURE = re.compile(r'^(?:ERROR|FAIL): \S+ \((.+)\)$', re.M)
RAN = re.compile(r'^Ran (\d+) tests? in', re.M)


def child_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith('EKK_')}
    for marker in ('CODEX_HOME', 'CLAUDECODE'):
        env.pop(marker, None)
    return env


def run_job(name, argv, base_env, logs):
    with tempfile.TemporaryDirectory(prefix='ekk-test-') as home:
        env = dict(base_env, EKK_DATA_HOME=home + '/data', EKK_CONFIG_HOME=home + '/config',
                   EKK_CACHE_HOME=home + '/cache')
        started = time.monotonic()
        try:
            proc = subprocess.run([sys.executable, *argv], cwd=ROOT, env=env, capture_output=True,
                                  text=True, timeout=TIMEOUT)
            output, code = proc.stdout + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = f'{exc.stdout or ""}{exc.stderr or ""}\ntimed out after {TIMEOUT}s', -1
        seconds = time.monotonic() - started
    (logs / f'{name}.log').write_text(output)
    ran = RAN.search(output)
    failed = set(FAILURE.findall(output))
    if code and not failed:
        failed = {f'{name} (exit {code}, see {name}.log)'}
    return {'name': name, 'seconds': round(seconds, 1), 'tests': int(ran.group(1)) if ran else 0,
            'failed': sorted(failed)}


def owner_journal():
    sys.path.insert(0, str(ROOT / 'src'))
    try:
        from ekk.adapters.local_profile import data_home
        return data_home().expanduser() / 'operations' / 'operations.jsonl'
    except Exception:
        return None


def unattributed_rows(journal, since):
    """Rows the suite could have written: tests run without host markers, so they are unknown."""
    if journal is None or not journal.is_file():
        return []
    rows = []
    for line in journal.read_text(errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (row.get('started_at') or '') >= since and row.get('caller_profile') == 'unknown':
            rows.append(row)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('-j', '--jobs', type=int, default=os.cpu_count() or 4)
    parser.add_argument('-k', '--select', nargs='+', metavar='TEXT',
                        help='Run only test modules whose name contains one of these strings (no extra checks)')
    args = parser.parse_args(argv)

    modules = sorted(p.name for p in (ROOT / 'tests').glob('test_*.py'))
    if args.select:
        modules = [m for m in modules if any(s in m for s in args.select)]
    jobs = {m[:-3]: ['-m', 'unittest', 'discover', '-s', 'tests', '-p', m] for m in modules}
    if not args.select:
        jobs.update(CHECKS)
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    logs = RUNS / stamp
    logs.mkdir()
    timings_path = RUNS / 'timings.json'
    try:
        previous = json.loads(timings_path.read_text())
    except (OSError, ValueError):
        previous = {}
    # Longest first keeps the slowest module from starting last.
    order = sorted(jobs, key=lambda n: -previous.get(n, (ROOT / 'tests' / (n + '.py')).stat().st_size / 1000
                                                     if (ROOT / 'tests' / (n + '.py')).exists() else 0))
    journal = owner_journal()
    since = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    started = time.monotonic()
    env = child_environment()
    results = []

    def report(result):
        results.append(result)
        mark = 'FAIL' if set(result['failed']) - KNOWN_FAILURES else 'ok'
        print(f"{mark:4} {result['name']:<40} {result['tests']:>4} tests {result['seconds']:>7.1f}s", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(run_job, name, jobs[name], env, logs) for name in order if name not in EXCLUSIVE]
        for future in concurrent.futures.as_completed(futures):
            report(future.result())
    for name in order:
        if name in EXCLUSIVE:
            report(run_job(name, jobs[name], env, logs))
    wall = time.monotonic() - started

    failed = {f for r in results for f in r['failed']}
    selected_known = {f for f in KNOWN_FAILURES if f.split('.')[0] in jobs}
    new = sorted(failed - KNOWN_FAILURES)
    fixed = sorted(selected_known - failed)
    leaked = unattributed_rows(journal, since)
    previous.update({r['name']: r['seconds'] for r in results})
    timings_path.write_text(json.dumps(previous, indent=1, sort_keys=True))
    summary = {'started': since, 'wall_seconds': round(wall, 1), 'jobs': args.jobs,
               'tests': sum(r['tests'] for r in results), 'results': sorted(results, key=lambda r: r['name']),
               'new_failures': new, 'known_failures_now_passing': fixed, 'owner_journal_rows': len(leaked)}
    (logs / 'summary.json').write_text(json.dumps(summary, indent=1))

    print(f"\n{summary['tests']} tests in {len(results)} jobs, {wall:.0f}s wall with {args.jobs} workers; logs in {logs.relative_to(ROOT)}")
    print('slowest: ' + ', '.join(f"{r['name']} {r['seconds']:.0f}s" for r in sorted(results, key=lambda r: -r['seconds'])[:5]))
    if selected_known & failed:
        print(f'known failures ({len(selected_known & failed)}):')
        for name in sorted(selected_known & failed):
            print('  ' + name)
    for name in new:
        print('NEW FAILURE ' + name)
    for name in fixed:
        print('NOW PASSING (remove from KNOWN_FAILURES) ' + name)
    if leaked:
        print(f'OWNER JOURNAL: {len(leaked)} unattributed rows appeared during the run; a test may bypass isolation '
              '(or an unregistered agent used EKK meanwhile):')
        for row in leaked[:10]:
            print(f"  {row.get('started_at')} {row.get('operation')} {row.get('result')}")
    ok = not new and not fixed and not leaked
    print('result: ' + ('OK' if ok else 'FAILED'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
