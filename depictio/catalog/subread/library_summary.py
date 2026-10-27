"""Per-library depth and complexity from a featureCounts count matrix.

What the count matrix alone says about each library, for a run that publishes
it without the ``.summary`` file MultiQC reads: how many reads were counted over
features, how many features reached a usable count, and how much of the library
the most expressed features take. A library whose top 100 features hold most of
its reads (rRNA, a handful of very highly transcribed loci) is a narrow library:
its other features are counted from what is left.

Reads the long table of ``subread_gene_counts`` through ``dc_ref``, so the
matrix is parsed once per run.

Output schema:
    sample : Utf8                 library
    assigned_reads : Int64        reads counted over any feature
    genes_detected : Int64        features with at least ``MIN_COUNTS`` reads
    genes_detected_pct : Float64  those features, in percent of every feature with a read in any library
    top100_share_pct : Float64    reads on the library's 100 most counted features, in percent of its reads
    median_log2_cpm : Float64     median log2(cpm + 1) over the detected features
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "subread_gene_counts"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        dc_ref=RAW_DC_TAG,
        input_schema={
            "gene_id": pl.Utf8,
            "sample": pl.Utf8,
            "counts": pl.Int64,
            "log2_cpm": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "assigned_reads": pl.Int64,
    "genes_detected": pl.Int64,
    "genes_detected_pct": pl.Float64,
    "top100_share_pct": pl.Float64,
    "median_log2_cpm": pl.Float64,
}

#: Reads a feature needs in a library to count as detected there. Ten reads is
#: the usual floor below which a count is Poisson noise around zero.
MIN_COUNTS = 10
#: How many of the most counted features the concentration share sums.
TOP_FEATURES = 100


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    counts = sources["counts"]
    if counts.is_empty():
        raise ValueError("subread_library_summary: the count table is empty")
    n_features = counts.get_column("gene_id").n_unique()
    ranked = counts.with_columns(
        pl.col("counts").rank(method="ordinal", descending=True).over("sample").alias("_rank")
    )
    total = pl.col("counts").sum()
    return (
        ranked.group_by("sample")
        .agg(
            total.cast(pl.Int64).alias("assigned_reads"),
            (pl.col("counts") >= MIN_COUNTS).sum().cast(pl.Int64).alias("genes_detected"),
            (
                pl.col("counts").filter(pl.col("_rank") <= TOP_FEATURES).sum()
                / total.cast(pl.Float64).replace(0.0, None)
                * 100
            ).alias("top100_share_pct"),
            pl.col("log2_cpm")
            .filter(pl.col("counts") >= MIN_COUNTS)
            .median()
            .alias("median_log2_cpm"),
        )
        .with_columns(
            (pl.col("genes_detected") / max(1, n_features) * 100).alias("genes_detected_pct"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort("sample")
    )
