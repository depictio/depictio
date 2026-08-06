"""Producer A × the code-mode prologue (RFC §7, phase 6).

``test_serverless_export.py`` owns the general export contract; this module
owns the one flow phase 6 added — a **code-mode** figure going live:

    transpile the data prologue -> read the terminal ``px`` call ->
    build the figure through the SERVER pipeline (``build_figure_preview``,
    RestrictedPython — producer A never execs user code itself) ->
    replay the IR on the bundled base frame with Polars ->
    bind the real figure against the derived frame.

Three components exercise the three landing zones, all against fake Mongo
collections and a fake ``build_figure_preview`` monkeypatched onto the real
modules (the same offline seam the sibling module uses):

``fig-live``    transpilable + bindable -> LIVE, ``prologues`` + ``bindings``,
                no frozen payload, its DC bundled keep-all;
``fig-frozen``  outside the IR grammar -> FROZEN / ``code_mode`` carrying the
                transpiler's refusal;
``fig-miss``    analyzable but unbindable (the scaffold's traces do not
                reproduce the derived frame) -> FROZEN / ``binding_miss`` WITH
                the frozen payload.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import plotly.express as px
import polars as pl
import pytest
from bson import ObjectId

from depictio.models.models.serverless import (
    BundleManifest,
    ComponentTier,
    TierReason,
)
from depictio.serverless.producer_a import (
    ExportUser,
    classify_stored_component,
    export_manifest,
    live_column_sets,
)

DASHBOARD_OID = ObjectId("6824cb3b89d2b72169309738")
PROJECT_OID = ObjectId("646b0f3c1e4a2d7f8e5b8c9e")
WF_OID = ObjectId("646b0f3c1e4a2d7f8e5b8c02")
DC_OID = ObjectId("646b0f3c1e4a2d7f8e5b8cb1")

# The prologue shape phase 6 targets: group_by + sort, then a plain px call.
# Group means are distinct (2.0 / 5.0 / 9.0) so the derived frame has a total
# order — nothing here depends on how Polars breaks a tie.
LIVE_CODE = (
    "import polars as pl\n"
    "import plotly.express as px\n"
    "\n"
    "df2 = df.group_by('species').agg(pl.col('bill').mean().alias('mean_bill'))\n"
    "df2 = df2.sort('mean_bill', descending=True)\n"
    "fig = px.bar(df2, x='species', y='mean_bill')\n"
)

# `with_columns` computes a column the IR cannot express -> frozen, code_mode.
FROZEN_CODE = (
    "df2 = df.with_columns((pl.col('bill') * 2).alias('double'))\n"
    "fig = px.scatter(df2, x='bill', y='double')\n"
)

# Transpiles and reads fine, but the figure the "server" returns is a heatmap
# built from other data: no trace reproduces the derived frame's columns, so the
# binder refuses -> binding_miss, and the frozen payload it already holds ships.
MISS_CODE = "df2 = df.sort('bill')\nfig = px.scatter(df2, x='bill', y='flipper')\n"


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "bill": [1.0, 5.0, 3.0, 9.0],
            "flipper": [181, 186, 190, 195],
            "species": ["Adelie", "Chinstrap", "Adelie", "Gentoo"],
            "year": [2021, 2021, 2022, 2023],
        }
    )


def _derived() -> pl.DataFrame:
    """What ``LIVE_CODE``'s prologue produces — the frame the scaffold is built
    from, computed here the way the user's code computes it."""
    return (
        _frame()
        .group_by("species", maintain_order=True)
        .agg(pl.col("bill").mean().alias("mean_bill"))
        .sort("mean_bill", descending=True)
    )


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    def find_one(self, query: dict[str, Any], projection: Any = None) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None


def _code_component(index: str, code: str) -> dict[str, Any]:
    return {
        "index": index,
        "component_type": "figure",
        "mode": "code",
        "visu_type": "scatter",
        "code_content": code,
        "wf_id": WF_OID,
        "dc_id": DC_OID,
        "dc_config": {"type": "table", "delta_location": "memory://dcA", "size_bytes": 1},
    }


def _dashboard_doc() -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "dashboard_id": DASHBOARD_OID,
        "project_id": PROJECT_OID,
        "title": "Code-mode dashboard",
        "permissions": {"owners": []},
        "stored_metadata": [
            {
                "index": "filter-1",
                "component_type": "interactive",
                "interactive_component_type": "MultiSelect",
                "wf_id": WF_OID,
                "dc_id": DC_OID,
                "dc_config": {"type": "table", "delta_location": "memory://dcA"},
                "column_name": "species",
            },
            _code_component("fig-live", LIVE_CODE),
            _code_component("fig-frozen", FROZEN_CODE),
            _code_component("fig-miss", MISS_CODE),
        ],
    }


@pytest.fixture
def offline_export(monkeypatch: pytest.MonkeyPatch) -> BundleManifest:
    from depictio.api.v1 import celery_tasks as celery_mod
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1 import deltatables_utils as dtu_mod

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    monkeypatch.setattr(db_mod, "deltatables_collection", _FakeCollection([]))
    # Phase 7 reads the project for its cross-DC links; this one declares none.
    monkeypatch.setattr(
        db_mod, "projects_collection", _FakeCollection([{"_id": PROJECT_OID, "links": []}])
    )

    monkeypatch.setattr(
        dtu_mod,
        "schema_deltatable_lite",
        lambda workflow_id, data_collection_id, init_data: dict(_frame().schema),
    )
    monkeypatch.setattr(
        dtu_mod,
        "load_deltatable_lite",
        lambda workflow_id, data_collection_id, metadata=None, select_columns=None, **kw: (
            _frame().select(select_columns) if select_columns else _frame()
        ),
    )
    monkeypatch.setattr(dtu_mod, "_get_aggregation_hash", lambda dc_id: "agghash-code")

    calls: list[tuple[str, bool]] = []

    def fake_figure_preview(payload: dict[str, Any]) -> dict[str, Any]:
        """Stand-in for the worker: runs the component's code the way the real
        pipeline would (the sandbox itself is not what this module tests) and
        returns the same response shape."""
        meta = payload["metadata"]
        code = meta["code_content"]
        calls.append((code.splitlines()[-1], bool(payload["full_load"])))
        assert meta["mode"] == "code"
        assert payload["filter_metadata"] == []
        if code is MISS_CODE:
            # A figure that does NOT describe the derived frame: the binder must
            # refuse it rather than invent a trace↔column mapping.
            fig = px.scatter(x=[0.0, 1.0], y=[0.0, 1.0])
        else:
            ns: dict[str, Any] = {"df": _frame(), "pl": pl, "px": px}
            exec(compile(code, "<code-mode>", "exec"), ns)  # noqa: S102 — test-owned source
            fig = ns["fig"]
        return {
            "figure": fig.to_plotly_json(),
            "metadata": {"visu_type": "code", "filter_applied": False, "was_sampled": False},
        }

    monkeypatch.setattr(celery_mod, "build_figure_preview", fake_figure_preview)

    result = export_manifest(str(DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True))
    assert result.manifest is not None
    # Every code figure went through the server pipeline exactly once, and the
    # two analyzable ones asked for the uncapped frame (a scaffold built from a
    # sample could not be refilled from the full bundled table).
    assert [full for _, full in calls] == [True, False, True]
    assert len(calls) == 3
    return result.manifest


# ---------------------------------------------------------------------------
# Planned verdicts (data-free — the transpiler reads the code, not the data)
# ---------------------------------------------------------------------------


def test_planned_verdict_transpilable_offers_bind_and_refill():
    tier, reason, detail = classify_stored_component(_code_component("c", LIVE_CODE))
    assert tier is ComponentTier.FROZEN
    assert reason is TierReason.BINDING_MISS
    assert detail and "transpilable prologue" in detail


def test_planned_verdict_untranspilable_keeps_code_mode():
    tier, reason, detail = classify_stored_component(_code_component("c", FROZEN_CODE))
    assert tier is ComponentTier.FROZEN
    assert reason is TierReason.CODE_MODE
    assert detail and "with_columns" in detail


def test_planned_verdict_without_code_is_code_mode():
    tier, reason, detail = classify_stored_component({"component_type": "figure", "mode": "code"})
    assert tier is ComponentTier.FROZEN
    assert reason is TierReason.CODE_MODE
    assert detail


def test_live_column_sets_widen_to_keep_all_for_a_transpilable_figure():
    """A transpilable code figure's DC ships keep-all (``None``): arbitrary code
    may read any column, and the runtime re-derives the frame from them."""
    dc = ObjectId()
    assert live_column_sets(
        [
            {"component_type": "card", "dc_id": dc, "column_name": "bill"},
            {**_code_component("fig-live", LIVE_CODE), "dc_id": dc},
        ]
    ) == {str(dc): None}
    # An untranspilable one is not offered to the binder at all, so it neither
    # widens the set nor pulls its DC into the bundle.
    assert live_column_sets(
        [
            {"component_type": "card", "dc_id": dc, "column_name": "bill"},
            {**_code_component("fig-frozen", FROZEN_CODE), "dc_id": dc},
        ]
    ) == {str(dc): {"bill"}}


# ---------------------------------------------------------------------------
# The export itself
# ---------------------------------------------------------------------------


def test_transpilable_code_figure_goes_live(offline_export: BundleManifest):
    manifest = offline_export
    entry = manifest.tiers["fig-live"]
    assert entry.tier is ComponentTier.LIVE
    assert entry.reason is None and entry.detail is None
    # LIVE means no frozen payload: the runtime re-derives it at every filter
    # state from the bundled base table.
    assert "fig-live" not in manifest.frozen

    ops = [op.model_dump(mode="json") for op in manifest.prologues["fig-live"]]
    assert ops == [
        {
            "op": "group_by",
            "by": ["species"],
            "agg": [{"col": "bill", "fn": "mean", "alias": "mean_bill"}],
        },
        {"op": "sort", "by": ["mean_bill"], "desc": [True]},
    ]

    binding = manifest.bindings["fig-live"]
    assert binding.sampled is False
    assert binding.group_cols == []
    assert [t.i for t in binding.traces] == [0]
    # Fields reference DERIVED column names — `mean_bill` exists only after the
    # prologue runs, which is exactly what the runtime replays.
    assert binding.traces[0].fields == {"x": "species", "y": "mean_bill"}
    assert binding.traces[0].group == {}
    trace = binding.scaffold["data"][0]
    assert "x" not in trace and "y" not in trace  # stripped; refill writes them
    assert binding.scaffold["layout"]["yaxis"]["title"]["text"] == "mean_bill"

    BundleManifest.model_validate(manifest.model_dump(mode="json"))


def test_live_code_figure_bundles_its_dc_keep_all(offline_export: BundleManifest):
    """The prologue is replayed in the browser over the BASE columns, so the DC
    ships unprojected (``species`` is a String filter column: direct membership,
    no codebook companion, so the physical schema is exactly the base frame)."""
    manifest = offline_export
    ref = manifest.data_refs[str(DC_OID)]
    assert {c.name for c in ref.columns} == {"bill", "flipper", "species", "year"}
    assert ref.companions == {}
    blob = base64.b64decode(manifest.inline_blobs[f"dc_{DC_OID}"])
    df = pl.read_parquet(io.BytesIO(blob))
    assert df.height == ref.rows == 4

    # The derived frame the binding refers to is reproducible from those base
    # columns alone — nothing the binding names is missing from the bundle.
    derived = _derived()
    assert set(manifest.bindings["fig-live"].traces[0].fields.values()) <= set(derived.columns)
    assert derived["species"].to_list() == ["Gentoo", "Chinstrap", "Adelie"]


def test_untranspilable_code_figure_freezes_with_code_mode(offline_export: BundleManifest):
    entry = offline_export.tiers["fig-frozen"]
    assert entry.tier is ComponentTier.FROZEN
    assert entry.reason is TierReason.CODE_MODE
    assert entry.detail and "with_columns" in entry.detail
    assert "fig-frozen" not in offline_export.bindings
    assert "fig-frozen" not in offline_export.prologues
    frozen = offline_export.frozen["fig-frozen"]
    assert frozen.kind == "figure"
    assert frozen.filter_state == []
    assert frozen.payload["figure"]["data"]  # the real (server-built) figure


def test_analyzable_but_unbindable_code_figure_freezes_with_binding_miss(
    offline_export: BundleManifest,
):
    entry = offline_export.tiers["fig-miss"]
    assert entry.tier is ComponentTier.FROZEN
    assert entry.reason is TierReason.BINDING_MISS
    # The detail names which bail-out fired, not a generic "no binding".
    assert entry.detail and entry.detail.startswith("code analyzed, but ")
    assert "frozen at the default filter state" in entry.detail
    assert "fig-miss" not in offline_export.bindings
    # No half-state: a figure that did not bind ships no IR either, only the
    # frozen payload the pipeline already produced.
    assert "fig-miss" not in offline_export.prologues
    assert offline_export.frozen["fig-miss"].kind == "figure"


def test_no_data_bundled_when_no_code_figure_binds(monkeypatch: pytest.MonkeyPatch):
    """A DC bundled speculatively for a code figure that failed to bind is
    dropped again — its frozen payload is self-contained."""
    from depictio.api.v1 import celery_tasks as celery_mod
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1 import deltatables_utils as dtu_mod

    doc = _dashboard_doc()
    doc["stored_metadata"] = [_code_component("fig-miss", MISS_CODE)]
    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([doc]))
    monkeypatch.setattr(db_mod, "deltatables_collection", _FakeCollection([]))
    monkeypatch.setattr(
        db_mod, "projects_collection", _FakeCollection([{"_id": PROJECT_OID, "links": []}])
    )
    monkeypatch.setattr(
        dtu_mod,
        "schema_deltatable_lite",
        lambda workflow_id, data_collection_id, init_data: dict(_frame().schema),
    )
    monkeypatch.setattr(
        dtu_mod,
        "load_deltatable_lite",
        lambda workflow_id, data_collection_id, metadata=None, select_columns=None, **kw: _frame(),
    )
    monkeypatch.setattr(dtu_mod, "_get_aggregation_hash", lambda dc_id: "agghash-code")
    monkeypatch.setattr(
        celery_mod,
        "build_figure_preview",
        lambda payload: {
            "figure": px.scatter(x=[0.0], y=[0.0]).to_plotly_json(),
            "metadata": {"visu_type": "code", "filter_applied": False, "was_sampled": False},
        },
    )

    manifest = export_manifest(
        str(DASHBOARD_OID), ExportUser(id=ObjectId(), is_admin=True)
    ).manifest
    assert manifest is not None
    assert manifest.tiers["fig-miss"].tier is ComponentTier.FROZEN
    assert manifest.data_refs == {}
    assert manifest.inline_blobs == {}
    assert manifest.bindings == {} and manifest.prologues == {}
