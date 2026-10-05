"""Edit outcome composition, one row per library and outcome class.

Melts ``<sample>_edits.csv`` (reads per class as counted by the CIGAR parser)
into long form with each class's share of the library's classified reads, the
shape a stacked composition bar reads.

Output:
    sample : Utf8     library id
    outcome : Utf8    outcome class (wild type, template-based, deletion-insertion,
                      in-frame or frameshift insertion or deletion)
    level : Utf8      constant "Outcome", the composition bar's rank
    reads : Int64     reads in the class
    pct : Float64     share of the library's classified reads, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import (
    OUTCOME_COLUMNS,
    first_matching,
    num,
    rounded,
    sample_expr,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="edits",
        glob_pattern="**/*_edits.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", ""]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "outcome": pl.Utf8,
    "level": pl.Utf8,
    "reads": pl.Int64,
    "pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["edits"]
    exprs = [sample_expr()]
    for raw, label in OUTCOME_COLUMNS.items():
        src = first_matching(df.columns, raw)
        expr = num(src, pl.Int64) if src else pl.lit(0, dtype=pl.Int64)
        exprs.append(expr.fill_null(0).cast(pl.Int64).alias(label))
    wide = df.select(exprs).unique(subset=["sample"], keep="first")
    long = wide.unpivot(index="sample", variable_name="outcome", value_name="reads")
    total = pl.col("reads").sum().over("sample")
    order = {label: i for i, label in enumerate(OUTCOME_COLUMNS.values())}
    return (
        long.with_columns(
            pl.lit("Outcome").alias("level"),
            pl.when(total > 0).then(pl.col("reads") * 100.0 / total).otherwise(0.0).alias("pct"),
            pl.col("outcome").replace_strict(order, return_dtype=pl.Int64).alias("_o"),
        )
        .with_columns(rounded("pct"))
        .sort("sample", "_o")
        .select(list(EXPECTED_SCHEMA))
    )
