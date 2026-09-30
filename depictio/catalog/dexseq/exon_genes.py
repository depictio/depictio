"""DEXSeq differential exon usage, summarised per contrast and gene.

nf-core/rnasplice's ``dexseq_exon`` route counts reads on the collapsed exonic
bins of every gene and runs DEXSeq per contrast. It writes, per contrast:

* ``DEXSeqResults.<contrast>.csv``: one row per exonic bin (``groupID`` the
  gene, ``featureID`` the bin, ``E001``...), with the bin's p-value, BH
  adjustment and a ``log2fold_<A>_<B>`` column named after the two conditions;
* ``perGeneQValue.<contrast>.csv``: DEXSeq's gene-level q-value, the chance
  that at least one bin of the gene is used differently.

A run over 60k annotated genes writes ~650k bins per contrast, too many to
plot, and the question a reader asks is gene-level ("which genes change exon
usage?"). So this recipe keeps one row per contrast and gene: the gene q-value,
how many bins were tested and significant, and its most significant bin (the
smallest bin q-value, the larger shift breaking ties).

Orientation: DEXSeq names its fold change ``log2fold_<A>_<B>`` = log2(A / B).
rnasplice names a contrast ``<treatment>-<control>``; when the contrast reads
``<B>-<A>`` the sign is flipped so ``log2fc`` is always treatment over control.

Genes DEXSeq could not separate (overlapping loci) come as one aggregated
``groupID`` ``ENSG1+ENSG2``; it is kept as the ``gene_id`` here.

Sources:
    bins   every ``DEXSeqResults.*.csv`` under the run root (DTU writes ``.tsv``).
    genes  every ``perGeneQValue.*.csv``.

Params:
    fdr    significance cut-off on the q-values (default 0.05).
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="bins",
        glob_pattern="**/DEXSeqResults.*.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", "NaN", ""]},
        source_path="source_path",
    ),
    RecipeSource(
        ref="genes",
        glob_pattern="**/perGeneQValue.*.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", "NaN", ""]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "gene_id": pl.Utf8,
    "bins_tested": pl.Int64,
    "bins_significant": pl.Int64,
    "top_bin": pl.Utf8,
    "log2fc": pl.Float64,
    "abs_log2fc": pl.Float64,
    "bin_padj": pl.Float64,
    "padj": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

DEFAULT_FDR = 0.05
PADJ_ZERO_NEG_LOG10 = 300.0
_CONTRAST = r"(?:DEXSeqResults|perGeneQValue)\.(.+)\.[ct]sv$"
_FOLD = re.compile(r"^log2fold_(.+)_(.+)$")


def fdr_cutoff(params: dict[str, str] | None) -> float:
    raw = str((params or {}).get("fdr") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_FDR
    return value if 0 < value < 1 else DEFAULT_FDR


def oriented_fold(df: pl.DataFrame) -> pl.Expr:
    """One ``log2fc`` from the per-contrast ``log2fold_<A>_<B>`` columns.

    A concatenation of several contrasts carries one fold column per condition
    pair, null outside its own files; each is flipped when the contrast names
    the pair the other way round, then the non-null one is kept.
    """
    exprs = []
    for col in df.columns:
        m = _FOLD.match(col)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        value = pl.col(col).cast(pl.Float64, strict=False)
        exprs.append(pl.when(pl.col("contrast") == f"{b}-{a}").then(-value).otherwise(value))
    if not exprs:
        raise ValueError(f"dexseq exon_genes: no log2fold_* column in {df.columns}")
    return pl.coalesce(exprs)


def neg_log10(col: str) -> pl.Expr:
    return (
        pl.when(pl.col(col) > 0)
        .then(-pl.col(col).log10())
        .when(pl.col(col) == 0)
        .then(pl.lit(PADJ_ZERO_NEG_LOG10))
        .otherwise(None)
    )


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """One row per contrast and gene: gene q-value and its most significant bin."""
    fdr = fdr_cutoff(params)
    bins = sources["bins"].with_columns(
        pl.col("source_path").str.extract(_CONTRAST, 1).alias("contrast")
    )
    bins = bins.select(
        pl.col("contrast"),
        pl.col("groupID").cast(pl.Utf8).alias("gene_id"),
        pl.col("featureID").cast(pl.Utf8).alias("bin"),
        oriented_fold(bins).alias("log2fc"),
        pl.col("padj").cast(pl.Float64, strict=False).alias("bin_padj"),
    ).filter(pl.col("bin_padj").is_not_null() & pl.col("log2fc").is_not_null())

    bin_sig = pl.col("bin_padj") < fdr
    # The most significant bin leads, the larger shift breaking ties: ranking
    # on the fold alone would pick near-empty bins whose log2 ratio explodes.
    ranked = bins.with_columns(bin_sig.alias("_sig"), pl.col("log2fc").abs().alias("_abs")).sort(
        ["contrast", "gene_id", "bin_padj", "_abs"], descending=[False, False, False, True]
    )
    per_gene = ranked.group_by(["contrast", "gene_id"], maintain_order=True).agg(
        pl.len().cast(pl.Int64).alias("bins_tested"),
        pl.col("_sig").sum().cast(pl.Int64).alias("bins_significant"),
        pl.col("bin").first().alias("top_bin"),
        pl.col("log2fc").first(),
        pl.col("bin_padj").first(),
    )

    genes = sources["genes"].select(
        pl.col("source_path").str.extract(_CONTRAST, 1).alias("contrast"),
        pl.col("groupID").cast(pl.Utf8).alias("gene_id"),
        pl.col("padj").cast(pl.Float64, strict=False).alias("padj"),
    )
    out = per_gene.join(genes, on=["contrast", "gene_id"], how="inner")
    significant = (pl.col("padj") < fdr).fill_null(False)
    out = out.with_columns(
        pl.col("log2fc").abs().alias("abs_log2fc"),
        neg_log10("padj").alias("neg_log10_padj"),
        significant.alias("significant"),
    ).with_columns(
        pl.when(~pl.col("significant"))
        .then(pl.lit("not significant"))
        .when(pl.col("log2fc") > 0)
        .then(pl.lit("up"))
        .otherwise(pl.lit("down"))
        .alias("direction")
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["contrast", "padj"], nulls_last=True)
