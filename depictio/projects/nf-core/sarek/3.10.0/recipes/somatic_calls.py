"""One row per somatic call: a tumour/normal pair's, and a tumour called on its own.

Reads the raw VCF lines the ``vcf_calls_raw`` scan holds and keeps the calling units
that are not germline (``depictio.recipes.lib.sarek_units``): a pair
(``<tumour>_vs_<normal>``, called by Mutect2 and Strelka) and a single sample whose
samplesheet status is 1 (a tumour with no matched normal). The germline units stay in
``vcf_variants`` alone, and these two never share it.

The callers write their evidence under their own FORMAT keys, so the parsing is per
caller (``depictio.recipes.lib.vcf_somatic``): tumour allele fraction and depth, and the
normal's when the call is paired. A pair called by a caller without a parser is left out
rather than guessed at. The unit column keeps the pair's name, ``sample`` is the tumour
whose reads carry the call (what the hub's sample filter narrows), ``normal`` the pair's
normal, and ``unit_type`` is the colour and the filter that keep a tumour-only callset
from being drawn on the scale of a paired one.

A run with no somatic calls (no tumour, no paired caller, or a paired caller that found
nothing) has nothing to show, so the recipe raises and the collection, being optional, is
skipped: the Somatic calls tab does not appear.

Output schema:
    unit : Utf8          the sample, or `<tumour>_vs_<normal>`
    unit_type : Utf8     paired or tumour_only
    patient : Utf8       the patient (from the hub)
    sample : Utf8        the tumour sample the call was made in
    normal : Utf8        the pair's normal sample; null for a tumour on its own
    caller : Utf8        mutect2, strelka, ...
    chrom, pos, ref, alt, variant_key, variant_type, qual, filter_status, is_pass
    score : Float64      the caller's own confidence (Strelka SomaticEVS, Mutect2 TLOD, else QUAL)
    tumour_vaf, tumour_dp, normal_vaf, normal_dp : the allele fraction and depth in each sample
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sarek_units import PAIRED, TUMOUR_ONLY, unit_frame
from depictio.recipes.lib.vcf import SOURCE_PATH_COL, sample_and_caller
from depictio.recipes.lib.vcf_somatic import somatic_to_long

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
        input_schema={"sample_id": pl.Utf8, "patient": pl.Utf8, "status": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
    "unit_type": pl.Utf8,
    "patient": pl.Utf8,
    "sample": pl.Utf8,
    "normal": pl.Utf8,
    "caller": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_key": pl.Utf8,
    "variant_type": pl.Utf8,
    "qual": pl.Float64,
    "score": pl.Float64,
    "filter_status": pl.Utf8,
    "is_pass": pl.Boolean,
    "tumour_vaf": pl.Float64,
    "tumour_dp": pl.Int64,
    "normal_vaf": pl.Float64,
    "normal_dp": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse the pairs' and the tumours' VCF lines into one row per call."""
    raw = sources["raw"]
    units = unit_frame(sample_and_caller(raw)["sample"], sources["hub"])
    somatic = units.filter(pl.col("unit_type").is_in([PAIRED, TUMOUR_ONLY]))
    # The unit is the file name's first token, which is what `sample_and_caller` reads.
    paths = sample_and_caller(raw).join(
        somatic.select(pl.col("unit").alias("sample")), on="sample", how="inner"
    )
    calls = somatic_to_long(
        raw.join(paths.select(SOURCE_PATH_COL), on=SOURCE_PATH_COL, how="inner")
    )
    if calls.is_empty():
        raise ValueError(
            "sarek somatic_calls: no call of a tumour/normal pair (Mutect2, Strelka) or of a "
            "tumour called on its own among the run's VCFs"
        )
    return (
        calls.join(somatic, on="unit", how="left")
        .select(list(OUTPUT_SCHEMA))
        .sort(["unit", "caller", "chrom", "pos"])
    )
