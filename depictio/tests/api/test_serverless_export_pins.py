"""A static export of a state pinned to a past dashboard version ships that version.

The seed project ``iris_versioned`` stages its two batches as the two commits
of one Delta table: batch 2 (versicolor added) is commit 0, batch 3 (the
Setosa petal measurements recalibrated) overwrites as commit 1. Dashboard
version 2 stamps commit 0, version 3 stamps commit 1 — the same two rows
count, different values, story the live time-travel tests hold.

Producer A resolves the exported state's pins once, with the resolver every
render endpoint uses, so the bundle freezes on the commit the named version
stamped — and the assertions are against direct ``pl.read_delta`` reads at
those commits, the only honest witness of what "pinned" means:

* two exports pinned to version 2 and version 3 bundle the same 100 rows with
  different values, each matching its commit, and the manifest names the
  version in ``pinned_version``; an unpinned export of the same dashboard is
  byte-for-byte today's data with ``pinned_version`` null;
* a stale version id raises (the route answers 400 with the same sentence),
  never a silent fallback to current data under a historical label;
* ``definition_version`` draws each component as the stored version defined
  it, and omits a component that version never held rather than drawing the
  version's data through today's definition of it.

All against the offline producer-A stack of ``test_serverless_export.py``
(fake Mongo collections, fake endpoint bodies) plus a real on-disk Delta
table — no infrastructure needed.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from bson import ObjectId

from depictio.models.models.analysis_state import AnalysisState
from depictio.models.models.serverless import BundleManifest, ComponentTier, TierReason
from depictio.serverless.producer_a import ExportUser, VersionPinsError, export_manifest
from depictio.tests.api.test_serverless_export import (  # noqa: F401 (fixture)
    DASHBOARD_OID,
    DC_OID,
    PROJECT_OID,
    WF_OID,
    _FakeCollection,
    _FakeTabCollection,
    _register_collections,
)

BATCHES = Path(__file__).resolve().parents[2] / "projects" / "init" / "iris_versioned" / "batches"
BATCH_2 = BATCHES / "batch_02_versicolor_added" / "iris.csv"
BATCH_3 = BATCHES / "batch_03_setosa_recalibrated" / "iris.csv"

V2 = "507f1f77bcf86cd799430002"  # stamps Delta commit 0 (batch 2)
V3 = "507f1f77bcf86cd799430003"  # stamps Delta commit 1 (batch 3)
FOREIGN = "507f1f77bcf86cd799430004"  # a version of another dashboard family
VDEFS = "507f1f77bcf86cd799430005"  # the definition_version snapshot below

CREATED_V2 = datetime(2026, 11, 20, 9, 0, 0)
CREATED_V3 = datetime(2026, 11, 21, 9, 0, 0)

ADMIN = ExportUser(id=ObjectId(), is_admin=True)


class _DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data
        return True


def _pins_dashboard_doc() -> dict[str, Any]:
    """One iris dashboard: a card, a filter, a binding scatter and a table, all
    reading the one collection. The ``dc_config`` locations are decoys — the
    loader reads ``deltatables``."""
    dc_config = {"type": "table", "delta_location": "memory://decoy-iris", "size_bytes": 900}
    return {
        "_id": ObjectId(),
        "dashboard_id": DASHBOARD_OID,
        "project_id": PROJECT_OID,
        "title": "iris_versioned",
        "permissions": {"owners": []},
        "stored_metadata": [
            {
                "index": "card-1",
                "component_type": "card",
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
                "column_name": "petal.length",
                "aggregation": "mean",
            },
            {
                "index": "filter-1",
                "component_type": "interactive",
                "interactive_component_type": "MultiSelect",
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
                "column_name": "variety",
            },
            {
                # A plain binding scatter: LIVE, built off the bundled pinned
                # frame — the worker's build_figure_preview is never called.
                "index": "fig-1",
                "component_type": "figure",
                "mode": "ui",
                "visu_type": "scatter",
                "dict_kwargs": {"x": "petal.length", "y": "petal.width"},
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": dc_config,
            },
            {
                "index": "fig-2",
                "component_type": "figure",
                "mode": "ui",
                "visu_type": "scatter",
                "dict_kwargs": {"x": "sepal.length", "y": "sepal.width"},
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
        ],
    }


def _version_record(
    version_id: str, seq: int, label: str, created_at: datetime, *, delta_version: int, tabs: list
) -> dict[str, Any]:
    return {
        "version_id": version_id,
        "family_id": str(DASHBOARD_OID),
        "seq": seq,
        "label": label,
        "created_at": created_at,
        "data_collections": [
            {"dc_id": str(DC_OID), "version_kind": "delta", "delta_version": delta_version}
        ],
        "tabs": tabs,
    }


def _definition_snapshot(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The version ``VDEFS`` held: every live component except ``fig-2`` (added
    since), with ``fig-1`` reading the sepal measurements instead."""
    snap = []
    for comp in doc["stored_metadata"]:
        stored = {k: v for k, v in comp.items() if k != "dc_config"}
        if comp["index"] == "fig-2":
            continue
        if comp["index"] == "fig-1":
            stored["dict_kwargs"] = {"x": "sepal.length", "y": "sepal.width"}
        snap.append(stored)
    return [
        {
            "dashboard_id": str(DASHBOARD_OID),
            "title": doc["title"],
            "tab_order": 0,
            "stored_metadata": snap,
        }
    ]


def _state(pins: dict[str, Any] | None = None) -> AnalysisState:
    return AnalysisState.model_validate(
        {
            "context": {"dashboard_id": str(DASHBOARD_OID)},
            **({"pins": pins} if pins else {}),
        }
    )


def _bundled(manifest, dc_id: ObjectId = DC_OID) -> pl.DataFrame:
    """The bundled table of one collection, decoded from the inline blob."""
    blob = base64.b64decode(manifest.inline_blobs[f"dc_{dc_id}"])
    return pl.read_parquet(io.BytesIO(blob))


@pytest.fixture()
def iris_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The two batches as Delta commits, plus the fake instance around them."""
    from depictio.api import cache as cache_module
    from depictio.api.v1 import celery_tasks as celery_mod
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1 import deltatables_utils as dtu_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as core_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    # The staged history: commit 0 = batch 2, commit 1 = batch 3's recalibration.
    table = str(tmp_path / "iris.delta")
    pl.read_csv(BATCH_2).write_delta(table)
    pl.read_csv(BATCH_3).write_delta(table, mode="overwrite")

    doc = _pins_dashboard_doc()
    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([doc]))
    monkeypatch.setattr(core_mod, "dashboards_collection", _FakeTabCollection([]))
    # The real Delta location lives in `deltatables`; the document's copies are
    # decoys the loader must not read.
    _register_collections(monkeypatch, [doc], locations={str(DC_OID): table})

    records = [
        _version_record(V2, 2, "Batch 2 ingested", CREATED_V2, delta_version=0, tabs=[]),
        _version_record(V3, 3, "Batch 3 recalibrated", CREATED_V3, delta_version=1, tabs=[]),
        _version_record(
            VDEFS, 4, "The snapshot", CREATED_V3, delta_version=0, tabs=_definition_snapshot(doc)
        ),
        {  # Another family's version: never readable through this dashboard.
            "version_id": FOREIGN,
            "family_id": str(ObjectId()),
            "seq": 9,
            "data_collections": [],
            "tabs": [],
        },
    ]
    monkeypatch.setattr(version_store, "dashboard_versions_collection", _FakeCollection(records))

    # Real Delta reads, offline: no S3 config, an in-process cache, and no
    # aggregation history in `deltatables` (a fresh collection has none).
    monkeypatch.setattr(dtu_mod, "polars_s3_config", {})
    monkeypatch.setattr(cache_module, "get_cache", lambda: _DictCache())
    dtu_mod.clear_memory_cache()

    bodies: dict[str, list[dict[str, Any]]] = {"cards": [], "tables": [], "previews": []}

    def fake_bulk_cards(dashboard_id, request, current_user, access_token):
        bodies["cards"].append(dict(request))
        return {
            "values": {"card-1": 3.0},
            "secondary_values": {},
            "aggregations": {},
            "filter_applied": False,
            "filter_count": 0,
        }

    def fake_render_table(
        dashboard_id, component_id, request, response, current_user, access_token
    ):
        bodies["tables"].append(dict(request))
        start, limit = int(request["start"]), int(request["limit"])
        return {
            "columns": [{"field": "variety", "headerName": "variety"}],
            "rows": [{"i": i} for i in range(start, min(start + limit, 100))],
            "total": 100,
            "sort_by": None,
            "sort_dir": "desc",
        }

    def fake_figure_preview(payload):
        bodies["previews"].append(dict(payload))
        return {
            "figure": {"data": [], "layout": {}},
            "metadata": {"visu_type": "scatter", "filter_applied": False, "was_sampled": False},
        }

    monkeypatch.setattr(routes_mod, "bulk_compute_cards", fake_bulk_cards)
    monkeypatch.setattr(routes_mod, "render_table_endpoint", fake_render_table)
    monkeypatch.setattr(celery_mod, "build_figure_preview", fake_figure_preview)
    return {"table": table, "doc": doc, "bodies": bodies}


def _sorted_petal_lengths(df: pl.DataFrame) -> list[float]:
    return sorted(df["petal.length"].to_list())


# ---------------------------------------------------------------------------
# Two exports, two versions: the bundle IS the version's data
# ---------------------------------------------------------------------------


def test_two_exports_pinned_to_two_versions_ship_each_versions_data(iris_env):
    m2 = export_manifest(str(DASHBOARD_OID), ADMIN, state=_state({"as_of_version": V2})).manifest
    m3 = export_manifest(str(DASHBOARD_OID), ADMIN, state=_state({"as_of_version": V3})).manifest
    live = export_manifest(str(DASHBOARD_OID), ADMIN, state=_state()).manifest
    assert m2 is not None and m3 is not None and live is not None

    df2, df3, dfl = _bundled(m2), _bundled(m3), _bundled(live)
    # The direct reads at each commit — the only honest witness.
    batch2 = pl.read_delta(iris_env["table"], version=0)
    batch3 = pl.read_delta(iris_env["table"], version=1)

    # Same row count, different values: the recalibrated Setosa.
    assert df2.height == df3.height == dfl.height == 100
    values2, values3 = _sorted_petal_lengths(df2), _sorted_petal_lengths(df3)
    assert values2 != values3
    # Each export matches a direct read at ITS version's commit, and nothing else.
    assert values2 == _sorted_petal_lengths(batch2)
    assert values3 == _sorted_petal_lengths(batch3)
    assert _sorted_petal_lengths(dfl) == _sorted_petal_lengths(batch3)

    # The manifest names the version each bundle froze on.
    assert m2.pinned_version is not None
    assert m2.pinned_version.version_id == V2
    assert m2.pinned_version.seq == 2
    assert m2.pinned_version.label == "Batch 2 ingested"
    assert m2.pinned_version.created_at == "2026-11-20T09:00:00"
    assert m2.pinned_version.unresolved == []
    assert m3.pinned_version is not None
    assert m3.pinned_version.version_id == V3
    assert m3.pinned_version.seq == 3
    assert m3.pinned_version.unresolved == []
    # No pin, no claim.
    assert live.pinned_version is None

    # Both figures bound off the bundled pinned frame — the worker's figure
    # pipeline never ran for a binding ui-mode scatter.
    assert iris_env["bodies"]["previews"] == []
    assert m2.tiers["fig-1"].tier is ComponentTier.LIVE
    assert m2.bindings["fig-1"].traces[0].fields == {"x": "petal.length", "y": "petal.width"}

    # The frozen endpoint fallbacks carry the pin in their request bodies, so a
    # pinned card asks for the version's data exactly as a render does.
    cards = iris_env["bodies"]["cards"]
    assert [r.get("as_of_version") for r in cards] == [V2, V3, None]
    # A LIVE table never pages from the endpoint: it reads the bundled Parquet,
    # which is the pinned commit's data — no second read to get wrong.
    assert iris_env["bodies"]["tables"] == []


def test_a_collection_the_version_cannot_pin_reads_current_data_and_is_reported(
    iris_env, monkeypatch
):
    """A version stamping nothing for the collection cannot pin it: the bundle
    reads current data (never a refusal, never a silent claim) and the manifest
    says so in ``pinned_version.unresolved``."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    bare = _version_record(
        "507f1f77bcf86cd799430009", 5, "Layout only", CREATED_V3, delta_version=0, tabs=[]
    )
    bare["data_collections"] = []  # the version recorded no commit for anything
    monkeypatch.setattr(
        version_store,
        "dashboard_versions_collection",
        _FakeCollection([bare, *version_store.dashboard_versions_collection.docs]),
    )

    manifest = export_manifest(
        str(DASHBOARD_OID), ADMIN, state=_state({"as_of_version": bare["version_id"]})
    ).manifest
    assert manifest is not None

    # Current data (commit 1), and the manifest names the collection as live.
    assert _sorted_petal_lengths(_bundled(manifest)) == _sorted_petal_lengths(
        pl.read_delta(iris_env["table"], version=1)
    )
    assert manifest.pinned_version is not None
    assert manifest.pinned_version.version_id == bare["version_id"]
    assert [u.model_dump() for u in manifest.pinned_version.unresolved] == [
        {"dc_id": str(DC_OID), "reason": "not_in_version"}
    ]


# ---------------------------------------------------------------------------
# A version that cannot be read is an error, never a fallback
# ---------------------------------------------------------------------------


def test_a_stale_version_id_raises_rather_than_shipping_current_data(iris_env):
    with pytest.raises(VersionPinsError, match=r"Version gone no longer exists\."):
        export_manifest(str(DASHBOARD_OID), ADMIN, state=_state({"as_of_version": "gone"}))


def test_a_version_of_another_dashboard_raises(iris_env):
    with pytest.raises(VersionPinsError, match="does not belong to this dashboard"):
        export_manifest(str(DASHBOARD_OID), ADMIN, state=_state({"as_of_version": FOREIGN}))


# ---------------------------------------------------------------------------
# definition_version: the stored version's components, not today's
# ---------------------------------------------------------------------------


def test_definitions_come_from_the_named_version(iris_env):
    """``definition_version`` ships the version's definitions: ``fig-1`` draws
    the sepal measurements that version defined, and ``fig-2`` — added since —
    is omitted rather than drawn through a definition the version never held."""
    manifest = export_manifest(
        str(DASHBOARD_OID), ADMIN, state=_state({"definition_version": VDEFS})
    ).manifest
    assert manifest is not None

    # The shipped document carries the stored definition, not today's.
    shipped = {c["index"]: c for c in manifest.dashboard.doc["stored_metadata"]}
    assert shipped["fig-1"]["dict_kwargs"] == {"x": "sepal.length", "y": "sepal.width"}
    # The identity fields stay live: the version's definition reads the same
    # collection through today's dc_config, never a snapshot location. (The
    # shipped doc is a JSON dump, so ids are strings.)
    assert shipped["fig-1"]["dc_id"] == str(DC_OID)
    assert shipped["fig-1"]["dc_config"]["delta_location"] == "memory://decoy-iris"

    # The binding was built from the stored definition over the bundled frame.
    assert manifest.tiers["fig-1"].tier is ComponentTier.LIVE
    assert manifest.bindings["fig-1"].traces[0].fields == {"x": "sepal.length", "y": "sepal.width"}
    assert "fig-1" not in manifest.frozen

    # fig-2 did not exist in that version: omitted, with the reason a reader
    # can act on — never the version's data through today's definition.
    entry = manifest.tiers["fig-2"]
    assert entry.tier is ComponentTier.OMITTED
    assert entry.reason is TierReason.UNSUPPORTED
    assert entry.detail and "did not exist in version" in entry.detail
    assert "fig-2" not in manifest.bindings and "fig-2" not in manifest.frozen

    # The definition version names the version in the manifest too.
    assert manifest.pinned_version is not None
    assert manifest.pinned_version.version_id == VDEFS
    assert manifest.pinned_version.unresolved == []
    # And the whole thing is still a valid manifest of the contract.
    BundleManifest.model_validate(manifest.model_dump(mode="json"))


def test_a_stale_definition_version_raises(iris_env):
    with pytest.raises(VersionPinsError, match=r"Version gone no longer exists\."):
        export_manifest(str(DASHBOARD_OID), ADMIN, state=_state({"definition_version": "gone"}))
