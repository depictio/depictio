"""One row per annotated variant call, read from SnpEff's annotated VCF.

Same fourteen columns as ``vcf/variants`` plus SnpEff's first ``ANN`` entry
split into gene, gene id, impact class, consequence and protein change. SnpEff
writes one ANN entry per overlapping transcript, ordered most severe first, so
the first entry is the canonical consequence its own summary reports count.

This is the collection a variant-calling template reads for everything that is
per-variant AND functional: impact composition, consequence tables, the
gene-level lollipop and the caller-against-caller variant overlap. It is also
the only per-variant view of a caller whose unannotated VCF did not survive the
bucket sync (see the sarek template's VALIDATION_REPORT, SK-D6).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import vcf_to_long

RAW_DC_TAG = "snpeff_ann_vcf_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "variant_key": pl.Utf8,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "qual": pl.Float64,
    "filter_status": pl.Utf8,
    "is_pass": pl.Boolean,
    "gt": pl.Utf8,
    "dp": pl.Int64,
    "vaf": pl.Float64,
    "gene": pl.Utf8,
    "gene_id": pl.Utf8,
    "impact": pl.Utf8,
    "consequence": pl.Utf8,
    "hgvs_p": pl.Utf8,
    "aa_pos": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse every scanned annotated VCF line into one row per annotated call."""
    return vcf_to_long(sources["raw"], with_annotation=True).sort(
        ["sample", "caller", "chrom", "pos"]
    )
