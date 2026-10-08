"""Sample and caller of a ``bcftools stats`` report, read from the report itself.

A ``bcftools stats`` file never names its sample or its caller in a dedicated
field, but its ``ID`` line records the VCF it was computed from, and every
nf-core pipeline names that VCF ``<sample>.<caller>[.<qualifier>...].vcf.gz``::

    ID  0  NA12878_75M.haplotypecaller.filtered.vcf.gz     sarek
    ID  0  NA12878_75M.manta.diploid_sv.vcf.gz             sarek
    ID  0  COD076.haplotypecaller.vcf.gz                   eager

Reading the two ids off that line is the only rule that survives the layouts
the reports are published under: sarek's megatest writes
``reports/bcftools/<caller>/<sample>/``, sarek's own docs describe
``reports/bcftools/<sample>/<caller>/``, and eager writes a flat
``bcftools/stats/<sample>.vcf.stats``. A regex on the directory order silently
swapped the two columns on one layout and matched nothing on the other, which
is why eager's genotyping tab had no bcftools tile at all.

When the ``ID`` line is missing the report's own file name is split the same
way, and a name with a single token falls back to the grandparent directory
for the caller (sarek's layout) so the column is never null.

Shared here because the two bcftools catalog recipes need exactly this and
recipes may not import each other.
"""

from __future__ import annotations

import polars as pl

#: Column holding one full report line (the raw DC scans with a separator that
#: never occurs in the file, so every line lands in this single column).
RAW_LINE_COL = "raw_line"
#: Column carrying the report's path (``include_file_paths`` on the raw DC).
SOURCE_PATH_COL = "source_path"

_ID_LINE_RE = r"^ID\t\d+\t(.+?)\s*$"
_VCF_SUFFIX_RE = r"\.(?:vcf|bcf)(?:\.b?gz)?$"
_REPORT_SUFFIX_RE = r"(?:\.bcftools_stats\.txt|\.vcf\.stats|\.stats|\.txt)$"


def sample_and_caller(raw: pl.DataFrame) -> pl.DataFrame:
    """One row per ``source_path`` with the ``sample`` and ``caller`` it belongs to.

    Join the result back onto the raw frame on ``source_path``.
    """
    paths = raw.select(pl.col(SOURCE_PATH_COL)).unique()
    id_lines = (
        raw.filter(pl.col(RAW_LINE_COL).str.starts_with("ID\t"))
        .with_columns(pl.col(RAW_LINE_COL).str.extract(_ID_LINE_RE, 1).alias("vcf_name"))
        .group_by(SOURCE_PATH_COL)
        .agg(pl.col("vcf_name").drop_nulls().first())
    )
    joined = paths.join(id_lines, on=SOURCE_PATH_COL, how="left")
    if "vcf_name" not in joined.columns:
        joined = joined.with_columns(pl.lit(None, dtype=pl.Utf8).alias("vcf_name"))

    report_stem = (
        pl.col(SOURCE_PATH_COL).str.split("/").list.last().str.replace(_REPORT_SUFFIX_RE, "")
    )
    vcf_stem = pl.col("vcf_name").str.split("/").list.last().str.replace(_VCF_SUFFIX_RE, "")
    tokens = pl.coalesce(vcf_stem, report_stem).str.split(".")
    grandparent = pl.col(SOURCE_PATH_COL).str.extract(r"([^/]+)/[^/]+/[^/]+$", 1)

    return joined.select(
        pl.col(SOURCE_PATH_COL),
        tokens.list.get(0, null_on_oob=True).alias("sample"),
        pl.coalesce(
            tokens.list.get(1, null_on_oob=True),
            grandparent,
            pl.lit("unknown"),
        ).alias("caller"),
    )
