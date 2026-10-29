"""Intron chains of the isoforms, weighted by what each isoform was counted at.

A long-read BAM draws its own splice arcs, but only over the reads it holds in
view. The chain of introns an isoform is built from lives in the annotation Bambu
extended, and how much the isoform is used lives in Bambu's transcript counts.
Joined, they give the junction table the ``sashimi`` kind draws: one arc per
intron of a transcript, one lane per condition the run compares, the arc
weighted by the reads Bambu assigned to that transcript.

Sources (both are collections of the template, read through ``dc_ref``):
    blocks  ``gtf_transcripts``, the exon blocks of the extended annotation
            (optional: a run that let Bambu extend nothing has no such file, and
            this collection is then empty)
    counts  ``bambu_counts_transcript_long``, one row per library and transcript

Output, one row per condition, transcript and intron:
    chrom         contig the transcript sits on
    start, end    donor (last base of the exon before) and acceptor (first base of
                  the exon after) of the intron
    reads         the transcript's reads in the condition, averaged over its libraries
    condition     the lane the arc is drawn in
    transcript_id Bambu transcript the intron belongs to (links to the DEXSeq row)
    gene_id       gene of the transcript
    gene_name     readable symbol, falling back to the gene id
    annotation    ``known`` when the transcript is in the reference, else ``novel``

A transcript with one exon has no intron and no row. Two transcripts that share an
intron each keep a row: a pick on the DEXSeq table narrows the table to one
transcript's chain, which is the reading the tile is for.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="blocks",
        dc_ref="gtf_transcripts",
        optional=True,
        input_schema={
            "transcript_id": pl.Utf8,
            "gene_id": pl.Utf8,
            "chrom": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "feature": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="counts",
        dc_ref="bambu_counts_transcript_long",
        input_schema={
            "sample": pl.Utf8,
            "condition": pl.Utf8,
            "transcript_id": pl.Utf8,
            "count": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "reads": pl.Float64,
    "condition": pl.Utf8,
    "transcript_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "annotation": pl.Utf8,
}


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=OUTPUT_SCHEMA)


def _introns(blocks: pl.DataFrame) -> pl.DataFrame:
    """Exon blocks -> one row per intron of every transcript."""
    gene_name = pl.col("gene_name") if "gene_name" in blocks.columns else pl.col("gene_id")
    klass = pl.col("transcript_class") if "transcript_class" in blocks.columns else pl.lit("known")
    exons = (
        blocks.filter(pl.col("feature") == "exon")
        .select(
            "transcript_id",
            "gene_id",
            gene_name.alias("gene_name"),
            "chrom",
            "start",
            "end",
            klass.alias("transcript_class"),
        )
        .unique(["transcript_id", "chrom", "start", "end"])
        .sort(["transcript_id", "start"])
    )
    return (
        exons.with_columns(
            pl.col("start").shift(-1).over("transcript_id").alias("next_start"),
        )
        # The last exon of a transcript has no next block; two blocks that touch
        # (a gap of one base or less) leave no intron to draw.
        .filter(pl.col("next_start").is_not_null() & (pl.col("next_start") - pl.col("end") > 1))
        .select(
            "chrom",
            pl.col("end").alias("start"),
            pl.col("next_start").alias("end"),
            "transcript_id",
            "gene_id",
            "gene_name",
            pl.when(pl.col("transcript_class") == "known")
            .then(pl.lit("known"))
            .otherwise(pl.lit("novel"))
            .alias("annotation"),
        )
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Join the intron chains with the transcript counts of every condition."""
    blocks = sources.get("blocks")
    counts = sources["counts"]
    if blocks is None or blocks.is_empty() or counts.is_empty():
        return _empty()

    introns = _introns(blocks)
    libraries = counts.group_by("condition").agg(pl.col("sample").n_unique().alias("n_libraries"))
    usage = (
        counts.group_by("condition", "transcript_id")
        .agg(pl.col("count").sum().alias("total"))
        .join(libraries, on="condition", how="left")
        .select(
            "condition",
            "transcript_id",
            (pl.col("total") / pl.col("n_libraries")).alias("reads"),
        )
        .filter(pl.col("reads") > 0)
    )
    out = introns.join(usage, on="transcript_id", how="inner")
    if out.is_empty():
        return _empty()
    return out.select(
        "chrom",
        pl.col("start").cast(pl.Int64),
        pl.col("end").cast(pl.Int64),
        pl.col("reads").cast(pl.Float64),
        "condition",
        "transcript_id",
        "gene_id",
        "gene_name",
        "annotation",
    ).sort(["chrom", "start", "end", "condition", "transcript_id"])
