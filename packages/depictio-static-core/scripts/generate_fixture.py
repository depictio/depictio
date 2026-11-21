#!/usr/bin/env python
"""Generate the depictio-static-core engine test fixture.

Writes ``fixtures/engine-fixture.parquet`` (snappy, 4 row groups) plus
``fixtures/engine-expected.json`` — the Polars-computed ground truth the vitest
suite compares the TypeScript kernels against.

Run with the repo venv (Polars pinned there is the server's version):

    /home/user/depictio/venv/bin/python packages/depictio-static-core/scripts/generate_fixture.py

Every predicate/aggregation below is written in the *server's* form, mirroring
``depictio/api/v1/deltatables_utils.py`` (``add_filter`` /
``_categorical_predicate``) and
``depictio/api/v1/endpoints/dashboards_endpoints/routes.py`` (``_agg_value``),
so the JSON is "what the server would answer", not "what Polars can do".

Companion columns + codebooks come from the REAL builder
(``depictio.serverless.companions.build_companions``), so the vitest suite is a
true cross-language contract test: the TS ``serializeOption`` must produce the
byte-identical keys the Python ``serialize_option`` wrote.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from depictio.serverless.companions import build_companions

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures"
N = 2000
ROW_GROUP_SIZE = 600  # -> 4 row groups over 2000 rows

rng = random.Random(42)

CATEGORIES = ["alpha", "beta", "gamma", "delta", "epsilon"]
# Weighted so 'alpha' is the unique mode (asserted below — Polars' tie order is
# nondeterministic, so the fixture must not contain an aggregation tie).
CATEGORY_WEIGHTS = [0.34, 0.22, 0.18, 0.16, 0.10]
BATCHES = [1, 2, 3, 4, 5]

EPOCH = datetime(1970, 1, 1)

#: Component-static filter_exprs the binding cases AND in (card / interactive
#: ``filter_expr`` — the seeds' own shapes: comparisons, null checks, is_in).
FILTER_EXPRS = [
    "col('value_f64') > 0.5",
    "(col('category_str') != 'alpha') & col('value_i64').is_not_null()",
    "col('batch').is_in([1, 3])",
]

#: Viewer filter payloads (InteractiveFilter shape) whose rows the TS binder
#: (filterBinding.bindFilters) + mask kernel must reproduce. Expected rows are
#: what the SERVER keeps: clean_filter_payload → process_metadata_and_filter.
BINDING_CASES: dict[str, list[dict]] = {
    # TextInput: case-insensitive regex by default (text_filter_pattern).
    "text_ci_default": [
        {"value": "ALP", "column_name": "category_str", "interactive_component_type": "TextInput"}
    ],
    "text_case_sensitive": [
        {
            "value": "ALP",
            "column_name": "category_str",
            "interactive_component_type": "TextInput",
            "metadata": {"case_sensitive": True},
        }
    ],
    "text_regex_ci_anchored": [
        {
            "value": "^(ALPHA|beta)$",
            "column_name": "category_str",
            "interactive_component_type": "TextInput",
        }
    ],
    "text_contains_literal_meta": [
        {
            "value": "^al",
            "column_name": "category_str",
            "interactive_component_type": "TextInput",
            "metadata": {"match_mode": "contains"},
        }
    ],
    "text_contains_ci": [
        {
            "value": "AMM",
            "column_name": "category_str",
            "interactive_component_type": "TextInput",
            "match_mode": "contains",
        }
    ],
    "text_trimmed": [
        {
            "value": "  gam  ",
            "column_name": "category_str",
            "interactive_component_type": "TextInput",
        }
    ],
    "text_invalid_regex_is_no_filter": [
        {"value": "(", "column_name": "category_str", "interactive_component_type": "TextInput"}
    ],
    "text_numeric_column": [
        {"value": "^4", "column_name": "value_i64", "interactive_component_type": "TextInput"}
    ],
    # Slider: >= unless slider_mode says otherwise (_slider_predicate).
    "slider_default_gte": [
        {"value": 42, "column_name": "value_i64", "interactive_component_type": "Slider"}
    ],
    "slider_lt_meta": [
        {
            "value": 0.5,
            "column_name": "value_f64",
            "interactive_component_type": "Slider",
            "metadata": {"slider_mode": "lt"},
        }
    ],
    "slider_eq": [
        {
            "value": 42,
            "column_name": "value_i64",
            "interactive_component_type": "Slider",
            "slider_mode": "eq",
        }
    ],
    "slider_ne": [
        {
            "value": 42,
            "column_name": "value_i64",
            "interactive_component_type": "Slider",
            "slider_mode": "ne",
        }
    ],
    "slider_zero_is_a_value": [
        {"value": 0, "column_name": "value_f64", "interactive_component_type": "Slider"}
    ],
    # filter_expr ANDed after the entry's own predicate.
    "multiselect_with_filter_expr": [
        {
            "value": ["2", "4"],
            "column_name": "batch",
            "interactive_component_type": "MultiSelect",
            "filter_expr": FILTER_EXPRS[0],
        }
    ],
    "text_with_filter_expr_in_metadata": [
        {
            "value": "a",
            "column_name": "category_str",
            "interactive_component_type": "TextInput",
            "metadata": {"filter_expr": FILTER_EXPRS[1]},
        }
    ],
    "range_with_isin_filter_expr": [
        {
            "value": [-1.0, 2.0],
            "column_name": "value_f64",
            "interactive_component_type": "RangeSlider",
            "filter_expr": FILTER_EXPRS[2],
        }
    ],
    # A categorical filter on ``depictio_run_id`` also keeps the rows with no
    # run (add_filter's ``| is_null()``): they aggregate several runs.
    "run_id_keeps_null_runs": [
        {
            "value": ["run-1"],
            "column_name": "depictio_run_id",
            "interactive_component_type": "MultiSelect",
        }
    ],
    "run_id_select_scalar": [
        {"value": "run-2", "column_name": "depictio_run_id", "interactive_component_type": "Select"}
    ],
    # ...but only that column: a null category never matches a Select.
    "select_drops_null_elsewhere": [
        {"value": ["alpha"], "column_name": "category_str", "interactive_component_type": "Select"}
    ],
    # An empty value drops the whole entry — its filter_expr with it.
    "empty_value_drops_its_filter_expr": [
        {
            "value": [],
            "column_name": "batch",
            "interactive_component_type": "MultiSelect",
            "filter_expr": FILTER_EXPRS[0],
        }
    ],
}

#: Card aggregations defined by the server's _agg_value / precompute parity
#: table rather than spelled out in the kernel (q1/q3 quantiles, the bias-
#: corrected skew/kurtosis, `percentile`).
PARITY_AGGS = ["q1", "q3", "percentile", "skewness", "kurtosis"]

#: Card secondary layouts (card_breakdown.compute_breakdown /
#: card_metrics.numeric_layout_payload), each over the full frame and under the
#: ``in_str`` mask: (name, card, layout).
CARD_LAYOUT_CASES: list[tuple[str, dict, str]] = [
    (
        "bd_count",
        {"column_name": "category_str", "aggregation": "count", "breakdown_col": "batch"},
        "top_n",
    ),
    (
        "bd_sum_f64",
        {"column_name": "value_f64", "aggregation": "sum", "breakdown_col": "category_str"},
        "donut",
    ),
    (
        "bd_sum_i64",
        {
            "column_name": "value_i64",
            "aggregation": "sum",
            "breakdown_col": "batch",
            "top_n_count": 5,
        },
        "composition",
    ),
    (
        "bd_nunique",
        {"column_name": "value_i64", "aggregation": "nunique", "breakdown_col": "category_str"},
        "concentration",
    ),
    (
        "bd_self",
        {"column_name": "category_str", "aggregation": "nunique", "breakdown_col": "category_str"},
        "top_n",
    ),
    (
        "bd_mean",
        {"column_name": "value_f64", "aggregation": "average", "breakdown_col": "batch"},
        "top_n",
    ),
    (
        "bd_min",
        {"column_name": "value_f64", "aggregation": "min", "breakdown_col": "category_str"},
        "top_n",
    ),
    (
        "bd_bool",
        {"column_name": "value_f64", "aggregation": "count", "breakdown_col": "flag_bool"},
        "donut",
    ),
    ("hist_f64", {"column_name": "value_f64", "aggregation": "average"}, "histogram"),
    ("hist_nn", {"column_name": "metric_f64_nn", "aggregation": "average"}, "histogram"),
    ("hist_batch", {"column_name": "batch", "aggregation": "average"}, "histogram"),
    (
        "thr_min_warn",
        {
            "column_name": "value_f64",
            "aggregation": "average",
            "threshold_value": 0.5,
            "threshold_warn": -1.0,
        },
        "threshold",
    ),
    (
        "thr_max",
        {
            "column_name": "value_i64",
            "aggregation": "average",
            "threshold_value": 100,
            "threshold_direction": "max",
        },
        "threshold",
    ),
    ("completeness", {"column_name": "value_f64", "aggregation": "count"}, "completeness"),
    ("uniq_sample", {"column_name": "sample_id", "aggregation": "nunique"}, "uniqueness"),
    ("uniq_batch", {"column_name": "batch", "aggregation": "nunique"}, "uniqueness"),
    (
        "trend_date_mean",
        {"column_name": "value_f64", "aggregation": "average", "trend_col": "event_date"},
        "trend",
    ),
    (
        "trend_batch_count",
        {"column_name": "value_f64", "aggregation": "count", "trend_col": "batch"},
        "trend",
    ),
    (
        "trend_idx_sum",
        {"column_name": "value_i64", "aggregation": "sum", "trend_col": "idx_i32"},
        "trend",
    ),
    (
        "trend_cat_max",
        {"column_name": "value_f64", "aggregation": "max", "trend_col": "category_str"},
        "trend",
    ),
    (
        "attrition",
        {
            "column_name": "metric_f64_nn",
            "aggregation": "sum",
            "attrition_cols": ["idx_i32", "value_i64"],
        },
        "attrition",
    ),
]
DATE_LO = datetime(2023, 1, 1)


def maybe_null(value, p=0.06):
    return None if rng.random() < p else value


def main() -> None:
    value_f64: list[float | None] = []
    value_i64: list[int | None] = []
    category_str: list[str | None] = []
    batch: list[int | None] = []
    flag_bool: list[bool | None] = []
    event_date: list[datetime | None] = []
    sample_id: list[str | None] = []

    for i in range(N):
        value_f64.append(maybe_null(round(rng.gauss(0.0, 2.0), 6)))
        # Mostly small repeated ints (so `eq` has hits) + a sprinkle of large
        # values that force the Int64 -> BigInt64Array path to matter.
        if rng.random() < 0.02:
            base = 4_000_000_000_000 + rng.randint(0, 10)
        else:
            base = rng.randint(0, 200)
        value_i64.append(maybe_null(base))
        category_str.append(maybe_null(rng.choices(CATEGORIES, CATEGORY_WEIGHTS)[0]))
        batch.append(maybe_null(rng.choice(BATCHES)))
        flag_bool.append(maybe_null(rng.random() < 0.4))
        event_date.append(
            maybe_null(
                DATE_LO
                + timedelta(minutes=rng.randint(0, 60 * 24 * 400), seconds=rng.randint(0, 59))
            )
        )
        sample_id.append(maybe_null("S" + str(i).zfill(4), p=0.03))

    df = pl.DataFrame(
        {
            # Null-free columns: exercise the typed-array preservation path of
            # the engine's chunk assembly (every other column carries nulls and
            # therefore decodes to plain arrays).
            "idx_i32": pl.Series(list(range(N)), dtype=pl.Int32),
            "metric_f64_nn": pl.Series(
                [round(i * 0.25 - 100.0, 6) for i in range(N)], dtype=pl.Float64
            ),
            "value_f64": pl.Series(value_f64, dtype=pl.Float64),
            "value_i64": pl.Series(value_i64, dtype=pl.Int64),
            "category_str": pl.Series(category_str, dtype=pl.String),
            "batch": pl.Series(batch, dtype=pl.Int64),
            "flag_bool": pl.Series(flag_bool, dtype=pl.Boolean),
            "event_date": pl.Series(event_date, dtype=pl.Datetime("us")),
            "sample_id": pl.Series(sample_id, dtype=pl.String),
            # Every 7th row has no run (a recipe recomputed over every run);
            # derived from the index so the rng stream above is unchanged.
            "depictio_run_id": pl.Series(
                [None if i % 7 == 0 else f"run-{i % 3}" for i in range(N)], dtype=pl.String
            ),
        }
    )

    # ---- companions: produced by the REAL builder ---------------------------
    # ``__code__batch``/``__code__flag_bool`` (Int32 codes + str()-keyed
    # codebooks) and ``__ts__event_date`` (epoch-µs Int64) come from
    # depictio.serverless.companions.build_companions, so the fixture's
    # codebook keys are exactly what production bundles will carry.
    base_df = df  # the server's view: no companions
    companion_result = build_companions(
        df,
        categorical_cols=["batch", "flag_bool", "category_str"],  # String col → no codebook
        datetime_cols=["event_date"],
        # Component-static filter_exprs → ``__fe__<sha8>`` Boolean companions,
        # evaluated with the server's build_filter_expr (RFC §5).
        filter_exprs=FILTER_EXPRS,
    )
    df = companion_result.df
    assert "category_str" not in companion_result.codebooks  # String stays direct
    assert companion_result.codebooks["batch"] == {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4}
    assert companion_result.codebooks["flag_bool"] == {"false": 0, "true": 1}

    FIXTURES.mkdir(parents=True, exist_ok=True)
    # Write via pyarrow so the null-free columns can be marked REQUIRED
    # (non-nullable). Polars' native writer marks every column OPTIONAL, and
    # hyparquet's assembly de-types OPTIONAL columns even with zero nulls —
    # only REQUIRED columns exercise the typed-array preservation path.
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = df.to_arrow()
    fields = [f.with_nullable(df[f.name].null_count() > 0) for f in table.schema]
    table = table.cast(pa.schema(fields))
    pq.write_table(
        table,
        FIXTURES / "engine-fixture.parquet",
        compression="snappy",
        row_group_size=ROW_GROUP_SIZE,
        # PLAIN-encode the two REQUIRED columns: hyparquet's dictionary decode
        # materialises plain JS arrays, so only REQUIRED + PLAIN columns come
        # back as typed arrays (the spike's 1M-row columns hit this naturally
        # via the writer's dictionary-size fallback). Everything else keeps
        # dictionary encoding so both decode paths are exercised.
        use_dictionary=[c for c in df.columns if c not in ("idx_i32", "metric_f64_nn")],
    )

    # ---- expected results (server predicate forms) -------------------------

    def mask_summary(mask_expr: pl.Expr) -> dict:
        sub = df.filter(mask_expr)
        chk = sub["value_f64"].sum()
        return {"matched": sub.height, "value_f64_sum": float(chk) if chk is not None else 0.0}

    ts_lo = datetime(2023, 6, 1)
    ts_hi = datetime(2023, 9, 30, 23, 59, 59)

    filters: dict[str, dict] = {}

    # add_filter Select/MultiSelect on String col: pl.col(c).is_in(str_values)
    in_str_expr = pl.col("category_str").is_in(["alpha", "beta"])
    filters["in_str"] = {**mask_summary(in_str_expr)}

    # Codebook path: engine matches codes on __code__batch; server casts the
    # stringified values back to Int64 and is_in's the source column. Same rows.
    filters["in_codebook"] = {**mask_summary(pl.col("batch").is_in([2, 4]))}
    filters["in_codebook_miss"] = {**mask_summary(pl.col("batch").is_in([2, 99]))}
    filters["in_codebook_all_miss"] = {**mask_summary(pl.col("batch").is_in([99]))}

    # Boolean column: the server's _categorical_predicate keeps the Utf8
    # fallback for Boolean dtypes (deltatables_utils.py:174-175,185), so a
    # picked option "true" is `col.cast(Utf8).is_in(["true"])`. The engine's
    # codebook path (codebook {"false":0,"true":1}) selects the same rows.
    filters["in_bool"] = {
        **mask_summary(pl.col("flag_bool").cast(pl.Utf8, strict=False).is_in(["true"]))
    }

    # RangeSlider: (col >= lo) & (col <= hi), inclusive (add_filter:268-272)
    filters["range_f64"] = {
        **mask_summary((pl.col("value_f64") >= -0.5) & (pl.col("value_f64") <= 1.5))
    }

    # Slider: col == value (add_filter:264-266)
    eq_target = 42
    filters["eq_i64"] = {**mask_summary(pl.col("value_i64") == eq_target), "value": eq_target}

    # TextInput: pl.col(c).str.contains(pattern) — regex, case-sensitive
    filters["contains_regex"] = {
        **mask_summary(pl.col("category_str").str.contains("^al")),
        "pattern": "^al",
    }
    filters["contains_sub"] = {
        **mask_summary(pl.col("category_str").str.contains("amma")),
        "pattern": "amma",
    }

    # DateRangePicker/Timeline: (date >= start) & (date <= end), inclusive
    # (add_filter:343-345). Engine equivalent: __ts__ compare in epoch-us.
    ts_expr = (pl.col("event_date") >= pl.lit(ts_lo)) & (pl.col("event_date") <= pl.lit(ts_hi))
    filters["ts_range"] = {
        **mask_summary(ts_expr),
        "min_us": int((ts_lo - EPOCH).total_seconds() * 1_000_000),
        "max_us": int((ts_hi - EPOCH).total_seconds() * 1_000_000),
    }

    # Filters AND together (_apply_scan_filters:1191-1195)
    filters["combo"] = {
        **mask_summary(in_str_expr & (pl.col("value_f64") >= -0.5) & (pl.col("value_f64") <= 1.5))
    }

    # ---- aggregations (mirror _agg_value; routes.py:1290) ------------------

    def agg_value(col: pl.Series, agg: str):
        if agg == "count":
            return int(col.drop_nulls().len())
        if agg == "mean":
            m = col.mean()
            return float(m) if m is not None else None
        if agg == "sum":
            s = col.sum()
            return float(s) if s is not None else None
        if agg == "median":
            m = col.median()
            return float(m) if m is not None else None
        if agg in ("min", "max"):
            v = col.min() if agg == "min" else col.max()
            return float(v) if isinstance(v, (int, float)) else (str(v) if v is not None else None)
        if agg == "std":
            v = col.std()
            return float(v) if v is not None else None
        if agg == "var":
            v = col.var()
            return float(v) if v is not None else None
        if agg == "nunique":
            return int(col.n_unique())
        if agg == "mode":
            m = col.mode()
            # Server (_agg_value routes.py:1377-1383): None when empty, else m[0].
            if len(m) == 0:
                return None
            assert len(m) == 1, f"fixture must not contain a mode tie (got {m.to_list()})"
            return float(m[0]) if isinstance(m[0], (int, float)) else str(m[0])
        if agg == "first":
            v = col.first()
            return float(v) if isinstance(v, (int, float)) else (str(v) if v is not None else None)
        if agg == "last":
            v = col.last()
            return float(v) if isinstance(v, (int, float)) else (str(v) if v is not None else None)
        raise ValueError(agg)

    NUM_AGGS = [
        "sum",
        "mean",
        "median",
        "min",
        "max",
        "count",
        "nunique",
        "std",
        "var",
        "first",
        "last",
    ]

    def agg_block(frame: pl.DataFrame) -> dict:
        out: dict = {}
        for col in ("value_f64", "value_i64"):
            out[col] = {agg: agg_value(frame[col], agg) for agg in NUM_AGGS}
        out["category_str"] = {
            agg: agg_value(frame["category_str"], agg)
            for agg in ("count", "nunique", "mode", "min", "max", "first", "last")
        }
        return out

    masked_df = df.filter(in_str_expr)

    aggregates = {
        "full": agg_block(df),
        "masked_in_str": agg_block(masked_df),
        # Empty selection: what each agg returns on a zero-row frame.
        "empty": agg_block(df.head(0)),
    }
    aggregates["full"]["value_i64"]["mode"] = agg_value(df["value_i64"], "mode")

    # ---- unique (server: deltatables routes.py get_unique_values:687-689 —
    # drop_nulls, stringify, dedupe, sorted) ---------------------------------
    def unique_server(col: pl.Series) -> list[str]:
        return sorted({str(v) for v in col.drop_nulls().to_list()})

    unique = {
        "category_str_full": unique_server(df["category_str"]),
        "batch_full": unique_server(df["batch"]),
        "category_str_masked_range_f64": unique_server(
            df.filter((pl.col("value_f64") >= -0.5) & (pl.col("value_f64") <= 1.5))["category_str"]
        ),
    }

    # ---- minMax ------------------------------------------------------------
    def minmax(col: pl.Series) -> list:
        mn, mx = col.min(), col.max()
        return [
            float(mn) if mn is not None else None,
            float(mx) if mx is not None else None,
        ]

    minmax_block = {
        "value_f64_full": minmax(df["value_f64"]),
        "value_i64_full": minmax(df["value_i64"]),
        "value_f64_masked_in_str": minmax(masked_df["value_f64"]),
        "empty": [None, None],
    }

    # ---- sortSlice (phase 3) ----------------------------------------------
    # Ground truth for the TS sortSlice kernel, computed with the server's
    # EXACT sort call: render_table_endpoint's sorted branch delegates to
    # load_sorted_deltatable_lite (dashboards routes.py:2606-2621), which runs
    #     df.sort(sort_by, descending=..., nulls_last=True, maintain_order=True)
    # (deltatables_utils.py:1591-1592; identical arguments on the lazy page
    # path at 1568-1577; nulls_last=True is the function default at :1468 and
    # the endpoint never overrides it) and pages via .slice(start, limit)
    # (deltatables_utils.py:1522-1523). Filters apply BEFORE the sort
    # (metadata=filter_metadata, routes.py:2612-2621); total is the filtered
    # count (routes.py:2577-2579). The multi-key case uses the list form the
    # server itself uses at routes.py:2838-2847 (per-key descending,
    # nulls_last=True), plus maintain_order=True to pin stability.
    def sort_slice_case(
        sort_cols,
        descending,
        start: int,
        limit: int,
        filter_expr=None,
        value_col: str | None = None,
    ) -> dict:
        frame = df.filter(filter_expr) if filter_expr is not None else df
        if sort_cols:
            frame_sorted = frame.sort(
                sort_cols, descending=descending, nulls_last=True, maintain_order=True
            )
        else:
            frame_sorted = frame  # natural order branch (routes.py:2622-2633)
        page = frame_sorted.slice(start, limit)
        out: dict = {
            "total": frame.height,
            # idx_i32 is unique + null-free, so this list pins the full row order.
            "idx": page["idx_i32"].to_list(),
        }
        if value_col is not None:
            out["values"] = [
                (float(v) if isinstance(v, float) else v) for v in page[value_col].to_list()
            ]
        return out

    tail = N - 10  # last page: where nulls_last placement becomes visible
    sort_slice = {
        "f64_asc_head": sort_slice_case(["value_f64"], [False], 0, 10, value_col="value_f64"),
        "f64_asc_tail": sort_slice_case(["value_f64"], [False], tail, 10, value_col="value_f64"),
        "f64_desc_head": sort_slice_case(["value_f64"], [True], 0, 10, value_col="value_f64"),
        "f64_desc_tail": sort_slice_case(["value_f64"], [True], tail, 10, value_col="value_f64"),
        "i64_asc_head": sort_slice_case(["value_i64"], [False], 0, 10, value_col="value_i64"),
        "i64_desc_head": sort_slice_case(["value_i64"], [True], 0, 10, value_col="value_i64"),
        "str_asc_head": sort_slice_case(["category_str"], [False], 0, 10, value_col="category_str"),
        "str_asc_tail": sort_slice_case(
            ["category_str"], [False], tail, 10, value_col="category_str"
        ),
        "str_desc_head": sort_slice_case(["category_str"], [True], 0, 10, value_col="category_str"),
        "bool_asc_head": sort_slice_case(["flag_bool"], [False], 0, 10, value_col="flag_bool"),
        "date_asc_head": sort_slice_case(["event_date"], [False], 0, 10),
        "date_desc_head": sort_slice_case(["event_date"], [True], 0, 10),
        # Heavy ties on `batch` — maintain_order=True must keep input order
        # within each tie, so idx is the stability oracle.
        "batch_asc_stability": sort_slice_case(["batch"], [False], 0, 25),
        # Multi-key: per-key direction, ties on key 1 broken by key 2.
        "multi_str_asc_f64_desc": sort_slice_case(
            ["category_str", "value_f64"], [False, True], 0, 15
        ),
        # Filter-then-sort: mask narrows first, total is the filtered count.
        "masked_in_str_i64_asc": sort_slice_case(
            ["value_i64"], [False], 0, 10, filter_expr=in_str_expr, value_col="value_i64"
        ),
        # Natural order under a mask: plain slice of the filtered frame.
        "masked_in_str_natural": sort_slice_case([], [], 5, 10, filter_expr=in_str_expr),
    }

    # ---- binding cases (server: clean_filter_payload → process_metadata_and_filter)
    from depictio.api.v1.deltatables_utils import (
        clean_filter_payload,
        process_metadata_and_filter,
    )

    binding: dict[str, dict] = {}
    for name, payload in BINDING_CASES.items():
        exprs = process_metadata_and_filter(
            clean_filter_payload(payload), schema=dict(base_df.schema)
        )
        mask_expr = pl.all_horizontal(exprs) if exprs else pl.lit(True)
        binding[name] = {**mask_summary(mask_expr), "filters": payload}

    # ---- parity aggregations (server _agg_value) ---------------------------
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _agg_value

    aggregates_parity = {
        block: {
            col: {agg: _agg_value(frame[col], agg) for agg in PARITY_AGGS}
            for col in ("value_f64", "value_i64", "metric_f64_nn")
        }
        for block, frame in (
            ("full", df),
            ("masked_in_str", masked_df),
            ("empty", df.head(0)),
            ("tiny", df.head(3)),
        )
    }

    # ---- card secondary layouts (card_breakdown / card_metrics) ------------
    from depictio.api.v1.services.card_breakdown import compute_breakdown
    from depictio.api.v1.services.card_metrics import numeric_layout_payload

    card_layouts: dict[str, dict] = {}
    for name, card, layout in CARD_LAYOUT_CASES:
        for scope, frame in (("full", base_df), ("masked_in_str", base_df.filter(in_str_expr))):
            if layout in ("top_n", "concentration", "composition", "donut"):
                payload = compute_breakdown(
                    frame,
                    column=card["column_name"],
                    breakdown_col=card["breakdown_col"],
                    aggregation=card["aggregation"],
                    top_n_count=int(card.get("top_n_count") or 3),
                )
            else:
                payload = numeric_layout_payload(frame, card, card["column_name"], layout)
            card_layouts[f"{name}:{scope}"] = {"card": card, "layout": layout, "payload": payload}

    expected = {
        "rows": N,
        "row_group_size": ROW_GROUP_SIZE,
        "columns": {name: str(dtype) for name, dtype in df.schema.items()},
        "null_counts": {name: int(df[name].null_count()) for name in df.columns},
        "companions": companion_result.companions,
        "codebooks": companion_result.codebooks,
        "filters": filters,
        "aggregates": aggregates,
        "unique": unique,
        "minmax": minmax_block,
        "sort_slice": sort_slice,
        "binding": binding,
        "aggregates_parity": aggregates_parity,
        "card_layouts": card_layouts,
        "polars_version": pl.__version__,
    }

    (FIXTURES / "engine-expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    print(
        f"wrote {FIXTURES / 'engine-fixture.parquet'} ({(FIXTURES / 'engine-fixture.parquet').stat().st_size} bytes)"
    )
    print(f"wrote {FIXTURES / 'engine-expected.json'}")


if __name__ == "__main__":
    main()
