"""How far transcription has moved at each time point, as two curves over time.

The time course read as one line per comparison, from ``sample_similarity``:
the Spearman correlation of each time point with the baseline (how far the
program has moved from where it started) and with the previous time point (how
much it moved in that step). Libraries of one time point are averaged. The
baseline's own point is 1 against itself and has no previous one.

Sources:
    similarity  ``sample_similarity``

Output schema:
    comparison, time_point : Utf8
    time_h : Float64, time_order : Int64, time_axis : Float64
    correlation : Float64
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="similarity",
        dc_ref="sample_similarity",
        input_schema={
            "sample": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "corr_to_baseline": pl.Float64,
            "corr_to_previous": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "comparison": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "correlation": pl.Float64,
}

#: Curve labels, as the legend prints them.
COMPARISONS = {
    "corr_to_baseline": "Against the baseline",
    "corr_to_previous": "Against the previous time point",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    timed = sources["similarity"].filter(pl.col("time_order").is_not_null())
    long = timed.unpivot(
        index=["time_point", "time_h", "time_order", "time_axis"],
        on=list(COMPARISONS),
        variable_name="comparison",
        value_name="correlation",
    ).with_columns(pl.col("comparison").replace_strict(COMPARISONS, return_dtype=pl.Utf8))
    return (
        long.drop_nulls("correlation")
        .group_by("comparison", "time_point", "time_h", "time_order", "time_axis")
        .agg(pl.col("correlation").mean())
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["comparison", "time_order"])
    )
