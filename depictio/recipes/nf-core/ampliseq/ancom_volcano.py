"""Transform ANCOM results and taxonomy table into volcano plot data."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ancom_data",
        path="qiime2/ancom/Category-habitat-ASV/data.tsv",
        format="TSV",
    ),
    RecipeSource(
        ref="taxonomy_table",
        path="qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "id": pl.Utf8,
    "taxonomy": pl.Utf8,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
    "W": pl.Float64,
    "clr": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Merge ANCOM results with taxonomy annotations for volcano plots."""
    ancom = sources["ancom_data"]
    tax = sources["taxonomy_table"]

    # Build taxonomy string from taxonomy table
    # The taxonomy table has ID, Kingdom, Phylum, etc. columns
    if "Kingdom" in tax.columns and "Phylum" in tax.columns:
        tax = tax.with_columns(
            (pl.col("Kingdom") + pl.lit(";") + pl.col("Phylum").fill_null("Unclassified")).alias(
                "taxonomy"
            ),
        )
        tax_cols = tax.select("ID", "taxonomy", "Kingdom", "Phylum")
    else:
        # Fallback: parse from ID column if taxonomy columns not present
        tax_cols = tax.select("ID").with_columns(
            pl.col("ID").alias("taxonomy"),
            pl.col("ID").str.split(";").list.get(0).alias("Kingdom"),
            pl.col("ID").str.split(";").list.get(1).fill_null("Unclassified").alias("Phylum"),
        )

    # Join ANCOM results with taxonomy
    result = ancom.join(tax_cols, left_on="id", right_on="ID", how="left")

    # Cast numeric columns
    result = result.with_columns(
        pl.col("W").cast(pl.Float64),
        pl.col("clr").cast(pl.Float64),
    )

    # Fill missing taxonomy
    result = result.with_columns(
        pl.col("taxonomy").fill_null(pl.col("id")),
        pl.col("Kingdom").fill_null("Unknown"),
        pl.col("Phylum").fill_null("Unclassified"),
    )

    return result.select("id", "taxonomy", "Kingdom", "Phylum", "W", "clr")
