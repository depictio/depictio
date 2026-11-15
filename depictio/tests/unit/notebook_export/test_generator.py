"""The generator on the seeded dashboards: a valid Quarto document, run top to bottom."""

from __future__ import annotations

import ast
import builtins
import html
import re

import polars as pl

from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    NotebookBuilder,
    StagePlan,
    generate_qmd,
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


_CHUNK_RE = re.compile(r"^(`{3,})\{python\}\n(.*?)\n\1$", re.S | re.M)


def python_chunks(source: str) -> list[str]:
    """The ``{python}`` chunks of a ``.qmd``, in document order."""
    return [m.group(2) for m in _CHUNK_RE.finditer(source)]


def _targets(node: ast.AST):
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _targets(elt)
    elif isinstance(node, ast.Starred):
        yield from _targets(node.value)


def _top_level_bound(tree: ast.Module) -> set[str]:
    bound: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                bound.update(_targets(t))
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor)):
            bound.update(_targets(stmt.target))
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(stmt.name)
    return bound


def _free_loads(tree: ast.Module) -> set[str]:
    """Names the chunk reads without binding them anywhere inside it."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    loads = {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    return loads - bound


def assert_defined_before_use(source: str) -> dict[str, int]:
    """Run top to bottom, every chunk only reads what an earlier chunk defined,
    and every public global is defined by exactly one chunk (a second one would
    silently replace what the first showed). Returns ``{name: chunk index}``."""
    chunks = python_chunks(source)
    assert chunks, "no {python} chunks found"
    owners: dict[str, int] = {}
    private: set[str] = set()
    known = set(dir(builtins))
    for i, body in enumerate(chunks):
        tree = ast.parse(body)
        unknown = _free_loads(tree) - known - set(owners) - private
        assert not unknown, f"chunk {i} reads {unknown} that no earlier chunk defines"
        for name in _top_level_bound(tree):
            if name.startswith("_"):
                private.add(name)
                continue
            assert name not in owners, f"{name!r} defined by chunks {owners[name]} and {i}"
            owners[name] = i
    return owners


def test_penguins_export_defines_every_global_once(penguins_tabs):
    src = generate_qmd(penguins_plan(penguins_tabs))
    owners = assert_defined_before_use(src)
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
    src = generate_qmd(penguins_plan(penguins_tabs))
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
    # Text tiles and section titles stay real ATX headings — the table of
    # contents, the anchors and the fold script are all built from them — with
    # the icon/colour/fold marker riding inline inside the line. Tabs are h3 and
    # sections h4 wherever they sit in the family, under the one h2 the tabs
    # hang off, so the outline reads title > results > tab > section rather
    # than jumping a level between tabs.
    # The main tab carries its own sidebar label ("Species"), not the
    # dashboard's title, which the document already prints as its h1.
    assert re.search(r"^\s*# Penguins Species Analysis", src, re.M)
    assert re.search(r"^\s*## <span data-dpx-accent=.*Results", src, re.M)
    assert re.search(r"^\s*### <span data-dpx-accent=.*Species", src, re.M)
    assert re.search(r"^\s*#### <span data-dpx-accent=.*Cohort", src, re.M)
    assert "How to run" in src
    # A section's cards fold into one row (card_row, an even CSS grid), same
    # shape as the dashboard's own card strip, instead of stacking one per cell.
    assert "card_row([viz_individuals, viz_species_mix, viz_island_balance, " in src
    assert "viz_sex_recorded])" in src
    # A persistent link back to the live dashboard, and the metadata as a
    # scannable table rather than a run-on sentence.
    assert "https://depictio.example.org/dashboard/6824cb3b89d2b72169309738" in src
    assert "| **Live dashboard** |" in src
    assert "| **Exported** |" in src
    # Groups and panels.
    assert (
        "group_heavy_adelie = group_heavy_adelie.filter("
        "pl.col('individual_id').is_in(['N1A1', 'N2A2']))" in src
    )
    assert "panel_biscoe = panel_biscoe.filter(pl.col('island').is_in(['Biscoe']))" in src


def test_card_row_reads_the_real_display_not_the_iframe_tile():
    # card_row's members are a mix of HTML objects (code-mode cards) and Depictio
    # components (api-mode, multi-metric cards). A Depictio component's
    # `.html` is a different thing — an embeddable iframe tile pointing back
    # at a live session — while `_repr_html_()` is the same self-contained
    # look the object would show if displayed bare. Grouping cards into a
    # row must read the latter: exec the generator's own injected cell so
    # this exercises the exact code that ships, not a reimplementation.
    class HTML:  # IPython.display.HTML, as far as card_row and metric_card use it
        def __init__(self, data: str) -> None:
            self.data = data

        def _repr_html_(self) -> str:
            return self.data

    body = NotebookBuilder._metric_card_cell(None).body
    ns: dict = {}
    exec(compile(body, "<metric_card_cell>", "exec"), {"HTML": HTML}, ns)
    card_row, metric_card = ns["card_row"], ns["metric_card"]

    class FakeApiCard:
        def _repr_html_(self) -> str:
            return '<div style="display:inline-block">Species mix</div>'

        @property
        def html(self) -> str:  # pragma: no cover - must not be touched
            raise AssertionError("card_row must not read .html, the iframe tile")

    row = card_row([metric_card("Samples", 3), FakeApiCard()])
    assert "iframe" not in row.data
    assert "Samples" in row.data and "Species mix" in row.data


def test_unknown_schema_falls_back_to_string_cast(penguins_tabs):
    src = generate_qmd(penguins_plan(penguins_tabs, dtypes=None))
    assert "pl.col('species').cast(pl.Utf8, strict=False).is_in(['Adelie', 'Gentoo'])" in src


def test_preflight_lists_every_tile_with_a_verdict(penguins_tabs):
    builder = NotebookBuilder(penguins_plan(penguins_tabs))
    pre = builder.preflight()
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
    src = generate_qmd(plan)
    owners = assert_defined_before_use(src)
    pre = NotebookBuilder(plan).preflight()
    kinds = {c.component_type for c in pre.components}
    assert "advanced_viz" in kinds
    assert any(c.status == "api" for c in pre.components)
    assert all(c.status != "omitted" for c in pre.components)
    assert "client.component(" in src
    assert len(owners) > 20


def test_penguins_export_is_one_quarto_document(penguins_tabs):
    import yaml

    src = generate_qmd(penguins_plan(penguins_tabs))
    assert src.startswith("---\n")
    front = yaml.safe_load(src.split("\n---\n", 1)[0].removeprefix("---\n"))
    assert front["title"] == "Penguins Species Analysis"
    assert front["jupyter"] == "python3"
    assert front["format"]["html"]["embed-resources"] is True
    assert "marimo" not in src and "mo.Html" not in src
    assert "from IPython.display import HTML" in python_chunks(src)[0]
    assert "| **Notebook** | Quarto document (.qmd) |" in src or "Quarto document (.qmd)" in src


def test_a_highlight_points_at_the_figure_it_repeats(ampliseq_tabs):
    """A highlight re-shows a figure from another tab. The document already
    draws that figure in its own tab's part, so the highlight is a pointer,
    with no name and no code of its own."""
    tabs = ampliseq_tabs
    state = AnalysisState.model_validate(
        {"context": {"dashboard_id": str(tabs[0]["dashboard_id"])}}
    )
    plan = ExportPlan(tabs=tabs, project=None, state=state, dcs=[], stages=[], title="x")
    pre = NotebookBuilder(plan).preflight()
    highlights = [c for c in pre.components if c.component_type == "highlight"]
    assert highlights
    assert all(c.status == "code" and c.name is None for c in highlights)
    src = generate_qmd(plan)
    source = next(
        m
        for t in tabs
        for m in t["stored_metadata"]
        if m.get("component_type") == "highlight" and m.get("source_tab")
    )
    assert f"from the **{html.escape(source['source_tab'])}** tab" in src
