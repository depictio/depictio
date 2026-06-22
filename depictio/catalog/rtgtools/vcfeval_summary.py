"""Normalize an rtg-tools vcfeval aggregated summary into a tidy benchmark table.

Consumes the pipeline-aggregated ``summary/tables/rtgtools/rtgtools.summary.csv``
(``RTGTOOLS_VCFEVAL`` outputs collated per category). The same recipe serves both the
germline (``small/``) and the somatic (``indel/``) categories — repoint the source via
``source_overrides`` in the data-collection config.

In the germline table the ``Tool`` column carries the *sample* id (test1/test2/test3) and
``Caller`` the truth-set version; in the somatic table ``Tool``/``Caller`` carry the variant
*caller* (mutect2/strelka/freebayes). We expose ``Tool`` as the generic ``label`` so a single
schema covers both; the threshold sweep is collapsed to the canonical summary row
(``Threshold == "None"``).
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rtgtools_summary",
        path="small/summary/tables/rtgtools/rtgtools.summary.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "label": pl.Utf8,
    "caller": pl.Utf8,
    "tp_base": pl.Int64,
    "tp_comp": pl.Int64,
    "fp": pl.Int64,
    "fn": pl.Int64,
    "precision": pl.Float64,
    "recall": pl.Float64,
    "f1": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse the threshold sweep to the summary row and standardize column names."""
    df = sources["rtgtools_summary"]

    # Keep the canonical (non-thresholded) summary row per tool. ``Threshold`` mixes the
    # literal "None" with numeric strings, so polars reads it as Utf8.
    if "Threshold" in df.columns:
        df = df.with_columns(pl.col("Threshold").cast(pl.Utf8))
        if (df["Threshold"] == "None").any():
            df = df.filter(pl.col("Threshold") == "None")

    df = df.rename({"Tool": "label", "Caller": "caller"})

    for col_name in ("tp_base", "tp_comp", "fp", "fn"):
        src = {"tp_base": "TP_base", "tp_comp": "TP_comp", "fp": "FP", "fn": "FN"}[col_name]
        df = df.with_columns(pl.col(src).cast(pl.Int64, strict=False).alias(col_name))
    for col_name in ("precision", "recall", "f1"):
        src = {"precision": "Precision", "recall": "Recall", "f1": "F1"}[col_name]
        df = df.with_columns(pl.col(src).cast(pl.Float64, strict=False).alias(col_name))

    return df.select(
        ["label", "caller", "tp_base", "tp_comp", "fp", "fn", "precision", "recall", "f1"]
    )
