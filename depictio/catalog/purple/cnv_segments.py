"""PURPLE's fitted copy-number segments as a canonical ``cnv_profile`` table.

``<tumor>.purple.cnv.somatic.tsv`` holds one row per fitted segment, tab
separated with a header::

    chromosome  start  end  copyNumber  bafCount  observedBAF  baf
    segmentStartSupport  segmentEndSupport  method  depthWindowCount  gcContent
    minStart  maxStart  minorAlleleCopyNumber  majorAlleleCopyNumber

``copyNumber`` is already absolute and purity-adjusted (PURPLE fits purity and
ploidy first), so it lands on the canonical row contract of
``depictio/recipes/lib/cnv_profile.py`` the way ASCAT's allele counts do:

* ``log2 = log2(copyNumber / 2)``, the ratio against a diploid baseline;
* ``baf`` is PURPLE's fitted BAF of the segment (0.5 balanced, 1 for LOH);
* ``copy_number`` is ``copyNumber`` rounded to the nearest integer;
* ``label`` spells the allele split, e.g. ``3.1 = 2.1 + 1.0``.

Two extra columns keep the allele-specific fit for the GenomeSpy locus view
(``minor_copy_number_col``): ``minor_copy_number`` and ``major_copy_number``.
The tumor id is the file name before ``.purple.cnv.somatic.tsv``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cnv_profile import (
    CNV_PROFILE_COLUMNS,
    CNV_PROFILE_SCHEMA,
    SEGMENT_ROW,
    finalise,
    safe_log2,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="segments",
        glob_pattern="**/purple/*.purple.cnv.somatic.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    **CNV_PROFILE_SCHEMA,
    "minor_copy_number": pl.Float64,
    "major_copy_number": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.purple\.cnv\.somatic\.tsv$"
_REQUIRED = ("chromosome", "start", "end", "copyNumber")


def _f(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Float64, strict=False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["segments"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"purple_cnv_segments: input lacks columns {missing}; got {df.columns}")
    for opt in ("baf", "minorAlleleCopyNumber", "majorAlleleCopyNumber", "depthWindowCount"):
        if opt not in df.columns:
            df = df.with_columns(pl.lit(None, pl.Utf8).alias(opt))

    cn = _f("copyNumber").clip(lower_bound=0.0)
    minor = _f("minorAlleleCopyNumber").clip(lower_bound=0.0)
    major = _f("majorAlleleCopyNumber").clip(lower_bound=0.0)
    keyed = df.with_columns(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("chromosome").cast(pl.Utf8).alias("chrom"),
        pl.col("start").cast(pl.Int64, strict=False).alias("start"),
        pl.col("end").cast(pl.Int64, strict=False).alias("end"),
        safe_log2(cn / 2.0).alias("log2"),
        _f("baf").alias("baf"),
        cn.round(0).cast(pl.Int64).alias("copy_number"),
        pl.lit(SEGMENT_ROW).alias("segment"),
        pl.format(
            "{} = {} + {}",
            cn.round(1),
            major.round(1),
            minor.round(1),
        ).alias("label"),
        _f("depthWindowCount").alias("depth"),
        minor.alias("minor_copy_number"),
        major.alias("major_copy_number"),
    )
    canonical = finalise(
        keyed.select([*CNV_PROFILE_COLUMNS, "minor_copy_number", "major_copy_number"])
    )
    # finalise() keeps the canonical columns only: join the allele split back on
    # the segment key (sample, chrom, start is unique per PURPLE segment).
    alleles = keyed.select("sample", "chrom", "start", "minor_copy_number", "major_copy_number")
    return canonical.join(alleles, on=["sample", "chrom", "start"], how="left").select(
        list(EXPECTED_SCHEMA)
    )
