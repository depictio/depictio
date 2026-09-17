"""DEXSeq differential exon/transcript usage results (volcano schema).

nf-core/nanoseq's local DEXSeq module writes one ``dexseq.results.txt`` (R
``write.csv``, quoted, comma-separated, unnamed first column of row names) per
run, with the effect-size column named after the two conditions compared
(``log2fold_<A>_<B>``) rather than a fixed name, DEXSeq bakes the contrast
into the column, unlike DESeq2's fixed ``log2FoldChange``.

Output schema:
    feature_id : Utf8    DEXSeq ``featureID`` (a transcript id here)
    gene_id : Utf8        Ensembl gene id, extracted from ``groupID``
    log2fc : Float64      the ``log2fold_*`` column, whatever the two
                           condition names are, renamed to a fixed name
    pvalue : Float64      raw DEXSeq p-value
    padj : Float64         ``dex.padj$gene``, the gene-level BH-adjusted
                           q-value (more meaningful for a volcano than the
                           per-feature ``dex.padj$transcript``, which DEXSeq
                           leaves ``NA`` for features it could not test)
    significant : Boolean  padj < 0.05
    direction : Utf8       "up" / "down" / "not significant"
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="results",
        glob_pattern="**/dexseq/*.results.txt",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "log2fc": pl.Float64,
    "pvalue": pl.Float64,
    "padj": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

PADJ_THRESHOLD = 0.05
_GENE_RE = r"(ENSG\d+)"


def _to_float(df: pl.DataFrame, col: str) -> pl.DataFrame:
    return df.with_columns(
        pl.when(pl.col(col).str.to_uppercase().is_in(["NA", "NAN", ""]))
        .then(None)
        .otherwise(pl.col(col))
        .cast(pl.Float64, strict=False)
        .alias(col)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["results"]

    log2fold_col = next((c for c in df.columns if c.lower().startswith("log2fold_")), None)
    if log2fold_col is None:
        raise ValueError(f"dexseq results: no log2fold_* column in {df.columns}")
    gene_padj_col = next(
        (c for c in df.columns if re.sub(r"[^a-z]", "", c.lower()) == "dexpadjgene"), None
    )
    if gene_padj_col is None:
        raise ValueError(f"dexseq results: no dex.padj$gene column in {df.columns}")

    df = df.rename({"featureID": "feature_id", log2fold_col: "log2fc", gene_padj_col: "padj"})
    df = df.with_columns(pl.col("groupID").str.extract(_GENE_RE, 1).alias("gene_id"))
    for col in ("log2fc", "pvalue", "padj"):
        df = _to_float(df, col)

    is_sig = pl.col("padj") < PADJ_THRESHOLD
    df = df.with_columns(
        is_sig.fill_null(False).alias("significant"),
        pl.when(is_sig & (pl.col("log2fc") > 0))
        .then(pl.lit("up"))
        .when(is_sig & (pl.col("log2fc") < 0))
        .then(pl.lit("down"))
        .otherwise(pl.lit("not significant"))
        .alias("direction"),
    )
    df = df.filter(pl.col("feature_id").is_not_null() & pl.col("gene_id").is_not_null())
    return df.select(
        ["feature_id", "gene_id", "log2fc", "pvalue", "padj", "significant", "direction"]
    )
