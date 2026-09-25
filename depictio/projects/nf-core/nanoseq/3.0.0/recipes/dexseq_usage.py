"""Relative transcript usage per library, for the genes DEXSeq ranks first.

DEXSeq's statistic is about proportions: whether one transcript takes a larger
share of its gene's reads in one condition, the gene's total held constant.
The results table gives the verdict (a log2 fold change of usage and a
gene-level q-value) but not the proportions themselves, which are what a
reader wants to see before trusting a call on six libraries. nanoseq publishes
the transcript counts DEXSeq was run on (``bambu/counts_transcript.txt``), so
the proportions are recomputed here: for each tested gene and each library,
every transcript's count over the gene's total.

Only the ``TOP_GENES`` genes with the smallest gene-level q-value are kept, the
significant ones first, so the tile is the handful of genes the DEXSeq table
leads with rather than 200 stacked bars. The q-value travels with every row in
``gene_label`` so a gene kept only to fill the panel says it is not
significant.

    sample, condition     library and its condition
    gene_id, gene_label   Ensembl gene id; the id with its DEXSeq q-value
    transcript_id         the Bambu transcript DEXSeq tested
    count                 reads Bambu assigned to the transcript
    usage_pct             100 x count / the gene's reads in that library
    gene_padj             DEXSeq gene-level adjusted q-value (dex.padj$gene)
    usage_log2fc          DEXSeq log2 fold change of the transcript's usage
    significant           gene_padj below 0.05
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bambu import condition_of, gene_id_expr
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="results",
        glob_pattern="**/dexseq/*.results.txt",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="counts",
        glob_pattern="**/bambu/counts_transcript.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_label": pl.Utf8,
    "transcript_id": pl.Utf8,
    "count": pl.Float64,
    "usage_pct": pl.Float64,
    "gene_padj": pl.Float64,
    "usage_log2fc": pl.Float64,
    "significant": pl.Boolean,
}

#: Genes kept, ranked by gene-level q-value.
TOP_GENES = 6
PADJ_THRESHOLD = 0.05


def _float(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Float64, strict=False)


def _tested(results: pl.DataFrame) -> pl.DataFrame:
    """DEXSeq table -> (transcript_id, gene_id, usage_log2fc, gene_padj)."""
    lfc = next((c for c in results.columns if c.lower().startswith("log2fold_")), None)
    padj = next(
        (c for c in results.columns if re.sub(r"[^a-z]", "", c.lower()) == "dexpadjgene"),
        None,
    )
    if lfc is None or padj is None:
        raise ValueError(
            f"dexseq results: log2fold_* or dex.padj$gene missing in {results.columns}"
        )
    return (
        results.select(
            pl.col("featureID").alias("transcript_id"),
            gene_id_expr("groupID").alias("gene_id"),
            _float(lfc).alias("usage_log2fc"),
            _float(padj).alias("gene_padj"),
        )
        .drop_nulls(["transcript_id", "gene_id"])
        .unique(["transcript_id", "gene_id"], keep="first")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """DEXSeq verdicts + Bambu transcript counts -> per-library usage shares."""
    tested = _tested(sources["results"])
    ranked = (
        tested.group_by("gene_id")
        .agg(pl.col("gene_padj").min())
        .sort(["gene_padj", "gene_id"], nulls_last=True)
        .head(TOP_GENES)
    )
    kept = tested.join(ranked.select("gene_id"), on="gene_id", how="semi")

    counts = sources["counts"]
    id_col, _gene_col, *generic = counts.columns
    samples = [strip_stage_suffixes(c) for c in generic]
    long = (
        counts.rename({id_col: "transcript_id", **dict(zip(generic, samples, strict=True))})
        .select(["transcript_id", *samples])
        .unpivot(index="transcript_id", on=samples, variable_name="sample", value_name="count")
        .with_columns(_float("count"))
    )

    usage = (
        kept.join(long, on="transcript_id", how="inner")
        .with_columns(pl.col("count").sum().over(["gene_id", "sample"]).alias("_gene_total"))
        .with_columns(
            pl.when(pl.col("_gene_total") > 0)
            .then(pl.col("count") * 100.0 / pl.col("_gene_total"))
            .otherwise(None)
            .alias("usage_pct"),
            (pl.col("gene_padj") < PADJ_THRESHOLD).fill_null(False).alias("significant"),
            pl.format(
                "{} (q {})",
                pl.col("gene_id"),
                pl.col("gene_padj").round_sig_figs(2).cast(pl.Utf8).fill_null("NA"),
            ).alias("gene_label"),
            pl.col("sample").map_elements(condition_of, return_dtype=pl.Utf8).alias("condition"),
        )
    )
    if usage.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    return usage.select(list(EXPECTED_SCHEMA)).sort(
        ["gene_padj", "gene_id", "sample", "transcript_id"]
    )
