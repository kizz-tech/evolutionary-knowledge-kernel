"""Run preserved temporal semantics in an explicit historical process."""
from pathlib import Path
import os
import subprocess
import sys


def main():
    archive = Path(__file__).resolve().parents[1] / 'archive/runtime-0.4'
    env = dict(os.environ, PYTHONPATH=str(archive / 'src'))
    return subprocess.run([sys.executable, str(archive / 'replay.py')], cwd=archive, env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
