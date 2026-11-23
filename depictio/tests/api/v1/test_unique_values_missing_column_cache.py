"""``GET /deltatables/unique_values`` caches "column not in this DC".

A viewer probing a column the DC lacks used to re-open the Delta table on S3
for every request. The negative answer is now cached (salted by aggregation
version, like the positive path), so repeats are answered from the cache.
"""

from __future__ import annotations

import inspect

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.deltatables_endpoints import routes


@pytest.fixture
def env(tmp_path, monkeypatch):
    dc_id = ObjectId()
    table = tmp_path / "dt"
    pl.DataFrame(
        {"sample": ["b", "a", "a"], "reads": [1, 2, 3], "tag": ["x", None, "y"]}
    ).write_delta(str(table))

    db = mongomock.MongoClient().db
    db["projects"].insert_one(
        {
            "_id": ObjectId(),
            "workflows": [{"data_collections": [{"_id": dc_id, "config": {"type": "table"}}]}],
        }
    )
    db["deltatables"].insert_one({"data_collection_id": dc_id, "delta_table_location": str(table)})
    monkeypatch.setattr(routes, "projects_collection", db["projects"])
    monkeypatch.setattr(routes, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(routes, "polars_s3_config", {})
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.dashboards_endpoints.routes.check_project_permission",
        lambda *a, **k: True,
    )
    # A fresh version salt per test isolates the process-wide cache.
    salt = str(ObjectId())
    monkeypatch.setattr(
        "depictio.api.v1.deltatables_utils._get_aggregation_version", lambda _dc: salt
    )

    scans: list[str] = []
    real_scan = pl.scan_delta

    def counting_scan(*args, **kwargs):
        scans.append(args[0])
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(routes.pl, "scan_delta", counting_scan)
    return dc_id, scans


def _call(dc_id, column, **kw):
    return routes.get_unique_values(
        dc_id, column, current_user="u", **{"limit": 1000, "filter_expr": None, **kw}
    )


def test_present_column_returns_sorted_values(env):
    dc_id, _ = env
    assert _call(dc_id, "sample") == {"column": "sample", "values": ["a", "b"], "truncated": False}


@pytest.mark.parametrize("order_by", [None, "reads"])
def test_a_capped_list_says_it_was_cut(env, order_by):
    # An entity picker read the first 1,000 of 4,333 families as the whole
    # table and opened its logo on another family than the one picked (#1418).
    dc_id, _ = env
    kw = {"order_by": order_by}
    assert _call(dc_id, "sample", limit=2, **kw)["truncated"] is False  # exactly 2 values
    cut = _call(dc_id, "sample", limit=1, **kw)
    assert cut["truncated"] is True and len(cut["values"]) == 1
    # A null is not a value: it neither fills the list nor marks it cut.
    tags = _call(dc_id, "tag", limit=2, **kw)
    assert tags["values"] == ["x", "y"] and tags["truncated"] is False
    # Served from the cache, the flag is still there.
    assert _call(dc_id, "sample", limit=1, **kw)["truncated"] is True


def test_missing_column_404_is_cached(env):
    dc_id, scans = env
    for _ in range(3):
        with pytest.raises(HTTPException) as exc:
            _call(dc_id, "nope")
        assert exc.value.status_code == 404
        assert "Column 'nope' not found" in exc.value.detail
    assert len(scans) == 1, "the Delta table should be opened once, then the miss is cached"

    # The negative entry does not depend on limit / filter_expr.
    with pytest.raises(HTTPException):
        _call(dc_id, "nope", limit=5)
    assert len(scans) == 1


def test_endpoint_runs_in_the_thread_pool():
    # Blocking Mongo/S3/Polars work in an `async def` stalls the event loop, so
    # ~20 option lists requested by one dashboard load queued behind each other.
    assert not inspect.iscoroutinefunction(routes.get_unique_values)


def test_other_columns_reuse_the_open_table(env):
    dc_id, scans = env
    assert _call(dc_id, "sample")["values"] == ["a", "b"]
    assert _call(dc_id, "reads")["values"] == ["1", "2", "3"]
    assert len(scans) == 1, "one base scan per table version, shared by every column"
