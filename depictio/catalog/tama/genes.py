"""Genes of the TAMA merge transcriptome: how many isoforms each carries, and how novel they are.

Rolls ``tama/transcripts`` up to one row per sample and gene. A gene is the
reference gene the isoforms were assigned to (``annotated``) or, for isoforms
sharing nothing with the annotation, the TAMA gene they were merged into
(``novel``). The counts per structural category say whether a gene's diversity
is annotation (FSM, ISM) or discovery (NIC, NNC); ``dominant_isoform_pct`` says
whether one isoform carries the gene or its reads are spread.

Source:
    transcripts  ``tama_transcripts`` (catalog ``tama/transcripts``)

Output schema (one row per sample and gene; the gene and its measures first,
its position and id last, so a table reads left to right):
    gene_name : Utf8                reference gene name, else the TAMA gene id
    sample : Utf8                   sample
    gene_status : Utf8              annotated or novel
    isoforms : Int64                isoforms assigned to the gene
    read_support : Int64            FLNC reads over the gene's isoforms
    dominant_isoform_pct : Float64  reads of the best-supported isoform over the gene's reads, percent (2 decimals)
    top_category : Utf8             structural category carrying most of the gene's reads
    novel_isoforms : Int64          NIC plus NNC
    fsm_isoforms : Int64            full splice matches
    ism_isoforms : Int64            incomplete splice matches
    nic_isoforms : Int64            novel in catalog
    nnc_isoforms : Int64            novel not in catalog
    chrom : Utf8                    sequence
    start : Int64                   first base of the gene's isoforms, 1-based
    end : Int64                     last base of the gene's isoforms
    strand : Utf8                   strand of the gene's isoforms
    gene_id : Utf8                  reference gene, else ``<sample>:<tama gene>``
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

TRANSCRIPTS_DC_TAG = "tama_transcripts"

SOURCES: list[RecipeSource] = [RecipeSource(ref="transcripts", dc_ref=TRANSCRIPTS_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_name": pl.Utf8,
    "sample": pl.Utf8,
    "gene_status": pl.Utf8,
    "isoforms": pl.Int64,
    "read_support": pl.Int64,
    "dominant_isoform_pct": pl.Float64,
    "top_category": pl.Utf8,
    "novel_isoforms": pl.Int64,
    "fsm_isoforms": pl.Int64,
    "ism_isoforms": pl.Int64,
    "nic_isoforms": pl.Int64,
    "nnc_isoforms": pl.Int64,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "gene_id": pl.Utf8,
}

_KEY = ["sample", "gene_id"]


def _count(category: str) -> pl.Expr:
    return (pl.col("structural_category") == category).sum().cast(pl.Int64)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    tx = sources["transcripts"]
    if tx.is_empty():
        raise ValueError("TAMA genes: the transcripts collection is empty")
    top = (
        tx.group_by(*_KEY, "structural_category")
        .agg(pl.col("read_support").sum().alias("_reads"))
        .sort(*_KEY, "_reads", "structural_category", descending=[False, False, True, False])
        .unique(subset=_KEY, keep="first")
        .select(*_KEY, pl.col("structural_category").alias("top_category"))
    )
    genes = tx.group_by(_KEY).agg(
        pl.col("gene_name").first(),
        (pl.col("gene_id") != pl.col("sample") + ":" + pl.col("tama_gene_id"))
        .any()
        .alias("_annotated"),
        pl.col("chrom").first(),
        pl.col("start").min().cast(pl.Int64),
        pl.col("end").max().cast(pl.Int64),
        pl.col("strand").mode().first(),
        pl.len().cast(pl.Int64).alias("isoforms"),
        pl.col("read_support").sum().cast(pl.Int64),
        pl.col("read_support").max().alias("_top_reads"),
        _count("FSM").alias("fsm_isoforms"),
        _count("ISM").alias("ism_isoforms"),
        _count("NIC").alias("nic_isoforms"),
        _count("NNC").alias("nnc_isoforms"),
    )
    return (
        genes.join(top, on=_KEY, how="left")
        .with_columns(
            pl.when(pl.col("_annotated"))
            .then(pl.lit("annotated"))
            .otherwise(pl.lit("novel"))
            .alias("gene_status"),
            (pl.col("nic_isoforms") + pl.col("nnc_isoforms"))
            .cast(pl.Int64)
            .alias("novel_isoforms"),
            pl.when(pl.col("read_support") > 0)
            .then(pl.col("_top_reads") * 100.0 / pl.col("read_support"))
            .otherwise(None)
            .cast(pl.Float64)
            .round(2)
            .alias("dominant_isoform_pct"),
        )
        .sort(["sample", "read_support", "gene_id"], descending=[False, True, False])
        .select(list(EXPECTED_SCHEMA))
    )
