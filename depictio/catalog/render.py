"""Render a catalog output's ``renders_as`` on its fixture using depictio's REAL
dashboard components, served in a minimal Dash app.

The earlier static-HTML approach only reused the *libraries* (plotly.js /
ag-grid) — it did not look like depictio. This module instead calls depictio's
own builders with the output's ``fixture`` injected where a delta table would
normally be loaded, so the result is identical to the depictio viewer:

  - figure (UI)   → ``figure_component.utils.render_figure`` (mantine plotly template)
  - figure (code) → ``figure_component.callbacks.core._process_code_mode_figure``
                    (depictio's RestrictedPython executor; the ``df_modified``
                    code-mode contract applies)
  - card          → ``card_component.utils.build_card`` with the value computed by
                    ``compute_value`` (the real DMC card)
  - table         → depictio's AG-Grid column defs (``_build_column_definitions``)
                    rendered client-side from the fixture rows (the real
                    dash-ag-grid table + mantine theme)

The components are wrapped in a ``dmc.MantineProvider`` and served by a local
Dash app that loads depictio's own ``assets/`` (so the DMC theme + the AG-Grid
``mantine_light``/``mantine_dark`` styling match). ``advanced_viz`` / ``multiqc``
renders are recognised but not built yet — they show a placeholder alert.

Because this renders through depictio's stack, it requires the depictio runtime
(the dash venv); imports are kept lazy so ``import depictio.catalog.render`` stays
cheap and the heavy stack is only pulled when a preview is actually built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from depictio.models.components.advanced_viz.catalog import PROJECTS_DIR

if TYPE_CHECKING:
    from depictio.models.components.advanced_viz.catalog import CatalogOutput, Render

# Rows shown in a table preview (a fixture is a small canonical sample anyway).
_TABLE_PREVIEW_ROWS = 1000


class CatalogRenderError(Exception):
    """Raised when a catalog output cannot be rendered (no fixture, bad spec…)."""


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


def _load_fixture_df(output: CatalogOutput):  # -> pl.DataFrame
    """Load the output's bundled fixture (path under ``depictio/projects/``)."""
    import polars as pl

    if not output.fixture:
        raise CatalogRenderError(
            f"output {output.id!r} has no 'fixture' to preview — add a bundled "
            f"sample under projects/ (see catalog TODO 'add a fixture to every output')"
        )
    path = PROJECTS_DIR / output.fixture
    if not path.exists():
        raise CatalogRenderError(f"fixture not found: {path}")
    separator = "\t" if path.suffix == ".tsv" else ","
    return pl.read_csv(path, separator=separator).head(_TABLE_PREVIEW_ROWS)


def _label(render: Render, index: int) -> str:
    if render.component == "figure":
        return f"Figure ({'code' if render.code else render.visu_type})"
    if render.component == "card":
        return f"Card — {render.aggregation}({render.column})"
    if render.component == "advanced_viz":
        return f"Advanced viz — {render.kind}"
    if render.component == "table":
        return "Table"
    if render.component == "multiqc":
        return f"MultiQC — {render.section or 'section'}"
    return f"{render.component} #{index}"


# ---------------------------------------------------------------------------
# Per-component rendering — calls depictio's own builders
# ---------------------------------------------------------------------------


def _render_figure(df, render: Render, index: int, theme: str):
    from dash import dcc

    from depictio.dash.modules.figure_component.utils import render_figure

    if render.code:
        from depictio.dash.modules.figure_component.callbacks.core import (
            _process_code_mode_figure,
        )

        ok, fig, _ = _process_code_mode_figure(render.code, df, theme, f"catalog-preview-{index}")
        if not ok or fig is None:
            raise CatalogRenderError(
                "code figure failed — depictio code mode expects single-line "
                "`df_modified = …` preprocessing then `fig = px.…(df_modified, …)`"
            )
    else:
        fig, _ = render_figure(
            dict(render.dict_kwargs), render.visu_type or "scatter", df, theme=theme
        )

    return dcc.Graph(
        figure=fig,
        config={"displayModeBar": "hover", "responsive": True},
        style={"height": "420px", "width": "100%"},
    )


def _render_card(df, render: Render, index: int, theme: str):
    from depictio.dash.modules.card_component.utils import build_card, compute_value

    column, aggregation = render.column or "", render.aggregation or ""
    if column not in df.columns:
        raise CatalogRenderError(f"card column {column!r} absent from fixture {df.columns}")
    value = compute_value(df, column, aggregation)
    if isinstance(value, float):
        value = round(value, 4)
    return build_card(
        index=f"preview-card-{index}",
        title=f"{aggregation}({column})",
        column_name=column,
        column_type=str(df[column].dtype),
        aggregation=aggregation,
        value=value,
        build_frame=True,
        theme=theme,
    )


def _render_table(df, index: int, theme: str):
    import dash_ag_grid as dag

    from depictio.dash.modules.figure_component.utils import _get_theme_template
    from depictio.dash.modules.table_component.utils import (
        _build_column_definitions,
        _configure_column_filters,
    )

    cols_json = {c: {"type": str(df[c].dtype)} for c in df.columns}
    _configure_column_filters(cols_json)
    column_defs = _build_column_definitions(cols_json)

    # depictio's table uses an infinite (callback-fed) row model + an "ID" column
    # and getRowId="params.data.ID". For a static fixture we feed the rows
    # client-side, reusing depictio's exact column defs, mantine theme class and
    # default column behaviour so the grid looks identical.
    return dag.AgGrid(
        id={"type": "table-aggrid", "index": f"preview-table-{index}"},
        rowModelType="clientSide",
        columnDefs=column_defs,
        rowData=[{"ID": i, **row} for i, row in enumerate(df.to_dicts())],
        getRowId="params.data.ID",
        defaultColDef={
            "flex": 1,
            "minWidth": 150,
            "sortable": True,
            "resizable": True,
            "floatingFilter": True,
            "filter": True,
        },
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 100,
            "rowSelection": "multiple",
            "enableCellTextSelection": True,
        },
        className=_get_theme_template(theme),
        style={"height": "460px", "width": "100%"},
    )


def render_component(df, render: Render, index: int, theme: str) -> Any:
    """Build the real depictio Dash component for one ``renders_as`` target."""
    if render.component == "figure":
        return _render_figure(df, render, index, theme)
    if render.component == "card":
        return _render_card(df, render, index, theme)
    if render.component == "table":
        return _render_table(df, index, theme)
    raise CatalogRenderError(
        f"preview for component '{render.component}' is not supported yet "
        f"(figure/card/table only for now)"
    )


# ---------------------------------------------------------------------------
# Preview app
# ---------------------------------------------------------------------------


def build_preview_sections(output: CatalogOutput, theme: str = "light") -> list[Any]:
    """Build one titled section per ``renders_as`` target (real depictio comps).

    Per-render failures become an inline alert rather than aborting the whole
    preview, so a contributor sees every component's status at once.
    """
    import dash_mantine_components as dmc

    # Register the mantine plotly templates depictio applies at app startup.
    dmc.add_figure_templates()

    df = _load_fixture_df(output)
    sections: list[Any] = []
    for i, render in enumerate(output.renders_as):
        try:
            body = render_component(df, render, i, theme)
        except Exception as exc:
            body = dmc.Alert(str(exc), title="Render failed", color="red", variant="light")
        sections.append(
            dmc.Paper(
                [dmc.Text(_label(render, i), fw="bold", size="sm", mb="sm"), body],
                withBorder=True,
                p="md",
                mb="md",
                radius="md",
            )
        )
    return sections


def build_preview_layout(output: CatalogOutput, theme: str = "light") -> Any:
    """Full ``dmc.MantineProvider`` layout for an output's preview."""
    import dash_mantine_components as dmc
    from dash import html

    sections = build_preview_sections(output, theme)
    return dmc.MantineProvider(
        html.Div(
            [
                dmc.Title(output.id, order=3),
                dmc.Text(output.description or "", size="sm", mb="lg"),
                *sections,
            ],
            style={"padding": "24px", "maxWidth": "1100px", "margin": "0 auto"},
        ),
        forceColorScheme="dark" if theme == "dark" else "light",
    )


def _depictio_assets_folder() -> str:
    """depictio's own Dash ``assets/`` (DMC theme + AG-Grid mantine styling)."""
    import os

    import depictio.dash as dash_pkg

    # Use __path__ (works for namespace packages where __file__ is None).
    return os.path.join(next(iter(dash_pkg.__path__)), "assets")


def run_preview_server(
    output: CatalogOutput,
    theme: str = "light",
    port: int = 8899,
    open_browser: bool = True,
) -> None:
    """Serve an output's preview in a local Dash app using depictio's components."""
    import webbrowser

    import dash

    app = dash.Dash(
        __name__,
        assets_folder=_depictio_assets_folder(),
        assets_url_path="/assets",
        suppress_callback_exceptions=True,
    )
    app.layout = build_preview_layout(output, theme)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    app.run(port=port)
