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
from depictio.serverless.producer_a import (
    ExportUser,
    ProducerAError,
    advanced_viz_request,
    classify_stored_component,
    classify_stored_metadata,
    export_manifest,
    export_static,
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
        (
            {"component_type": "advanced_viz", "viz_kind": "volcano"},
            ComponentTier.FROZEN,
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


def test_live_column_sets_covers_only_live_data_components():
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
        # frozen/omitted types contribute no live columns
        {"component_type": "figure", "dc_id": dc_a, "dict_kwargs": {"x": "flipper"}},
        {"component_type": "table", "dc_id": dc_a},
        {"component_type": "text", "dc_id": dc_a},
    ]
    sets = live_column_sets(stored)
    assert sets[str(dc_a)] == {"bill", "isl", "mass", "q", "year"}
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


DASHBOARD_OID = ObjectId("6824cb3b89d2b72169309737")
PROJECT_OID = ObjectId("646b0f3c1e4a2d7f8e5b8c9d")
WF_OID = ObjectId("646b0f3c1e4a2d7f8e5b8c01")
DC_OID = ObjectId("646b0f3c1e4a2d7f8e5b8ca1")
AV_DC_OID = ObjectId("646b0f3c1e4a2d7f8e5b8ca2")

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


def _dashboard_doc() -> dict[str, Any]:
    dc_config = {"type": "table", "delta_location": "memory://dcA", "size_bytes": 123}
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
                "index": "tbl-1",
                "component_type": "table",
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
            },
            {
                "index": "av-1",
                "component_type": "advanced_viz",
                "viz_kind": "volcano",
                "wf_id": WF_OID,
                "dc_id": AV_DC_OID,
                "config": {"viz_kind": "volcano", "x_col": "lfc", "y_col": "q_val"},
            },
            {
                "index": "emb-1",
                "component_type": "advanced_viz",
                "viz_kind": "embedding",
                "wf_id": WF_OID,
                "dc_id": AV_DC_OID,
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
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    monkeypatch.setattr(db_mod, "deltatables_collection", _FakeCollection([]))

    frame = _frame()

    def fake_schema(workflow_id, data_collection_id, init_data):
        assert str(data_collection_id) == str(DC_OID)
        assert init_data[str(DC_OID)]["delta_location"] == "memory://dcA"
        return dict(frame.schema)

    def fake_load(workflow_id, data_collection_id, metadata=None, select_columns=None, **kw):
        assert metadata is None  # bundling loads the unfiltered frame
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

    def fake_figure_preview(payload):
        assert payload["filter_metadata"] == []
        assert payload["metadata"]["dc_id"] == str(DC_OID)
        assert payload["metadata"]["visu_type"] == "scatter"
        return {
            "figure": {"data": [], "layout": {}},
            "metadata": {"visu_type": "scatter", "filter_applied": False, "was_sampled": True},
        }

    def fake_av_data(response, payload, current_user, access_token):
        assert payload["viz_kind"] == "volcano"
        assert payload["columns"] == ["lfc", "q_val"]
        assert payload["roles"] == {"x": "lfc", "y": "q_val"}
        assert payload["filter_metadata"] == []
        return {
            "columns": ["lfc", "q_val"],
            "rows": {"lfc": [1.0], "q_val": [0.01]},
            "row_count": 1,
            "total_rows": 17_000_000,
            "sampled": True,
            "sampling": {"policy": "tail_preserving", "exact": False, "degraded": False},
            "filter_applied": False,
        }

    monkeypatch.setattr(routes_mod, "bulk_compute_cards", fake_bulk_cards)
    monkeypatch.setattr(routes_mod, "render_table_endpoint", fake_render_table)
    monkeypatch.setattr(celery_mod, "build_figure_preview", fake_figure_preview)
    monkeypatch.setattr(av_mod, "fetch_advanced_viz_data", fake_av_data)

    result = export_manifest(str(DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True))
    assert result.manifest is not None
    # The table freeze paged through the 500-row endpoint clamp.
    assert table_calls == [(0, 500), (500, 500)]
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


def test_offline_export_tiers(offline_export: BundleManifest):
    tiers = {k: v for k, v in offline_export.tiers.items()}
    assert tiers["card-1"].tier is ComponentTier.LIVE
    assert tiers["filter-1"].tier is ComponentTier.LIVE
    assert tiers["text-1"].tier is ComponentTier.LIVE
    # Sampled frozen figure was refined to partial (FIGURE_MAX_POINTS).
    assert tiers["fig-1"].tier is ComponentTier.PARTIAL
    assert tiers["fig-1"].reason is TierReason.MAX_POINTS
    assert tiers["tbl-1"].tier is ComponentTier.FROZEN
    assert tiers["av-1"].tier is ComponentTier.FROZEN
    assert tiers["emb-1"].tier is ComponentTier.OMITTED
    assert tiers["emb-1"].reason is TierReason.CELERY_COMPUTE
    assert tiers["img-1"].tier is ComponentTier.OMITTED
    assert tiers["img-1"].reason is TierReason.IMAGE


def test_offline_export_data_ref_and_blob(offline_export: BundleManifest):
    manifest = offline_export
    assert set(manifest.data_refs) == {str(DC_OID)}  # only the live components' DC
    ref = manifest.data_refs[str(DC_OID)]
    assert ref.aggregation_hash == "agghash-1"  # the server-side staleness token
    assert ref.uri == f"inline:dc_{DC_OID}"
    # Pruned to live columns (card 'bill' + interactive 'year'), figure/table
    # columns excluded, plus the Int64 filter column's codebook companion.
    names = {c.name for c in ref.columns}
    assert names == {"bill", "year", "__code__year"}
    assert ref.companions == {"__code__year": "year"}
    assert ref.codebooks == {"year": {"2021": 0, "2022": 1, "2023": 2}}

    blob = base64.b64decode(manifest.inline_blobs[f"dc_{DC_OID}"])
    assert len(blob) == ref.size_bytes
    df = pl.read_parquet(io.BytesIO(blob))
    assert df.height == ref.rows == 4
    assert df["__code__year"].to_list() == [0, 0, 1, 2]


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
    # Figure payload came straight from build_figure_preview.
    assert frozen["fig-1"].kind == "figure"
    assert frozen["fig-1"].payload["metadata"]["was_sampled"] is True
    # advanced_viz keeps the /advanced_viz/data sampling block verbatim.
    av = frozen["av-1"].payload
    assert av["sampling"] == {"policy": "tail_preserving", "exact": False, "degraded": False}
    assert av["total_rows"] == 17_000_000
    # Omitted components ship no payload.
    assert "emb-1" not in frozen and "img-1" not in frozen


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

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    # --check needs only viewer; an admin passes without touching projects.
    result = export_static(
        str(DASHBOARD_OID), check=True, user=ExportUser(id=ObjectId(), is_admin=True)
    )
    assert result.manifest is None
    assert {r.component_id for r in result.tier_rows} == {
        "card-1",
        "filter-1",
        "text-1",
        "fig-1",
        "tbl-1",
        "av-1",
        "emb-1",
        "img-1",
    }


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
