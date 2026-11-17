"""One row per callset (sample and caller): what a germline callset is judged on.

Built from the per-variant rows of ``vcf/variants`` rather than from a
``bcftools stats`` report, because not every variant-calling pipeline runs
bcftools stats (nf-core/rnavar does not) while every one publishes its VCFs.

The counts split the caller's own FILTER column: ``calls`` is every record,
``pass_calls`` the ones it kept. Everything after ``pass_pct`` is computed on
the PASS calls only, since a filtered call is the caller saying "do not read
this":

* ``ts_tv``: transitions over transversions of the PASS SNVs (first ALT allele).
  About 2.0 to 2.1 genome-wide in a human germline callset and higher in coding
  sequence; RNA editing (A to G on the transcript) pushes an RNA callset up.
* ``het_hom_ratio``: heterozygous over homozygous-alternate PASS calls. About 1.5
  to 2 in an outbred human sample; a cell line that lost heterozygosity reads lower.
* ``median_het_vaf``: allele fraction of the heterozygous PASS calls, near 0.5
  for a clean diploid call; allele-specific expression spreads it on RNA.

A ratio with an empty denominator is null, never 0.

Output schema:
    sample, caller : Utf8
    calls : Int64               every record of the VCF
    pass_calls : Int64          records the caller kept (FILTER PASS or .)
    pass_pct : Float64          pass_calls over calls, percent
    snvs, indels, mnps : Int64  PASS calls by type
    multiallelic : Int64        PASS calls with more than one ALT allele
    transitions : Int64         PASS SNVs that are A<->G or C<->T
    transversions : Int64       the other PASS SNVs
    ts_tv : Float64             transitions over transversions
    het, hom_alt : Int64        PASS calls by genotype class
    het_hom_ratio : Float64     het over hom_alt
    median_qual : Float64       median QUAL of the PASS calls
    median_dp : Float64         median read depth at the PASS calls
    median_het_vaf : Float64    median allele fraction of the heterozygous PASS calls
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        dc_ref="vcf_variants",
        input_schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "ref": pl.Utf8,
            "alt": pl.Utf8,
            "variant_type": pl.Utf8,
            "qual": pl.Float64,
            "is_pass": pl.Boolean,
            "gt": pl.Utf8,
            "dp": pl.Int64,
            "vaf": pl.Float64,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "calls": pl.Int64,
    "pass_calls": pl.Int64,
    "pass_pct": pl.Float64,
    "snvs": pl.Int64,
    "indels": pl.Int64,
    "mnps": pl.Int64,
    "multiallelic": pl.Int64,
    "transitions": pl.Int64,
    "transversions": pl.Int64,
    "ts_tv": pl.Float64,
    "het": pl.Int64,
    "hom_alt": pl.Int64,
    "het_hom_ratio": pl.Float64,
    "median_qual": pl.Float64,
    "median_dp": pl.Float64,
    "median_het_vaf": pl.Float64,
}

_TRANSITIONS = ["AG", "GA", "CT", "TC"]


def _ratio(num: str, den: str, digits: int = 3) -> pl.Expr:
    return (
        pl.when(pl.col(den) > 0)
        .then(pl.col(num).cast(pl.Float64) / pl.col(den).cast(pl.Float64))
        .otherwise(None)
        .round(digits)
    )


def genotype_class() -> pl.Expr:
    """het (two different alleles), hom_alt (two copies of one ALT), else ref / missing."""
    alleles = pl.col("gt").str.replace_all(r"\|", "/").str.split("/")
    first = alleles.list.get(0, null_on_oob=True)
    second = alleles.list.get(1, null_on_oob=True)
    return (
        pl.when(first.is_null() | second.is_null() | (first == ".") | (second == "."))
        .then(pl.lit("missing"))
        .when(first != second)
        .then(pl.lit("het"))
        .when(first == "0")
        .then(pl.lit("hom_ref"))
        .otherwise(pl.lit("hom_alt"))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count every callset, split its PASS calls and compute the three ratios."""
    v = sources["variants"].with_columns(
        genotype_class().alias("_gt_class"),
        pl.col("alt").str.split(",").list.get(0, null_on_oob=True).alias("_alt1"),
    )
    passed = pl.col("is_pass").fill_null(False)
    snv = passed & (pl.col("variant_type") == "SNP")
    sub = pl.concat_str([pl.col("ref"), pl.col("_alt1")]).str.to_uppercase()
    out = v.group_by(["sample", "caller"]).agg(
        pl.len().cast(pl.Int64).alias("calls"),
        passed.sum().cast(pl.Int64).alias("pass_calls"),
        snv.sum().cast(pl.Int64).alias("snvs"),
        (passed & (pl.col("variant_type") == "INDEL")).sum().cast(pl.Int64).alias("indels"),
        (passed & (pl.col("variant_type") == "MNP")).sum().cast(pl.Int64).alias("mnps"),
        (passed & pl.col("alt").str.contains(",")).sum().cast(pl.Int64).alias("multiallelic"),
        (snv & sub.is_in(_TRANSITIONS)).sum().cast(pl.Int64).alias("transitions"),
        (snv & ~sub.is_in(_TRANSITIONS)).sum().cast(pl.Int64).alias("transversions"),
        (passed & (pl.col("_gt_class") == "het")).sum().cast(pl.Int64).alias("het"),
        (passed & (pl.col("_gt_class") == "hom_alt")).sum().cast(pl.Int64).alias("hom_alt"),
        pl.col("qual").filter(passed).median().cast(pl.Float64).alias("median_qual"),
        pl.col("dp").filter(passed).median().cast(pl.Float64).alias("median_dp"),
        pl.col("vaf")
        .filter(passed & (pl.col("_gt_class") == "het"))
        .median()
        .cast(pl.Float64)
        .alias("median_het_vaf"),
    )
    return (
        out.with_columns(
            (_ratio("pass_calls", "calls", 4) * 100.0).round(2).alias("pass_pct"),
            _ratio("transitions", "transversions").alias("ts_tv"),
            _ratio("het", "hom_alt").alias("het_hom_ratio"),
            pl.col("median_het_vaf").round(4),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "caller"])
    )
