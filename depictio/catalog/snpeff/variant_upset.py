"""Variant-level caller overlap: one row per variant, one 0/1 column per caller.

The honest question a multi-caller germline run answers is not "which caller is
right" but "which calls does a caller keep that the others drop". That is a set
intersection over variant keys, which is what ``upset_plot`` draws.

Built from the annotated calls rather than the raw ones so that every caller is
represented even when its unannotated VCF did not survive the bucket sync, and
restricted to PASS calls: a filtered-out call is not a claim the caller is
making, so counting it as membership would inflate every intersection.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Depth is a second axis here (the same individual sequenced twice), so a set
#: is a caller-and-depth pair and the plot reads as depth sensitivity, not as a
#: truth comparison. Set columns are therefore "<caller> <sample>".
SOURCES: list[RecipeSource] = [RecipeSource(ref="variants", dc_ref="snpeff_ann_variants")]

#: An UpSet over 300k rows is unreadable and slow to compute. Structural
#: variants dominate nothing here but carry symbolic alleles whose keys never
#: match across callers, so they are dropped rather than shown as five
#: singletons.
MAX_VARIANTS = 60_000

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {"variant_key": pl.Utf8}
# Set columns are one per caller-and-sample pair, known only at ingest.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot PASS calls into a variant by caller-and-sample membership matrix."""
    calls = (
        sources["variants"]
        .filter(pl.col("is_pass") & (pl.col("variant_type") != "SV"))
        .with_columns(
            pl.concat_str([pl.col("caller"), pl.col("sample")], separator=" ").alias("callset")
        )
    )

    # Keep the variants seen by the most callsets: those are the rows that carry
    # the intersections, and the long tail of private calls is summarised by the
    # cardinality bars anyway.
    ranked = (
        calls.group_by("variant_key")
        .agg(pl.col("callset").n_unique().alias("n_callsets"))
        .sort(["n_callsets", "variant_key"], descending=[True, False])
        .head(MAX_VARIANTS)
        .select("variant_key")
    )
    calls = calls.join(ranked, on="variant_key", how="inner")

    presence = calls.group_by(["variant_key", "callset"]).agg(
        pl.lit(1, dtype=pl.Int8).alias("present")
    )
    wide = presence.pivot(
        values="present", index="variant_key", on="callset", aggregate_function="max"
    )
    # A pivot's column order follows the group_by order, which is not stable
    # between runs; sorted so the Delta schema and the fixture never churn.
    set_cols = sorted(c for c in wide.columns if c != "variant_key")
    return wide.select(
        "variant_key", *[pl.col(c).fill_null(0).cast(pl.Int8) for c in set_cols]
    ).sort("variant_key")
