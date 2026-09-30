"""CUPPA's probabilities as a cancer type by classifier matrix, for a heatmap.

The same ``prob`` rows as ``cuppa_predictions``, pivoted to one row per tumor
and cancer type and one numeric column per classifier (``combined``,
``dna_combined``, ``snv96``, ``gen_pos``, ``event`` and, with RNA,
``rna_combined``, ``gene_exp``, ``alt_sj``). Reading across a row shows whether
the feature families agree on a cancer type or the combined call rests on one
of them. ``row_label`` is the cancer type, prefixed with the tumor id when the
run has several tumors, so it stays unique as a heatmap row.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="vis",
        glob_pattern="**/*.cuppa.vis_data.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "row_label": pl.Utf8,
    "sample": pl.Utf8,
    "cancer_type": pl.Utf8,
    "combined": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "dna_combined": pl.Float64,
    "snv96": pl.Float64,
    "gen_pos": pl.Float64,
    "event": pl.Float64,
    "rna_combined": pl.Float64,
    "gene_exp": pl.Float64,
    "alt_sj": pl.Float64,
}

#: Column order: the final call first, then DNA, then RNA classifiers.
CLASSIFIER_ORDER = ["combined", *OPTIONAL_SCHEMA]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    long = (
        sources["vis"]
        .filter(pl.col("data_type") == "prob")
        .select(
            pl.col("sample_id").alias("sample"),
            pl.col("clf_name").alias("classifier"),
            pl.col("cancer_type"),
            pl.col("data_value").cast(pl.Float64, strict=False).fill_null(0.0).alias("probability"),
        )
    )
    wide = long.pivot(
        on="classifier", index=["sample", "cancer_type"], values="probability",
        aggregate_function="first",
    )  # fmt: skip
    if "combined" not in wide.columns:
        wide = wide.with_columns(pl.lit(None, pl.Float64).alias("combined"))
    classifiers = [c for c in CLASSIFIER_ORDER if c in wide.columns]
    label = (
        pl.format("{} | {}", pl.col("sample"), pl.col("cancer_type"))
        if wide["sample"].n_unique() > 1
        else pl.col("cancer_type")
    )
    return (
        wide.with_columns(label.alias("row_label"))
        .select(["row_label", "sample", "cancer_type", *classifiers])
        .sort(["sample", "combined"], descending=[False, True])
    )
