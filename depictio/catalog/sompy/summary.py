"""Normalize the som.py somatic benchmark summary into a tidy per-caller table.

Consumes the pipeline-aggregated ``indel/summary/tables/sompy/sompy.summary.csv``
(``HAPPY_SOMPY`` collated across callers). One row per somatic callset × variant type, with
precision/recall/F1 and the binomial confidence intervals som.py reports. A precision without
calls and a recall without truth variants are null, not som.py's 0.0. ``caller`` is the
tool that made the calls, ``label`` the callset's samplesheet id and ``truth_set`` the truth
set it was compared against, read off the ``<id>.<truth set>.<caller>`` file name.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sompy_summary",
        glob_pattern="*/summary/tables/sompy/sompy.summary.csv",
        format="CSV",
        input_schema={
            "Tool": pl.Utf8,
            "Type": pl.Utf8,
            "TP_comp": pl.Int64,
            "FP": pl.Int64,
            "FN": pl.Int64,
            "Recall": pl.Float64,
            "Precision": pl.Float64,
            "F1": pl.Float64,
        },
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


def null_undefined_metrics(df: pl.DataFrame) -> pl.DataFrame:
    """Null each ratio whose denominator is 0 instead of keeping som.py's 0.0.

    som.py prints 0.0 for a precision without calls (``tp + fp == 0``) and for a
    recall without truth variants (``tp + fn == 0``). Both are undefined, and a 0.0
    reads as a measured failure; F1 is undefined as soon as either one is. Rows whose
    counts are missing keep the tool's values.
    """
    no_calls = (pl.col("tp") + pl.col("fp")) == 0
    no_truth = (pl.col("tp") + pl.col("fn")) == 0
    null = pl.lit(None, dtype=pl.Float64)
    return df.with_columns(
        pl.when(no_calls).then(null).otherwise(pl.col("precision")).alias("precision"),
        pl.when(no_truth).then(null).otherwise(pl.col("recall")).alias("recall"),
        pl.when(no_calls | no_truth).then(null).otherwise(pl.col("f1")).alias("f1"),
    )


#: Truth-set size in the pipeline's harmonised table; absent from older tables.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {"tp_base": pl.Int64}

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
# som.py always emits the binomial confidence intervals, so they are required
# output columns — the `metric_ci_bars` render (catalog/sompy/summary.yaml) binds them.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "caller": pl.Utf8,
    "label": pl.Utf8,  # callset id in the pipeline samplesheet
    "truth_set": pl.Utf8,  # null when the table has no File column
    "variant_type": pl.Utf8,
    "tp": pl.Int64,
    "fp": pl.Int64,
    "fn": pl.Int64,
    "recall": pl.Float64,
    "precision": pl.Float64,
    "f1": pl.Float64,
    "recall_lower": pl.Float64,
    "recall_upper": pl.Float64,
    "precision_lower": pl.Float64,
    "precision_upper": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename som.py columns to the tidy schema and cast numeric types."""
    df = sources["sompy_summary"]

    # `Caller` is the tool that made the calls, `Tool` the callset's samplesheet id
    # (a table without a `Caller` column falls back to `Tool`).
    df = df.with_columns(
        pl.col("Tool").cast(pl.Utf8).alias("label"),
        (truth_set_expr() if "File" in df.columns else pl.lit(None, dtype=pl.Utf8)).alias(
            "truth_set"
        ),
    )
    caller_src = "Caller" if "Caller" in df.columns else "Tool"
    df = df.with_columns(pl.col(caller_src).cast(pl.Utf8).alias("caller"))
    df = df.rename({"Type": "variant_type"})

    # The pipeline's harmonised som.py table puts the truth-set size in TP_base and the
    # true positives in TP_comp (TP_comp + FN == TP_base), so `tp` reads TP_comp.
    for out, src in (("tp", "TP_comp"), ("fp", "FP"), ("fn", "FN")):
        df = df.with_columns(pl.col(src).cast(pl.Int64, strict=False).alias(out))
    if "TP_base" in df.columns:
        df = df.with_columns(pl.col("TP_base").cast(pl.Int64, strict=False).alias("tp_base"))
    for out, src in (("recall", "Recall"), ("precision", "Precision"), ("f1", "F1")):
        df = df.with_columns(pl.col(src).cast(pl.Float64, strict=False).alias(out))
    df = null_undefined_metrics(df)
    for col_name in ("recall_lower", "recall_upper", "precision_lower", "precision_upper"):
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).cast(pl.Float64, strict=False))

    keep = [
        "caller",
        "label",
        "truth_set",
        "variant_type",
        "tp_base",
        "tp",
        "fp",
        "fn",
        "recall",
        "precision",
        "f1",
        "recall_lower",
        "recall_upper",
        "precision_lower",
        "precision_upper",
    ]
    return df.select([c for c in keep if c in df.columns])
