"""Code-mode figures keep their own template, and only their own.

`process_code_mode_figure` applies the theme's mantine template unless the
user code picks one. The check used to be the substring ``template=``, which
``hovertemplate=`` and ``texttemplate=`` also contain, so a figure that only
formatted its hover text was drawn in Plotly's default look.
"""

import polars as pl
import pytest

from depictio.api.v1.services.figure.figure_builder import (
    code_sets_template,
    process_code_mode_figure,
)


@pytest.mark.parametrize(
    "code",
    [
        "fig = px.scatter(df, x='a', y='b', template='plotly_white')",
        "fig = px.scatter(df, x='a', y='b', template = 'simple_white')",
        "fig = px.scatter(df, x='a', y='b')\nfig.update_layout(template='ggplot2')",
        "fig = px.scatter(df, x='a', y='b')\nfig.layout.template = 'seaborn'",
        "fig = px.scatter(df, x='a', y='b')\nfig.update_layout({'template': 'none'})",
        "pio.templates.default = 'plotly_dark'\nfig = px.scatter(df, x='a', y='b')",
    ],
)
def test_detects_a_template_the_code_picks(code):
    assert code_sets_template(code)


@pytest.mark.parametrize(
    "code",
    [
        "fig = px.scatter(df, x='a', y='b')",
        "fig = px.scatter(df, x='a', y='b')\n"
        "fig.update_traces(hovertemplate='%{x}<extra></extra>')",
        "fig = px.bar(df, x='a', y='b', text='b')\nfig.update_traces(texttemplate='%{y:.0%}')",
        "fig = px.scatter(df, x='a', y='b')\n"
        "fig.update_traces({'hovertemplate': '<b>%{hovertext}</b>'})",
        # A comparison and a comment are not a choice of template.
        "template_name = 'x'\nok = template_name == 'x'\nfig = px.scatter(df, x='a', y='b')",
        "# template='plotly_white' would be nice\nfig = px.scatter(df, x='a', y='b')",
        "",
    ],
)
def test_ignores_code_that_picks_no_template(code):
    assert not code_sets_template(code)


def test_unparsable_code_falls_back_to_a_word_bounded_match():
    assert code_sets_template("fig = px.scatter(df, template='x'")
    assert not code_sets_template("fig = px.scatter(df, hovertemplate='x'")


DF = pl.DataFrame({"a": [1, 2, 3], "b": [3, 1, 2]})


@pytest.fixture(autouse=True)
def _mantine_templates():
    """Register the vanilla mantine templates (no branding, no settings)."""
    from depictio.cli.cli.utils.mantine_templates import ensure_mantine_templates

    ensure_mantine_templates()


def _template_font(fig) -> str | None:
    """The font family of the figure's template.

    A named template is expanded on assignment, so the name is gone; the font
    family is a property the mantine template sets and Plotly's default does not.
    """
    return fig.layout.template.layout.font.family


def test_hovertemplate_code_still_gets_the_theme_template():
    code = (
        "fig = px.scatter(df.to_pandas(), x='a', y='b')\n"
        "fig.update_traces(hovertemplate='%{x}<extra></extra>')"
    )
    ok, fig, _ = process_code_mode_figure(code, DF, "light", "test")
    assert ok
    themed_ok, themed, _ = process_code_mode_figure(
        "fig = px.scatter(df.to_pandas(), x='a', y='b')", DF, "light", "test"
    )
    assert themed_ok
    assert _template_font(fig) == _template_font(themed)
    assert _template_font(fig)  # the mantine template sets a font family


def test_code_with_its_own_template_keeps_it():
    code = "fig = px.scatter(df.to_pandas(), x='a', y='b', template='plotly_dark')"
    ok, fig, _ = process_code_mode_figure(code, DF, "light", "test")
    assert ok
    # plotly_dark paints a dark plot background; the mantine template does not.
    assert fig.layout.template.layout.plot_bgcolor == "rgb(17,17,17)"
