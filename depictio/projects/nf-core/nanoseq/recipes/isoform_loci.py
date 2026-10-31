"""One row per transcript DEXSeq tested, with its span and a score the genome browser opens on.

The genome browser of the Isoform usage tab needs somewhere to look. DEXSeq's
table has the verdict but no coordinates; the annotation Bambu extended
(``gtf_transcripts``, optional) has the coordinates but no verdict. Joined, each
tested transcript becomes a call: the browser opens on the best one, steps from
one to the next, and a transcript picked in the DEXSeq table frames exactly its
span.

Sources (both are collections of the template, read through ``dc_ref``):
    dex     ``dexseq_results``, one row per transcript tested (always present)
    blocks  ``gtf_transcripts``, the exon blocks of the extended annotation
            (optional: a quantification-only run has no such file)

Without the annotation the rows are still written, with no ``chrom`` / ``start`` /
``end``: the collection exists on every run, the browser has no call to frame,
and it opens on the first region its tracks hold.

Output, one row per tested transcript:
    transcript_id      DEXSeq featureID (a Bambu transcript id)
    gene_id            Ensembl gene id
    gene_name          readable symbol from the annotation, else the gene id
    chrom              contig of the transcript (null without the annotation)
    start, end         first base of its first exon, last base of its last exon
    strand             transcript strand
    n_exons            exon blocks of the transcript
    transcript_class   novelty label of the annotation (`known`, `novel`...)
    log2fc             DEXSeq log2 fold change of the transcript's usage
    padj               DEXSeq gene-level adjusted q-value
    significant        padj below 0.05
    direction          up / down / not significant
    rank_score         -log10(padj) (capped at 300, 0 where DEXSeq gave none) plus
                       |log2fc| / 1000: DEXSeq's q-value is the gene's, shared by all its
                       transcripts, so the effect size breaks the tie in one number
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="dex",
        dc_ref="dexseq_results",
        input_schema={
            "feature_id": pl.Utf8,
            "gene_id": pl.Utf8,
            "log2fc": pl.Float64,
            "padj": pl.Float64,
            "significant": pl.Boolean,
            "direction": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="blocks",
        dc_ref="gtf_transcripts",
        optional=True,
        input_schema={
            "transcript_id": pl.Utf8,
            "chrom": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "feature": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "transcript_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "n_exons": pl.Int64,
    "transcript_class": pl.Utf8,
    "log2fc": pl.Float64,
    "padj": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
    "rank_score": pl.Float64,
}

#: Cap of -log10(padj): a q-value that underflowed to 0 would be infinite.
_MAX_NEG_LOG10 = 300.0


def _spans(blocks: pl.DataFrame | None) -> pl.DataFrame:
    """One row per transcript: contig, span, strand, exon count, novelty, gene symbol."""
    schema = {
        "transcript_id": pl.Utf8,
        "_chrom": pl.Utf8,
        "_start": pl.Int64,
        "_end": pl.Int64,
        "_strand": pl.Utf8,
        "_n_exons": pl.Int64,
        "_class": pl.Utf8,
        "_gene_name": pl.Utf8,
    }
    if blocks is None or blocks.is_empty():
        return pl.DataFrame(schema=schema)
    cols = blocks.columns
    exons = blocks.filter(pl.col("feature") == "exon").with_columns(
        (pl.col("strand") if "strand" in cols else pl.lit(None, dtype=pl.Utf8)).alias("_strand"),
        (
            pl.col("transcript_class")
            if "transcript_class" in cols
            else pl.lit(None, dtype=pl.Utf8)
        ).alias("_class"),
        (pl.col("gene_name") if "gene_name" in cols else pl.lit(None, dtype=pl.Utf8)).alias(
            "_gene_name"
        ),
    )
    if exons.is_empty():
        return pl.DataFrame(schema=schema)
    return exons.group_by("transcript_id").agg(
        pl.col("chrom").first().alias("_chrom"),
        pl.col("start").min().alias("_start"),
        pl.col("end").max().alias("_end"),
        pl.col("_strand").drop_nulls().first().alias("_strand"),
        pl.struct("start", "end").n_unique().cast(pl.Int64).alias("_n_exons"),
        pl.col("_class").drop_nulls().first().alias("_class"),
        pl.col("_gene_name").drop_nulls().first().alias("_gene_name"),
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """The DEXSeq transcripts, each with its span where the annotation has one."""
    dex = sources["dex"]
    if dex is None or dex.is_empty():
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    spans = _spans(sources.get("blocks"))
    neg_log10 = (
        pl.when(pl.col("padj").is_null())
        .then(0.0)
        .when(pl.col("padj") <= 0)
        .then(_MAX_NEG_LOG10)
        .otherwise((-pl.col("padj").log10()).clip(upper_bound=_MAX_NEG_LOG10))
    )
    return (
        dex.join(spans, left_on="feature_id", right_on="transcript_id", how="left")
        .select(
            pl.col("feature_id").alias("transcript_id"),
            "gene_id",
            pl.coalesce("_gene_name", "gene_id").alias("gene_name"),
            pl.col("_chrom").alias("chrom"),
            pl.col("_start").alias("start"),
            pl.col("_end").alias("end"),
            pl.col("_strand").alias("strand"),
            pl.col("_n_exons").alias("n_exons"),
            pl.col("_class").alias("transcript_class"),
            "log2fc",
            "padj",
            "significant",
            "direction",
            (neg_log10 + pl.col("log2fc").abs().clip(upper_bound=50.0).fill_null(0.0) / 1000)
            .round(6)
            .alias("rank_score"),
        )
        .unique(subset="transcript_id", keep="first", maintain_order=True)
        .sort("rank_score", descending=True, nulls_last=True)
    )
