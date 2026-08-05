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

A final smoke test runs ``export_static(check=True)`` against a real MongoDB
when one is reachable (CI provides the stack; a bare box skips cleanly).
"""

from __future__ import annotations

import base64
import io
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
from depictio.serverless.producer_a import (
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
        ({"component_type": "table"}, ComponentTier.FROZEN, TierReason.UNSUPPORTED),
        ({"component_type": "figure", "mode": "ui"}, ComponentTier.FROZEN, TierReason.BINDING_MISS),
        # mode defaults to "ui"
        ({"component_type": "figure"}, ComponentTier.FROZEN, TierReason.BINDING_MISS),
        ({"component_type": "figure", "mode": "code"}, ComponentTier.FROZEN, TierReason.CODE_MODE),
        ({"component_type": "multiqc"}, ComponentTier.FROZEN, TierReason.MULTIQC),
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
    got_tier, got_reason, detail = classify_stored_component(comp)
    assert got_tier is tier
    assert got_reason is reason
    if tier is not ComponentTier.LIVE:
        assert detail  # every degradation carries a human explanation


def test_classify_stored_metadata_keys_by_index():
    rows = classify_stored_metadata(
        [
            {"index": "c1", "component_type": "card", "title": "Mean"},
            {"component_type": "table"},  # no index -> positional fallback
        ]
    )
    assert [r.component_id for r in rows] == ["c1", "component-1"]
    assert rows[0].tier is ComponentTier.LIVE
    assert rows[1].tier is ComponentTier.FROZEN


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
    dc_a, dc_b = ObjectId(), ObjectId()
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
        # …but code-mode figures, tables and text contribute nothing.
        {"component_type": "figure", "mode": "code", "dc_id": dc_a, "code_content": "fig = 1"},
        {"component_type": "table", "dc_id": dc_a},
        {"component_type": "text", "dc_id": dc_a},
    ]
    sets = live_column_sets(stored)
    assert sets[str(dc_a)] == {"bill", "isl", "mass", "q", "year", "flipper"}
    assert sets[str(dc_b)] == {"species"}
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
                # Refused: hover_data makes 2-D customdata, which the static
                # runtime cannot refill -> frozen with binding_miss.
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
def offline_export(monkeypatch: pytest.MonkeyPatch) -> BundleManifest:
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

    def fake_bulk_cards(dashboard_id, request, current_user, access_token):
        assert request["filters"] == []
        assert request["component_ids"] == ["card-1"]
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

    result = export_manifest(str(DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True))
    assert result.manifest is not None
    assert av_calls == ["phylogenetic"]
    # The table freeze paged through the 500-row endpoint clamp.
    assert table_calls == [(0, 500), (500, 500)]
    # Only the unbindable figures fell back to the frozen figure pipeline —
    # the bound fig-1 never touched it (it ships a binding table instead).
    assert preview_calls == ["scatter:ui", "scatter:code", "heatmap:ui"]
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
    # The bound figure was upgraded to LIVE (bind-and-refill, RFC §4).
    assert tiers["fig-1"].tier is ComponentTier.LIVE
    assert tiers["fig-1"].reason is None and tiers["fig-1"].detail is None
    # The refused figures froze with binding_miss (same wording as producer B).
    for refused in ("fig-2", "fig-4"):
        assert tiers[refused].tier is ComponentTier.FROZEN
        assert tiers[refused].reason is TierReason.BINDING_MISS
        assert tiers[refused].detail and "binding" in tiers[refused].detail
    # Sampled frozen code figure was refined to partial (FIGURE_MAX_POINTS).
    assert tiers["fig-3"].tier is ComponentTier.PARTIAL
    assert tiers["fig-3"].reason is TierReason.MAX_POINTS
    assert tiers["tbl-1"].tier is ComponentTier.FROZEN
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
    # Table paged to the endpoint clamp, all 700 rows captured.
    tbl = frozen["tbl-1"].payload
    assert tbl["total"] == TABLE_TOTAL
    assert len(tbl["rows"]) == TABLE_TOTAL
    assert tbl["rows"][0] == {"i": 0} and tbl["rows"][-1] == {"i": TABLE_TOTAL - 1}
    # Refused/code figures came straight from build_figure_preview; the bound
    # fig-1 ships NO frozen payload (the runtime refills from the Parquet).
    assert "fig-1" not in frozen
    assert frozen["fig-2"].kind == "figure"
    assert frozen["fig-2"].payload["metadata"]["was_sampled"] is False
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
    assert set(manifest.bindings) == {"fig-1"}
    binding = manifest.bindings["fig-1"]
    assert binding.sampled is False
    assert binding.group_cols == []  # plain scatter: one ungrouped trace
    assert [t.i for t in binding.traces] == [0]
    assert binding.traces[0].group == {}
    assert binding.traces[0].fields == {"x": "bill", "y": "flipper"}
    # Stripping convention: bound arrays are ABSENT from the scaffold (the
    # runtime writes them back); layout is the real figure service's.
    trace = binding.scaffold["data"][0]
    assert "x" not in trace and "y" not in trace
    assert binding.scaffold["layout"]["xaxis"]["title"]["text"] == "bill"
    # Every bound column exists in the bundled DataRef (pruning kept them).
    ref = manifest.data_refs[str(DC_OID)]
    bundled = {c.name for c in ref.columns}
    for t in binding.traces:
        assert set(t.fields.values()) <= bundled
    # The manifest round-trips with the binding in place.
    BundleManifest.model_validate(manifest.model_dump(mode="json"))


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


def test_export_static_check_classifies_without_building(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as core_mod

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    monkeypatch.setattr(core_mod, "dashboards_collection", _FakeTabCollection([]))
    # --check needs only viewer; an admin passes the permission gate without
    # touching projects, but the links preflight still reads the project doc.
    monkeypatch.setattr(
        db_mod, "projects_collection", _FakeCollection([{"_id": PROJECT_OID, "links": []}])
    )
    result = export_static(
        str(DASHBOARD_OID), check=True, user=ExportUser(id=ObjectId(), is_admin=True)
    )
    assert result.manifest is None
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
    """Preflight a real seeded dashboard end-to-end (Mongo only, no S3 writes)."""
    from depictio.api.v1.db import dashboards_collection

    doc = dashboards_collection.find_one({})
    if not doc:
        pytest.skip("no dashboards seeded in the reachable MongoDB")
    result = export_static(str(doc["dashboard_id"]), check=True, user=None)
    assert result.manifest is None
    assert len(result.tier_rows) == len(doc.get("stored_metadata") or [])
