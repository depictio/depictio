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


# ── The local mirror (DEPICTIO_USE_LOCAL_FILES) ─────────────────────────────


@pytest.fixture()
def local_mirror(delta_table, tmp_path, monkeypatch):
    """Turn the local mirror on, with a mirror built the way production builds it.

    ``cache_delta_table_from_s3`` copies the *latest* state into a fresh Delta
    table, so the mirror has a single commit whatever the source's history.
    Returns the list of paths the mirror was asked for.
    """
    from depictio.api.v1 import deltatables_utils

    mirror_path = str(tmp_path / "mirror")
    calls: list[str] = []

    def fake_cache(s3_path, _storage_options):
        calls.append(s3_path)
        pl.scan_delta(s3_path).collect().write_delta(mirror_path, mode="overwrite")
        return mirror_path

    monkeypatch.setattr(deltatables_utils, "USE_LOCAL_FILES", True)
    monkeypatch.setattr(deltatables_utils, "cache_delta_table_from_s3", fake_cache)
    return calls


def test_a_pinned_read_bypasses_the_local_mirror(delta_table, local_mirror):
    """The mirror's version 0 is today's data; a pin must read the source.

    Before the fix the pin was passed to the mirror, which answered version 0
    with the newest 150 rows: current data under a historical label, no error.
    """
    v0 = _create_delta_scan(delta_table, "table", 0).collect()
    v1 = _create_delta_scan(delta_table, "table", 1).collect()

    assert v0.height == 100, "version 0 of the source, not version 0 of the mirror"
    assert v1.filter(pl.col("species") == "virginica")["petal_length"].max() == 5.5
    assert local_mirror == [], "a pinned read must never take the mirror path"


def test_a_live_read_still_uses_the_local_mirror(delta_table, local_mirror):
    """The mirror is a performance switch for current data, and stays one."""
    latest = _create_delta_scan(delta_table, "table").collect()

    assert local_mirror == [delta_table]
    assert latest.height == 150


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


# ── the column schema has to travel with the rows ───────────────────────────


@pytest.fixture()
def widening_delta_table(tmp_path):
    """A Delta table that gains a column in its second commit.

    The row-level fixture above keeps one schema throughout, which cannot
    distinguish a schema read at the pinned commit from one read at the newest.
    """
    path = str(tmp_path / "widening_delta")

    pl.DataFrame({"petal_length": [1.4, 4.5], "species": ["setosa", "versicolor"]}).write_delta(
        path, mode="overwrite"
    )
    pl.DataFrame(
        {
            "petal_length": [1.4, 4.5],
            "species": ["setosa", "versicolor"],
            "petal_width": [0.2, 1.5],
        }
    ).write_delta(path, mode="overwrite", delta_write_options={"schema_mode": "overwrite"})
    return path


def _schema_at(path, version=None):
    from depictio.api.v1.deltatables_utils import schema_deltatable_lite

    return schema_deltatable_lite(
        workflow_id=WF,
        data_collection_id=DC,
        init_data={DC: {"delta_location": path, "dc_type": "table", "size_bytes": 0}},
        delta_version=version,
    )


def test_schema_peek_honours_the_pin(widening_delta_table):
    """The table render endpoint builds its column defs from this peek.

    Read at the newest commit while the rows come from a pinned one, the grid
    gets a header for `petal_width` with no values under it, and can be asked to
    sort on a column the pinned data does not have. The endpoint passed the pin
    through a merge that had removed the parameter, so every pinned table render
    raised instead — a 500 no test covered, because this peek had no test at all.
    """
    assert "petal_width" not in _schema_at(widening_delta_table, 0)
    assert "petal_width" in _schema_at(widening_delta_table, 1)


def test_schema_peek_defaults_to_the_newest_commit(widening_delta_table):
    """No pin means today's schema, which is the ordinary read."""
    assert "petal_width" in _schema_at(widening_delta_table)


def test_schema_peek_degrades_rather_than_raising(widening_delta_table):
    """A version that does not exist returns {} and lets the caller carry on.

    The peek is an optimisation over loading rows to learn their names; failing
    it must not fail the request, and the endpoint already falls back.
    """
    assert _schema_at(widening_delta_table, 99) == {}
