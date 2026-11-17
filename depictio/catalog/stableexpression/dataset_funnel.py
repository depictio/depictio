"""The samples of every nf-core/stableexpression dataset, step by step (long form).

One row per dataset and step: downloaded, after the gene ID mapping (a dataset
whose ids did not map loses all its samples there), after the zero filter
(``--max_zero_ratio``) and after the missing-value filter
(``--max_null_ratio``), the last being the samples of the merged matrix. A
step the dataset never reached holds 0, so summing a step over datasets gives
the run's funnel, and stacking it by platform shows where each one loses
samples.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import FUNNEL_STEPS, dataset_sources, dataset_table

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = dataset_sources()

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "step_key": pl.Utf8,
    "dataset": pl.Utf8,
    "platform": pl.Utf8,
    "outcome": pl.Utf8,
    "step": pl.Utf8,
    "step_order": pl.Int64,
    "samples": pl.Int64,
    "samples_lost": pl.Int64,
    "dataset_in": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    datasets = dataset_table(sources)
    steps = []
    previous = None
    for order, (label, column) in enumerate(FUNNEL_STEPS, start=1):
        lost = (
            pl.lit(0, dtype=pl.Int64)
            if previous is None
            else (pl.col(previous) - pl.col(column)).clip(lower_bound=0)
        )
        steps.append(
            datasets.select(
                "dataset",
                "platform",
                "outcome",
                pl.lit(label).alias("step"),
                pl.lit(order, dtype=pl.Int64).alias("step_order"),
                pl.col(column).fill_null(0).cast(pl.Int64).alias("samples"),
                lost.cast(pl.Int64).alias("samples_lost"),
            )
        )
        previous = column
    return (
        pl.concat(steps)
        .with_columns(
            (pl.col("dataset") + "|" + pl.col("step_order").cast(pl.Utf8)).alias("step_key"),
            (pl.col("samples") > 0).cast(pl.Int64).alias("dataset_in"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort("step_order", "dataset")
    )
