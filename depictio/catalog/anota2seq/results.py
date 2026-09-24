"""anota2seq results in long form: one row per contrast, analysis and gene.

nf-core's anota2seq module writes, per contrast, one table per analysis:

* ``translated_mRNA``: change in ribosome-bound mRNA (Ribo-seq) between the
  conditions, alone;
* ``total_mRNA``: change in total mRNA (RNA-seq), alone;
* ``translation``: change in ribosome-bound mRNA not explained by total mRNA,
  the translational-efficiency effect (analysis of partial variance);
* ``buffering``: change in total mRNA not followed by the ribosome-bound
  fraction, which keeps the protein output constant.

Each table carries ``apvEff`` (the effect, log2 scale), the RVM p-value and its
BH adjustment; translation and buffering also carry the APV slope. The contrast
and the analysis are read from the file name
(``<contrast>.<analysis>.anota2seq.results.tsv``).

Sources:
    results  every ``*.anota2seq.results.tsv`` under the run root.
    genes    optional table with ``gene_id`` and ``gene_name`` columns (the
             merged Salmon count matrix by default) to put symbols on the
             Ensembl ids; repoint it with ``source_overrides``.

Output: see ``EXPECTED_SCHEMA``. ``significant`` uses anota2seq's default
selection: adjusted p below ``MAX_PADJ`` and an absolute effect of at least
``MIN_EFFECT`` (log2 of a 1.2-fold change).
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
    "analysis": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "effect": pl.Float64,
    "slope": pl.Float64,
    "pvalue": pl.Float64,
    "padj": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

MAX_PADJ = 0.15
MIN_EFFECT = math.log2(1.2)
PADJ_ZERO_NEG_LOG10 = 300.0

ANALYSIS_LABELS = {
    "translated_mRNA": "Ribosome-bound mRNA",
    "total_mRNA": "Total mRNA",
    "translation": "Translation",
    "buffering": "Buffering",
    "mRNA_abundance": "mRNA abundance",
}

_FILE = r"([^/]+)\.([^./]+)\.anota2seq\.results\.tsv$"


def gene_names(genes: pl.DataFrame | None) -> pl.DataFrame | None:
    """Unique gene_id to gene_name map, or None when no annotation was found."""
    if genes is None or not {"gene_id", "gene_name"} <= set(genes.columns):
        return None
    return genes.select(pl.col("gene_id").cast(pl.Utf8), pl.col("gene_name").cast(pl.Utf8)).unique(
        subset="gene_id", keep="first"
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Stack the analyses of every contrast, with the significance call."""
    df = sources["results"]
    for col in ("apvSlope",):
        if col not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(col))
    parts = pl.col("source_path").str.extract_groups(_FILE)
    df = df.with_columns(
        parts.struct.field("1").alias("contrast"),
        parts.struct.field("2").alias("_analysis"),
    )
    out = df.select(
        pl.col("contrast"),
        pl.col("_analysis").replace(ANALYSIS_LABELS).alias("analysis"),
        pl.col("gene_id").cast(pl.Utf8),
        pl.col("apvEff").cast(pl.Float64).alias("effect"),
        pl.col("apvSlope").cast(pl.Float64).alias("slope"),
        pl.col("apvRvmP").cast(pl.Float64).alias("pvalue"),
        pl.col("apvRvmPAdj").cast(pl.Float64).alias("padj"),
    )
    names = gene_names(sources.get("genes"))
    if names is not None:
        out = out.join(names, on="gene_id", how="left")
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("gene_name"))
    significant = (pl.col("padj") < MAX_PADJ) & (pl.col("effect").abs() >= MIN_EFFECT)
    out = out.with_columns(
        pl.col("gene_name").fill_null(pl.col("gene_id")),
        pl.when(pl.col("padj") > 0)
        .then(-pl.col("padj").log10())
        .when(pl.col("padj") == 0)
        .then(pl.lit(PADJ_ZERO_NEG_LOG10))
        .otherwise(None)
        .alias("neg_log10_padj"),
        significant.fill_null(False).alias("significant"),
    ).with_columns(
        pl.when(~pl.col("significant"))
        .then(pl.lit("not significant"))
        .when(pl.col("effect") > 0)
        .then(pl.lit("up"))
        .otherwise(pl.lit("down"))
        .alias("direction")
    )
    return out.sort("contrast", "analysis", "gene_id").select(list(EXPECTED_SCHEMA))
