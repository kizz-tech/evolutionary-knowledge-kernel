"""Bounded cooperative locks; closing the descriptor releases ownership.

Never remove a busy lock file or expire its owner. A timeout describes only
acquisition of this lock, not the outcome or total duration of a request.
"""
import errno
import fcntl
import time

from ..model import StoreError

LOCK_WAIT_SECONDS = 30.0
DIAGNOSTIC_LOCK_WAIT_SECONDS = 0.25
POLL_SECONDS = 0.05


class LockBusy(StoreError):
    def __init__(self, kind, waited_ms):
        self.lock_kind = kind
        self.waited_ms = waited_ms
        super().__init__(
            f'{kind} lock is busy after {waited_ms} ms; publication is unconfirmed '
            'by this attempt. Retry the identical request and idempotency key. '
            'Do not remove the lock file.')


def acquire_lock(descriptor, *, kind):
    timeout = (DIAGNOSTIC_LOCK_WAIT_SECONDS if kind == 'diagnostics'
               else LOCK_WAIT_SECONDS)
    started = time.monotonic()
    deadline = started + timeout
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
                raise
        now = time.monotonic()
        if now >= deadline:
            raise LockBusy(kind, round((now - started) * 1000))
        time.sleep(min(POLL_SECONDS, deadline - now))
