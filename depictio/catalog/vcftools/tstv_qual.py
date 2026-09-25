"""Transition/transversion ratio as a function of the quality floor.

``vcftools --TsTv-by-qual`` sweeps the QUAL threshold and reports, at every
step, the Ts/Tv of the calls above it. A germline callset's curve climbs toward
the expected exome ratio as the floor rises: where it flattens is where the
caller's quality score stops separating real variants from noise, which is the
one plot that compares callers on calibration rather than on yield.

The sweep has one step per distinct QUAL in the callset (about 10 000 rows per
file here), so the recipe decimates to at most ``MAX_POINTS`` evenly spaced
steps per series, always keeping the first and the last: a profile is never
sampled downstream, so a recipe that hands over 100 000 points ships 100 000
points to the browser.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import finite_float, sample_and_caller

RAW_DC_TAG = "vcftools_tstv_qual_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

#: Points kept per series. The curve is smooth; 200 steps redraw it exactly.
MAX_POINTS = 200

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "series": pl.Utf8,
    "qual_threshold": pl.Float64,
    "n_ts_above": pl.Int64,
    "n_tv_above": pl.Int64,
    "ts_tv_above": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One decimated Ts/Tv-by-quality curve per sample and caller."""
    raw = sources["raw"]
    df = (
        raw.join(sample_and_caller(raw), on="source_path", how="left")
        .with_columns(
            pl.col("QUAL_THRESHOLD").cast(pl.Float64, strict=False).alias("qual_threshold"),
            pl.col("N_Ts_GT_QUAL_THRESHOLD").cast(pl.Int64, strict=False).alias("n_ts_above"),
            pl.col("N_Tv_GT_QUAL_THRESHOLD").cast(pl.Int64, strict=False).alias("n_tv_above"),
            finite_float("Ts/Tv_GT_QUAL_THRESHOLD").alias("ts_tv_above"),
        )
        .filter(pl.col("qual_threshold").is_not_null())
        .with_columns(
            pl.concat_str([pl.col("sample"), pl.col("caller")], separator=" / ").alias("series")
        )
        .sort(["series", "qual_threshold"])
    )

    # Evenly spaced on the step rank, first and last always kept.
    stride = (pl.len().over("series") // MAX_POINTS).clip(lower_bound=1)
    rank = pl.int_range(pl.len()).over("series")
    df = df.filter((rank % stride == 0) | (rank == 0) | (rank == pl.len().over("series") - 1))

    return df.select(list(EXPECTED_SCHEMA)).sort(["series", "qual_threshold"])
