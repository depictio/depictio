"""Tests for composing a DashboardDataLite from a scanned run directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.models.components.advanced_viz.catalog import (
    CatalogEntry,
    CatalogFind,
    CatalogOutput,
    Render,
)
from depictio.models.components.advanced_viz.compose import (
    GRID_WIDTH,
    build_dashboard_from_run_dir,
    render_to_component_dict,
)
from depictio.models.models.dashboards import DashboardDataLite

REPO_ROOT = Path(__file__).resolve().parents[3]
VIRALRECON_RUN = REPO_ROOT / "depictio" / "projects" / "nf-core" / "viralrecon" / "3.0.0" / "run_1"


def _entry(**kw) -> CatalogEntry:
    base = {"id": "tool", "name": "tool", "outputs": []}
    base.update(kw)
    return CatalogEntry(**base)


# ---------------------------------------------------------------------------
# Unit: Render → lite component dict mapping
# ---------------------------------------------------------------------------


def test_advanced_viz_render_emits_use_reference():
    render = Render(
        id="volcano",
        component="advanced_viz",
        kind="volcano",
        roles={"feature_id": "id", "effect_size": "lfc", "significance": "q"},
    )
    output = CatalogOutput(id="tool_diff", find=CatalogFind(filename="x.csv"), recipe="t/d.py")
    entry = _entry(outputs=[output])
    comp = render_to_component_dict(
        render, entry, output, workflow_tag="nf-core/x", data_collection_tag="tool_diff", index=0
    )
    assert comp is not None
    assert comp["component_type"] == "advanced_viz"
    assert comp["use"] == "tool/volcano"  # render id preferred
    assert comp["data_collection_tag"] == "tool_diff"


def test_advanced_viz_without_render_id_uses_output_short_and_kind():
    render = Render(component="advanced_viz", kind="qq", roles={"p_value": "pval"})
    output = CatalogOutput(id="tool_diff", find=CatalogFind(filename="x.csv"), recipe="t/d.py")
    entry = _entry(outputs=[output])
    comp = render_to_component_dict(
        render, entry, output, workflow_tag="", data_collection_tag="tool_diff", index=1
    )
    assert comp is not None
    assert comp["use"] == "tool/diff"  # output id minus the "tool_" prefix
    assert comp["viz_kind"] == "qq"


def test_card_render_maps_fields_and_derives_column_type():
    render = Render(component="card", column="coverage", aggregation="average")
    output = CatalogOutput(
        id="tool_cov",
        find=CatalogFind(filename="x.tsv"),
        columns={"coverage": "Float64"},
    )
    entry = _entry(outputs=[output])
    comp = render_to_component_dict(
        render, entry, output, workflow_tag="", data_collection_tag="tool_cov", index=0
    )
    assert comp is not None
    assert comp["component_type"] == "card"
    assert comp["column_name"] == "coverage"
    assert comp["aggregation"] == "average"
    assert comp["column_type"] == "float64"


def test_figure_code_mode_render():
    render = Render(component="figure", code="fig = px.box(df)")
    output = CatalogOutput(id="tool_fig", find=CatalogFind(filename="x.tsv"))
    entry = _entry(outputs=[output])
    comp = render_to_component_dict(
        render, entry, output, workflow_tag="", data_collection_tag="tool_fig", index=0
    )
    assert comp is not None
    assert comp["mode"] == "code"
    assert comp["code_content"] == "fig = px.box(df)"


def test_multiqc_render_is_skipped():
    render = Render(component="multiqc", section="fastqc")
    output = CatalogOutput(id="tool_mqc", find=CatalogFind(filename="x"))
    entry = _entry(outputs=[output])
    comp = render_to_component_dict(
        render, entry, output, workflow_tag="", data_collection_tag="tool_mqc", index=0
    )
    assert comp is None


# ---------------------------------------------------------------------------
# End-to-end on a real run directory
# ---------------------------------------------------------------------------


def _require_run():
    if not VIRALRECON_RUN.is_dir():
        pytest.skip("viralrecon run_1 fixture not present")


def test_build_returns_nonempty_dashboard():
    _require_run()
    dash = build_dashboard_from_run_dir(VIRALRECON_RUN, confirm_with_versions=False)
    assert isinstance(dash, DashboardDataLite)
    assert dash.components, "expected catalog-recognised components"


def test_advanced_viz_components_validate_and_expand_use():
    _require_run()
    dash = build_dashboard_from_run_dir(VIRALRECON_RUN, confirm_with_versions=False)
    kinds = {
        getattr(c, "viz_kind", None)
        for c in dash.components
        if getattr(c, "component_type", None) == "advanced_viz"
    }
    # mosdepth genome/amplicon coverage → coverage_track (use: expanded to config)
    assert "coverage_track" in kinds
    for comp in dash.components:
        if getattr(comp, "component_type", None) == "advanced_viz":
            assert comp.config is not None
            assert comp.viz_kind == comp.config.viz_kind


def test_layout_fits_grid():
    _require_run()
    dash = build_dashboard_from_run_dir(VIRALRECON_RUN, confirm_with_versions=False)
    for comp in dash.components:
        layout = getattr(comp, "layout", None)
        assert layout is not None
        assert layout["x"] + layout["w"] <= GRID_WIDTH


def test_yaml_roundtrip_lite_only():
    _require_run()
    dash = build_dashboard_from_run_dir(VIRALRECON_RUN, confirm_with_versions=False)
    # Lite → yaml → Lite must re-validate (do NOT go through to_full/from_full).
    reparsed = DashboardDataLite.from_yaml(dash.to_yaml())
    assert len(reparsed.components) == len(dash.components)


# ---------------------------------------------------------------------------
# Architectural guard: the compose module must stay recipe-free / offline
# ---------------------------------------------------------------------------


def test_compose_module_never_imports_recipes():
    import ast

    source = (
        REPO_ROOT / "depictio" / "models" / "components" / "advanced_viz" / "compose.py"
    ).read_text()
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not any(m == "depictio.recipes" or m.startswith("depictio.recipes.") for m in imported)
