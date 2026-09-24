"""riboWaltz read-length distribution per library.

``*.ribowaltz.length_distribution.tsv`` counts the reads of each length that
riboWaltz kept for P-site assignment. Ribosome-protected fragments sit in a
narrow band (about 28 to 30 nt for monosomes in most eukaryotes); a broad or
shifted distribution points at degraded RNA, incomplete nuclease digestion or
contaminating fragments.

Output: one row per library and read length.
    sample : Utf8     library id
    length : Int64    read length, nt
    count : Int64     reads of that length
    pct : Float64     share of the library's reads, in percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="lengths",
        glob_pattern="**/*.ribowaltz.length_distribution.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "length": pl.Int64,
    "count": pl.Int64,
    "pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Counts per length plus the within-library share."""
    df = sources["lengths"].select(
        pl.col("sample").cast(pl.Utf8).str.replace(r"\.ribowaltz$", "").alias("sample"),
        pl.col("length").cast(pl.Int64),
        pl.col("count").cast(pl.Float64).fill_null(0).round(0).cast(pl.Int64),
    )
    total = pl.col("count").sum().over("sample")
    return (
        df.with_columns((pl.col("count") * 100.0 / total).cast(pl.Float64).alias("pct"))
        .sort("sample", "length")
        .select(list(EXPECTED_SCHEMA))
    )
