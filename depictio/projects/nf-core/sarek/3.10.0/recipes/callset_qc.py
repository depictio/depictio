"""One QC profile per callset (sample and caller), for a parallel-coordinates tile.

The megatest has two samples, so a per-sample profile would be two lines. The
unit the run actually varies is the callset: five callers on each of the two
depths. Every metric below is one a germline callset is judged on, read from
the caller's own `bcftools stats` report and from its snpEff-annotated VCF:

- ``n_records``: records in the VCF.
- ``snp_fraction``: SNPs over records.
- ``ts_tv``: transitions over transversions (exome expectation about 2.5 to 3).
- ``multiallelic_pct``: multiallelic sites per hundred records.
- ``pass_pct``: calls the caller kept (FILTER PASS or unset) per hundred.
- ``het_hom_ratio``: heterozygous over homozygous-alternate PASS calls
  (a single diploid genome sits near 1.5 to 2 on an exome).
- ``median_dp``: median read depth at the call.
- ``median_het_vaf``: median allele fraction of heterozygous PASS calls,
  which a clean caller keeps near 0.5.

Callsets with no SNP (Manta, a structural-variant caller) are dropped: every
SNV metric is undefined for them and a polyline through nulls draws nothing.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="summary", dc_ref="bcftools_stats_summary"),
    RecipeSource(ref="tstv", dc_ref="bcftools_stats_tstv"),
    RecipeSource(ref="variants", dc_ref="snpeff_ann_variants"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "callset": pl.Utf8,
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "n_records": pl.Int64,
    "snp_fraction": pl.Float64,
    "ts_tv": pl.Float64,
    "multiallelic_pct": pl.Float64,
    "pass_pct": pl.Float64,
    "het_hom_ratio": pl.Float64,
    "median_dp": pl.Float64,
    "median_het_vaf": pl.Float64,
}

_HET = ["0/1", "0|1", "1|0", "1/0"]
_HOM_ALT = ["1/1", "1|1"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample and caller with at least one SNP."""
    keys = ["sample", "caller"]
    summary = sources["summary"].select(
        *keys, "n_records", "n_snps", "snp_fraction", "n_multiallelic_sites"
    )
    tstv = sources["tstv"].select(*keys, "ts_tv")

    variants = sources["variants"]
    passing = pl.col("is_pass").fill_null(False)
    het = pl.col("gt").is_in(_HET)
    per_call = variants.group_by(keys).agg(
        (passing.mean() * 100).cast(pl.Float64).alias("pass_pct"),
        (passing & het).sum().alias("_n_het"),
        (passing & pl.col("gt").is_in(_HOM_ALT)).sum().alias("_n_hom"),
        pl.col("dp").median().cast(pl.Float64).alias("median_dp"),
        pl.col("vaf").filter(passing & het).median().cast(pl.Float64).alias("median_het_vaf"),
    )

    return (
        summary.join(tstv, on=keys, how="left")
        .join(per_call, on=keys, how="left")
        .filter(pl.col("n_snps") > 0)
        .with_columns(
            (pl.col("sample") + pl.lit(" / ") + pl.col("caller")).alias("callset"),
            pl.col("n_records").cast(pl.Int64),
            pl.col("snp_fraction").cast(pl.Float64),
            pl.col("ts_tv").cast(pl.Float64),
            (pl.col("n_multiallelic_sites") / pl.col("n_records") * 100)
            .cast(pl.Float64)
            .alias("multiallelic_pct"),
            pl.when(pl.col("_n_hom") > 0)
            .then(pl.col("_n_het") / pl.col("_n_hom"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("het_hom_ratio"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(keys)
    )
