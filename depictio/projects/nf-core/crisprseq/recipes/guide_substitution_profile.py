"""Substitution and gap rate around the cut site per guide: mean library and interquartile band.

Reads the CIGAR parser's per-position base percentages (``*_subs-perc.csv``)
and cut sites (``*_cutSite.json``), derives each library's substitution and
gap rate per offset (see ``substitutions_per_library``) and summarises them per
guide: the mean, median, first and third quartile over the guide's libraries.
The mean is the curve the dashboard draws: at most positions most libraries
carry no substitution at all, so the median sits on zero even where part of the
libraries carry an edit. Only libraries whose amplicon reaches an offset count
there (a position outside the amplicon is not a zero rate), and an offset
reached by fewer than :data:`MIN_COVERAGE` of the guide's libraries is left out:
the amplicon ends that only some libraries reach are alignment edges, where the
gap rate climbs towards 100% without any edit. One row per guide and offset
instead of one per library and position, which on a large run is over a million
rows no view can show.

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
    guide_quartiles,
    library_guides,
    rounded,
    substitutions_per_library,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples"),
    RecipeSource(ref="summary", dc_ref="crisprseq_edit_summary"),
    RecipeSource(
        ref="subs",
        glob_pattern="**/*_subs-perc.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", ""]},
        source_path="source_path",
    ),
    RecipeSource(
        ref="cut",
        glob_pattern="**/*_cutSite.json",
        format="csv",
        read_kwargs={"has_header": False, "new_columns": ["cut_site"], "infer_schema_length": 0},
        source_path="source_path",
    ),
]

# Share of a guide's libraries that must reach an offset for it to be reported.
# On the reference run the offsets below it are the amplicon ends, where the
# libraries that do reach them show a gap in most reads (mean gap rate near 50%
# against about 5% where every library aligns).
MIN_COVERAGE = 0.9

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
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
    quartiles = guide_quartiles(per_lib, libs, "offset", values, fill_zero=False).rename(
        {"libraries_with_signal": "libraries"}
    )
    joined = per_lib.join(libs.select("sample", "guide"), on="sample", how="inner")
    means = (
        joined.group_by("guide", "offset")
        .agg(*[pl.col(v).mean().cast(pl.Float64).alias(f"mean_{v}") for v in values])
        .with_columns(rounded(*[f"mean_{v}" for v in values]))
    )
    reached = joined.group_by("guide").agg(pl.col("sample").n_unique().alias("_libraries"))
    return (
        quartiles.join(means, on=["guide", "offset"], how="left")
        .join(reached, on="guide", how="inner")
        .filter(pl.col("libraries") >= MIN_COVERAGE * pl.col("_libraries"))
        .rename({"guide": "profile_guide"})
        .select(list(EXPECTED_SCHEMA))
        .sort("profile_guide", "offset")
    )
