"""Edit outcome composition per guide.

Pools the per-library outcome counts (``crisprseq_edit_outcomes``) of each
guide's libraries and expresses every class as a share of the guide's
classified reads: one stacked bar per guide. Pooling reads (rather than
averaging library shares) weights each library by its depth, which is what a
composition bar of the guide's reads should show.

Output:
    guide : Utf8       protospacer
    outcome : Utf8     outcome class
    level : Utf8       constant "Outcome", the composition bar's rank
    reads : Int64      reads in the class over the guide's libraries
    pct : Float64      share of the guide's classified reads, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import (
    SAMPLES_INPUT_SCHEMA,
    SUMMARY_INPUT_SCHEMA,
    library_guides,
    rounded,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples", input_schema=SAMPLES_INPUT_SCHEMA),
    RecipeSource(ref="summary", dc_ref="crisprseq_edit_summary", input_schema=SUMMARY_INPUT_SCHEMA),
    RecipeSource(
        ref="outcomes",
        dc_ref="crisprseq_edit_outcomes",
        input_schema={"sample": pl.Utf8, "outcome": pl.Utf8, "reads": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "guide": pl.Utf8,
    "outcome": pl.Utf8,
    "level": pl.Utf8,
    "reads": pl.Int64,
    "pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    libs = library_guides(sources["samples"], sources["summary"])
    out = (
        sources["outcomes"]
        .join(libs.select("sample", "guide"), on="sample", how="inner")
        .group_by("guide", "outcome")
        .agg(pl.col("reads").sum().cast(pl.Int64))
    )
    total = pl.col("reads").sum().over("guide")
    return (
        out.with_columns(
            pl.lit("Outcome").alias("level"),
            pl.when(total > 0).then(pl.col("reads") * 100.0 / total).otherwise(0.0).alias("pct"),
        )
        .with_columns(rounded("pct"))
        .sort("guide", "outcome")
        .select(list(OUTPUT_SCHEMA))
    )
