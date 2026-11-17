"""Peaks per sample and HOMER feature class, in the long form of a composition.

``homer/annotate_peaks.py`` gives one row per peak with its coarse feature class
(``promoter-TSS``, ``intron``, ``Intergenic``...). A composition tile (the
``stacked_taxonomy`` advanced viz) reads one row per sample and class with the
amount of that class, so this recipe counts the peaks: the tile then offers the
counts and the shares, sorts the libraries and hides classes from its own
controls, none of which a stacked bar figure over the per-peak table can.

Input: the ``homer_annotated_peaks`` data collection, read through ``dc_ref`` so
this table and the annotation cannot disagree on what a sample is.

Output schema:
    sample : Utf8             library the peaks were called in
    annotation_class : Utf8   coarse HOMER feature class; peaks HOMER left
                              unclassified are counted as ``Unclassified``
    peak_count : Int64        peaks of that library in that class
    rank : Utf8               constant ``Feature class``: the one level the composition
                              tile reads (it needs a level column even for a single one)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads: the tidy per-peak annotation table.
SOURCE_DC_TAG = "homer_annotated_peaks"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="peaks",
        dc_ref=SOURCE_DC_TAG,
        input_schema={
            "sample": pl.Utf8,
            "annotation_class": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "annotation_class": pl.Utf8,
    "peak_count": pl.Int64,
    "rank": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count the peaks of every sample in each feature class."""
    peaks = sources["peaks"]
    if peaks.is_empty():
        raise ValueError("homer_feature_classes: the annotated peaks are empty")
    missing = {"sample", "annotation_class"} - set(peaks.columns)
    if missing:
        raise ValueError(
            f"homer_feature_classes: {SOURCE_DC_TAG} has no {sorted(missing)} column; "
            f"got {peaks.columns}"
        )

    named = pl.col("annotation_class").cast(pl.Utf8)
    return (
        peaks.select(
            pl.col("sample").cast(pl.Utf8),
            pl.when(named.is_null() | (named.str.strip_chars() == ""))
            .then(pl.lit("Unclassified"))
            .otherwise(named)
            .alias("annotation_class"),
        )
        .group_by(["sample", "annotation_class"])
        # `pl.len()` is UInt64 and the schema check is exact.
        .agg(pl.len().cast(pl.Int64).alias("peak_count"))
        .with_columns(pl.lit("Feature class").alias("rank"))
        .select(list(OUTPUT_SCHEMA))
        .sort(["sample", "annotation_class"])
    )
