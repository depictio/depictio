"""Emit the expected card-strip payloads for `e2e/golden/card_metrics.csv`.

Tool Studio computes a card's secondary strip in the browser (`src/api/
cardMetrics.ts`) because it has no backend and polars has no Pyodide wheel.
This script runs the REAL server modules over the committed fixture and prints
their output as JSON; `src/test/cardMetrics.test.ts` asserts the TypeScript port
reproduces it exactly. A change on either side that alters a number fails the
test instead of quietly making a preview disagree with what depictio renders.

`card_metrics` and `card_breakdown` are pure polars, so they import in ~0.1s
with nothing configured. The plain aggregations are *not* imported: they live in
`dashboards_endpoints/routes.py`, which validates the server Settings at import
time and cannot run from a build script. Their polars expressions are mirrored
below from `_POLARS_AGG_EXPRS`
(depictio/api/v1/endpoints/deltatables_endpoints/utils.py) — keep the two in
step; the values themselves still come from polars, not from hand-written maths.

Usage: python scripts/card_metrics_golden.py   (prints JSON on stdout)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import polars as pl

from depictio.api.v1.services.card_breakdown import compute_breakdown
from depictio.api.v1.services.card_metrics import numeric_layout_payload

FIXTURE = Path(__file__).resolve().parent.parent / "e2e" / "golden" / "card_metrics.csv"

# Mirrors `_POLARS_AGG_EXPRS` + the `q1`/`q3`/`percentile` branches of
# `_agg_expr`. See the module docstring for why it is mirrored, not imported.
AGG_EXPRS = {
    "count": lambda e: e.drop_nulls().len(),
    "nunique": lambda e: e.drop_nulls().n_unique(),
    "sum": lambda e: e.sum(),
    "average": lambda e: e.mean(),
    "median": lambda e: e.median(),
    "min": lambda e: e.min(),
    "max": lambda e: e.max(),
    "range": lambda e: e.max() - e.min(),
    "variance": lambda e: e.var(),
    "std_dev": lambda e: e.std(),
    "q1": lambda e: e.quantile(0.25, interpolation="linear"),
    "q3": lambda e: e.quantile(0.75, interpolation="linear"),
    # `percentile` maps to the precompute's `quantile` entry, which is fixed at
    # the median — a "percentile" card shows the median.
    "percentile": lambda e: e.quantile(0.5, interpolation="linear"),
    "skewness": lambda e: pl.when(e.count() >= 3).then(e.skew(bias=False)),
    "kurtosis": lambda e: pl.when(e.count() >= 4).then(e.kurtosis(bias=False)),
    "mode": lambda e: e.drop_nulls().mode().min(),
}

# One case per layout, chosen so every branch of the port is exercised: the
# fixture has nulls, a duplicated sample id, an outlier coverage value, a
# 30-value date axis (which forces trend's bucketing branch) and a 6-value
# integer axis (which does not).
LAYOUT_CASES = [
    {"name": "histogram_coverage", "layout": "histogram", "column": "coverage", "card": {}},
    {
        "name": "threshold_coverage_min",
        "layout": "threshold",
        "column": "coverage",
        "card": {"threshold_value": 60, "threshold_direction": "min", "threshold_warn": 40},
    },
    {
        "name": "threshold_coverage_max_no_warn",
        "layout": "threshold",
        "column": "coverage",
        "card": {"threshold_value": 80, "threshold_direction": "max"},
    },
    {
        "name": "completeness_coverage",
        "layout": "completeness",
        "column": "coverage",
        "card": {},
    },
    {"name": "uniqueness_sample", "layout": "uniqueness", "column": "sample", "card": {}},
    {"name": "uniqueness_run", "layout": "uniqueness", "column": "run", "card": {}},
    {
        "name": "attrition_reads",
        "layout": "attrition",
        "column": "raw_reads",
        "card": {"attrition_cols": ["trimmed_reads", "mapped_reads"], "aggregation": "sum"},
    },
    {
        "name": "trend_by_day_bucketed",
        "layout": "trend",
        "column": "coverage",
        "card": {"trend_col": "day", "aggregation": "average"},
    },
    {
        "name": "trend_by_run",
        "layout": "trend",
        "column": "coverage",
        "card": {"trend_col": "run", "aggregation": "average"},
    },
    {
        "name": "trend_by_run_count",
        "layout": "trend",
        "column": "sample",
        "card": {"trend_col": "run", "aggregation": "count"},
    },
    {
        "name": "trend_by_lineage_categorical",
        "layout": "trend",
        "column": "coverage",
        "card": {"trend_col": "lineage", "aggregation": "sum"},
    },
]

BREAKDOWN_CASES = [
    {
        "name": "breakdown_lineage_count",
        "column": "coverage",
        "breakdown_col": "lineage",
        "aggregation": "count",
        "top_n_count": 3,
    },
    {
        "name": "breakdown_lineage_sum",
        "column": "coverage",
        "breakdown_col": "lineage",
        "aggregation": "sum",
        "top_n_count": 5,
    },
    {
        "name": "breakdown_self",
        "column": "lineage",
        "breakdown_col": "lineage",
        "aggregation": "nunique",
        "top_n_count": 3,
    },
    {
        "name": "breakdown_run_nunique",
        "column": "sample",
        "breakdown_col": "run",
        "aggregation": "nunique",
        "top_n_count": 4,
    },
]

AGG_CASES = [
    ("coverage", agg)
    for agg in (
        "count",
        "nunique",
        "sum",
        "average",
        "median",
        "min",
        "max",
        "range",
        "variance",
        "std_dev",
        "q1",
        "q3",
        "percentile",
        "skewness",
        "kurtosis",
    )
] + [("lineage", "count"), ("lineage", "nunique"), ("lineage", "mode"), ("run", "mode")]


#: Significant digits kept for every float in the payload. Variance, std_dev
#: and skewness are order-of-summation sensitive, so polars returns them
#: differing in the last bits from one machine to the next — the committed
#: golden then fails CI's byte-exact drift check even though nothing changed.
#: The test compares numbers with a 1e-9 relative tolerance, so rounding at
#: ~5e-13 relative loses nothing it can observe while making the file
#: reproducible. Do not lower this below the test's tolerance.
_SIGNIFICANT_DIGITS = 12


def _json_safe(value):
    """NaN / Inf have no JSON spelling, and a payload carrying one is a bug the
    test should see as such rather than as an unparseable file. Floats are
    rounded so the emitted JSON is byte-identical across machines."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(f"{value:.{_SIGNIFICANT_DIGITS}g}")
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def main() -> int:
    # `try_parse_dates` is what the catalog fixture loader uses, so `day` is a
    # real Datetime here exactly as it is when depictio reads the committed
    # fixture — which is what makes `trend`'s temporal branch the one under test.
    df = pl.read_csv(FIXTURE, try_parse_dates=True)

    layouts = {}
    for case in LAYOUT_CASES:
        layouts[case["name"]] = numeric_layout_payload(
            df, case["card"], case["column"], case["layout"]
        )

    breakdowns = {}
    for case in BREAKDOWN_CASES:
        breakdowns[case["name"]] = compute_breakdown(
            df,
            column=case["column"],
            breakdown_col=case["breakdown_col"],
            aggregation=case["aggregation"],
            top_n_count=case["top_n_count"],
        )

    aggregations = {}
    for column, agg in AGG_CASES:
        value = df.select(AGG_EXPRS[agg](pl.col(column)).alias("v")).item()
        if agg in ("count", "nunique"):
            value = int(value) if value is not None else None
        elif agg in ("min", "max", "mode"):
            value = float(value) if isinstance(value, (int, float)) else (
                str(value) if value is not None else None
            )
        elif value is not None:
            value = float(value) if isinstance(value, (int, float)) else None
        aggregations[f"{column}::{agg}"] = value

    print(
        json.dumps(
            _json_safe(
                {
                    "fixture": FIXTURE.name,
                    "layout_cases": LAYOUT_CASES,
                    "layouts": layouts,
                    "breakdown_cases": BREAKDOWN_CASES,
                    "breakdowns": breakdowns,
                    "aggregations": aggregations,
                }
            ),
            indent=2,
            sort_keys=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
