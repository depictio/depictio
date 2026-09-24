"""BUSCO scores as four classes per assembly, for a composition bar.

The four BUSCO classes partition the lineage set: complete single-copy +
complete duplicated + fragmented + missing = 100 percent. This recipe unpivots
the tidy batch summary into one row per assembly and class so a stacked bar can
draw them; the `rank` column is a constant because the composition kind splits
its bars by rank and BUSCO has only one.

Input: the tidy ``busco_batch_summary`` data collection
(`depictio/catalog/busco/batch_summary.py`), which a template declares before
this one.

Output schema:
    assembly_id : Utf8     the assessed assembly
    lineage : Utf8         the lineage dataset the class shares are against
    busco_class : Utf8     one of the four BUSCO classes
    rank : Utf8            always "BUSCO class"
    class_order : Int64    1 to 4, single-copy first, so tables sort the classes the BUSCO way
    percent : Float64      the class share of the lineage set, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SUMMARY_DC_TAG = "busco_batch_summary"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="summary", dc_ref=SUMMARY_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "lineage": pl.Utf8,
    "busco_class": pl.Utf8,
    "rank": pl.Utf8,
    "class_order": pl.Int64,
    "percent": pl.Float64,
}

#: Source column -> (class label, order). The labels are BUSCO's own words.
CLASSES: dict[str, tuple[str, int]] = {
    "single_pct": ("Complete single-copy", 1),
    "duplicated_pct": ("Complete duplicated", 2),
    "fragmented_pct": ("Fragmented", 3),
    "missing_pct": ("Missing", 4),
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot the four class percentages into one row per assembly and class."""
    summary = sources["summary"]
    if summary.is_empty():
        raise ValueError("busco_composition: the BUSCO batch summary is empty")
    missing = [c for c in ["assembly_id", "lineage", *CLASSES] if c not in summary.columns]
    if missing:
        raise ValueError(f"busco_composition: missing columns {missing} in {summary.columns}")

    parts = [
        summary.select(
            pl.col("assembly_id"),
            pl.col("lineage"),
            pl.lit(label).alias("busco_class"),
            pl.lit("BUSCO class").alias("rank"),
            pl.lit(order, dtype=pl.Int64).alias("class_order"),
            pl.col(column).cast(pl.Float64).alias("percent"),
        )
        for column, (label, order) in CLASSES.items()
    ]
    return (
        pl.concat(parts, how="vertical")
        .drop_nulls(["percent"])
        .select(list(EXPECTED_SCHEMA))
        .sort(["assembly_id", "lineage", "class_order"])
    )
