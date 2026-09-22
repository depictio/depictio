"""How a caller's own FILTER column partitions its calls.

``vcftools --FILTER-summary`` writes one row per FILTER value with the number
of variants carrying it and their transition/transversion split. Reading it per
caller is the only place a dashboard can say what a caller threw away and what
its hard filters cost in Ts/Tv, which the pooled MultiQC panel cannot show.

Sample and caller come off the file NAME (``<sample>.<caller>...``), the only
place that survives the layouts these reports are published under.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import finite_float, sample_and_caller

RAW_DC_TAG = "vcftools_filter_summary_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "filter_label": pl.Utf8,
    "n_variants": pl.Int64,
    "n_ts": pl.Int64,
    "n_tv": pl.Int64,
    "ts_tv": pl.Float64,
    "is_pass": pl.Boolean,
    "pct_of_calls": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample, caller and FILTER value."""
    raw = sources["raw"]
    df = raw.join(sample_and_caller(raw), on="source_path", how="left").with_columns(
        pl.col("FILTER").cast(pl.Utf8).alias("filter_label"),
        pl.col("N_VARIANTS").cast(pl.Int64, strict=False).alias("n_variants"),
        pl.col("N_Ts").cast(pl.Int64, strict=False).alias("n_ts"),
        pl.col("N_Tv").cast(pl.Int64, strict=False).alias("n_tv"),
        finite_float("Ts/Tv").alias("ts_tv"),
    )

    df = df.with_columns(
        (pl.col("filter_label") == "PASS").alias("is_pass"),
        (
            100.0
            * pl.col("n_variants")
            / pl.col("n_variants").sum().over(["sample", "caller"]).cast(pl.Float64)
        ).alias("pct_of_calls"),
    )

    return df.select(list(EXPECTED_SCHEMA)).sort(
        ["sample", "caller", "n_variants"], descending=[False, False, True]
    )
