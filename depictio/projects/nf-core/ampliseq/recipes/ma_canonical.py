"""Canonical-schema MA-plot DC for ampliseq.

Joins ANCOM-BC log-fold-change results with per-taxon mean log abundance
derived from the raw composition counts. Produces the canonical MA roles:

    feature_id : Utf8           -- taxon id (joined on id)
    avg_log_intensity : Float64 -- mean log10(count + 1) across samples (the A axis)
    log2_fold_change : Float64  -- ANCOM-BC lfc (the M axis)

Optional ``significance`` (q_val) drives tier colouring; ``label`` (Phylum)
appears in hover.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="ancombc", dc_ref="ancombc_results"),
    RecipeSource(ref="composition", dc_ref="taxonomy_composition"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "avg_log_intensity": pl.Float64,
    "log2_fold_change": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "significance": pl.Float64,
    "label": pl.Utf8,
    "contrast": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Compute mean log intensity per taxon and join with ANCOM-BC lfc."""
    composition = sources["composition"]
    ancombc = sources["ancombc"]

    # Mean log10(count + 1) per taxon across samples — the A axis.
    intensity = (
        composition.group_by("taxonomy")
        .agg((pl.col("count") + 1).log(base=10).mean().alias("avg_log_intensity"))
        .rename({"taxonomy": "feature_id"})
    )

    ancombc_renamed = ancombc.rename(
        {
            k: v
            for k, v in {
                "id": "feature_id",
                "lfc": "log2_fold_change",
                "q_val": "significance",
            }.items()
            if k in ancombc.columns
        }
    )

    df = ancombc_renamed.join(intensity, on="feature_id", how="left")

    df = df.with_columns(
        pl.col("feature_id").cast(pl.Utf8),
        pl.col("avg_log_intensity").cast(pl.Float64, strict=False),
        pl.col("log2_fold_change").cast(pl.Float64, strict=False),
    )
    if "significance" in df.columns:
        df = df.with_columns(pl.col("significance").cast(pl.Float64, strict=False))
    if "Phylum" in df.columns:
        df = df.with_columns(pl.col("Phylum").alias("label"))

    keep = [
        c
        for c in (
            "feature_id",
            "avg_log_intensity",
            "log2_fold_change",
            "significance",
            "label",
            "contrast",
        )
        if c in df.columns
    ]
    return df.select(keep).filter(pl.col("avg_log_intensity").is_not_null())
