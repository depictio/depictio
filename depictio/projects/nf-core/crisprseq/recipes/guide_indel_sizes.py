"""Indel size distribution per guide: the mean library with its interquartile band.

For every signed indel size, the mean, median, first and third quartile over
each guide's libraries of the share of classified reads carrying an indel of
that size. A library without an indel of that size counts as zero, and every
size between the smallest and largest seen for the guide gets a row, so the
curve drops to zero instead of jumping over gaps. One curve per guide replaces
one curve per library: a run has thousands of libraries and a guide's signature
is what they share.

The dashboard draws the mean with the band from the first to the third
quartile. At most sizes most libraries carry no such indel, so the median sits
on zero even where part of the libraries carry one; the mean keeps that part
visible, and a mean above its band says the size belongs to a minority of the
libraries.

The per-library sizes are summed from the indel alleles
(``crisprseq_indels``) in process rather than read from a per-library table.

Output:
    guide : Utf8                    protospacer
    size : Int64                    signed indel size, bp (insertions positive)
    mean_pct_reads : Float64        mean share of classified reads, percent
    median_pct_reads : Float64      median share of classified reads, percent
    q1_pct_reads : Float64          first quartile over the guide's libraries
    q3_pct_reads : Float64          third quartile over the guide's libraries
    libraries_with_signal : Int64   libraries with an indel of that size
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import (
    SAMPLES_INPUT_SCHEMA,
    SUMMARY_INPUT_SCHEMA,
    guide_stats,
    indel_sizes_per_library,
    library_guides,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples", input_schema=SAMPLES_INPUT_SCHEMA),
    RecipeSource(ref="summary", dc_ref="crisprseq_edit_summary", input_schema=SUMMARY_INPUT_SCHEMA),
    RecipeSource(
        ref="indels",
        dc_ref="crisprseq_indels",
        input_schema={
            "sample": pl.Utf8,
            "size": pl.Int64,
            "reads": pl.Int64,
            "pct_reads": pl.Float64,
            "pct_indel_reads": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "guide": pl.Utf8,
    "size": pl.Int64,
    "mean_pct_reads": pl.Float64,
    "median_pct_reads": pl.Float64,
    "q1_pct_reads": pl.Float64,
    "q3_pct_reads": pl.Float64,
    "libraries_with_signal": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    libs = library_guides(sources["samples"], sources["summary"])
    sizes = indel_sizes_per_library(sources["indels"])
    seen = sizes.join(libs.select("sample", "guide"), on="sample", how="inner")
    keys = (
        seen.group_by("guide")
        .agg(pl.int_ranges(pl.col("size").min(), pl.col("size").max() + 1).first().alias("size"))
        .explode("size")
        .with_columns(pl.col("size").cast(pl.Int64))
    )
    out = guide_stats(sizes, libs, "size", ["pct_reads"], fill_zero=True, keys=keys)
    return out.select(list(OUTPUT_SCHEMA))
