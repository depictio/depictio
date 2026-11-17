"""Every segmented cell of an nf-core/mcmicro run, one row per cell (MCQUANT, wide).

Reads ``quantification/mcquant/<segmenter>/<file>.csv`` and keeps MCQUANT's
columns as they are: ``CellID``, one mean-intensity column per marker of the
panel (named by the marker sheet, so only known at ingest), the centroid in
pixels of the registered image and the regionprops morphology. Adds the image
(``sample``), the segmentation method (``segmenter``: Mesmer, Cellpose ...),
``cell_key`` (``<sample>|<segmenter>|<CellID>``: ``CellID`` restarts at 1 for
every image and every mask, so it is never unique across a run) and
``aspect_ratio`` (major over minor axis).

The marker columns pass through untyped by this schema: a tile names them by
pattern (``spatial_cells`` ``value_columns_pattern``), never by name.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mcquant import load_cells

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

# OUTPUT SCHEMA: the columns transform() returns, checked after it (the marker
# columns, one Float64 per channel, sit between CellID and X_centroid).
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "cell_key": pl.Utf8,
    "sample": pl.Utf8,
    "segmenter": pl.Utf8,
    "CellID": pl.Int64,
    "X_centroid": pl.Float64,
    "Y_centroid": pl.Float64,
    "Area": pl.Float64,
    "MajorAxisLength": pl.Float64,
    "MinorAxisLength": pl.Float64,
    "Eccentricity": pl.Float64,
    "Solidity": pl.Float64,
    "Extent": pl.Float64,
    "Orientation": pl.Float64,
    "aspect_ratio": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    return load_cells(sources["mcquant"])
