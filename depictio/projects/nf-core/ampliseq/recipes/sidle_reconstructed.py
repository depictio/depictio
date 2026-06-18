"""Melt the SIDLE cross-region reconstructed feature table to long per-sample taxonomy.

The multiregion/SIDLE sub-workflow reconstructs one feature table from per-region ASVs.
`reconstructed_merged.tsv` carries one row per reconstructed feature with its taxonomy
and per-sample counts (ID, Taxon, <sample columns…>). Melting it to the canonical
sample/taxonomy/count long shape lets the dashboard render composition (stacked bar /
table) the same way the standard route renders qiime2/barplot.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reconstructed",
        path="sidle/reconstructed/reconstructed_merged.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "sample": pl.Utf8,
    "count": pl.Float64,
    "taxonomy": pl.Utf8,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot per-sample count columns and split taxonomy into Kingdom/Phylum."""
    df = sources["reconstructed"].rename({"ID": "feature_id", "Taxon": "taxonomy"})

    sample_cols = [c for c in df.columns if c not in ("feature_id", "taxonomy")]
    df = df.with_columns(pl.col(sample_cols).cast(pl.Float64, strict=False))
    df = df.unpivot(
        on=sample_cols,
        index=["feature_id", "taxonomy"],
        variable_name="sample",
        value_name="count",
    )
    df = df.filter(pl.col("count").is_not_null() & (pl.col("count") > 0))
    df = df.with_columns(
        pl.col("taxonomy")
        .str.split(";")
        .list.get(0)
        .fill_null("Unclassified")
        .str.strip_chars()
        .alias("Kingdom"),
        pl.col("taxonomy")
        .str.split(";")
        .list.get(1)
        .fill_null("Unclassified")
        .str.strip_chars()
        .alias("Phylum"),
    )
    return df.select(["feature_id", "sample", "count", "taxonomy", "Kingdom", "Phylum"])
