"""``rank_values``: the order an always_selected Select with ``default_by`` starts on."""

import polars as pl

from depictio.api.v1.endpoints.deltatables_endpoints.routes import rank_values

FAMILIES = pl.LazyFrame(
    {
        "family": ["a", "b", "c", "c", "d", None],
        "size": [10, 300, 40, 55, None, 999],
    }
)


def test_largest_first_by_default_and_a_value_ranks_on_its_largest_row():
    assert rank_values(FAMILIES, "family", "size") == ["b", "c", "a", "d"]


def test_ascending_puts_the_smallest_first_and_a_null_measure_stays_last():
    assert rank_values(FAMILIES, "family", "size", descending=False) == ["a", "c", "b", "d"]


def test_ties_fall_back_on_the_value_and_the_limit_cuts_the_tail():
    tied = pl.LazyFrame({"k": ["y", "x", "z"], "n": [5, 5, 1]})
    assert rank_values(tied, "k", "n") == ["x", "y", "z"]
    assert rank_values(tied, "k", "n", limit=2) == ["x", "y"]
