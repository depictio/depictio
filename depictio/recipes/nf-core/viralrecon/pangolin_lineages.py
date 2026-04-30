"""Extract and clean Pangolin lineage assignments from viralrecon output."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pangolin_raw",
        glob_pattern="variants/ivar/consensus/bcftools/pangolin/*.pangolin.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "lineage": pl.Utf8,
    "conflict": pl.Float64,
    "ambiguity_score": pl.Float64,
    "scorpio_call": pl.Utf8,
    "scorpio_support": pl.Float64,
    "pangolin_version": pl.Utf8,
    "qc_status": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Clean Pangolin CSV: extract sample name from taxon, cast types."""
    df = sources["pangolin_raw"]

    # The 'taxon' column contains sample names (consensus FASTA headers)
    # Extract clean sample name: strip reference genome suffix and consensus suffixes
    if "taxon" in df.columns:
        df = df.with_columns(
            pl.col("taxon")
            .str.replace(r"\s+.*$", "")
            .str.replace(r"\.consensus.*$", "")
            .str.replace(r"\.primertrimmed.*$", "")
            .alias("sample")
        )
    elif "Taxon" in df.columns:
        df = df.with_columns(
            pl.col("Taxon")
            .str.replace(r"\s+.*$", "")
            .str.replace(r"\.consensus.*$", "")
            .str.replace(r"\.primertrimmed.*$", "")
            .alias("sample")
        )

    # Handle version column name variations
    if "version" in df.columns and "pangolin_version" not in df.columns:
        df = df.rename({"version": "pangolin_version"})

    # Cast numeric columns
    for col_name in ("conflict", "ambiguity_score", "scorpio_support", "scorpio_conflict"):
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).cast(pl.Float64, strict=False))

    # Fill null string columns
    str_cols = [
        "lineage",
        "scorpio_call",
        "scorpio_notes",
        "pangolin_version",
        "status",
        "note",
        "qc_status",
    ]
    for col_name in str_cols:
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).fill_null(""))

    # Select available columns
    keep_cols = [
        "sample",
        "lineage",
        "conflict",
        "ambiguity_score",
        "scorpio_call",
        "scorpio_support",
        "scorpio_conflict",
        "scorpio_notes",
        "pangolin_version",
        "status",
        "note",
        "qc_status",
    ]
    available = [c for c in keep_cols if c in df.columns]
    return df.select(available)
