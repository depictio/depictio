"""``jbrowse_calls``: the pages of calls the genome browser's stepper walks.

Storage and Mongo are faked, as in ``test_jbrowse_render_endpoint``; this pins
the order, the paging, which filters and which commit each read uses, and the
permission check.
"""

from __future__ import annotations

from types import SimpleNamespace

import polars as pl
import pytest
from fastapi import HTTPException

from depictio.api.v1 import deltatables_utils
from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.api.v1.endpoints.dashboards_endpoints.data_versions import DataVersionPins

DASHBOARD_ID = "646b0f3c1e4a2d7f8e5b8d01"
CALLS_DC = "646b0f3c1e4a2d7f8e5b8d03"

FUSIONS = pl.DataFrame(
    {
        "chrom": ["chr1", "chr2", "chr3", "chr4", "chr5"],
        "start": [100, 200, 300, 400, 500],
        "end": [150, 250, 350, 450, 550],
        "chrom_b": ["chr9", "chr9", "chr9", "chr9", "chr9"],
        "pos_b": [10, 20, 30, 40, 50],
        "gene": ["A", "B", "C", "D", None],
        "reads": [5, 50, 20, 1, 30],
    }
)

LOCUS_FROM = {
    "data_collection_tag": "fusions",
    "chrom_column": "chrom",
    "start_column": "start",
    "end_column": "end",
    "padding": 10,
    "sort_by": "reads",
    "descending": True,
    "label_column": "gene",
    "mate": {"chrom_column": "chrom_b", "start_column": "pos_b"},
}


def _component(**locus_from) -> dict:
    return {
        "index": "jb",
        "component_type": "jbrowse",
        "dc_id": "646b0f3c1e4a2d7f8e5b8d02",
        "locus_from": {**LOCUS_FROM, **locus_from},
    }


@pytest.fixture
def env(monkeypatch):
    seen: dict = {"component": _component(), "allowed": True, "dc_exists": True}

    def find_one(*a, **k):
        return {
            "dashboard_id": DASHBOARD_ID,
            "project_id": "646b0f3c1e4a2d7f8e5b8d00",
            "stored_metadata": [seen["component"]],
        }

    monkeypatch.setattr(routes, "dashboards_collection", SimpleNamespace(find_one=find_one))
    monkeypatch.setattr(routes, "check_project_permission", lambda *a, **k: seen["allowed"])

    def link(**kw):
        seen["filters"] = kw["filters"]
        return kw["filters"]

    monkeypatch.setattr(routes, "_resolve_link_filters_cached", link)
    monkeypatch.setattr(
        routes,
        "_find_project_dc",
        lambda pid, tag: ("646b0f3c1e4a2d7f8e5b8d04", CALLS_DC) if seen["dc_exists"] else None,
    )
    monkeypatch.setattr(
        routes,
        "_data_pins",
        lambda request, dash: DataVersionPins(
            pins={CALLS_DC: 4} if request.get("as_of_version") else {}
        ),
    )

    def count(**kw):
        seen["count_version"] = kw.get("delta_version")
        seen["count_metadata"] = kw.get("metadata")
        return FUSIONS.height

    monkeypatch.setattr(deltatables_utils, "count_deltatable_lite", count)
    monkeypatch.setattr(
        routes,
        "_cached_row_count",
        lambda wf, dc, metadata, init, fn, delta_version=None: fn(
            workflow_id=wf, data_collection_id=dc, metadata=metadata, delta_version=delta_version
        ),
    )

    def sorted_page(**kw):
        seen["sorted"] = kw
        frame = FUSIONS.sort(kw["sort_by"], descending=kw["descending"], nulls_last=True)
        start, limit = kw["page"]
        return frame.slice(start, limit)

    def natural_page(wf, dc, metadata, init, columns, start, limit, delta_version=None):
        seen["natural"] = (start, limit, delta_version)
        return FUSIONS.slice(start, limit)

    monkeypatch.setattr(deltatables_utils, "load_sorted_deltatable_lite", sorted_page)
    monkeypatch.setattr(routes, "_load_natural_page", natural_page)
    return seen


def _calls(body: dict | None = None, user=None) -> dict:
    return routes.jbrowse_calls_endpoint(
        DASHBOARD_ID,
        "jb",
        body or {},
        current_user=user or SimpleNamespace(id="u1"),
        access_token=None,
    )


def test_calls_come_ordered_by_sort_by_with_both_sides_and_labels(env):
    out = _calls()
    assert out["total"] == 5
    assert [r["locus"] for r in out["rows"]] == [
        "chr2:190-260",
        "chr5:490-560",
        "chr3:290-360",
        "chr1:90-160",
        "chr4:390-460",
    ]
    first = out["rows"][0]
    assert (first["locus"], first["mate_locus"], first["label"]) == (
        "chr2:190-260",
        "chr9:10-30",
        "B",
    )
    assert (first["chrom"], first["start"], first["end"], first["score"]) == ("chr2", 200, 250, 50)
    assert first["source"] == "fusions" and first["extra"] == {}
    assert out["rows"][1]["label"] is None


def test_ascending_order(env):
    env["component"] = _component(descending=False)
    out = _calls()
    assert out["rows"][0]["locus"] == "chr4:390-460"


def test_paging_slices_the_ordered_calls(env):
    first = _calls({"start": 0, "limit": 2})
    second = _calls({"start": 2, "limit": 2})
    assert [r["locus"] for r in first["rows"]] == ["chr2:190-260", "chr5:490-560"]
    assert [r["locus"] for r in second["rows"]] == ["chr3:290-360", "chr1:90-160"]
    assert second["total"] == 5
    assert env["sorted"]["page"] == (2, 2)


def test_a_page_past_the_end_is_empty(env):
    assert _calls({"start": 50}) == {"total": 5, "rows": []}


def test_limit_is_capped_at_200(env):
    _calls({"limit": 10_000})
    assert env["sorted"]["page"] == (0, 200)


def test_without_a_sort_the_collections_own_order_is_used(env):
    env["component"] = _component(sort_by=None)
    out = _calls({"limit": 2})
    assert env["natural"] == (0, 2, None)
    assert [r["locus"] for r in out["rows"]] == ["chr1:90-160", "chr2:190-260"]


def test_the_filters_reach_the_count_and_the_page(env):
    filters = [{"index": "f1", "column_name": "gene", "value": ["A", "B"]}]
    _calls({"filters": filters})
    assert env["filters"] == filters
    assert env["count_metadata"] and env["sorted"]["metadata"] == env["count_metadata"]


def test_a_pinned_request_reads_the_pinned_commit(env):
    _calls({"as_of_version": "v1"})
    assert env["count_version"] == 4
    assert env["sorted"]["delta_version"] == 4
    _calls()
    assert env["count_version"] is None
    assert env["sorted"]["delta_version"] is None


def test_a_viewer_without_access_gets_403(env):
    env["allowed"] = False
    with pytest.raises(HTTPException) as exc:
        _calls()
    assert exc.value.status_code == 403


def test_a_component_without_locus_from_is_400(env):
    env["component"] = {k: v for k, v in _component().items() if k != "locus_from"}
    with pytest.raises(HTTPException) as exc:
        _calls()
    assert exc.value.status_code == 400


def test_a_missing_collection_is_400(env):
    env["dc_exists"] = False
    with pytest.raises(HTTPException) as exc:
        _calls()
    assert exc.value.status_code == 400


def test_a_read_failure_is_a_generic_500(env, monkeypatch):
    def boom(**kw):
        raise RuntimeError("s3://secret-bucket/key unreadable")

    monkeypatch.setattr(deltatables_utils, "load_sorted_deltatable_lite", boom)
    with pytest.raises(HTTPException) as exc:
        _calls()
    assert exc.value.status_code == 500
    assert "secret" not in exc.value.detail


def test_a_malformed_page_request_is_400(env):
    with pytest.raises(HTTPException) as exc:
        _calls({"start": "x"})
    assert exc.value.status_code == 400
