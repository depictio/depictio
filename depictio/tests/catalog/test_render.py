"""Tests for the catalog fixture render core (``depictio.catalog.render``).

Covers the per-component renderers (figure UI + code mode, card aggregations,
table), the graceful per-render error handling, the ``render_index`` selector,
the no-fixture message, and the self-contained HTML output. An integration test
renders the bundled ``qiime2_alpha_diversity`` flagship (code-mode figure + 3
cards + table) end-to-end on its real fixture.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.catalog.render import (
    CatalogRenderError,
    _aggregate,
    _render_figure_ui,
    render_output,
    render_output_to_html,
)
from depictio.models.components.advanced_viz.catalog import (
    CatalogFind,
    CatalogOutput,
    Render,
    load_catalog_entries,
)

FLAGSHIP = "qiime2_alpha_diversity"


@pytest.fixture
def small_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "group": ["a", "a", "b", "b", "b"],
            "value": [1.0, 3.0, 2.0, 4.0, 6.0],
        }
    )


def _get_output(output_id: str) -> CatalogOutput:
    return next(o for e in load_catalog_entries() for o in e.outputs if o.id == output_id)


# ---------------------------------------------------------------------------
# Unit: per-component renderers
# ---------------------------------------------------------------------------


def test_figure_ui_mode_builds_plotly_figure(small_df: pl.DataFrame) -> None:
    render = Render(component="figure", visu_type="bar", dict_kwargs={"x": "group", "y": "value"})
    fig = _render_figure_ui(small_df, render)
    assert hasattr(fig, "to_dict")
    assert len(fig.data) >= 1


def test_figure_ui_mode_unknown_visu_type(small_df: pl.DataFrame) -> None:
    render = Render(
        component="figure", visu_type="scatter", dict_kwargs={"x": "group", "y": "value"}
    )
    object.__setattr__(render, "visu_type", "definitely_not_a_px_fn")
    with pytest.raises(CatalogRenderError):
        _render_figure_ui(small_df, render)


@pytest.mark.parametrize(
    "aggregation,expected",
    [
        ("count", 5),
        ("sum", 16.0),
        ("average", 3.2),
        ("min", 1.0),
        ("max", 6.0),
        ("range", 5.0),
        ("nunique", 5),
    ],
)
def test_card_aggregations(small_df: pl.DataFrame, aggregation: str, expected: float) -> None:
    assert _aggregate(small_df, "value", aggregation) == pytest.approx(expected)


def test_card_unknown_column(small_df: pl.DataFrame) -> None:
    with pytest.raises(CatalogRenderError):
        _aggregate(small_df, "missing", "sum")


def test_card_unknown_aggregation(small_df: pl.DataFrame) -> None:
    with pytest.raises(CatalogRenderError):
        _aggregate(small_df, "value", "not_an_agg")


# ---------------------------------------------------------------------------
# Unit: render_output error handling (no real fixture needed)
# ---------------------------------------------------------------------------


def test_no_fixture_reports_error_per_render() -> None:
    # A table render binds no columns, so the model accepts no fixture/recipe.
    output = CatalogOutput(
        id="t",
        find=CatalogFind(filename="x.csv"),
        renders_as=[Render(component="table")],
    )
    [rc] = render_output(output)
    assert rc.ok is False
    assert "fixture" in (rc.error or "")


def test_render_index_out_of_range() -> None:
    output = CatalogOutput(
        id="t",
        find=CatalogFind(filename="x.csv"),
        renders_as=[Render(component="table")],
    )
    with pytest.raises(CatalogRenderError):
        render_output(output, render_index=5)


def test_unsupported_component_is_placeholder_not_crash() -> None:
    # advanced_viz isn't rendered yet → ok=False with a clear message, no raise.
    output = CatalogOutput(
        id="av",
        find=CatalogFind(filename="x.csv"),
        fixture=_get_output(FLAGSHIP).fixture,
        renders_as=[Render(component="advanced_viz", kind="volcano")],
    )
    [rc] = render_output(output)
    assert rc.ok is False
    assert "not supported yet" in (rc.error or "")


# ---------------------------------------------------------------------------
# Integration: the real bundled flagship output
# ---------------------------------------------------------------------------


def test_flagship_renders_all_components() -> None:
    output = _get_output(FLAGSHIP)
    comps = render_output(output)
    assert len(comps) == len(output.renders_as)
    assert all(c.ok for c in comps), [c.error for c in comps if not c.ok]

    figures = [c for c in comps if c.figure is not None]
    cards = [c for c in comps if c.card is not None]
    tables = [c for c in comps if c.table is not None]
    assert figures and cards and tables
    # code-mode box plot: one trace per metric × habitat
    assert len(figures[0].figure.data) >= 1
    assert all(isinstance(c.card["value"], (int, float)) for c in cards)
    assert tables[0].table["total_rows"] > 0


def test_flagship_html_is_self_contained() -> None:
    output = _get_output(FLAGSHIP)
    html = render_output_to_html(output)
    assert "<!DOCTYPE html>" in html
    assert "cdn.plot.ly" in html  # plotly.js for the figure
    assert "ag-grid-community" in html  # AG Grid for the table
    assert output.id in html


def test_render_index_selects_single_component() -> None:
    output = _get_output(FLAGSHIP)
    comps = render_output(output, render_index=1)  # second render = a card
    assert len(comps) == 1
    assert comps[0].card is not None


def test_code_mode_cannot_reassign_df() -> None:
    output = CatalogOutput(
        id="bad",
        find=CatalogFind(filename="x.csv"),
        fixture=_get_output(FLAGSHIP).fixture,
        renders_as=[Render(component="figure", code="df = px.scatter(df)\nfig = df")],
    )
    [rc] = render_output(output)
    assert rc.ok is False
    assert "reassign" in (rc.error or "")
