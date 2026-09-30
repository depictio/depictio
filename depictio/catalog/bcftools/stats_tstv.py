"""Per-sample, per-caller transition/transversion ratio from `bcftools stats`.

Same raw `raw_line`-per-row block as `stats_summary.py` (see that file for
the row-width rationale and how sample/caller are recovered), reading the `TSTV`
record instead of `SN`:
`TSTV 0 <ts> <tv> <ts/tv> <ts 1st ALT> <tv 1st ALT> <ts/tv 1st ALT>`.

A caller that calls no SNPs at all (sarek's `manta`, an SV caller, calls a
handful of small indels and no SNPs) writes `ts=0 tv=0 ts/tv=0.0` here, which
reads as "no signal" rather than "poor signal", the dashboard's Ts/Tv panel
notes this rather than filtering manta out, so a caller with zero variance
called is still visible as zero rather than silently absent.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bcftools_stats import sample_and_caller

RAW_DC_TAG = "bcftools_stats_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "ts": pl.Int64,
    "tv": pl.Int64,
    "ts_tv": pl.Float64,
    "ts_1st_alt": pl.Int64,
    "tv_1st_alt": pl.Int64,
    "ts_tv_1st_alt": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample x caller, read off the file's single `TSTV` line."""
    df = sources["raw"]

    out = (
        df.filter(pl.col("raw_line").str.starts_with("TSTV\t"))
        .with_columns(pl.col("raw_line").str.split("\t").alias("fields"))
        .join(sample_and_caller(df), on="source_path", how="left")
        .with_columns(
            pl.col("fields").list.get(2).cast(pl.Int64, strict=False).alias("ts"),
            pl.col("fields").list.get(3).cast(pl.Int64, strict=False).alias("tv"),
            pl.col("fields").list.get(4).cast(pl.Float64, strict=False).alias("ts_tv"),
            pl.col("fields").list.get(5).cast(pl.Int64, strict=False).alias("ts_1st_alt"),
            pl.col("fields").list.get(6).cast(pl.Int64, strict=False).alias("tv_1st_alt"),
            pl.col("fields").list.get(7).cast(pl.Float64, strict=False).alias("ts_tv_1st_alt"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "caller"])
    )

    return out
