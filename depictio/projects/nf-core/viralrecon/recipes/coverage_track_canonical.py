"""Canonical-schema Coverage Track DC for viralrecon.

Consumes the existing ``mosdepth_genome_coverage`` DC and renames its columns
to the canonical coverage_track roles:

    chromosome : Utf8
    position : Int64
    value : Float64        -- coverage depth

Optional roles:
    end : Int64    -- window end (mosdepth emits 200bp bins)
    sample : Utf8  -- per-sample faceting
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="coverage", dc_ref="mosdepth_genome_coverage"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chromosome": pl.Utf8,
    "position": pl.Int64,
    "value": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "end": pl.Int64,
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename mosdepth columns to canonical coverage_track roles."""
    df = sources["coverage"]

    rename_map = {"chrom": "chromosome", "start": "position", "coverage": "value"}
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})

    df = df.with_columns(
        pl.col("chromosome").cast(pl.Utf8),
        pl.col("position").cast(pl.Int64, strict=False),
        pl.col("value").cast(pl.Float64, strict=False),
    )
    if "end" in df.columns:
        df = df.with_columns(pl.col("end").cast(pl.Int64, strict=False))
    if "sample" in df.columns:
        df = df.with_columns(pl.col("sample").cast(pl.Utf8))

    keep = [c for c in ("chromosome", "position", "value", "end", "sample") if c in df.columns]
    return df.select(keep)
