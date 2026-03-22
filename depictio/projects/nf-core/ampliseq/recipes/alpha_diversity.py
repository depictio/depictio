"""Transform QIIME2 alpha diversity vector to per-sample Faith PD table.

When ampliseq is run with --metadata, QIIME2 embeds metadata columns directly
into the faith_pd_vector/metadata.tsv file (e.g. habitat). This recipe handles
both cases: with and without embedded metadata columns.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="faith_pd",
        path="qiime2/diversity/alpha_diversity/faith_pd_vector/metadata.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "faith_pd": pl.Float64,
}
# Any metadata columns embedded by QIIME2 (e.g. habitat) are passed through.
# Their names are user-defined so they are not declared here.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Transform raw Faith PD vector to clean per-sample table.

    Returns all columns from the file: at minimum sample + faith_pd.
    If QIIME2 embedded metadata columns (e.g. habitat), they are preserved.
    """
    df = sources["faith_pd"]
    df = df.filter(~pl.col("id").str.starts_with("#"))
    df = df.rename({"id": "sample"})
    df = df.with_columns(pl.col("faith_pd").cast(pl.Float64))
    return df
