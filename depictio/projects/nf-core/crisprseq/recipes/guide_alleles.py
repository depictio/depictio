"""The indel alleles of each guide, pooled over its libraries.

Groups the per-library alleles of ``crisprseq_indels`` by guide and by type,
length and offset from the cut site (the offset, not the amplicon start, so
libraries of one guide on different amplicons line up), and keeps for each:
how many of the guide's libraries carry it, its reads pooled over them and
their share of the guide's classified reads, and its median share in the
libraries that carry it. Only the most frequent ``ALLELES_PER_GUIDE`` alleles
of a guide are kept: on the reference run they hold a median of 94% of a
guide's indel reads, and the long tail of single-read alleles is what turns a
per-library allele table into a million rows.

Output:
    guide : Utf8               protospacer
    allele : Utf8              type, length and offset from the cut site
    libraries : Int64          libraries of the guide carrying the allele
    pct_reads : Float64        pooled share of the guide's classified reads, percent
    reads : Int64              reads pooled over the guide's libraries
    indel_type : Utf8          Deletion, Insertion or Deletion-insertion
    size : Int64               signed size, bp (insertions positive)
    offset : Int64             start minus the cut site, bp
    frame : Utf8               In-frame or Frameshift
    peak : Utf8                Main peak when in the main indel peak of at least
                               half the libraries carrying it
    median_pct_reads : Float64 median share of classified reads in those libraries
    rank : Int64               rank of the allele in the guide by pooled reads
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import library_guides, rounded

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples"),
    RecipeSource(ref="summary", dc_ref="crisprseq_edit_summary"),
    RecipeSource(ref="indels", dc_ref="crisprseq_indels"),
]

ALLELES_PER_GUIDE = 200

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "guide": pl.Utf8,
    "allele": pl.Utf8,
    "libraries": pl.Int64,
    "pct_reads": pl.Float64,
    "reads": pl.Int64,
    "indel_type": pl.Utf8,
    "size": pl.Int64,
    "offset": pl.Int64,
    "frame": pl.Utf8,
    "peak": pl.Utf8,
    "median_pct_reads": pl.Float64,
    "rank": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    summary = sources["summary"]
    libs = library_guides(sources["samples"], summary)
    classified = (
        summary.join(libs.select("sample", "guide"), on="sample", how="inner")
        .group_by("guide")
        .agg(pl.col("classified_reads").sum().alias("_classified"))
    )
    alleles = (
        sources["indels"]
        .join(libs.select("sample", "guide"), on="sample", how="inner")
        .group_by("guide", "allele", "indel_type", "size", "offset", "frame")
        .agg(
            pl.col("sample").n_unique().cast(pl.Int64).alias("libraries"),
            pl.col("reads").sum().cast(pl.Int64),
            (pl.col("peak") == "Main peak").mean().alias("_in_peak"),
            pl.col("pct_reads").median().cast(pl.Float64).alias("median_pct_reads"),
        )
        .sort(["guide", "reads", "allele"], descending=[False, True, False])
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).over("guide").alias("rank"))
        .filter(pl.col("rank") <= ALLELES_PER_GUIDE)
        .join(classified, on="guide", how="left")
    )
    return (
        alleles.with_columns(
            pl.when(pl.col("_classified") > 0)
            .then(pl.col("reads") * 100.0 / pl.col("_classified"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("pct_reads"),
            pl.when(pl.col("_in_peak") >= 0.5)
            .then(pl.lit("Main peak"))
            .otherwise(pl.lit("Outside the main peak"))
            .alias("peak"),
        )
        .with_columns(rounded("pct_reads", "median_pct_reads"))
        .select(list(EXPECTED_SCHEMA))
        .sort("guide", "rank")
    )
