"""anota2seq regulatory mode per gene: one row per contrast and gene.

Joins the four anota2seq analyses of a contrast side by side and assigns each
gene one regulatory mode, following anota2seq's own reading of the tables:

* ``translation``: the translation analysis is significant (a change in
  ribosome-bound mRNA not explained by total mRNA), with an APV slope inside
  anota2seq's default window (``SLOPE_TRANSLATION``);
* ``buffering``: otherwise, the buffering analysis is significant (total mRNA
  changes and the ribosome-bound fraction does not follow), slope inside
  ``SLOPE_BUFFERING``;
* ``mRNA abundance``: otherwise, total and ribosome-bound mRNA both change
  significantly in the same direction, so the gene is regulated through its
  mRNA level;
* ``not regulated``: none of the above.

Significance is anota2seq's default selection: adjusted p below ``MAX_PADJ``
and an absolute effect of at least ``MIN_EFFECT`` (log2 of a 1.2-fold change).
``direction`` is the sign of the effect that decided the mode.

Sources: the same files as ``results.py`` (every
``<contrast>.<analysis>.anota2seq.results.tsv``) and the same optional gene
symbol table.

Output: see ``EXPECTED_SCHEMA``.
"""

from __future__ import annotations

import math

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="results",
        glob_pattern="**/*.anota2seq.results.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", "NaN", ""]},
        source_path="source_path",
    ),
    RecipeSource(
        ref="genes",
        path="quantification/salmon/salmon.merged.gene_counts.tsv",
        format="tsv",
        optional=True,
        read_kwargs={"columns": ["gene_id", "gene_name"], "infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "total_mrna_lfc": pl.Float64,
    "total_mrna_padj": pl.Float64,
    "translated_mrna_lfc": pl.Float64,
    "translated_mrna_padj": pl.Float64,
    "translation_effect": pl.Float64,
    "translation_pvalue": pl.Float64,
    "translation_padj": pl.Float64,
    "buffering_effect": pl.Float64,
    "buffering_padj": pl.Float64,
    "regulation_mode": pl.Utf8,
    "direction": pl.Utf8,
}

MAX_PADJ = 0.15
MIN_EFFECT = math.log2(1.2)
SLOPE_TRANSLATION = (-1.0, 2.0)
SLOPE_BUFFERING = (-2.0, 1.0)

_FILE = r"([^/]+)\.([^./]+)\.anota2seq\.results\.tsv$"
_PREFIX = {
    "total_mRNA": "total_mrna",
    "translated_mRNA": "translated_mrna",
    "translation": "translation",
    "buffering": "buffering",
}


def _sig(prefix: str, effect: str, slope: tuple[float, float] | None = None) -> pl.Expr:
    expr = (pl.col(f"{prefix}_padj") < MAX_PADJ) & (pl.col(effect).abs() >= MIN_EFFECT)
    if slope is not None:
        lo, hi = slope
        expr = expr & pl.col(f"{prefix}_slope").is_between(lo, hi)
    return expr.fill_null(False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Four analyses side by side, one regulatory mode per gene."""
    df = sources["results"]
    if "apvSlope" not in df.columns:
        df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias("apvSlope"))
    parts = pl.col("source_path").str.extract_groups(_FILE)
    df = df.with_columns(
        parts.struct.field("1").alias("contrast"),
        parts.struct.field("2").alias("analysis"),
    ).filter(pl.col("analysis").is_in(list(_PREFIX)))

    wide: pl.DataFrame | None = None
    for analysis, prefix in _PREFIX.items():
        part = df.filter(pl.col("analysis") == analysis).select(
            pl.col("contrast"),
            pl.col("gene_id").cast(pl.Utf8),
            pl.col("apvEff").cast(pl.Float64).alias(f"{prefix}_eff"),
            pl.col("apvSlope").cast(pl.Float64).alias(f"{prefix}_slope"),
            pl.col("apvRvmP").cast(pl.Float64).alias(f"{prefix}_pvalue"),
            pl.col("apvRvmPAdj").cast(pl.Float64).alias(f"{prefix}_padj"),
        )
        wide = (
            part
            if wide is None
            else wide.join(part, on=["contrast", "gene_id"], how="full", coalesce=True)
        )
    assert wide is not None
    for prefix in _PREFIX.values():
        for suffix in ("eff", "slope", "pvalue", "padj"):
            if f"{prefix}_{suffix}" not in wide.columns:
                wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(f"{prefix}_{suffix}"))

    translation = _sig("translation", "translation_eff", SLOPE_TRANSLATION)
    buffering = _sig("buffering", "buffering_eff", SLOPE_BUFFERING)
    abundance = (
        _sig("total_mrna", "total_mrna_eff")
        & _sig("translated_mrna", "translated_mrna_eff")
        & (pl.col("total_mrna_eff").sign() == pl.col("translated_mrna_eff").sign())
    )
    wide = wide.with_columns(
        pl.when(translation)
        .then(pl.lit("translation"))
        .when(buffering)
        .then(pl.lit("buffering"))
        .when(abundance)
        .then(pl.lit("mRNA abundance"))
        .otherwise(pl.lit("not regulated"))
        .alias("regulation_mode"),
        pl.when(translation)
        .then(pl.col("translation_eff"))
        .when(buffering)
        .then(pl.col("buffering_eff"))
        .when(abundance)
        .then(pl.col("translated_mrna_eff"))
        .otherwise(None)
        .alias("_deciding"),
    ).with_columns(
        pl.when(pl.col("_deciding").is_null())
        .then(pl.lit("none"))
        .when(pl.col("_deciding") > 0)
        .then(pl.lit("up"))
        .otherwise(pl.lit("down"))
        .alias("direction")
    )

    genes = sources.get("genes")
    if genes is not None and {"gene_id", "gene_name"} <= set(genes.columns):
        names = genes.select(
            pl.col("gene_id").cast(pl.Utf8), pl.col("gene_name").cast(pl.Utf8)
        ).unique(subset="gene_id", keep="first")
        wide = wide.join(names, on="gene_id", how="left")
    else:
        wide = wide.with_columns(pl.lit(None, dtype=pl.Utf8).alias("gene_name"))

    return (
        wide.select(
            pl.col("contrast").cast(pl.Utf8),
            pl.col("gene_id"),
            pl.col("gene_name").fill_null(pl.col("gene_id")),
            pl.col("total_mrna_eff").alias("total_mrna_lfc"),
            pl.col("total_mrna_padj"),
            pl.col("translated_mrna_eff").alias("translated_mrna_lfc"),
            pl.col("translated_mrna_padj"),
            pl.col("translation_eff").alias("translation_effect"),
            pl.col("translation_pvalue"),
            pl.col("translation_padj"),
            pl.col("buffering_eff").alias("buffering_effect"),
            pl.col("buffering_padj"),
            pl.col("regulation_mode"),
            pl.col("direction"),
        )
        .sort("contrast", "gene_id")
        .select(list(EXPECTED_SCHEMA))
    )
