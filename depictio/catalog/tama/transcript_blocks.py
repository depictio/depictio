"""Exon blocks of the TAMA merge isoforms, beside the reference isoforms of their genes.

The long frame the ``transcript_structure`` kind binds (one row per drawn
block, the shape ``gtf/transcripts`` produces): every exon of every merged
isoform, labelled with its structural category and its FLNC read support, plus,
when a reference annotation is available, the exons and CDS of the reference
transcripts of every gene the run found an isoform of. The reference lanes
carry the class ``reference`` and the sample ``reference``, so the kind draws
them in neutral grey below the run's own isoforms, sorted by read support: a
new exon, a skipped one or a shifted splice site reads directly against the
annotation.

Sources:
    transcripts  ``tama_transcripts`` (catalog ``tama/transcripts``): category,
                 gene and read support per isoform
    bed          ``tama_merge_bed_raw``: the merged BED12 files (exon blocks)
    reference    optional reference GTF (default ``ULTRA_INDEX/genome.gtf``)

Output schema (one row per exon / CDS block):
    transcript_id : Utf8       isoform (TAMA id, or the reference transcript id)
    gene_id : Utf8             reference gene, else ``<sample>:<tama gene>``
    gene_name : Utf8           reference gene name, else the TAMA gene id
    chrom : Utf8               sequence
    start : Int64              block start, 1-based inclusive
    end : Int64                block end, inclusive
    feature : Utf8             exon, or CDS on reference transcripts
    strand : Utf8              + or -
    transcript_class : Utf8    structural category, or ``reference``
    sample : Utf8              sample, or ``reference``
    expression : Float64       FLNC reads supporting the isoform (null on reference lanes)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

TRANSCRIPTS_DC_TAG = "tama_transcripts"
RAW_DC_TAG = "tama_merge_bed_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="transcripts", dc_ref=TRANSCRIPTS_DC_TAG),
    RecipeSource(ref="bed", dc_ref=RAW_DC_TAG),
    RecipeSource(
        ref="reference",
        path="ULTRA_INDEX/genome.gtf",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "comment_prefix": "#",
            "quote_char": None,
            "columns": [0, 2, 3, 4, 6, 8],
            "new_columns": ["seqname", "feature", "start", "end", "strand", "attributes"],
            "infer_schema_length": 0,
            "truncate_ragged_lines": True,
        },
        optional=True,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "transcript_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "feature": pl.Utf8,
    "strand": pl.Utf8,
    "transcript_class": pl.Utf8,
    "sample": pl.Utf8,
    "expression": pl.Float64,
}

REFERENCE = "reference"
POOLED = "all_samples"


def _attr(key: str) -> pl.Expr:
    return pl.col("attributes").str.extract(rf'{key} "([^"]*)"', 1)


def query_blocks(bed: pl.DataFrame, transcripts: pl.DataFrame) -> pl.DataFrame:
    name = pl.col("source_path").str.split("/").list.last()
    models = (
        bed.filter(~name.str.contains(r"_(collapsed|trans_read)\.bed$"))
        .with_columns(name.str.replace(r"\.bed$", "").alias("sample"))
        .filter(pl.col("sample") != POOLED)
        .select(
            "sample",
            pl.col("name").str.split(";").list.get(-1, null_on_oob=True).alias("transcript_id"),
            pl.col("chrom").cast(pl.Utf8),
            pl.col("strand").cast(pl.Utf8),
            pl.col("chrom_start").cast(pl.Int64).alias("_cs"),
            pl.col("block_sizes").str.strip_chars(",").str.split(",").alias("_sizes"),
            pl.col("block_starts").str.strip_chars(",").str.split(",").alias("_starts"),
        )
        .unique(subset=["sample", "transcript_id"], keep="first")
    )
    meta = transcripts.select(
        "sample",
        "transcript_id",
        "gene_id",
        "gene_name",
        pl.col("structural_category").alias("transcript_class"),
        pl.col("read_support").cast(pl.Float64).alias("expression"),
    )
    return (
        models.explode(["_sizes", "_starts"])
        .with_columns(
            (pl.col("_cs") + pl.col("_starts").cast(pl.Int64) + 1).alias("start"),
            (
                pl.col("_cs") + pl.col("_starts").cast(pl.Int64) + pl.col("_sizes").cast(pl.Int64)
            ).alias("end"),
            pl.lit("exon").alias("feature"),
        )
        .join(meta, on=["sample", "transcript_id"], how="inner")
        .select(list(EXPECTED_SCHEMA))
    )


def reference_blocks(gtf: pl.DataFrame, genes: pl.Series) -> pl.DataFrame:
    """Exon and CDS blocks of the reference transcripts of ``genes``."""
    return (
        gtf.filter(pl.col("feature").is_in(["exon", "CDS"]))
        .with_columns(_attr("gene_id").alias("gene_id"))
        .filter(pl.col("gene_id").is_in(genes.implode()))
        .select(
            _attr("transcript_id").alias("transcript_id"),
            "gene_id",
            pl.coalesce(_attr("gene_name"), pl.col("gene_id")).alias("gene_name"),
            pl.col("seqname").cast(pl.Utf8).alias("chrom"),
            pl.col("start").cast(pl.Int64, strict=False),
            pl.col("end").cast(pl.Int64, strict=False),
            pl.col("feature").cast(pl.Utf8),
            pl.col("strand").cast(pl.Utf8),
            pl.lit(REFERENCE).alias("transcript_class"),
            pl.lit(REFERENCE).alias("sample"),
            pl.lit(None, dtype=pl.Float64).alias("expression"),
        )
        .drop_nulls(["transcript_id", "start", "end"])
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    transcripts = sources["transcripts"]
    blocks = query_blocks(sources["bed"], transcripts)
    if blocks.is_empty():
        raise ValueError("TAMA merge: no exon block joined the transcripts collection")
    frames = [blocks]
    reference = sources.get("reference")
    if reference is not None and not reference.is_empty():
        genes = transcripts.filter(pl.col("structural_category") != "intergenic")[
            "gene_id"
        ].unique()
        frames.append(reference_blocks(reference, genes))
    return (
        pl.concat(frames, how="vertical_relaxed")
        .sort("gene_id", "sample", "transcript_id", "start")
        .select(list(EXPECTED_SCHEMA))
    )
