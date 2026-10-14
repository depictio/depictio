"""Substitution and gap rate around the cut site per guide: mean library and interquartile band.

Reads the CIGAR parser's per-position base percentages (``*_subs-perc.csv``)
and cut sites (``*_cutSite.json``), derives each library's substitution and
gap rate per offset (see ``substitutions_per_library``) and summarises them per
guide: the mean, median, first and third quartile over the guide's libraries.
The mean is the curve the dashboard draws, with the band from the first to the
third quartile: at most positions most libraries carry no substitution at all,
so the median sits on zero even where part of the libraries carry an edit. Only
libraries whose amplicon reaches an offset count there (a position outside the
amplicon is not a zero rate), and an offset reached by fewer than
:data:`MIN_COVERAGE` of the guide's libraries is left out: the amplicon ends
that only some libraries reach are alignment edges, where the gap rate climbs
towards 100% without any edit. One row per guide and offset instead of one per
library and position, which on a large run is over a million rows no view can
show.

The guide column is ``profile_guide``, not ``guide``: a dashboard filter also
applies to every collection with a column of the same name, so a guide picker
on this collection would otherwise narrow the guide-by-offset heatmap and the
samplesheet as well. The samplesheet link still reaches it through
``target_field``.

Output:
    profile_guide : Utf8                     protospacer
    offset : Int64                           position minus the cut site, bp
    mean_substitution_pct : Float64          mean share of reads with another base
    median_substitution_pct : Float64        its median over the guide's libraries
    q1_substitution_pct, q3_substitution_pct its first and third quartile
    mean_gap_pct : Float64                   mean share of reads with a gap
    median_gap_pct : Float64                 its median
    q1_gap_pct, q3_gap_pct                   its first and third quartile
    libraries : Int64                        libraries with a value at the offset
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import (
    SAMPLES_INPUT_SCHEMA,
    SUMMARY_INPUT_SCHEMA,
    TEXT_READ_KWARGS,
    guide_stats,
    library_guides,
    substitutions_per_library,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples", input_schema=SAMPLES_INPUT_SCHEMA),
    RecipeSource(ref="summary", dc_ref="crisprseq_edit_summary", input_schema=SUMMARY_INPUT_SCHEMA),
    RecipeSource(
        ref="subs",
        glob_pattern="**/*_subs-perc.csv",
        format="csv",
        read_kwargs=TEXT_READ_KWARGS,
        source_path="source_path",
        input_schema={
            "pos": pl.Utf8,
            "percentage": pl.Utf8,
            "nucleotide": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
    # The cut site file is a one-element JSON list, read as a headerless csv of one column.
    RecipeSource(
        ref="cut",
        glob_pattern="**/*_cutSite.json",
        format="csv",
        read_kwargs={"has_header": False, "new_columns": ["cut_site"], "infer_schema_length": 0},
        source_path="source_path",
        input_schema={"cut_site": pl.Utf8, "source_path": pl.Utf8},
    ),
]

# Share of a guide's libraries that must reach an offset for it to be reported.
# On the reference run the offsets below it are the amplicon ends, where the
# libraries that do reach them show a gap in most reads (mean gap rate near 50%
# against about 5% where every library aligns).
MIN_COVERAGE = 0.9

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "profile_guide": pl.Utf8,
    "offset": pl.Int64,
    "mean_substitution_pct": pl.Float64,
    "median_substitution_pct": pl.Float64,
    "q1_substitution_pct": pl.Float64,
    "q3_substitution_pct": pl.Float64,
    "mean_gap_pct": pl.Float64,
    "median_gap_pct": pl.Float64,
    "q1_gap_pct": pl.Float64,
    "q3_gap_pct": pl.Float64,
    "libraries": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    libs = library_guides(sources["samples"], sources["summary"])
    per_lib = substitutions_per_library(sources["subs"], sources["cut"])
    values = ["substitution_pct", "gap_pct"]
    stats = guide_stats(per_lib, libs, "offset", values, fill_zero=False).rename(
        {"libraries_with_signal": "libraries"}
    )
    reached = (
        per_lib.join(libs.select("sample", "guide"), on="sample", how="inner")
        .group_by("guide")
        .agg(pl.col("sample").n_unique().alias("_libraries"))
    )
    return (
        stats.join(reached, on="guide", how="inner")
        .filter(pl.col("libraries") >= MIN_COVERAGE * pl.col("_libraries"))
        .rename({"guide": "profile_guide"})
        .select(list(OUTPUT_SCHEMA))
        .sort("profile_guide", "offset")
    )
