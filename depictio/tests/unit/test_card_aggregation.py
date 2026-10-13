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
    _filter_expr_columns,
)
from depictio.models.components.filter_expr import apply_filter_expr, build_filter_expr

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
    # Answered by the shared precompute expressions. Before these had an
    # expression form a card showed a number while unfiltered (served from the
    # precomputed specs) and blanked to "—" the moment a filter forced it onto
    # one of the two paths below.
    "skewness",
    "kurtosis",
    "percentile",
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


class TestCardFilterExpr:
    """A card's own ``filter_expr`` narrows the rows before anything is reduced.

    ``bulk_compute_cards`` used to ignore the field entirely, so a card declaring
    a conditional aggregation in YAML rendered the *unfiltered* number — silently
    wrong rather than visibly broken. The endpoint now narrows the lazy scan
    (pushdown path) or the collected frame (fallback path); these pin the two
    together and check the value actually moves.
    """

    EXPR = "col('v') >= 10"

    @pytest.mark.parametrize("agg", PUSHDOWN_AGGS)
    def test_both_paths_agree_under_a_filter_expr(self, frame, agg):
        # Pushdown path: narrow the lazy frame, same as _try_pushdown does.
        lazy = frame.lazy().filter(build_filter_expr(self.EXPR))
        pushed = _coerce_agg_result(
            lazy.select(_agg_expr("v", agg).alias("x")).collect().row(0)[0], agg
        )
        # Fallback path: narrow the materialised frame, same as the load branch.
        loaded = _agg_value(apply_filter_expr(frame, self.EXPR)["v"], agg)
        if isinstance(loaded, float):
            assert pushed == pytest.approx(loaded)
        else:
            assert pushed == loaded

    def test_the_filter_actually_changes_the_answer(self, frame):
        """Guard against a filter that silently matches everything."""
        filtered = apply_filter_expr(frame, self.EXPR)
        assert 0 < filtered.height < frame.height
        assert _agg_value(filtered["v"], "count") < _agg_value(frame["v"], "count")

    def test_expression_columns_are_discovered_for_projection(self):
        """The projected load must carry columns only the expression mentions."""
        assert _filter_expr_columns("col('v') >= 10") == {"v"}
        assert _filter_expr_columns("(col('a') >= 5) & (col('b') == 'x')") == {"a", "b"}
        assert _filter_expr_columns('col("quoted") > 1') == {"quoted"}
        assert _filter_expr_columns(None) == set()
        assert _filter_expr_columns("") == set()

    def test_a_filter_matching_nothing_still_agrees(self, frame):
        """An over-narrow expression must blank both paths the same way."""
        expr = "col('v') > 1000000"
        lazy = frame.lazy().filter(build_filter_expr(expr))
        pushed = _coerce_agg_result(
            lazy.select(_agg_expr("v", "average").alias("x")).collect().row(0)[0], "average"
        )
        loaded = _agg_value(apply_filter_expr(frame, expr)["v"], "average")
        assert pushed == loaded is None


class TestTopCategory:
    """``top`` / ``top_share``: a text tile's dominant category and its share.

    One expression serves the scan pushdown and the collected-frame path, so the
    tests evaluate it both lazily and eagerly.
    """

    FRAME = pl.DataFrame(
        {
            "phylum": ["b", "a", None, "b", "a", "c", None],
            "reads": [1.0, 2.0, 10.0, 1.0, 0.0, 1.5, None],
        }
    )

    def _both(self, frame: pl.DataFrame, agg: str, weight: str | None):
        expr = _agg_expr("phylum", agg, weight)
        assert expr is not None
        lazy = frame.lazy().select(expr.alias("x")).collect().item()
        eager = frame.select(expr.alias("x")).item()
        assert lazy == eager
        return _coerce_agg_result(lazy, agg)

    def test_weighted_top_breaks_ties_alphabetically(self):
        # a = 2.0, b = 2.0, c = 1.5: a tie, "a" first.
        assert self._both(self.FRAME, "top", "reads") == "a"

    def test_weighted_share_is_over_every_rows_weight(self):
        # 2.0 out of 15.5: the 10.0 read on a null phylum stays in the total.
        assert self._both(self.FRAME, "top_share", "reads") == pytest.approx(2.0 / 15.5)

    def test_unweighted_counts_rows_and_never_picks_null(self):
        frame = self.FRAME.with_columns(
            pl.Series("phylum", [None, "a", None, "b", "a", None, None])
        )
        assert self._both(frame, "top", None) == "a"
        assert self._both(frame, "top_share", None) == pytest.approx(2 / 7)

    def test_largest_weight_wins_over_more_rows(self):
        frame = pl.DataFrame({"phylum": ["a", "a", "a", "b"], "reads": [1.0, 1.0, 1.0, 9.0]})
        assert self._both(frame, "top", "reads") == "b"
        assert self._both(frame, "top", None) == "a"

    def test_no_category_or_no_weight_gives_null(self):
        empty = pl.DataFrame(
            {"phylum": [], "reads": []}, schema={"phylum": pl.Utf8, "reads": pl.Float64}
        )
        assert self._both(empty, "top", "reads") is None
        assert self._both(empty, "top_share", None) is None
        all_null = pl.DataFrame(
            {"phylum": [None, None], "reads": [1.0, 2.0]},
            schema={"phylum": pl.Utf8, "reads": pl.Float64},
        )
        assert self._both(all_null, "top", "reads") is None
        assert self._both(all_null, "top_share", "reads") is None
        zero = pl.DataFrame({"phylum": ["a"], "reads": [0.0]})
        assert self._both(zero, "top_share", "reads") is None

    def test_a_numeric_category_comes_back_as_text(self):
        frame = pl.DataFrame({"phylum": [10, 9, 10]})
        assert self._both(frame, "top", None) == "10"

    def test_runs_beside_card_aggregations_in_one_query(self):
        row = (
            self.FRAME.lazy()
            .select(
                _agg_expr("phylum", "top", "reads").alias("c0"),
                _agg_expr("reads", "sum").alias("c1"),
                _agg_expr("phylum", "nunique").alias("c2"),
            )
            .collect()
            .row(0)
        )
        assert row == ("a", 15.5, 4)
