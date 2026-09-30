"""PURPLE's copy number per gene, with a call a reader can filter on.

``<tumor>.purple.cnv.gene.tsv`` has one row per gene transcript with the
minimum and maximum copy number across the gene, the minimum minor-allele copy
number and ``relativeMinCopyNumber`` (minimum copy number over the sample
ploidy). Only the canonical transcript is kept, so there is one row per gene.

``cn_event`` names the state of the gene with PURPLE's own driver cut-offs
(hmftools PURPLE documentation, "Copy number drivers"):

* ``AMP``: the whole gene is above 3 times the sample ploidy;
* ``PARTIAL_AMP``: only part of it is (the maximum is, the minimum is not);
* ``DEL``: the whole gene is below 0.5 copies (homozygous deletion);
* ``PARTIAL_DEL``: part of the gene is below 0.5 copies;
* ``LOH``: at least 0.5 copies remain but the minor allele is lost (below 0.5);
* ``NEUTRAL``: none of the above.

The gene's reporting status and driver type come through unchanged. The tumor
id is the file name before ``.purple.cnv.gene.tsv``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="genes",
        glob_pattern="**/purple/*.purple.cnv.gene.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "gene": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "chromosome_band": pl.Utf8,
    "transcript": pl.Utf8,
    "min_copy_number": pl.Float64,
    "max_copy_number": pl.Float64,
    "min_minor_allele_copy_number": pl.Float64,
    "relative_min_copy_number": pl.Float64,
    "somatic_regions": pl.Int64,
    "cn_event": pl.Utf8,
    "reported_status": pl.Utf8,
    "driver_type": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.purple\.cnv\.gene\.tsv$"

#: PURPLE's copy-number driver cut-offs.
AMP_RELATIVE_CN = 3.0
DEL_ABSOLUTE_CN = 0.5
LOH_MINOR_CN = 0.5


def _f(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Float64, strict=False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["genes"]
    if "isCanonical" in df.columns:
        df = df.filter(pl.col("isCanonical").str.to_lowercase() == "true")
    for opt in ("chromosomeBand", "transcriptId", "reportedStatus", "driverType", "somaticRegions"):
        if opt not in df.columns:
            df = df.with_columns(pl.lit(None, pl.Utf8).alias(opt))

    min_cn, max_cn = _f("minCopyNumber"), _f("maxCopyNumber")
    minor = _f("minMinorAlleleCopyNumber")
    rel_min = _f("relativeMinCopyNumber")
    # relative max = max CN over ploidy = rel_min * max / min, undefined at min 0
    ploidy = pl.when(min_cn > 0).then(min_cn / rel_min).otherwise(None)
    rel_max = max_cn / ploidy
    event = (
        pl.when(rel_min > AMP_RELATIVE_CN)
        .then(pl.lit("AMP"))
        .when(rel_max > AMP_RELATIVE_CN)
        .then(pl.lit("PARTIAL_AMP"))
        .when(max_cn < DEL_ABSOLUTE_CN)
        .then(pl.lit("DEL"))
        .when(min_cn < DEL_ABSOLUTE_CN)
        .then(pl.lit("PARTIAL_DEL"))
        .when(minor < LOH_MINOR_CN)
        .then(pl.lit("LOH"))
        .otherwise(pl.lit("NEUTRAL"))
    )
    return (
        df.select(
            pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
            pl.col("gene").alias("gene"),
            pl.col("chromosome").alias("chrom"),
            pl.col("start").cast(pl.Int64, strict=False),
            pl.col("end").cast(pl.Int64, strict=False),
            pl.col("chromosomeBand").alias("chromosome_band"),
            pl.col("transcriptId").alias("transcript"),
            min_cn.alias("min_copy_number"),
            max_cn.alias("max_copy_number"),
            minor.alias("min_minor_allele_copy_number"),
            rel_min.alias("relative_min_copy_number"),
            pl.col("somaticRegions").cast(pl.Int64, strict=False).alias("somatic_regions"),
            event.alias("cn_event"),
            pl.col("reportedStatus").alias("reported_status"),
            pl.col("driverType").alias("driver_type"),
        )
        .filter(pl.col("sample").is_not_null() & pl.col("gene").is_not_null())
        .unique(subset=["sample", "gene"], keep="first", maintain_order=True)
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "chrom", "start"])
    )
