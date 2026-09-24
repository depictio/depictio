"""One row per miRNA: how much, how widely and how variably it is expressed.

The per-miRNA record behind the expression tab: mean and median CPM, the
spread of log2(CPM + 1) across samples, how many samples detect it, how many
distinct isomiRs carry its reads and what share of them match the reference
sequence exactly. Plotted as mean against spread it is the mean-variance plane
where the miRNAs worth a closer look (well expressed and variable) sit in one
corner; read as a record it is the card for the miRNA picked there.

The arm (5p or 3p) is read from the miRBase name suffix; names without one
(older single-arm entries) get null.

Source: the ``mirtop_mirna_counts`` collection (``mirtop/mirna_counts.py``).

Output schema:
    mirna : Utf8
    arm : Utf8                  5p | 3p, from the name
    expression_rank : Int64     1 = highest mean CPM
    total_reads : Int64         reads over all samples
    mean_cpm : Float64
    median_cpm : Float64
    mean_log2_cpm : Float64
    sd_log2_cpm : Float64       spread of log2(CPM + 1) across samples
    samples_detected : Int64    samples with at least one read
    detection_pct : Float64     of all samples, %
    max_isomirs : Int64         most distinct isomiRs seen in one sample
    reference_pct : Float64     reads matching the reference sequence, over all samples, %
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="counts", dc_ref="mirtop_mirna_counts"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "mirna": pl.Utf8,
    "arm": pl.Utf8,
    "expression_rank": pl.Int64,
    "total_reads": pl.Int64,
    "mean_cpm": pl.Float64,
    "median_cpm": pl.Float64,
    "mean_log2_cpm": pl.Float64,
    "sd_log2_cpm": pl.Float64,
    "samples_detected": pl.Int64,
    "detection_pct": pl.Float64,
    "max_isomirs": pl.Int64,
    "reference_pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Aggregate the per-sample counts to one row per miRNA."""
    counts = sources["counts"]
    n_samples = max(counts["sample"].n_unique(), 1)
    ref_reads = pl.col("reference_pct").fill_null(0.0) * pl.col("reads") / 100.0
    out = counts.group_by("mirna").agg(
        pl.col("reads").sum().cast(pl.Int64).alias("total_reads"),
        pl.col("cpm").mean().alias("mean_cpm"),
        pl.col("cpm").median().alias("median_cpm"),
        pl.col("log2_cpm").mean().alias("mean_log2_cpm"),
        pl.col("log2_cpm").std().fill_null(0.0).alias("sd_log2_cpm"),
        (pl.col("reads") > 0).sum().cast(pl.Int64).alias("samples_detected"),
        pl.col("isomirs").max().cast(pl.Int64).alias("max_isomirs"),
        ref_reads.sum().alias("_ref"),
    )
    out = out.with_columns(
        pl.col("mirna").str.extract(r"-(5p|3p)$", 1).alias("arm"),
        (pl.col("samples_detected") * 100.0 / n_samples).alias("detection_pct"),
        pl.when(pl.col("total_reads") > 0)
        .then(pl.col("_ref") * 100.0 / pl.col("total_reads"))
        .otherwise(None)
        .alias("reference_pct"),
    ).sort(["mean_cpm", "mirna"], descending=[True, False])
    out = out.with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("expression_rank"))
    return out.with_columns([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()]).select(
        list(EXPECTED_SCHEMA)
    )
