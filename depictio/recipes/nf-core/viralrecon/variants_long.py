"""Clean and normalize viralrecon variants_long_table.csv for dashboard consumption."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants_raw",
        path="variants/ivar/variants_long_table.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "CHROM": pl.Utf8,
    "POS": pl.Int64,
    "REF": pl.Utf8,
    "ALT": pl.Utf8,
    "FILTER": pl.Utf8,
    "DP": pl.Int64,
    "REF_DP": pl.Int64,
    "ALT_DP": pl.Int64,
    "AF": pl.Float64,
    "GENE": pl.Utf8,
    "AA": pl.Utf8,
    "EFFECT": pl.Utf8,
    "FUNCLASS": pl.Utf8,
    "mutation_label": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Normalize variant table: cast types, add mutation label, filter pass variants."""
    df = sources["variants_raw"]

    # Rename SAMPLE to sample if present (some versions use uppercase)
    if "SAMPLE" in df.columns and "sample" not in df.columns:
        df = df.rename({"SAMPLE": "sample"})

    # Cast numeric columns
    for col_name in ("POS", "DP", "REF_DP", "ALT_DP"):
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).cast(pl.Int64, strict=False))
    if "AF" in df.columns:
        df = df.with_columns(pl.col("AF").cast(pl.Float64, strict=False))

    # Fill null string columns
    for col_name in ("GENE", "AA", "EFFECT", "FUNCLASS", "FILTER"):
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).fill_null("Unknown"))

    # Create mutation label: GENE:REF{POS}ALT
    df = df.with_columns(
        (pl.col("GENE") + ":" + pl.col("REF") + pl.col("POS").cast(pl.Utf8) + pl.col("ALT")).alias(
            "mutation_label"
        )
    )

    # Select final columns
    keep_cols = [
        "sample",
        "CHROM",
        "POS",
        "REF",
        "ALT",
        "FILTER",
        "DP",
        "REF_DP",
        "ALT_DP",
        "AF",
        "GENE",
        "AA",
        "EFFECT",
        "FUNCLASS",
        "mutation_label",
    ]
    available = [c for c in keep_cols if c in df.columns]
    return df.select(available)
