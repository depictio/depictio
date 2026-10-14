"""Indel position profile around the cut site per guide: mean library and interquartile band.

At every offset of the profile window, the mean, median, first and third
quartile over each guide's libraries of the share of reads whose deletion covers
the position and of the share with an insertion starting there. A library
without an indel at an offset counts as zero. The per-library profiles are
derived from the indel alleles (``crisprseq_indels``) in process, so no table
with one row per library and offset is shipped.

The dashboard draws the mean with the band from the first to the third
quartile. At most offsets most libraries carry no indel, so the median sits on
zero even where part of the libraries carry one; the mean keeps that part
visible, and a mean above its band says the offset belongs to a minority of the
libraries.

Output:
    guide : Utf8                       protospacer
    offset : Int64                     position minus the cut site, bp
    mean_deletion_pct : Float64        mean share of reads with a deletion covering it
    median_deletion_pct : Float64      its median over the guide's libraries
    q1_deletion_pct, q3_deletion_pct   its first and third quartile
    mean_insertion_pct : Float64       mean share of reads with an insertion starting there
    median_insertion_pct : Float64     its median over the guide's libraries
    q1_insertion_pct, q3_insertion_pct its first and third quartile
    libraries_with_signal : Int64      libraries with an indel at that offset
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import (
    PROFILE_WINDOW,
    SAMPLES_INPUT_SCHEMA,
    SUMMARY_INPUT_SCHEMA,
    cut_site_per_library,
    guide_stats,
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
            "indel_type": pl.Utf8,
            "offset": pl.Int64,
            "length": pl.Int64,
            "pct_reads": pl.Float64,
        },
    ),
]

_VALUES = ["deletion_pct", "insertion_pct"]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "guide": pl.Utf8,
    "offset": pl.Int64,
    **{f"{s}_{v}": pl.Float64 for v in _VALUES for s in ("mean", "median", "q1", "q3")},
    "libraries_with_signal": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    libs = library_guides(sources["samples"], sources["summary"])
    profile = cut_site_per_library(sources["indels"])
    offsets = pl.DataFrame(
        {"offset": list(range(-PROFILE_WINDOW, PROFILE_WINDOW + 1))}, schema={"offset": pl.Int64}
    )
    keys = libs.select("guide").unique().join(offsets, how="cross")
    out = guide_stats(profile, libs, "offset", _VALUES, fill_zero=True, keys=keys)
    return out.select(list(OUTPUT_SCHEMA))
