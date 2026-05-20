"""Canonical-schema Manhattan DC for viralrecon variants.

Source: same ``variants/ivar/variants_long_table.csv`` the existing
``variants_long`` recipe reads. Reframes (CHROM, POS, AF) as the generic
Manhattan (chr, pos, score) triple; ``score_kind`` is exposed as a constant
literal in the project YAML's DC metadata, not as a column.

``score`` is the **raw allele frequency** (0 → 1, linear). The previous
``-log10(1 - AF)`` transform compressed an already-bounded value through an
unfamiliar non-linearity — for a ~30 kb viral genome with a few hundred
variants, the linear AF axis is what virologists actually read (≈ 0.5 =
consensus cutoff, ≥ 0.95 = fixed).

Canonical schema (see advanced_viz/schemas.py):
    chr : Utf8
    pos : Int64
    score : Float64        -- allele frequency, 0..1 linear

``variant_label`` (optional) is a human-readable variant identifier built from
the SnpEff annotation columns:

  * non-synonymous change (HGVS protein notation available)
        → ``GENE:HGVS_P_1LETTER``  (e.g. ``S:D614G``)
  * synonymous / intergenic / no protein context
        → ``GENE:POS REF>ALT``     (e.g. ``orf1ab:14408 C>T``)

This is what the Manhattan label slot (``feature_col``) reads — the gene-only
``feature`` column is kept as a separate field for the Gene MultiSelect filter
(it would otherwise become a per-variant filter and balloon to thousands of
options).
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
    "variant_label": pl.Utf8,
    "effect": pl.Utf8,
    "lineage": pl.Utf8,
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cast + rename CHROM/POS, expose AF directly as the score."""
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

    af_col = "AF" if "AF" in df.columns else ("af" if "af" in df.columns else None)
    if af_col is None:
        raise ValueError(
            "viralrecon manhattan recipe: input is missing an AF/af allele-frequency column"
        )
    df = df.with_columns(
        pl.col(af_col).cast(pl.Float64, strict=False).alias("score"),
    )

    # Gene name (kept as its own column for the dashboard's Gene filter).
    if "GENE" in df.columns:
        df = df.with_columns(pl.col("GENE").cast(pl.Utf8).alias("feature"))
    elif "gene" in df.columns:
        df = df.with_columns(pl.col("gene").cast(pl.Utf8).alias("feature"))

    # SnpEff annotations — carry through for richer labelling + future colouring.
    for src, dst in (("EFFECT", "effect"), ("LINEAGE", "lineage")):
        if src in df.columns:
            df = df.with_columns(pl.col(src).cast(pl.Utf8).alias(dst))

    # Human-readable variant label. Prefer the HGVS protein 1-letter notation
    # (``p.D614G`` → ``D614G``) when it's a real protein change; fall back to
    # ``POS REF>ALT`` for synonymous / intergenic / unannotated rows. Prepend
    # ``feature`` (gene name) so the label always carries spatial context.
    if "HGVS_P_1LETTER" in df.columns and "REF" in df.columns and "ALT" in df.columns:
        # Strip the leading "p." (HGVS protein prefix) for compactness on labels.
        hgvs_clean = pl.col("HGVS_P_1LETTER").cast(pl.Utf8).str.replace(r"^p\.", "")
        has_protein_change = (
            pl.col("HGVS_P_1LETTER").is_not_null()
            & (pl.col("HGVS_P_1LETTER") != ".")
            & (pl.col("HGVS_P_1LETTER") != "")
        )
        protein_label = pl.col("feature").fill_null("?") + pl.lit(":") + hgvs_clean
        nucleotide_label = (
            pl.col("feature").fill_null("?")
            + pl.lit(":")
            + pl.col("pos").cast(pl.Utf8)
            + pl.lit(" ")
            + pl.col("REF").cast(pl.Utf8)
            + pl.lit(">")
            + pl.col("ALT").cast(pl.Utf8)
        )
        df = df.with_columns(
            pl.when(has_protein_change)
            .then(protein_label)
            .otherwise(nucleotide_label)
            .alias("variant_label"),
        )

    if "SAMPLE" in df.columns:
        df = df.rename({"SAMPLE": "sample"})

    keep = [
        c
        for c in ("chr", "pos", "score", "feature", "variant_label", "effect", "lineage", "sample")
        if c in df.columns
    ]
    return df.select(keep)
