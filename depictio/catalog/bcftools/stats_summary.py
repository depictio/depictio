"""Per-sample, per-caller variant record counts from `bcftools stats`.

`bcftools stats <vcf>` writes one flat text report per VCF with `#`-comment
documentation lines and tab-separated data rows tagged by record type (`SN`,
`TSTV`, `SiS`, `AF`, `QUAL`, ...). The `SN` rows carry the headline counts
(records, SNPs, indels, multiallelic sites); this recipe reads only those.

Multi-caller pipelines (sarek's five germline callers, any tumour/normal
somatic caller set) write one such file per `<caller>/<sample>/` directory,
and the file's own `ID 0 <filename>` line never names the caller or the
sample, both live only in the directory path. The raw DC therefore scans
with `include_file_paths: source_path` and this recipe reads them off the
path with a regex, not off the file content.

Row width varies by record type (`SN` is 4 tab-separated fields, `TSTV` is
8, `SiS`/`AF` are wider still), and `has_header: false` infers the column
count from the file's first data row, always an `SN` row here, which
would truncate every wider row before a fixed `new_columns` list could see
past column 4. The raw DC sidesteps this by scanning with a separator that
never appears in the file, so each full line lands in one `raw_line` text
column; this recipe splits it on `\t` itself after filtering to `SN` rows.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "bcftools_stats_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "n_records": pl.Int64,
    "n_no_alts": pl.Int64,
    "n_snps": pl.Int64,
    "n_mnps": pl.Int64,
    "n_indels": pl.Int64,
    "n_others": pl.Int64,
    "n_multiallelic_sites": pl.Int64,
    "n_multiallelic_snp_sites": pl.Int64,
    # Derived, for the caller-comparison dot plot: naturally 0-1 (dot_plot's
    # frac_expressing) and a log-scaled magnitude (its mean_expression), so a
    # structural-variant caller with a two-order-of-magnitude-smaller record
    # count than the SNP/indel callers still reads on the same plot.
    "snp_fraction": pl.Float64,
    "log10_n_records": pl.Float64,
}

# reports/bcftools/<caller>/<sample>/<sample>.<caller...>.bcftools_stats.txt
_PATH_RE = r"reports/bcftools/([^/]+)/([^/]+)/"

# `SN` key text (column c2, colon included) -> output column name.
_KEY_MAP: dict[str, str] = {
    "number of records:": "n_records",
    "number of no-ALTs:": "n_no_alts",
    "number of SNPs:": "n_snps",
    "number of MNPs:": "n_mnps",
    "number of indels:": "n_indels",
    "number of others:": "n_others",
    "number of multiallelic sites:": "n_multiallelic_sites",
    "number of multiallelic SNP sites:": "n_multiallelic_snp_sites",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample x caller, pivoting the `SN` block's key/value rows."""
    df = sources["raw"]

    sn = (
        df.filter(pl.col("raw_line").str.starts_with("SN\t"))
        .with_columns(pl.col("raw_line").str.split("\t").alias("fields"))
        .with_columns(
            pl.col("source_path").str.extract(_PATH_RE, 1).alias("caller"),
            pl.col("source_path").str.extract(_PATH_RE, 2).alias("sample"),
            pl.col("fields").list.get(2).str.strip_chars().alias("key"),
            pl.col("fields").list.get(3).cast(pl.Int64, strict=False).alias("value"),
        )
        .filter(pl.col("key").is_in(list(_KEY_MAP)))
        .with_columns(pl.col("key").replace(_KEY_MAP).alias("metric"))
    )

    wide = sn.pivot(on="metric", index=["sample", "caller"], values="value")

    # A caller/sample pair missing one SN line entirely (should not happen,
    # but bcftools stats has no schema contract) still gets every column.
    for col in EXPECTED_SCHEMA:
        if col in ("sample", "caller", "snp_fraction", "log10_n_records"):
            continue
        if col not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Int64).alias(col))

    wide = wide.with_columns(
        pl.when(pl.col("n_records") > 0)
        .then(pl.col("n_snps") / pl.col("n_records"))
        .otherwise(0.0)
        .alias("snp_fraction"),
        (pl.col("n_records") + 1).log(base=10).alias("log10_n_records"),
    )

    return wide.select(list(EXPECTED_SCHEMA)).sort(["sample", "caller"])
