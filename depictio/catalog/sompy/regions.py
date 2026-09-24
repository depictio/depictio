"""Reshape the som.py region-stratified benchmark into a caller × AF-bin metrics table.

Consumes ``indel/summary/tables/sompy/sompy.regions.csv``. som.py encodes the
allele-fraction stratum inside the ``Type`` column as ``indels.<lo>-<hi>``; we split that
into a clean ``af_bin`` so the result drives a caller × AF-bin heatmap of recall/precision/F1.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sompy_regions",
        glob_pattern="*/summary/tables/sompy/sompy.regions.csv",
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
    "caller": pl.Utf8,
    "label": pl.Utf8,  # callset id in the pipeline samplesheet
    "truth_set": pl.Utf8,  # null when the table has no File column
    "af_bin": pl.Utf8,
    "recall": pl.Float64,
    "precision": pl.Float64,
    "f1": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "tp": pl.Int64,
    "fp": pl.Int64,
    "fn": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split the AF stratum out of ``Type`` and standardize metric columns."""
    df = sources["sompy_regions"]

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

    # ``Type`` is e.g. "indels.0.000000-0.200000" -> af_bin "0.000000-0.200000".
    df = df.with_columns(pl.col("Type").cast(pl.Utf8).str.replace(r"^[^.]*\.", "").alias("af_bin"))

    for out, src in (("recall", "Recall"), ("precision", "Precision"), ("f1", "F1")):
        df = df.with_columns(pl.col(src).cast(pl.Float64, strict=False).alias(out))
    # The pipeline's harmonised som.py table puts the truth-set size in TP_base and the
    # true positives in TP_comp (TP_comp + FN == TP_base), so `tp` reads TP_comp.
    for out, src in (("tp", "TP_comp"), ("fp", "FP"), ("fn", "FN")):
        if src in df.columns:
            df = df.with_columns(pl.col(src).cast(pl.Int64, strict=False).alias(out))

    keep = ["caller", "label", "truth_set", "af_bin", "recall", "precision", "f1", "tp", "fp", "fn"]
    return df.select([c for c in keep if c in df.columns])
