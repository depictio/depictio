"""Marker intensities of every cell, one row per cell and marker (MCQUANT, long).

The wide MCQUANT table melted on its marker columns: the cell's mean intensity
in that channel, the same through ``asinh(x / 150)`` (linear near zero,
logarithmic in the bright tail, so markers of very different brightness share an
axis), the marker's position in the panel and whether it is a nuclear stain
(DNA, DAPI, Hoechst ...) or a marker. ``cell_key`` is the run-wide cell id of
``mcquant/cells``, so a lasso on the cells reaches these rows.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mcquant import load_cells, melt_markers

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="mcquant",
        input_schema={
            "source_path": pl.Utf8,
            "CellID": pl.Int64,
            "X_centroid": pl.Float64,
            "Y_centroid": pl.Float64,
        },
        glob_pattern="quantification/mcquant/*/*.csv",
        format="csv",
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "cell_key": pl.Utf8,
    "sample": pl.Utf8,
    "segmenter": pl.Utf8,
    "CellID": pl.Int64,
    "marker": pl.Utf8,
    "marker_order": pl.Int64,
    "marker_role": pl.Utf8,
    "intensity": pl.Float64,
    "asinh_intensity": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    long = melt_markers(load_cells(sources["mcquant"]))
    return long.select(list(OUTPUT_SCHEMA)).sort(["sample", "segmenter", "CellID", "marker_order"])
