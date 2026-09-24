"""Ribo-TISH ORF predictions, one row per library and ORF.

Ribo-TISH ``predict`` reports every supported start codon of an ORF as its own
row (``Tid``, ``Start``, ``Stop``, ``TisType``, ``GenomePos`` and the frame and
TIS statistics). Rows sharing a transcript and stop codon are the same ORF
read from different starts, so this recipe collapses them: the ORF keeps the
``Annotated`` call when one of its starts is the annotated start codon, else
the start with the smallest frame-test p-value.

The ORF key ``orf_id`` is ``<chrom>:<strand>:<stop>``, the genomic coordinate
of the last base before the stop codon's end on that strand, the same key the
``ribocode/orfs`` recipe builds. Two callers that report the same stop codon
therefore agree on the ORF even when they chose different starts or
transcripts.

``orf_class`` harmonises Ribo-TISH's ``TisType`` into the classes both callers
share: Annotated CDS, N-terminal variant (Extended or Truncated starts),
Upstream ORF, Downstream ORF, Internal ORF and Novel ORF.

Sources: every ``*_pred.txt`` Ribo-TISH wrote into a ``ribotish/`` folder, one
per library (the library id is the file name without ``_pred.txt``). The
pooled run nf-core/riboseq writes under ``ribotish_all/`` is not a library and
is not matched.

Output: see ``EXPECTED_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pred",
        glob_pattern="**/ribotish/*_pred.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["None", "NA", ""]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "orf_id": pl.Utf8,
    "transcript_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "gene_type": pl.Utf8,
    "chrom": pl.Utf8,
    "strand": pl.Utf8,
    "orf_type": pl.Utf8,
    "orf_class": pl.Utf8,
    "start_codon": pl.Utf8,
    "aa_length": pl.Int64,
    "start_sites": pl.Int64,
    "frame_qvalue": pl.Float64,
}


def orf_class(tis_type: pl.Expr) -> pl.Expr:
    """Ribo-TISH TisType (``Truncated:Known``, ``3'UTR:CDSFrameOverlap``...) to a shared class."""
    base = tis_type.str.split(":").list.first().str.to_lowercase()
    return (
        pl.when(base == "annotated")
        .then(pl.lit("Annotated CDS"))
        .when(base.is_in(["extended", "truncated"]))
        .then(pl.lit("N-terminal variant"))
        .when(base.is_in(["uorf", "5'utr"]))
        .then(pl.lit("Upstream ORF"))
        .when(base.is_in(["dorf", "3'utr"]))
        .then(pl.lit("Downstream ORF"))
        .when(base == "internal")
        .then(pl.lit("Internal ORF"))
        .otherwise(pl.lit("Novel ORF"))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library and ORF (transcript + stop codon)."""
    df = sources["pred"]
    pos = pl.col("GenomePos").str.extract_groups(
        r"^(?P<chrom>[^:]+):(?P<gs>\d+)-(?P<ge>\d+):(?P<strand>[+-])$"
    )
    df = df.with_columns(
        pl.col("source_path").str.extract(r"([^/]+)_pred\.txt$", 1).alias("sample"),
        pos.struct.field("chrom").alias("chrom"),
        pos.struct.field("strand").alias("strand"),
        pos.struct.field("gs").cast(pl.Int64).alias("_gs"),
        pos.struct.field("ge").cast(pl.Int64).alias("_ge"),
        pl.col("RiboPvalue").cast(pl.Float64).alias("_p"),
        pl.col("FrameQvalue").cast(pl.Float64).alias("frame_qvalue"),
        pl.col("AALen").cast(pl.Int64).alias("aa_length"),
        (pl.col("TisType").str.to_lowercase() == "annotated").alias("_annotated"),
    ).with_columns(
        pl.format(
            "{}:{}:{}",
            pl.col("chrom"),
            pl.col("strand"),
            pl.when(pl.col("strand") == "+").then(pl.col("_ge")).otherwise(pl.col("_gs") + 1),
        ).alias("orf_id")
    )
    ranked = df.sort(
        ["sample", "Tid", "Stop", "_annotated", "_p"],
        descending=[False, False, False, True, False],
        nulls_last=True,
    )
    collapsed = ranked.group_by(["sample", "Tid", "Stop"], maintain_order=True).agg(
        pl.all().first(), pl.len().cast(pl.Int64).alias("start_sites")
    )
    # One genomic ORF may be reported on several transcripts: keep one row per
    # library and ORF key, preferring the annotated call.
    collapsed = collapsed.sort(
        ["sample", "orf_id", "_annotated", "_p"], descending=[False, False, True, False]
    ).unique(subset=["sample", "orf_id"], keep="first", maintain_order=True)
    return (
        collapsed.select(
            pl.col("sample").cast(pl.Utf8),
            pl.col("orf_id"),
            pl.col("Tid").cast(pl.Utf8).alias("transcript_id"),
            pl.col("Gid").cast(pl.Utf8).alias("gene_id"),
            pl.col("Symbol").cast(pl.Utf8).alias("gene_name"),
            pl.col("GeneType").cast(pl.Utf8).alias("gene_type"),
            pl.col("chrom").cast(pl.Utf8),
            pl.col("strand").cast(pl.Utf8),
            pl.col("TisType").cast(pl.Utf8).alias("orf_type"),
            orf_class(pl.col("TisType").cast(pl.Utf8)).alias("orf_class"),
            pl.col("StartCodon").cast(pl.Utf8).alias("start_codon"),
            pl.col("aa_length"),
            pl.col("start_sites"),
            pl.col("frame_qvalue"),
        )
        .sort("sample", "orf_id")
        .select(list(EXPECTED_SCHEMA))
    )
