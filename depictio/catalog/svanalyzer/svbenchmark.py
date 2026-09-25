"""Normalize an SVanalyzer (svbenchmark) structural-variant summary into a tidy table.

Targets the pipeline-aggregated ``summary/tables/svbenchmark/svbenchmark.summary.csv``,
collated from the per-sample SVanalyzer ``*.report``. The pipeline writes everything under ``<outdir>/<variant_type>/``, and ``variant_type``
is one of small, snv, indel, structural or copynumber, so the source is anchored on that
one directory level rather than on a value: naming a value pins the recipe to a single
route, and two of the values a recipe can meet are not the ones a reader would guess.

Pinned against a real ``germline_sv`` run. SVanalyzer reports no ``TP_comp``, so that column
is absent from the output where Truvari has it.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="svbenchmark_summary",
        glob_pattern="*/summary/tables/svbenchmark/svbenchmark.summary.csv",
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
    "precision": pl.Float64,
    "recall": pl.Float64,
    "f1": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "caller": pl.Utf8,  # the tool that made the calls (pipeline `Caller` column)
    "truth_set": pl.Utf8,  # read off the `<id>.<truth set>.<caller>.<ext>` File name
    "tp": pl.Int64,
    "fp": pl.Int64,
    "fn": pl.Int64,
}


def _find(df: pl.DataFrame, *candidates: str) -> str | None:
    norm = {c.lower().replace("-", "").replace("_", "").replace(".", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace("-", "").replace("_", "").replace(".", "")
        if key in norm:
            return norm[key]
    return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Resolve svbenchmark metric columns tolerantly. SVanalyzer reports sensitivity/precision."""
    df = sources["svbenchmark_summary"]

    label_col = _find(df, "Tool", "sample", "label", "File")
    df = (
        df.with_columns(pl.col(label_col).cast(pl.Utf8).alias("label"))
        if label_col
        else df.with_columns(pl.lit("svbenchmark").alias("label"))
    )

    caller_col = _find(df, "Caller")
    if caller_col is not None:
        df = df.with_columns(pl.col(caller_col).cast(pl.Utf8).alias("caller"))
    if "File" in df.columns and "Tool" in df.columns:
        df = df.with_columns(truth_set_expr().alias("truth_set"))

    prec = _find(df, "precision", "ppv")
    rec = _find(df, "recall", "sensitivity")
    if prec is None or rec is None:
        raise ValueError(f"svbenchmark_summary: missing precision/recall in {df.columns}")
    df = df.with_columns(
        pl.col(prec).cast(pl.Float64, strict=False).alias("precision"),
        pl.col(rec).cast(pl.Float64, strict=False).alias("recall"),
    )

    f1_col = _find(df, "f1", "f1_score", "fmeasure")
    if f1_col is not None:
        df = df.with_columns(pl.col(f1_col).cast(pl.Float64, strict=False).alias("f1"))
    else:
        df = df.with_columns(
            (
                2
                * pl.col("precision")
                * pl.col("recall")
                / (pl.col("precision") + pl.col("recall"))
            ).alias("f1")
        )

    for out, *cands in (("tp", "TP"), ("fp", "FP"), ("fn", "FN")):
        col = _find(df, *cands)
        if col is not None:
            df = df.with_columns(pl.col(col).cast(pl.Int64, strict=False).alias(out))

    keep = ["label", "caller", "truth_set", "precision", "recall", "f1", "tp", "fp", "fn"]
    return df.select([c for c in keep if c in df.columns])
