"""Each paired somatic call set against the normal's own germline calls.

A somatic caller reads a tumour against its matched normal, so a call that is really
inherited (a germline variant the caller failed to subtract) is a known failure. It is
visible from the data the run already holds: the normal sample was called on its own, and
a somatic call whose variant (contig, position and alleles) is a PASS germline call of the
pair's normal is a likely leak.

One row per somatic call of a *pair* (a tumour called on its own has no normal), with:

* the tumour allele fraction and depth, and the normal's (``normal_vaf``): from the paired
  call's own normal column when the caller wrote one, else from the matching germline call,
  with ``normal_vaf_source`` saying which;
* ``germline_callers``: how many callers made a PASS germline call of the same variant in
  the normal, and ``in_germline``, true when at least one did.

The normal's calls are ``vcf_variants`` (germline units only); the pairs are ``pairs``, so
a run without a tumour/normal pair has no such table and the comparison tab is skipped.

Output schema:
    unit : Utf8                 `<tumour>_vs_<normal>`
    patient, sample (the tumour), normal : Utf8
    caller, chrom, pos, ref, alt, variant_key, variant_type, filter_status, is_pass
    tumour_vaf, tumour_dp : the tumour's allele fraction and depth
    normal_vaf : Float64        the normal's allele fraction
    normal_vaf_source : Utf8    "paired call" or "germline call"; null when neither has one
    germline_callers : Int64    callers with a PASS germline call of this variant in the normal
    in_germline : Boolean       true when germline_callers is above 0
    origin : Utf8               the same fact as a label, for a colour: "Also in the normal's
                                germline calls" or "Not in the normal's germline calls"
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

ORIGIN_IN_GERMLINE = "Also in the normal's germline calls"
ORIGIN_SOMATIC_ONLY = "Not in the normal's germline calls"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="somatic",
        dc_ref="somatic_calls",
        input_schema={
            "unit": pl.Utf8,
            "unit_type": pl.Utf8,
            "variant_key": pl.Utf8,
            "tumour_vaf": pl.Float64,
            "normal_vaf": pl.Float64,
        },
    ),
    RecipeSource(
        ref="germline",
        dc_ref="vcf_variants",
        input_schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "variant_key": pl.Utf8,
            "is_pass": pl.Boolean,
            "vaf": pl.Float64,
        },
    ),
    RecipeSource(
        ref="pairs",
        dc_ref="pairs",
        input_schema={"pair_id": pl.Utf8, "patient": pl.Utf8, "tumour": pl.Utf8, "normal": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
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
    "filter_status": pl.Utf8,
    "is_pass": pl.Boolean,
    "tumour_vaf": pl.Float64,
    "tumour_dp": pl.Int64,
    "normal_vaf": pl.Float64,
    "normal_vaf_source": pl.Utf8,
    "germline_callers": pl.Int64,
    "in_germline": pl.Boolean,
    "origin": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join each paired somatic call to the PASS germline calls of its normal."""
    pairs = sources["pairs"].select(
        pl.col("pair_id").alias("unit"),
        pl.col("patient").alias("_patient"),
        pl.col("tumour").alias("sample"),
        "normal",
    )
    somatic = sources["somatic"].filter(pl.col("unit_type") == "paired")
    # The pairs are the design; a paired caller's unit the sheet does not list is dropped.
    paired = somatic.drop("patient", "sample", "normal", strict=False).join(
        pairs, on="unit", how="inner"
    )
    if paired.is_empty():
        raise ValueError(
            "sarek somatic_vs_germline: no somatic call of a tumour/normal pair listed in "
            "the sample sheet"
        )

    germline = (
        sources["germline"]
        .filter(pl.col("is_pass"))
        .group_by(["sample", "variant_key"])
        .agg(
            pl.col("caller").n_unique().cast(pl.Int64).alias("germline_callers"),
            pl.col("vaf").median().alias("_germline_vaf"),
        )
        .rename({"sample": "normal"})
    )
    out = paired.join(germline, on=["normal", "variant_key"], how="left").with_columns(
        pl.col("_patient").alias("patient"),
        pl.col("germline_callers").fill_null(0).cast(pl.Int64),
        pl.coalesce(pl.col("normal_vaf"), pl.col("_germline_vaf")).alias("normal_vaf"),
        pl.when(pl.col("normal_vaf").is_not_null())
        .then(pl.lit("paired call"))
        .when(pl.col("_germline_vaf").is_not_null())
        .then(pl.lit("germline call"))
        .alias("normal_vaf_source"),
    )
    return (
        out.with_columns((pl.col("germline_callers") > 0).alias("in_germline"))
        .with_columns(
            pl.when(pl.col("in_germline"))
            .then(pl.lit(ORIGIN_IN_GERMLINE))
            .otherwise(pl.lit(ORIGIN_SOMATIC_ONLY))
            .alias("origin")
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["unit", "caller", "chrom", "pos"])
    )
