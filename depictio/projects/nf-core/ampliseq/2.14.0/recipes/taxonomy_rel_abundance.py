"""Transform QIIME2 relative abundance table to long-format per-sample taxonomy table."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rel_table",
        path="qiime2/rel_abundance_tables/rel-table-2.tsv",
        format="TSV",
        read_kwargs={"skip_rows": 1},
    ),
    RecipeSource(
        ref="metadata",
        dc_ref="metadata",  # Reference another DC
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "taxonomy": pl.Utf8,
    "rel_abundance": pl.Float64,
    "habitat": pl.Utf8,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot wide abundance table and join with metadata (v2.14: metadata column is 'sample')."""
    df = sources["rel_table"]
    df = df.rename({"#OTU ID": "taxonomy"})

    sample_cols = [c for c in df.columns if c != "taxonomy"]
    df = df.with_columns(pl.col(sample_cols).cast(pl.Float64))
    df = df.unpivot(
        on=sample_cols, index="taxonomy", variable_name="sample", value_name="rel_abundance"
    )
    df = df.filter(pl.col("rel_abundance").is_not_null() & (pl.col("rel_abundance") > 0))
    df = df.with_columns(
        pl.col("taxonomy").str.split(";").list.get(0).alias("Kingdom"),
        pl.col("taxonomy").str.split(";").list.get(1).fill_null("Unclassified").alias("Phylum"),
    )

    metadata = sources["metadata"].select("sample", "habitat")
    df = df.join(metadata, on="sample", how="left")

    return df.select("sample", "taxonomy", "rel_abundance", "habitat", "Kingdom", "Phylum")
