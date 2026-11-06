"""Indel size per guide, as a guide by size matrix.

Pivots the mean share of classified reads of ``guide_indel_sizes`` to one row per
guide and one column per signed indel size within the heatmap window (columns
named ``-30`` to ``+30``). A size a guide has no row for is a size none of its
libraries carries, so it is zero, not missing. The guide column is named
``size_guide`` and not ``guide``: the Indel spectrum tab picks one guide on
``guide``, and a column of the same name would narrow this matrix to that guide,
when the matrix is there to compare the guides. The mean, not the median, so a
size carried by part of a guide's libraries still shows.

Output:
    size_guide : Utf8   protospacer
    <size> : Float64    mean share of classified reads at that signed size, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sizes",
        dc_ref="guide_indel_sizes",
        input_schema={"guide": pl.Utf8, "size": pl.Int64, "mean_pct_reads": pl.Float64},
    ),
]

# A fixed window of this template: larger indels are rare and would stretch the
# matrix until no column is readable. The size distribution above draws ±100 bp.
HEATMAP_WINDOW = 30


def size_label(size: int) -> str:
    return f"+{size}" if size > 0 else str(size)


# No indel has size 0, so there is no column for it.
SIZE_COLUMNS = [size_label(s) for s in range(-HEATMAP_WINDOW, HEATMAP_WINDOW + 1) if s != 0]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "size_guide": pl.Utf8,
    **{c: pl.Float64 for c in SIZE_COLUMNS},
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sizes = sources["sizes"].filter(pl.col("size").abs() <= HEATMAP_WINDOW)
    guides = sources["sizes"].select("guide").unique()
    long = sizes.select(
        "guide",
        pl.col("size").map_elements(size_label, return_dtype=pl.Utf8).alias("col"),
        pl.col("mean_pct_reads").alias("v"),
    )
    wide = long.pivot(on="col", index="guide", values="v") if not long.is_empty() else guides
    for c in SIZE_COLUMNS:
        if c not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
    return (
        guides.join(wide, on="guide", how="left")
        .with_columns([pl.col(c).cast(pl.Float64).fill_null(0.0) for c in SIZE_COLUMNS])
        .rename({"guide": "size_guide"})
        .select(list(OUTPUT_SCHEMA))
        .sort("size_guide")
    )
