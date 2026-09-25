"""Per-gene variant counts by impact class, from SnpEff's gene effect table.

``*_snpEff.genes.txt`` holds one row per transcript with the number of variants
SnpEff assigned to it in each impact class. It is the cheapest gene-level view
a variant-calling run publishes: no VCF parsing, no gene model, and it already
covers every gene the annotation database knows about.

The column set is NOT stable across callers (the ``variants_effect_*`` block
has one column per consequence term the callset actually produced), so a
header-based scan over a run's files has no single schema. The raw DC scans
with a separator that never occurs in the file, one full line per row, and this
recipe splits on tab itself and reads only the first eight fields, whose order
SnpEff fixes: GeneName, GeneId, TranscriptId, BioType and the four
``variants_impact_*`` counts.

Transcripts are summed up to the gene: a lollipop wants transcript resolution
and reads the annotated VCF instead, while an oncoplot, a burden heatmap and a
caller overlap all want one row per gene.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import sample_and_caller

RAW_DC_TAG = "snpeff_genes_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "gene_name": pl.Utf8,
    "gene_id": pl.Utf8,
    "biotype": pl.Utf8,
    "n_high": pl.Int64,
    "n_low": pl.Int64,
    "n_moderate": pl.Int64,
    "n_modifier": pl.Int64,
    "n_variants": pl.Int64,
    "n_coding": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Sum SnpEff's per-transcript impact counts up to the gene."""
    raw = sources["raw"]
    fields = pl.col("raw_line").str.split("\t")

    def count(index: int) -> pl.Expr:
        return fields.list.get(index, null_on_oob=True).cast(pl.Int64, strict=False).fill_null(0)

    rows = (
        raw.filter(pl.col("raw_line").is_not_null() & pl.col("raw_line").str.contains("\t"))
        .with_columns(
            fields.list.get(0, null_on_oob=True).alias("gene_name"),
            fields.list.get(1, null_on_oob=True).alias("gene_id"),
            fields.list.get(3, null_on_oob=True).alias("biotype"),
            count(4).alias("n_high"),
            count(5).alias("n_low"),
            count(6).alias("n_moderate"),
            count(7).alias("n_modifier"),
        )
        .join(sample_and_caller(raw), on="source_path", how="left")
    )

    genes = (
        rows.group_by(["sample", "caller", "gene_name", "gene_id", "biotype"])
        .agg(
            pl.col("n_high").sum(),
            pl.col("n_low").sum(),
            pl.col("n_moderate").sum(),
            pl.col("n_modifier").sum(),
        )
        .with_columns(
            (
                pl.col("n_high") + pl.col("n_low") + pl.col("n_moderate") + pl.col("n_modifier")
            ).alias("n_variants"),
            (pl.col("n_high") + pl.col("n_moderate")).alias("n_coding"),
        )
        .filter(pl.col("n_variants") > 0)
    )

    return genes.select(list(EXPECTED_SCHEMA)).sort(
        ["sample", "caller", "n_variants"], descending=[False, False, True]
    )
