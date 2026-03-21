"""Transform QIIME2 barplot CSV (wide) to long-format taxonomy composition table."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="barplot_csv",
        path="qiime2/barplot/level-2.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "taxonomy": pl.Utf8,
    "count": pl.Float64,
    "habitat": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt wide barplot CSV to long format with taxonomy and counts.

    The barplot CSV embeds metadata columns (index, habitat, etc.) alongside
    taxonomy count columns. We extract habitat directly from the CSV — no
    external metadata join needed.
    """
    df = sources["barplot_csv"]

    # The barplot CSV has: index (sample), taxonomy columns, then metadata columns at end.
    # Metadata columns are known names that should be excluded from melting.
    metadata_col_names = {
        "index",
        "name",
        "condition",
        "condition_binary",
        "cycle",
        "bio_rep",
        "habitat",
        "Riv_vs_Gro",
        "Sed_vs_Soil",
        "sampling_date",
    }

    # Taxonomy columns are everything that's not index or a known metadata column
    taxonomy_cols = [c for c in df.columns if c not in metadata_col_names]

    if not taxonomy_cols:
        raise ValueError("No taxonomy columns found in barplot CSV")

    # Preserve habitat before melting (it's embedded in the CSV)
    keep_cols = ["index"]
    if "habitat" in df.columns:
        keep_cols.append("habitat")

    # Melt to long format
    df = df.unpivot(on=taxonomy_cols, index=keep_cols, variable_name="taxonomy", value_name="count")
    df = df.rename({"index": "sample"})
    df = df.with_columns(pl.col("count").cast(pl.Float64))

    # Filter out zero/null counts
    df = df.filter(pl.col("count").is_not_null() & (pl.col("count") > 0))

    # If habitat wasn't in the CSV, add null column
    if "habitat" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("habitat"))

    return df.select("sample", "taxonomy", "count", "habitat")
