"""Normalize an rtg-tools vcfeval aggregated summary into a tidy benchmark table.

Consumes the pipeline-aggregated ``summary/tables/rtgtools/rtgtools.summary.csv``
(``RTGTOOLS_VCFEVAL`` outputs collated per category). The pipeline writes everything under ``<outdir>/<variant_type>/``, and ``variant_type``
is one of small, snv, indel, structural or copynumber, so the source is anchored on that
one directory level rather than on a value: naming a value pins the recipe to a single
route, and two of the values a recipe can meet are not the ones a reader would guess.

The same recipe therefore serves the germline and the somatic categories without a
``source_overrides`` entry per route.

Every row is one benchmarked callset: ``Tool`` is its id in the pipeline samplesheet
(exposed as ``label``), ``Caller`` the caller the samplesheet names for it (``caller``), and
the truth set it was compared against is the second token of the ``File`` name
(``<id>.<truth set>.<caller>.summary.txt``, exposed as ``truth_set``). The vocabulary is the
same on the germline and the somatic route: ``caller`` is always the tool that made the calls,
never the truth set. The threshold sweep is collapsed to the canonical summary row
(``Threshold == "None"``).
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rtgtools_summary",
        glob_pattern="*/summary/tables/rtgtools/rtgtools.summary.csv",
        format="CSV",
    ),
]


#: The pipeline names every per-callset file ``<id>.<truth set>.<caller>.<ext>``
#: and its summary tables carry that name in ``File`` next to ``Tool`` (the
#: samplesheet id) and ``Caller``, so the truth set is the token after the id.
def truth_set_expr(file_col: str = "File", tool_col: str = "Tool") -> pl.Expr:
    """The truth-set token of the pipeline's ``<id>.<truth>.<caller>.<ext>`` file name."""
    return (
        pl.col(file_col)
        .cast(pl.Utf8)
        .str.strip_prefix(pl.col(tool_col).cast(pl.Utf8) + pl.lit("."))
        .str.split(".")
        .list.first()
    )


EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "label": pl.Utf8,
    "caller": pl.Utf8,
    "truth_set": pl.Utf8,  # null when the table has no File column
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

    df = df.with_columns(
        (truth_set_expr() if "File" in df.columns else pl.lit(None, dtype=pl.Utf8)).alias(
            "truth_set"
        )
    ).rename({"Tool": "label", "Caller": "caller"})

    for col_name in ("tp_base", "tp_comp", "fp", "fn"):
        src = {"tp_base": "TP_base", "tp_comp": "TP_comp", "fp": "FP", "fn": "FN"}[col_name]
        df = df.with_columns(pl.col(src).cast(pl.Int64, strict=False).alias(col_name))
    for col_name in ("precision", "recall", "f1"):
        src = {"precision": "Precision", "recall": "Recall", "f1": "F1"}[col_name]
        df = df.with_columns(pl.col(src).cast(pl.Float64, strict=False).alias(col_name))

    return df.select(
        [
            "label",
            "caller",
            "truth_set",
            "tp_base",
            "tp_comp",
            "fp",
            "fn",
            "precision",
            "recall",
            "f1",
        ]
    )
