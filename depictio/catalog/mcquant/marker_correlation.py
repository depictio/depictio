"""How the markers co-vary over the cells, per segmenter (MCQUANT).

A marker by marker Pearson correlation of the cells' asinh intensities
(``asinh(x / 150)``), over every cell a segmentation method found on every image
of the run: one row per segmenter and marker (``marker_row``, the marker with
its segmenter, so two segmenters never share a row label), one Float64 column
per marker of the panel. Markers expressed by the same cells (two lineage
markers, a nuclear stain of each cycle) correlate; a marker with no signal has
no correlation (null). The marker columns are only known at ingest, so a heatmap
draws every numeric column of the table.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mcquant import asinh, is_nuclear, load_cells, marker_columns

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

# OUTPUT SCHEMA: the columns transform() returns, checked after it (then one
# Float64 column per marker).
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "marker_row": pl.Utf8,
    "segmenter": pl.Utf8,
    "marker": pl.Utf8,
    "marker_role": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def _correlation(matrix: np.ndarray) -> np.ndarray:
    """Pearson correlation of the columns; a constant column correlates with nothing."""
    centred = matrix - np.nanmean(matrix, axis=0)
    centred = np.nan_to_num(centred)
    norms = np.sqrt((centred**2).sum(axis=0))
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = (centred.T @ centred) / np.outer(norms, norms)
    corr[~np.isfinite(corr)] = np.nan
    return np.clip(corr, -1.0, 1.0)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    cells = load_cells(sources["mcquant"])
    markers = marker_columns(cells)
    if len(markers) < 2:
        raise ValueError("mcquant marker correlation: fewer than two marker columns")
    frames = []
    for (segmenter,), group in cells.group_by(["segmenter"], maintain_order=True):
        values = group.select([asinh(pl.col(m)).alias(m) for m in markers]).to_numpy()
        corr = _correlation(values.astype(np.float64))
        block = pl.DataFrame(
            {
                m: [None if np.isnan(v) else round(float(v), 4) for v in corr[:, j]]
                for j, m in enumerate(markers)
            },
            schema={m: pl.Float64 for m in markers},
        )
        frames.append(
            block.with_columns(
                pl.Series("marker", markers, dtype=pl.Utf8),
                pl.lit(str(segmenter)).alias("segmenter"),
            )
        )
    out = pl.concat(frames, how="vertical")
    out = out.with_columns(
        (pl.col("marker") + " (" + pl.col("segmenter") + ")").alias("marker_row"),
        pl.col("marker")
        .map_elements(
            lambda m: "Nuclear stain" if is_nuclear(m) else "Marker", return_dtype=pl.Utf8
        )
        .alias("marker_role"),
    )
    return out.select([*OUTPUT_SCHEMA, *markers])
