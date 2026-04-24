"""Transform QIIME2 alpha rarefaction wide CSV to long-format rarefaction curves."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="faith_pd_csv",
        path="qiime2/alpha-rarefaction/faith_pd.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "depth": pl.Int64,
    "iter": pl.Int64,
    "faith_pd": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt wide rarefaction table (depth-X_iter-Y columns) to long format."""
    df = sources["faith_pd_csv"]

    # Identify value columns (depth-*_iter-* pattern)
    id_col = "sample-id"
    value_cols = [c for c in df.columns if c.startswith("depth-")]

    # Melt to long format
    df = df.unpivot(on=value_cols, index=id_col, variable_name="depth_iter", value_name="faith_pd")
    df = df.rename({id_col: "sample"})

    # Extract depth and iter from column names like "depth-500_iter-3"
    df = df.with_columns(
        pl.col("depth_iter").str.extract(r"depth-(\d+)", 1).cast(pl.Int64).alias("depth"),
        pl.col("depth_iter").str.extract(r"iter-(\d+)", 1).cast(pl.Int64).alias("iter"),
        pl.col("faith_pd").cast(pl.Float64),
    )

    df = df.drop_nulls(subset=["faith_pd"])

    return df.select("sample", "depth", "iter", "faith_pd")
