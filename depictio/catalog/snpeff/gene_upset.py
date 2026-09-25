"""Gene-level caller overlap: one row per gene, one 0/1 column per caller.

The variant-level overlap answers "the same call", which two callers can miss
for a one-base difference in how they left-align an indel. The gene-level
overlap answers "the same gene carries a coding variant", which is the question
an analyst downstream of the callset actually asks, and it is robust to
representation differences.

Restricted to genes carrying at least one HIGH or MODERATE variant: with
MODIFIER variants included, every gene is in every set and the plot says
nothing.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="genes", dc_ref="snpeff_genes")]

#: An UpSet over the full gene universe is unreadable; the busiest genes carry
#: the intersections.
MAX_GENES = 3_000

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {"gene_name": pl.Utf8}
# Caller columns are one per caller in the run, known only at ingest.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot the coding-variant genes into a gene by caller membership matrix."""
    coding = sources["genes"].filter(pl.col("n_coding") > 0)

    top = (
        coding.group_by("gene_name")
        .agg(pl.col("n_coding").sum().alias("total_coding"))
        .sort(["total_coding", "gene_name"], descending=[True, False])
        .head(MAX_GENES)
        .select("gene_name")
    )

    presence = (
        coding.join(top, on="gene_name", how="inner")
        .group_by(["gene_name", "caller"])
        .agg(pl.lit(1, dtype=pl.Int8).alias("present"))
    )
    wide = presence.pivot(
        values="present", index="gene_name", on="caller", aggregate_function="max"
    )
    # A pivot's column order follows the group_by order, which is not stable
    # between runs; sorted so the Delta schema and the fixture never churn.
    set_cols = sorted(c for c in wide.columns if c != "gene_name")
    return wide.select("gene_name", *[pl.col(c).fill_null(0).cast(pl.Int8) for c in set_cols]).sort(
        "gene_name"
    )
