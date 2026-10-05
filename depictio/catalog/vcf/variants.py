"""One row per variant call, read from the VCFs themselves.

Consumes the raw ``vcf_calls_raw`` scan (one full VCF line per row in
``raw_line``, plus ``source_path``) and hands back the long frame every
variant-level panel reads: sample, caller, locus, allele, quality, filter,
genotype, depth and variant allele fraction.

All the parsing lives in ``depictio.recipes.lib.vcf`` because the annotated
twin (``snpeff/ann_variants``) needs exactly the same fourteen columns plus
snpEff's ANN split, and recipes may not import each other.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import vcf_to_long

RAW_DC_TAG = "vcf_calls_raw"
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
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse every scanned VCF line into one row per call."""
    return vcf_to_long(sources["raw"]).sort(["sample", "caller", "chrom", "pos"])
