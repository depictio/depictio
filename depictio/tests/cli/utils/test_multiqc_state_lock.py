"""MultiQC keeps its state in the module (``multiqc.report``), so every reader
in one process must take the same lock.

Without it, two Celery tasks of a threaded worker (``depictio local``: two
threads) parse two reports at once: one report's files leak into the other's,
and ``multiqc.report.search_files`` can spin forever, which pins both worker
threads and leaves every later ingestion "running".
"""

import threading

import pytest

pytest.importorskip("multiqc")

from depictio.cli.cli.utils import multiqc_processor  # noqa: E402
from depictio.cli.cli.utils.multiqc_state import MULTIQC_STATE_LOCK  # noqa: E402


def _held_elsewhere() -> bool:
    """Whether another thread holds the lock (it cannot be taken from here)."""
    taken: list[bool] = []

    def probe() -> None:
        got = MULTIQC_STATE_LOCK.acquire(blocking=False)
        if got:
            MULTIQC_STATE_LOCK.release()
        taken.append(got)

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    return not taken[0]


def test_every_reader_of_multiqc_state_shares_one_lock():
    # The API's readers: not on the CLI-only install.
    pytest.importorskip("fastapi")
    from depictio.api.v1.endpoints.projects_endpoints import from_run
    from depictio.api.v1.services.multiqc import figures

    assert figures._multiqc_lock is MULTIQC_STATE_LOCK
    assert from_run._MULTIQC_READ is MULTIQC_STATE_LOCK


@pytest.mark.parametrize(
    "call",
    [
        lambda: multiqc_processor.extract_multiqc_metadata("/x/multiqc.parquet"),
        lambda: multiqc_processor.validate_multiqc_parquet("/x/multiqc.parquet"),
    ],
    ids=["extract_multiqc_metadata", "validate_multiqc_parquet"],
)
def test_parsing_a_report_holds_the_lock(monkeypatch, call):
    import multiqc

    seen: list[bool] = []
    monkeypatch.setattr(multiqc, "reset", lambda: seen.append(_held_elsewhere()))
    monkeypatch.setattr(multiqc, "parse_logs", lambda *_a, **_k: seen.append(_held_elsewhere()))
    monkeypatch.setattr(multiqc, "list_samples", lambda: ["S1"])
    monkeypatch.setattr(multiqc, "list_modules", lambda: ["fastqc"])
    monkeypatch.setattr(
        multiqc_processor, "_parquet_has_general_stats", lambda _p: False, raising=False
    )
    try:
        call()
    except Exception:  # noqa: BLE001 - the stubbed report is not a real one
        pass
    assert seen and all(seen)


def test_in_the_parent_process_the_initializer_keeps_the_lock():
    from depictio.cli.cli.utils import multiqc_state

    before = multiqc_state.MULTIQC_STATE_LOCK
    multiqc_state.fresh_lock_in_child()
    assert multiqc_state.MULTIQC_STATE_LOCK is before


def test_a_pool_child_gets_a_lock_of_its_own(monkeypatch):
    """A child forked while another thread held the lock would inherit it held."""
    from depictio.cli.cli.utils import multiqc_state

    monkeypatch.setattr(multiqc_state, "MULTIQC_STATE_LOCK", multiqc_state.MULTIQC_STATE_LOCK)
    held = threading.Event()
    release = threading.Event()

    def _hold():
        with multiqc_state.MULTIQC_STATE_LOCK:
            held.set()
            release.wait(5)

    holder = threading.Thread(target=_hold)
    holder.start()
    held.wait(5)
    try:
        import multiprocessing

        monkeypatch.setattr(multiprocessing, "parent_process", lambda: object())
        multiqc_state.fresh_lock_in_child()
        # What a child of the pool would then do: read under a lock it can take.
        assert multiqc_state.MULTIQC_STATE_LOCK.acquire(blocking=False)
        multiqc_state.MULTIQC_STATE_LOCK.release()
    finally:
        release.set()
        holder.join()
