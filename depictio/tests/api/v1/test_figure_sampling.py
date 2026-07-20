"""Tests for point-plot downsampling in ``create_figure_from_data``.

Covers the ``max_points`` cap + ``render_stats`` accounting that feed the
React viewer's "showing N of M points" badge and the "Load all" override.
"""

import polars as pl
import pytest

from depictio.api.v1.services.figure.figure_builder import (
    FIGURE_MAX_POINTS,
    create_figure_from_data,
)
from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates


@pytest.fixture(autouse=True)
def _templates():
    # px figure builds resolve a ``mantine_*`` template; register it once.
    ensure_mantine_templates()


def _df(n: int) -> pl.DataFrame:
    return pl.DataFrame({"x": list(range(n)), "y": list(range(n))})


def test_scatter_downsampled_above_cap():
    stats: dict = {}
    create_figure_from_data(
        _df(1000), "scatter", {"x": "x", "y": "y"}, max_points=100, render_stats=stats
    )
    assert stats == {"sampled": True, "displayed": 100}


def test_scatter_not_sampled_below_cap():
    stats: dict = {}
    create_figure_from_data(
        _df(50), "scatter", {"x": "x", "y": "y"}, max_points=100, render_stats=stats
    )
    assert stats == {"sampled": False, "displayed": 50}


def test_negative_max_points_disables_sampling():
    # -1 is how the render path signals an explicit full load: no cap at all.
    stats: dict = {}
    create_figure_from_data(
        _df(1000), "scatter", {"x": "x", "y": "y"}, max_points=-1, render_stats=stats
    )
    assert stats == {"sampled": False, "displayed": 1000}


def test_aggregated_plot_never_sampled():
    # Bar/box/line aggregate rows — every row matters, so the cap must not apply.
    stats: dict = {}
    create_figure_from_data(
        _df(1000), "bar", {"x": "x", "y": "y"}, max_points=100, render_stats=stats
    )
    assert stats == {"sampled": False, "displayed": 1000}


def test_none_max_points_falls_back_to_default():
    stats: dict = {}
    create_figure_from_data(
        _df(FIGURE_MAX_POINTS + 10),
        "scatter",
        {"x": "x", "y": "y"},
        max_points=None,
        render_stats=stats,
    )
    assert stats["sampled"] is True
    assert stats["displayed"] == FIGURE_MAX_POINTS
