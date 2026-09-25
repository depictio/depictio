"""``GET /deltatables/unique_values`` caches "column not in this DC".

A viewer probing a column the DC lacks used to re-open the Delta table on S3
for every request. The negative answer is now cached (salted by aggregation
version, like the positive path), so repeats are answered from the cache.
"""

from __future__ import annotations

import asyncio

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
    pl.DataFrame({"sample": ["b", "a", "a"], "reads": [1, 2, 3]}).write_delta(str(table))

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
    return asyncio.run(
        routes.get_unique_values(
            dc_id, column, current_user="u", **{"limit": 1000, "filter_expr": None, **kw}
        )
    )


def test_present_column_returns_sorted_values(env):
    dc_id, _ = env
    assert _call(dc_id, "sample") == {"column": "sample", "values": ["a", "b"]}


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
