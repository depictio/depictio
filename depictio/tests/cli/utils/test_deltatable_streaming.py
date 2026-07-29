"""Streaming (``sink_delta``) vs collect-then-write equivalence + the opt-in gate.

The streaming ingest path exists to avoid materialising the whole concatenated
dataset in RAM (the OOM source on large ingests). Because the "aggregation" is a
vertical concat plus a literal timestamp column — no groupby — streaming must be
*semantically identical* to collecting and writing. These tests pin that, and
pin the flag defaulting to off, so the fast path can never silently change the
data it writes.

Local Delta paths are used throughout: no S3/MinIO or running stack required.
"""

import polars as pl
import pytest

from depictio.cli.cli.utils.deltatables import (
    aggregate_lazy_dataframes,
    build_aggregated_lazyframe,
    delta_table_stats,
    streaming_write_enabled,
)
from depictio.models.models.s3 import PolarsStorageOptions

_SORT_COLS = ["id", "grp", "value"]

# ``sink_delta`` landed well after polars 1.19 (the version some dev venvs still
# pin), which is precisely why the ingest path treats streaming as opt-in with a
# collect+write fallback. Skip rather than fail where the API is absent.
_HAS_SINK_DELTA = hasattr(pl.LazyFrame, "sink_delta")
requires_sink_delta = pytest.mark.skipif(
    not _HAS_SINK_DELTA, reason="polars build has no LazyFrame.sink_delta"
)


def _storage_options() -> PolarsStorageOptions:
    """Dummy credentials — local Delta paths ignore them, but the model requires them."""
    return PolarsStorageOptions(
        endpoint_url="http://localhost:9000",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def _shards(tmp_path, n_shards=3, rows=200):
    """Write ``n_shards`` CSVs with overlapping schemas; return their LazyFrames."""
    lfs = []
    for s in range(n_shards):
        path = tmp_path / f"shard_{s}.csv"
        pl.DataFrame(
            {
                "id": [f"I{s}_{i}" for i in range(rows)],
                "grp": ["a", "b"] * (rows // 2),
                "value": [float(s * rows + i) for i in range(rows)],
            }
        ).write_csv(path)
        lfs.append(pl.scan_csv(path))
    return lfs


@requires_sink_delta
def test_streaming_and_collect_write_identical_data(tmp_path):
    """sink_delta and collect+write_delta must produce the same table."""
    lfs = _shards(tmp_path)
    stream_dest = str(tmp_path / "delta_stream")
    collect_dest = str(tmp_path / "delta_collect")

    build_aggregated_lazyframe(lfs).sink_delta(
        stream_dest, mode="overwrite", delta_write_options={"schema_mode": "overwrite"}
    )
    aggregate_lazy_dataframes(_shards(tmp_path)).write_delta(
        collect_dest, mode="overwrite", delta_write_options={"schema_mode": "overwrite"}
    )

    streamed = pl.read_delta(stream_dest).sort(_SORT_COLS)
    collected = pl.read_delta(collect_dest).sort(_SORT_COLS)

    assert streamed.height == collected.height
    assert set(streamed.columns) == set(collected.columns)
    # aggregation_time is a wall-clock literal stamped per call, so compare the data.
    assert streamed.select(_SORT_COLS).equals(collected.select(_SORT_COLS))


def test_aggregated_lazyframe_stamps_aggregation_time(tmp_path):
    lf = build_aggregated_lazyframe(_shards(tmp_path, n_shards=2))
    assert "aggregation_time" in lf.collect_schema().names()


@requires_sink_delta
def test_delta_table_stats_reports_size_and_rows(tmp_path):
    """Stats come from the transaction log — no materialized frame needed."""
    dest = str(tmp_path / "delta_stats")
    lfs = _shards(tmp_path, n_shards=2, rows=100)
    build_aggregated_lazyframe(lfs).sink_delta(
        dest, mode="overwrite", delta_write_options={"schema_mode": "overwrite"}
    )
    size_bytes, num_records = delta_table_stats(dest, _storage_options())
    assert num_records == 200
    assert size_bytes > 0


def test_delta_table_stats_missing_table_is_not_fatal(tmp_path):
    assert delta_table_stats(str(tmp_path / "nope"), _storage_options()) == (0, 0)


@pytest.mark.parametrize(
    "env_value,expected",
    [(None, False), ("", False), ("false", False), ("0", False), ("true", True), ("1", True)],
)
def test_streaming_flag_defaults_off_and_reads_env(monkeypatch, env_value, expected):
    monkeypatch.delenv("DEPICTIO_INGEST_STREAMING_WRITE", raising=False)
    if env_value is not None:
        monkeypatch.setenv("DEPICTIO_INGEST_STREAMING_WRITE", env_value)
    assert streaming_write_enabled({}) is expected


def test_streaming_flag_honours_command_parameter(monkeypatch):
    monkeypatch.delenv("DEPICTIO_INGEST_STREAMING_WRITE", raising=False)
    assert streaming_write_enabled({"streaming": True}) is True
