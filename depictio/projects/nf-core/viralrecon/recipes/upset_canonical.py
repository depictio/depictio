"""Canonical-schema UpSet DC for viralrecon variants.

Pivots the long-format ``variants_long`` DC to a mutation × lineage binary
membership matrix: each row is one mutation_label; each column (one per
PANGO lineage) is a 1/0 indicator of whether the mutation is present in any
sample assigned to that lineage.

Schema for ``upset_plot`` is permissive — set columns are detected at
compute time. We join Pangolin lineage assignments onto the variants table
to derive the per-lineage mask.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="variants", dc_ref="variants_long"),
    RecipeSource(ref="pangolin", dc_ref="pangolin_lineages"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "mutation_label": pl.Utf8,
}
# Lineage columns are dynamic — validated via OPTIONAL_SCHEMA = {}.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Build mutation × lineage binary matrix."""
    variants = sources["variants"]
    pangolin = sources["pangolin"]

    if "mutation_label" not in variants.columns or "sample" not in variants.columns:
        raise ValueError("viralrecon upset: variants_long must expose mutation_label + sample")
    if "sample" not in pangolin.columns or "lineage" not in pangolin.columns:
        raise ValueError("viralrecon upset: pangolin_lineages must expose sample + lineage")

    sample_to_lineage = pangolin.select("sample", "lineage").unique(subset=["sample"])
    df = (
        variants.select("sample", "mutation_label")
        .unique()
        .join(sample_to_lineage, on="sample", how="inner")
    )

    presence = (
        df.filter(pl.col("lineage").is_not_null() & (pl.col("lineage") != ""))
        .group_by(["mutation_label", "lineage"])
        .agg(pl.lit(1, dtype=pl.Int8).alias("present"))
    )

    wide = presence.pivot(
        values="present", index="mutation_label", on="lineage", aggregate_function="max"
    )
    set_cols = [c for c in wide.columns if c != "mutation_label"]
    return wide.with_columns([pl.col(c).fill_null(0).cast(pl.Int8) for c in set_cols])
