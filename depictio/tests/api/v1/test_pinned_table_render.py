"""A pinned table, map or row count reads the pinned commit — every read of it.

``render_table`` once pinned only its schema peek: the total, the sorted page
and the natural page all read current data, so a grid "as of v1" showed today's
rows under v1's headers. ``map_data`` read nothing pinned at all. Neither failed;
both answered 200 with plausible numbers, which is the one outcome time travel
cannot have.

These tests drive the endpoints against a **real** local Delta table, with only
Mongo and the link resolver stubbed. Its two commits have the same row count and
different values in every row, so a test that only counted rows could not pass
by reading the wrong commit — and a filter on ``species`` gives the two commits
different totals, so a total read at the wrong commit is visible too.

Each read is also run live after the pinned one (and the other way round) in
the same cache, because a pinned read filed under the live key is the other
half of the same bug: the *next* caller gets the wrong commit.
"""

from __future__ import annotations

import polars as pl
import pytest
from bson import ObjectId
from fastapi import HTTPException, Response

from depictio.api.v1 import deltatables_utils
from depictio.api.v1.endpoints.dashboards_endpoints import routes, version_store

DASHBOARD_ID = "507f1f77bcf86cd799439011"
OTHER_DASHBOARD_ID = "507f1f77bcf86cd799439099"
PROJECT_ID = "507f1f77bcf86cd799439012"
WF_ID = "507f1f77bcf86cd799439013"
DC_ID = "646b0f3c1e4a2d7f8e5b9101"
TABLE_ID = "table-1"
MAP_ID = "map-1"

SAMPLES = ["s1", "s2", "s3", "s4"]
# v0 → v1 is a recalibration: the same four samples, every measurement changed
# and one sample re-classified. Same height, different content.
V0 = pl.DataFrame(
    {
        "sample": SAMPLES,
        "species": ["setosa", "setosa", "versicolor", "virginica"],
        "petal_length": [1.4, 1.3, 4.5, 5.5],
    }
)
V1 = pl.DataFrame(
    {
        "sample": SAMPLES,
        "species": ["setosa", "versicolor", "versicolor", "virginica"],
        "petal_length": [1.5, 4.4, 4.6, 4.9],
    }
)
SETOSA = [
    {
        "index": "species-filter",
        "column_name": "species",
        "interactive_component_type": "MultiSelect",
        "value": ["setosa"],
    }
]


def _by_sample(frame: pl.DataFrame) -> dict[str, float]:
    return dict(zip(frame["sample"].to_list(), frame["petal_length"].to_list()))


class _DictCache:
    """Stands in for the Redis-backed ``SimpleCache``, so every run starts cold."""

    def __init__(self):
        self.store: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data
        return True

    def exists(self, key):
        return key in self.store

    def delete_pattern(self, pattern):
        doomed = [k for k in self.store if pattern in k]
        for k in doomed:
            del self.store[k]
        return len(doomed)


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    """A two-commit Delta table on disk, a dashboard over it, and a cold cache.

    Returns the cache stub so a test can look at the keys the reads filed.
    """
    from depictio.api import cache as cache_module

    path = str(tmp_path / "iris_delta")
    V0.write_delta(path)
    V1.write_delta(path, mode="overwrite")

    dc_config = {"delta_location": path, "type": "table", "size_bytes": 0}
    dashboard = {
        "dashboard_id": DASHBOARD_ID,
        "project_id": PROJECT_ID,
        "is_main_tab": True,
        "stored_metadata": [
            {
                "index": TABLE_ID,
                "component_type": "table",
                "wf_id": WF_ID,
                "dc_id": DC_ID,
                "dc_config": dc_config,
            },
            {
                "index": MAP_ID,
                "component_type": "map",
                "wf_id": WF_ID,
                "dc_id": DC_ID,
                "map_type": "scatter_map",
                "dc_config": dc_config,
            },
        ],
    }
    versions = {
        "v-own": {
            "version_id": "v-own",
            "family_id": DASHBOARD_ID,
            "data_collections": [{"dc_id": DC_ID, "version_kind": "delta", "delta_version": 0}],
        },
        "v-foreign": {
            "version_id": "v-foreign",
            "family_id": OTHER_DASHBOARD_ID,
            "data_collections": [{"dc_id": DC_ID, "version_kind": "delta", "delta_version": 0}],
        },
    }

    stub = _DictCache()
    monkeypatch.setattr(cache_module, "get_cache", lambda: stub)
    # A fixed latest aggregation version: no Mongo, and every key carries one.
    monkeypatch.setattr(deltatables_utils, "_get_aggregation_version", lambda _dc: "7")
    monkeypatch.setattr(deltatables_utils, "polars_s3_config", {})
    monkeypatch.setattr(
        routes,
        "dashboards_collection",
        type("C", (), {"find_one": lambda _self, *a, **k: dashboard})(),
    )
    monkeypatch.setattr(routes, "check_project_permission", lambda *a, **k: True)
    monkeypatch.setattr(routes, "_resolve_link_filters_cached", lambda **kw: kw["filters"])
    monkeypatch.setattr(version_store, "get_version", lambda vid: versions.get(vid))

    deltatables_utils.clear_memory_cache()
    deltatables_utils._DELTA_SCHEMA_CACHE.clear()
    yield stub
    deltatables_utils.clear_memory_cache()
    deltatables_utils._DELTA_SCHEMA_CACHE.clear()


def _table(**body) -> dict:
    return routes.render_table_endpoint(
        DASHBOARD_ID, TABLE_ID, body, Response(), current_user=None, access_token=None
    )


def _map_data(**body) -> dict:
    return routes.map_data_endpoint(
        DASHBOARD_ID, MAP_ID, {"filters": [], **body}, current_user=None, access_token=None
    )


def _rows(result: dict) -> pl.DataFrame:
    return pl.DataFrame(result["rows"])


PINNED = {"data_versions": {DC_ID: 0}}


# ── render_table ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pinned_first", [True, False], ids=["pinned-first", "live-first"])
def test_a_pinned_page_is_the_pinned_commit(cache, pinned_first):
    """The natural-order page: ``_load_natural_page``'s scan."""
    if pinned_first:
        pinned, live = _table(**PINNED), _table()
    else:
        live, pinned = _table(), _table(**PINNED)

    assert _by_sample(_rows(pinned)) == _by_sample(V0)
    assert _by_sample(_rows(live)) == _by_sample(V1), "a pinned read must not poison the live one"


@pytest.mark.parametrize("lazy", [False, True], ids=["memoised-sort", "lazy-sort"])
@pytest.mark.parametrize("pinned_first", [True, False], ids=["pinned-first", "live-first"])
def test_a_pinned_sorted_page_is_the_pinned_commit(cache, monkeypatch, lazy, pinned_first):
    """``load_sorted_deltatable_lite`` has two paths and a memo; all three are pinned.

    The memo is keyed on the sort, so a live sorted frame memoised first would be
    sliced for the pinned request unless the key carries the pin.
    """
    if lazy:
        # Every frame is "too big to memoise": the lazy sort + slice path.
        monkeypatch.setattr(deltatables_utils, "MEMORY_PER_ITEM_MAX_BYTES", 0)
    sort = {"sort_by": "petal_length", "sort_dir": "asc"}

    if pinned_first:
        pinned, live = _table(**sort, **PINNED), _table(**sort)
    else:
        live, pinned = _table(**sort), _table(**sort, **PINNED)

    assert pinned["sort_by"] == "petal_length"
    assert _rows(pinned)["petal_length"].to_list() == sorted(V0["petal_length"].to_list())
    assert _rows(live)["petal_length"].to_list() == sorted(V1["petal_length"].to_list())


@pytest.mark.parametrize("pinned_first", [True, False], ids=["pinned-first", "live-first"])
def test_a_pinned_total_counts_the_pinned_commit(cache, pinned_first):
    """Two setosa at v0, one at v1: the total is visibly per commit.

    The total is memoised per block, so the second read of each pair is the one
    that would be handed the first one's number if the key ignored the pin.
    """
    if pinned_first:
        pinned, live = _table(filters=SETOSA, **PINNED), _table(filters=SETOSA)
    else:
        live, pinned = _table(filters=SETOSA), _table(filters=SETOSA, **PINNED)

    assert pinned["total"] == 2
    assert _by_sample(_rows(pinned)) == {"s1": 1.4, "s2": 1.3}
    assert live["total"] == 1
    assert _by_sample(_rows(live)) == {"s1": 1.5}


def test_the_live_row_count_key_is_unchanged(cache):
    """Adding pins must not invalidate a single existing deployment's cache."""
    _table()
    _table(**PINNED)

    counts = sorted(k for k in cache.store if k.startswith("rowcount_"))
    assert counts == [f"rowcount_{DC_ID}_nofilter_7", f"rowcount_{DC_ID}_nofilter_7_dv0"]


def test_the_data_version_echo_tells_live_and_pinned_apart(cache):
    """The grid purges its blocks when this changes; live and pinned must differ."""
    assert _table()["data_version"] == "7"
    assert _table(**PINNED)["data_version"] == "7_dv0"


def test_as_of_version_pins_the_table(cache):
    """The dashboard-wide grain reaches the table through the stored stamps."""
    result = _table(as_of_version="v-own", filters=SETOSA)

    assert result["total"] == 2
    assert _by_sample(_rows(result)) == {"s1": 1.4, "s2": 1.3}


def test_a_version_of_another_dashboard_is_a_400(cache):
    with pytest.raises(HTTPException) as exc:
        _table(as_of_version="v-foreign")

    assert exc.value.status_code == 400
    assert "does not belong" in exc.value.detail


def test_a_pin_that_cannot_be_honoured_fails_rather_than_serving_current_rows(cache):
    """There is no commit 99. The scan fails, and so must the fallback loader."""
    with pytest.raises(HTTPException) as exc:
        _table(data_versions={DC_ID: 99})

    assert exc.value.status_code >= 400


def test_the_natural_page_fallback_is_pinned_too(cache, monkeypatch):
    """When the scan can't be built, the row loader answers — at the same commit.

    The fallback is the path most likely to be missed: it only runs when the
    scan failed, and an unpinned fallback turns that failure into a 200 with
    today's rows.
    """
    monkeypatch.setattr(deltatables_utils, "open_deltatable_scan", lambda **kw: None)
    dc_config = routes.dashboards_collection.find_one()["stored_metadata"][0]["dc_config"]
    init_data = {DC_ID: {"delta_location": dc_config["delta_location"], "dc_type": "table"}}

    page = routes._load_natural_page(
        ObjectId(WF_ID), DC_ID, None, init_data, None, 0, 10, delta_version=0
    )

    assert _by_sample(page) == _by_sample(V0)


# ── map_data ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pinned_first", [True, False], ids=["pinned-first", "live-first"])
def test_a_pinned_map_read_is_the_pinned_commit(cache, pinned_first):
    if pinned_first:
        pinned, live = _map_data(**PINNED), _map_data()
    else:
        live, pinned = _map_data(), _map_data(**PINNED)

    assert _by_sample(_rows(pinned)) == _by_sample(V0)
    assert _by_sample(_rows(live)) == _by_sample(V1)


def test_a_truncated_pinned_map_read_counts_the_pinned_commit(cache, monkeypatch):
    """Past the cap the total comes from the count, which has to be pinned too.

    An unpinned count answers 1 (one setosa today), and ``max(1, rows)`` then
    reports "1 of 1" for a pinned read that holds two.
    """
    monkeypatch.setattr(routes, "MAP_DATA_MAX_ROWS", 1)

    result = _map_data(filters=SETOSA, **PINNED)

    assert result["truncated"] is True
    assert result["total_rows"] == 2
    assert _by_sample(_rows(result)) == {"s1": 1.4}


def test_map_data_as_of_a_foreign_version_is_a_400_not_a_422(cache):
    """A caller error, reported as one — not as "could not read this data"."""
    with pytest.raises(HTTPException) as exc:
        _map_data(as_of_version="v-foreign")

    assert exc.value.status_code == 400


# ── render_map ──────────────────────────────────────────────────────────────


def test_render_map_draws_the_pinned_commit(cache, monkeypatch):
    """Already pinned before this change; kept honest now its prologue moved."""
    from depictio.api.v1.services.map import render as map_render

    drawn: list[pl.DataFrame] = []

    def _fake_render_map(df, **_kwargs):
        drawn.append(df)
        return {"data": [], "layout": {}}, {"displayed_count": df.height}

    monkeypatch.setattr(map_render, "render_map", _fake_render_map)

    routes.render_map_endpoint(DASHBOARD_ID, MAP_ID, PINNED, current_user=None, access_token=None)
    routes.render_map_endpoint(DASHBOARD_ID, MAP_ID, {}, current_user=None, access_token=None)

    assert _by_sample(drawn[0]) == _by_sample(V0)
    assert _by_sample(drawn[1]) == _by_sample(V1)
