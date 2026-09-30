"""hmftools BamTools coverage distribution, as a cumulative curve per sample.

``<sample>.bam_metric.coverage.tsv`` is a histogram: the number of genome (or
target) bases at each read depth, from 0 to the coverage cap. It is turned into
the curve a reader actually compares, the fraction of bases covered at least
``coverage`` times, next to the per-depth fraction. One row per sample and
depth; BamTools caps the depth (250 by default), so a series stays within the
``profile`` kind's point budget. The sample id is the file name before
``.bam_metric.coverage.tsv``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="coverage",
        glob_pattern="**/*.bam_metric.coverage.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "coverage": pl.Int64,
    "bases": pl.Int64,
    "fraction": pl.Float64,
    "fraction_at_least": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.bam_metric\.coverage\.tsv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["coverage"].select(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("Coverage").cast(pl.Int64, strict=False).alias("coverage"),
        pl.col("Count").cast(pl.Int64, strict=False).alias("bases"),
    )
    total = pl.col("bases").sum().over("sample")
    return (
        df.filter(pl.col("coverage").is_not_null())
        .sort(["sample", "coverage"])
        .with_columns(
            (pl.col("bases") / total).alias("fraction"),
            # at least k = total minus the bases below k
            ((total - pl.col("bases").cum_sum().over("sample") + pl.col("bases")) / total).alias(
                "fraction_at_least"
            ),
        )
        .select(list(EXPECTED_SCHEMA))
    )
