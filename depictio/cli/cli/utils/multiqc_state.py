"""The one lock around MultiQC's module state in this process.

MultiQC keeps the report it reads in the module (``multiqc.report``):
``multiqc.reset()`` / ``multiqc.parse_logs()`` / ``multiqc.list_*`` /
``multiqc.get_plot()`` all act on it. Two threads using it at once mix two
reports, and ``multiqc.report.search_files`` can loop forever. A threaded
Celery worker (``depictio local`` runs two threads) and the API both read
reports from several threads, so every reader takes this lock, from the reset
to the last read of the resident report. Reentrant: a holder may call another
reader.
"""

import functools
import threading
from typing import Callable, TypeVar

MULTIQC_STATE_LOCK = threading.RLock()

_F = TypeVar("_F", bound=Callable)


def holds_multiqc_state(func: _F) -> _F:
    """Run ``func`` under :data:`MULTIQC_STATE_LOCK`: it resets or reads MultiQC's state."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with MULTIQC_STATE_LOCK:
            return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def fresh_lock_in_child() -> None:
    """A process pool's initializer: give the child a lock of its own.

    A child forked while another thread held the lock would otherwise inherit
    it held, by a thread that does not exist there, and block on it forever.
    The child's MultiQC state is its own, so its own lock is the right one.
    """
    import multiprocessing

    if multiprocessing.parent_process() is None:
        return  # not a child process (a thread pool in its place): the lock stays
    global MULTIQC_STATE_LOCK
    MULTIQC_STATE_LOCK = threading.RLock()
