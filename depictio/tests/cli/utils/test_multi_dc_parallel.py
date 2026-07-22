"""Parallel multi-DC ingestion: the opt-in gate, ordering, and failure isolation.

Data collections are ingested independently, so they can overlap; but the printed
summary must stay identical to the sequential path. These tests pin the two
properties that guarantee that: results come back in *input* order regardless of
completion order, and a raising DC is captured rather than aborting the batch.
"""

import threading

import pytest

from depictio.cli.cli.utils import process as proc

_ENV = "DEPICTIO_INGEST_DC_WORKERS"


class FakeDC:
    """Minimal stand-in for a data collection (only the tag is read here)."""

    def __init__(self, tag: str, optional: bool = False):
        self.data_collection_tag = tag
        self.optional = optional


@pytest.mark.parametrize(
    "env_value,n_dcs,expected",
    [
        (None, 8, 1),  # unset -> sequential (new features are opt-in)
        ("", 8, 1),
        ("1", 8, 1),
        ("3", 8, 3),
        ("99", 8, 4),  # clamped to _MAX_DC_WORKERS
        ("4", 2, 2),  # never more workers than data collections
        ("0", 8, 1),
        ("-2", 8, 1),
        ("garbage", 8, 1),
    ],
)
def test_worker_count_gate(monkeypatch, env_value, n_dcs, expected):
    monkeypatch.delenv(_ENV, raising=False)
    if env_value is not None:
        monkeypatch.setenv(_ENV, env_value)
    assert proc.data_collection_workers(n_dcs) == expected


def _collect(monkeypatch, dcs, side_effect):
    monkeypatch.setattr(
        proc,
        "process_single_data_collection",
        lambda workflow, data_collection, **kw: side_effect(data_collection),
    )
    return proc._ingest_data_collections(
        workflow=object(), data_collections=dcs, CLI_config=object(), command_parameters={}
    )


def test_sequential_by_default(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    dcs = [FakeDC("a"), FakeDC("b")]
    out = _collect(monkeypatch, dcs, lambda dc: {"success": True, "tag": dc.data_collection_tag})
    assert [d.data_collection_tag for d, _, _ in out] == ["a", "b"]
    assert [r["tag"] for _, r, _ in out] == ["a", "b"]
    assert all(err is None for _, _, err in out)


def test_parallel_preserves_input_order_despite_completion_order(monkeypatch):
    """The first DC finishes last; results must still come back a, b, c."""
    monkeypatch.setenv(_ENV, "3")
    started = threading.Barrier(3, timeout=10)
    release_first = threading.Event()

    def side_effect(dc):
        started.wait()  # guarantee all three are genuinely in flight at once
        if dc.data_collection_tag == "a":
            release_first.wait(timeout=10)
        else:
            release_first.set()
        return {"success": True, "tag": dc.data_collection_tag}

    dcs = [FakeDC("a"), FakeDC("b"), FakeDC("c")]
    out = _collect(monkeypatch, dcs, side_effect)
    assert [d.data_collection_tag for d, _, _ in out] == ["a", "b", "c"]
    assert [r["tag"] for _, r, _ in out] == ["a", "b", "c"]


def test_runs_concurrently_when_enabled(monkeypatch):
    """Without overlap the pool would be pointless — the barrier proves it."""
    monkeypatch.setenv(_ENV, "3")
    barrier = threading.Barrier(3, timeout=5)

    def side_effect(dc):
        barrier.wait()  # deadlocks (TimeoutError) if execution is serialised
        return {"success": True}

    out = _collect(monkeypatch, [FakeDC("a"), FakeDC("b"), FakeDC("c")], side_effect)
    assert all(err is None for _, _, err in out)


def test_failure_is_captured_not_raised(monkeypatch):
    """One bad DC must not abandon the others mid-flight."""
    monkeypatch.setenv(_ENV, "2")
    boom = ValueError("scan exploded")

    def side_effect(dc):
        if dc.data_collection_tag == "bad":
            raise boom
        return {"success": True, "tag": dc.data_collection_tag}

    out = _collect(monkeypatch, [FakeDC("ok1"), FakeDC("bad"), FakeDC("ok2")], side_effect)
    assert [d.data_collection_tag for d, _, _ in out] == ["ok1", "bad", "ok2"]
    assert out[1][1] is None and out[1][2] is boom
    assert out[0][2] is None and out[2][2] is None


def test_captured_exception_keeps_traceback(monkeypatch):
    """The reporting pass re-raises and logs with exc_info — needs a traceback."""
    monkeypatch.delenv(_ENV, raising=False)

    def side_effect(dc):
        raise RuntimeError("nope")

    _, _, err = _collect(monkeypatch, [FakeDC("a")], side_effect)[0]
    assert err.__traceback__ is not None


def test_empty_input(monkeypatch):
    monkeypatch.setenv(_ENV, "4")
    assert (
        proc._ingest_data_collections(
            workflow=object(), data_collections=[], CLI_config=object(), command_parameters={}
        )
        == []
    )
