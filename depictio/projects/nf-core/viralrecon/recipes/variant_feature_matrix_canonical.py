"""Canonical-schema sample × variant feature matrix for live PCA embedding.

Pivots the long-format ``variants_long`` DC to a wide sample × mutation_label
binary matrix suitable for the Embedding viz's ``live`` compute mode (PCA /
UMAP / t-SNE on a sample-feature matrix, see EmbeddingConfig.compute_method).

Output shape:
    sample_id : Utf8        -- one row per sample
    <mut_1>, <mut_2>, ...   -- Int8 columns, 1 if the mutation is present in
                               the sample, 0 otherwise

The Celery worker calls run_pca (or other dim-reduction) on the numeric
columns and returns coordinates the renderer plots.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="variants", dc_ref="variants_long"),
    RecipeSource(ref="pangolin", dc_ref="pangolin_lineages", optional=True),
    RecipeSource(ref="nextclade", dc_ref="nextclade_results", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
}
# Mutation columns are dynamic — validated via OPTIONAL_SCHEMA = {}.
# `lineage` / `clade` are pass-through metadata for embedding colour / cluster
# overlay (compute_embedding picks them up via extra_cols).
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "lineage": pl.Utf8,
    "clade": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot variants_long to wide sample × mutation binary matrix; attach
    lineage + clade metadata for embedding colour / cluster overlay."""
    df = sources["variants"]

    if "sample" not in df.columns or "mutation_label" not in df.columns:
        raise ValueError(
            "viralrecon variant_feature_matrix: variants_long must expose sample + mutation_label"
        )

    presence = (
        df.select("sample", "mutation_label")
        .unique()
        .with_columns(pl.lit(1, dtype=pl.Int8).alias("present"))
    )
    wide = presence.pivot(
        values="present", index="sample", on="mutation_label", aggregate_function="max"
    )
    wide = wide.rename({"sample": "sample_id"})

    feature_cols = [c for c in wide.columns if c != "sample_id"]
    wide = wide.with_columns(
        [pl.col(c).fill_null(0).cast(pl.Int8) for c in feature_cols]
    ).with_columns(pl.col("sample_id").cast(pl.Utf8))

    # Attach metadata for colour / cluster overlay on the live PCA. Both
    # sources are optional — if upstream DCs are absent, the matrix still
    # works for PCA without colour annotation.
    pangolin = sources.get("pangolin")
    if pangolin is not None and "sample" in pangolin.columns and "lineage" in pangolin.columns:
        lineage_map = (
            pangolin.select("sample", "lineage")
            .unique(subset=["sample"])
            .rename({"sample": "sample_id", "lineage": "lineage"})
            .with_columns(pl.col("sample_id").cast(pl.Utf8), pl.col("lineage").cast(pl.Utf8))
        )
        wide = wide.join(lineage_map, on="sample_id", how="left")
        wide = wide.with_columns(pl.col("lineage").fill_null("Unassigned"))

    nextclade = sources.get("nextclade")
    if nextclade is not None and "sample" in nextclade.columns and "clade" in nextclade.columns:
        clade_map = (
            nextclade.select("sample", "clade")
            .unique(subset=["sample"])
            .rename({"sample": "sample_id", "clade": "clade"})
            .with_columns(pl.col("sample_id").cast(pl.Utf8), pl.col("clade").cast(pl.Utf8))
        )
        wide = wide.join(clade_map, on="sample_id", how="left")
        wide = wide.with_columns(pl.col("clade").fill_null("Unknown"))

    return wide
