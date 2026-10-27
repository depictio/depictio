"""``render_jbrowse`` under a pinned data version.

A version preview (or a dataset pin) sends ``as_of_version`` / ``data_versions``
with the render. The browser's manifest, the filter applied to it and the
``locus_from`` collection must all be read at their pinned commits, or a past
view shows today's tracks under a past label. Storage and Mongo are faked; this
pins which commit each read asks for.
"""

from __future__ import annotations

from types import SimpleNamespace

import polars as pl
import pytest
from fastapi import HTTPException

from depictio.api.v1 import deltatables_utils
from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.api.v1.endpoints.dashboards_endpoints.data_versions import DataVersionPins
from depictio.api.v1.services.jbrowse import render, tracks

DASHBOARD_ID = "646b0f3c1e4a2d7f8e5b8d01"
TRACKS_DC = "646b0f3c1e4a2d7f8e5b8d02"
PEAKS_DC = "646b0f3c1e4a2d7f8e5b8d03"

COMPONENT = {
    "index": "jb",
    "component_type": "jbrowse",
    "dc_id": TRACKS_DC,
    "locus_from": {
        "data_collection_tag": "peaks",
        "chrom_column": "chrom",
        "start_column": "start",
        "end_column": "end",
        "padding": 10,
    },
}
FILTERS = [{"index": "f1", "column_name": "sample", "value": ["S1"]}]


@pytest.fixture
def calls(monkeypatch):
    seen: dict[str, object] = {}

    dashboard = {
        "dashboard_id": DASHBOARD_ID,
        "project_id": "646b0f3c1e4a2d7f8e5b8d00",
        "stored_metadata": [COMPONENT],
        "category_colors": {"EFFECT": {"missense_variant": "#e8590c"}},
    }
    monkeypatch.setattr(
        routes, "dashboards_collection", SimpleNamespace(find_one=lambda *a, **k: dashboard)
    )
    monkeypatch.setattr(routes, "check_project_permission", lambda *a, **k: True)
    monkeypatch.setattr(routes, "_resolve_link_filters_cached", lambda **kw: kw["filters"])
    monkeypatch.setattr(
        routes, "_find_project_dc", lambda pid, tag: ("646b0f3c1e4a2d7f8e5b8d04", PEAKS_DC)
    )
    monkeypatch.setattr(
        routes,
        "_data_pins",
        lambda request, dash: DataVersionPins(
            pins={TRACKS_DC: 3, PEAKS_DC: 7} if request.get("as_of_version") else {}
        ),
    )
    monkeypatch.setattr(tracks, "find_tracks_dc", lambda dc_id: SimpleNamespace(dc_id=dc_id))

    def filtered(tdc, metadata, delta_version=None):
        seen["filtered"] = delta_version
        return []

    def payload(
        component,
        tdc,
        rows,
        uid,
        locus=None,
        delta_version=None,
        category_colors=None,
        anonymous=False,
        mate_locus=None,
        first_call=None,
        locus_source=None,
    ):
        seen["payload"] = delta_version
        seen["locus_source"] = locus_source
        seen["anonymous"] = anonymous
        seen["category_colors"] = category_colors
        seen["locus"] = locus
        seen["mate_locus"] = mate_locus
        seen["first_call"] = first_call
        return {}

    def load(**kw):
        seen["locus_dc"] = kw.get("delta_version")
        return seen.get("frame", pl.DataFrame({"chrom": ["chr1"], "start": [100], "end": [200]}))

    def natural_page(wf, dc, metadata, init_data, columns, start, limit, delta_version=None):
        seen["natural"] = {"dc": dc, "columns": columns, "page": (start, limit)}
        seen["natural_dc_version"] = delta_version
        return seen.get("calls", pl.DataFrame({"chrom": [], "start": [], "end": []}))

    def sorted_page(**kw):
        seen["sorted"] = kw
        return seen.get("calls", pl.DataFrame({"chrom": [], "start": [], "end": []}))

    monkeypatch.setattr(routes, "_load_natural_page", natural_page)
    monkeypatch.setattr(deltatables_utils, "load_sorted_deltatable_lite", sorted_page)
    monkeypatch.setattr(render, "filtered_track_rows", filtered)
    monkeypatch.setattr(render, "build_jbrowse_payload", payload)
    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", load)
    return seen


def _render(body: dict, user: SimpleNamespace | None = None) -> None:
    routes.render_jbrowse_endpoint(
        DASHBOARD_ID,
        "jb",
        body,
        current_user=user or SimpleNamespace(id="u1"),
        access_token=None,
    )


def test_every_read_follows_the_pin(calls):
    _render({"filters": FILTERS, "as_of_version": "v1"})
    assert calls["filtered"] == 3
    assert calls["payload"] == 3
    assert calls["locus_dc"] == 7
    assert calls["locus"] == "chr1:90-210"


def test_a_live_render_reads_current_data(calls):
    _render({"filters": FILTERS})
    assert calls["filtered"] is None
    assert calls["payload"] is None
    assert calls["locus_dc"] is None


def test_an_anonymous_viewer_is_passed_to_the_payload(calls):
    _render({"filters": FILTERS}, SimpleNamespace(id="anon", is_anonymous=True))
    assert calls["anonymous"] is True
    _render({"filters": FILTERS})
    assert calls["anonymous"] is False


def test_the_anonymous_owner_in_single_user_mode_is_not_a_stranger(calls, monkeypatch):
    monkeypatch.setattr(routes.settings, "auth", SimpleNamespace(is_single_user_mode=True))
    _render({"filters": FILTERS}, SimpleNamespace(id="anon", is_anonymous=True))
    assert calls["anonymous"] is False


def test_the_dashboard_category_colors_reach_the_payload(calls):
    _render({"filters": FILTERS})
    assert calls["category_colors"] == {"EFFECT": {"missense_variant": "#e8590c"}}


def _frame(**cols) -> pl.DataFrame:
    return pl.DataFrame(cols)


def test_one_row_frames_that_row(calls):
    calls["frame"] = _frame(chrom=["chr1"], start=[500], end=[800])
    _render({"filters": FILTERS})
    assert calls["locus"] == "chr1:490-810"


def test_several_rows_frame_their_span(calls):
    calls["frame"] = _frame(chrom=["chr1"] * 3, start=[500, 100, 900], end=[800, 200, 1000])
    _render({"filters": FILTERS})
    assert calls["locus"] == "chr1:90-1010"


def test_rows_on_two_chromosomes_frame_the_majority_one(calls):
    calls["frame"] = _frame(
        chrom=["chr2", "chr1", "chr1"], start=[10_000, 300, 100], end=[10_100, 400, 200]
    )
    _render({"filters": FILTERS})
    assert calls["locus"] == "chr1:90-410"


def test_a_tie_between_chromosomes_keeps_the_first_seen(calls):
    calls["frame"] = _frame(chrom=["chr2", "chr1"], start=[300, 100], end=[400, 200])
    _render({"filters": FILTERS})
    assert calls["locus"] == "chr2:290-410"


def test_above_max_rows_the_view_does_not_jump(calls, monkeypatch):
    monkeypatch.setitem(COMPONENT["locus_from"], "max_rows", 2)
    calls["frame"] = _frame(chrom=["chr1"] * 3, start=[1, 2, 3], end=[4, 5, 6])
    _render({"filters": FILTERS})
    assert calls["locus"] is None


MATE = {"chrom_column": "chrom_b", "start_column": "pos_b"}


@pytest.fixture
def fusion(monkeypatch):
    """The ``locus_from`` of a fusion table: two sides, ordered by supporting reads."""
    spec = {
        **COMPONENT["locus_from"],
        "sort_by": "reads",
        "descending": True,
        "mate": MATE,
    }
    monkeypatch.setitem(COMPONENT, "locus_from", spec)
    return spec


def test_a_narrowed_view_frames_both_sides_and_skips_the_first_call(calls, fusion):
    calls["frame"] = _frame(
        chrom=["chr4"], start=[1_000], end=[1_000], chrom_b=["chr4"], pos_b=[5_000]
    )
    _render({"filters": FILTERS})
    assert calls["locus"] == "chr4:990-1010"
    assert calls["mate_locus"] == "chr4:4990-5010"
    assert calls["first_call"] is None
    assert "sorted" not in calls


def test_no_location_and_no_narrowing_opens_on_the_first_call(calls, fusion):
    calls["calls"] = _frame(
        chrom=["chr22"], start=[2_000], end=[2_100], chrom_b=["chr9"], pos_b=[8_000]
    )
    _render({"as_of_version": "v1"})
    assert calls["locus"] is None
    assert calls["first_call"] == {"locus": "chr22:1990-2110", "mate_locus": "chr9:7990-8010"}
    sort = calls["sorted"]
    assert (sort["sort_by"], sort["descending"], sort["page"]) == ("reads", True, (0, 1))
    assert sort["delta_version"] == 7
    assert set(sort["select_columns"]) >= {"chrom", "start", "end", "chrom_b", "pos_b", "reads"}


def test_the_first_call_follows_the_filters_when_they_do_not_narrow(calls, fusion, monkeypatch):
    monkeypatch.setitem(COMPONENT["locus_from"], "max_rows", 1)
    calls["frame"] = _frame(chrom=["chr1"] * 2, start=[1, 2], end=[3, 4])
    calls["calls"] = _frame(chrom=["chr1"], start=[50], end=[60], chrom_b=["chr2"], pos_b=[70])
    _render({"filters": FILTERS})
    assert calls["locus"] is None
    assert calls["first_call"]["locus"] == "chr1:40-70"


def test_without_a_sort_the_first_call_is_the_first_row_in_delta_order(calls, monkeypatch):
    calls["calls"] = _frame(chrom=["chr3"], start=[10], end=[20])
    _render({})
    assert calls["first_call"] == {"locus": "chr3:1-30", "mate_locus": None}
    assert calls["natural"]["page"] == (0, 1)
    assert "sorted" not in calls


def test_a_yaml_location_wins_over_the_first_call(calls, monkeypatch):
    monkeypatch.setitem(COMPONENT, "location", "chr5:1-100")
    _render({})
    assert calls["first_call"] is None
    assert "natural" not in calls and "sorted" not in calls


def test_an_unreadable_call_table_falls_through(calls, fusion, monkeypatch):
    def boom(**kw):
        raise RuntimeError("no such column")

    monkeypatch.setattr(deltatables_utils, "load_sorted_deltatable_lite", boom)
    _render({})
    assert calls["first_call"] is None


class TestFloatingEndpointRule:
    """The cross-tab endpoint lifts a floating browser out of the grid like a map."""

    def test_a_floating_browser_floats(self):
        assert routes._is_floating_component({"component_type": "jbrowse", "placement": "floating"})

    def test_a_grid_browser_does_not(self):
        assert not routes._is_floating_component({"component_type": "jbrowse", "placement": "grid"})
        assert not routes._is_floating_component({"component_type": "jbrowse"})

    def test_the_other_rules_are_unchanged(self):
        assert routes._is_floating_component({"component_type": "map", "placement": "floating"})
        assert routes._is_floating_component(
            {"component_type": "advanced_viz", "viz_kind": "molecule_3d", "placement": "floating"}
        )
        assert not routes._is_floating_component(
            {"component_type": "advanced_viz", "viz_kind": "volcano", "placement": "floating"}
        )
        assert not routes._is_floating_component(
            {"component_type": "table", "placement": "floating"}
        )


def test_the_locus_source_names_the_locus_from_collection(calls):
    _render({"filters": FILTERS})
    assert calls["locus_source"] == {
        "dc_id": PEAKS_DC,
        "chrom_column": "chrom",
        "start_column": "start",
        "end_column": "end",
    }


def test_the_locus_source_has_no_end_column_when_locus_from_has_none(calls, monkeypatch):
    spec = {k: v for k, v in COMPONENT["locus_from"].items() if k != "end_column"}
    monkeypatch.setitem(COMPONENT, "locus_from", spec)
    _render({"filters": FILTERS})
    assert calls["locus_source"]["end_column"] is None
    assert calls["locus_source"]["dc_id"] == PEAKS_DC


def test_there_is_no_locus_source_without_locus_from(calls, monkeypatch):
    monkeypatch.delitem(COMPONENT, "locus_from")
    _render({"filters": FILTERS})
    assert calls["locus_source"] is None


def test_there_is_no_locus_source_when_the_collection_is_not_in_the_project(calls, monkeypatch):
    monkeypatch.setattr(routes, "_find_project_dc", lambda pid, tag: None)
    _render({"filters": FILTERS})
    assert calls["locus_source"] is None


# ---------------------------------------------------------------------------
# Several sources: the region picker, the next / previous step and the density
# ---------------------------------------------------------------------------

GENES_DC = "646b0f3c1e4a2d7f8e5b8d05"
PEAKS_SPEC = {
    "name": "peaks",
    "data_collection_tag": "peaks",
    "chrom_column": "chrom",
    "start_column": "start",
    "end_column": "end",
    "padding": 10,
    "sort_by": "score",
    "descending": True,
    "label_column": "gene",
    "sample_column": "sample",
    "run_column": "run",
    "columns": ["fc"],
    "search_columns": ["gene"],
    "mate": {"chrom_column": "mchrom", "start_column": "mpos"},
}
GENES_SPEC = {
    "data_collection_tag": "genes",
    "workflow_tag": "rna",
    "chrom_column": "chromosome",
    "start_column": "pos",
    "label_column": "symbol",
    "padding": 100,
    "columns": ["fc"],
}
PEAKS = pl.DataFrame(
    {
        "chrom": ["chr1", "chr1", "chr1", "chr2", "chr3"],
        "start": [100, 150, 900, 50, 10],
        "end": [200, 260, 950, 80, 20],
        "score": [5.0, 9.0, 2.0, 7.0, 1.0],
        "gene": ["A", "B", "C", "D", "E"],
        "sample": ["S1", "S2", "S1", "S1", "S3"],
        "run": ["r1", "r2", "r1", "r1", "r2"],
        "fc": [1, 2, 3, 4, 5],
        "mchrom": ["chr9"] * 5,
        "mpos": [1000, 2000, 3000, 4000, 5000],
    }
)
GENES = pl.DataFrame(
    {"chromosome": ["1", "2"], "pos": [180, 60], "symbol": ["TP53", "BRCA"], "fc": [-1.5, 2.5]}
)
CHROM_ORDER = ["chr1", "chr2", "chr3", "chrX"]


@pytest.fixture
def multi(monkeypatch):
    seen: dict = {"reads": [], "link_dcs": [], "component_sources": [PEAKS_SPEC, GENES_SPEC]}

    def component():
        return {
            "index": "jb",
            "component_type": "jbrowse",
            "dc_id": TRACKS_DC,
            "locus_from": seen["component_sources"],
        }

    dashboard = {
        "dashboard_id": DASHBOARD_ID,
        "project_id": "646b0f3c1e4a2d7f8e5b8d00",
    }

    def find_one(*a, **k):
        return {**dashboard, "stored_metadata": [component()]}

    monkeypatch.setattr(routes, "dashboards_collection", SimpleNamespace(find_one=find_one))
    monkeypatch.setattr(routes, "check_project_permission", lambda *a, **k: True)

    def link(**kw):
        seen["link_dcs"].append(kw["target_dc_id"])
        return kw["filters"]

    monkeypatch.setattr(routes, "_resolve_link_filters_cached", link)

    def find_dc(pid, tag, workflow_tag=None):
        seen["workflow_tag"] = workflow_tag
        return {
            "peaks": ("646b0f3c1e4a2d7f8e5b8d04", PEAKS_DC),
            "genes": ("646b0f3c1e4a2d7f8e5b8d06", GENES_DC),
        }.get(tag)

    monkeypatch.setattr(routes, "_find_project_dc", find_dc)
    monkeypatch.setattr(
        routes,
        "_data_pins",
        lambda request, dash: DataVersionPins(
            pins={PEAKS_DC: 7, GENES_DC: 2} if request.get("as_of_version") else {}
        ),
    )
    monkeypatch.setattr(deltatables_utils, "_version_salt_for", lambda dc, version=None: None)

    def load(**kw):
        seen["reads"].append((str(kw["data_collection_id"]), kw.get("delta_version")))
        seen["metadata"] = kw.get("metadata")
        return {PEAKS_DC: PEAKS, GENES_DC: GENES}[str(kw["data_collection_id"])]

    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", load)
    for cache in (
        routes._JBROWSE_SOURCE_FRAMES,
        routes._JBROWSE_UNION_FRAMES,
        routes._JBROWSE_MERGED_FRAMES,
    ):
        cache.clear()
    yield seen
    for cache in (
        routes._JBROWSE_SOURCE_FRAMES,
        routes._JBROWSE_UNION_FRAMES,
        routes._JBROWSE_MERGED_FRAMES,
    ):
        cache.clear()


def _list(body: dict | None = None) -> dict:
    return routes.jbrowse_calls_endpoint(
        DASHBOARD_ID,
        "jb",
        body or {},
        current_user=SimpleNamespace(id="u1"),
        access_token=None,
    )


def _density(body: dict) -> dict:
    return routes.jbrowse_call_density_endpoint(
        DASHBOARD_ID,
        "jb",
        {
            "regions": [{"refName": "chr1", "length": 1000}, {"refName": "chr2", "length": 100}],
            **body,
        },
        current_user=SimpleNamespace(id="u1"),
        access_token=None,
    )


def _labels(out: dict) -> list:
    return [r["label"] for r in out["rows"]]


class TestSourceModel:
    def test_a_single_dict_is_one_source_named_after_its_collection(self):
        sources = render.locus_sources({"locus_from": {"data_collection_tag": "peaks"}})
        assert sources == [{"data_collection_tag": "peaks", "name": "peaks"}]

    def test_a_list_keeps_its_order_and_explicit_names(self):
        component = {"locus_from": [PEAKS_SPEC, GENES_SPEC]}
        assert [s["name"] for s in render.locus_sources(component)] == ["peaks", "genes"]
        assert render.primary_locus_source(component)["name"] == "peaks"

    def test_there_is_no_source_without_locus_from(self):
        assert render.locus_sources({}) == []
        assert render.primary_locus_source({"locus_from": None}) is None


class TestFindProjectDc:
    PROJECT = {
        "workflows": [
            {
                "_id": "w1",
                "name": "first",
                "workflow_tag": "dna",
                "data_collections": [{"_id": "d1", "data_collection_tag": "shared"}],
            },
            {
                "_id": "w2",
                "name": "second",
                "workflow_tag": "rna",
                "data_collections": [{"_id": "d2", "data_collection_tag": "shared"}],
            },
        ]
    }

    @pytest.fixture(autouse=True)
    def project(self, monkeypatch):
        monkeypatch.setattr(
            routes,
            "projects_collection",
            SimpleNamespace(find_one=lambda *a, **k: self.PROJECT),
        )

    PID = "646b0f3c1e4a2d7f8e5b8d00"

    def test_the_first_workflow_answers_without_a_workflow_tag(self):
        assert routes._find_project_dc(self.PID, "shared") == ("w1", "d1")

    def test_the_workflow_tag_picks_its_workflow(self):
        assert routes._find_project_dc(self.PID, "shared", workflow_tag="rna") == ("w2", "d2")
        assert routes._find_project_dc(self.PID, "shared", workflow_tag="second") == ("w2", "d2")

    def test_an_unknown_workflow_tag_falls_back_to_the_first_holder(self):
        assert routes._find_project_dc(self.PID, "shared", workflow_tag="x") == ("w1", "d1")

    def test_an_unknown_collection_is_none(self):
        assert routes._find_project_dc(self.PID, "nope", workflow_tag="rna") is None


class TestListing:
    def test_both_sources_are_listed_in_declared_order_with_their_own_padding(self, multi):
        out = _list({"limit": 200})
        assert out["total"] == 7
        rows = out["rows"]
        # Delta order of peaks sorted best-first, then the genes (no sort_by there).
        assert [r["source"] for r in rows] == ["peaks"] * 5 + ["genes"] * 2
        assert rows[0]["label"] == "B" and rows[0]["score"] == 9.0
        assert rows[0]["locus"] == "chr1:140-270"
        assert rows[-2]["locus"] == "1:80-280" and rows[-2]["label"] == "TP53"
        assert multi["workflow_tag"] == "rna"

    def test_the_picker_columns_sample_run_and_the_mate_come_back(self, multi):
        row = _list({"limit": 1})["rows"][0]
        assert row["extra"] == {"fc": 2}
        assert (row["sample"], row["run"]) == ("S2", "r2")
        assert (row["chrom"], row["start"], row["end"]) == ("chr1", 150, 260)
        assert row["mate_locus"] == "chr9:1990-2010"

    def test_the_mate_belongs_to_the_primary_source_only(self, multi):
        rows = _list({"limit": 200})["rows"]
        assert all(r["mate_locus"] is None for r in rows if r["source"] == "genes")
        assert all(r["mate_locus"] for r in rows if r["source"] == "peaks")

    def test_sources_restricts_the_read_and_ignores_unknown_names(self, multi):
        out = _list({"sources": ["genes", "nope"]})
        assert out["total"] == 2 and {r["source"] for r in out["rows"]} == {"genes"}
        assert multi["reads"] == [(GENES_DC, None)]
        assert _list({"sources": []}) == {"total": 0, "rows": []}
        assert _list({"sources": ["nope"]}) == {"total": 0, "rows": []}

    def test_each_source_gets_the_filters_extended_to_its_own_collection(self, multi):
        _list({"filters": FILTERS})
        assert set(multi["link_dcs"]) == {PEAKS_DC, GENES_DC}

    def test_a_pinned_request_reads_each_collection_at_its_commit(self, multi):
        _list({"as_of_version": "v1", "search": "a"})
        assert sorted(multi["reads"]) == sorted([(PEAKS_DC, 7), (GENES_DC, 2)])

    def test_sort_by_a_raw_column(self, multi):
        out = _list({"sort": {"column": "gene", "descending": False}, "sources": ["peaks"]})
        assert _labels(out) == ["A", "B", "C", "D", "E"]
        out = _list({"sort": {"column": "fc", "descending": True}, "limit": 200})
        assert [r["extra"]["fc"] for r in out["rows"]][:3] == [5, 4, 3]

    def test_sort_by_a_common_name(self, multi):
        out = _list({"sort": {"column": "start", "descending": False}, "sources": ["peaks"]})
        assert [r["start"] for r in out["rows"]] == [10, 50, 100, 150, 900]
        out = _list({"sort": {"column": "sample", "descending": False}, "sources": ["peaks"]})
        assert [r["sample"] for r in out["rows"]] == ["S1", "S1", "S1", "S2", "S3"]

    def test_an_unreadable_sort_column_is_a_400(self, multi):
        with pytest.raises(HTTPException) as exc:
            _list({"sort": {"column": "nope", "descending": True}})
        assert exc.value.status_code == 400 and "nope" in exc.value.detail
        with pytest.raises(HTTPException) as exc:
            _list({"sort": {"column": "n_samples", "descending": True}})
        assert exc.value.status_code == 400

    def test_search_is_a_case_insensitive_substring_over_label_and_search_columns(self, multi):
        assert _labels(_list({"search": "tp5"})) == ["TP53"]
        assert _labels(_list({"search": "b"}))[:2] == ["B", "BRCA"]
        assert _list({"search": "zzz"}) == {"total": 0, "rows": []}

    def test_paging_slices_the_sorted_union(self, multi):
        out = _list({"start": 5, "limit": 10, "sort": {"column": "start", "descending": False}})
        assert out["total"] == 7 and len(out["rows"]) == 2

    def test_a_repeated_listing_does_not_read_the_collections_again(self, multi):
        _list({"search": "a"})
        reads = len(multi["reads"])
        assert reads == 2
        _list({"search": "b", "start": 1})
        _list({"sort": {"column": "start", "descending": True}})
        assert len(multi["reads"]) == reads

    def test_a_missing_collection_is_skipped_and_none_is_a_400(self, multi, monkeypatch):
        monkeypatch.setattr(
            routes,
            "_find_project_dc",
            lambda pid, tag, workflow_tag=None: (
                ("646b0f3c1e4a2d7f8e5b8d04", PEAKS_DC) if tag == "peaks" else None
            ),
        )
        assert {r["source"] for r in _list()["rows"]} == {"peaks"}
        monkeypatch.setattr(routes, "_find_project_dc", lambda pid, tag, workflow_tag=None: None)
        with pytest.raises(HTTPException) as exc:
            _list()
        assert exc.value.status_code == 400

    def test_one_source_without_new_keys_still_pages_through_delta(self, multi, monkeypatch):
        multi["component_sources"] = [PEAKS_SPEC]
        sorted_calls: list = []

        def sorted_page(**kw):
            sorted_calls.append(kw["page"])
            return PEAKS.sort("score", descending=True).slice(*kw["page"])

        monkeypatch.setattr(deltatables_utils, "load_sorted_deltatable_lite", sorted_page)
        monkeypatch.setattr(deltatables_utils, "count_deltatable_lite", lambda **kw: PEAKS.height)
        monkeypatch.setattr(
            routes,
            "_cached_row_count",
            lambda wf, dc, metadata, init, fn, delta_version=None: fn(
                workflow_id=wf, data_collection_id=dc, metadata=metadata
            ),
        )
        out = _list({"start": 1, "limit": 2})
        assert sorted_calls == [(1, 2)] and multi["reads"] == []
        assert _labels(out) == ["D", "A"]


class TestNear:
    def _near(self, chrom, pos, direction, **extra):
        body = {
            "near": {
                "chrom": chrom,
                "pos": pos,
                "direction": direction,
                "chrom_order": CHROM_ORDER,
            },
            **extra,
        }
        return _list(body)

    def test_the_next_region_by_position_over_all_sources(self, multi):
        out = self._near("chr1", 100, 1)
        assert out["total"] == 7 and len(out["rows"]) == 1
        # genes TP53 at 180 comes before the peak at 150? No: 150 is nearer.
        assert out["rows"][0]["start"] == 150

    def test_the_previous_region(self, multi):
        out = self._near("1", 500, -1)
        assert (out["rows"][0]["source"], out["rows"][0]["label"]) == ("peaks", "B")

    def test_it_moves_on_to_the_next_chromosome_with_chr_tolerance(self, multi):
        out = self._near("chr1", 900, 1)
        assert out["rows"][0]["chrom"] in ("chr2", "2")
        assert out["rows"][0]["start"] == 50

    def test_past_the_last_region_there_is_no_row(self, multi):
        out = self._near("chr3", 10, 1)
        assert out["rows"] == [] and out["total"] == 7

    def test_a_malformed_near_is_a_400(self, multi):
        with pytest.raises(HTTPException) as exc:
            _list({"near": {"chrom": "chr1", "pos": 1, "direction": 2, "chrom_order": []}})
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException):
            _list({"near": {"chrom": "chr1"}})

    def test_near_respects_sources_and_search(self, multi):
        out = self._near("chr1", 0, 1, sources=["genes"])
        assert (out["rows"][0]["source"], out["rows"][0]["start"]) == ("genes", 180)
        out = self._near("chr1", 0, 1, search="C")
        assert out["rows"][0]["label"] == "C"


class TestMerge:
    def test_overlapping_regions_across_samples_are_one_row_within_a_source(self, multi):
        out = _list({"merge": True, "limit": 200})
        # peaks: chr1 100-260 (A+B), chr1 900, chr2, chr3; genes: two, kept apart
        assert out["total"] == 6
        first = out["rows"][0]
        assert (first["chrom"], first["start"], first["end"]) == ("chr1", 100, 260)
        assert first["n_rows"] == 2 and first["n_samples"] == 2
        assert first["samples"] == ["S1", "S2"]
        assert first["sources"] == ["peaks"]
        # best score is the peak B, whose label, source and mate the row takes
        assert (first["score"], first["label"], first["source"]) == (9.0, "B", "peaks")
        assert first["mate_locus"] == "chr9:1990-2010"
        assert first["locus"] == "chr1:90-270"

    def test_merged_rows_come_best_first_when_a_source_has_a_sort_by(self, multi):
        out = _list({"merge": True, "limit": 200})
        assert [r["score"] for r in out["rows"]] == [9.0, 7.0, 2.0, 1.0, None, None]

    def test_merged_rows_sort_by_n_samples_and_start(self, multi):
        out = _list({"merge": True, "sort": {"column": "n_samples", "descending": True}})
        assert out["rows"][0]["n_samples"] == 2
        out = _list({"merge": True, "sort": {"column": "start", "descending": False}})
        assert [r["start"] for r in out["rows"]] == [10, 50, 60, 100, 180, 900]

    def test_near_with_merge_steps_over_the_whole_overlap(self, multi):
        body = {"chrom": "chr1", "pos": 100, "direction": 1, "chrom_order": CHROM_ORDER}
        out = _list({"merge": True, "near": body})
        # the peak overlap (100-260) is one stop; the gene at 180 is another source
        assert out["total"] == 6 and out["rows"][0]["label"] == "TP53"
        body["pos"] = 180
        assert _list({"merge": True, "near": body})["rows"][0]["start"] == 900

    def test_search_and_paging_apply_to_merged_rows(self, multi):
        out = _list({"merge": True, "search": "d"})
        assert out["total"] == 1 and out["rows"][0]["label"] == "D"
        assert _list({"merge": True, "start": 3, "limit": 5})["total"] == 6

    def test_merge_with_sources_leaves_the_others_out(self, multi):
        out = _list({"merge": True, "sources": ["peaks"]})
        assert out["total"] == 4 and out["rows"][0]["n_rows"] == 2


class TestDensity:
    def test_one_track_per_source(self, multi):
        out = _density({"bins": 11})
        assert out["bin_size"] == 100 and out["truncated"] == 0
        assert [t["source"] for t in out["tracks"]] == ["peaks", "genes"]
        peaks = out["tracks"][0]
        assert [c["refName"] for c in peaks["chroms"]] == ["chr1", "chr2"]
        # chr1 starts: 100, 150 (bin 1), 900 (bin 9); chr2: 50 (bin 0)
        assert peaks["chroms"][0]["counts"][1] == 2 and peaks["chroms"][0]["counts"][9] == 1
        assert peaks["chroms"][1]["counts"] == [1]
        genes = out["tracks"][1]
        assert genes["chroms"][0]["counts"][1] == 1  # "1" matches chr1
        assert out["max"] == 2

    def test_group_by_sample_carries_the_run_and_keeps_a_source_without_samples_whole(self, multi):
        out = _density({"bins": 11, "group": "sample"})
        got = [(t["source"], t["label"], t["run"]) for t in out["tracks"]]
        assert got == [
            ("peaks", "S1", "r1"),
            ("peaks", "S2", "r2"),
            ("genes", "genes", None),  # S3 only has a region on chr3, outside the request
        ]

    def test_group_by_run(self, multi):
        out = _density({"bins": 11, "group": "run", "sources": ["peaks"]})
        assert [(t["label"], t["run"]) for t in out["tracks"]] == [("r1", None), ("r2", None)]

    def test_sources_restrict_the_tracks(self, multi):
        assert [t["source"] for t in _density({"sources": ["genes"]})["tracks"]] == ["genes"]
        assert _density({"sources": ["nope"]})["tracks"] == []

    def test_density_and_listing_share_one_read(self, multi):
        _list({"search": "a"})
        reads = len(multi["reads"])
        _density({})
        assert len(multi["reads"]) == reads

    def test_bins_are_clamped_and_the_request_is_validated(self, multi):
        assert _density({"bins": 10_000_000})["bin_size"] == 1
        with pytest.raises(HTTPException) as exc:
            _density({"group": "cell"})
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            _density({"regions": []})
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            _density({"regions": [{"refName": "chr1"}]})
        assert exc.value.status_code == 400

    def test_a_pinned_density_reads_the_pinned_commits(self, multi):
        _density({"as_of_version": "v1"})
        assert sorted(multi["reads"]) == sorted([(PEAKS_DC, 7), (GENES_DC, 2)])

    def test_the_endpoint_is_off_when_the_genome_browser_is(self, multi, monkeypatch):
        monkeypatch.setattr(routes.settings, "jbrowse", SimpleNamespace(enabled=False))
        with pytest.raises(HTTPException) as exc:
            _density({})
        assert exc.value.status_code == 404


class TestPrimarySource:
    def test_the_view_is_framed_and_filtered_on_the_primary_source_only(self, multi):
        source = routes._jbrowse_calls_source(
            {"locus_from": [PEAKS_SPEC, GENES_SPEC]}, FILTERS, "pid", None
        )
        assert source[0]["name"] == "peaks" and source[2] == PEAKS_DC
        assert routes._jbrowse_locus_source({"locus_from": [PEAKS_SPEC, GENES_SPEC]}, "pid") == {
            "dc_id": PEAKS_DC,
            "chrom_column": "chrom",
            "start_column": "start",
            "end_column": "end",
        }

    def test_the_first_call_reads_the_primary_source(self, multi, monkeypatch):
        seen: list = []

        def natural_page(wf, dc, metadata, init, columns, start, limit, delta_version=None):
            seen.append(dc)
            return PEAKS.slice(start, limit)

        def sorted_page(**kw):
            seen.append(kw["data_collection_id"])
            return PEAKS.sort("score", descending=True).slice(*kw["page"])

        monkeypatch.setattr(routes, "_load_natural_page", natural_page)
        monkeypatch.setattr(deltatables_utils, "load_sorted_deltatable_lite", sorted_page)
        pins = DataVersionPins(pins={})
        first = routes._jbrowse_first_call(
            {"locus_from": [PEAKS_SPEC, GENES_SPEC]}, [], "pid", None, pins
        )
        assert seen == [PEAKS_DC]
        assert first["locus"] == "chr1:140-270" and first["mate_locus"] == "chr9:1990-2010"


class TestRegionFilterIgnoresTheChrPrefix:
    """A ``genome_selection`` chromosome filter matches ``1`` and ``chr1`` alike."""

    DF = pl.DataFrame({"chrom": ["chr1", "1", "chr2", "chrM"], "start": [1, 2, 3, 4]})

    def _filtered(self, source, value, column="chrom"):
        filters = routes._build_filter_metadata(
            [
                {
                    "index": "r",
                    "value": value,
                    "source": source,
                    "column_name": column,
                    "interactive_component_type": "MultiSelect",
                }
            ]
        )
        exprs = deltatables_utils.process_metadata_and_filter(filters, dict(self.DF.schema))
        return self.DF.filter(*exprs)["start"].to_list()

    def test_the_region_pair_matches_both_spellings(self):
        assert self._filtered("genome_selection", ["chr1"]) == [1, 2]
        assert self._filtered("genome_selection", ["1"]) == [1, 2]
        assert self._filtered("genome_selection", ["MT"]) == [4]

    def test_every_other_filter_stays_exact(self):
        assert self._filtered("sidebar", ["chr1"]) == [1]
        assert self._filtered(None, ["1"]) == [2]


def test_track_summary_group_reads_color_by_then_the_manifest_group() -> None:
    """The legend's label: the tile's `color_by` column, else the manifest's `group`."""
    props = SimpleNamespace(direct_access=False, s3_prefixes=[], base_url=None)
    track = tracks.TrackRow(
        key="k",
        track_id="t",
        name="t",
        uri="",
        index_uri=None,
        fmt="bigwig",
        sample="A_R1",
        color="red",
        row={"group": "A", "condition": "treated", "empty": ""},
    )
    assert render._track_summary(track, None, props)["group"] == "A"
    assert render._track_summary(track, None, props, group_column="condition")["group"] == "treated"
    assert render._track_summary(track, None, props, group_column="empty")["group"] is None
