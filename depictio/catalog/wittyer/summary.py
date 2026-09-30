"""Normalize a Wittyer CNV/SV benchmark summary into a tidy, optionally stratified table.

Targets the pipeline-aggregated ``summary/tables/wittyer/wittyer.summary.csv``, collated
from the per-sample Wittyer ``*.json``, which stratifies precision/recall/F1 by event type and
size bin. The pipeline writes everything under ``<outdir>/<variant_type>/``, and ``variant_type``
is one of small, snv, indel, structural or copynumber, so the source is anchored on that
one directory level rather than on a value: naming a value pins the recipe to a single
route, and two of the values a recipe can meet are not the ones a reader would guess.

Wittyer serves the structural route as well as the copy-number one, so this recipe is reached
by any run that benchmarks with it. Pinned against a real ``germline_sv`` run, whose header
carries an extra ``StatsType`` column alongside the shared metric columns.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="wittyer_summary",
        glob_pattern="*/summary/tables/wittyer/wittyer.summary.csv",
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
    "event_type": pl.Utf8,
    "size_bin": pl.Utf8,
    # Wittyer scores every callset twice, per event and per base; the pipeline's
    # aggregated table keeps that level in `StatsType` (Event / Base) and carries no
    # event-type or size-bin stratum.
    "stats_type": pl.Utf8,
}


def _find(df: pl.DataFrame, *candidates: str) -> str | None:
    norm = {c.lower().replace("-", "").replace("_", "").replace(".", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace("-", "").replace("_", "").replace(".", "")
        if key in norm:
            return norm[key]
    return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Resolve Wittyer metric/stratum columns tolerantly and standardize names."""
    df = sources["wittyer_summary"]

    label_col = _find(df, "Tool", "sample", "label", "File")
    df = (
        df.with_columns(pl.col(label_col).cast(pl.Utf8).alias("label"))
        if label_col
        else df.with_columns(pl.lit("wittyer").alias("label"))
    )

    caller_col = _find(df, "Caller")
    if caller_col is not None:
        df = df.with_columns(pl.col(caller_col).cast(pl.Utf8).alias("caller"))
    if "File" in df.columns and "Tool" in df.columns:
        df = df.with_columns(truth_set_expr().alias("truth_set"))

    prec = _find(df, "precision", "ppv")
    rec = _find(df, "recall", "sensitivity")
    f1_col = _find(df, "f1", "fscore", "f1_score")
    if prec is None or rec is None or f1_col is None:
        raise ValueError(f"wittyer_summary: missing precision/recall/f1 in {df.columns}")
    df = df.with_columns(
        pl.col(prec).cast(pl.Float64, strict=False).alias("precision"),
        pl.col(rec).cast(pl.Float64, strict=False).alias("recall"),
        pl.col(f1_col).cast(pl.Float64, strict=False).alias("f1"),
    )

    et = _find(df, "event_type", "variant_type", "type", "svtype")
    if et is not None:
        df = df.with_columns(pl.col(et).cast(pl.Utf8).alias("event_type"))
    sb = _find(df, "size_bin", "bin", "binid")
    if sb is not None:
        df = df.with_columns(pl.col(sb).cast(pl.Utf8).alias("size_bin"))

    st = _find(df, "StatsType", "stats_type")
    if st is not None:
        df = df.with_columns(pl.col(st).cast(pl.Utf8).alias("stats_type"))

    keep = [
        "label",
        "caller",
        "truth_set",
        "stats_type",
        "event_type",
        "size_bin",
        "precision",
        "recall",
        "f1",
    ]
    return df.select([c for c in keep if c in df.columns])
