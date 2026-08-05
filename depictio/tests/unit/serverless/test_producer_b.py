"""End-to-end tests for serverless producer B (build-from-spec).

Builds the worked example spec (``depictio/serverless/examples/penguins.yaml``)
against a temp data dir derived from the repo's penguins CSVs, and asserts the
manifest contract: stable synthetic dc_ids, complete data_refs (columns /
dtypes / companions / codebooks / hash), exact pruning, frozen figure payloads,
the tier table, and that the inline blob round-trips to a polars-readable
snappy Parquet. Manifest assembly is tested without the HTML template; the
injection assertions are skipped when ``dist-static/static.html`` is absent
(CI may not have built the viewer).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import polars as pl
import pytest

from depictio.models.models.serverless import (
    BundleManifest,
    BundleMode,
    ComponentTier,
    Producer,
    TierReason,
)
from depictio.serverless.preflight import classify_spec
from depictio.serverless.producer_b import (
    TEMPLATE_PATH,
    BuildResult,
    ProducerBError,
    build_manifest,
    build_static,
    load_spec,
    render_bundle_html,
    resolve_parquet_path,
    synthetic_dc_id,
    synthetic_wf_id,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLE_SPEC = REPO_ROOT / "depictio" / "serverless" / "examples" / "penguins.yaml"
ISLAND_REGIONS_CSV = (
    REPO_ROOT / "depictio" / "serverless" / "examples" / "data" / "island_regions.csv"
)
PENGUINS_DATA = REPO_ROOT / "depictio" / "projects" / "init" / "penguins" / "data"

WF_TAG = "penguin_species_analysis"
DC_TAG = "joined_penguins_complete"
# The example's second data collection: the island -> region lookup the
# cross-DC link resolves through (RFC §8, phase 7).
LINKED_DC_TAG = "island_regions"


def _penguins_frame() -> pl.DataFrame:
    """Join the repo's penguins CSV runs into the flat example table."""
    runs = sorted(p for p in PENGUINS_DATA.iterdir() if p.is_dir())
    parts = []
    for run in runs:
        demo = pl.read_csv(run / "demographic_data.csv")
        phys = pl.read_csv(run / "physical_features.csv")
        parts.append(demo.join(phys, on="individual_id", how="inner"))
    return pl.concat(parts)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("penguins-data")
    dc_dir = root / WF_TAG
    dc_dir.mkdir(parents=True)
    _penguins_frame().write_parquet(dc_dir / f"{DC_TAG}.parquet")
    pl.read_csv(ISLAND_REGIONS_CSV).write_parquet(dc_dir / f"{LINKED_DC_TAG}.parquet")
    return root


def _penguins_ref(manifest: BundleManifest):
    """The measurements DataRef (the example bundles two data collections)."""
    return manifest.data_refs[synthetic_dc_id(WF_TAG, DC_TAG)]


@pytest.fixture(scope="module")
def result(data_dir: Path) -> BuildResult:
    return build_manifest(load_spec(EXAMPLE_SPEC), data_dir)


@pytest.fixture(scope="module")
def manifest(result: BuildResult) -> BundleManifest:
    return result.manifest


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------


def test_manifest_validates_and_roundtrips(manifest: BundleManifest) -> None:
    assert manifest.producer is Producer.BUILD_FROM_SPEC
    assert manifest.mode is BundleMode.SINGLE_FILE
    assert manifest.dashboard.id  # runtime no-ops several component types without one
    assert manifest.dashboard.title == "Penguins — static bundle example"
    # JSON-safety guard: NaN/Inf tokens would blank the embedded blob.
    text = json.dumps(manifest.model_dump(mode="json"))
    assert "NaN" not in text and "Infinity" not in text
    assert BundleManifest.model_validate(json.loads(text))


def test_dc_ids_are_stable(data_dir: Path, manifest: BundleManifest) -> None:
    expected = hashlib.sha1(f"{WF_TAG}:{DC_TAG}".encode()).hexdigest()[:24]
    linked = synthetic_dc_id(WF_TAG, LINKED_DC_TAG)
    assert synthetic_dc_id(WF_TAG, DC_TAG) == expected
    assert set(manifest.data_refs) == {expected, linked}
    # A rebuild produces the same ids and the same blob bytes.
    again = build_manifest(load_spec(EXAMPLE_SPEC), data_dir).manifest
    assert set(again.data_refs) == {expected, linked}
    assert again.inline_blobs == manifest.inline_blobs
    # Component dc_ids in the mounted doc point at the same synthetic id.
    for comp in manifest.dashboard.doc["stored_metadata"]:
        if comp.get("data_collection_tag") == DC_TAG:
            assert comp["dc_id"] == expected


def test_components_carry_their_workflows_synthetic_id(manifest: BundleManifest) -> None:
    """Every component with a workflow tag names that workflow.

    Not decoration: each advanced_viz renderer gates its data fetch on a truthy
    ``metadata.wf_id`` and otherwise draws "missing data binding" — a
    ``wf_id: None`` document used to need a runtime workaround in the api shim.
    The id is derived from the workflow TAG, so both data collections of this
    one-workflow example share it, and the text component (no tags at all)
    still has none.
    """
    wf_id = synthetic_wf_id(WF_TAG)
    assert len(wf_id) == 24
    int(wf_id, 16)  # raises if not hex
    by_index = {c["index"]: c for c in manifest.dashboard.doc["stored_metadata"]}
    for comp in by_index.values():
        assert comp["wf_id"] == (wf_id if comp.get("workflow_tag") else None)
    # One workflow, two data collections, one workflow id.
    assert by_index["table-penguins"]["dc_id"] != by_index["table-island-regions"]["dc_id"]
    assert by_index["table-penguins"]["wf_id"] == by_index["table-island-regions"]["wf_id"]
    assert by_index["text-intro"]["wf_id"] is None


def test_data_ref_is_complete(manifest: BundleManifest) -> None:
    ref = _penguins_ref(manifest)
    assert ref.uri == f"inline:dc_{synthetic_dc_id(WF_TAG, DC_TAG)}"
    assert ref.rows == 342  # inner join of the repo CSVs (2 rows lack physical features)
    assert ref.size_bytes > 0
    names = [c.name for c in ref.columns]
    dtypes = {c.name: c.dtype for c in ref.columns}
    assert dtypes["body_mass_g"] == "Float64"
    assert dtypes["species"] == "String"
    assert dtypes["year"] == "Int64"
    # `year` is a non-String MultiSelect column → codebook + Int32 companion.
    assert ref.companions == {"__code__year": "year"}
    assert "__code__year" in names
    assert dtypes["__code__year"] == "Int32"
    assert ref.codebooks == {"year": {"2007": 0, "2008": 1, "2009": 2}}
    # `species` is a String MultiSelect column → direct membership, no codebook.
    assert "species" not in ref.codebooks
    assert ref.aggregation_hash is not None and len(ref.aggregation_hash) == 64


def test_pruning_kept_every_column_for_the_table(manifest: BundleManifest) -> None:
    # The live table widens pruning to keep-all (RFC §6: sorting/filtering may
    # touch any column), so the whole joined frame ships.
    ref = _penguins_ref(manifest)
    physical = {c.name for c in ref.columns if not c.name.startswith("__")}
    assert physical == {
        "individual_id",
        "island",
        "sex",
        "year",
        "species",
        "bill_length_mm",
        "bill_depth_mm",
        "flipper_length_mm",
        "body_mass_g",
    }


def test_inline_blob_roundtrips_to_snappy_parquet(manifest: BundleManifest) -> None:
    ref = _penguins_ref(manifest)
    blob_key = ref.uri.removeprefix("inline:")
    assert blob_key in manifest.inline_blobs
    raw = base64.b64decode(manifest.inline_blobs[blob_key])
    assert len(raw) == ref.size_bytes
    assert hashlib.sha256(raw).hexdigest() == ref.aggregation_hash
    df = pl.read_parquet(io.BytesIO(raw))
    assert df.height == ref.rows
    assert [(c.name, c.dtype) for c in ref.columns] == [
        (name, str(dtype)) for name, dtype in df.schema.items()
    ]
    # snappy re-export (engine-spike builder rule): bare hyparquet can decode it.
    import pyarrow.parquet as pq

    meta = pq.ParquetFile(io.BytesIO(raw)).metadata
    assert meta.row_group(0).column(0).compression.lower() == "snappy"


def test_tier_table(manifest: BundleManifest) -> None:
    tiers = {cid: e.tier for cid, e in manifest.tiers.items()}
    assert tiers == {
        "text-intro": ComponentTier.LIVE,
        "card-body-mass": ComponentTier.LIVE,
        "card-species-count": ComponentTier.LIVE,
        "filter-species": ComponentTier.LIVE,
        "filter-year": ComponentTier.LIVE,
        # The scatter binds (RFC §4), so it refills live in the browser.
        "scatter-mass-flipper": ComponentTier.LIVE,
        # Tables are live since phase 3 — sortSlice recomputes pages offline.
        "table-penguins": ComponentTier.LIVE,
        # The code-mode bar chart transpiles and binds (RFC §7, phase 6), so
        # the browser replays its prologue at every filter state.
        "figure-codemode": ComponentTier.LIVE,
        # advanced_viz data-path kinds are live since phase 4 — the in-browser
        # engine recomputes /advanced_viz/data from the bundled Parquet.
        "sunburst-mass": ComponentTier.LIVE,
        "dotplot-mass": ComponentTier.LIVE,
        # The linked lookup collection (RFC §8, phase 7): its filter drives the
        # cross-DC link, its table shows the rows the translation reads.
        "filter-region": ComponentTier.LIVE,
        "table-island-regions": ComponentTier.LIVE,
    }
    for cid in ("sunburst-mass", "dotplot-mass"):
        av_entry = manifest.tiers[cid]
        assert av_entry.reason is None
        assert av_entry.detail and "in-browser engine" in av_entry.detail
    for cid in ("scatter-mass-flipper", "figure-codemode"):
        figure_entry = manifest.tiers[cid]
        assert figure_entry.reason is None
        assert figure_entry.detail is None
    table_entry = manifest.tiers["table-penguins"]
    assert table_entry.reason is None
    assert table_entry.detail is None


def _trace_points(trace: dict) -> int:
    """Point count of one trace's x array — plotly ≥6 serialises numeric arrays
    as base64 typed arrays ({'dtype', 'bdata'}), older versions as lists."""
    x = trace["x"]
    if isinstance(x, dict) and "bdata" in x:
        import numpy as np

        return len(base64.b64decode(x["bdata"])) // np.dtype(x["dtype"]).itemsize
    return len(x)


def test_bound_figure_ships_no_frozen_payload(manifest: BundleManifest) -> None:
    # A bound figure refills at EVERY filter state, including the default empty
    # one, so a frozen snapshot would only duplicate data the bundle carries.
    # Same for the live table — the whole example ships zero frozen payloads.
    assert manifest.frozen == {}
    binding = manifest.bindings["scatter-mass-flipper"]
    assert binding.group_cols == ["species"]
    assert [t.group["species"] for t in binding.traces] == ["Adelie", "Chinstrap", "Gentoo"]
    for trace in binding.traces:
        assert trace.fields == {"x": "flipper_length_mm", "y": "body_mass_g"}
    assert binding.sampled is False
    # Scaffold: layout intact, data arrays stripped (refill.ts writes them back).
    assert len(binding.scaffold["data"]) == 3
    assert all("x" not in t and "y" not in t for t in binding.scaffold["data"])
    assert binding.scaffold["layout"]["legend"]["title"]["text"] == "species"
    # The bound columns are in the bundle (pruning keeps every referenced one).
    ref = _penguins_ref(manifest)
    assert {"flipper_length_mm", "body_mass_g", "species"} <= {c.name for c in ref.columns}


def test_example_code_mode_figure_is_live_with_its_prologue(manifest: BundleManifest) -> None:
    """The demo's code-mode bar chart (the one the phase-6 Playwright spec
    drives): IR + binding, no frozen payload, bound to DERIVED columns."""
    assert manifest.tiers["figure-codemode"].tier is ComponentTier.LIVE
    assert "figure-codemode" not in manifest.frozen
    assert [op.model_dump(mode="json") for op in manifest.prologues["figure-codemode"]] == [
        {
            "op": "group_by",
            "by": ["species"],
            "agg": [{"col": "body_mass_g", "fn": "mean", "alias": "mean_mass"}],
        },
        {"op": "sort", "by": ["mean_mass"], "desc": [True]},
    ]
    binding = manifest.bindings["figure-codemode"]
    assert binding.group_cols == []
    assert [t.fields for t in binding.traces] == [{"x": "species", "y": "mean_mass"}]
    assert binding.scaffold["data"][0]["type"] == "bar"
    assert all("x" not in t and "y" not in t for t in binding.scaffold["data"])
    # `mean_mass` exists only after the prologue runs; `species`/`body_mass_g`
    # — the columns it reads — are in the bundle.
    ref = _penguins_ref(manifest)
    assert {"species", "body_mass_g"} <= {c.name for c in ref.columns}


def test_text_labelled_figure_binds_and_keeps_its_label_column(data_dir: Path) -> None:
    """A ``text=`` figure stays LIVE end-to-end: pruning keeps the label column
    in the bundled parquet, so the binder can build against it.

    Regression — ``referenced_columns`` omitted ``text``, so the column was
    pruned out and the figure froze with ``binding_miss``.
    """
    import yaml

    from depictio.models.models.dashboards import DashboardDataLite

    spec_dict = yaml.safe_load(EXAMPLE_SPEC.read_text())
    for comp in spec_dict["components"]:
        if comp["tag"] == "scatter-mass-flipper":
            comp["dict_kwargs"]["text"] = "island"
    manifest = build_manifest(DashboardDataLite.model_validate(spec_dict), data_dir).manifest

    entry = manifest.tiers["scatter-mass-flipper"]
    assert entry.tier is ComponentTier.LIVE
    assert entry.reason is None
    binding = manifest.bindings["scatter-mass-flipper"]
    for trace in binding.traces:
        assert trace.fields["text"] == "island"
    # Pruning kept the label column, and the scaffold ships no text array.
    ref = _penguins_ref(manifest)
    assert "island" in {c.name for c in ref.columns}
    assert all("text" not in t for t in binding.scaffold["data"])


def test_unbindable_figure_falls_back_to_frozen(data_dir: Path) -> None:
    """A figure the matcher refuses keeps the frozen path + binding_miss."""
    import yaml

    from depictio.models.models.dashboards import DashboardDataLite

    spec_dict = yaml.safe_load(EXAMPLE_SPEC.read_text())
    for comp in spec_dict["components"]:
        if comp["tag"] == "scatter-mass-flipper":
            # `hover_data` gives every point an (n, k) customdata array. The
            # runtime writes 1-D arrays only, so a bound figure would refill the
            # points and leave their hover text describing other rows — the
            # matcher refuses rather than ship that.
            comp["dict_kwargs"]["hover_data"] = ["island"]
    manifest = build_manifest(DashboardDataLite.model_validate(spec_dict), data_dir).manifest

    assert "scatter-mass-flipper" not in manifest.bindings
    entry = manifest.tiers["scatter-mass-flipper"]
    assert entry.tier is ComponentTier.FROZEN
    assert entry.reason is TierReason.BINDING_MISS
    assert entry.detail and "binding" in entry.detail
    frozen = manifest.frozen["scatter-mass-flipper"]
    assert frozen.kind == "figure"
    assert frozen.filter_state == []  # default filter state
    fig = frozen.payload["figure"]
    assert sum(_trace_points(t) for t in fig["data"]) == 342
    meta = frozen.payload["metadata"]
    assert meta["filter_applied"] is False
    assert meta["was_sampled"] is False
    assert meta["total_data_count"] == 342


def test_preflight_refines_the_figure_verdict(manifest: BundleManifest) -> None:
    # Preflight is data-free, so it can only promise the frozen fallback; the
    # build refines it once the matcher has seen the frame. That holds for both
    # figures: the code-mode one's prologue transpiles without data too, but
    # whether it BINDS is only knowable against the frame.
    refined = {"scatter-mass-flipper", "figure-codemode"}
    rows = {r.component_id: r for r in classify_spec(load_spec(EXAMPLE_SPEC))}
    final = {cid: e.tier for cid, e in manifest.tiers.items()}
    for cid in refined:
        assert rows[cid].tier is ComponentTier.FROZEN
        assert rows[cid].reason is TierReason.BINDING_MISS
        assert final[cid] is ComponentTier.LIVE
    assert rows["figure-codemode"].detail and "transpilable" in rows["figure-codemode"].detail
    assert {k: v.tier for k, v in rows.items() if k not in refined} == {
        k: v for k, v in final.items() if k not in refined
    }


# ---------------------------------------------------------------------------
# Data-dependent behaviours (synthetic mini-specs)
# ---------------------------------------------------------------------------


def _mini_spec(components: list[dict]) -> dict:
    return {"title": "mini", "components": components}


def test_datetime_companion_and_live_table(tmp_path: Path) -> None:
    from datetime import date

    from depictio.models.models.dashboards import DashboardDataLite

    (tmp_path / "wf").mkdir()
    pl.DataFrame(
        {
            "sample": ["a", "b", "c"],
            "captured": [date(2024, 1, 1), date(2024, 6, 1), date(2025, 1, 1)],
            "value": [1.0, 2.0, float("nan")],
        }
    ).write_parquet(tmp_path / "wf" / "dc.parquet")

    spec = DashboardDataLite.model_validate(
        _mini_spec(
            [
                {
                    "tag": "filter-date",
                    "component_type": "interactive",
                    "workflow_tag": "wf",
                    "data_collection_tag": "dc",
                    "interactive_component_type": "DateRangePicker",
                    "column_name": "captured",
                    "column_type": "datetime",
                },
                {
                    "tag": "table-1",
                    "component_type": "table",
                    "workflow_tag": "wf",
                    "data_collection_tag": "dc",
                },
            ]
        )
    )
    manifest = build_manifest(spec, tmp_path).manifest

    ref = next(iter(manifest.data_refs.values()))
    assert ref.companions == {"__ts__captured": "captured"}
    dtypes = {c.name: c.dtype for c in ref.columns}
    assert dtypes["__ts__captured"] == "Int64"
    # Table ⇒ keep-all pruning; the whole frame (+ companions) ships as data.
    assert set(dtypes) == {"sample", "captured", "value", "__ts__captured"}
    # Live table (phase 3): no frozen payload — the runtime sorts/paginates/
    # filters the bundled Parquet itself. This spec has no figure, so the
    # manifest is bindings-free: live tables don't ride on the binding path.
    assert manifest.tiers["table-1"].tier is ComponentTier.LIVE
    assert manifest.tiers["table-1"].reason is None
    assert manifest.tiers["table-1"].detail is None
    assert "table-1" not in manifest.frozen
    assert manifest.frozen == {}
    assert manifest.bindings == {}
    # NaN in the data must not leak into the serialized manifest (the rows now
    # live only in the Parquet blob, which is base64 — but keep the guard).
    assert "NaN" not in json.dumps(manifest.model_dump(mode="json"))


def test_table_without_dc_is_omitted() -> None:
    from depictio.models.models.dashboards import DashboardDataLite

    spec = DashboardDataLite.model_validate(
        _mini_spec([{"tag": "table-nodc", "component_type": "table"}])
    )
    rows = {r.component_id: r for r in classify_spec(spec)}
    assert rows["table-nodc"].tier is ComponentTier.OMITTED
    assert rows["table-nodc"].reason is TierReason.UNSUPPORTED


@pytest.fixture
def code_data_dir(tmp_path: Path) -> Path:
    """A tiny two-group frame for the code-mode cases (distinct group means, so
    the derived frame has a total order and nothing hinges on tie-breaking)."""
    (tmp_path / "wf").mkdir()
    pl.DataFrame(
        {
            "g": ["a", "b", "a", "c"],
            "x": [1.0, 5.0, 3.0, 9.0],
            "y": [2.0, 4.0, 6.0, 14.0],
        }
    ).write_parquet(tmp_path / "wf" / "dc.parquet")
    return tmp_path


def _code_spec(code: str):
    from depictio.models.models.dashboards import DashboardDataLite

    return DashboardDataLite.model_validate(
        _mini_spec(
            [
                {
                    "tag": "fig-code",
                    "component_type": "figure",
                    "workflow_tag": "wf",
                    "data_collection_tag": "dc",
                    "visu_type": "scatter",
                    "mode": "code",
                    "code_content": code,
                }
            ]
        )
    )


PROLOGUE_CODE = (
    "import polars as pl\n"
    "import plotly.express as px\n"
    "\n"
    "df2 = df.group_by('g').agg(pl.col('x').mean().alias('mean_x'))\n"
    "df2 = df2.sort('mean_x', descending=True)\n"
    "fig = px.bar(df2, x='g', y='mean_x')\n"
)


def test_code_mode_figure_with_a_prologue_goes_live(code_data_dir: Path) -> None:
    """Phase 6 (RFC §7): transpilable code ships IR + binding and NO frozen
    payload — the runtime re-derives the frame at every filter state."""
    manifest = build_manifest(_code_spec(PROLOGUE_CODE), code_data_dir).manifest

    entry = manifest.tiers["fig-code"]
    assert entry.tier is ComponentTier.LIVE
    assert entry.reason is None and entry.detail is None
    assert manifest.frozen == {}

    ops = [op.model_dump(mode="json") for op in manifest.prologues["fig-code"]]
    assert ops == [
        {
            "op": "group_by",
            "by": ["g"],
            "agg": [{"col": "x", "fn": "mean", "alias": "mean_x"}],
        },
        {"op": "sort", "by": ["mean_x"], "desc": [True]},
    ]

    # The binding references DERIVED column names (the group_by's output), not
    # the base frame's — the runtime refills from the reshaped table.
    binding = manifest.bindings["fig-code"]
    assert binding.sampled is False
    assert binding.group_cols == []
    assert [t.fields for t in binding.traces] == [{"x": "g", "y": "mean_x"}]
    assert all("x" not in t and "y" not in t for t in binding.scaffold["data"])

    # Code mode ⇒ never projected: the whole schema ships, because the runtime
    # re-runs the reshape over the base columns.
    ref = next(iter(manifest.data_refs.values()))
    assert {c.name for c in ref.columns} == {"g", "x", "y"}

    # And the manifest still round-trips with IR + binding in it.
    assert BundleManifest.model_validate(json.loads(json.dumps(manifest.model_dump(mode="json"))))


def test_free_code_mode_figure_binds_on_the_base_frame(code_data_dir: Path) -> None:
    """Code that reshapes nothing binds straight to the base table — and the
    contract omits its empty op list from ``prologues``."""
    manifest = build_manifest(
        _code_spec("fig = px.scatter(df.to_pandas(), x='x', y='y')"), code_data_dir
    ).manifest

    assert manifest.tiers["fig-code"].tier is ComponentTier.LIVE
    assert manifest.frozen == {}
    assert manifest.prologues == {}  # empty op lists are never shipped
    assert [t.fields for t in manifest.bindings["fig-code"].traces] == [{"x": "x", "y": "y"}]


def test_untranspilable_code_mode_figure_stays_frozen(code_data_dir: Path) -> None:
    """A computed column is outside the IR grammar: freeze with ``code_mode``
    and the transpiler's own refusal reason."""
    code = (
        "df2 = df.with_columns((pl.col('x') * 2).alias('x2'))\nfig = px.scatter(df2, x='x', y='x2')"
    )
    manifest = build_manifest(_code_spec(code), code_data_dir).manifest

    entry = manifest.tiers["fig-code"]
    assert entry.tier is ComponentTier.FROZEN
    assert entry.reason is TierReason.CODE_MODE
    assert entry.detail and "with_columns" in entry.detail
    assert manifest.frozen["fig-code"].kind == "figure"
    assert manifest.frozen["fig-code"].filter_state == []
    assert "fig-code" not in manifest.bindings and "fig-code" not in manifest.prologues


def test_code_mode_figure_whose_px_call_is_opaque_stays_frozen(code_data_dir: Path) -> None:
    """The prologue transpiles, but a ``px`` kwarg is not a literal — the binder
    would have to guess its column hypothesis, so freeze instead."""
    code = "df2 = df.sort('x')\nfig = px.scatter(df2, x='x', y='y', title=str(len(df2)))"
    manifest = build_manifest(_code_spec(code), code_data_dir).manifest

    entry = manifest.tiers["fig-code"]
    assert entry.tier is ComponentTier.FROZEN
    assert entry.reason is TierReason.CODE_MODE
    assert entry.detail and "not analyzable" in entry.detail
    assert "fig-code" in manifest.frozen
    assert "fig-code" not in manifest.bindings and "fig-code" not in manifest.prologues


def test_code_mode_figure_omitted_when_execution_fails(code_data_dir: Path) -> None:
    manifest = build_manifest(_code_spec("fig = undefined_name"), code_data_dir).manifest
    entry = manifest.tiers["fig-code"]
    assert entry.tier is ComponentTier.OMITTED
    assert entry.reason is TierReason.CODE_MODE
    assert "fig-code" not in manifest.frozen


def test_omitted_types_get_accurate_reasons() -> None:
    from depictio.models.models.dashboards import DashboardDataLite

    spec = DashboardDataLite.model_validate(
        _mini_spec(
            [
                {
                    "tag": "mqc",
                    "component_type": "multiqc",
                    "workflow_tag": "wf",
                    "data_collection_tag": "dc",
                    "selected_module": "fastqc",
                    "selected_plot": "x",
                },
                {
                    "tag": "img",
                    "component_type": "image",
                    "workflow_tag": "wf",
                    "data_collection_tag": "dc",
                    "image_column": "path",
                },
            ]
        )
    )
    rows = {r.component_id: r for r in classify_spec(spec)}
    assert rows["mqc"].tier is ComponentTier.OMITTED
    assert rows["mqc"].reason is TierReason.MULTIQC
    assert rows["img"].tier is ComponentTier.OMITTED
    assert rows["img"].reason is TierReason.IMAGE


def test_missing_parquet_raises_with_expected_path(tmp_path: Path) -> None:
    spec = load_spec(EXAMPLE_SPEC)
    with pytest.raises(ProducerBError, match=f"{WF_TAG}/{DC_TAG}.parquet"):
        build_manifest(spec, tmp_path)


def test_missing_referenced_column_raises(tmp_path: Path) -> None:
    from depictio.models.models.dashboards import DashboardDataLite

    (tmp_path / "wf").mkdir()
    pl.DataFrame({"x": [1.0]}).write_parquet(tmp_path / "wf" / "dc.parquet")
    spec = DashboardDataLite.model_validate(
        _mini_spec(
            [
                {
                    "tag": "card-1",
                    "component_type": "card",
                    "workflow_tag": "wf",
                    "data_collection_tag": "dc",
                    "aggregation": "average",
                    "column_name": "missing_col",
                    "column_type": "float64",
                }
            ]
        )
    )
    with pytest.raises(ProducerBError, match="missing_col"):
        build_manifest(spec, tmp_path)


def test_data_yaml_map_overrides_layout(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.parquet"
    pl.DataFrame({"a": [1]}).write_parquet(elsewhere)
    (tmp_path / "data.yaml").write_text(f"'{WF_TAG}:{DC_TAG}': {elsewhere}\n")
    assert resolve_parquet_path(tmp_path, WF_TAG, DC_TAG) == elsewhere


# ---------------------------------------------------------------------------
# Injection (skipped when the viewer bundle is not built, e.g. bare CI)
# ---------------------------------------------------------------------------


def test_render_bundle_html_injects_manifest(manifest: BundleManifest) -> None:
    if not TEMPLATE_PATH.exists():
        pytest.skip("dist-static/static.html not built (run `pnpm run build:static`)")
    html = render_bundle_html(manifest)
    assert "__BUNDLE_MANIFEST__" not in html
    assert '"producer": "B"' in html or '"producer":"B"' in html


def test_build_static_end_to_end(data_dir: Path, tmp_path: Path) -> None:
    if not TEMPLATE_PATH.exists():
        pytest.skip("dist-static/static.html not built (run `pnpm run build:static`)")
    out = tmp_path / "nested" / "bundle.html"
    result = build_static(EXAMPLE_SPEC, data_dir, out)
    assert out.exists()
    html = out.read_text()
    assert "__BUNDLE_MANIFEST__" not in html
    # The embedded manifest survives extraction and validates.
    start = html.index('<script id="bundle-manifest" type="application/json">')
    start = html.index(">", start) + 1
    end = html.index("</script>", start)
    embedded = BundleManifest.model_validate_json(html[start:end].replace("<\\/", "</"))
    assert embedded.dashboard.id == result.manifest.dashboard.id
