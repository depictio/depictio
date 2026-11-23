"""Server-side search over a filter's option list.

An entity picker listed the first 1,000 of 4,333 families and a value beyond
the cut could not be reached at all (#1418). ``GET /deltatables/unique_values``
now takes ``search``: a literal, case-insensitive substring match applied on
the column cast to string, before the unique and its limit, so any value can be
found no matter where the limit cut the list. The cache key carries the search,
so one query's answer is never served for another's.
"""

from __future__ import annotations

import mongomock
import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.deltatables_endpoints import routes

# "a.c" against "abc" pins the literal semantics: a regex "." would catch both.
FAMILIES = ["Brassicaceae", "brassica.oleracea", "a.c", "abc", "SOLANACEAE", "poaceae", None]


@pytest.fixture
def env(tmp_path, monkeypatch):
    dc_id = ObjectId()
    table = tmp_path / "dt"
    pl.DataFrame({"family": FAMILIES, "reads": [1, 2, 3, 4, 5, 6, 7]}).write_delta(str(table))

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
    return dc_id


def _call(dc_id, column, **kw):
    return routes.get_unique_values(
        dc_id,
        column,
        current_user="u",
        **{"limit": 1000, "filter_expr": None, "search": None, "order_by": None, **kw},
    )


def test_a_search_returns_only_the_matching_values(env):
    got = _call(env, "family", search="brassica")
    assert got == {
        "column": "family",
        "values": ["Brassicaceae", "brassica.oleracea"],
        "truncated": False,
    }


def test_a_search_matches_regardless_of_case(env):
    # The query's case and the data's case must both be ignored.
    assert _call(env, "family", search="SOLANACEAE")["values"] == ["SOLANACEAE"]
    assert _call(env, "family", search="solanaceae")["values"] == ["SOLANACEAE"]


def test_a_search_is_literal_not_a_regex(env):
    # A "." matches a dot only: a regex "a.c" would also catch "abc".
    assert _call(env, "family", search="a.c")["values"] == ["a.c"]


def test_a_search_casts_the_column_to_string(env):
    # A numeric column is searched as its string form, like the options list
    # the client shows.
    assert _call(env, "reads", search="1")["values"] == ["1"]


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_search_is_no_search(env, blank):
    got = _call(env, "family", search=blank)
    # Every family, the null is not a value.
    assert len(got["values"]) == 6
    assert got["truncated"] is False


def test_a_searched_list_cut_at_its_limit_says_so(env):
    # "ss" catches Brassicaceae and brassica.oleracea: two matches, a limit of
    # one cuts it.
    cut = _call(env, "family", search="ss", limit=1)
    assert cut["truncated"] is True
    assert len(cut["values"]) == 1
    # Served from the cache, the flag is still there.
    assert _call(env, "family", search="ss", limit=1)["truncated"] is True
    # Both matches fit: nothing is cut.
    both = _call(env, "family", search="ss", limit=2)
    assert both["values"] == ["Brassicaceae", "brassica.oleracea"]
    assert both["truncated"] is False


def test_a_search_applies_with_an_order_by_companion(env):
    got = _call(env, "family", search="ss", order_by="reads")
    assert got["values"] == ["Brassicaceae", "brassica.oleracea"]
    assert got["truncated"] is False


def test_a_cache_hit_of_one_search_is_not_served_for_another(env):
    first = _call(env, "family", search="solan")
    second = _call(env, "family", search="poa")
    assert first["values"] == ["SOLANACEAE"]
    # The second search must not be handed the first one's cached answer.
    assert second["values"] == ["poaceae"]
    # The unsearched list has its own entry too.
    assert len(_call(env, "family")["values"]) == 6
