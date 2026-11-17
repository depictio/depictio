"""Sequences per Tiara class and assembly, from the per-sequence Tiara table.

``tiara_classifications`` holds one row per sequence of 3 kb or more and its
class, and no number to stack. This counts them per assembly and class, so the
Contamination tab can draw each assembly's composition (shares, sorting and
the zoom on the small classes come from the stacked bar).

Input: ``tiara_classifications`` through ``dc_ref``.

Output schema:
    genome : Utf8         assembly name
    tiara_class : Utf8    Tiara's class (mitochondrion and plastid for organelles)
    sequences : Int64     sequences of the assembly in the class
    share_pct : Float64   the class's share of the assembly's classified sequences, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="classes",
        dc_ref="tiara_classifications",
        input_schema={"genome": pl.Utf8, "tiara_class": pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "tiara_class": pl.Utf8,
    "sequences": pl.Int64,
    "share_pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    counts = (
        sources["classes"]
        .drop_nulls(["genome", "tiara_class"])
        .group_by(["genome", "tiara_class"])
        .agg(pl.len().cast(pl.Int64).alias("sequences"))
    )
    return (
        counts.with_columns(
            (pl.col("sequences") * 100.0 / pl.col("sequences").sum().over("genome"))
            .round(3)
            .alias("share_pct")
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["genome", "sequences"], descending=[False, True])
    )
