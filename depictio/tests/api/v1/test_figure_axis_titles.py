"""The value axis of a histogram takes the author's label, not px's aggregate formula."""

import polars as pl
import pytest

from depictio.api.v1.services.figure.figure_builder import create_figure_from_data
from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates


@pytest.fixture(autouse=True)
def _templates():
    ensure_mantine_templates()


DF = pl.DataFrame({"step": ["a", "a", "b"], "samples": [1, 2, 3], "platform": ["x", "y", "x"]})


def test_summed_histogram_takes_the_label():
    fig = create_figure_from_data(
        DF,
        "histogram",
        {"x": "step", "y": "samples", "histfunc": "sum", "labels": {"samples": "Samples"}},
    )
    assert fig.layout.yaxis.title.text == "Samples"


def test_horizontal_histogram_titles_the_x_axis():
    fig = create_figure_from_data(
        DF,
        "histogram",
        {
            "y": "step",
            "x": "samples",
            "orientation": "h",
            "histfunc": "avg",
            "labels": {"samples": "Mean samples"},
        },
    )
    assert fig.layout.xaxis.title.text == "Mean samples"


def test_counting_histogram_takes_the_count_label():
    fig = create_figure_from_data(
        DF,
        "histogram",
        {"x": "step", "barnorm": "percent", "labels": {"count": "Share of the steps (%)"}},
    )
    assert fig.layout.yaxis.title.text == "Share of the steps (%)"


def test_without_a_label_px_keeps_its_title():
    fig = create_figure_from_data(DF, "histogram", {"x": "step", "y": "samples", "histfunc": "sum"})
    assert fig.layout.yaxis.title.text == "sum of samples"
