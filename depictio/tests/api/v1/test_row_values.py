"""``row_values``: the facts a scope banner reads for the value a filter holds."""

import json
from datetime import date, datetime
from decimal import Decimal

import polars as pl

from depictio.api.v1.endpoints.deltatables_endpoints.routes import row_values

TABLE = pl.LazyFrame(
    {
        "name": ["alpha", "beta", "alpha", "gamma"],
        "rank": [1, 2, 3, 4],
        "score": [0.5, float("nan"), 0.9, float("inf")],
        "label": ["first", "second", "third", "fourth"],
    }
)


def test_a_string_column_matches_its_value_and_the_first_row_wins():
    assert row_values(TABLE, "name", "alpha", ["rank", "label"]) == {"rank": 1, "label": "first"}


def test_a_numeric_column_is_matched_through_its_string_form():
    assert row_values(TABLE, "rank", "3", ["name", "label"]) == {"name": "alpha", "label": "third"}


def test_no_match_gives_none():
    assert row_values(TABLE, "name", "missing", ["rank"]) is None
    assert row_values(TABLE, "rank", "99", ["name"]) is None


def test_the_columns_come_back_deduplicated_in_the_order_asked():
    row = row_values(TABLE, "name", "beta", ["label", "rank", "label"])
    assert row is not None
    assert list(row) == ["label", "rank"]


def test_a_non_finite_float_becomes_none():
    assert row_values(TABLE, "name", "beta", ["score"]) == {"score": None}
    assert row_values(TABLE, "name", "gamma", ["score"]) == {"score": None}
    assert row_values(TABLE, "name", "alpha", ["score"]) == {"score": 0.5}


def test_dates_come_back_as_iso_strings_and_the_row_is_json_safe():
    typed = pl.LazyFrame(
        {
            "k": ["a"],
            "day": [date(2024, 3, 9)],
            "moment": [datetime(2024, 3, 9, 14, 30, 5)],
            "exact": [Decimal("1.25")],
        }
    )
    row = row_values(typed, "k", "a", ["day", "moment", "exact"])
    assert row == {"day": "2024-03-09", "moment": "2024-03-09T14:30:05", "exact": 1.25}
    json.dumps(row, allow_nan=False)


def test_a_categorical_column_is_compared_directly():
    categorical = pl.LazyFrame({"k": ["a", "b"], "n": [1, 2]}).with_columns(
        pl.col("k").cast(pl.Categorical)
    )
    assert row_values(categorical, "k", "b", ["n"]) == {"n": 2}
    assert row_values(categorical, "k", "z", ["n"]) is None
