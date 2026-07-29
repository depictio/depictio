"""Card metrics: the scan-level pushdown must equal the in-memory reduction.

``bulk_compute_cards`` has two ways to produce a card's value — a Polars
expression evaluated against the Delta scan (fast, nothing materialised) and
``_agg_value`` over a collected Series (the fallback). Which one runs depends on
whether a *sibling* card on the same data collection needed a full frame, so any
divergence between them would make a card's displayed value depend on what else
happens to be on the dashboard. These tests pin them together.
"""

import numpy as np
import polars as pl
import pytest

from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _agg_expr,
    _agg_value,
    _coerce_agg_result,
)

# Every aggregation name the card component offers that has an expression form.
PUSHDOWN_AGGS = [
    "count",
    "average",
    "mean",
    "sum",
    "median",
    "min",
    "max",
    "std",
    "std_dev",
    "variance",
    "var",
    "nunique",
    "unique",
    "range",
    "q1",
    "q3",
]


@pytest.fixture
def frame() -> pl.DataFrame:
    rng = np.random.default_rng(0)
    n = 50_000
    return pl.DataFrame(
        {
            "v": rng.normal(10, 3, n),
            "g": rng.choice(list("abcdefgh"), n),
            "sparse": [None if i % 3 else float(i) for i in range(n)],
        }
    )


def _pushdown(frame: pl.DataFrame, column: str, agg: str):
    expr = _agg_expr(column, agg)
    assert expr is not None, f"{agg} should have an expression form"
    raw = frame.lazy().select(expr.alias("x")).collect().row(0)[0]
    return _coerce_agg_result(raw, agg)


@pytest.mark.parametrize("agg", PUSHDOWN_AGGS)
def test_pushdown_matches_in_memory_reduction(frame, agg):
    want = _agg_value(frame["v"], agg)
    got = _pushdown(frame, "v", agg)
    if isinstance(want, float):
        assert got == pytest.approx(want)
    else:
        assert got == want


@pytest.mark.parametrize("agg", PUSHDOWN_AGGS)
def test_pushdown_matches_with_nulls_present(frame, agg):
    """Null handling is where the two paths would most plausibly drift."""
    want = _agg_value(frame["sparse"], agg)
    got = _pushdown(frame, "sparse", agg)
    if isinstance(want, float):
        assert got == pytest.approx(want)
    else:
        assert got == want


@pytest.mark.parametrize("agg", ["min", "max"])
def test_pushdown_matches_on_a_string_column(frame, agg):
    """min/max on a non-numeric column must return a string from both paths."""
    want = _agg_value(frame["g"], agg)
    got = _pushdown(frame, "g", agg)
    assert got == want
    assert isinstance(got, str)


@pytest.mark.parametrize("agg", ["box_plot_stats", "mode", "something_unknown", ""])
def test_aggregations_without_an_expression_form_fall_back(agg):
    """These must return None so the caller loads the frame and uses _agg_value.

    ``box_plot_stats`` needs its outlier rows; ``mode`` has no guaranteed order
    among ties, so letting it take either path could change the answer between
    renders.
    """
    assert _agg_expr("v", agg) is None


def test_count_ignores_nulls_in_both_paths(frame):
    """``count`` means "non-null values", not "rows" — a classic drift point."""
    non_null = frame["sparse"].drop_nulls().len()
    assert _agg_value(frame["sparse"], "count") == non_null
    assert _pushdown(frame, "sparse", "count") == non_null
    assert non_null < frame.height  # the fixture really does have nulls


def test_result_types_match_the_renderer_contract(frame):
    """React formats on type: counts must be int, numeric reductions float."""
    assert isinstance(_pushdown(frame, "v", "count"), int)
    assert isinstance(_pushdown(frame, "v", "nunique"), int)
    assert isinstance(_pushdown(frame, "v", "mean"), float)
    assert isinstance(_pushdown(frame, "v", "sum"), float)


@pytest.mark.parametrize("agg", PUSHDOWN_AGGS)
def test_empty_frame_agrees_between_paths(agg):
    """A filter can narrow a card's input to nothing — both paths must agree.

    Polars is deliberately asymmetric here (``sum`` of nothing is ``0.0``, but
    ``mean`` of nothing is null), so this asserts equivalence rather than a
    guessed value: what matters is that a card shows the same thing regardless of
    which path served it.
    """
    empty = pl.DataFrame({"v": []}, schema={"v": pl.Float64})
    assert _pushdown(empty, "v", agg) == _agg_value(empty["v"], agg)
