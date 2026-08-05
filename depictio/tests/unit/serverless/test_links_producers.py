"""Cross-DC links in the bundle manifest (RFC §8, phase 7).

Both producers must hand the browser core (`packages/depictio-static-core/src/links.ts`)
the two things it needs to propagate a filter across data collections offline:

1. ``manifest.links.configs`` — the link documents, with dc ids the runtime can
   match against ``manifest.data_refs`` keys.
2. ``manifest.links.tables`` — precomputed translations for the hops whose
   source data collection is NOT bundled (producer A only; producer B bundles
   every DC it knows about).

…plus the invisible third thing: the *join columns* must survive column
pruning on both endpoints, or the link resolves against a column the bundled
Parquet does not have. That mirrors the server's ``_effective_projection`` fold,
pinned by ``depictio/tests/api/v1/test_column_projection.py::TestCrossDcLinkProjection``.
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest
from bson import ObjectId

from depictio.models.models.dashboards import DashboardDataLite
from depictio.models.models.serverless import BundleManifest
from depictio.serverless.preflight import (
    LINK_TIER_A,
    LINK_TIER_B,
    LINK_TIER_INERT,
)
from depictio.serverless.producer_b import (
    build_link_configs,
    build_manifest,
    synthetic_dc_id,
    synthetic_link_id,
)
from depictio.serverless.pruning import compute_column_sets, link_join_columns, spec_links

WF_TAG = "wf"
DC_META = "metadata"
DC_MEASURE = "measurements"


# ---------------------------------------------------------------------------
# Producer B — spec-level links
# ---------------------------------------------------------------------------


def _spec(links: list[dict[str, Any]] | None = None) -> DashboardDataLite:
    """Two DCs: a metadata table (filtered on ``habitat``) and a measurements
    table (a card on ``depth``). Neither component reads the join columns."""
    doc: dict[str, Any] = {
        "title": "Linked",
        "components": [
            {
                "tag": "filter-habitat",
                "component_type": "interactive",
                "workflow_tag": WF_TAG,
                "data_collection_tag": DC_META,
                "interactive_component_type": "MultiSelect",
                "column_name": "habitat",
                "column_type": "object",
            },
            {
                "tag": "card-depth",
                "component_type": "card",
                "workflow_tag": WF_TAG,
                "data_collection_tag": DC_MEASURE,
                "aggregation": "average",
                "column_name": "depth",
                "column_type": "float64",
            },
        ],
    }
    if links is not None:
        doc["links"] = links
    return DashboardDataLite.model_validate(doc)


DIRECT_LINK: dict[str, Any] = {
    "source_dc_tag": DC_META,
    "source_column": "sample",
    "target_dc_tag": DC_MEASURE,
    "target_type": "table",
    "link_config": {"resolver": "direct", "target_field": "sample_id"},
    "enabled": True,
}


def test_spec_links_are_read_through_the_extra_field():
    # DashboardDataLite is extra="allow", so a top-level `links:` block simply
    # rides along — no model change was needed for producer B to see it.
    assert spec_links(_spec([DIRECT_LINK])) == [DIRECT_LINK]
    assert spec_links(_spec()) == []


def test_producer_b_resolves_tags_to_synthetic_dc_ids():
    configs, rows = build_link_configs(_spec([DIRECT_LINK]))
    assert len(configs) == 1
    config = configs[0]
    assert config["source_dc_id"] == synthetic_dc_id(WF_TAG, DC_META)
    assert config["target_dc_id"] == synthetic_dc_id(WF_TAG, DC_MEASURE)
    # 24-hex ids, the same shape the data_refs keys (and producer A's Mongo
    # ObjectIds) have — the browser core matches them as opaque strings.
    for key in ("id", "source_dc_id", "target_dc_id"):
        assert len(config[key]) == 24
        int(config[key], 16)  # raises if not hex
    assert config["source_column"] == "sample"
    assert config["link_config"] == {"resolver": "direct", "target_field": "sample_id"}
    assert config["enabled"] is True
    assert [(r.tier, r.resolver) for r in rows] == [(LINK_TIER_A, "direct")]


def test_producer_b_link_id_is_stable_across_builds():
    first, _ = build_link_configs(_spec([DIRECT_LINK]))
    second, _ = build_link_configs(_spec([DIRECT_LINK]))
    assert first[0]["id"] == second[0]["id"]
    assert first[0]["id"] == synthetic_link_id(DC_META, "sample", DC_MEASURE)
    # A different natural triple is a different link.
    other = {**DIRECT_LINK, "source_column": "run"}
    assert build_link_configs(_spec([other]))[0][0]["id"] != first[0]["id"]


def test_producer_b_folds_join_columns_into_both_column_sets():
    spec = _spec([DIRECT_LINK])
    meta_key = f"{WF_TAG}:{DC_META}"
    measure_key = f"{WF_TAG}:{DC_MEASURE}"

    # Without links: only what the components read.
    assert compute_column_sets(_spec()) == {meta_key: {"habitat"}, measure_key: {"depth"}}

    # With the link: the source's join column and the TARGET's target_field —
    # neither of which any component reads — survive pruning.
    assert link_join_columns(spec) == {meta_key: {"sample"}, measure_key: {"sample_id"}}
    sets = compute_column_sets(spec)
    assert sets[meta_key] == {"habitat", "sample"}
    assert sets[measure_key] == {"depth", "sample_id"}


def test_producer_b_target_column_falls_back_to_source_column():
    # No target_field: a direct table->table link joins on the same name on both
    # sides (`_link_target_column`, filter_links.py:57-78).
    link = {**DIRECT_LINK, "link_config": {"resolver": "direct"}}
    sets = compute_column_sets(_spec([link]))
    assert sets[f"{WF_TAG}:{DC_MEASURE}"] == {"depth", "sample"}


def test_producer_b_skips_links_whose_tags_do_not_resolve():
    bad = {**DIRECT_LINK, "target_dc_tag": "nope"}
    configs, rows = build_link_configs(_spec([bad]))
    assert configs == []
    assert len(rows) == 1
    assert rows[0].tier == LINK_TIER_INERT
    assert "unresolvable" in (rows[0].note or "")
    assert "nope" in (rows[0].note or "")
    # …and it contributes no columns either.
    assert link_join_columns(_spec([bad])) == {f"{WF_TAG}:{DC_META}": {"sample"}}


def test_producer_b_keeps_disabled_links():
    configs, rows = build_link_configs(_spec([{**DIRECT_LINK, "enabled": False}]))
    assert configs[0]["enabled"] is False
    assert rows[0].enabled is False


def test_producer_b_notes_sample_mapping_without_inline_mappings():
    link = {
        **DIRECT_LINK,
        "target_type": "multiqc",
        "link_config": {"resolver": "sample_mapping", "target_field": "sample_name"},
    }
    configs, rows = build_link_configs(_spec([link]))
    # Emitted as-is: the runtime's resolver treats missing mappings as
    # pass-through-with-unmapped, which is what the server does too when the
    # MultiQC auto-fetch finds nothing.
    assert configs[0]["link_config"] == {
        "resolver": "sample_mapping",
        "target_field": "sample_name",
    }
    assert "sample_mapping without inline 'mappings'" in (rows[0].note or "")


# ---------------------------------------------------------------------------
# Producer B — end-to-end build over a real data dir
# ---------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path):
    """``{data_dir}/{wf_tag}/{dc_tag}.parquet`` for both DCs.

    ``measurements`` deliberately carries ``sample_id`` (the link's target
    column) but NOT ``sample`` — the join column lives under a different name on
    that side, which is exactly what ``target_field`` is for.
    """
    dc_dir = tmp_path / "data" / WF_TAG
    dc_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "sample": ["S1", "S2", "S3"],
            "habitat": ["river", "lake", "river"],
            "unused": [1, 2, 3],
        }
    ).write_parquet(dc_dir / f"{DC_META}.parquet")
    pl.DataFrame(
        {"sample_id": ["S1", "S2", "S3"], "depth": [1.0, 2.0, 3.0], "spare": [9, 9, 9]}
    ).write_parquet(dc_dir / f"{DC_MEASURE}.parquet")
    return tmp_path / "data"


def test_build_emits_links_and_keeps_join_columns(data_dir):
    result = build_manifest(_spec([DIRECT_LINK]), data_dir)
    manifest = result.manifest

    assert len(manifest.links.configs) == 1
    config = manifest.links.configs[0]
    # Every emitted endpoint id is a bundled data ref — the runtime resolves
    # link paths by dc id, so a dangling id would be a dead hop.
    assert config["source_dc_id"] in manifest.data_refs
    assert config["target_dc_id"] in manifest.data_refs
    # No tables: producer B bundles every DC, so both hops are tier A.
    assert manifest.links.tables == {}
    assert [r.tier for r in result.link_rows] == [LINK_TIER_A]

    meta_cols = {c.name for c in manifest.data_refs[config["source_dc_id"]].columns}
    measure_cols = {c.name for c in manifest.data_refs[config["target_dc_id"]].columns}
    assert "sample" in meta_cols  # source join column
    assert "sample_id" in measure_cols  # target_field, read by no component
    # Pruning still bites: columns nobody references stay out.
    assert "unused" not in meta_cols
    assert "spare" not in measure_cols

    BundleManifest.model_validate(manifest.model_dump(mode="json"))


def test_build_without_links_yields_an_empty_links_section(data_dir):
    manifest = build_manifest(_spec(), data_dir).manifest
    assert manifest.links.configs == []
    assert manifest.links.tables == {}
    # Backward compatibility: a bundle built before phase 7 round-trips the
    # same way, with the section defaulted rather than absent.
    assert BundleManifest.model_validate(manifest.model_dump(mode="json")).links.configs == []


def test_build_schema_guards_a_join_column_absent_from_the_target(data_dir):
    # target_field names a column the measurements Parquet does not have. The
    # server drops such a column from the projection rather than crashing
    # (_project_scan / TestCrossDcLinkProjection); so must the producer.
    link = {**DIRECT_LINK, "link_config": {"resolver": "direct", "target_field": "not_a_column"}}
    manifest = build_manifest(_spec([link]), data_dir).manifest
    measure_cols = {c.name for c in manifest.data_refs[synthetic_dc_id(WF_TAG, DC_MEASURE)].columns}
    assert "not_a_column" not in measure_cols
    assert "depth" in measure_cols
    assert len(manifest.links.configs) == 1


# ---------------------------------------------------------------------------
# Producer A — project links out of Mongo
# ---------------------------------------------------------------------------

DASHBOARD_OID = ObjectId("6824cb3b89d2b72169309740")
PROJECT_OID = ObjectId("646b0f3c1e4a2d7f8e5b8d01")
WF_OID = ObjectId("646b0f3c1e4a2d7f8e5b8d02")
DC_A_OID = ObjectId("646b0f3c1e4a2d7f8e5b8d11")  # bundled: filter + card
DC_B_OID = ObjectId("646b0f3c1e4a2d7f8e5b8d12")  # bundled: card (link target)
DC_SRC_OID = ObjectId("646b0f3c1e4a2d7f8e5b8d13")  # NOT on the dashboard (tier B source)
DC_OFF_OID = ObjectId("646b0f3c1e4a2d7f8e5b8d14")  # not on the dashboard at all

LINK_AB_OID = ObjectId("646b0f3c1e4a2d7f8e5b8e01")
LINK_SRC_B_OID = ObjectId("646b0f3c1e4a2d7f8e5b8e02")
LINK_OFF_OID = ObjectId("646b0f3c1e4a2d7f8e5b8e03")
LINK_DISABLED_OID = ObjectId("646b0f3c1e4a2d7f8e5b8e04")


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    def find_one(self, query: dict[str, Any], projection: Any = None) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None


def _dc_config(location: str) -> dict[str, Any]:
    return {"type": "table", "delta_location": location, "size_bytes": 1}


def _dashboard_doc() -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "dashboard_id": DASHBOARD_OID,
        "project_id": PROJECT_OID,
        "title": "Linked dashboard",
        "stored_metadata": [
            {
                "index": "filter-1",
                "component_type": "interactive",
                "interactive_component_type": "MultiSelect",
                "wf_id": WF_OID,
                "dc_id": DC_A_OID,
                "dc_config": _dc_config("memory://dcA"),
                "column_name": "habitat",
            },
            {
                "index": "card-a",
                "component_type": "card",
                "wf_id": WF_OID,
                "dc_id": DC_A_OID,
                "dc_config": _dc_config("memory://dcA"),
                "column_name": "reads",
                "aggregation": "mean",
            },
            {
                "index": "card-b",
                "component_type": "card",
                "wf_id": WF_OID,
                "dc_id": DC_B_OID,
                "dc_config": _dc_config("memory://dcB"),
                "column_name": "depth",
                "aggregation": "mean",
            },
        ],
    }


def _project_doc(links: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "_id": PROJECT_OID,
        "name": "linked",
        "workflows": [
            {
                "_id": WF_OID,
                "data_collections": [
                    {"_id": DC_A_OID},
                    {"_id": DC_B_OID},
                    {"_id": DC_SRC_OID},
                ],
            }
        ],
        "links": links,
    }


def _links() -> list[dict[str, Any]]:
    return [
        {
            # Tier A: both endpoints bundled.
            "_id": LINK_AB_OID,
            "source_dc_id": DC_A_OID,
            "source_column": "sample",
            "target_dc_id": DC_B_OID,
            "target_type": "table",
            "link_config": {"resolver": "direct", "target_field": "sample_id"},
            "enabled": True,
        },
        {
            # Tier B: the source DC is on no component, so its whole
            # join-column translation is precomputed.
            "_id": LINK_SRC_B_OID,
            "source_dc_id": DC_SRC_OID,
            "source_column": "run",
            "target_dc_id": DC_B_OID,
            "target_type": "multiqc",
            "link_config": {
                "resolver": "sample_mapping",
                "target_field": "sample_name",
                "mappings": {"R1_R1": ["R1_R1_x"], "R1_R2": ["R1_R2_x"], "R2": ["R2_y"]},
            },
            "enabled": True,
        },
        {
            # Target is a DC this dashboard never renders -> not emitted.
            "_id": LINK_OFF_OID,
            "source_dc_id": DC_A_OID,
            "source_column": "sample",
            "target_dc_id": DC_OFF_OID,
            "target_type": "table",
            "link_config": {"resolver": "direct"},
            "enabled": True,
        },
        {
            # Disabled: emitted verbatim (the runtime's walk skips it), but
            # nothing is precomputed for it.
            "_id": LINK_DISABLED_OID,
            "source_dc_id": DC_SRC_OID,
            "source_column": "run",
            "target_dc_id": DC_B_OID,
            "target_type": "table",
            "link_config": {"resolver": "direct"},
            "enabled": False,
        },
    ]


FRAMES = {
    str(DC_A_OID): pl.DataFrame(
        {
            "habitat": ["river", "lake"],
            "reads": [10, 20],
            "sample": ["S1", "S2"],
            "junk": [0, 0],
        }
    ),
    str(DC_B_OID): pl.DataFrame({"depth": [1.0, 2.0], "sample_id": ["S1", "S2"], "junk": [0, 0]}),
    str(DC_SRC_OID): pl.DataFrame({"run": ["R1", "R2", "R1"], "other": [1, 2, 3]}),
}

LOCATIONS = {
    str(DC_A_OID): "memory://dcA",
    str(DC_B_OID): "memory://dcB",
    str(DC_SRC_OID): "memory://dcSRC",
}


@pytest.fixture
def producer_a_env(monkeypatch: pytest.MonkeyPatch):
    """Fake Mongo + fake Delta access, monkeypatched onto the real server
    modules (producer A resolves them through module objects at call time).

    Returns a callable taking the project's link list and yielding the manifest.
    """
    from depictio.api.v1 import celery_tasks as celery_mod
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1 import deltatables_utils as dtu_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    monkeypatch.setattr(
        db_mod,
        "deltatables_collection",
        _FakeCollection(
            [
                {"data_collection_id": oid, "delta_table_location": LOCATIONS[str(oid)]}
                for oid in (DC_A_OID, DC_B_OID, DC_SRC_OID)
            ]
        ),
    )

    def fake_schema(workflow_id, data_collection_id, init_data):
        return dict(FRAMES[str(data_collection_id)].schema)

    loads: list[tuple[str, tuple[str, ...] | None]] = []

    def fake_load(workflow_id, data_collection_id, metadata=None, select_columns=None, **kw):
        dc = str(data_collection_id)
        loads.append((dc, tuple(select_columns) if select_columns else None))
        frame = FRAMES[dc]
        return frame.select(select_columns) if select_columns else frame

    monkeypatch.setattr(dtu_mod, "schema_deltatable_lite", fake_schema)
    monkeypatch.setattr(dtu_mod, "load_deltatable_lite", fake_load)
    monkeypatch.setattr(dtu_mod, "_get_aggregation_hash", lambda dc_id: "agghash")
    monkeypatch.setattr(
        routes_mod,
        "bulk_compute_cards",
        lambda *a, **kw: {"values": {}, "secondary_values": {}, "aggregations": {}},
    )
    monkeypatch.setattr(celery_mod, "build_figure_preview", lambda payload: {})

    def run(links: list[dict[str, Any]]):
        from depictio.serverless.producer_a import ExportUser, export_manifest

        monkeypatch.setattr(db_mod, "projects_collection", _FakeCollection([_project_doc(links)]))
        result = export_manifest(str(DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True))
        assert result.manifest is not None
        return result

    run.loads = loads  # type: ignore[attr-defined]
    return run


def test_producer_a_emits_configs_verbatim_and_stringified(producer_a_env):
    manifest = producer_a_env(_links()).manifest
    by_id = {c["id"]: c for c in manifest.links.configs}

    # Mongo's `_id` is normalised to `id` (DCLink.convert_id_field does the same)
    # and every ObjectId is a string, so the manifest is JSON-serialisable and
    # the browser core can compare ids as opaque strings.
    assert set(by_id) == {str(LINK_AB_OID), str(LINK_SRC_B_OID), str(LINK_DISABLED_OID)}
    ab = by_id[str(LINK_AB_OID)]
    assert "_id" not in ab
    assert ab["source_dc_id"] == str(DC_A_OID)
    assert ab["target_dc_id"] == str(DC_B_OID)
    assert ab["source_column"] == "sample"
    assert ab["target_type"] == "table"
    # Everything else rides along untouched.
    assert ab["link_config"] == {"resolver": "direct", "target_field": "sample_id"}
    BundleManifest.model_validate(manifest.model_dump(mode="json"))


def test_producer_a_drops_links_targeting_an_unrendered_dc(producer_a_env):
    manifest = producer_a_env(_links()).manifest
    assert str(LINK_OFF_OID) not in {c["id"] for c in manifest.links.configs}
    # The keep-rule is on the TARGET: a link that cannot land a filter on
    # anything this dashboard renders is dead weight.
    assert all(c["target_dc_id"] == str(DC_B_OID) for c in manifest.links.configs)


def test_producer_a_keeps_disabled_links_but_precomputes_no_table(producer_a_env):
    result = producer_a_env(_links())
    disabled = next(c for c in result.manifest.links.configs if c["id"] == str(LINK_DISABLED_OID))
    assert disabled["enabled"] is False
    assert str(LINK_DISABLED_OID) not in result.manifest.links.tables
    row = next(r for r in result.link_rows if r.link_id == str(LINK_DISABLED_OID))
    assert row.tier == LINK_TIER_INERT
    assert "disabled" in (row.note or "")


def test_producer_a_folds_join_columns_into_the_bundled_frames(producer_a_env):
    manifest = producer_a_env(_links()).manifest
    a_cols = {c.name for c in manifest.data_refs[str(DC_A_OID)].columns}
    b_cols = {c.name for c in manifest.data_refs[str(DC_B_OID)].columns}
    # `sample` is read by no component on DC A; `sample_id` by none on DC B.
    assert "sample" in a_cols
    assert "sample_id" in b_cols
    # Pruning still drops what nothing references.
    assert "junk" not in a_cols and "junk" not in b_cols


def test_producer_a_precomputes_a_table_for_an_unbundled_source(producer_a_env):
    result = producer_a_env(_links())
    manifest = result.manifest
    # The tier-A link needs no table (its source DC is bundled, so the browser
    # runs the translation query itself).
    assert str(LINK_AB_OID) not in manifest.links.tables
    assert str(DC_SRC_OID) not in manifest.data_refs

    table = manifest.links.tables[str(LINK_SRC_B_OID)]
    # Keys are the DISTINCT values of the link's source_column on the source DC.
    assert set(table.values) == {"R1", "R2"}

    rows = {r.link_id: r for r in result.link_rows}
    assert rows[str(LINK_AB_OID)].tier == LINK_TIER_A
    assert rows[str(LINK_SRC_B_OID)].tier == LINK_TIER_B
    assert rows[str(LINK_SRC_B_OID)].entries == 2


def test_producer_a_table_goes_through_the_real_server_resolver(producer_a_env):
    """Resolver fidelity: the table is whatever ``resolvers.py`` returns.

    'R1' matches no mapping key exactly; SampleMappingResolver's suffix-stripped
    base bucket (``_R1``/``_R2``) aggregates the variants of BOTH ``R1_R1`` and
    ``R1_R2`` — a behaviour no reimplementation would produce by accident.
    """
    table = producer_a_env(_links()).manifest.links.tables[str(LINK_SRC_B_OID)]
    assert table.values["R1"] == ["R1_R1_x", "R1_R2_x"]
    # 'R2' matches a key exactly, so the fallback never runs.
    assert table.values["R2"] == ["R2_y"]


def test_producer_a_reads_only_the_join_column_of_an_unbundled_source(producer_a_env):
    env = producer_a_env
    env(_links())
    src_loads = [cols for dc, cols in env.loads if dc == str(DC_SRC_OID)]
    assert src_loads == [("run",)]


def test_producer_a_skips_the_table_when_the_source_delta_is_unreadable(
    producer_a_env, monkeypatch
):
    from depictio.api.v1 import db as db_mod

    # No deltatable document for the unbundled source: nothing to precompute.
    monkeypatch.setattr(
        db_mod,
        "deltatables_collection",
        _FakeCollection(
            [
                {"data_collection_id": oid, "delta_table_location": LOCATIONS[str(oid)]}
                for oid in (DC_A_OID, DC_B_OID)
            ]
        ),
    )
    result = producer_a_env(_links())
    assert result.manifest.links.tables == {}
    # The config still ships — it is a true statement about the project — but
    # the hop is inert, so the filter simply does not propagate.
    assert str(LINK_SRC_B_OID) in {c["id"] for c in result.manifest.links.configs}
    row = next(r for r in result.link_rows if r.link_id == str(LINK_SRC_B_OID))
    assert row.tier == LINK_TIER_INERT
    assert "inert" in (row.note or "")


def test_producer_a_drops_a_table_over_the_pair_cap(producer_a_env, monkeypatch):
    from depictio.serverless import producer_a as pa

    big = [f"v{i}" for i in range(pa.LINK_TABLE_MAX_PAIRS + 1)]
    monkeypatch.setattr(pa, "_link_source_column_values", lambda dc_id, wf_id, column: big)

    # A direct resolver: one target value per source value, so pairs == values.
    links = [link for link in _links() if link["_id"] != LINK_SRC_B_OID]
    links.append(
        {
            "_id": LINK_SRC_B_OID,
            "source_dc_id": DC_SRC_OID,
            "source_column": "run",
            "target_dc_id": DC_B_OID,
            "target_type": "table",
            "link_config": {"resolver": "direct"},
            "enabled": True,
        }
    )
    result = producer_a_env(links)
    assert result.manifest.links.tables == {}
    row = next(r for r in result.link_rows if r.link_id == str(LINK_SRC_B_OID))
    assert row.tier == LINK_TIER_INERT
    assert "too big" in (row.note or "")


def test_producer_a_notes_sample_mapping_without_inline_mappings(producer_a_env):
    links = [
        {
            "_id": LINK_AB_OID,
            "source_dc_id": DC_A_OID,
            "source_column": "sample",
            "target_dc_id": DC_B_OID,
            "target_type": "multiqc",
            "link_config": {"resolver": "sample_mapping", "target_field": "sample_name"},
            "enabled": True,
        }
    ]
    result = producer_a_env(links)
    config = result.manifest.links.configs[0]
    # Emitted as-is: the producer cannot replicate the server's MultiQC
    # auto-fetch, and the resolver's documented empty-mappings behaviour is
    # pass-through-with-unmapped.
    assert config["link_config"].get("mappings") is None
    row = result.link_rows[0]
    assert row.tier == LINK_TIER_A
    assert "sample_mapping without inline 'mappings'" in (row.note or "")


def test_producer_a_without_project_links_yields_an_empty_section(producer_a_env):
    manifest = producer_a_env([]).manifest
    assert manifest.links.configs == []
    assert manifest.links.tables == {}
    # And the join-column fold contributes nothing, so pruning is unchanged.
    assert "sample" not in {c.name for c in manifest.data_refs[str(DC_A_OID)].columns}


def test_producer_a_check_predicts_tiers_without_reading_any_delta(
    monkeypatch: pytest.MonkeyPatch,
):
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1 import deltatables_utils as dtu_mod
    from depictio.serverless.producer_a import ExportUser, export_static

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    monkeypatch.setattr(db_mod, "projects_collection", _FakeCollection([_project_doc(_links())]))

    def boom(*a, **kw):  # preflight must stay data-free
        raise AssertionError("--check must not read any Delta table")

    monkeypatch.setattr(dtu_mod, "load_deltatable_lite", boom)
    monkeypatch.setattr(dtu_mod, "schema_deltatable_lite", boom)

    result = export_static(
        str(DASHBOARD_OID), check=True, user=ExportUser(id=ObjectId(), is_admin=True)
    )
    assert result.manifest is None
    rows = {r.link_id: r for r in result.link_rows}
    assert set(rows) == {str(LINK_AB_OID), str(LINK_SRC_B_OID), str(LINK_DISABLED_OID)}
    assert rows[str(LINK_AB_OID)].tier == LINK_TIER_A
    # Predicted from bundling alone: the table itself is built at build time.
    assert rows[str(LINK_SRC_B_OID)].tier == LINK_TIER_B
    assert rows[str(LINK_SRC_B_OID)].entries is None


# ---------------------------------------------------------------------------
# Cap arithmetic (unit, no Mongo)
# ---------------------------------------------------------------------------


def test_build_link_table_counts_pairs_not_keys():
    from depictio.serverless.producer_a import LINK_TABLE_MAX_PAIRS, build_link_table

    # Few keys, huge fan-out: the cap is on emitted PAIRS, which is what lands
    # in the manifest JSON.
    variants = [f"x{i}" for i in range(LINK_TABLE_MAX_PAIRS + 1)]
    link = {
        "source_column": "run",
        "link_config": {"resolver": "sample_mapping", "mappings": {"R1": variants}},
    }
    table, pairs = build_link_table(link, ["R1"])
    assert table is None
    assert pairs > LINK_TABLE_MAX_PAIRS

    table, pairs = build_link_table(link, [])
    assert table is not None and table.values == {} and pairs == 0


def test_build_link_table_rejects_an_unknown_resolver():
    from depictio.serverless.producer_a import build_link_table

    table, pairs = build_link_table({"link_config": {"resolver": "nope"}}, ["a"])
    assert table is None and pairs == 0
