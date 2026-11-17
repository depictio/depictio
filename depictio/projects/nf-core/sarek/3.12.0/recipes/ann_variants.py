"""One row per annotated germline variant call, read from SnpEff's annotated VCF.

Overrides the catalog's ``snpeff/ann_variants`` (the same columns, parsed by
``depictio.recipes.lib.vcf``) for a run that may also hold somatic calls: sarek annotates
a pair's calls and a tumour's own calls too, in the same ``annotation/<caller>/<unit>/``
layout. Only the units of a *germline* sample are kept (``vcf_variants`` does the same),
so the consequence, gene and protein tabs read the germline callsets. The sample hub says
which unit is which (``depictio.recipes.lib.sarek_units``).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sarek_units import GERMLINE, keep_unit_types
from depictio.recipes.lib.vcf import vcf_to_long

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        dc_ref="snpeff_ann_vcf_raw",
        input_schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
    ),
    RecipeSource(
        ref="hub",
        dc_ref="samples",
        input_schema={"sample_id": pl.Utf8, "status": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
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
    """Parse every germline unit's annotated VCF lines into one row per annotated call."""
    calls = vcf_to_long(sources["raw"], with_annotation=True)
    germline = keep_unit_types(calls, sources.get("hub"), GERMLINE)
    return germline.sort(["sample", "caller", "chrom", "pos"])
