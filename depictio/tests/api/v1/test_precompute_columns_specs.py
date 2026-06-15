"""Invariants on ``precompute_columns_specs`` — the per-column spec
builder run during Delta-table upsert.

Two histories are pinned here.

1. The function used to call ``.to_pandas()`` on the whole aggregated frame.
   On a ~14M-row data collection that allocated gigabytes (every string cell
   became a Python ``str``) and got the API worker OOM-killed mid-upsert. It is
   now pure lazy polars. ``test_never_materialises_to_pandas`` makes the
   materialisation impossible to reintroduce silently.

2. Before that, the pandas implementation did ``result[0]`` on the ``.mode()``
   Series — *label*-based indexing, which raised ``KeyError(0)`` whenever the
   index didn't contain 0 (viralrecon's ``pangolin_lineages``, whose sparse
   string columns produce such modes). The upsert aborted and every dashboard
   tile bound to that DC was stuck on 404. The mode tests below keep the
   "smallest tied mode" behaviour those cases depend on.

The output shape — one dict per column with ``name`` / ``description`` /
``type`` / ``specs`` — is the contract consumed by the ``DeltaTableColumn``
validator, the ``agg_functions`` lookup and the frontend type maps, so
``test_matches_pandas_reference`` compares the whole thing against the previous
pandas implementation, kept verbatim in this module.
"""

from __future__ import annotations

import collections
import math
from datetime import date, datetime, time

import numpy as np
import polars as pl
import pytest
from bson import encode as bson_encode

from depictio.api.v1.endpoints.deltatables_endpoints.utils import precompute_columns_specs
from depictio.api.v1.utils import agg_functions as REAL_AGG_FUNCTIONS
from depictio.api.v1.utils import numpy_to_python

_AGG_FUNCTIONS = {
    "object": {
        "card_methods": {
            "mode": {"pandas": "mode"},
            "count": {"pandas": "count"},
            "nunique": {"pandas": "nunique"},
        }
    },
    "str": {
        # polars→pandas conversion can produce ``str``/``string`` dtypes; alias.
        "card_methods": {
            "mode": {"pandas": "mode"},
            "count": {"pandas": "count"},
            "nunique": {"pandas": "nunique"},
        }
    },
}


def _dc_data() -> dict:
    return {"config": {"dc_specific_properties": {}}}


# --------------------------------------------------------------------------
# Reference implementation: the pandas body this function had before the
# lazy-polars rewrite. Kept here so parity is asserted, not assumed.
# --------------------------------------------------------------------------
def _pandas_reference(aggregated_df: pl.DataFrame, agg_functions: dict, dc_data: dict):
    aggregated_df = aggregated_df.to_pandas()  # type: ignore[assignment]

    results = list()
    dc_config = dc_data["config"]

    for column in aggregated_df.columns:
        tmp_dict = collections.defaultdict(dict)
        tmp_dict["name"] = column
        column_description = None

        if "columns_description" in dc_config["dc_specific_properties"]:
            if column in list(dc_config["dc_specific_properties"]["columns_description"].keys()):
                column_description = dc_config["dc_specific_properties"]["columns_description"][
                    column
                ]

        tmp_dict["description"] = column_description
        col_type = str(aggregated_df[column].dtype).lower()

        if col_type.startswith("datetime64"):
            normalized_type = "datetime"
        elif col_type.startswith("timedelta64"):
            normalized_type = "time"
        elif col_type in ["int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"]:
            normalized_type = "int64"
        elif col_type in ["float16", "float32", "float64"]:
            normalized_type = "float64"
        elif col_type in ["bool", "boolean"]:
            normalized_type = "bool"
        elif col_type == "str" or col_type.startswith("string") or col_type == "large_string":
            normalized_type = "object"
        else:
            normalized_type = col_type.lower()

        tmp_dict["type"] = normalized_type

        lookup_key = normalized_type if normalized_type in agg_functions else col_type
        if lookup_key in agg_functions:
            methods = agg_functions[lookup_key]["card_methods"]

            for method_name, method_info in methods.items():
                pandas_method = method_info["pandas"]
                if callable(pandas_method):
                    result = pandas_method(aggregated_df[column])
                elif isinstance(pandas_method, str):
                    result = getattr(aggregated_df[column], pandas_method)()
                else:
                    continue

                if hasattr(result, "iloc"):  # pd.Series
                    if len(result) == 0:
                        continue
                    result = result.iloc[0]
                elif isinstance(result, np.ndarray):
                    if result.size == 0:
                        continue
                    result = result.flat[0]
                tmp_dict["specs"][str(method_name)] = numpy_to_python(result)

        results.append(tmp_dict)

    return results


def _mixed_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "text": ["alpha", "beta", "alpha", "gamma", "beta"],
            "text_with_nulls": ["a", None, "a", "b", None],
            "ints": [3, 1, 4, 1, 5],
            "ints_small": pl.Series([10, 20, 30, 40, 50], dtype=pl.Int32),
            "ints_with_nulls": [1, None, 3, None, 5],
            "floats": [1.5, -2.25, 0.0, 8.125, 3.5],
            "floats_with_nan": [1.0, float("nan"), 3.0, None, 5.0],
            "flags": [True, False, True, True, False],
            "flags_with_nulls": [True, None, False, True, None],
            "when": [datetime(2024, 1, i + 1) for i in range(5)],
            "labels": pl.Series(["x", "y", "x", "z", "y"], dtype=pl.Categorical),
        }
    )


def _assert_specs_equivalent(new: list[dict], ref: list[dict]) -> None:
    """Every reference spec is reproduced, up to float rounding.

    A reference entry that is NaN is allowed to be absent from the new output:
    pandas returned NaN for aggregations over nothing (empty / all-null column),
    the lazy implementation returns null and skips the key. Both read as
    "no value" downstream, and NaN is turned into null on serialisation anyway
    (``sanitize_for_json``).
    """
    assert [c["name"] for c in new] == [c["name"] for c in ref]
    for got, want in zip(new, ref):
        assert got["type"] == want["type"], f"type drift on {want['name']}"
        assert got["description"] == want["description"]
        for method, expected in want["specs"].items():
            if isinstance(expected, float) and math.isnan(expected):
                assert method not in got["specs"] or math.isnan(got["specs"][method])
                continue
            assert method in got["specs"], f"{want['name']}.{method} missing"
            actual = got["specs"][method]
            if isinstance(expected, float):
                assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12), (
                    f"{want['name']}.{method}"
                )
            else:
                assert actual == expected, f"{want['name']}.{method}"
        assert set(got["specs"]) <= set(want["specs"]), (
            f"{want['name']}: unexpected extra specs {set(got['specs']) - set(want['specs'])}"
        )


# --------------------------------------------------------------------------
# Contract: parity with the pandas implementation
# --------------------------------------------------------------------------
def test_matches_pandas_reference() -> None:
    """Full parity against the previous pandas implementation, real agg_functions.

    ``previous_types`` is seeded from the reference output so the two agree on
    the nullable-int / nullable-bool types pandas used to widen — that
    divergence is covered on its own in ``test_type_policy_*``.
    """
    df = _mixed_frame()
    dc_data = {
        "config": {
            "dc_specific_properties": {"columns_description": {"ints": "a counter of things"}}
        }
    }
    ref = _pandas_reference(df, REAL_AGG_FUNCTIONS, dc_data)
    previous_types = {c["name"]: c["type"] for c in ref}
    new = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, dc_data, previous_types=previous_types)
    _assert_specs_equivalent(new, ref)


def test_never_materialises_to_pandas(monkeypatch) -> None:
    """The whole point of the rewrite: no frame is ever converted to pandas."""

    def explode(*_a, **_kw):
        raise AssertionError("precompute_columns_specs must not materialise via to_pandas()")

    monkeypatch.setattr(pl.DataFrame, "to_pandas", explode)
    specs = precompute_columns_specs(_mixed_frame(), REAL_AGG_FUNCTIONS, _dc_data())
    assert len(specs) == len(_mixed_frame().columns)


def test_lazyframe_and_dataframe_agree(tmp_path) -> None:
    """A LazyFrame over a file yields the same specs as the eager frame."""
    df = _mixed_frame()
    path = tmp_path / "frame.parquet"
    df.write_parquet(path)
    eager = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())
    lazy = precompute_columns_specs(pl.scan_parquet(path), REAL_AGG_FUNCTIONS, _dc_data())
    # Same values, up to last-bit differences between execution plans.
    _assert_specs_equivalent(lazy, eager)


# --------------------------------------------------------------------------
# Type names — the vocabulary the validator and the frontend depend on
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("series", "expected"),
    [
        (pl.Series(["a", "b"]), "object"),
        (pl.Series(["a", "b"], dtype=pl.Categorical), "category"),
        (pl.Series(["a", "b"], dtype=pl.Enum(["a", "b"])), "category"),
        (pl.Series([1, 2]), "int64"),
        (pl.Series([1, 2], dtype=pl.Int32), "int64"),
        (pl.Series([1, 2], dtype=pl.UInt8), "int64"),
        (pl.Series([1.0, 2.0]), "float64"),
        (pl.Series([1.0, 2.0], dtype=pl.Float32), "float64"),
        (pl.Series([True, False]), "bool"),
        (pl.Series([datetime(2024, 1, 1)]), "datetime"),
        (pl.Series([], dtype=pl.Date), "datetime"),
        (pl.Series([], dtype=pl.Duration), "time"),
        (pl.Series([], dtype=pl.Time), "object"),
        (pl.Series([[1, 2]]), "object"),
        (pl.Series([{"a": 1}]), "object"),
        (pl.Series([None, None]), "object"),
    ],
)
def test_type_names(series: pl.Series, expected: str) -> None:
    """Every emitted name must be accepted by DeltaTableColumn.validate_column_type."""
    [spec] = precompute_columns_specs(pl.DataFrame({"col": series}), REAL_AGG_FUNCTIONS, _dc_data())
    assert spec["type"] == expected


def test_type_policy_new_column_gets_true_polars_type() -> None:
    """A column never seen before is typed from polars, not from pandas' widening.

    ``to_pandas()`` turned an Int64 column holding nulls into float64 and a
    Boolean column holding nulls into object. New columns no longer inherit that.
    """
    df = pl.DataFrame({"i": [1, None, 3], "b": [True, None, False]})
    specs = {
        s["name"]: s["type"] for s in precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())
    }
    assert specs == {"i": "int64", "b": "bool"}


def test_type_policy_known_column_keeps_recorded_type() -> None:
    """A column already recorded keeps its type, so saved components don't desync."""
    df = pl.DataFrame({"i": [1, None, 3], "b": [True, None, False]})
    specs = precompute_columns_specs(
        df,
        REAL_AGG_FUNCTIONS,
        _dc_data(),
        previous_types={"i": "float64", "b": "object"},
    )
    by_name = {s["name"]: s for s in specs}
    assert by_name["i"]["type"] == "float64"
    assert by_name["b"]["type"] == "object"
    # ...and the specs follow the recorded type's card methods.
    assert "average" in by_name["i"]["specs"]
    assert "nunique" in by_name["b"]["specs"]


def test_type_policy_real_schema_change_wins_over_recorded_type() -> None:
    """A recorded type that no longer describes the column is dropped."""
    df = pl.DataFrame({"c": ["a", "b"]})
    [spec] = precompute_columns_specs(
        df, REAL_AGG_FUNCTIONS, _dc_data(), previous_types={"c": "int64"}
    )
    assert spec["type"] == "object"


# --------------------------------------------------------------------------
# Values whose pandas/polars defaults differ
# --------------------------------------------------------------------------
def test_pandas_default_semantics_on_numeric_column() -> None:
    """quantile/skew/kurt/var use the pandas conventions, not the polars ones."""
    values = [1.0, 2.0, 2.5, 4.0, 9.0, 11.5, 12.0]
    df = pl.DataFrame({"v": values})
    pdf = df.to_pandas()
    [spec] = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["percentile"] == pytest.approx(pdf["v"].quantile())
    assert spec["specs"]["skewness"] == pytest.approx(pdf["v"].skew())
    assert spec["specs"]["kurtosis"] == pytest.approx(pdf["v"].kurt())
    assert spec["specs"]["variance"] == pytest.approx(pdf["v"].var())
    assert spec["specs"]["range"] == pytest.approx(max(values) - min(values))


def test_nan_counts_as_missing_like_pandas() -> None:
    """polars treats NaN as a value, pandas as missing — pandas wins here."""
    df = pl.DataFrame({"v": [1.0, float("nan"), None, 2.0]})
    [spec] = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["count"] == 2
    assert spec["specs"]["unique"] == 2
    assert spec["specs"]["average"] == pytest.approx(1.5)
    assert spec["specs"]["max"] == pytest.approx(2.0)


def test_nunique_and_mode_ignore_nulls() -> None:
    df = pl.DataFrame({"c": ["a", None, None, "b", "a"]})
    [spec] = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["nunique"] == 2
    assert spec["specs"]["mode"] == "a"
    assert spec["specs"]["count"] == 3


# --------------------------------------------------------------------------
# Mode — the viralrecon regression
# --------------------------------------------------------------------------
def test_mode_with_default_index() -> None:
    df = pl.DataFrame({"lineage": ["A", "A", "B", "A"]})
    [spec] = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["mode"] == "A"
    assert spec["specs"]["count"] == 4
    assert spec["specs"]["nunique"] == 2


def test_mode_tie_picks_smallest_like_pandas() -> None:
    """pandas returned the tied modes sorted and the caller took the first."""
    df = pl.DataFrame({"c": ["b", "b", "a", "a", "c"]})
    [spec] = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["mode"] == "a"


def test_empty_column_does_not_crash() -> None:
    """An empty column emits count=0 without raising, mode entry skipped."""
    df = pl.DataFrame({"empty_col": pl.Series([], dtype=pl.Utf8)})
    [spec] = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["count"] == 0
    assert "mode" not in spec["specs"]


def test_pangolin_lineages_shape_does_not_raise() -> None:
    """Smoke test matching the bundled pangolin_lineages.tsv shape:
    44 rows, sparse string columns (many empty), non-trivial mode targets.
    """
    rows = [
        {
            "sample": f"SAMPLE_{i:02d}",
            "lineage": "B.1.1.7" if i % 2 else "Unassigned",
            "scorpio_call": "Alpha (B.1.1.7-like)" if i % 2 else "",
            "scorpio_notes": "",
            "note": "",
            "qc_status": "pass" if i % 2 else "fail",
        }
        for i in range(44)
    ]
    df = pl.from_dicts(rows)
    specs = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    assert len(specs) == len(df.columns)
    by_name = {s["name"]: s for s in specs}
    assert by_name["lineage"]["specs"]["mode"] in ("B.1.1.7", "Unassigned")
    assert by_name["qc_status"]["specs"]["mode"] in ("pass", "fail")


def test_unique_values_recorded_for_categorical() -> None:
    """Categorical columns carry a frequency-ordered ``unique_values`` sample so
    the card-builder preview shows real names instead of "Bucket N" labels."""
    df = pl.DataFrame({"variety": ["Setosa", "Setosa", "Versicolor", "Virginica"]})
    [spec] = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    uv = spec["specs"]["unique_values"]
    assert uv[0] == "Setosa"  # most frequent first
    assert set(uv) == {"Setosa", "Versicolor", "Virginica"}


def test_unique_values_capped() -> None:
    """High-cardinality columns only keep a capped sample to keep specs compact."""
    df = pl.DataFrame({"id": [f"v{i}" for i in range(50)]})
    [spec] = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    assert len(spec["specs"]["unique_values"]) == 20


# --------------------------------------------------------------------------
# Degradation rather than aborting the upsert
# --------------------------------------------------------------------------
def test_nested_dtype_does_not_abort_other_columns() -> None:
    """A dtype some aggregations reject must not take the whole upsert down."""
    df = pl.DataFrame({"nested": [{"a": 1}, {"a": 2}], "text": ["x", "y"]})
    specs = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())
    by_name = {s["name"]: s for s in specs}
    assert by_name["nested"]["type"] == "object"
    assert by_name["text"]["specs"]["count"] == 2


def test_unknown_card_method_is_skipped_not_fatal() -> None:
    """A card method with no polars equivalent is dropped with a warning."""
    agg = {
        "object": {
            "card_methods": {
                "count": {"pandas": "count"},
                "made_up": {"pandas": "there_is_no_such_method"},
            }
        }
    }
    df = pl.DataFrame({"c": ["a", "b"]})
    [spec] = precompute_columns_specs(df, agg, _dc_data())
    assert spec["specs"]["count"] == 2
    assert "made_up" not in spec["specs"]


def test_description_is_attached_from_dc_config() -> None:
    dc_data = {"config": {"dc_specific_properties": {"columns_description": {"c": "the c column"}}}}
    df = pl.DataFrame({"c": ["a"], "other": ["b"]})
    specs = {
        s["name"]: s["description"] for s in precompute_columns_specs(df, _AGG_FUNCTIONS, dc_data)
    }
    assert specs == {"c": "the c column", "other": None}


# --------------------------------------------------------------------------
# Temporal columns — the ampliseq ``metadata`` regression
# --------------------------------------------------------------------------
# Specs go straight into MongoDB, so every value has to be BSON-encodable.
# polars hands back ``datetime.date`` for a Date column and ``datetime.time``
# for a Time column, neither of which BSON can encode. The upsert answered 500
# with ``InvalidDocument: cannot encode object: datetime.date(...)``, so no
# deltatable document was written; the S3 prefix that had just been written was
# then reaped as an orphan, and every component bound to the DC was left on a
# 404. Hit in production by ampliseq's ``metadata`` DC, whose ``sampling_date``
# is parsed by ``try_parse_dates``.
def test_date_column_specs_are_bson_encodable() -> None:
    df = pl.DataFrame({"sampling_date": [date(2023, 1, 5), date(2023, 3, 17)]})
    [spec] = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())

    assert spec["type"] == "datetime"
    # The exact call that used to raise.
    bson_encode(spec["specs"])
    assert spec["specs"]["min"] == datetime(2023, 1, 5)
    assert spec["specs"]["max"] == datetime(2023, 3, 17)


def test_datetime_column_specs_keep_their_time_component() -> None:
    """``datetime`` is BSON-native and must not be truncated to midnight."""
    stamps = [datetime(2023, 1, 5, 13, 45, 30), datetime(2023, 3, 17, 4, 20, 0)]
    df = pl.DataFrame({"seen_at": stamps})
    [spec] = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())

    bson_encode(spec["specs"])
    assert spec["specs"]["min"] == stamps[0]
    assert spec["specs"]["max"] == stamps[1]


def test_time_column_specs_are_bson_encodable() -> None:
    """A Time column normalizes to ``object``, whose mode is a ``datetime.time``."""
    df = pl.DataFrame({"collected_at": [time(9, 30), time(17, 15)]})
    [spec] = precompute_columns_specs(df, REAL_AGG_FUNCTIONS, _dc_data())

    bson_encode(spec["specs"])
