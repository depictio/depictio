"""One row per germline variant call, read from the caller VCFs themselves.

Overrides the catalog's ``vcf/variants`` (the same fourteen columns, parsed by
``depictio.recipes.lib.vcf``) for a run that may also hold somatic calls. sarek
publishes a pair's calls (``<tumour>_vs_<normal>``) and a tumour's own calls beside the
germline ones, under the same ``variant_calling/<caller>/<unit>/`` layout, so the scan
cannot tell them apart. The sample hub can: only the units of a *germline* sample (status
0, or a sample the sheet does not describe) are kept, so the germline tabs never read a
somatic call. The somatic ones are ``somatic_calls``.

A run with no tumour keeps every unit, so its table is the catalog recipe's.
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
        dc_ref="vcf_calls_raw",
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
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse every germline unit's VCF lines into one row per call."""
    calls = vcf_to_long(sources["raw"])
    germline = keep_unit_types(calls, sources.get("hub"), GERMLINE)
    return germline.sort(["sample", "caller", "chrom", "pos"])
