"""A join deleted and re-created under its name serves its new table, not cached scans.

The re-created join keeps its table id (``stable_join_result_id``) and its
aggregation counter starts again at 1, so a scan cached for the first table
(``_base_delta_scan``, keyed by location and version) answered for the second:
its parquet files were gone, and every option list of a dashboard filter on the
joined table failed with a 500. Two guards, each pinned below: deleting or
writing a table drops every cache of its id, and the cache keys carry the
identity of the table's record, which a re-creation renews (another API worker,
which never saw the invalidation, then misses instead of reading dead files).
"""

from __future__ import annotations

import shutil

import polars as pl
import pytest
from bson import ObjectId

from depictio.api import cache as api_cache
from depictio.api.v1 import db as api_db
from depictio.api.v1 import deltatables_utils
from depictio.api.v1.endpoints.datacollections_endpoints import table_manage
from depictio.api.v1.endpoints.deltatables_endpoints import routes as dt_routes


@pytest.fixture()
def reads(env, monkeypatch):
    """``GET /deltatables/unique_values`` over the env's tables, caches live."""
    monkeypatch.setattr(dt_routes, "projects_collection", env.projects)
    monkeypatch.setattr(dt_routes, "deltatables_collection", env.db["deltatables"])
    monkeypatch.setattr(api_db, "deltatables_collection", env.db["deltatables"])
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.dashboards_endpoints.routes.check_project_permission",
        lambda *a, **k: True,
    )
    real_scan = deltatables_utils._create_delta_scan

    def local_scan(file_id, dc_type=None, delta_version=None):
        return real_scan(str(env.root / file_id.rstrip("/").rsplit("/", 1)[-1]), None, None)

    monkeypatch.setattr(deltatables_utils, "_create_delta_scan", local_scan)
    monkeypatch.setattr(deltatables_utils, "_BASE_SCAN_CACHE", {})
    monkeypatch.setattr(deltatables_utils, "_DELTA_SCHEMA_CACHE", {})
    monkeypatch.setattr(api_cache, "_cache", None)

    def unique(dc_id: str, column: str) -> list[str]:
        return dt_routes.get_unique_values(
            ObjectId(dc_id), column, limit=1000, filter_expr=None, current_user="u"
        )["values"]

    return unique


def _delete_and_recreate(env, joined: str, **fields) -> None:
    assert env.request(env.owner, "DELETE", "/penguins").status_code == 200
    shutil.rmtree(env.where(joined))  # what the route's S3 cleanup does
    assert env.create_ok(name="penguins", **fields)["data_collection_id"] == joined


def test_the_filter_options_of_a_re_created_join_are_read_again(env, reads, monkeypatch):
    # Writes invalidate for real here (the env records them otherwise).
    monkeypatch.setattr(
        table_manage,
        "_invalidate_table_caches_for_dc",
        lambda dc_id: deltatables_utils.invalidate_data_collection_cache(dc_id),
    )
    joined = env.create_ok(name="penguins")["data_collection_id"]
    assert reads(joined, "species") == ["Adelie", "Chinstrap", "Gentoo"]

    _delete_and_recreate(env, joined, how="inner")

    assert reads(joined, "species") == ["Adelie", "Chinstrap", "Gentoo"]
    assert reads(joined, "island") == ["Biscoe", "Dream", "Torgersen"]


def test_a_worker_that_missed_the_invalidation_reads_the_new_table(env, reads, monkeypatch):
    """No invalidation reaches this process: only the cache keys tell the tables apart."""
    monkeypatch.setattr(deltatables_utils, "invalidate_data_collection_cache", lambda _id: 0)
    joined = env.create_ok(name="penguins")["data_collection_id"]
    assert reads(joined, "species") == ["Adelie", "Chinstrap", "Gentoo"]
    first_salt = deltatables_utils._get_aggregation_version(joined)

    # Only Gentoo this time: a stale option list would still offer the others.
    env.write(env.demo, env.read(env.demo).filter(pl.col("species") == "Gentoo"))
    _delete_and_recreate(env, joined)

    assert deltatables_utils._get_aggregation_version(joined) != first_salt
    assert reads(joined, "species") == ["Gentoo"]


def test_deleting_a_join_drops_every_cache_of_its_table(env, reads):
    joined = env.create_ok(name="penguins")["data_collection_id"]
    reads(joined, "species")
    assert any(joined in key[0] for key in deltatables_utils._BASE_SCAN_CACHE)
    assert any(key[0] == joined for key in deltatables_utils._DELTA_SCHEMA_CACHE)

    assert env.request(env.owner, "DELETE", "/penguins").status_code == 200

    assert not any(joined in key[0] for key in deltatables_utils._BASE_SCAN_CACHE)
    assert not any(key[0] == joined for key in deltatables_utils._DELTA_SCHEMA_CACHE)
    assert not [k for k in api_cache.get_cache()._memory_cache if joined in k]


def test_invalidating_one_table_keeps_the_others_cached(env, reads):
    joined = env.create_ok(name="penguins")["data_collection_id"]
    env.db["deltatables"].insert_one(
        {
            "data_collection_id": ObjectId(env.demo),
            "delta_table_location": f"s3://bucket/{env.demo}",
            "aggregation": [{"aggregation_version": 1}],
        }
    )
    reads(joined, "species")
    reads(env.demo, "species")

    deltatables_utils.invalidate_data_collection_cache(joined)

    assert any(env.demo in key[0] for key in deltatables_utils._BASE_SCAN_CACHE)
    assert any(key[0] == env.demo for key in deltatables_utils._DELTA_SCHEMA_CACHE)


def test_deleting_the_joined_table_forgets_its_history_and_its_caches(env, reads):
    """Manage data, Delete on the joined table: a later join starts a history of its own."""
    import asyncio

    from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils

    joined = env.create_ok(name="penguins")["data_collection_id"]
    reads(joined, "species")

    asyncio.run(dc_utils._delete_data_collection_by_id(joined, env.owner))

    assert env.aggregations(joined) == []
    shutil.rmtree(env.where(joined))
    assert env.create_ok(name="penguins")["data_collection_id"] == joined
    assert [a["aggregation_version"] for a in env.aggregations(joined)] == [1]
    assert reads(joined, "species") == ["Adelie", "Chinstrap", "Gentoo"]
