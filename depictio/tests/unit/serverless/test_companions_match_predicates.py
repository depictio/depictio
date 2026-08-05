"""Drift guard: the codebook path must select exactly the server's rows.

The serverless runtime never casts filter values — it looks each picked option
string up in a build-time codebook and does integer set-membership over the
``__code__<col>`` companion (RFC §12 errata #1). These tests assert, over a
dtype × value-shape matrix, that this is row-for-row equivalent to the server
predicate (``_categorical_predicate``), and that the ``__ts__<col>`` epoch-µs
companion reproduces the server's datetime-range branch
(``datetime_range_predicate``).

Everything imported here is FastAPI-free (``depictio.models`` +
``depictio.serverless``) — the same import surface the producer uses.
"""

from datetime import date, datetime, time

import polars as pl
import pytest

from depictio.models.components.predicates import (
    LINK_NO_MATCH,
    _categorical_predicate,
    datetime_range_predicate,
)
from depictio.serverless.companions import CompanionResult, build_companions, serialize_option

# ---------------------------------------------------------------------------
# Fixture frame: one column per dtype under test, a null in each, and a row id
# so row-set comparisons are positional-order-proof.
# ---------------------------------------------------------------------------

NULL_RID = 2  # the row that is null in every value column


def make_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "rid": pl.Series([0, 1, 2, 3], dtype=pl.Int64),
            "int": pl.Series([1, 2, None, 3], dtype=pl.Int64),
            "float": pl.Series([1.5, 2.5, None, 3.0], dtype=pl.Float64),
            "date": pl.Series(
                [date(2024, 1, 1), date(2024, 2, 1), None, date(2024, 3, 1)], dtype=pl.Date
            ),
            "ts": pl.Series(
                [
                    datetime(2024, 1, 1, 12, 30, 45),
                    datetime(2024, 6, 1, 0, 0, 0),
                    None,
                    datetime(2025, 1, 1, 0, 0, 1),
                ],
                dtype=pl.Datetime("us"),
            ),
            "time": pl.Series([time(9, 0), time(10, 30), None, time(23, 59, 59)], dtype=pl.Time),
            "str": pl.Series(["soil", "gut", None, "water"], dtype=pl.String),
            "bool": pl.Series([True, False, None, True], dtype=pl.Boolean),
        }
    )


CATEGORICAL_COLS = ["int", "float", "date", "ts", "time", "str", "bool"]
DATETIME_COLS = ["ts", "date"]


@pytest.fixture(scope="module")
def df() -> pl.DataFrame:
    return make_df()


@pytest.fixture(scope="module")
def companions(df: pl.DataFrame) -> CompanionResult:
    return build_companions(df, categorical_cols=CATEGORICAL_COLS, datetime_cols=DATETIME_COLS)


# ---------------------------------------------------------------------------
# The two filter paths under comparison.
# ---------------------------------------------------------------------------


def server_rids(df: pl.DataFrame, col: str, values: list) -> set:
    """Rows the server selects: ``df.filter(_categorical_predicate(...))``."""
    return set(df.filter(_categorical_predicate(col, values, df.schema[col]))["rid"].to_list())


def codebook_rids(companions: CompanionResult, col: str, values: list) -> set:
    """Rows the serverless runtime selects: codebook lookup + code membership.

    A value missing from the codebook matches nothing — exactly the runtime's
    ``.get`` semantics; an empty code set matches no rows.
    """
    if col not in companions.codebooks:  # String column: direct membership
        expr = pl.col(col).is_in([str(v) for v in values])
        return set(companions.df.filter(expr)["rid"].to_list())
    codebook = companions.codebooks[col]
    codes = [c for v in values if (c := codebook.get(serialize_option(v))) is not None]
    predicate = pl.col(f"__code__{col}").is_in(codes) if codes else pl.lit(False)
    return set(companions.df.filter(predicate)["rid"].to_list())


# ---------------------------------------------------------------------------
# The dtype × value-shape matrix. Each entry: (column, filter values, expected
# rids). ``expected`` is asserted on BOTH paths — equality between the paths
# alone could not distinguish "both right" from "both empty".
# ---------------------------------------------------------------------------

_D = make_df()  # only to derive canonical wire renderings below

MATRIX: list[tuple[str, list, set]] = [
    # --- exact members, wire form (what MultiSelect sends back: str(v)) ---
    ("int", ["1", "3"], {0, 3}),
    ("float", ["2.5", "3.0"], {1, 3}),
    ("date", ["2024-01-01", "2024-03-01"], {0, 3}),
    ("ts", ["2024-01-01 12:30:45"], {0}),
    ("ts", [str(_D["ts"][3]), str(_D["ts"][1])], {1, 3}),
    ("time", ["09:00:00", "23:59:59"], {0, 3}),
    ("str", ["soil", "water"], {0, 3}),
    # Boolean: polars' Utf8 rendering is lowercase, so "true" is the matchable
    # wire form on the server's fallback predicate...
    ("bool", ["true"], {0, 3}),
    ("bool", ["false"], {1}),
    # ...while the options endpoint's ``str(True)`` rendering matches NOTHING
    # on the live server (case mismatch against the cast column). The codebook
    # must reproduce that, not "fix" it.
    ("bool", ["True", "False"], set()),
    # --- exact members, native form (scatter/table selections) ---
    ("int", [2], {1}),
    ("float", [1.5], {0}),
    ("date", [date(2024, 2, 1)], {1}),
    ("ts", [datetime(2024, 6, 1)], {1}),
    ("time", [time(10, 30)], {1}),
    # --- values absent from the column: nothing matches, on both paths ---
    ("int", ["99"], set()),
    ("int", ["abc"], set()),
    ("float", ["9.9"], set()),
    ("date", ["2030-01-01"], set()),
    ("ts", ["2030-01-01 00:00:00"], set()),
    ("time", ["01:23:45"], set()),
    ("str", ["lava"], set()),
    ("bool", ["maybe"], set()),
    # --- mixed present + absent: only the present member matches ---
    ("int", ["2", "99", "abc"], {1}),
    ("str", ["gut", "lava"], {1}),
    # --- empty selection: matches nothing on both paths ---
    ("int", [], set()),
    ("float", [], set()),
    ("date", [], set()),
    ("ts", [], set()),
    ("time", [], set()),
    ("str", [], set()),
    ("bool", [], set()),
]


@pytest.mark.parametrize(("col", "values", "expected"), MATRIX)
def test_codebook_path_matches_server_predicate(df, companions, col, values, expected):
    server = server_rids(df, col, values)
    codebook = codebook_rids(companions, col, values)

    assert server == codebook, (
        f"drift on {col!r} ({df.schema[col]}) with values={values!r}: "
        f"server selected {sorted(server)}, codebook selected {sorted(codebook)}"
    )
    assert server == expected, (
        f"unexpected server rows on {col!r} with values={values!r}: "
        f"got {sorted(server)}, expected {sorted(expected)}"
    )
    assert NULL_RID not in server  # nulls never match a categorical filter


def test_link_no_match_sentinel_is_all_false_on_both_paths(df, companions):
    """A cross-DC link that resolved to no values must yield NO rows.

    Server: ``add_filter`` maps the ``LINK_NO_MATCH`` sentinel to
    ``pl.lit(False)``. Runtime: the sentinel carries no values, so the code
    set is empty → all-false. Both are the opposite of "empty list = no
    filter", which would render every row.
    """
    assert LINK_NO_MATCH == "__link_no_match__"
    assert df.filter(pl.lit(False)).height == 0  # the server's branch
    for col in CATEGORICAL_COLS:
        assert codebook_rids(companions, col, []) == set()


class TestStringColumnsStayDirect:
    """String columns get no companion machinery at all."""

    def test_no_codebook_and_no_companion(self, companions):
        assert "str" not in companions.codebooks
        assert "__code__str" not in companions.df.columns
        assert "__code__str" not in companions.companions

    def test_server_predicate_is_direct_is_in(self, df):
        values = ["soil", "water"]
        direct = df.filter(pl.col("str").is_in(values))
        server = df.filter(_categorical_predicate("str", values, df.schema["str"]))
        assert direct["rid"].to_list() == server["rid"].to_list()


class TestCompanionShape:
    def test_code_companions_are_int32_and_null_preserving(self, df, companions):
        for col in CATEGORICAL_COLS:
            if col == "str":
                continue
            companion = f"__code__{col}"
            assert companions.companions[companion] == col
            series = companions.df[companion]
            assert series.dtype == pl.Int32
            assert series[NULL_RID] is None, f"{companion} must be null where {col} is null"

    def test_codes_are_dense_and_deterministic(self, companions):
        for col, codebook in companions.codebooks.items():
            codes = sorted(codebook.values())
            assert codes == list(range(len(codes))), f"{col}: codes not dense 0..n-1"
            assert list(codebook) == sorted(codebook, key=str), (
                f"{col}: keys not sorted by serialized form"
            )

    def test_codebook_keys_are_the_wire_option_strings(self, df, companions):
        """Keys must be byte-identical to what the options endpoint would send
        (``str(v)`` per ``get_unique_values``) for every confidently-converted
        dtype; bool is the documented polars-rendering exception."""
        for col in ["int", "float", "date", "ts", "time"]:
            expected = {str(v) for v in df[col].drop_nulls().to_list()}
            assert set(companions.codebooks[col]) == expected
        assert set(companions.codebooks["bool"]) == {"true", "false"}

    def test_idempotent(self, df, companions):
        again = build_companions(
            companions.df, categorical_cols=CATEGORICAL_COLS, datetime_cols=DATETIME_COLS
        )
        assert again.df.columns == companions.df.columns  # no duplicates
        assert again.df.equals(companions.df)
        assert again.codebooks == companions.codebooks
        assert again.companions == companions.companions


# ---------------------------------------------------------------------------
# Datetime: __ts__ epoch-µs range compares must equal the server's
# datetime-range branch.
# ---------------------------------------------------------------------------


def _epoch_us(value: str) -> int:
    """Epoch-µs of a filter boundary, converted exactly as the build converts
    the column (naive wall-clock → µs)."""
    from depictio.models.components.predicates import parse_datetime_boundary, strip_timezone

    boundary = strip_timezone(parse_datetime_boundary(value))
    return pl.Series([boundary]).cast(pl.Datetime("us")).cast(pl.Int64)[0]


class TestTsCompanionMatchesDatetimeBranch:
    RANGES = [
        # (col, start, end, expected rids)
        ("ts", "2024-01-01", "2024-12-31 23:59:59", {0, 1}),
        ("ts", "2024-01-01T12:30:45", "2024-01-01T12:30:45", {0}),  # inclusive bounds
        ("ts", "2026-01-01", "2026-12-31", set()),  # nothing in range
        ("ts", "2024-06-01T00:00:00.000000", "2025-06-01 00:00:02", {1, 3}),
        ("date", "2024-01-15", "2024-03-01", {1, 3}),
        ("date", "2024-01-01", "2024-01-01", {0}),
    ]

    @pytest.mark.parametrize(("col", "start", "end", "expected"), RANGES)
    def test_epoch_range_equals_server_branch(self, df, companions, col, start, end, expected):
        server = set(df.filter(datetime_range_predicate(col, start, end))["rid"].to_list())

        lo, hi = _epoch_us(start), _epoch_us(end)
        ts_col = pl.col(f"__ts__{col}")
        runtime = set(companions.df.filter((ts_col >= lo) & (ts_col <= hi))["rid"].to_list())

        assert server == runtime, (
            f"drift on {col!r} range [{start!r}, {end!r}]: "
            f"server {sorted(server)}, __ts__ compare {sorted(runtime)}"
        )
        assert server == expected
        assert NULL_RID not in server  # nulls never fall inside a range

    def test_ts_companions_are_int64_and_null_preserving(self, companions):
        for col in DATETIME_COLS:
            companion = f"__ts__{col}"
            assert companions.companions[companion] == col
            series = companions.df[companion]
            assert series.dtype == pl.Int64
            assert series[NULL_RID] is None

    def test_ts_values_are_epoch_microseconds(self, df, companions):
        expected = datetime(2024, 1, 1, 12, 30, 45)
        epoch = int((expected - datetime(1970, 1, 1)).total_seconds() * 1_000_000)
        assert companions.df["__ts__ts"][0] == epoch
