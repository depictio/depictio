"""Canonical-schema MA-plot DC for ampliseq.

Joins ANCOM-BC log-fold-change results with per-taxon mean log abundance
derived from the raw composition counts. Produces the canonical MA roles:

    feature_id : Utf8           -- taxon id (joined on id)
    avg_log_intensity : Float64 -- mean log10(count + 1) across samples (the A axis)
    log2_fold_change : Float64  -- ANCOM-BC lfc (the M axis)

Optional ``significance`` (q_val) drives tier colouring; ``label`` (Phylum)
appears in hover.

When the ANCOM-BC table carries a ``taxonomy`` label (a run analysed against two
reference databases, see ``qiime2/ancombc.py``), the taxa of a label that has a
barplot of its own, ``qiime2/barplot/level-N.<label>.csv``, take their mean
abundance from it: their lineages are that database's, which the default
composition does not hold.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: id, lfc and q_val are renamed only when present.
    RecipeSource(ref="ancombc", dc_ref="ancombc_results"),
    RecipeSource(
        ref="composition",
        dc_ref="taxonomy_composition",
        input_schema={"taxonomy": pl.Utf8, "count": pl.Float64},
    ),
    # The barplots of the other analyses, one per label. Absent on an ordinary run.
    RecipeSource(
        ref="labelled_barplots",
        glob_pattern="qiime2/barplot/level-2.*.csv",
        format="CSV",
        source_path="source_path",
        optional=True,
        input_schema={"index": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "avg_log_intensity": pl.Float64,
    "log2_fold_change": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "significance": pl.Float64,
    "label": pl.Utf8,
    "contrast": pl.Utf8,
    "taxonomy": pl.Utf8,
}


def _labelled_intensity(barplots: pl.DataFrame) -> pl.DataFrame:
    """Mean log10(count + 1) per taxon of each labelled barplot.

    The same quantity as below, taken from the wide barplot the way the
    composition table is built from it: zero counts are dropped before the mean.
    """
    taxa = [c for c in barplots.columns if ";" in c]
    return (
        barplots.with_columns(
            pl.col("source_path").str.extract(r"\.([^/.]+)\.csv$", 1).alias("taxonomy")
        )
        .unpivot(on=taxa, index="taxonomy", variable_name="feature_id", value_name="count")
        .with_columns(pl.col("count").cast(pl.Float64))
        .filter(pl.col("count") > 0)
        .group_by("taxonomy", "feature_id")
        .agg((pl.col("count") + 1).log(base=10).mean().alias("labelled_intensity"))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Compute mean log intensity per taxon and join with ANCOM-BC lfc."""
    composition = sources["composition"]
    ancombc = sources["ancombc"]
    labelled = sources.get("labelled_barplots")

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
    if labelled is not None and "taxonomy" in df.columns:
        df = df.join(
            _labelled_intensity(labelled), on=["taxonomy", "feature_id"], how="left"
        ).with_columns(
            pl.coalesce("labelled_intensity", "avg_log_intensity").alias("avg_log_intensity")
        )

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
            "taxonomy",
        )
        if c in df.columns
    ]
    return df.select(keep).filter(pl.col("avg_log_intensity").is_not_null())
