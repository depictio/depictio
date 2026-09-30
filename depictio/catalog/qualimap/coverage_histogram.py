"""How many bases of the reference sit at each depth, from Qualimap BamQC.

``raw_data_qualimapReport/coverage_histogram.txt`` is the table behind the
"Coverage histogram" plot: one row per depth, two tab-separated columns after a
``#``-prefixed header, the counts written in Java's scientific notation::

    #Coverage  Number of genomic locations
    0.0        3.54519793E8
    1.0        1.51646969E8

Qualimap caps the histogram at the depth its own binning reached, so the row
count varies with the library (156 rows here, thousands on a deep genome); the
recipe keeps every row and lets the ``profile`` kind draw the curve.

The share of the reference at each depth is added because the raw counts are
reference-size dependent and therefore not comparable between two runs mapped
against different references, while the share is.

Input: a data collection reading every matched table one LINE per row (see
``qualimap/coverage_across_reference.py`` for the scan block, which is
identical).

Output schema:
    sample : Utf8              library Qualimap ran on
    coverage : Int64            depth, X
    n_genomic_locations : Float64  bases of the reference at that depth
    fraction : Float64          share of the reference at that depth, 0-1
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.qualimap_raw import split_columns

#: Data-collection tag the template must scan the histograms into.
RAW_DC_TAG = "qualimap_coverage_histogram_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="histograms", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "coverage": pl.Int64,
    "n_genomic_locations": pl.Float64,
    "fraction": pl.Float64,
}

_RECIPE = "qualimap_coverage_histogram"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, depth)."""
    frame = (
        split_columns(sources["histograms"], ["coverage", "n_genomic_locations"], recipe=_RECIPE)
        .with_columns(
            pl.col("coverage").cast(pl.Float64, strict=False).cast(pl.Int64),
            pl.col("n_genomic_locations").cast(pl.Float64, strict=False),
        )
        .drop_nulls(["coverage", "n_genomic_locations"])
    )
    if frame.is_empty():
        raise ValueError(f"{_RECIPE}: no row carried a depth and a base count")

    return (
        frame.with_columns(
            (
                pl.col("n_genomic_locations") / pl.col("n_genomic_locations").sum().over("sample")
            ).alias("fraction")
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "coverage"])
    )
