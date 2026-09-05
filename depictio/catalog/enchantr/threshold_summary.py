"""Clonal distance threshold per subject, from enchantR's find-threshold report.

``clonal_analysis/find_threshold/all_reps_dist_report/tables/all_reps_threshold-summary.tsv``
records, per subject (the report's ``fields`` column, renamed here to
``subject_id``), the nearest-neighbour distance model shazam fitted, the
``threshold`` that separates clonally related from unrelated sequences, the
sensitivity and specificity that threshold achieves, and ``mean_threshold``, the
value airrflow ends up applying across subjects.

Only written when the run used ``--clonal_threshold auto``; a run with an
explicit threshold has nothing to fit and writes no report.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path=(
            "clonal_analysis/find_threshold/all_reps_dist_report/tables/"
            "all_reps_threshold-summary.tsv"
        ),
        format="TSV",
    ),
]

_FLOAT_COLS = ["loglk", "threshold", "sensitivity", "specificity", "pvalue", "mean_threshold"]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "subject_id": pl.Utf8,
    "model": pl.Utf8,
    "cutoff": pl.Utf8,
    **{c: pl.Float64 for c in _FLOAT_COLS},
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename the grouping column and cast the fit statistics."""
    df = sources["summary"]
    if "fields" in df.columns:
        df = df.rename({"fields": "subject_id"})
    return df.select(
        pl.col("subject_id").cast(pl.Utf8),
        pl.col("model").cast(pl.Utf8),
        pl.col("cutoff").cast(pl.Utf8),
        *[pl.col(c).cast(pl.Float64) for c in _FLOAT_COLS if c in df.columns],
    ).sort("subject_id")
