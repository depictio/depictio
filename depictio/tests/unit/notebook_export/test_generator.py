"""The generator on the seeded dashboards: valid marimo, one definition per global."""

from __future__ import annotations

import ast
import subprocess
import sys

import polars as pl
import pytest

from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    NotebookBuilder,
    StagePlan,
    generate_marimo,
)
from depictio.models.models.analysis_state import AnalysisState

PENGUINS_DC = "646b0f3c1e4a2d7f8e5b8ca1"
PENGUINS_DASHBOARD = "6824cb3b89d2b72169309738"

PENGUINS_DTYPES = {
    "individual_id": pl.String,
    "species": pl.String,
    "island": pl.String,
    "sex": pl.String,
    "year": pl.Int64,
    "body_mass_g": pl.Float64,
    "bill_length_mm": pl.Float64,
    "bill_depth_mm": pl.Float64,
    "flipper_length_mm": pl.Float64,
}


def _filter(index, column, itype, value):
    return {
        "index": index,
        "column_name": column,
        "interactive_component_type": itype,
        "value": value,
        "metadata": {"dc_id": PENGUINS_DC, "column_name": column},
    }


def penguins_state() -> AnalysisState:
    return AnalysisState.model_validate(
        {
            "filters": [
                _filter("filter-species", "species", "MultiSelect", ["Adelie", "Gentoo"]),
                _filter("filter-mass", "body_mass_g", "RangeSlider", [3500, 5000]),
                {
                    "index": "__depictio_group__:g1",
                    "column_name": "individual_id",
                    "interactive_component_type": "MultiSelect",
                    "value": ["N1A1", "N2A2"],
                    "source": "group_filter",
                    "metadata": {"dc_id": PENGUINS_DC},
                },
            ],
            "groups": [
                {
                    "id": "g1",
                    "name": "Heavy Adelie",
                    "color": "#e64980",
                    "dc_id": PENGUINS_DC,
                    "column_name": "individual_id",
                    "values": ["N1A1", "N2A2"],
                    "filter_active": True,
                }
            ],
            "display_mode": "facet",
            "funnel": {"stage_order": ["filter-mass", "filter-species"]},
            "split_panels": [
                {
                    "name": "Biscoe",
                    "constraints": [
                        _filter("__depictio_group__:panel:b", "island", "MultiSelect", ["Biscoe"])
                    ],
                },
                {
                    "name": "Dream",
                    "constraints": [
                        _filter("__depictio_group__:panel:d", "island", "MultiSelect", ["Dream"])
                    ],
                },
            ],
            "context": {"dashboard_id": PENGUINS_DASHBOARD},
        }
    )


def _stage(index, label, column, itype, value, rows):
    return StagePlan(
        index=index,
        label=label,
        column=column,
        interactive_component_type=itype,
        value=value,
        source_dc_id=PENGUINS_DC,
        per_dc={
            PENGUINS_DC: [
                {"interactive_component_type": itype, "column_name": column, "value": value}
            ]
        },
        rows_by_dc={PENGUINS_DC: rows},
    )


def penguins_plan(tabs, *, dtypes=PENGUINS_DTYPES) -> ExportPlan:
    dc = DCPlan(
        dc_id=PENGUINS_DC, tag="penguins_complete", dtypes=dtypes, initial_rows=342, n_cols=12
    )
    stages = [
        _stage("filter-mass", "Body mass (g)", "body_mass_g", "RangeSlider", [3500, 5000], 250),
        _stage("filter-species", "Species", "species", "MultiSelect", ["Adelie", "Gentoo"], 151),
        _stage(
            "__depictio_group__:g1",
            "Heavy Adelie",
            "individual_id",
            "MultiSelect",
            ["N1A1", "N2A2"],
            2,
        ),
    ]
    return ExportPlan(
        tabs=tabs,
        project={
            "name": "Palmer Penguins",
            "workflows": [
                {
                    "workflow_tag": "penguin_species_analysis",
                    "engine": {"name": "python", "version": "3.11"},
                }
            ],
        },
        state=penguins_state(),
        dcs=[dc],
        stages=stages,
        title="Penguins Species Analysis",
        subtitle="Body size across species",
        exported_by="t.weber",
        instance="depictio.example.org",
    )


# ---------------------------------------------------------------------------
# The guard: no global is defined by two cells, returns match definitions.
# ---------------------------------------------------------------------------


def _cell_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(d, ast.Attribute) and d.attr == "cell" for d in node.decorator_list
        ):
            out.append(node)
    return out


def _bound_names(fn: ast.FunctionDef) -> set[str]:
    bound: set[str] = set()

    def targets(node):
        if isinstance(node, ast.Name):
            bound.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for e in node.elts:
                targets(e)
        elif isinstance(node, ast.Starred):
            targets(node.value)

    for stmt in fn.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                targets(t)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            targets(stmt.target)
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            targets(stmt.target)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if item.optional_vars is not None:
                    targets(item.optional_vars)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(stmt.name)
    return {n for n in bound if not n.startswith("_")}


def _returned_names(fn: ast.FunctionDef) -> set[str]:
    for stmt in fn.body:
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                return set()
            if isinstance(stmt.value, ast.Tuple):
                return {e.id for e in stmt.value.elts if isinstance(e, ast.Name)}
            if isinstance(stmt.value, ast.Name):
                return {stmt.value.id}
    return set()


def assert_no_global_redefinition(source: str) -> dict[str, int]:
    tree = ast.parse(source)
    cells = _cell_functions(tree)
    assert cells, "no @app.cell functions found"
    owners: dict[str, int] = {}
    for i, fn in enumerate(cells):
        bound = _bound_names(fn)
        assert _returned_names(fn) == bound, (
            f"cell {i}: returns {_returned_names(fn)} but defines {bound}"
        )
        for name in bound:
            assert name not in owners, f"{name!r} defined by cells {owners[name]} and {i}"
            owners[name] = i
    for i, fn in enumerate(cells):
        params = {a.arg for a in fn.args.args}
        unknown = {p for p in params if p not in owners}
        assert not unknown, f"cell {i} reads {unknown} that no cell defines"
        assert all(owners[p] != i for p in params)
    return owners


def test_penguins_export_defines_every_global_once(penguins_tabs):
    src = generate_marimo(penguins_plan(penguins_tabs))
    owners = assert_no_global_redefinition(src)
    for name in (
        "client",
        "DASHBOARD_ID",
        "depictio_state",
        "df_penguins_complete",
        "stage_1_penguins_complete",
        "stage_2_penguins_complete",
        "stage_3_penguins_complete",
        "final_penguins_complete",
        "group_heavy_adelie",
        "panel_biscoe",
        "panel_dream",
    ):
        assert name in owners, name
    assert "df" not in owners and "fig" not in owners


def test_penguins_export_content(penguins_tabs):
    src = generate_marimo(penguins_plan(penguins_tabs))
    # Stage order follows the funnel order in the plan, not the filter list.
    assert src.index("body_mass_g') >= 3500") < src.index("is_in(['Adelie', 'Gentoo'])")
    assert "stage_1_penguins_complete = df_penguins_complete" in src
    assert (
        '# Stage 2, "Species" (MultiSelect): Adelie, Gentoo. After this stage: '
        "penguins_complete → 151 rows." in src
    )
    # Code-mode figures are inlined verbatim, wrapped so `df`/`fig` stay local.
    assert "def _make_fig_" in src and "    return fig" in src
    assert "px.violin(" in src
    # UI figures render through the API, not a reconstructed px.* call.
    assert "px.scatter(\n        final_penguins_complete," not in src
    assert "a scatter figure built by Depictio's chart builder" in src
    # The table is an explicit reduction; every seeded card carries a
    # secondary visualization (donut, box plot, gauge...), so cards render
    # through the API too rather than showing only the hero number.
    assert ".head(100)" in src
    assert "a gauge card built by Depictio's card renderer" in src
    assert (
        "'938c7080-b193-5529-8dcd-673f4fa917ae'" in src
    )  # "Bills > 50 mm", filter_expr applied server-side
    # Text tiles and section titles are markdown.
    assert "## Cohort" in src and "# Penguins Species Analysis" in src
    assert "How to run" in src
    # Groups and panels.
    assert (
        "group_heavy_adelie = group_heavy_adelie.filter("
        "pl.col('individual_id').is_in(['N1A1', 'N2A2']))" in src
    )
    assert "panel_biscoe = panel_biscoe.filter(pl.col('island').is_in(['Biscoe']))" in src


def test_unknown_schema_falls_back_to_string_cast(penguins_tabs):
    src = generate_marimo(penguins_plan(penguins_tabs, dtypes=None))
    assert "pl.col('species').cast(pl.Utf8, strict=False).is_in(['Adelie', 'Gentoo'])" in src


def test_preflight_lists_every_tile_with_a_verdict(penguins_tabs):
    builder = NotebookBuilder(penguins_plan(penguins_tabs))
    pre = builder.preflight(ipynb_available=True)
    tiles = {
        m["index"]
        for t in penguins_tabs
        for m in t["stored_metadata"]
        if m["component_type"] != "interactive"
    }
    assert {c.index for c in pre.components} == tiles
    assert all(c.status in ("code", "api", "omitted") for c in pre.components)
    assert pre.counts["stages"] == 3 and pre.counts["dcs"] == 1
    # UI-built figures and every multi-metric card render through the API;
    # the rest (text, the table, and the few code-mode figures) stay
    # closed-form Python.
    assert pre.counts["code"] == 10 and pre.counts["api"] == 24
    assert all(c.tab for c in pre.components)
    named = [c for c in pre.components if c.component_type != "text"]
    assert all(c.name for c in named)
    assert len({c.name for c in named}) == len(named)


def test_ampliseq_export_defines_every_global_once(ampliseq_tabs):
    tabs = ampliseq_tabs
    dc_ids = sorted(
        {str(m.get("dc_id")) for t in tabs for m in t["stored_metadata"] if m.get("dc_id")}
    )
    dcs = [DCPlan(dc_id=d, tag=f"dc_{i}") for i, d in enumerate(dc_ids)]
    state = AnalysisState.model_validate(
        {"context": {"dashboard_id": str(tabs[0]["dashboard_id"])}}
    )
    plan = ExportPlan(
        tabs=tabs, project=None, state=state, dcs=dcs, stages=[], title="nf-core/ampliseq"
    )
    src = generate_marimo(plan)
    owners = assert_no_global_redefinition(src)
    pre = NotebookBuilder(plan).preflight(ipynb_available=False)
    kinds = {c.component_type for c in pre.components}
    assert "advanced_viz" in kinds
    assert any(c.status == "api" for c in pre.components)
    assert all(c.status != "omitted" for c in pre.components)
    assert "client.component(" in src
    assert len(owners) > 20


@pytest.mark.skipif(sys.platform == "win32", reason="subprocess path quoting")
def test_marimo_check_accepts_the_penguins_export(penguins_tabs, tmp_path):
    pytest.importorskip("marimo")
    path = tmp_path / "penguins.py"
    path.write_text(generate_marimo(penguins_plan(penguins_tabs)))
    proc = subprocess.run(
        [sys.executable, "-m", "marimo", "check", "--strict", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
