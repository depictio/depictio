"""Which callers make each call: one row per call in a sample, one 0/1 column per caller.

The honest question a multi-caller germline run answers is not "which caller is
right" but "which calls does a caller keep that the others drop". That is a set
intersection over variant keys, which is what ``upset_plot`` draws. The catalog
recipe (``snpeff/variant_upset.py``) makes one set per caller *and sample*, so a
run of two libraries draws ten sets and ``min_size`` hides most intersections.
Here the sets are the callers, and an element is a call in one sample: the
``sample`` column narrows it, so the persistent sample filter reads one library's
callers, and with none picked every sample's calls are counted once each.

Built from the annotated calls rather than the raw ones so that every caller is
represented even when its unannotated VCF did not survive the bucket sync, and
restricted to PASS calls: a filtered-out call is not a claim the caller is
making, so counting it as membership would inflate every intersection. Structural
variants carry symbolic alleles whose keys never match across callers, so they
are dropped rather than shown as singletons.

Two columns beside the sets read the agreement itself: ``n_callers`` (how many
callers made the call) and ``sample_shared_pct`` (the share of the sample's PASS
calls that two callers or more made, counted before the table is capped, so the
Overview can state it).

Sources:
    variants  ``snpeff_ann_variants`` (catalog ``snpeff/ann_variants.py``)

Output schema (one column per caller after these, known only at ingest):
    sample, variant_key : Utf8
    n_callers : Int64           callers that made the call in this sample
    sample_shared_pct : Float64 share of the sample's PASS calls two callers or more made, in percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        dc_ref="snpeff_ann_variants",
        input_schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "variant_key": pl.Utf8,
            "variant_type": pl.Utf8,
            "is_pass": pl.Boolean,
        },
    )
]

#: An UpSet over a million elements is slow to compute and its long tail of private
#: calls is already summarised by the cardinality bars, so the calls made by the most
#: callers are kept, up to this many (sample, variant) pairs.
MAX_ELEMENTS = 150_000

#: The columns that are not sets. The dashboard's ``set_columns_pattern`` excludes
#: them by name, since ``n_callers`` is 0/1-valued on a one-caller run.
NON_SET_COLUMNS = ("sample", "variant_key", "n_callers", "sample_shared_pct")

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "variant_key": pl.Utf8,
    "n_callers": pl.Int64,
    "sample_shared_pct": pl.Float64,
}
# Set columns are one per caller, known only at ingest.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot PASS calls into a (sample, variant) by caller membership matrix."""
    calls = (
        sources["variants"]
        .filter(pl.col("is_pass") & (pl.col("variant_type") != "SV"))
        .select("sample", "variant_key", "caller")
        .unique()
    )
    keys = ["sample", "variant_key"]
    per_call = calls.group_by(keys).agg(
        pl.col("caller").n_unique().cast(pl.Int64).alias("n_callers")
    )
    shared = per_call.group_by("sample").agg(
        ((pl.col("n_callers") >= 2).mean() * 100).alias("sample_shared_pct")
    )
    kept = per_call.sort(["n_callers", *keys], descending=[True, False, False]).head(MAX_ELEMENTS)

    presence = calls.join(kept.select(keys), on=keys, how="inner").with_columns(
        pl.lit(1, dtype=pl.Int8).alias("present")
    )
    wide = presence.pivot(values="present", index=keys, on="caller", aggregate_function="max")
    # A pivot's column order follows the group_by order, which is not stable between
    # runs; sorted so the Delta schema and the fixture never churn.
    set_cols = sorted(c for c in wide.columns if c not in keys)
    return (
        wide.join(kept, on=keys, how="left")
        .join(shared, on="sample", how="left")
        .select(
            "sample",
            "variant_key",
            "n_callers",
            "sample_shared_pct",
            *[pl.col(c).fill_null(0).cast(pl.Int8) for c in set_cols],
        )
        .sort(keys)
    )
