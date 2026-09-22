"""What share of the reference is covered at least X deep, from Qualimap BamQC.

``raw_data_qualimapReport/genome_fraction_coverage.txt`` is the table behind the
"Coverage histogram (0-50X)" cumulative plot: one row per depth threshold, two
tab-separated columns after a ``#``-prefixed header, the fraction already in
percent::

    #Coverage (X)  Coverage
    1.0            47.08394506984902
    2.0            24.448934274852576

This is the number a shallow shotgun library is actually judged on: a mean depth
of 0.5X says nothing about whether it is spread over half the genome once or
over a tenth of it five times, and this curve does.

Input: a data collection reading every matched table one LINE per row (see
``qualimap/coverage_across_reference.py`` for the scan block, which is
identical).

Output schema:
    sample : Utf8               library Qualimap ran on
    min_coverage : Int64        depth threshold, X
    genome_fraction_pct : Float64  share of the reference covered at least that deep, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.qualimap_raw import split_columns

#: Data-collection tag the template must scan the curves into.
RAW_DC_TAG = "qualimap_genome_fraction_coverage_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="curves", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "min_coverage": pl.Int64,
    "genome_fraction_pct": pl.Float64,
}

_RECIPE = "qualimap_genome_fraction_coverage"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, depth threshold)."""
    frame = (
        split_columns(sources["curves"], ["min_coverage", "genome_fraction_pct"], recipe=_RECIPE)
        .with_columns(
            pl.col("min_coverage").cast(pl.Float64, strict=False).cast(pl.Int64),
            pl.col("genome_fraction_pct").cast(pl.Float64, strict=False),
        )
        .drop_nulls(["min_coverage", "genome_fraction_pct"])
    )
    if frame.is_empty():
        raise ValueError(f"{_RECIPE}: no row carried a threshold and a fraction")

    return frame.select(list(EXPECTED_SCHEMA)).sort(["sample", "min_coverage"])
