"""Reading a data collection as it was at an earlier Delta commit.

These tests write a **real** Delta table with three commits rather than mocking
``pl.scan_delta``. Time travel is exactly the behaviour a mock would assume
instead of verify: the interesting question is whether version N genuinely
returns version N's rows, which only the Delta log can answer.

The cache-key test is the one that matters most. Salting on the *latest*
aggregation version alone — which is what the code did before time travel
existed — files a historical read under the same key as a live one. The next
caller asking for current data is then handed the historical frame, with no
error and no visible symptom beyond wrong numbers.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.deltatables_utils import _create_delta_scan, _generate_cache_keys

WF = "68d0f0f0f0f0f0f0f0f0f0f0"
DC = "646b0f3c1e4a2d7f8e5b9003"


@pytest.fixture()
def delta_table(tmp_path):
    """A Delta table with three commits, mirroring the iris_versioned demo.

    v0: 100 rows, 2 species. v1: 150 rows, 3 species. v2: 150 rows, one
    species' measurements recalibrated — the same shape as v1 but different
    values, so a test can tell v1 and v2 apart by content and not just by count.
    """
    path = str(tmp_path / "iris_delta")

    v0 = pl.DataFrame(
        {
            "petal_length": [1.4] * 50 + [4.5] * 50,
            "species": ["setosa"] * 50 + ["versicolor"] * 50,
        }
    )
    v0.write_delta(path)

    v1 = pl.DataFrame({"petal_length": [5.5] * 50, "species": ["virginica"] * 50})
    v1.write_delta(path, mode="append")

    # Recalibration: rewrite the whole table with virginica petals shortened.
    v2 = pl.concat(
        [
            v0,
            pl.DataFrame({"petal_length": [4.9] * 50, "species": ["virginica"] * 50}),
        ]
    )
    v2.write_delta(path, mode="overwrite")

    return path


def test_each_commit_returns_its_own_rows(delta_table):
    """The baseline claim: version N is version N, not 'latest'."""
    assert _create_delta_scan(delta_table, "table", 0).collect().height == 100
    assert _create_delta_scan(delta_table, "table", 1).collect().height == 150
    assert _create_delta_scan(delta_table, "table", 2).collect().height == 150


def test_none_means_latest(delta_table):
    """Every existing caller passes nothing and must keep reading current data."""
    latest = _create_delta_scan(delta_table, "table").collect()
    pinned = _create_delta_scan(delta_table, "table", 2).collect()

    assert latest.height == 150
    assert latest.equals(pinned)


def test_commits_with_equal_row_counts_are_still_distinguishable(delta_table):
    """v1 and v2 both have 150 rows; only the values differ.

    A row-count check alone would pass while serving the wrong data, which is
    precisely the failure mode of a cache key that ignores the version.
    """
    v1 = _create_delta_scan(delta_table, "table", 1).collect()
    v2 = _create_delta_scan(delta_table, "table", 2).collect()

    virginica = pl.col("species") == "virginica"
    assert v1.filter(virginica)["petal_length"].max() == 5.5
    assert v2.filter(virginica)["petal_length"].max() == 4.9


def test_travelling_past_the_end_raises(delta_table):
    """An out-of-range version must fail, not silently fall back to latest."""
    with pytest.raises(Exception):
        _create_delta_scan(delta_table, "table", 99).collect()


def test_parquet_collections_refuse_to_time_travel(tmp_path):
    """MultiQC is plain parquet: no commit log, so no honest answer exists."""
    path = str(tmp_path / "mqc")
    pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "mqc.parquet")

    with pytest.raises(ValueError, match="no commit log"):
        _create_delta_scan(path, "MultiQC", 0)


# ── Cache keys ──────────────────────────────────────────────────────────────


def _key(*, version_salt):
    base, _, _ = _generate_cache_keys(WF, DC, False, None, None, False, version_salt=version_salt)
    return base


def test_historical_and_live_reads_use_different_keys():
    """The blocker this feature had to clear before it could ship.

    Salting only on the latest aggregation version gives a pinned read of an
    old commit the *same* key as a live read, so whichever runs first poisons
    the other.
    """
    live = _key(version_salt="3")
    historical = _key(version_salt="3_dv0")

    assert live != historical


def test_each_pinned_version_gets_its_own_key():
    keys = {_key(version_salt=f"3_dv{v}") for v in (0, 1, 2)}
    assert len(keys) == 3


def test_pinning_the_newest_commit_is_not_the_live_key():
    """Equal data today, different data after the next ingest.

    Pinning v2 when v2 is newest returns the same rows as an unpinned read, so
    sharing a key looks harmless. It is not: the next commit makes the live key
    mean v3 while the pinned reader still wants v2.
    """
    assert _key(version_salt="3") != _key(version_salt="3_dv2")


def test_unpinned_key_is_unchanged():
    """No existing deployment's cache is invalidated by adding time travel."""
    assert _key(version_salt="3") == f"{WF}_{DC}_base_v3"
