"""Parallel MultiQC parsing: the opt-in gate, ordering, and failure isolation.

``multiqc.parse_logs`` is ~90-99% of MultiQC ingestion wall-clock and is
independent per file, so it is parsed across processes (MultiQC keeps
module-global state, so threads are not an option). These tests pin the
behaviour that matters without needing MultiQC installed: the feature stays off
unless asked for, results keep input order, and one bad report cannot take down
the batch.
"""

import pytest

from depictio.cli.cli.utils import multiqc_processor as mp

_ENV = "DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS"


@pytest.mark.parametrize(
    "env_value,expected",
    [(None, 1), ("", 1), ("1", 1), ("4", 4), ("0", 1), ("-3", 1), ("garbage", 1)],
)
def test_worker_count_defaults_to_serial(monkeypatch, env_value, expected):
    monkeypatch.delenv(_ENV, raising=False)
    if env_value is not None:
        monkeypatch.setenv(_ENV, env_value)
    assert mp.multiqc_parse_workers() == expected


def test_is_parseable_rejects_non_parquet(tmp_path):
    p = tmp_path / "report.txt"
    p.write_text("nope")
    assert mp._is_parseable_multiqc_file(str(p)) is False


def test_is_parseable_rejects_missing_file(tmp_path):
    assert mp._is_parseable_multiqc_file(str(tmp_path / "gone.parquet")) is False


def test_is_parseable_accepts_existing_parquet(tmp_path):
    p = tmp_path / "multiqc.parquet"
    p.write_bytes(b"")
    assert mp._is_parseable_multiqc_file(str(p)) is True


def test_serial_parse_preserves_order_and_isolates_failures(monkeypatch):
    """One unparseable report yields None; the rest still come back, in order."""
    monkeypatch.delenv(_ENV, raising=False)

    def fake_worker(path: str):
        if "bad" in path:
            raise ValueError("corrupt report")
        return {"samples": [path], "modules": [], "multiqc_version": "1.0"}

    monkeypatch.setattr(mp, "_parse_multiqc_worker", fake_worker)
    paths = ["a.parquet", "bad.parquet", "c.parquet"]
    result = mp._parse_multiqc_files(paths)

    assert [p for p, _ in result] == paths  # order preserved
    assert result[1][1] is None  # the bad one degraded, not raised
    assert result[0][1]["samples"] == ["a.parquet"]
    assert result[2][1]["samples"] == ["c.parquet"]


def test_single_file_never_spawns_a_pool(monkeypatch):
    """A pool for one file would cost more than it saves."""
    monkeypatch.setenv(_ENV, "8")
    monkeypatch.setattr(mp, "_parse_multiqc_worker", lambda p: {"samples": [p]})

    def explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("ProcessPoolExecutor should not be used for a single file")

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", explode)
    assert mp._parse_multiqc_files(["only.parquet"])[0][1]["samples"] == ["only.parquet"]


def test_empty_input_returns_empty(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    assert mp._parse_multiqc_files([]) == []
