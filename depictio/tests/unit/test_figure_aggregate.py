"""Scan-level figure aggregation: exactness, bail-outs, and the sampling fixes.

The aggregation path replaces "collect every row, hand it to Plotly Express"
with "reduce it in Polars". That is only acceptable if the numbers are the same
ones px would have produced, so the exactness assertions here compare against
numpy rather than against a golden file — a golden file would happily encode a
bug. The bail-out assertions matter just as much: anything the planner can't
reproduce faithfully must return ``None`` so the caller falls back to px.
"""

import numpy as np
import polars as pl
import pytest

from depictio.api.v1.services.figure.aggregate import (
    build_aggregated_figure,
    plan_aggregation,
)
from depictio.api.v1.services.figure.figure_builder import (
    _ORDERED_PLOT_TYPES,
    _SAMPLABLE_PLOT_TYPES,
    _decimate_ordered,
)


@pytest.fixture
def frame() -> pl.DataFrame:
    rng = np.random.default_rng(0)
    n = 20_000
    return pl.DataFrame(
        {
            "g": rng.choice(["a", "b", "c"], n),
            "sex": rng.choice(["M", "F"], n),
            "v": rng.normal(10, 3, n),
            "w": rng.normal(5, 1, n),
        }
    )


# --------------------------------------------------------------------------- #
# Exactness
# --------------------------------------------------------------------------- #


def test_box_quartiles_match_numpy(frame):
    """A precomputed box must carry the same five numbers px would have drawn."""
    plan = plan_aggregation("box", {"x": "g", "y": "v", "color": "sex"})
    fig = build_aggregated_figure(frame.lazy(), plan, "light", {})
    assert fig is not None

    trace = next(t for t in fig.data if t.name == "M")
    i = list(trace.x).index("a")
    subset = frame.filter((pl.col("g") == "a") & (pl.col("sex") == "M"))["v"].to_numpy()

    assert trace.q1[i] == pytest.approx(np.percentile(subset, 25))
    assert trace.median[i] == pytest.approx(np.percentile(subset, 50))
    assert trace.q3[i] == pytest.approx(np.percentile(subset, 75))
    # Fences are Tukey, clipped to the observed extremes.
    assert trace.lowerfence[i] >= subset.min()
    assert trace.upperfence[i] <= subset.max()


def test_box_without_grouping_is_a_single_box(frame):
    plan = plan_aggregation("box", {"y": "v"})
    fig = build_aggregated_figure(frame.lazy(), plan, "light", {})
    assert len(fig.data) == 1
    assert fig.data[0].q1[0] == pytest.approx(np.percentile(frame["v"].to_numpy(), 25))


def test_histogram_counts_match_numpy(frame):
    plan = plan_aggregation("histogram", {"x": "v"})
    fig = build_aggregated_figure(frame.lazy(), plan, "light", {})
    counts = np.array(fig.data[0].y)
    expected, _ = np.histogram(frame["v"].to_numpy(), bins=40)
    np.testing.assert_array_equal(counts, expected)


def test_histogram_keeps_empty_bins(frame):
    """An empty bin must stay in the trace as a zero, not vanish.

    A group-by only returns bins that got rows. Dropping the empties would make
    the neighbouring bars adjacent, reading as a continuous distribution across
    a gap that actually has no data.
    """
    # A deliberately gapped distribution: nothing between 100 and 200.
    gapped = pl.DataFrame({"v": [1.0] * 100 + [200.0] * 100})
    plan = plan_aggregation("histogram", {"x": "v"})
    fig = build_aggregated_figure(gapped.lazy(), plan, "light", {})
    assert len(fig.data[0].y) == 40
    assert 0 in list(fig.data[0].y)
    assert sum(fig.data[0].y) == 200


def test_density_grid_conserves_every_row(frame):
    plan = plan_aggregation("density_heatmap", {"x": "v", "y": "w"})
    fig = build_aggregated_figure(frame.lazy(), plan, "light", {})
    assert np.array(fig.data[0].z).sum() == frame.height


def test_bar_heights_are_group_sums_not_a_sample(frame):
    """Regression: px.bar stacks one segment per row, so sampling scaled bars down.

    ``bar`` was in ``_SAMPLABLE_PLOT_TYPES``, which meant a bar chart over a large
    frame rendered every bar at roughly ``cap / n_rows`` of its true height —
    wrong output rather than an approximation.
    """
    plan = plan_aggregation("bar", {"x": "g", "y": "v"})
    fig = build_aggregated_figure(frame.lazy(), plan, "light", {})
    got = dict(zip(fig.data[0].x, fig.data[0].y))
    want = {row[0]: row[1] for row in frame.group_by("g").agg(pl.col("v").sum()).iter_rows()}
    for key, value in want.items():
        assert got[key] == pytest.approx(value)


def test_bar_is_no_longer_randomly_sampled():
    assert "bar" not in _SAMPLABLE_PLOT_TYPES


# --------------------------------------------------------------------------- #
# Approximate paths declare themselves
# --------------------------------------------------------------------------- #


def test_violin_subsamples_and_flags_it():
    rng = np.random.default_rng(0)
    n = 300_000
    big = pl.DataFrame({"g": rng.choice(["a", "b"], n), "v": rng.normal(0, 1, n)})
    stats: dict = {}
    fig = build_aggregated_figure(
        big.lazy(), plan_aggregation("violin", {"y": "v", "color": "g"}), "light", stats
    )
    assert fig is not None
    assert stats["sampled"] is True
    assert stats["total_rows"] == n
    assert stats["rows_displayed"] < n
    # Both groups must survive the subsample — a per-value hash would have taken
    # whole categories in or out.
    assert len(fig.data) == 2


def test_exact_paths_do_not_claim_to_be_sampled(frame):
    for visu, kwargs in [
        ("box", {"x": "g", "y": "v"}),
        ("histogram", {"x": "v"}),
        ("bar", {"x": "g", "y": "v"}),
        ("density_heatmap", {"x": "v", "y": "w"}),
    ]:
        stats: dict = {}
        build_aggregated_figure(frame.lazy(), plan_aggregation(visu, kwargs), "light", stats)
        assert stats["sampled"] is False, visu
        assert stats["aggregated"] is True, visu


# --------------------------------------------------------------------------- #
# Bail-outs — the planner must refuse rather than approximate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "visu,kwargs",
    [
        ("box", {"x": "g", "y": "v", "marginal": "rug"}),
        ("box", {"x": "g", "y": "v", "hover_data": ["w"]}),
        ("box", {"x": "g", "y": "v", "facet_col": "sex"}),
        ("box", {"y": "v", "size": "w"}),
        ("box", {"x": "g", "y": "v", "trendline": "ols"}),
        ("box", {"x": "g", "y": "v", "animation_frame": "sex"}),
        ("histogram", {"x": "v", "histfunc": "avg"}),
        ("histogram", {"x": "v", "cumulative": True}),
        ("bar", {"x": "g", "y": "v", "some_future_kwarg": "z"}),
        ("bar", {"x": ["g", "sex"], "y": "v"}),
        ("scatter", {"x": "v", "y": "w"}),
        ("line", {"x": "v", "y": "w"}),
        ("box", "not-a-dict"),
        ("violin", {"x": "g"}),
        ("density_heatmap", {"x": "v"}),
    ],
)
def test_planner_refuses_what_it_cannot_reproduce(visu, kwargs):
    assert plan_aggregation(visu, kwargs) is None


def test_build_falls_back_when_a_column_is_missing(frame):
    """A plan naming an absent column must return None, not raise."""
    plan = plan_aggregation("box", {"x": "g", "y": "does_not_exist"})
    assert build_aggregated_figure(frame.lazy(), plan, "light", {}) is None


def test_build_falls_back_on_cardinality_blowup():
    """Grouping by an ID column would defeat the point — bail to the px path."""
    n = 20_000
    wide = pl.DataFrame({"id": [str(i) for i in range(n)], "v": np.arange(n, dtype=float)})
    plan = plan_aggregation("box", {"x": "id", "y": "v"})
    assert build_aggregated_figure(wide.lazy(), plan, "light", {}) is None


# --------------------------------------------------------------------------- #
# Ordered decimation for series
# --------------------------------------------------------------------------- #


def test_decimation_preserves_extremes_where_sampling_loses_them():
    rng = np.random.default_rng(0)
    n = 200_000
    series = pl.DataFrame(
        {"t": range(n), "y": np.sin(np.linspace(0, 60, n)) + rng.normal(0, 0.01, n)}
    )
    decimated = _decimate_ordered(series, "t", 5_000)

    assert decimated.height <= 5_000
    # The whole point: a spike must survive thinning.
    assert decimated["y"].min() == pytest.approx(series["y"].min())
    assert decimated["y"].max() == pytest.approx(series["y"].max())
    # Order is the mark's meaning for a line — it must not be shuffled.
    assert decimated["t"].is_sorted()
    assert decimated.columns == series.columns


def test_decimation_falls_back_to_stride_without_an_x_column():
    frame = pl.DataFrame({"y": np.arange(100_000, dtype=float)})
    assert _decimate_ordered(frame, None, 1_000).height <= 1_100


def test_decimation_is_a_noop_below_the_cap():
    frame = pl.DataFrame({"t": range(10), "y": np.arange(10, dtype=float)})
    assert _decimate_ordered(frame, "t", 5_000).height == 10


def test_series_types_use_ordered_decimation_not_random_sampling():
    assert _ORDERED_PLOT_TYPES <= _SAMPLABLE_PLOT_TYPES
    assert "line" in _ORDERED_PLOT_TYPES and "area" in _ORDERED_PLOT_TYPES
