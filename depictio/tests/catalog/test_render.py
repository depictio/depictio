"""Tests for the catalog preview render core (``depictio.catalog.render``).

These exercise depictio's REAL component builders (figure / card / table) with a
catalog output's bundled fixture injected, so they require the depictio dash
runtime. They assert that each ``renders_as`` target builds the genuine depictio
Dash component (a plotly ``Graph``, a DMC card ``Paper``, a dash-ag-grid
``AgGrid``) — i.e. the preview looks like the depictio viewer, not a bespoke page.
"""

from __future__ import annotations

import dash_mantine_components as dmc
import polars as pl
import pytest

from depictio.catalog.render import (
    CatalogRenderError,
    _load_fixture_df,
    build_preview_sections,
    render_component,
)
from depictio.models.components.advanced_viz.catalog import (
    CatalogFind,
    CatalogOutput,
    Render,
    load_catalog_entries,
)

FLAGSHIP = "qiime2_alpha_diversity"


@pytest.fixture(autouse=True)
def _figure_templates() -> None:
    # depictio registers the mantine plotly templates at app startup.
    dmc.add_figure_templates()


def _get_output(output_id: str) -> CatalogOutput:
    return next(o for e in load_catalog_entries() for o in e.outputs if o.id == output_id)


@pytest.fixture
def flagship_df() -> pl.DataFrame:
    return _load_fixture_df(_get_output(FLAGSHIP))


# ---------------------------------------------------------------------------
# Fixture loading / error handling
# ---------------------------------------------------------------------------


def test_no_fixture_raises() -> None:
    output = CatalogOutput(
        id="t",
        find=CatalogFind(filename="x.csv"),
        renders_as=[Render(component="table")],
    )
    with pytest.raises(CatalogRenderError, match="fixture"):
        _load_fixture_df(output)


def test_unsupported_component_raises(flagship_df: pl.DataFrame) -> None:
    render = Render(component="advanced_viz", kind="volcano")
    with pytest.raises(CatalogRenderError, match="not supported yet"):
        render_component(flagship_df, render, 0, "light")


# ---------------------------------------------------------------------------
# Real depictio component builders
# ---------------------------------------------------------------------------


def test_figure_ui_builds_real_graph(flagship_df: pl.DataFrame) -> None:
    from dash import dcc

    render = Render(
        component="figure", visu_type="box", dict_kwargs={"x": "habitat", "y": "shannon"}
    )
    comp = render_component(flagship_df, render, 0, "light")
    assert isinstance(comp, dcc.Graph)
    assert len(comp.figure.data) >= 1
    # depictio applies the mantine template
    assert comp.figure.layout.template is not None


def test_figure_code_builds_real_graph(flagship_df: pl.DataFrame) -> None:
    from dash import dcc

    code = (
        'df_modified = df.to_pandas().melt(id_vars=["sample_id", "habitat"], '
        'value_vars=["shannon", "evenness", "faith_pd"], var_name="metric", value_name="value")\n'
        'fig = px.box(df_modified, x="habitat", y="value", color="habitat", facet_col="metric")'
    )
    comp = render_component(flagship_df, Render(component="figure", code=code), 0, "light")
    assert isinstance(comp, dcc.Graph)
    assert len(comp.figure.data) >= 1


def test_figure_code_violating_depictio_contract_raises(flagship_df: pl.DataFrame) -> None:
    # depictio code mode needs `df_modified`; an intermediate `m = …` breaks there.
    bad = 'm = df.to_pandas()\nfig = px.box(m, x="habitat", y="shannon")'
    with pytest.raises(CatalogRenderError):
        render_component(flagship_df, Render(component="figure", code=bad), 0, "light")


def test_card_builds_real_dmc_card(flagship_df: pl.DataFrame) -> None:
    render = Render(component="card", column="shannon", aggregation="average")
    comp = render_component(flagship_df, render, 0, "light")
    # build_card(build_frame=True) returns a dmc.Paper
    assert isinstance(comp, dmc.Paper)


def test_card_unknown_column_raises(flagship_df: pl.DataFrame) -> None:
    render = Render(component="card", column="not_a_col", aggregation="average")
    with pytest.raises(CatalogRenderError, match="absent"):
        render_component(flagship_df, render, 0, "light")


def test_table_builds_real_aggrid(flagship_df: pl.DataFrame) -> None:
    import dash_ag_grid as dag

    comp = render_component(flagship_df, Render(component="table"), 0, "light")
    assert isinstance(comp, dag.AgGrid)
    assert comp.rowModelType == "clientSide"
    assert len(comp.rowData) == flagship_df.height
    # depictio adds an "ID" column used by getRowId="params.data.ID"
    assert all("ID" in row for row in comp.rowData)


# ---------------------------------------------------------------------------
# Full flagship preview
# ---------------------------------------------------------------------------


def test_flagship_builds_all_real_components() -> None:
    import dash_ag_grid as dag
    from dash import dcc

    output = _get_output(FLAGSHIP)
    sections = build_preview_sections(output, theme="light")
    assert len(sections) == len(output.renders_as)

    bodies = [p.children[1] for p in sections]
    # None should have failed (no Alert placeholders)
    assert not any(isinstance(b, dmc.Alert) for b in bodies), [
        b.children for b in bodies if isinstance(b, dmc.Alert)
    ]
    assert sum(isinstance(b, dcc.Graph) for b in bodies) == 1
    assert sum(isinstance(b, dmc.Paper) for b in bodies) == 3  # 3 metric cards
    assert sum(isinstance(b, dag.AgGrid) for b in bodies) == 1
