"""Categorical filters must stay pushable without changing which rows match.

``add_filter`` used to express Select/MultiSelect/SegmentedControl filters as
``pl.col(c).cast(pl.Utf8).is_in([...])``. That is dtype-agnostic — which it had
to be, because the values arrive stringified from the React MultiSelect — but
wrapping the column in a cast makes the predicate opaque to Polars' parquet
reader, so row-group statistics can't skip and the whole filter column is
decoded on every filtered read.

The predicate is now typed against the column's dtype instead. These tests pin
both halves of that trade: the rows selected are unchanged (including the
stringified-values case the cast existed for), and the predicate no longer
wraps the column in a cast.
"""

import polars as pl
import pytest

from depictio.api.v1.deltatables_utils import (
    _categorical_predicate,
    add_filter,
    process_metadata_and_filter,
)

CATEGORICAL_TYPES = ["Select", "MultiSelect", "SegmentedControl"]


def _legacy_predicate(column_name: str, values: list):
    """The pre-change expression, kept verbatim as the parity reference."""
    return pl.col(column_name).cast(pl.Utf8, strict=False).is_in([str(v) for v in values])


class TestRowParityWithTheStringCastForm:
    """Same rows in, same rows out — the reason the cast was there."""

    def test_int_column_with_stringified_values(self):
        """The case the column-cast form existed for: int64 vs ["1", "3"]."""
        df = pl.DataFrame({"id": [1, 2, 3, 4], "v": ["a", "b", "c", "d"]})
        values = ["1", "3"]

        typed = df.filter(_categorical_predicate("id", values, df.schema["id"]))
        legacy = df.filter(_legacy_predicate("id", values))

        assert typed.to_dicts() == legacy.to_dicts()
        assert typed["id"].to_list() == [1, 3]

    def test_int_column_with_native_values(self):
        df = pl.DataFrame({"id": [1, 2, 3, 4]})
        values = [2, 4]

        typed = df.filter(_categorical_predicate("id", values, df.schema["id"]))
        assert typed.to_dicts() == df.filter(_legacy_predicate("id", values)).to_dicts()
        assert typed["id"].to_list() == [2, 4]

    def test_string_column(self):
        df = pl.DataFrame({"habitat": ["soil", "gut", "water", "soil"]})
        values = ["soil", "water"]

        typed = df.filter(_categorical_predicate("habitat", values, df.schema["habitat"]))
        assert typed.to_dicts() == df.filter(_legacy_predicate("habitat", values)).to_dicts()
        assert typed.height == 3

    def test_float_column_with_stringified_values(self):
        df = pl.DataFrame({"score": [1.0, 2.5, 3.0]})
        values = ["2.5", "3.0"]

        typed = df.filter(_categorical_predicate("score", values, df.schema["score"]))
        assert typed.to_dicts() == df.filter(_legacy_predicate("score", values)).to_dicts()
        assert typed["score"].to_list() == [2.5, 3.0]

    def test_int_column_with_integral_float_string_matches_nothing(self):
        """``"1.0"`` against an int column selects no row — as it did before.

        Worth pinning explicitly because it looks like it should match: the
        column-cast form compared ``"1"`` to ``"1.0"`` and found nothing, and
        the typed form fails to parse ``"1.0"`` as an Int64 and drops it. Same
        answer by a different route, so this is parity, not a regression.
        """
        df = pl.DataFrame({"id": [1, 2, 3]})
        values = ["1.0"]

        typed = df.filter(_categorical_predicate("id", values, df.schema["id"]))
        assert typed.to_dicts() == df.filter(_legacy_predicate("id", values)).to_dicts()
        assert typed.height == 0

    def test_date_column_with_iso_strings(self):
        df = pl.DataFrame({"d": ["2024-01-01", "2024-02-01", "2024-03-01"]}).with_columns(
            pl.col("d").str.to_date()
        )
        values = ["2024-01-01", "2024-03-01"]

        typed = df.filter(_categorical_predicate("d", values, df.schema["d"]))
        assert typed.to_dicts() == df.filter(_legacy_predicate("d", values)).to_dicts()
        assert typed.height == 2

    def test_unconvertible_value_matches_nothing(self):
        """An int column has no row equal to "abc" — as before."""
        df = pl.DataFrame({"id": [1, 2, 3]})
        values = ["abc"]

        typed = df.filter(_categorical_predicate("id", values, df.schema["id"]))
        assert typed.height == 0
        assert typed.height == df.filter(_legacy_predicate("id", values)).height

    def test_partially_convertible_keeps_the_convertible_values(self):
        df = pl.DataFrame({"id": [1, 2, 3]})
        values = ["2", "abc"]

        typed = df.filter(_categorical_predicate("id", values, df.schema["id"]))
        assert typed.to_dicts() == df.filter(_legacy_predicate("id", values)).to_dicts()
        assert typed["id"].to_list() == [2]

    def test_nulls_are_not_matched(self):
        df = pl.DataFrame({"id": [1, None, 3]}, schema={"id": pl.Int64})
        values = ["1"]

        typed = df.filter(_categorical_predicate("id", values, df.schema["id"]))
        assert typed.to_dicts() == df.filter(_legacy_predicate("id", values)).to_dicts()
        assert typed["id"].to_list() == [1]


class TestTemporalDtypesAreParsedNotCast:
    """Casting a string to a temporal dtype is a parse polars does NOT do.

    ``Series(["09:00:00"]).cast(pl.Time, strict=False)`` yields null instead of
    raising, so a naive typed predicate on a Time column matched nothing — real
    data loss, found in review. Temporal values now go through the real parsers.

    That also fixes a *pre-existing* bug: the column-cast form rendered a
    Datetime with microseconds while clients send seconds, so a Datetime
    categorical filter matched nothing no matter what the user picked. These
    tests assert the correct answer, which is why several of them deliberately
    do NOT match the legacy predicate.
    """

    def test_time_column_matches(self):
        df = pl.DataFrame({"t": pl.Series(["09:00:00", "10:00:00"]).str.to_time()})

        typed = df.filter(_categorical_predicate("t", ["09:00:00"], df.schema["t"]))
        assert typed.height == 1
        assert typed.height == df.filter(_legacy_predicate("t", ["09:00:00"])).height

    def test_datetime_matches_every_rendering_a_client_sends(self):
        """str(), isoformat() and Polars' own cast all name the same instant."""
        df = pl.DataFrame({"ts": pl.Series(["2024-01-01 12:30:45"]).str.to_datetime()})
        value = df["ts"][0]

        for rendering in (str(value), value.isoformat(), "2024-01-01 12:30:45.000000"):
            typed = df.filter(_categorical_predicate("ts", [rendering], df.schema["ts"]))
            assert typed.height == 1, rendering

    def test_datetime_now_matches_where_the_legacy_form_never_did(self):
        """The pre-existing bug this fixes, stated explicitly."""
        df = pl.DataFrame({"ts": pl.Series(["2024-01-01 12:30:45"]).str.to_datetime()})
        values = [str(df["ts"][0])]  # what a client actually sends

        assert df.filter(_legacy_predicate("ts", values)).height == 0  # was broken
        assert df.filter(_categorical_predicate("ts", values, df.schema["ts"])).height == 1

    def test_timezone_aware_datetime_round_trips(self):
        for tz in ("UTC", "Europe/Paris"):
            series = pl.Series(["2024-01-01 12:30:45"]).str.to_datetime().dt.replace_time_zone(tz)
            df = pl.DataFrame({"ts": series})
            values = [str(df["ts"][0])]

            typed = df.filter(_categorical_predicate("ts", values, df.schema["ts"]))
            assert typed.height == 1, tz

    def test_temporal_predicates_are_pushable(self):
        """The column stays bare, so row-group statistics remain usable."""
        cases = [
            (pl.Datetime("us"), "2024-01-01 00:00:00"),
            (pl.Datetime("us", "UTC"), "2024-01-01 00:00:00+00:00"),
            (pl.Time, "09:00:00"),
            (pl.Date, "2024-01-01"),
        ]
        for dtype, value in cases:
            expr = repr(_categorical_predicate("c", [value], dtype)).lower()
            assert 'col("c").cast' not in expr, dtype

    def test_duration_keeps_the_fallback(self):
        """No parser exists, and ``"1000"`` would cast to 1000µs — a wrong match.

        The fallback it keeps cannot render a Duration as text on polars 1.19
        and raises. That raise is pre-existing (every categorical filter used
        this form before); what matters is that a loud failure was not replaced
        by a silently wrong match.
        """
        assert "cast" in repr(_categorical_predicate("d", ["1000"], pl.Duration("us"))).lower()

        df = pl.DataFrame({"d": pl.Series([1000], dtype=pl.Int64).cast(pl.Duration("us"))})
        with pytest.raises(pl.exceptions.InvalidOperationError):
            df.filter(_legacy_predicate("d", ["1000"]))

    def test_unparseable_temporal_value_falls_back(self):
        assert "cast" in repr(_categorical_predicate("ts", ["nope"], pl.Datetime("us"))).lower()


class TestNothingConvertsFallsBack:
    """An all-null conversion means "this dtype doesn't parse", not "no match"."""

    def test_unconvertible_values_do_not_produce_a_match_nothing_predicate(self):
        expr = repr(_categorical_predicate("id", ["abc"], pl.Int64)).lower()
        assert "false" not in expr
        assert "cast" in expr

    def test_and_the_rows_still_agree_with_the_old_form(self):
        df = pl.DataFrame({"id": [1, 2, 3]})
        values = ["abc"]

        typed = df.filter(_categorical_predicate("id", values, df.schema["id"]))
        assert typed.to_dicts() == df.filter(_legacy_predicate("id", values)).to_dicts()
        assert typed.height == 0


class TestPredicateShape:
    """The point of the change: the column is no longer wrapped in a cast."""

    def test_typed_predicate_does_not_cast_the_column(self):
        expr = repr(_categorical_predicate("id", ["1", "2"], pl.Int64))
        assert "cast" not in expr.lower()

    def test_string_column_predicate_does_not_cast(self):
        expr = repr(_categorical_predicate("habitat", ["soil"], pl.Utf8))
        assert "cast" not in expr.lower()

    def test_unknown_dtype_falls_back_to_the_cast_form(self):
        """No schema available: correctness first, the old form is kept."""
        expr = repr(_categorical_predicate("id", ["1"], None))
        assert "cast" in expr.lower()

    def test_boolean_dtype_falls_back(self):
        """String→bool conversion is not obvious enough to risk; keep the old form."""
        expr = repr(_categorical_predicate("flag", ["true"], pl.Boolean))
        assert "cast" in expr.lower()


class TestWiring:
    """dtype must actually reach the predicate through the public helpers."""

    def test_add_filter_without_dtype_keeps_previous_behaviour(self):
        for component_type in CATEGORICAL_TYPES:
            filters: list = []
            add_filter(filters, component_type, "id", ["1"])
            assert len(filters) == 1
            assert "cast" in repr(filters[0]).lower()

    def test_add_filter_with_dtype_is_typed(self):
        for component_type in CATEGORICAL_TYPES:
            filters: list = []
            add_filter(filters, component_type, "id", ["1"], dtype=pl.Int64)
            assert len(filters) == 1
            assert "cast" not in repr(filters[0]).lower()

    def test_process_metadata_passes_the_dtype_through(self):
        metadata = [
            {
                "metadata": {
                    "interactive_component_type": "MultiSelect",
                    "column_name": "id",
                },
                "value": ["1", "2"],
            }
        ]

        untyped = process_metadata_and_filter(metadata)
        typed = process_metadata_and_filter(metadata, {"id": pl.Int64})

        assert "cast" in repr(untyped[0]).lower()
        assert "cast" not in repr(typed[0]).lower()

    def test_process_metadata_tolerates_a_column_absent_from_the_schema(self):
        """A schema that doesn't mention the column falls back, not crashes."""
        metadata = [
            {
                "interactive_component_type": "MultiSelect",
                "column_name": "missing",
                "value": ["1"],
            }
        ]

        filters = process_metadata_and_filter(metadata, {"other": pl.Int64})
        assert len(filters) == 1
        assert "cast" in repr(filters[0]).lower()

    def test_both_filter_paths_agree_on_the_same_frame(self):
        """Lazy scan and materialised frame must select identical rows."""
        df = pl.DataFrame({"id": [1, 2, 3, 4], "v": ["a", "b", "c", "d"]})
        metadata = [
            {
                "interactive_component_type": "MultiSelect",
                "column_name": "id",
                "value": ["2", "4"],
            }
        ]

        exprs = process_metadata_and_filter(metadata, dict(df.schema))
        eager = df.filter(exprs[0])
        lazy = df.lazy().filter(exprs[0]).collect()

        assert eager.to_dicts() == lazy.to_dicts()
        assert eager["id"].to_list() == [2, 4]
