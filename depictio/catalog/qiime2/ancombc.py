"""Merge ANCOM-BC differential abundance results (5 slices) into one long-format table.

Each slice is read by a glob so a run can hold several analyses of the same
samples side by side, e.g. ANCOM-BC against two reference databases. A file named
``<slice>.<label>.csv`` (``lfc_slice.pr2.csv``) carries its rows under
``taxonomy = <label>``; the file ampliseq writes (``lfc_slice.csv``) has no label
and leaves the column empty. A dashboard switches between the labels with a filter
on ``taxonomy``.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.lineage import kingdom_phylum

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="lfc",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/lfc_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="p_val",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/p_val_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="q_val",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/q_val_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="w",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/w_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="se",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/se_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
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
    "taxonomy": pl.Utf8,
}


# A slice named ``lfc_slice.pr2.csv`` holds the rows labelled "pr2"; the plain
# ``lfc_slice.csv`` has no label.
_LABEL = r"_slice\.([^/.]+)\.csv$"
_NO_LABEL = ""


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt each ANCOM-BC slice and join into one table with taxonomy annotations."""
    contrast_cols = [
        c for c in sources["lfc"].columns if c not in ("id", "(Intercept)", "source_path")
    ]

    melted = {
        name: (
            sources[name]
            .select(
                "id",
                pl.col("source_path").str.extract(_LABEL, 1).fill_null(_NO_LABEL).alias("taxonomy"),
                *contrast_cols,
            )
            .unpivot(
                on=contrast_cols,
                index=["id", "taxonomy"],
                variable_name="contrast",
                value_name=name,
            )
        )
        for name in ["lfc", "p_val", "q_val", "w", "se"]
    }

    result = melted["lfc"]
    for name in ["p_val", "q_val", "w", "se"]:
        result = result.join(melted[name], on=["id", "taxonomy", "contrast"], how="left")

    # Ranks are read from the tail of the lineage: the template points the five
    # slices at the ANCOM-BC level that *is* Phylum for the run's reference
    # database, so the leaf is the Phylum whatever depth sits above it.
    result = result.with_columns(
        *kingdom_phylum(pl.col("id")),
        (-pl.col("q_val").log(base=10)).alias("neg_log10_qval"),
        (pl.col("q_val") < 0.05).alias("significant"),
        pl.when(pl.col("taxonomy") == _NO_LABEL)
        .then(None)
        .otherwise(pl.col("taxonomy"))
        .alias("taxonomy"),
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
        "taxonomy",
    )
