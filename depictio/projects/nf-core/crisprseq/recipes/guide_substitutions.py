"""Substitution rate per guide and position, as a guide by offset matrix.

Pivots the mean substitution rate of ``guide_substitution_profile`` to one row
per guide and one column per offset from the cut site within the heatmap
window (columns named ``-20`` to ``+20``). The guide column is renamed back to
``guide`` here: this matrix follows the samplesheet's guide like every other
per-guide collection, while the profile's own guide picker leaves it whole. A base editor leaves a hot band a
few bases upstream of the cut in the guides it was used with; a nuclease leaves
the matrix flat. The mean, not the median, so a band carried by part of a
guide's libraries still shows.

Output:
    guide : Utf8        protospacer
    libraries : Int64   most libraries the means at any offset are over
    <offset> : Float64  mean substitution rate at that offset, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profile", dc_ref="guide_substitution_profile"),
]

HEATMAP_WINDOW = 20


def offset_label(offset: int) -> str:
    return f"+{offset}" if offset > 0 else str(offset)


OFFSET_COLUMNS = [offset_label(o) for o in range(-HEATMAP_WINDOW, HEATMAP_WINDOW + 1)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "guide": pl.Utf8,
    "libraries": pl.Int64,
    **{c: pl.Float64 for c in OFFSET_COLUMNS},
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    prof = (
        sources["profile"]
        .rename({"profile_guide": "guide"})
        .filter(pl.col("offset").abs() <= HEATMAP_WINDOW)
    )
    n = prof.group_by("guide").agg(pl.col("libraries").max().cast(pl.Int64))
    long = prof.select(
        "guide",
        pl.col("offset").map_elements(offset_label, return_dtype=pl.Utf8).alias("col"),
        pl.col("mean_substitution_pct").alias("v"),
    )
    wide = long.pivot(on="col", index="guide", values="v")
    for c in OFFSET_COLUMNS:
        if c not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
    return (
        n.join(wide, on="guide", how="inner")
        .with_columns([pl.col(c).cast(pl.Float64) for c in OFFSET_COLUMNS])
        .select(list(EXPECTED_SCHEMA))
        .sort("guide")
    )
