"""CUPPA's tissue-of-origin probabilities, one row per tumor, classifier and cancer type.

CUPPA (hmftools) predicts the primary tumor location from genome-wide features
with one classifier per feature family (``snv96`` mutational profile,
``gen_pos`` genomic position of mutations, ``event`` drivers and SVs; with RNA
``gene_exp`` and ``alt_sj``), a combined DNA and a combined RNA classifier and a
final ``combined`` call. ``<tumor>.cuppa.vis_data.tsv`` is the long table the
CUPPA plot is drawn from; its ``prob`` rows hold every classifier's probability
for every cancer type, with CUPPA's rank of that type within the classifier.

Only the ``prob`` rows are kept (the feature contributions and performance rows
describe the model, not the tumor). ``is_top`` flags each classifier's first
ranked type. The tumor id is the ``sample_id`` column.
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
    "sample": pl.Utf8,
    "classifier_group": pl.Utf8,
    "classifier": pl.Utf8,
    "cancer_type": pl.Utf8,
    "probability": pl.Float64,
    "rank": pl.Int64,
    "is_top": pl.Boolean,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["vis"].filter(pl.col("data_type") == "prob")
    return (
        df.select(
            pl.col("sample_id").alias("sample"),
            pl.col("clf_group").alias("classifier_group"),
            pl.col("clf_name").alias("classifier"),
            pl.col("cancer_type"),
            pl.col("data_value").cast(pl.Float64, strict=False).fill_null(0.0).alias("probability"),
            pl.col("rank").cast(pl.Float64, strict=False).round(0).cast(pl.Int64).alias("rank"),
        )
        .with_columns((pl.col("rank") == 1).alias("is_top"))
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "classifier", "rank"])
    )
