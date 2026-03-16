"""Extract and clean Nextclade clade assignment results from viralrecon output."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="nextclade_raw",
        glob_pattern="variants/ivar/consensus/bcftools/nextclade/*.csv",
        format="CSV",
        read_kwargs={"separator": ";"},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "clade": pl.Utf8,
    "Nextclade_pango": pl.Utf8,
    "totalSubstitutions": pl.Int64,
    "totalDeletions": pl.Int64,
    "totalInsertions": pl.Int64,
    "totalFrameShifts": pl.Int64,
    "totalMissing": pl.Int64,
    "totalNonACGTNs": pl.Int64,
    "alignmentScore": pl.Float64,
    "coverage": pl.Float64,
    "qc_overallScore": pl.Float64,
    "qc_overallStatus": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Clean Nextclade CSV: extract sample name, select key QC and clade columns."""
    df = sources["nextclade_raw"]

    # Extract sample name from seqName: strip reference genome suffix and consensus suffixes
    if "seqName" in df.columns:
        df = df.with_columns(
            pl.col("seqName")
            .str.replace(r"\s+.*$", "")
            .str.replace(r"\.consensus.*$", "")
            .str.replace(r"\.primertrimmed.*$", "")
            .alias("sample")
        )

    # Use clade_display if available (more readable), fall back to clade
    if "clade_display" in df.columns and "clade" in df.columns:
        df = df.with_columns(pl.col("clade_display").alias("clade"))

    # Cast integer columns
    int_cols = [
        "totalSubstitutions",
        "totalDeletions",
        "totalInsertions",
        "totalFrameShifts",
        "totalMissing",
        "totalNonACGTNs",
    ]
    for col_name in int_cols:
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).cast(pl.Int64, strict=False))

    # Cast float columns
    float_cols = ["alignmentScore", "coverage", "qc.overallScore"]
    for col_name in float_cols:
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).cast(pl.Float64, strict=False))

    # Rename dotted column names
    if "qc.overallScore" in df.columns:
        df = df.rename({"qc.overallScore": "qc_overallScore"})
    if "qc.overallStatus" in df.columns:
        df = df.rename({"qc.overallStatus": "qc_overallStatus"})

    # Fill null strings
    str_cols = ["clade", "Nextclade_pango", "qc_overallStatus"]
    for col_name in str_cols:
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).fill_null("Unknown"))

    # Select available columns
    keep_cols = [
        "sample",
        "clade",
        "Nextclade_pango",
        "totalSubstitutions",
        "totalDeletions",
        "totalInsertions",
        "totalFrameShifts",
        "totalMissing",
        "totalNonACGTNs",
        "alignmentScore",
        "coverage",
        "qc_overallScore",
        "qc_overallStatus",
    ]
    available = [c for c in keep_cols if c in df.columns]
    return df.select(available)
