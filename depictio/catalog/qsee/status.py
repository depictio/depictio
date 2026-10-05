"""QSEE's QC verdicts, one row per sample and checked feature.

QSEE (hmftools) collects the QC metrics of a WiGiTS run (BamTools coverage and
read quality, PURPLE purity, deleted genes, contamination, TINC, ...) and
checks each against its threshold. ``<tumor>.qsee.status.tsv.gz`` has one row
per sample and feature: the source tool, the feature, its value, the verdict
(``PASS``, ``WARN``, ``FAIL``) and the condition that fails it (e.g.
``<70``). Values are numeric; the condition is kept as text. ``check_id``
(sample, tool, feature) is the record key.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="status",
        glob_pattern="**/*.qsee.status.tsv.gz",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "check_id": pl.Utf8,
    "sample": pl.Utf8,
    "sample_type": pl.Utf8,
    "source_tool": pl.Utf8,
    "feature_type": pl.Utf8,
    "feature": pl.Utf8,
    "value": pl.Float64,
    "qc_status": pl.Utf8,
    "fail_condition": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["status"]
    if "FailCondition" not in df.columns:
        df = df.with_columns(pl.lit(None, pl.Utf8).alias("FailCondition"))
    return (
        df.select(
            pl.format("{}|{}|{}", "SampleId", "SourceTool", "FeatureName").alias("check_id"),
            pl.col("SampleId").alias("sample"),
            pl.col("SampleType").str.to_lowercase().alias("sample_type"),
            pl.col("SourceTool").alias("source_tool"),
            pl.col("FeatureType").alias("feature_type"),
            pl.col("FeatureName").alias("feature"),
            pl.col("FeatureValue").cast(pl.Float64, strict=False).alias("value"),
            pl.col("QcStatus").alias("qc_status"),
            pl.when(pl.col("FailCondition").str.strip_chars() == "")
            .then(None)
            .otherwise(pl.col("FailCondition"))
            .alias("fail_condition"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "source_tool", "feature"])
    )
