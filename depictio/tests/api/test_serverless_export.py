"""Tests for serverless producer A (export a static bundle from an instance).

Two layers, mirroring how the rest of ``depictio/tests/api`` is structured
(unit tests over route/module internals, no running stack required):

1. **Pure-unit** tests for the translation/assembly parts — tier
   classification of ``stored_metadata`` components, the advanced_viz request
   derivation, dashboard-document sanitisation, bulk-card splitting and the
   live column-set computation. These run everywhere.
2. An **offline end-to-end** export against fake Mongo collections and fake
   endpoint bodies, monkeypatched onto the real server modules (producer A
   resolves them through their module objects at call time precisely so this
   seam exists). This exercises the full manifest assembly — data refs,
   companions/codebooks, snappy re-export, frozen payloads, tier refinements —
   without Mongo, S3 or Celery.

The same offline stack also drives the **binding preflight** —
``export_static(check=True)``, which is that end-to-end body stopped before it
builds anything — so the report and the bundle can be asserted row for row.

A final smoke test runs the data-free plan (``check=True, bind=False``) against
a real MongoDB when one is reachable (CI provides the stack; a bare box skips
cleanly).
"""

from __future__ import annotations

import base64
import io
import random
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from bson import ObjectId

from depictio.models.models.serverless import (
    BundleManifest,
    ComponentTier,
    Producer,
    TierReason,
)
from depictio.serverless import producer_a
from depictio.serverless.preflight import classify_component
from depictio.serverless.producer_a import (
    BundleTooLargeError,
    ComputeBudget,
    ExportUser,
    FamilyTab,
    ProducerAError,
    advanced_viz_request,
    classify_stored_component,
    classify_stored_metadata,
    export_manifest,
    export_static,
    family_components,
    interactive_filter_columns,
    live_column_sets,
    sanitize_dashboard_doc,
    split_bulk_cards,
)

# ---------------------------------------------------------------------------
# Pure-unit: tier classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "comp,tier,reason",
    [
        ({"component_type": "card"}, ComponentTier.LIVE, None),
        ({"component_type": "interactive"}, ComponentTier.LIVE, None),
        ({"component_type": "text"}, ComponentTier.LIVE, None),
        # A table plans LIVE: `renderTableLive` recomputes every page from the
        # bundled Parquet. Only a table whose DC never lands in the bundle is
        # downgraded, and that is a build-time fact.
        ({"component_type": "table"}, ComponentTier.LIVE, None),
        ({"component_type": "figure", "mode": "ui"}, ComponentTier.FROZEN, TierReason.BINDING_MISS),
        # mode defaults to "ui"
        ({"component_type": "figure"}, ComponentTier.FROZEN, TierReason.BINDING_MISS),
        ({"component_type": "figure", "mode": "code"}, ComponentTier.FROZEN, TierReason.CODE_MODE),
        # MultiQC only ever fetched a figure keyed on frozen inputs and then
        # applied a pure patch — the runtime re-applies that patch offline.
        ({"component_type": "multiqc"}, ComponentTier.LIVE, None),
        ({"component_type": "map"}, ComponentTier.FROZEN, TierReason.MAP_TILES),
        ({"component_type": "image"}, ComponentTier.OMITTED, TierReason.IMAGE),
        ({"component_type": "jbrowse"}, ComponentTier.OMITTED, TierReason.JBROWSE),
        (
            {"component_type": "advanced_viz", "viz_kind": "embedding"},
            ComponentTier.OMITTED,
            TierReason.CELERY_COMPUTE,
        ),
        (
            {"component_type": "advanced_viz", "config": {"viz_kind": "complex_heatmap"}},
            ComponentTier.OMITTED,
            TierReason.CELERY_COMPUTE,
        ),
        # Data-path kinds are live since phase 4 — the in-browser engine
        # recomputes /advanced_viz/data from the bundled Parquet.
        (
            {
                "component_type": "advanced_viz",
                "viz_kind": "volcano",
                "wf_id": "6" * 24,
                "dc_id": "7" * 24,
                "config": {"viz_kind": "volcano", "x_col": "lfc", "y_col": "q_val"},
            },
            ComponentTier.LIVE,
            None,
        ),
        # …except phylogenetic, whose Newick tree DC no single bundled table
        # can carry: it keeps the frozen /advanced_viz/data payload.
        (
            {
                "component_type": "advanced_viz",
                "viz_kind": "phylogenetic",
                "wf_id": "6" * 24,
                "dc_id": "7" * 24,
                "config": {
                    "viz_kind": "phylogenetic",
                    "leaf_col": "tip",
                    "tree_dc_id": "8" * 24,
                },
            },
            ComponentTier.FROZEN,
            TierReason.UNSUPPORTED,
        ),
        # A config that binds no column has no request to serve or freeze.
        (
            {"component_type": "advanced_viz", "viz_kind": "volcano"},
            ComponentTier.OMITTED,
            TierReason.UNSUPPORTED,
        ),
        ({"component_type": "wat"}, ComponentTier.OMITTED, TierReason.UNSUPPORTED),
    ],
)
def test_classify_stored_component(comp, tier, reason):
    plan = classify_stored_component(comp)
    assert plan.tier is tier
    assert plan.reason is reason
    if tier is not ComponentTier.LIVE:
        assert plan.detail  # every degradation carries a human explanation


def test_classify_stored_metadata_keys_by_index():
    rows = classify_stored_metadata(
        [
            {"index": "c1", "component_type": "card", "title": "Mean"},
            {"component_type": "table"},  # no index -> positional fallback
        ]
    )
    assert [r.component_id for r in rows] == ["c1", "component-1"]
    assert rows[0].tier is ComponentTier.LIVE
    assert rows[1].tier is ComponentTier.LIVE


# The planned verdicts a *data-free* classifier can and cannot decide. Both
# producers answer from the same helper (``binding.planned_figure_miss``), so
# the parity is asserted rather than assumed.
def _ui_figure(**dict_kwargs: Any) -> dict[str, Any]:
    return {
        "index": "fig-1",
        "tag": "fig-1",
        "component_type": "figure",
        "workflow_tag": "wf",
        "data_collection_tag": "dc",
        "wf_id": "6" * 24,
        "dc_id": "7" * 24,
        "visu_type": dict_kwargs.pop("visu_type", "scatter"),
        "dict_kwargs": dict_kwargs,
    }


def test_a_non_ols_trendline_is_a_final_frozen_verdict():
    """``trendline: lowess`` (the penguins body-mass scatter) is refused by the
    binder before it ever looks at data — so say so, instead of 'undecided'."""
    comp = _ui_figure(x="flipper_length_mm", y="body_mass_g", trendline="lowess")
    for plan in (classify_stored_component(comp), classify_component(comp)):
        assert plan.tier is ComponentTier.FROZEN
        assert plan.reason is TierReason.BINDING_MISS
        assert plan.detail and "only an OLS trendline can be refit" in plan.detail
        assert plan.provisional is False


def test_a_whole_frame_visu_is_a_final_frozen_verdict():
    comp = _ui_figure(visu_type="scatter_matrix", dimensions=["a", "b"])
    for plan in (classify_stored_component(comp), classify_component(comp)):
        assert plan.tier is ComponentTier.FROZEN
        assert plan.reason is TierReason.WHOLE_FRAME_VIZ
        assert plan.detail and "computed over the whole table at once" in plan.detail
        assert plan.provisional is False


def test_a_code_mode_whole_frame_visu_is_decided_from_its_px_call():
    """The iris pairwise-measurements tile: `mode: code`, `visu_type: scatter`,
    and a `px.scatter_matrix` inside. The transpiler reads the terminal call, so
    the whole-frame refusal is as knowable here as on a ui-mode figure."""
    comp = _ui_figure(x="a", y="b")
    comp["mode"] = "code"
    comp["code_content"] = "fig = px.scatter_matrix(df, dimensions=['a', 'b'])"
    for plan in (classify_stored_component(comp), classify_component(comp)):
        assert plan.tier is ComponentTier.FROZEN
        assert plan.reason is TierReason.WHOLE_FRAME_VIZ
        assert plan.detail and "computed over the whole table at once" in plan.detail
        assert plan.provisional is False


def test_a_phylogenetic_tile_freezes_from_its_metadata_collection(monkeypatch):
    """The reference seeds point a phylogenetic tile's own `dc_id` at the TREE
    (a `type: phylogeny` collection, which is a Newick file and has no Delta
    table), and carry the tip table in `config.metadata_dc_id`. Asking
    `/advanced_viz/data` for the tree 404s and drops the whole tile to omitted,
    which is what used to happen. Mirror `PhylogeneticRenderer`: table from the
    metadata ids, tree from `tree_dc_id`."""
    from depictio.api.v1.endpoints.advanced_viz_endpoints import routes as av_mod

    tree_dc, meta_dc, meta_wf = ObjectId(), ObjectId(), ObjectId()
    seen: dict[str, Any] = {}

    def fake_av_data(_response, payload, current_user, access_token):  # noqa: ARG001
        seen["request"] = payload
        return {"columns": ["tip"], "rows": {"tip": ["t1"]}, "row_count": 1}

    def fake_newick(data_collection_id, current_user):  # noqa: ARG001
        seen["newick_dc"] = str(data_collection_id)
        return "(t1:0.1,t2:0.2);"

    monkeypatch.setattr(av_mod, "fetch_advanced_viz_data", fake_av_data)
    monkeypatch.setattr(av_mod, "get_phylogeny_newick", fake_newick)

    payload = producer_a._freeze_advanced_viz(
        {
            "index": "phylo-tree",
            "component_type": "advanced_viz",
            "viz_kind": "phylogenetic",
            "wf_id": str(ObjectId()),
            "dc_id": str(tree_dc),
            "config": {
                "viz_kind": "phylogenetic",
                "taxon_col": "tip",
                "tree_dc_id": str(tree_dc),
                "metadata_wf_id": str(meta_wf),
                "metadata_dc_id": str(meta_dc),
            },
        },
        ExportUser(id=ObjectId(), is_admin=True),
    )

    assert seen["request"]["dc_id"] == str(meta_dc)
    assert seen["request"]["wf_id"] == str(meta_wf)
    assert seen["newick_dc"] == str(tree_dc)
    assert payload["newick"].startswith("(t1")


def test_a_phylogenetic_tile_ships_its_tree_when_the_tip_metadata_is_missing(monkeypatch):
    """The tree is the visualisation; the tip table only colours and labels it,
    and `PhylogeneticRenderer` already treats it as optional. An unmaterialised
    metadata collection must therefore cost the colours, not the tree."""
    from depictio.api.v1.endpoints.advanced_viz_endpoints import routes as av_mod

    def boom(_response, payload, current_user, access_token):  # noqa: ARG001
        raise ValueError("404: Data collection has no materialised Delta table yet.")

    monkeypatch.setattr(av_mod, "fetch_advanced_viz_data", boom)
    monkeypatch.setattr(av_mod, "get_phylogeny_newick", lambda dc, user: "(t1:0.1,t2:0.2);")

    comp = {
        "index": "phylo-tree",
        "component_type": "advanced_viz",
        "viz_kind": "phylogenetic",
        "wf_id": str(ObjectId()),
        "dc_id": str(ObjectId()),
        "config": {
            "viz_kind": "phylogenetic",
            "taxon_col": "tip",
            "tree_dc_id": str(ObjectId()),
            "metadata_dc_id": str(ObjectId()),
        },
    }
    payload = producer_a._freeze_advanced_viz(comp, ExportUser(id=ObjectId(), is_admin=True))
    assert payload["newick"].startswith("(t1")
    assert payload["columns"] == [] and payload["rows"] == {}

    # …but with neither table nor tree there is nothing to draw, and the
    # component must be omitted rather than shipped empty.
    monkeypatch.setattr(
        av_mod, "get_phylogeny_newick", lambda dc, user: (_ for _ in ()).throw(ValueError("gone"))
    )
    with pytest.raises(ProducerAError, match="phylogeny tree could not be read"):
        producer_a._freeze_advanced_viz(comp, ExportUser(id=ObjectId(), is_admin=True))


def test_a_phylogenetic_tile_that_loses_its_tree_is_omitted_even_with_metadata(monkeypatch):
    """The asymmetry runs the other way from the table's: the TREE is the
    visualisation and the tip metadata only colours it. A tile that keeps its
    columns but loses its Newick used to ship as ``frozen`` with no ``newick``
    key — the runtime reads that as ``''``, `PhylogeneticRenderer` returns null
    on an empty tree, and the reader gets a titled empty box with no message.
    No tree is fatal whatever the table did."""
    from depictio.api.v1.endpoints.advanced_viz_endpoints import routes as av_mod

    monkeypatch.setattr(
        av_mod,
        "fetch_advanced_viz_data",
        lambda _response, payload, current_user, access_token: {  # noqa: ARG005
            "columns": ["tip"],
            "rows": {"tip": ["t1", "t2"]},
            "row_count": 2,
        },
    )
    monkeypatch.setattr(
        av_mod,
        "get_phylogeny_newick",
        lambda dc, user: (_ for _ in ()).throw(ValueError("404: no Newick for this collection")),
    )
    comp = {
        "index": "phylo-tree",
        "component_type": "advanced_viz",
        "viz_kind": "phylogenetic",
        "wf_id": str(ObjectId()),
        "dc_id": str(ObjectId()),
        "config": {
            "viz_kind": "phylogenetic",
            "taxon_col": "tip",
            "tree_dc_id": str(ObjectId()),
            "metadata_dc_id": str(ObjectId()),
        },
    }

    with pytest.raises(ProducerAError, match="phylogeny tree could not be read"):
        producer_a._freeze_advanced_viz(comp, ExportUser(id=ObjectId(), is_admin=True))


def test_a_phylogenetic_tile_without_a_tree_binding_is_omitted_not_fetched(monkeypatch):
    """`PhylogeneticRenderer` bails with "missing tree DC binding" before it ever
    calls ``fetchPhylogenyNewick`` when ``config.tree_dc_id`` is unset, so
    fetching a Newick off the component's own ``dc_id`` produced a payload the
    runtime cannot reach. Omit the tile instead of shipping it blank."""
    from depictio.api.v1.endpoints.advanced_viz_endpoints import routes as av_mod

    fetched: list[str] = []
    monkeypatch.setattr(
        av_mod,
        "fetch_advanced_viz_data",
        lambda _response, payload, current_user, access_token: {  # noqa: ARG005
            "columns": ["tip"],
            "rows": {"tip": ["t1"]},
            "row_count": 1,
        },
    )
    monkeypatch.setattr(
        av_mod,
        "get_phylogeny_newick",
        lambda dc, user: fetched.append(str(dc)) or "(t1:0.1,t2:0.2);",
    )
    comp = {
        "index": "phylo-tree",
        "component_type": "advanced_viz",
        "viz_kind": "phylogenetic",
        "wf_id": str(ObjectId()),
        "dc_id": str(ObjectId()),  # the tile's own DC — never asked for a tree
        "config": {"viz_kind": "phylogenetic", "taxon_col": "tip"},
    }

    with pytest.raises(ProducerAError, match="no tree data collection bound"):
        producer_a._freeze_advanced_viz(comp, ExportUser(id=ObjectId(), is_admin=True))
    assert fetched == []  # the dead fetch is gone, not merely unused


def test_a_code_figure_whose_px_call_is_unreadable_is_a_final_frozen_verdict():
    """Both halves have to succeed for a code-mode figure to reach the binder:
    a prologue that transpiles but a terminal ``px`` call the analyzer refuses
    (a non-literal kwarg here) freezes as ``code_mode``, and is never offered.
    A classifier that only checked the transpiler promised "upgraded to live
    when the binding matches" for a figure that can never be upgraded — and
    ``print_tier_table`` does not print ``provisional``, so the CLI printed the
    promise as fact."""
    comp = _ui_figure(x="a", y="b")
    comp["mode"] = "code"
    comp["code_content"] = "df2 = df.sort('a')\nfig = px.bar(df2, x='a', y=y_col)"

    from depictio.serverless.prologue import transpile_with_reason
    from depictio.serverless.prologue_exec import terminal_px_call

    # The gap this pins: the transpiler is happy, the px reader is not.
    assert transpile_with_reason(comp["code_content"])[0] is not None
    assert terminal_px_call(comp["code_content"]) is None

    for plan in (classify_stored_component(comp), classify_component(comp)):
        assert plan.tier is ComponentTier.FROZEN
        assert plan.reason is TierReason.CODE_MODE
        assert plan.detail and "figure call not analyzable" in plan.detail
        assert plan.provisional is False


def test_an_ols_figure_stays_undecided_until_the_build_binds_it():
    """The gates it clears prove nothing: whether the trace set matches the
    frame is only knowable with the frame in hand."""
    comp = _ui_figure(x="bill_length_mm", y="bill_depth_mm", trendline="ols")
    for plan in (classify_stored_component(comp), classify_component(comp)):
        assert plan.tier is ComponentTier.FROZEN
        assert plan.reason is TierReason.BINDING_MISS
        assert plan.provisional is True


def test_the_printed_tier_table_marks_the_rows_the_build_can_overturn():
    """``provisional`` used to reach the CLI and vanish: an undecided row read
    exactly like a settled one, so "upgraded to live when the binding matches"
    printed as a promise. One word in the Tier cell, plus a legend."""
    from rich.console import Console

    from depictio.serverless.preflight import TierRow, print_tier_table

    console = Console(record=True, width=200)
    print_tier_table(
        [
            TierRow(
                component_id="fig-1",
                title="Undecided",
                component_type="figure",
                tier=ComponentTier.FROZEN,
                reason=TierReason.BINDING_MISS,
                provisional=True,
            ),
            TierRow(
                component_id="fig-2",
                title="Settled",
                component_type="figure",
                tier=ComponentTier.FROZEN,
                reason=TierReason.WHOLE_FRAME_VIZ,
            ),
        ],
        console,
    )
    lines = console.export_text().splitlines()

    marked = [line for line in lines if "fig-1" in line]
    assert marked and "(planned)" in marked[0]
    assert all("(planned)" not in line for line in lines if "fig-2" in line)
    assert any("1 row(s) the build can still overturn" in line for line in lines)


# ---------------------------------------------------------------------------
# Pure-unit: advanced_viz request derivation
# ---------------------------------------------------------------------------


def test_advanced_viz_request_from_config():
    comp = {
        "component_type": "advanced_viz",
        "wf_id": ObjectId(),
        "dc_id": ObjectId(),
        "viz_kind": "volcano",
        "config": {
            "viz_kind": "volcano",
            "x_col": "lfc",
            "y_col": "q_val",
            "label_col": "gene",
            "compute_method": "wilcoxon",  # scalar, not a column
        },
    }
    req = advanced_viz_request(comp)
    assert req is not None
    assert req["columns"] == ["lfc", "q_val", "gene"]
    assert req["roles"] == {"x": "lfc", "y": "q_val", "label": "gene"}
    assert req["viz_kind"] == "volcano"
    assert req["filter_metadata"] == []
    assert req["wf_id"] == str(comp["wf_id"]) and req["dc_id"] == str(comp["dc_id"])


def test_advanced_viz_request_rank_cols_and_dedupe():
    comp = {
        "wf_id": "6" * 24,
        "dc_id": "7" * 24,
        "config": {
            "viz_kind": "sunburst",
            "rank_cols": ["Phylum", "Genus"],
            "abundance_col": "rel_abundance",
            "sample_id_col": "Phylum",  # duplicate column across roles
        },
    }
    req = advanced_viz_request(comp)
    assert req is not None
    assert req["columns"] == ["Phylum", "Genus", "rel_abundance"]
    assert req["roles"] == {"abundance": "rel_abundance", "sample_id": "Phylum"}


def test_advanced_viz_request_none_without_columns_or_ids():
    assert advanced_viz_request({"wf_id": "a", "dc_id": "b", "config": {}}) is None
    assert advanced_viz_request({"config": {"x_col": "v"}}) is None


# ---------------------------------------------------------------------------
# Pure-unit: dashboard document sanitisation
# ---------------------------------------------------------------------------


def test_sanitize_dashboard_doc_strips_and_stringifies():
    oid = ObjectId()
    doc = {
        "_id": ObjectId(),
        "dashboard_id": oid,
        "title": "T",
        "permissions": {"owners": [{"_id": ObjectId()}]},
        "project_realtime": {"enabled": True},
        "stored_metadata": [{"index": "c1", "dc_id": oid, "wf_id": oid}],
    }
    out = sanitize_dashboard_doc(doc)
    assert "_id" not in out
    assert "permissions" not in out  # a shared bundle must not carry the ACL
    assert "project_realtime" not in out  # keeps the realtime hook inert (errata #5)
    assert out["dashboard_id"] == str(oid)
    assert out["stored_metadata"][0]["dc_id"] == str(oid)
    # The original document is untouched (find_one result reused by callers).
    assert isinstance(doc["stored_metadata"][0]["dc_id"], ObjectId)


# ---------------------------------------------------------------------------
# Pure-unit: bulk-card splitting + live column sets
# ---------------------------------------------------------------------------


def test_split_bulk_cards():
    bulk = {
        "values": {"a": 1.5, "b": None},
        "secondary_values": {"a": {"max": 9}},
        "aggregations": {"a": ["max"]},
        "filter_applied": False,
        "filter_count": 0,
    }
    out = split_bulk_cards(bulk, ["a", "b", "missing"])
    assert set(out) == {"a", "b"}
    assert out["a"] == {
        "values": {"a": 1.5},
        "filter_applied": False,
        "filter_count": 0,
        "secondary_values": {"a": {"max": 9}},
        "aggregations": {"a": ["max"]},
    }
    assert out["b"] == {"values": {"b": None}, "filter_applied": False, "filter_count": 0}


def test_live_column_sets_covers_bundled_data_components():
    dc_a, dc_b, dc_c = ObjectId(), ObjectId(), ObjectId()
    stored = [
        {"component_type": "card", "dc_id": dc_a, "column_name": "bill", "breakdown_col": "isl"},
        {
            "component_type": "card",
            "dc_id": dc_a,
            "column_name": "mass",
            "filter_expr": "col('q') < 0.05",
        },
        {"component_type": "interactive", "dc_id": dc_a, "column_name": "year"},
        {"component_type": "interactive", "dc_id": dc_b, "column_name": "species"},
        # ui-mode figures contribute their referenced columns (bind-and-refill
        # needs them in the bundled Parquet)…
        {"component_type": "figure", "dc_id": dc_a, "dict_kwargs": {"x": "flipper"}},
        # …but an untranspilable code-mode figure and text contribute nothing.
        {"component_type": "figure", "mode": "code", "dc_id": dc_a, "code_content": "fig = 1"},
        {"component_type": "text", "dc_id": dc_a},
        # A table widens its DC to every column: sorting or filtering offline
        # may touch any of them.
        {"component_type": "table", "dc_id": dc_c},
    ]
    sets = live_column_sets(stored)
    assert sets[str(dc_a)] == {"bill", "isl", "mass", "q", "year", "flipper"}
    assert sets[str(dc_b)] == {"species"}
    assert sets[str(dc_c)] is None
    assert interactive_filter_columns(stored) == {"year", "species"}


# ---------------------------------------------------------------------------
# Offline end-to-end export (fake Mongo + fake endpoint bodies)
# ---------------------------------------------------------------------------


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    def find_one(self, query: dict[str, Any], projection: Any = None) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None


class _FakeTabCollection:
    """``dashboards_collection`` as ``core_functions.get_child_tabs`` uses it:
    ``find(...).sort(field, direction)``.

    Every export resolves a tab family, so this has to be patched onto
    ``core_functions`` (which binds the collection at import time) even for a
    single-tab dashboard — otherwise the child lookup would reach for a real
    MongoDB.
    """

    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    def find(self, query: dict[str, Any], projection: Any = None):
        matched = [d for d in self.docs if all(d.get(k) == v for k, v in query.items())]

        class _Cursor:
            def sort(self, field: str, direction: int = 1):
                return sorted(matched, key=lambda d: d.get(field) or 0, reverse=direction < 0)

        return _Cursor()


DASHBOARD_OID = ObjectId("6824cb3b89d2b72169309737")
PROJECT_OID = ObjectId("646b0f3c1e4a2d7f8e5b8c9d")
WF_OID = ObjectId("646b0f3c1e4a2d7f8e5b8c01")
DC_OID = ObjectId("646b0f3c1e4a2d7f8e5b8ca1")
DC2_OID = ObjectId("646b0f3c1e4a2d7f8e5b8ca3")  # consumed only by an unbindable figure
AV_DC_OID = ObjectId("646b0f3c1e4a2d7f8e5b8ca2")  # the advanced_viz components' DC
TREE_DC_OID = ObjectId("646b0f3c1e4a2d7f8e5b8ca4")  # phylogenetic's Newick source

TABLE_TOTAL = 700  # > one 500-row endpoint page, < the 1000-row producer cap


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "bill": [39.1, 40.2, 41.3, 42.4],
            "flipper": [181, 186, 190, 195],
            "species": ["Adelie", "Adelie", "Gentoo", "Gentoo"],
            "year": [2021, 2021, 2022, 2023],
        }
    )


def _frame_2() -> pl.DataFrame:
    return pl.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})


def _frame_av() -> pl.DataFrame:
    """The advanced_viz DC: `tip` is read by the FROZEN phylogenetic component
    only, so pruning must leave it out of the bundle."""
    return pl.DataFrame(
        {
            "lfc": [1.0, -2.0, 0.5],
            "q_val": [0.01, 0.2, 0.7],
            "tip": ["t1", "t2", "t3"],
        }
    )


def _dashboard_doc() -> dict[str, Any]:
    dc_config = {"type": "table", "delta_location": "memory://dcA", "size_bytes": 123}
    dc2_config = {"type": "table", "delta_location": "memory://dcB", "size_bytes": 45}
    av_config = {"type": "table", "delta_location": "memory://dcAV", "size_bytes": 67}
    return {
        "_id": ObjectId(),
        "dashboard_id": DASHBOARD_OID,
        "project_id": PROJECT_OID,
        "title": "Fake dashboard",
        "permissions": {"owners": []},
        "project_realtime": {"enabled": True},
        "stored_metadata": [
            {
                "index": "card-1",
                "component_type": "card",
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
                "column_name": "bill",
                "aggregation": "mean",
            },
            {
                "index": "filter-1",
                "component_type": "interactive",
                "interactive_component_type": "MultiSelect",
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
                "column_name": "year",
            },
            {"index": "text-1", "component_type": "text"},
            {
                # Binds (bind-and-refill): plain scatter, no ambiguity -> LIVE.
                "index": "fig-1",
                "component_type": "figure",
                "mode": "ui",
                "visu_type": "scatter",
                "dict_kwargs": {"x": "bill", "y": "flipper"},
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
            },
            {
                # Binds too: hover_data makes a 2-D customdata array, which the
                # binder resolves column by column (TraceBinding.customdata) so
                # the runtime can zip it back for the hovertemplate -> LIVE.
                "index": "fig-2",
                "component_type": "figure",
                "mode": "ui",
                "visu_type": "scatter",
                "dict_kwargs": {"x": "bill", "y": "flipper", "hover_data": ["species"]},
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
            },
            {
                # Code mode never binds; the (fake) preview samples -> partial.
                "index": "fig-3",
                "component_type": "figure",
                "mode": "code",
                "visu_type": "scatter",
                "code_content": "fig = px.scatter(df, x='bill', y='flipper')",
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
            },
            {
                # Whole-frame visu on its own DC: binding refused, and the DC's
                # blob (bundled speculatively for the figure) must be dropped.
                "index": "fig-4",
                "component_type": "figure",
                "mode": "ui",
                "visu_type": "heatmap",
                "dict_kwargs": {"x": "a", "y": "b"},
                "wf_id": WF_OID,
                "dc_id": DC2_OID,
                "dc_config": dc2_config,
            },
            {
                "index": "tbl-1",
                "component_type": "table",
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
            },
            {
                # Data-path kind: LIVE since phase 4 — its DC is bundled,
                # pruned to the columns its config binds, and it ships no
                # frozen payload.
                "index": "av-1",
                "component_type": "advanced_viz",
                "viz_kind": "volcano",
                "wf_id": WF_OID,
                "dc_id": AV_DC_OID,
                "dc_config": av_config,
                "config": {"viz_kind": "volcano", "x_col": "lfc", "y_col": "q_val"},
            },
            {
                # Phylogenetic reads a second, non-tabular source (the Newick
                # tree DC) -> still frozen, tree merged into the payload.
                "index": "phy-1",
                "component_type": "advanced_viz",
                "viz_kind": "phylogenetic",
                "wf_id": WF_OID,
                "dc_id": AV_DC_OID,
                "dc_config": av_config,
                "config": {
                    "viz_kind": "phylogenetic",
                    "leaf_col": "tip",
                    "tree_dc_id": str(TREE_DC_OID),
                },
            },
            {
                "index": "emb-1",
                "component_type": "advanced_viz",
                "viz_kind": "embedding",
                "wf_id": WF_OID,
                "dc_id": AV_DC_OID,
                "dc_config": av_config,
                "config": {"viz_kind": "embedding"},
            },
            {"index": "img-1", "component_type": "image"},
        ],
    }


@pytest.fixture
def offline_stack(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """A fake instance holding the dashboard above, plus the call recorders.

    Shared by the end-to-end build (:func:`offline_export`) and the binding
    preflight, which is the same body stopped early — running both against one
    stack is what proves they agree.
    """
    from depictio.api.v1 import celery_tasks as celery_mod
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1 import deltatables_utils as dtu_mod
    from depictio.api.v1.endpoints.advanced_viz_endpoints import routes as av_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as core_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    # A lone dashboard is a one-tab family: the child lookup finds nothing.
    monkeypatch.setattr(core_mod, "dashboards_collection", _FakeTabCollection([]))
    monkeypatch.setattr(db_mod, "deltatables_collection", _FakeCollection([]))
    # Phase 7 reads the dashboard's project for its cross-DC ``links`` — this
    # one declares none, so ``manifest.links`` stays empty. (Links themselves
    # are covered in tests/unit/serverless/test_links_producers.py.)
    monkeypatch.setattr(
        db_mod, "projects_collection", _FakeCollection([{"_id": PROJECT_OID, "links": []}])
    )

    frames = {str(DC_OID): _frame(), str(DC2_OID): _frame_2(), str(AV_DC_OID): _frame_av()}
    locations = {
        str(DC_OID): "memory://dcA",
        str(DC2_OID): "memory://dcB",
        str(AV_DC_OID): "memory://dcAV",
    }

    def fake_schema(workflow_id, data_collection_id, init_data):
        dc = str(data_collection_id)
        assert init_data[dc]["delta_location"] == locations[dc]
        return dict(frames[dc].schema)

    def fake_load(workflow_id, data_collection_id, metadata=None, select_columns=None, **kw):
        assert metadata is None  # bundling loads the unfiltered frame
        frame = frames[str(data_collection_id)]
        return frame.select(select_columns) if select_columns else frame

    monkeypatch.setattr(dtu_mod, "schema_deltatable_lite", fake_schema)
    monkeypatch.setattr(dtu_mod, "load_deltatable_lite", fake_load)
    monkeypatch.setattr(dtu_mod, "_get_aggregation_hash", lambda dc_id: "agghash-1")

    card_calls: list[list[str]] = []

    def fake_bulk_cards(dashboard_id, request, current_user, access_token):
        assert request["filters"] == []
        assert request["component_ids"] == ["card-1"]
        card_calls.append(list(request["component_ids"]))
        return {
            "values": {"card-1": 40.75},
            "secondary_values": {},
            "aggregations": {},
            "filter_applied": False,
            "filter_count": 0,
        }

    table_calls: list[tuple[int, int]] = []

    def fake_render_table(
        dashboard_id, component_id, request, response, current_user, access_token
    ):
        start, limit = int(request["start"]), int(request["limit"])
        table_calls.append((start, limit))
        assert request["filters"] == []
        rows = [{"i": i} for i in range(start, min(start + limit, TABLE_TOTAL))]
        return {
            "columns": [{"field": "i", "headerName": "i", "type": "numericColumn"}],
            "rows": rows,
            "total": TABLE_TOTAL,
            "sort_by": None,
            "sort_dir": "desc",
        }

    preview_calls: list[str] = []

    def fake_figure_preview(payload):
        assert payload["filter_metadata"] == []
        meta = payload["metadata"]
        preview_calls.append(f"{meta['visu_type']}:{meta['mode']}")
        return {
            "figure": {"data": [], "layout": {}},
            "metadata": {
                "visu_type": meta["visu_type"],
                "filter_applied": False,
                # Only the code-mode figure exercises the sampled->partial path.
                "was_sampled": meta["mode"] == "code",
            },
        }

    av_calls: list[str] = []

    def fake_av_data(response, payload, current_user, access_token):
        # Only the FROZEN advanced_viz still calls the endpoint body: the
        # live data-path kinds are recomputed in the browser.
        av_calls.append(payload["viz_kind"])
        assert payload["viz_kind"] == "phylogenetic"
        assert payload["columns"] == ["tip"]
        assert payload["roles"] == {"leaf": "tip"}
        assert payload["filter_metadata"] == []
        return {
            "columns": ["tip"],
            "rows": {"tip": ["t1"]},
            "row_count": 1,
            "total_rows": 17_000_000,
            "sampled": True,
            "sampling": {"policy": "tail_preserving", "exact": False, "degraded": False},
            "filter_applied": False,
        }

    def fake_newick(data_collection_id, current_user):
        assert str(data_collection_id) == str(TREE_DC_OID)
        return "(t1:0.1,t2:0.2,t3:0.3);"

    monkeypatch.setattr(routes_mod, "bulk_compute_cards", fake_bulk_cards)
    monkeypatch.setattr(routes_mod, "render_table_endpoint", fake_render_table)
    monkeypatch.setattr(celery_mod, "build_figure_preview", fake_figure_preview)
    monkeypatch.setattr(av_mod, "fetch_advanced_viz_data", fake_av_data)
    monkeypatch.setattr(av_mod, "get_phylogeny_newick", fake_newick)

    return {
        "cards": card_calls,
        "tables": table_calls,
        "previews": preview_calls,
        "advanced_viz": av_calls,
    }


@pytest.fixture
def offline_export(offline_stack: dict[str, list]) -> BundleManifest:
    result = export_manifest(str(DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True))
    assert result.manifest is not None
    assert offline_stack["advanced_viz"] == ["phylogenetic"]
    # The table's DC shipped, so it went live off the bundled Parquet and the
    # frozen paging fallback never ran.
    assert offline_stack["tables"] == []
    # Only the unbindable figures fell back to the frozen figure pipeline —
    # the bound fig-1/fig-2 never touched it (they ship a binding table
    # instead; the code-mode fig-3 always renders here, bound or not).
    assert offline_stack["previews"] == ["scatter:code", "heatmap:ui"]
    return result.manifest


def test_offline_export_manifest_contract(offline_export: BundleManifest):
    manifest = offline_export
    assert manifest.producer is Producer.EXPORT_FROM_INSTANCE
    assert manifest.dashboard.id == str(DASHBOARD_OID)  # the REAL ObjectId string
    # Manifest round-trips through its own schema.
    BundleManifest.model_validate(manifest.model_dump(mode="json"))

    doc = manifest.dashboard.doc
    assert "permissions" not in doc and "project_realtime" not in doc and "_id" not in doc
    assert doc["stored_metadata"][0]["dc_id"] == str(DC_OID)

    # The bundle pins the exporting instance's sampling ceilings — the browser
    # engine has no settings of its own to fall back on.
    from depictio.api.v1.configs.config import settings

    perf = settings.performance
    assert manifest.limits.figure_max_points == perf.figure_max_points
    assert manifest.limits.advanced_viz_no_sample_max_rows == perf.advanced_viz_no_sample_max_rows
    assert manifest.limits.advanced_viz_tail_p_threshold == perf.advanced_viz_tail_p_threshold
    assert (
        manifest.limits.advanced_viz_tail_effect_threshold
        == perf.advanced_viz_tail_effect_threshold
    )


def test_offline_export_tiers(offline_export: BundleManifest):
    tiers = {k: v for k, v in offline_export.tiers.items()}
    assert tiers["card-1"].tier is ComponentTier.LIVE
    assert tiers["filter-1"].tier is ComponentTier.LIVE
    assert tiers["text-1"].tier is ComponentTier.LIVE
    # The bound figures were upgraded to LIVE (bind-and-refill, RFC §4) —
    # fig-2 included, since its 2-D customdata binds column by column.
    for bound in ("fig-1", "fig-2"):
        assert tiers[bound].tier is ComponentTier.LIVE
        assert tiers[bound].reason is None and tiers[bound].detail is None
    # The refused figure froze with the binder's own cause in its detail.
    assert tiers["fig-4"].tier is ComponentTier.FROZEN
    # A whole-frame visu is a binding_miss until the caller maps the binder's
    # cause onto TierReason.WHOLE_FRAME_VIZ (build_binding_with_reason).
    assert tiers["fig-4"].reason in (TierReason.BINDING_MISS, TierReason.WHOLE_FRAME_VIZ)
    assert tiers["fig-4"].detail and "frozen at the default filter state" in tiers["fig-4"].detail
    # Sampled frozen code figure was refined to partial (FIGURE_MAX_POINTS).
    assert tiers["fig-3"].tier is ComponentTier.PARTIAL
    assert tiers["fig-3"].reason is TierReason.MAX_POINTS
    # The table's DC shipped, so its planned live verdict stands untouched:
    # `renderTableLive` reproduces render_table_endpoint in full.
    assert tiers["tbl-1"].tier is ComponentTier.LIVE
    assert tiers["tbl-1"].reason is None
    assert tiers["tbl-1"].detail and "renderTableLive" in tiers["tbl-1"].detail
    # advanced_viz data-path kinds go live (phase 4); phylogenetic stays frozen
    # because its Newick tree DC is a second, non-tabular source.
    assert tiers["av-1"].tier is ComponentTier.LIVE
    assert tiers["av-1"].reason is None
    assert tiers["av-1"].detail and "in-browser engine" in tiers["av-1"].detail
    assert tiers["phy-1"].tier is ComponentTier.FROZEN
    assert tiers["phy-1"].reason is TierReason.UNSUPPORTED
    assert tiers["phy-1"].detail and "Newick" in tiers["phy-1"].detail
    assert tiers["emb-1"].tier is ComponentTier.OMITTED
    assert tiers["emb-1"].reason is TierReason.CELERY_COMPUTE
    assert tiers["img-1"].tier is ComponentTier.OMITTED
    assert tiers["img-1"].reason is TierReason.IMAGE


def test_offline_export_data_ref_and_blob(offline_export: BundleManifest):
    manifest = offline_export
    # The DCs live components / the bound figure / the live advanced_viz read:
    # DC2 was bundled speculatively for fig-4, whose binding was refused, so its
    # blob is dropped again (the frozen payload is self-contained).
    assert set(manifest.data_refs) == {str(DC_OID), str(AV_DC_OID)}
    assert f"dc_{DC2_OID}" not in manifest.inline_blobs
    ref = manifest.data_refs[str(DC_OID)]
    assert ref.aggregation_hash == "agghash-1"  # the server-side staleness token
    assert ref.uri == f"inline:dc_{DC_OID}"
    # Pruned to the bundled components' columns: card 'bill', interactive
    # 'year' (+ its codebook companion), the ui figures' 'flipper'/'species';
    # table columns still excluded.
    names = {c.name for c in ref.columns}
    assert names == {"bill", "flipper", "species", "year", "__code__year"}
    assert ref.companions == {"__code__year": "year"}
    assert ref.codebooks == {"year": {"2021": 0, "2022": 1, "2023": 2}}

    blob = base64.b64decode(manifest.inline_blobs[f"dc_{DC_OID}"])
    assert len(blob) == ref.size_bytes
    df = pl.read_parquet(io.BytesIO(blob))
    assert df.height == ref.rows == 4
    assert df["__code__year"].to_list() == [0, 0, 1, 2]


def test_offline_export_bundles_the_live_advanced_viz_columns(offline_export: BundleManifest):
    """A live advanced_viz gets its DC bundled, pruned to the columns its
    config binds — the same derivation ``advanced_viz_request`` sends."""
    manifest = offline_export
    ref = manifest.data_refs[str(AV_DC_OID)]
    # 'tip' is read only by the FROZEN phylogenetic component, whose payload is
    # self-contained, so pruning leaves it out.
    assert {c.name for c in ref.columns} == {"lfc", "q_val"}
    assert ref.uri == f"inline:dc_{AV_DC_OID}"
    df = pl.read_parquet(io.BytesIO(base64.b64decode(manifest.inline_blobs[f"dc_{AV_DC_OID}"])))
    assert df.height == ref.rows == 3


def test_offline_export_frozen_payloads(offline_export: BundleManifest):
    frozen = offline_export.frozen
    # Card fallback keeps the bulk response shape.
    assert frozen["card-1"].kind == "card"
    assert frozen["card-1"].payload["values"] == {"card-1": 40.75}
    # A live table ships no frozen snapshot: it would be a second copy of the
    # Parquet the bundle already carries.
    assert "tbl-1" not in frozen
    # Refused/code figures came straight from build_figure_preview; the bound
    # fig-1/fig-2 ship NO frozen payload (the runtime refills from the Parquet).
    assert "fig-1" not in frozen and "fig-2" not in frozen
    assert frozen["fig-3"].kind == "figure"
    assert frozen["fig-3"].payload["metadata"]["was_sampled"] is True
    assert frozen["fig-4"].kind == "figure"
    # The frozen advanced_viz (phylogenetic) keeps the /advanced_viz/data
    # sampling block verbatim — it is what the renderer's badge reads — and
    # carries the merged Newick tree its renderer also needs.
    phy = frozen["phy-1"]
    assert phy.kind == "advanced-viz-data"
    assert phy.payload["sampling"] == {
        "policy": "tail_preserving",
        "exact": False,
        "degraded": False,
    }
    assert phy.payload["total_rows"] == 17_000_000
    assert phy.payload["newick"] == "(t1:0.1,t2:0.2,t3:0.3);"
    # The live advanced_viz ships NO frozen payload (the runtime recomputes it).
    assert "av-1" not in frozen
    # Omitted components ship no payload.
    assert "emb-1" not in frozen and "img-1" not in frozen


def test_offline_export_bindings(offline_export: BundleManifest):
    """The bound ui figure ships a binding table built from the SAME pruned
    frame whose Parquet is in the bundle — live badge, no frozen copy."""
    manifest = offline_export
    assert set(manifest.bindings) == {"fig-1", "fig-2"}
    binding = manifest.bindings["fig-1"]
    assert binding.sampled is False
    assert binding.group_cols == []  # plain scatter: one ungrouped trace
    assert [t.i for t in binding.traces] == [0]
    assert binding.traces[0].group == {}
    assert binding.traces[0].fields == {"x": "bill", "y": "flipper"}
    assert binding.traces[0].customdata == []
    # Stripping convention: bound arrays are ABSENT from the scaffold (the
    # runtime writes them back); layout is the real figure service's.
    trace = binding.scaffold["data"][0]
    assert "x" not in trace and "y" not in trace
    assert binding.scaffold["layout"]["xaxis"]["title"]["text"] == "bill"

    # fig-2's hover column is bound positionally, so the hovertemplate's
    # %{customdata[0]} keeps addressing it after every refill.
    hover = manifest.bindings["fig-2"]
    assert hover.traces[0].customdata == ["species"]
    hover_trace = hover.scaffold["data"][0]
    assert "customdata" not in hover_trace
    assert "species=%{customdata[0]}" in hover_trace["hovertemplate"]

    # Every bound column exists in the bundled DataRef (pruning kept them).
    ref = manifest.data_refs[str(DC_OID)]
    bundled = {c.name for c in ref.columns}
    for t in [*binding.traces, *hover.traces]:
        assert set(t.fields.values()) | set(t.customdata) <= bundled
    # The manifest round-trips with the binding in place.
    BundleManifest.model_validate(manifest.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Binding preflight: the REAL tiers, no bundle
# ---------------------------------------------------------------------------


def _preflight() -> producer_a.ExportResult:
    """The default preflight: binding, viewer-gated, writes nothing."""
    return export_static(
        str(DASHBOARD_OID), check=True, user=ExportUser(id=ObjectId(), is_admin=True)
    )


def test_binding_preflight_decides_every_figure(offline_stack: dict[str, list]):
    """The preflight runs the binder, so its verdicts ARE the build's: bound
    figures live, refused ones frozen with the binder's own cause, and nothing
    left provisional for the caller to hedge about."""
    result = _preflight()
    assert result.manifest is None  # still writes nothing
    rows = {r.component_id: r for r in result.tier_rows}

    for bound in ("fig-1", "fig-2"):
        assert rows[bound].tier is ComponentTier.LIVE
        assert rows[bound].reason is None and rows[bound].detail is None
    # The whole-frame heatmap cannot bind; the reason is the binder's, not a plan.
    assert rows["fig-4"].tier is ComponentTier.FROZEN
    assert rows["fig-4"].reason in (TierReason.BINDING_MISS, TierReason.WHOLE_FRAME_VIZ)
    assert rows["fig-4"].detail and "frozen at the default filter state" in rows["fig-4"].detail
    # `sampled` is only knowable by building the figure the server would build.
    assert rows["fig-3"].tier is ComponentTier.PARTIAL
    assert rows["fig-3"].reason is TierReason.MAX_POINTS
    # The table's DC loaded, so it stays live off the (would-be) bundled Parquet.
    assert rows["tbl-1"].tier is ComponentTier.LIVE
    assert rows["tbl-1"].detail and "renderTableLive" in rows["tbl-1"].detail

    assert not any(row.provisional for row in result.tier_rows)


def test_a_crashing_binder_is_logged_and_named_as_a_crash(
    offline_stack: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """A builder that raises is not a builder that refused. Swallowed silently,
    a bug in ours was reported to the user as this chart's own analysis ("no
    unambiguous trace-group binding") with nothing in the log to contradict it —
    and the preflight presents that as a FINAL verdict."""

    def boom(*args, **kwargs):
        raise RuntimeError("scaffold went sideways")

    monkeypatch.setattr(producer_a, "build_binding_with_reason", boom)

    with caplog.at_level("WARNING", logger="depictio.serverless.producer_a"):
        rows = {r.component_id: r for r in _preflight().tier_rows}

    row = rows["fig-1"]
    assert row.tier is ComponentTier.FROZEN
    assert row.detail and "failed with an error rather than a verdict" in row.detail
    assert "RuntimeError: scaffold went sideways" in row.detail
    assert "no unambiguous" not in row.detail  # not dressed up as a binding miss
    crashes = [r for r in caplog.records if "bind-and-refill crashed" in r.getMessage()]
    assert crashes and crashes[0].exc_info is not None  # with the traceback


def test_binding_preflight_matches_the_build_row_for_row(offline_stack: dict[str, list]):
    """The report and the bundle come out of one body — pin that."""
    preflight = {r.component_id: (r.tier, r.reason, r.detail) for r in _preflight().tier_rows}
    built = export_manifest(str(DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True))
    assert preflight == {r.component_id: (r.tier, r.reason, r.detail) for r in built.tier_rows}


def test_binding_preflight_pays_only_for_the_figures(offline_stack: dict[str, list]):
    """Figures are built (that is the verdict); every other payload is not."""
    _preflight()
    # The two figures that could not bind still went through the server figure
    # pipeline — their `was_sampled` flag is the frozen/partial split.
    assert offline_stack["previews"] == ["scatter:code", "heatmap:ui"]
    # Skipped: frozen card fallbacks, table paging, the advanced_viz data body
    # (and with it the Newick fetch). Celery computes never dispatch either.
    assert offline_stack["cards"] == []
    assert offline_stack["tables"] == []
    assert offline_stack["advanced_viz"] == []


def test_preflight_data_refs_describe_the_bundle_without_serialising_it(
    offline_stack: dict[str, list],
):
    """``serialize=False`` still reports the real schema and row count — it just
    never writes the Parquet the preflight would throw away."""
    stored_metadata = _dashboard_doc()["stored_metadata"]
    refs, blobs, failures, frames = producer_a._bundle_data_refs(stored_metadata, serialize=False)

    assert blobs == {} and failures == {}
    ref = refs[str(DC_OID)]
    assert ref.rows == frames[str(DC_OID)].height == 4
    assert {c.name for c in ref.columns} == {"bill", "flipper", "species", "year", "__code__year"}
    assert ref.companions == {"__code__year": "year"}
    assert ref.size_bytes == 0  # nothing was encoded
    assert ref.aggregation_hash == "agghash-1"  # the server token still holds


def test_a_table_without_a_bundled_dc_is_downgraded_and_frozen(monkeypatch: pytest.MonkeyPatch):
    """The one case that overturns the planned live table: no Parquet to page
    through, so the build has to fall back to the server-rendered snapshot
    ``renderTable`` reads when ``dataRefFor(dcId)`` comes back empty."""
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as core_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod

    doc = {
        "_id": ObjectId(),
        "dashboard_id": DASHBOARD_OID,
        "project_id": PROJECT_OID,
        "title": "Table with no data collection",
        # No dc_id at all: the component never reaches _bundle_data_refs, so it
        # is neither in data_refs nor among the load failures.
        "stored_metadata": [{"index": "tbl-nodc", "component_type": "table"}],
    }
    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([doc]))
    monkeypatch.setattr(core_mod, "dashboards_collection", _FakeTabCollection([]))
    monkeypatch.setattr(db_mod, "deltatables_collection", _FakeCollection([]))
    monkeypatch.setattr(
        db_mod, "projects_collection", _FakeCollection([{"_id": PROJECT_OID, "links": []}])
    )

    def fake_render_table(
        dashboard_id, component_id, request, response, current_user, access_token
    ):
        return {
            "columns": [{"field": "i", "headerName": "i", "type": "numericColumn"}],
            "rows": [{"i": 0}],
            "total": 1,
            "sort_by": None,
            "sort_dir": "desc",
        }

    monkeypatch.setattr(routes_mod, "render_table_endpoint", fake_render_table)

    manifest = export_manifest(
        str(DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True)
    ).manifest
    assert manifest is not None
    entry = manifest.tiers["tbl-nodc"]
    assert entry.tier is ComponentTier.FROZEN
    assert entry.reason is TierReason.UNSUPPORTED
    assert entry.detail and "no bundled data collection" in entry.detail
    # …and the frozen payload the runtime falls back to really is emitted.
    assert manifest.frozen["tbl-nodc"].kind == "table"
    assert manifest.frozen["tbl-nodc"].payload["total"] == 1


def test_export_requires_owner(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    # Real check_project_permission logic over a fake private project.
    monkeypatch.setattr(
        routes_mod,
        "projects_collection",
        _FakeCollection(
            [
                {
                    "_id": PROJECT_OID,
                    "is_public": False,
                    "permissions": {"owners": [], "editors": [], "viewers": []},
                }
            ]
        ),
    )
    viewer = ExportUser(id=ObjectId(), is_admin=False)  # not in the (empty) owner list
    with pytest.raises(ProducerAError, match="permission denied"):
        export_manifest(str(DASHBOARD_OID), viewer)


def test_export_static_rejects_non_single_file():
    with pytest.raises(ProducerAError, match="single-file"):
        export_static("0" * 24, out_path="x.html", mode="static-dir", user=ExportUser(id=None))


def test_export_static_check_without_bind_classifies_without_reading(
    monkeypatch: pytest.MonkeyPatch,
):
    """``bind=False`` keeps the instant, data-free plan (producer B's flavour of
    ``--check``): no data collection is touched, so ui-mode figures come back as
    the provisional ``binding_miss`` the build may still overturn."""
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as core_mod

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    monkeypatch.setattr(core_mod, "dashboards_collection", _FakeTabCollection([]))
    # --check needs only viewer; an admin passes the permission gate without
    # touching projects, but the links preflight still reads the project doc.
    monkeypatch.setattr(
        db_mod, "projects_collection", _FakeCollection([{"_id": PROJECT_OID, "links": []}])
    )

    def no_data(*a, **kw):
        raise AssertionError("bind=False must not load a data collection")

    monkeypatch.setattr(producer_a, "_bundle_data_refs", no_data)

    result = export_static(
        str(DASHBOARD_OID), check=True, bind=False, user=ExportUser(id=ObjectId(), is_admin=True)
    )
    assert result.manifest is None
    rows = {r.component_id: r for r in result.tier_rows}
    assert rows["fig-1"].tier is ComponentTier.FROZEN
    assert rows["fig-1"].reason is TierReason.BINDING_MISS
    assert rows["fig-1"].provisional is True
    assert {r.component_id for r in result.tier_rows} == {
        "card-1",
        "filter-1",
        "text-1",
        "fig-1",
        "fig-2",
        "fig-3",
        "fig-4",
        "tbl-1",
        "av-1",
        "phy-1",
        "emb-1",
        "img-1",
    }


# ---------------------------------------------------------------------------
# Tab family: one bundle per family, data collections deduplicated
# ---------------------------------------------------------------------------

MAIN_TAB_OID = ObjectId("6824cb3b89d2b72169309750")
CHILD_TAB_OID = ObjectId("6824cb3b89d2b72169309751")
FAM_DC_OID = ObjectId("646b0f3c1e4a2d7f8e5b8cb1")


def _fam_dc_config() -> dict[str, Any]:
    return {"type": "table", "delta_location": "memory://famDC", "size_bytes": 11}


def _fam_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {"depth": [1, 2, 3], "shannon": [0.1, 0.2, 0.3], "habitat": ["a", "b", "a"]}
    )


def _main_tab_doc() -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "dashboard_id": MAIN_TAB_OID,
        "project_id": PROJECT_OID,
        "title": "Overview",
        "is_main_tab": True,
        "icon": "mdi:view-dashboard",
        "stored_metadata": [
            {
                "index": "card-main",
                "component_type": "card",
                "wf_id": WF_OID,
                "dc_id": FAM_DC_OID,
                "dc_config": _fam_dc_config(),
                "column_name": "shannon",
                "aggregation": "mean",
            }
        ],
    }


def _child_tab_doc(components: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "dashboard_id": CHILD_TAB_OID,
        "parent_dashboard_id": MAIN_TAB_OID,
        "project_id": PROJECT_OID,
        "title": "Clusters",
        "is_main_tab": False,
        "tab_order": 2,
        "tab_icon": "mdi:set-merge",
        "tab_icon_color": "grape",
        "stored_metadata": components
        if components is not None
        else [
            {
                # Same DC as the main tab's card: it must be bundled ONCE.
                "index": "card-child",
                "component_type": "card",
                "wf_id": WF_OID,
                "dc_id": FAM_DC_OID,
                "dc_config": _fam_dc_config(),
                "column_name": "depth",
                "aggregation": "max",
            },
            {
                "index": "upset-1",
                "component_type": "advanced_viz",
                "viz_kind": "upset_plot",
                "wf_id": WF_OID,
                "dc_id": FAM_DC_OID,
                "dc_config": _fam_dc_config(),
                "config": {"viz_kind": "upset_plot", "set_columns": ["a", "b"]},
            },
        ],
    }


UPSET_RESULT = {"figure": {"data": [], "layout": {}}, "row_count": 3, "compute_ms": 7}


@pytest.fixture
def family_stack(monkeypatch: pytest.MonkeyPatch):
    """Fake instance holding a two-tab family; returns the recorded compute calls."""
    from depictio.api.v1 import celery_tasks as celery_mod
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1 import deltatables_utils as dtu_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as core_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod

    docs = [_main_tab_doc(), _child_tab_doc()]
    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection(docs))
    # get_child_tabs binds the collection at import time on its own module.
    monkeypatch.setattr(core_mod, "dashboards_collection", _FakeTabCollection(docs))
    monkeypatch.setattr(db_mod, "deltatables_collection", _FakeCollection([]))
    monkeypatch.setattr(
        db_mod,
        "projects_collection",
        _FakeCollection([{"_id": PROJECT_OID, "name": "Fake project", "links": []}]),
    )

    frame = _fam_frame()
    monkeypatch.setattr(dtu_mod, "schema_deltatable_lite", lambda **kw: dict(frame.schema))
    monkeypatch.setattr(
        dtu_mod,
        "load_deltatable_lite",
        lambda workflow_id, data_collection_id, metadata=None, select_columns=None, **kw: (
            frame.select(select_columns) if select_columns else frame
        ),
    )
    monkeypatch.setattr(dtu_mod, "_get_aggregation_hash", lambda dc_id: "agghash-fam")
    monkeypatch.setattr(
        routes_mod,
        "bulk_compute_cards",
        lambda dashboard_id, request, current_user, access_token: {
            "values": dict.fromkeys(request["component_ids"], 1.0),
            "secondary_values": {},
            "aggregations": {},
            "filter_applied": False,
            "filter_count": 0,
        },
    )

    calls: list[dict[str, Any]] = []

    def fake_upset(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return dict(UPSET_RESULT)

    monkeypatch.setattr(celery_mod, "compute_upset", fake_upset)
    return calls


def _admin() -> ExportUser:
    return ExportUser(id=ObjectId(), email="owner@example.com", is_admin=True)


def test_family_resolves_from_a_child_id_with_that_child_as_entry(family_stack):
    """Exporting a CHILD opens the bundle on that child and still carries the
    whole family, main tab first."""
    result = export_manifest(str(CHILD_TAB_OID), _admin())
    manifest = result.manifest
    assert manifest is not None

    assert manifest.dashboard.id == str(CHILD_TAB_OID)  # entry stays the requested tab
    assert manifest.dashboard.title == "Clusters"
    assert [t.id for t in manifest.tabs] == [str(MAIN_TAB_OID), str(CHILD_TAB_OID)]
    assert [t.is_main_tab for t in manifest.tabs] == [True, False]
    assert [t.tab_order for t in manifest.tabs] == [0, 2]
    # The entry tab is duplicated between `dashboard` and `tabs`, per contract.
    assert manifest.tabs[1].doc == manifest.dashboard.doc
    assert manifest.tabs[1].icon == "mdi:set-merge"
    assert manifest.tabs[1].icon_color == "grape"
    # Every tab's document rides along, permissions stripped like the entry's.
    assert "permissions" not in manifest.tabs[0].doc
    assert manifest.tabs[0].doc["stored_metadata"][0]["index"] == "card-main"

    # Components merge across the family, each row naming its tab.
    assert set(manifest.tiers) == {"card-main", "card-child", "upset-1"}
    by_id = {row.component_id: row for row in result.tier_rows}
    assert by_id["card-main"].tab_id == str(MAIN_TAB_OID)
    assert by_id["card-child"].tab_id == str(CHILD_TAB_OID)
    assert [tab.id for tab in result.tabs] == [str(MAIN_TAB_OID), str(CHILD_TAB_OID)]

    BundleManifest.model_validate(manifest.model_dump(mode="json"))


def test_family_bundles_a_shared_data_collection_once(family_stack):
    """The size win: two tabs reading one DC inline one Parquet blob, not two."""
    manifest = export_manifest(str(MAIN_TAB_OID), _admin()).manifest
    assert manifest is not None
    assert list(manifest.data_refs) == [str(FAM_DC_OID)]
    assert list(manifest.inline_blobs) == [f"dc_{FAM_DC_OID}"]
    # Pruned to the union of BOTH tabs' cards.
    assert {c.name for c in manifest.data_refs[str(FAM_DC_OID)].columns} == {"shannon", "depth"}


def test_single_tab_export_carries_only_the_requested_tab(family_stack):
    manifest = export_manifest(str(MAIN_TAB_OID), _admin(), single_tab=True).manifest
    assert manifest is not None
    assert manifest.tabs == []  # empty == single-tab bundle, per the contract
    assert set(manifest.tiers) == {"card-main"}


def test_family_provenance_records_the_export(family_stack, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(producer_a, "_public_base_url", lambda: "https://demo.example.org")
    manifest = export_manifest(str(CHILD_TAB_OID), _admin()).manifest
    assert manifest is not None
    prov = manifest.provenance
    assert prov.exported_by == "owner@example.com"
    assert prov.exported_at == manifest.built_at
    assert prov.project_name == "Fake project"
    assert prov.source == "https://demo.example.org"
    assert prov.dashboard_url == f"https://demo.example.org/dashboard/{CHILD_TAB_OID}"


def test_provenance_omits_an_internal_only_instance_url(family_stack, monkeypatch):
    """No declared public_url ⇒ no URL at all: an internal compose hostname in a
    shipped bundle looks like a working link and is not one."""
    monkeypatch.setattr(producer_a, "_public_base_url", lambda: None)
    manifest = export_manifest(str(MAIN_TAB_OID), _admin()).manifest
    assert manifest is not None
    assert manifest.provenance.source is None
    assert manifest.provenance.dashboard_url is None


def test_family_component_id_collision_fails_loudly():
    """Component-keyed manifest sections merge flat across tabs, which only
    works because ids are uuids. A collision must not be silent."""
    tab_a = FamilyTab(doc=_main_tab_doc(), tab_order=0, is_main_tab=True)
    clash = _child_tab_doc([{"index": "card-main", "component_type": "card"}])
    tab_b = FamilyTab(doc=clash, tab_order=2, is_main_tab=False)
    with pytest.raises(ProducerAError, match="appears on two tabs"):
        family_components([tab_a, tab_b])


def test_family_preflight_reports_every_tab(family_stack):
    result = export_static(str(MAIN_TAB_OID), check=True, user=_admin())
    assert result.manifest is None
    assert [tab.title for tab in result.tabs] == ["Overview", "Clusters"]
    assert {row.tab_id for row in result.tier_rows} == {str(MAIN_TAB_OID), str(CHILD_TAB_OID)}


# ---------------------------------------------------------------------------
# Celery-computed advanced_viz kinds: pre-exported into a frozen payload
# ---------------------------------------------------------------------------


def test_celery_compute_is_frozen_at_export_time(family_stack):
    """The frozen payload is exactly what the poll endpoint returns to the
    renderer — ``{"result": <task return value>}`` — so the runtime's
    dispatch/poll shim needs no renderer change."""
    manifest = export_manifest(str(MAIN_TAB_OID), _admin()).manifest
    assert manifest is not None

    frozen = manifest.frozen["upset-1"]
    assert frozen.kind == "compute"
    assert frozen.payload == {"result": UPSET_RESULT}

    tier = manifest.tiers["upset-1"]
    assert tier.tier is ComponentTier.FROZEN
    assert tier.reason is TierReason.CELERY_COMPUTE
    assert tier.detail and "computed at export time" in tier.detail

    # Called with the renderer's first-paint payload at the default filter state.
    assert len(family_stack) == 1
    payload = family_stack[0]
    assert payload["dc_id"] == str(FAM_DC_OID)
    assert payload["set_columns"] == ["a", "b"]
    assert payload["sort_by"] == "cardinality"
    assert payload["filter_metadata"] == []


def test_a_failing_celery_compute_degrades_to_omitted(
    family_stack, monkeypatch: pytest.MonkeyPatch
):
    """A compute that raises must not sink the export — the component is
    omitted with the error, everything else still ships."""
    from depictio.api.v1 import celery_tasks as celery_mod

    def boom(payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("plotly-upset exploded")

    monkeypatch.setattr(celery_mod, "compute_upset", boom)
    manifest = export_manifest(str(MAIN_TAB_OID), _admin()).manifest
    assert manifest is not None

    assert "upset-1" not in manifest.frozen
    tier = manifest.tiers["upset-1"]
    assert tier.tier is ComponentTier.OMITTED
    assert tier.reason is TierReason.CELERY_COMPUTE
    assert tier.detail and "plotly-upset exploded" in tier.detail
    # The rest of the family is unaffected.
    assert manifest.tiers["card-main"].tier is ComponentTier.LIVE
    assert list(manifest.data_refs) == [str(FAM_DC_OID)]


def test_an_exhausted_compute_budget_omits_without_computing(family_stack):
    """Wall-clock guard: once the export's total budget is spent, the remaining
    computes are skipped (and say so) rather than running the task past the
    Celery job's own time limit."""
    manifest = export_manifest(
        str(MAIN_TAB_OID), _admin(), budget=ComputeBudget(per_component=30.0, total=0.0)
    ).manifest
    assert manifest is not None
    assert family_stack == []  # the task function was never called
    tier = manifest.tiers["upset-1"]
    assert tier.tier is ComponentTier.OMITTED
    assert tier.reason is TierReason.CELERY_COMPUTE
    assert tier.detail and "budget" in tier.detail


def test_a_compute_over_its_per_component_budget_is_abandoned(
    family_stack, monkeypatch: pytest.MonkeyPatch
):
    import time as _time

    from depictio.api.v1 import celery_tasks as celery_mod

    monkeypatch.setattr(
        celery_mod, "compute_upset", lambda payload: _time.sleep(5) or dict(UPSET_RESULT)
    )
    manifest = export_manifest(
        str(MAIN_TAB_OID), _admin(), budget=ComputeBudget(per_component=0.2, total=10.0)
    ).manifest
    assert manifest is not None
    assert "upset-1" not in manifest.frozen
    assert manifest.tiers["upset-1"].tier is ComponentTier.OMITTED
    assert manifest.tiers["upset-1"].detail and "budget" in manifest.tiers["upset-1"].detail


def test_compute_budget_reads_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEPICTIO_SERVERLESS_COMPUTE_BUDGET_S", "45")
    monkeypatch.setenv("DEPICTIO_SERVERLESS_COMPUTE_TOTAL_BUDGET_S", "90")
    budget = ComputeBudget.from_env()
    assert (budget.per_component, budget.total) == (45.0, 90.0)
    assert budget.slice() == 45.0
    budget.charge(80.0)
    assert budget.remaining == 10.0
    assert budget.slice() == 10.0  # the per-component cap is clipped to what is left

    monkeypatch.setenv("DEPICTIO_SERVERLESS_COMPUTE_BUDGET_S", "not-a-number")
    assert ComputeBudget.from_env().per_component == 120.0  # falls back to the default


# ---------------------------------------------------------------------------
# Bundle size ceilings (RFC §8.1)
#
# A `single-file` bundle is one HTML string with every data collection base64'd
# inside it, so an oversized export has to be refused BEFORE the bytes exist.
# The fixture below is three table-only data collections — a table bundles its
# DC whole and ships no frozen payload, so the whole bundle is data and no
# endpoint body has to be faked.
# ---------------------------------------------------------------------------


SIZE_DASHBOARD_OID = ObjectId("6824cb3b89d2b72169309799")
SIZE_WF_OID = ObjectId("646b0f3c1e4a2d7f8e5b8d01")
SIZE_DC_OIDS = [
    ObjectId("646b0f3c1e4a2d7f8e5b8e01"),
    ObjectId("646b0f3c1e4a2d7f8e5b8e02"),
    ObjectId("646b0f3c1e4a2d7f8e5b8e03"),
]
# ~0.70 MiB of base64 per data collection at 5 columns, which lets a 1 MB
# ceiling land BETWEEN two of them — the point of the fail-fast test.
SIZE_FRAME_ROWS = 120_000
_SIZED_FRAMES: dict[int, pl.DataFrame] = {}


def _sized_frame(seed: int) -> pl.DataFrame:
    """A frame with a data collection's compressibility, not a random one.

    The estimate under test is a *density* (RFC §8.1: ~2 bytes per cell as
    snappy Parquet), so a frame of incompressible noise would measure the wrong
    thing — real bundled columns are low-cardinality categoricals and bounded
    numerics, which is what that number was measured on. Seeded, and cached
    because three of these are rebuilt by every test that touches the fixture.
    """
    if seed not in _SIZED_FRAMES:
        rng = random.Random(seed)
        rows = SIZE_FRAME_ROWS
        _SIZED_FRAMES[seed] = pl.DataFrame(
            {
                "bill": [round(rng.uniform(30, 60), 1) for _ in range(rows)],
                "flipper": [rng.randint(170, 235) for _ in range(rows)],
                "species": [rng.choice(["Adelie", "Gentoo", "Chinstrap"]) for _ in range(rows)],
                "island": [rng.choice(["Torgersen", "Biscoe", "Dream"]) for _ in range(rows)],
                "year": [rng.choice([2021, 2022, 2023]) for _ in range(rows)],
            }
        )
    return _SIZED_FRAMES[seed]


@pytest.fixture
def size_stack(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Three sizeable table-only DCs, with the runtime floor pinned to zero.

    Pinning the floor keeps the ceiling arithmetic about the data alone: the
    real floor is ~7.7 MB, which would swallow any ceiling small enough to test
    against a fixture. That the floor is part of the total is asserted on its
    own (:func:`test_the_runtime_floor_counts_towards_the_ceiling`).

    Returns the list of dc_ids as they are loaded, so a refusal can be pinned to
    the data collection it happened on.
    """
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1 import deltatables_utils as dtu_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as core_mod

    doc = {
        "_id": ObjectId(),
        "dashboard_id": SIZE_DASHBOARD_OID,
        "project_id": PROJECT_OID,
        "title": "Three big tables",
        "stored_metadata": [
            {
                "index": f"tbl-{i}",
                "component_type": "table",
                "wf_id": SIZE_WF_OID,
                "dc_id": dc_oid,
                "dc_config": {"type": "table", "delta_location": f"memory://big{i}"},
            }
            for i, dc_oid in enumerate(SIZE_DC_OIDS)
        ],
    }
    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([doc]))
    monkeypatch.setattr(core_mod, "dashboards_collection", _FakeTabCollection([]))
    monkeypatch.setattr(db_mod, "deltatables_collection", _FakeCollection([]))
    monkeypatch.setattr(
        db_mod, "projects_collection", _FakeCollection([{"_id": PROJECT_OID, "links": []}])
    )

    frames = {str(oid): _sized_frame(i) for i, oid in enumerate(SIZE_DC_OIDS)}
    loaded: list[str] = []

    def fake_schema(workflow_id, data_collection_id, init_data):
        return dict(frames[str(data_collection_id)].schema)

    def fake_load(workflow_id, data_collection_id, metadata=None, select_columns=None, **kw):
        loaded.append(str(data_collection_id))
        frame = frames[str(data_collection_id)]
        return frame.select(select_columns) if select_columns else frame

    monkeypatch.setattr(dtu_mod, "schema_deltatable_lite", fake_schema)
    monkeypatch.setattr(dtu_mod, "load_deltatable_lite", fake_load)
    monkeypatch.setattr(dtu_mod, "_get_aggregation_hash", lambda dc_id: "agghash-big")
    # The floor is real everywhere else; here it is the data that is under test.
    monkeypatch.setattr(producer_a, "runtime_floor_bytes", lambda: 0)
    return loaded


def _set_ceilings(monkeypatch: pytest.MonkeyPatch, *, warn_mb: int, max_mb: int) -> None:
    """Move both ceilings on the real settings object, as a deployment would."""
    from depictio.api.v1.configs.config import settings

    monkeypatch.setattr(settings.performance, "static_bundle_warn_mb", warn_mb)
    monkeypatch.setattr(settings.performance, "static_bundle_max_mb", max_mb)


def _build() -> producer_a.ExportResult:
    return export_manifest(str(SIZE_DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True))


def test_the_hard_ceiling_refuses_before_the_whole_payload_is_encoded(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch
):
    """The point of the guard: a bundle that would blow the ceiling is never
    materialised. One DC fits under 1 MB, two do not — so the export must die on
    the second, with the third never even read off Delta."""
    _set_ceilings(monkeypatch, warn_mb=0, max_mb=1)

    with pytest.raises(ProducerAError) as excinfo:
        _build()

    assert len(size_stack) == 2 < len(SIZE_DC_OIDS)  # stopped mid-loop, not after
    message = str(excinfo.value)
    assert "static bundle too large" in message
    assert "2 of 3 data collection(s)" in message
    # Actionable: which DCs dominate, how big they are, and the way out.
    assert str(SIZE_DC_OIDS[0]) in message
    assert f"{SIZE_FRAME_ROWS} rows × 5 columns" in message
    assert "performance.static_bundle_max_mb" in message


def test_a_zero_hard_ceiling_disables_the_check(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch
):
    """0 disables, as it does for the other producer-side caps."""
    _set_ceilings(monkeypatch, warn_mb=0, max_mb=0)

    manifest = _build().manifest

    assert manifest is not None
    assert len(size_stack) == len(SIZE_DC_OIDS)
    assert len(manifest.inline_blobs) == len(SIZE_DC_OIDS)
    # …and the bundle really is past what the 1 MB ceiling above refused.
    assert sum(len(blob) for blob in manifest.inline_blobs.values()) > producer_a.BYTES_PER_MB


def test_the_soft_ceiling_reports_and_builds_anyway(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Past the soft ceiling a bundle still works — it just stops travelling
    well — so it is reported, not refused."""
    _set_ceilings(monkeypatch, warn_mb=1, max_mb=0)

    with caplog.at_level("WARNING", logger="depictio.serverless.producer_a"):
        manifest = _build().manifest

    assert manifest is not None
    assert len(manifest.inline_blobs) == len(SIZE_DC_OIDS)  # nothing was refused
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("past the 1.0 MB soft ceiling" in w for w in warnings), warnings
    assert any("performance.static_bundle_warn_mb" in w for w in warnings)


def test_a_bundle_under_both_ceilings_is_silent(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    _set_ceilings(monkeypatch, warn_mb=25, max_mb=100)

    with caplog.at_level("WARNING", logger="depictio.serverless.producer_a"):
        result = _build()

    assert result.manifest is not None
    assert result.size is not None and result.size.verdict == producer_a.SIZE_OK
    assert result.size.estimated is False  # a build measures, it does not guess
    assert not [r for r in caplog.records if "static bundle" in r.getMessage()]


def test_the_preflight_estimate_tracks_the_bundle_it_predicts(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch
):
    """The assertion that makes the estimate worth showing: the number a modal
    gets from the preflight is the size of the file the build then writes.

    The preflight prunes every frame but serialises none, so all it can apply is
    the RFC §8.1 density — rows × columns × 2 bytes × 4/3 — and that density is
    an order of magnitude, not a prediction. It over-predicts compressible
    frames (this fixture's, by ~2.2x) and under-predicts incompressible ones, so
    the **data** part can only be pinned to a factor of 3: it says the number is
    the right size, not that it is right. Erring high is the safe direction for
    a warning.

    The **total** a user is actually shown is better than that, and structurally
    so: it adds the exact runtime floor (~7.7 MB, most of the file on any
    dashboard the reference families' size), which can only shrink the relative
    error. That is asserted both ways — as a stated 50% bound, and as the
    invariant that the total is closer than the data part it contains.
    """
    _set_ceilings(monkeypatch, warn_mb=25, max_mb=0)

    preflight = export_static(
        str(SIZE_DASHBOARD_OID), check=True, user=ExportUser(id=ObjectId(), is_admin=True)
    )
    built = _build()

    assert preflight.size is not None and built.size is not None
    assert preflight.size.estimated is True and built.size.estimated is False
    # The build's own figure is not an estimate at all: it is the base64 in the
    # manifest, which is what lands in the HTML.
    manifest = built.manifest
    assert manifest is not None
    measured = sum(len(blob) for blob in manifest.inline_blobs.values())
    assert built.size.data_bytes == measured

    assert 1 / 3 <= preflight.size.data_bytes / measured <= 3

    # The fixture pins the floor to 0 so the ceilings are testable; the accuracy
    # claim is about the real one, so put it back for this comparison.
    from depictio.serverless.producer_b import runtime_floor_bytes

    floor = runtime_floor_bytes()
    data_error = abs(preflight.size.data_bytes - measured) / measured
    total_error = abs(preflight.size.data_bytes - measured) / (floor + measured)
    assert total_error < data_error
    assert total_error < 0.5


def test_the_runtime_floor_counts_towards_the_ceiling():
    """The floor is the bundle's biggest single line item on any small dashboard
    (~7.7 MB, RFC §8.1), so a total that left it out would be the wrong number
    to compare a ceiling against. Read from the built runtime rather than
    hardcoded, so it tracks the runtime instead of lagging it."""
    from depictio.serverless.producer_b import RUNTIME_FLOOR_FALLBACK_BYTES, runtime_floor_bytes

    floor = runtime_floor_bytes()
    assert floor > 0
    # Whether the template is built here or not, the floor is the §8.1 order of
    # magnitude — a floor an order out would silently move both ceilings.
    assert 4 * producer_a.BYTES_PER_MB < floor < 32 * producer_a.BYTES_PER_MB
    assert producer_a.estimate_bundle_size({}).total_bytes == floor
    assert RUNTIME_FLOOR_FALLBACK_BYTES == int(7.7 * producer_a.BYTES_PER_MB)


def test_the_preflight_is_capped_by_the_same_ceiling_as_the_build(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch
):
    """The preflight is the OPEN path — viewer-gated, and an anonymous visitor
    in public mode — and it loads every data collection uncapped while holding
    each pruned frame for the binder. Uncompressed Polars frames peak higher
    than the base64 a build accumulates, so leaving the ceiling on the
    serialising branch alone would mean the cheapest request to make is the one
    nothing bounds. It has to stop at the data collection that broke it, exactly
    as the build does."""
    _set_ceilings(monkeypatch, warn_mb=0, max_mb=1)

    with pytest.raises(BundleTooLargeError) as excinfo:
        export_static(
            str(SIZE_DASHBOARD_OID), check=True, user=ExportUser(id=ObjectId(), is_admin=True)
        )

    assert len(size_stack) < len(SIZE_DC_OIDS)  # stopped mid-loop, not after
    message = str(excinfo.value)
    assert "static bundle too large" in message
    # …and says which of the two numbers this was, because they differ in kind:
    # the build measures base64, this applies the RFC §8.1 density.
    assert "ESTIMATED" in message and "preflight was refused" in message
    assert "performance.static_bundle_max_mb" in message
    # A caller that catches the family error still catches this one.
    assert isinstance(excinfo.value, ProducerAError)


def test_the_preflight_charges_every_data_collection_the_build_charges(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch
):
    """Same ceiling over the same set: both totals are charged per data
    collection as it is loaded, before anything is dropped for figures that
    failed to bind, so a preflight cannot come back "ok" about a build that
    would be refused. The fixture's three DCs are charged one by one on both
    paths — the refusal lands on the first over-ceiling DC either way."""
    _set_ceilings(monkeypatch, warn_mb=0, max_mb=1)

    with pytest.raises(BundleTooLargeError) as preflight_exc:
        export_static(
            str(SIZE_DASHBOARD_OID), check=True, user=ExportUser(id=ObjectId(), is_admin=True)
        )
    with pytest.raises(BundleTooLargeError) as build_exc:
        _build()

    # Both name the same ceiling and the same denominator; only the numerator
    # differs (estimate vs measurement), which is why the estimate refuses
    # first — it runs high on compressible data, the safe direction.
    for exc in (preflight_exc, build_exc):
        assert "of 3 data collection(s)" in str(exc.value)
        assert "exceeds the 1.0 MB ceiling" in str(exc.value)


def test_the_report_names_the_ceiling_that_was_crossed(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """ "Too big to mail" and "too big to build" are different problems, so the
    soft-ceiling report must not describe itself as the second. Past the HARD
    ceiling nothing is reported at all — the running total refuses first, on
    both paths (see the two tests above)."""
    _set_ceilings(monkeypatch, warn_mb=1, max_mb=0)

    with caplog.at_level("WARNING", logger="depictio.serverless.producer_a"):
        result = export_static(
            str(SIZE_DASHBOARD_OID), check=True, user=ExportUser(id=ObjectId(), is_admin=True)
        )

    assert len(result.tier_rows) == len(SIZE_DC_OIDS)  # the report survived
    assert result.size is not None and result.size.verdict == producer_a.SIZE_OVER_SOFT_LIMIT
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("past the 1.0 MB soft ceiling" in w for w in warnings), warnings
    # An estimate says so, and never claims the build was refused.
    assert any("is estimated at" in w for w in warnings)
    assert not any("would be refused" in w for w in warnings)


def test_the_rendered_bundle_is_measured_before_it_is_written(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """The hole the earlier checks cannot see: the running total and
    ``measured_bundle_size`` only ever count base64 Parquet, so everything else
    in the file is unbounded by them — the frozen payloads, and above all a
    code-mode figure built with ``full_load=True`` whose binding then missed,
    which embeds every point it draws in the manifest JSON. A ceiling documented
    as "the size above which an export is refused" has to be applied to the
    thing that has that size."""
    _set_ceilings(monkeypatch, warn_mb=0, max_mb=4)
    # Stands in for the payloads no earlier check counts: the data is well under
    # the ceiling (~2.1 MB of base64 over three DCs) and the FILE is not.
    monkeypatch.setattr(producer_a, "render_bundle_html", lambda manifest: "x" * (6 << 20))
    out = tmp_path / "bundle.html"

    with pytest.raises(BundleTooLargeError) as excinfo:
        export_static(
            str(SIZE_DASHBOARD_OID),
            out_path=out,
            user=ExportUser(id=ObjectId(), is_admin=True),
        )

    assert not out.exists()  # refused BEFORE the write, not cleaned up after
    message = str(excinfo.value)
    assert "the rendered bundle is 6.0 MB" in message  # the real size, named
    assert "4.0 MB ceiling" in message
    assert "performance.static_bundle_max_mb" in message


def test_a_rendered_bundle_under_the_ceiling_is_written(
    size_stack: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """The other half of the check: it refuses the oversized file and nothing
    else. Same stack, a small render, and the bundle lands on disk."""
    _set_ceilings(monkeypatch, warn_mb=0, max_mb=4)
    monkeypatch.setattr(producer_a, "render_bundle_html", lambda manifest: "<html>ok</html>")
    out = tmp_path / "bundle.html"

    result = export_static(
        str(SIZE_DASHBOARD_OID), out_path=out, user=ExportUser(id=ObjectId(), is_admin=True)
    )

    assert result.manifest is not None
    assert out.read_text() == "<html>ok</html>"


def test_size_verdict_thresholds():
    """The three buckets the preflight hands the frontend, and what 0 means."""
    mb = producer_a.BYTES_PER_MB
    assert producer_a.size_verdict(10 * mb, 25 * mb, 100 * mb) == producer_a.SIZE_OK
    assert producer_a.size_verdict(25 * mb, 25 * mb, 100 * mb) == producer_a.SIZE_OK  # at, not over
    assert producer_a.size_verdict(26 * mb, 25 * mb, 100 * mb) == producer_a.SIZE_OVER_SOFT_LIMIT
    assert producer_a.size_verdict(101 * mb, 25 * mb, 100 * mb) == producer_a.SIZE_WOULD_BE_REFUSED
    # 0 disables that ceiling without disabling the other one.
    assert producer_a.size_verdict(500 * mb, 0, 100 * mb) == producer_a.SIZE_WOULD_BE_REFUSED
    assert producer_a.size_verdict(500 * mb, 25 * mb, 0) == producer_a.SIZE_OVER_SOFT_LIMIT
    assert producer_a.size_verdict(500 * mb, 0, 0) == producer_a.SIZE_OK


# ---------------------------------------------------------------------------
# Live-stack smoke test (skips cleanly when MongoDB is not reachable)
# ---------------------------------------------------------------------------


def _mongo_reachable() -> bool:
    try:
        import pymongo

        from depictio.api.v1.configs.config import MONGODB_URL

        client = pymongo.MongoClient(MONGODB_URL, serverSelectionTimeoutMS=500)
        client.admin.command("ping")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _mongo_reachable(), reason="MongoDB not reachable (live stack absent)")
def test_export_check_against_live_instance():
    """Preflight a real seeded dashboard end-to-end (Mongo only, no S3 reads).

    ``bind=False`` on purpose: the binding preflight reads the Delta tables, and
    this test only assumes a reachable MongoDB.
    """
    from depictio.api.v1.db import dashboards_collection

    doc = dashboards_collection.find_one({})
    if not doc:
        pytest.skip("no dashboards seeded in the reachable MongoDB")
    result = export_static(str(doc["dashboard_id"]), check=True, bind=False, user=None)
    assert result.manifest is None
    assert len(result.tier_rows) == len(doc.get("stored_metadata") or [])


def test_a_cold_multiqc_prerender_is_named_not_leaked_as_a_validation_error(monkeypatch):
    """`render_multiqc_endpoint` answers with a JSONResponse while the
    pre-render for that collection is still building. Pydantic used to reject
    it deep inside `FrozenPayload`, so the tile was omitted carrying a
    `dict_type` validation error — true, and useless to the reader."""
    from starlette.responses import JSONResponse

    routes_mod = producer_a._routes()
    monkeypatch.setattr(
        routes_mod, "_resolve_selected_keys", lambda comp: (None, None, None, False)
    )
    monkeypatch.setattr(
        routes_mod,
        "render_multiqc_endpoint",
        lambda *a, **k: JSONResponse({"status": "building"}, status_code=202),
    )
    with pytest.raises(ProducerAError, match="pre-render for this data collection"):
        producer_a._freeze_multiqc(
            ObjectId(), {"index": "mqc-1"}, ExportUser(id=ObjectId(), is_admin=True)
        )
