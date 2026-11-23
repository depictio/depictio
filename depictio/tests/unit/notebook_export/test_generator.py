"""The generator on the seeded dashboards: a valid Quarto document, run top to bottom."""

from __future__ import annotations

import ast
import builtins
import html
import re
from dataclasses import replace

import polars as pl

from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    NotebookBuilder,
    StagePlan,
    _layer_prose,
    generate_qmd,
)
from depictio.api.v1.services.notebook_export.reading_order import MarkdownUnit
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
    # The title lives in the front matter only (Quarto's title block), never
    # repeated as a heading in the body.
    assert "\ntitle: Penguins Species Analysis\n" in src
    assert not re.search(r"^\s*# Penguins Species Analysis", src, re.M)
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
    from depictio.notebook import StaticCard, static_card_row, static_figures
    from depictio.notebook.qmd_safe import esc

    glb = {
        "HTML": HTML,
        "html_text": esc,
        "static_figures": static_figures,
        "StaticCard": StaticCard,
        "static_card_row": static_card_row,
    }
    exec(compile(body, "<metric_card_cell>", "exec"), glb, ns)
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


def test_a_highlight_draws_its_figure_in_place(ampliseq_tabs):
    """A highlight re-shows a figure from another tab, and the dashboard draws
    that figure on the tab that highlights it. So does the document: the
    Overview's part holds the figure itself, read from its own tab, with a
    line linking there, not a pointer to another part."""
    tabs = ampliseq_tabs
    state = AnalysisState.model_validate(
        {"context": {"dashboard_id": str(tabs[0]["dashboard_id"])}}
    )
    plan = ExportPlan(tabs=tabs, project=None, state=state, dcs=[], stages=[], title="x")
    builder = NotebookBuilder(plan)
    entries = [e for e, _ in builder.entries() if not isinstance(e, MarkdownUnit)]
    drawn = [e for e in entries if e.highlight is not None]
    seeded = [
        m for t in tabs for m in t["stored_metadata"] if m.get("component_type") == "highlight"
    ]
    assert len(drawn) == len(seeded) == 3
    for e in drawn:
        assert e.unit.meta["component_type"] in ("figure", "advanced_viz")
        assert e.name  # a cell of its own
        assert e.unit.meta["index"] == e.highlight["source_component"]
        assert e.unit.section == e.highlight["section"]
    src = generate_qmd(plan)
    for e in drawn:
        tab_id = e.unit.tab["dashboard_id"]
        assert f"client.component({tab_id!r}, {e.unit.meta['index']!r}" in src
    assert "drawn in that tab's part" not in src
    assert "*From the [Community &amp; Diversity](#tab-community-diversity) tab.*" in src


def test_a_highlight_is_its_own_tile_in_the_report_layer(ampliseq_tabs):
    """The report layer, the outline and the editor know a highlight by its own
    (tab, index), not by the figure it draws: unticking it drops the highlight
    and leaves that figure on its own tab, and the preview marks it with its
    own ref while the runtime still mounts the figure."""
    tabs = ampliseq_tabs
    main = str(tabs[0]["dashboard_id"])
    state = AnalysisState.model_validate({"context": {"dashboard_id": main}})

    def plan(layer=None):
        return ExportPlan(
            tabs=tabs, project=None, state=state, dcs=[], stages=[], title="x", report_layer=layer
        )

    drawn = [
        e
        for e, _ in NotebookBuilder(plan()).entries()
        if not isinstance(e, MarkdownUnit) and e.highlight is not None
    ]
    hl = drawn[0]
    own_tab, own_index = hl.layer_key
    assert own_index == hl.highlight["index"]
    assert (own_tab, own_index) != (str(hl.unit.tab["dashboard_id"]), hl.unit.meta["index"])

    src = generate_qmd(plan())
    figure_ref = f"{hl.unit.tab['dashboard_id']}:{hl.unit.meta['index']}"
    assert f'data-depictio-tile="{figure_ref}" data-depictio-ref="{own_tab}:{own_index}"' in src

    layer = {"tiles": [{"tab_id": own_tab, "component_id": own_index, "in_report": False}]}
    left = [e for e, _ in NotebookBuilder(plan(layer)).entries() if not isinstance(e, MarkdownUnit)]
    assert own_index not in {e.highlight["index"] for e in left if e.highlight is not None}
    # The figure itself stays on the tab it lives on.
    assert any(
        e.highlight is None
        and e.unit.meta.get("index") == hl.unit.meta["index"]
        and str(e.unit.tab["dashboard_id"]) == str(hl.unit.tab["dashboard_id"])
        for e in left
    )


def test_an_unresolvable_highlight_stays_a_pointer():
    tab = {
        "dashboard_id": PENGUINS_DASHBOARD,
        "title": "T",
        "is_main_tab": True,
        "stored_metadata": [
            {
                "index": "hl",
                "component_type": "highlight",
                "source_tab": "Nowhere",
                "source_component": "gone",
            }
        ],
    }
    state = AnalysisState.model_validate({"context": {"dashboard_id": PENGUINS_DASHBOARD}})
    plan = ExportPlan(tabs=[tab], project=None, state=state, dcs=[], stages=[], title="x")
    src = generate_qmd(plan)
    assert "from the **Nowhere** tab" in src


def _code_figure_tab(code: str) -> dict:
    return {
        "dashboard_id": PENGUINS_DASHBOARD,
        "title": "Grouped",
        "stored_metadata": [
            {
                "index": "code-fig",
                "component_type": "figure",
                "mode": "code",
                "title": "By group",
                "dc_id": PENGUINS_DC,
                "code_content": code,
            }
        ],
    }


def _grouped_plan(tab: dict, color_by: dict, display: str = "color") -> ExportPlan:
    plan = penguins_plan([tab])
    plan.state = AnalysisState.model_validate(
        {
            **penguins_state().model_dump(mode="json"),
            "color_by": color_by,
            "display_mode": display,
        }
    )
    return plan


def test_a_grouped_export_hands_code_figures_what_the_server_does():
    """`depictio_group_kwargs` / `depictio_group_by` follow the exported colour-by,
    and the frame carries the group label, exactly as `build_figure_preview` hands
    them to code that opts in by naming them."""
    code = "fig = px.scatter(df, x='bill_length_mm', y='bill_depth_mm', **depictio_group_kwargs)"
    src = generate_qmd(_grouped_plan(_code_figure_tab(code), {"kind": "groups"}, "facet"))
    assert_defined_before_use(src)
    assert "'color': '__depictio_group__'" in src
    assert "'facet_col': '__depictio_group__'" in src
    assert "depictio_group_by=['__depictio_group__']" in src
    assert ".alias('__depictio_group__')" in src

    frame = pl.DataFrame(
        {
            "individual_id": ["N1A1", "N9"],
            "bill_length_mm": [1.0, 2.0],
            "bill_depth_mm": [3.0, 4.0],
        }
    )
    import plotly.express as px

    cell = next(c for c in python_chunks(src) if "def _make_fig_by_group" in c)
    scope = {"pl": pl, "px": px, "final_penguins_complete": frame}
    scope["depictio_group_kwargs"], scope["depictio_group_by"] = {}, []
    exec(cell, scope)  # noqa: S102 - the generated cell
    fig = scope["fig_by_group"]
    assert {t.name for t in fig.data} == {"Heavy Adelie", "Other"}


def test_column_colour_by_reaches_code_figures_and_ungrouped_code_is_untouched():
    code = "fig = px.scatter(df, x='year', y='body_mass_g', **depictio_group_kwargs)"
    src = generate_qmd(
        _grouped_plan(_code_figure_tab(code), {"kind": "column", "column_name": "island"})
    )
    assert "'color': 'island'" in src and "depictio_group_by=['island']" in src
    # Code that does not name the grouping is run exactly as before.
    plain = generate_qmd(
        _grouped_plan(
            _code_figure_tab("fig = px.scatter(df, x='year', y='body_mass_g')"), {"kind": "groups"}
        )
    )
    assert "_make_fig_by_group(final_penguins_complete)" in plain
    assert ".alias('__depictio_group__')" not in plain


def _ampliseq_plan(tabs, **extra) -> ExportPlan:
    dc_ids = sorted(
        {str(m.get("dc_id")) for t in tabs for m in t["stored_metadata"] if m.get("dc_id")}
    )
    state = AnalysisState.model_validate(
        {"context": {"dashboard_id": str(tabs[0]["dashboard_id"])}}
    )
    return ExportPlan(
        tabs=tabs,
        project=None,
        state=state,
        dcs=[DCPlan(dc_id=d, tag=f"dc_{i}") for i, d in enumerate(dc_ids)],
        stages=[],
        title="nf-core/ampliseq",
        **extra,
    )


def test_tab_links_become_jumps_to_the_tab_headings(ampliseq_tabs):
    src = generate_qmd(_ampliseq_plan(ampliseq_tabs))
    assert "](tab:" not in src
    anchors = set(re.findall(r"\{#(tab-[a-z0-9-]+)\}", src))
    targets = set(re.findall(r"\]\(#(tab-[a-z0-9-]+)\)", src))
    assert targets, "the seeded tab links should survive as in-document links"
    assert targets <= anchors, targets - anchors


def test_text_values_are_filled_when_the_document_runs(ampliseq_tabs):
    """Live values (`{{name}}`, `{{param:KEY}}`) print the server's numbers, not braces."""
    texts = [
        m
        for t in ampliseq_tabs
        for m in t["stored_metadata"]
        if m.get("component_type") == "text" and m.get("values")
    ]
    assert texts, "ampliseq seeds a text tile with live values"
    text = texts[0]
    names = list(text["values"])
    fallback = {name: 0.4123 for name in names}
    src = generate_qmd(_ampliseq_plan(ampliseq_tabs, text_values={text["index"]: fallback}))
    cell = next(c for c in python_chunks(src) if repr(str(text["index"])) in c and "fill_text" in c)
    assert cell.startswith("#| output: asis")

    import contextlib
    import io

    from depictio.notebook import fill_text

    class _Offline:
        def text_values(self, dashboard_id, index, state, *, fallback=None):
            return dict(fallback or {})

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(cell, {"fill_text": fill_text, "client": _Offline(), "depictio_state": {}})  # noqa: S102
    printed = out.getvalue()
    for name in names:
        assert "{{" + name + "}}" not in printed
    assert "](tab:" not in printed


def test_inline_text_icons_become_svg():
    tab = {
        "dashboard_id": PENGUINS_DASHBOARD,
        "title": "T",
        "stored_metadata": [
            {"index": "t1", "component_type": "text", "body": "![](icon:mdi:flask) **Samples**"}
        ],
    }
    plan = penguins_plan([tab])
    plan.icons = {"mdi:flask": '<svg id="flask"></svg>'}
    src = generate_qmd(plan)
    assert '<svg id="flask"></svg>' in src and "](icon:" not in src


def _front(src: str) -> dict:
    import yaml

    return yaml.safe_load(src.split("\n---\n", 1)[0].removeprefix("---\n"))


def test_the_report_is_in_paper_by_default(penguins_tabs):
    from depictio.api.v1.services.notebook_export.generator import PAPER_CHROME

    plan = penguins_plan(penguins_tabs)
    plan.brand = {"app_name": "Depictio", "primary": "violet", "font_family": "Lato, sans-serif"}
    src = generate_qmd(plan)
    brand = _front(src)["brand"]["light"]
    # The page's Bootstrap theme, from the instance brand, inline (one file).
    assert brand["color"] == {
        "primary": "#7950f2",
        "background": "#ffffff",
        "foreground": "#212529",
    }
    boot = brand["defaults"]["bootstrap"]["defaults"]
    assert boot["font-family-sans-serif"] == "Lato, sans-serif"
    assert boot["border-color"] == "rgba(33, 37, 41, 0.11)"
    # The chrome restyled, with the primary and its ink set beside it.
    assert PAPER_CHROME in src
    assert "--dpx-primary: #7950f2; --dpx-accent-fg: #7048e8;" in src
    assert "--dpx-font: Lato, sans-serif;" in src
    # The figures and the font: the setup cell turns them on.
    chunks = python_chunks(src)
    assert chunks[1].startswith("#| output: asis")
    assert (
        "print(use_theme(\"paper\", primary='#7950f2', font_family='Lato, sans-serif'))"
        in chunks[1]
    )
    # The foot says what produced the file, outside every fold.
    assert "dpx-footer" in _front(src)["format"]["html"]["include-after-body"]["text"]


def test_classic_keeps_quartos_stock_look(penguins_tabs):
    from depictio.api.v1.services.notebook_export.generator import PAPER_CHROME

    plan = penguins_plan(penguins_tabs)
    plan.theme = "classic"
    src = generate_qmd(plan)
    assert "brand" not in _front(src)
    assert PAPER_CHROME not in src
    assert 'print(use_theme("classic"))' in python_chunks(src)[1]


def test_unbranded_paper_falls_back_to_mantine_blue_and_inter(penguins_tabs):
    src = generate_qmd(penguins_plan(penguins_tabs))
    boot = _front(src)["brand"]["light"]["defaults"]["bootstrap"]["defaults"]
    assert boot["font-family-sans-serif"].startswith("'Inter Variable', Inter,")
    assert "print(use_theme(\"paper\", primary='#228be6'))" in src


def _heading_lines(src: str) -> list[str]:
    return [line for line in src.splitlines() if re.match(r"#{1,6} <span data-dpx-accent", line)]


def test_the_report_opens_on_its_first_tab_with_the_rest_folded(ampliseq_tabs):
    """Every tab after the first opens folded, every section the dashboard
    opens folded opens folded, and the filters are one folded line."""
    src = generate_qmd(_ampliseq_plan(ampliseq_tabs))
    tabs = [h for h in _heading_lines(src) if 'data-dpx-kind="tab"' in h]
    assert len(tabs) == len(ampliseq_tabs)
    assert 'data-dpx-fold="closed"' not in tabs[0]
    assert all('data-dpx-fold="closed"' in h for h in tabs[1:])
    collapsed = {
        s["name"] for t in ampliseq_tabs for s in t.get("grid_sections") or [] if s.get("collapsed")
    }
    assert collapsed
    for h in _heading_lines(src):
        if 'data-dpx-kind="section"' not in h:
            continue
        name = html.unescape(re.sub(r"<[^>]+>", "", h.split(">", 1)[1]))
        name = re.sub(r"\s*\{#.*\}$", "", name).strip()
        assert ('data-dpx-fold="closed"' in h) == (name in collapsed), name
    filters = next(h for h in _heading_lines(src) if 'data-dpx-kind="filters"' in h)
    assert 'data-dpx-fold="closed"' in filters
    assert '<span class="dpx-h-note">none active</span>' in filters
    # One fold control per tab, and links into folded parts open them.
    assert "function tabButtons()" in src and "function openTo(target)" in src


def test_active_filters_are_counted_on_the_folded_filters_line(penguins_tabs):
    src = generate_qmd(penguins_plan(penguins_tabs))
    filters = next(h for h in _heading_lines(src) if 'data-dpx-kind="filters"' in h)
    assert re.search(r'<span class="dpx-h-note">\d+ active</span>', filters)


def test_a_text_tiles_own_headings_rank_under_its_section(ampliseq_tabs):
    """`### Data & QC` inside a text tile used to close the section and the
    tab holding it, and listed itself among the tabs in the contents."""
    src = generate_qmd(_ampliseq_plan(ampliseq_tabs))
    for line in src.splitlines():
        m = re.match(r"(#{1,6}) ", line)
        if (
            m
            and "data-dpx-accent" not in line
            and not line.startswith("# ")
            and "{#methods}" not in line
        ):
            # Any heading a tile writes is below the section level (h4).
            assert len(m.group(1)) >= 5, line
    assert "##### Data & QC" in src
    assert "##### About this dashboard" in src


def test_the_overview_holds_everything_the_live_overview_shows(ampliseq_tabs):
    """In the dashboard's order: the opening text and the floating map, then
    the sections, with the highlighted figures drawn in place."""
    plan = _ampliseq_plan(ampliseq_tabs)
    builder = NotebookBuilder(plan)
    overview: list[str] = []
    tabs = 0
    for e, _ in builder.entries():
        if isinstance(e, MarkdownUnit):
            if e.kind == "tab":
                tabs += 1
                if tabs > 1:
                    break
            overview.append(e.text)
        else:
            overview.append(
                ("hl:" if e.highlight is not None else "") + str(e.unit.meta.get("index"))
            )
    assert overview == [
        "Overview",
        "ov-hero",
        "ov-study",
        "ov-run",
        "ov-steps",
        "ov-about",
        "ref-sampling-sites",
        "Key figures",
        "ov-kf-samples",
        "ov-kf-phyla",
        "ov-kf-shannon",
        "ov-kf-reads-kept",
        "Findings",
        "ov-findings",
        "hl:comm-composition-by-group",
        "hl:adv-volcano",
        "hl:ord-embedding",
        "ov-tree",
        "How to read this dashboard",
        "ov-how-to-read",
        # Pinned to the Overview too (nf-core RULES, #1306).
        "Sample sheet",
        "sample-sheet",
    ]


# ---------------------------------------------------------------------------
# The report layer's placement of tiles
# ---------------------------------------------------------------------------


def _figure_of(tab) -> dict:
    return next(m for m in tab["stored_metadata"] if m.get("component_type") == "figure")


def test_two_tabs_moving_a_tile_to_the_same_section_keep_both(penguins_tabs):
    """A moved section is per tab: two tabs that both move a tile to a section
    of the same name each get their own, and no tile is dropped on the way."""
    main = next(t for t in penguins_tabs if t.get("is_main_tab"))
    child = next(t for t in penguins_tabs if not t.get("is_main_tab"))
    plan = replace(
        penguins_plan(penguins_tabs),
        report_layer={
            "tiles": [
                {
                    "tab_id": str(main["dashboard_id"]),
                    "component_id": str(_figure_of(main)["index"]),
                    "section": "Overview",
                },
                {
                    "tab_id": str(child["dashboard_id"]),
                    "component_id": str(_figure_of(child)["index"]),
                    "section": "Overview",
                },
            ]
        },
    )
    src = generate_qmd(plan)
    overviews = re.findall(r'^:::: \{data-depictio-section="[^"]*:Overview"\}$', src, re.M)
    assert len(overviews) == 2
    for tab in (main, child):
        ref = f"{tab['dashboard_id']}:{_figure_of(tab)['index']}"
        assert f'data-depictio-tile="{ref}"' in src


def _card_strip_plan(excluded: set[str]) -> ExportPlan:
    """One tab holding a strip of exactly three cards over the penguins data."""
    tab = {
        "dashboard_id": PENGUINS_DASHBOARD,
        "title": "Strip",
        "is_main_tab": True,
        "stored_metadata": [
            {
                "index": f"card-{i}",
                "component_type": "card",
                "title": f"Card {i}",
                "dc_id": PENGUINS_DC,
                "aggregation": "count",
                "column_name": "species",
            }
            for i in range(3)
        ],
    }
    return replace(
        penguins_plan([tab]),
        pdf=True,
        report_layer={
            "tiles": [
                {"tab_id": PENGUINS_DASHBOARD, "component_id": f"card-{i}", "in_pdf": False}
                for i in range(3)
                if f"card-{i}" in excluded
            ]
        },
    )


def _card_rows(src: str) -> list[tuple[str, int]]:
    return [(m.group(1), m.start()) for m in re.finditer(r"^card_row\(\[([^\]]*)\]\)", src, re.M)]


def _fold_at(src: str, pos: int) -> str:
    """The format whose fold the position sits in (the nearest open above it)."""
    opens = [
        m.group(1)
        for m in re.finditer(r'^::: \{\.content-visible when-format="(html|typst)"\}$', src, re.M)
        if m.start() < pos
    ]
    assert opens, "the row sits in no content-visible fold"
    return opens[-1]


def test_a_pdf_excluded_card_stays_out_of_the_pdfs_card_row():
    """A strip the PDF only partly carries: the page draws every card, the PDF
    row references only the cards the layer keeps in it."""
    plan = _card_strip_plan({"card-1"})
    src = generate_qmd(plan)
    rows = _card_rows(src)
    assert len(rows) == 2
    (full, full_at), (pdf, pdf_at) = sorted(rows, key=lambda r: -len(r[0].split(", ")))
    assert len(full.split(", ")) == 3 and len(pdf.split(", ")) == 2
    assert set(pdf.split(", ")) < set(full.split(", "))
    assert _fold_at(src, full_at) == "html"
    assert _fold_at(src, pdf_at) == "typst"


def test_a_card_row_entirely_excluded_from_the_pdf_prints_no_pdf_row():
    plan = _card_strip_plan({"card-0", "card-1", "card-2"})
    src = generate_qmd(plan)
    rows = _card_rows(src)
    assert len(rows) == 1
    assert _fold_at(src, rows[0][1]) == "html"


# ---------------------------------------------------------------------------
# The layer's TipTap prose as markdown
# ---------------------------------------------------------------------------


def _prose_doc(*content) -> dict:
    return {"type": "doc", "content": list(content)}


def test_layer_prose_renders_author_json_of_an_odd_shape():
    """Any editor can PUT a layer, so none of these shapes may fail the export."""
    odd = [
        {"type": "text", "content": ["not a node"], "text": "t"},
        {"type": "text", "marks": ["bold"], "text": "b"},
        {"type": "heading", "attrs": "2", "content": [{"type": "text", "text": "h"}]},
        {"type": "heading", "attrs": {"level": "many"}, "content": [{"type": "text", "text": "i"}]},
        {"type": "codeBlock", "content": ["not a node"]},
        {"type": "paragraph", "content": "not a list"},
        ["not", "a", "node"],
        None,
    ]
    for node in odd:
        assert isinstance(_layer_prose(node), str)
    # Deep nesting is walked to a cap, not to the interpreter's limit.
    deep = {"type": "paragraph", "content": [{"type": "text", "text": "bottom"}]}
    for _ in range(2000):
        deep = {"type": "blockquote", "content": [deep]}
    assert isinstance(_layer_prose(_prose_doc(deep)), str)


def test_a_layer_code_block_keeps_its_lines_and_its_fence_beats_its_backticks():
    three = _layer_prose(
        _prose_doc({"type": "codeBlock", "content": [{"type": "text", "text": "a\nb\nc"}]})
    )
    assert "a\nb\nc" in three
    ticked = _layer_prose(
        _prose_doc({"type": "codeBlock", "content": [{"type": "text", "text": "x ``` y"}]})
    )
    assert "````\nx ``` y\n````" in ticked
