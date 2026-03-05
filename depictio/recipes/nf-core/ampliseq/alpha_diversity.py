"""Transform QIIME2 alpha diversity vector to per-sample Faith PD table."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="faith_pd",
        path="diversity/alpha_diversity/faith_pd_vector/metadata.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "habitat": pl.Utf8,
    "faith_pd": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Transform raw Faith PD vector to clean per-sample table."""
    df = sources["faith_pd"]
    df = df.filter(~pl.col("id").str.starts_with("#"))
    df = df.rename({"id": "sample"})
    df = df.with_columns(pl.col("faith_pd").cast(pl.Float64))
    return df.select("sample", "habitat", "faith_pd")
