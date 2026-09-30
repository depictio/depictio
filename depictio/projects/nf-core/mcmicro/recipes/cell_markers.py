"""Per-cell marker matrix of the Image tab's segmenter, keyed for a group comparison.

``group_compare`` tests every numeric column of its collection between two
groups of rows, so it needs a table whose only numbers are the features to
test. The per-cell MCQUANT table also carries coordinates, morphology and
principal components, which a marker comparison must not test. This recipe
keeps ``cell_uid`` (the id a lasso on the cell map or a table selection emits),
the sample, the design ``condition`` from the samples hub, the dominant marker,
and one Float64 column per marker of the panel.

Output columns:
    cell_uid, sample, condition, dominant_marker, <one Float64 column per marker>
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="cells", dc_ref="mc-cells-primary"),
    RecipeSource(ref="samples", dc_ref="samples", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "cell_uid": pl.Utf8,
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "dominant_marker": pl.Utf8,
}
# One column per marker; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Columns of the per-cell table that are not marker intensities.
NOT_MARKERS = frozenset(
    {
        "sample",
        "segmenter",
        "cell_id",
        "cell_uid",
        "x_centroid",
        "y_centroid",
        "area",
        "major_axis_length",
        "minor_axis_length",
        "eccentricity",
        "solidity",
        "extent",
        "orientation",
        "dominant_marker",
        "pc_1",
        "pc_2",
    }
)


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    cells = sources["cells"]
    if cells is None or cells.is_empty():
        raise ValueError("mcmicro cell_markers: no cells")
    markers = [c for c in cells.columns if c not in NOT_MARKERS and cells.schema[c].is_numeric()]
    samples = sources.get("samples")
    if samples is not None and {"sample", "condition"} <= set(samples.columns):
        cells = cells.join(
            samples.select("sample", pl.col("condition").cast(pl.Utf8)).unique("sample"),
            on="sample",
            how="left",
        )
    else:
        cells = cells.with_columns(pl.lit(None, dtype=pl.Utf8).alias("condition"))
    return cells.select(
        "cell_uid",
        "sample",
        pl.col("condition").fill_null("all"),
        "dominant_marker",
        *[pl.col(m).cast(pl.Float64) for m in markers],
    )
