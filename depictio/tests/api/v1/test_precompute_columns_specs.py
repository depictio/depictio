"""Invariants on ``precompute_columns_specs`` — the per-column spec
builder run during Delta-table upsert.

The previous code used ``result[0]`` after computing ``.mode()`` on each
column, which is *label-based* pandas indexing. For viralrecon's
``pangolin_lineages`` DC several columns are sparse strings whose mode,
computed on the already-aggregated dataframe, comes back with a
non-default index — so ``result[0]`` raised ``KeyError(0)`` and aborted
the whole upsert. That left the dashboard tiles bound to that DC stuck
on 404 because the deltatables collection never got a record written.

These tests pin the positional-indexing behaviour and cover empty /
non-default-index edge cases so the regression doesn't come back.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from depictio.api.v1.endpoints.deltatables_endpoints.utils import precompute_columns_specs

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


def test_mode_with_default_index() -> None:
    """The original happy path: mode returns a Series with RangeIndex starting at 0."""
    df = pl.DataFrame({"lineage": ["A", "A", "B", "A"]})
    [spec] = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["mode"] == "A"
    assert spec["specs"]["count"] == 4
    assert spec["specs"]["nunique"] == 2


def test_mode_with_non_default_index_does_not_raise(monkeypatch) -> None:
    """The bug reproducer: aggregated df has a non-default index after to_pandas().

    Before the fix this raised ``KeyError(0)`` and the entire upsert
    aborted, taking the whole dashboard with it. We patch ``to_pandas``
    to inject the non-default index that the live aggregation pipeline
    actually produces for sparse string columns.
    """
    df = pl.DataFrame({"lineage": ["B.1.1.7", "B.1.1.7", "Unassigned"]})
    real_to_pandas = pl.DataFrame.to_pandas

    def to_pandas_with_offset_index(self, *a, **kw):  # type: ignore[no-untyped-def]
        out = real_to_pandas(self, *a, **kw)
        out.index = pd.RangeIndex(start=10, stop=10 + len(out))
        return out

    monkeypatch.setattr(pl.DataFrame, "to_pandas", to_pandas_with_offset_index)
    [spec] = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["mode"] == "B.1.1.7"


def test_empty_column_does_not_crash() -> None:
    """An empty column emits count=0 without raising, mode entry skipped."""
    df = pl.DataFrame({"empty_col": pl.Series([], dtype=pl.Utf8)})
    [spec] = precompute_columns_specs(df, _AGG_FUNCTIONS, _dc_data())
    assert spec["specs"]["count"] == 0
    # Mode on an empty series returns an empty Series → guard skips it.
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


def test_ndarray_result_uses_positional_indexing() -> None:
    """When pandas_method is callable and returns ndarray, positional
    indexing must still work — protects the symmetric branch in the fix."""
    agg_with_callable = {
        "object": {
            "card_methods": {
                "first_unique": {"pandas": lambda s: np.array([s.iloc[0]])},
            }
        },
        "str": {
            "card_methods": {
                "first_unique": {"pandas": lambda s: np.array([s.iloc[0]])},
            }
        },
    }
    df = pl.DataFrame({"col": ["x", "y"]})
    [spec] = precompute_columns_specs(df, agg_with_callable, _dc_data())
    assert spec["specs"]["first_unique"] == "x"
