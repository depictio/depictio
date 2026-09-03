"""Merge ANCOM-BC differential abundance results (5 files) into one long-format table."""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.lineage import kingdom_phylum

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="lfc",
        path="qiime2/ancombc/differentials/Category-habitat-level-2/lfc_slice.csv",
        format="CSV",
    ),
    RecipeSource(
        ref="p_val",
        path="qiime2/ancombc/differentials/Category-habitat-level-2/p_val_slice.csv",
        format="CSV",
    ),
    RecipeSource(
        ref="q_val",
        path="qiime2/ancombc/differentials/Category-habitat-level-2/q_val_slice.csv",
        format="CSV",
    ),
    RecipeSource(
        ref="w",
        path="qiime2/ancombc/differentials/Category-habitat-level-2/w_slice.csv",
        format="CSV",
    ),
    RecipeSource(
        ref="se",
        path="qiime2/ancombc/differentials/Category-habitat-level-2/se_slice.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "id": pl.Utf8,
    "contrast": pl.Utf8,
    "lfc": pl.Float64,
    "p_val": pl.Float64,
    "q_val": pl.Float64,
    "w": pl.Float64,
    "se": pl.Float64,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
    "neg_log10_qval": pl.Float64,
    "significant": pl.Boolean,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt each ANCOM-BC slice and join into one table with taxonomy annotations."""
    contrast_cols = [c for c in sources["lfc"].columns if c not in ("id", "(Intercept)")]

    melted = {
        name: (
            sources[name]
            .select("id", *contrast_cols)
            .unpivot(on=contrast_cols, index="id", variable_name="contrast", value_name=name)
        )
        for name in ["lfc", "p_val", "q_val", "w", "se"]
    }

    result = melted["lfc"]
    for name in ["p_val", "q_val", "w", "se"]:
        result = result.join(melted[name], on=["id", "contrast"], how="left")

    # Ranks are read from the tail of the lineage: the template points the five
    # slices at the ANCOM-BC level that *is* Phylum for the run's reference
    # database, so the leaf is the Phylum whatever depth sits above it.
    result = result.with_columns(
        *kingdom_phylum(pl.col("id")),
        (-pl.col("q_val").log(base=10)).alias("neg_log10_qval"),
        (pl.col("q_val") < 0.05).alias("significant"),
    )

    return result.select(
        "id",
        "contrast",
        "lfc",
        "p_val",
        "q_val",
        "w",
        "se",
        "Kingdom",
        "Phylum",
        "neg_log10_qval",
        "significant",
    )
