"""Canonical-schema Manhattan DC for viralrecon variants.

Source: same ``variants/ivar/variants_long_table.csv`` the existing
``variants_long`` recipe reads. Reframes (CHROM, POS, AF) as the generic
Manhattan (chr, pos, score) triple; ``score_kind`` is exposed as a constant
literal in the project YAML's DC metadata, not as a column.

Canonical schema (see advanced_viz/schemas.py):
    chr : Utf8
    pos : Int64
    score : Float64        -- here = -log10(1 - AF) clipped to a sensible range
"""

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
    "chr": pl.Utf8,
    "pos": pl.Int64,
    "score": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature": pl.Utf8,
    "effect": pl.Float64,
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cast + rename CHROM/POS, derive a score from AF."""
    df = sources["variants_raw"]

    # Some viralrecon versions use lowercase column names.
    rename_map = {}
    if "CHROM" in df.columns:
        rename_map["CHROM"] = "chr"
    elif "chrom" in df.columns:
        rename_map["chrom"] = "chr"
    if "POS" in df.columns:
        rename_map["POS"] = "pos"
    elif "pos" in df.columns and "POS" not in df.columns:
        pass  # already named pos
    df = df.rename(rename_map)

    df = df.with_columns(
        pl.col("chr").cast(pl.Utf8),
        pl.col("pos").cast(pl.Int64, strict=False),
    )

    # Derive `score` from allele frequency: high AF (close to 1.0) becomes a
    # large positive score, low AF a small one. Clipping avoids log(0).
    af_col = "AF" if "AF" in df.columns else ("af" if "af" in df.columns else None)
    if af_col is None:
        raise ValueError(
            "viralrecon manhattan recipe: input is missing an AF/af allele-frequency column"
        )
    eps = 1e-6
    df = df.with_columns(
        (-(1.0 - pl.col(af_col).cast(pl.Float64, strict=False)).clip(eps, 1.0).log(base=10)).alias(
            "score"
        )
    )

    # Optional carry-through fields for hover.
    if "GENE" in df.columns:
        df = df.with_columns(pl.col("GENE").cast(pl.Utf8).alias("feature"))
    elif "gene" in df.columns:
        df = df.with_columns(pl.col("gene").cast(pl.Utf8).alias("feature"))
    if af_col == "AF":
        df = df.with_columns(pl.col("AF").cast(pl.Float64, strict=False).alias("effect"))
    elif af_col == "af":
        df = df.with_columns(pl.col("af").cast(pl.Float64, strict=False).alias("effect"))
    if "SAMPLE" in df.columns:
        df = df.rename({"SAMPLE": "sample"})

    keep = [c for c in ("chr", "pos", "score", "feature", "effect", "sample") if c in df.columns]
    return df.select(keep)
