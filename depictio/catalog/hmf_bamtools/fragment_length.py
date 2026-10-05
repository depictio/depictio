"""hmftools BamTools fragment length distribution, decimated for a profile.

``<sample>.bam_metric.frag_length.tsv`` counts read pairs per insert size, one
row per length (often a thousand or more). Lengths are grouped into windows of
equal width so each sample keeps at most ``MAX_POINTS`` points (the ``profile``
kind is never sampled); ``fraction`` is the share of the sample's pairs in the
window, so libraries of different depth overlay. The sample id is the file name
before ``.bam_metric.frag_length.tsv``.
"""

from __future__ import annotations

import math

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="frag",
        glob_pattern="**/*.bam_metric.frag_length.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "fragment_length": pl.Int64,
    "pairs": pl.Int64,
    "fraction": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

MAX_POINTS = 200
_SAMPLE_RE = r"([^/]+)\.bam_metric\.frag_length\.tsv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = (
        sources["frag"]
        .select(
            pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
            pl.col("FragmentLength").cast(pl.Int64, strict=False).alias("length"),
            pl.col("Count").cast(pl.Int64, strict=False).alias("pairs"),
        )
        .drop_nulls()
    )
    span = (df["length"].max() or 0) - (df["length"].min() or 0) + 1
    width = max(1, math.ceil(span / MAX_POINTS))
    binned = (
        df.with_columns(((pl.col("length") // width) * width + width // 2).alias("fragment_length"))
        .group_by(["sample", "fragment_length"])
        .agg(pl.col("pairs").sum().cast(pl.Int64))
    )
    return (
        binned.with_columns(
            (pl.col("pairs") / pl.col("pairs").sum().over("sample")).alias("fraction")
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "fragment_length"])
    )
