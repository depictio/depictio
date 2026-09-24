"""miRNA complexity curves: distinct miRNAs found against reads sequenced.

miRTrace subsamples each library and counts the distinct miRNAs detected at
each depth. A curve that has flattened says deeper sequencing would add few new
miRNAs; one still climbing at the library's full depth says the library was
sequenced short of its complexity. Low-complexity libraries (few miRNAs making
up most reads) flatten early and low.

Curves are decimated to at most ``MAX_POINTS`` points per library, keeping the
first and last, which is ample for a line and keeps the frame small.

Source: the run's ``multiqc_data/multiqc.parquet`` (plot ``mirtrace_complexity_plot``).

Output schema:
    sample : Utf8
    reads : Float64            reads sampled
    distinct_mirnas : Float64  distinct miRNAs detected at that depth
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="report",
        glob_pattern="**/*_data/multiqc.parquet",
        format="parquet",
        read_kwargs={"columns": ["anchor", "type", "plot_input_data"]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "reads": pl.Float64,
    "distinct_mirnas": pl.Float64,
}

ANCHOR = "mirtrace_complexity_plot"
MAX_POINTS = 200


def _decimate(pairs: list, limit: int) -> list:
    if len(pairs) <= limit:
        return pairs
    step = (len(pairs) - 1) / (limit - 1)
    return [pairs[round(i * step)] for i in range(limit)]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, sampled depth)."""
    report = sources["report"]
    rows = report.filter((pl.col("anchor") == ANCHOR) & (pl.col("type") == "plot_input"))
    if rows.is_empty() or rows["plot_input_data"][0] is None:
        raise ValueError("mirtrace_complexity: no miRTrace complexity plot in the report")
    data = json.loads(rows["plot_input_data"][0]).get("data") or [[]]
    records = []
    for s in data[0]:
        pairs = [
            p
            for p in s.get("pairs") or []
            if isinstance(p[0], (int, float)) and isinstance(p[1], (int, float))
        ]
        for x, y in _decimate(pairs, MAX_POINTS):
            records.append(
                {"sample": str(s["name"]), "reads": float(x), "distinct_mirnas": float(y)}
            )
    if not records:
        raise ValueError("mirtrace_complexity: the complexity plot has no points")
    return pl.DataFrame(records, schema=EXPECTED_SCHEMA).sort(["sample", "reads"])
