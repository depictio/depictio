"""Hill diversity at the three named orders, from the enchantR repertoire analysis report.

Reads the same ``clonal_diversity.tsv`` as ``clonal_diversity.py`` but keeps only
q = 0 (richness), q = 1 (exponential Shannon) and q = 2 (inverse Simpson), each
row labelled in an ``order`` column. A single-choice filter on that label ranks
the samples at one order with their bootstrap confidence interval, without
narrowing the full profile curves that read the long table.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="diversity",
        path=(
            "clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/"
            "clonal_diversity.tsv"
        ),
        format="TSV",
    ),
]

ORDER_LABELS: dict[int, str] = {
    0: "q = 0, richness",
    1: "q = 1, Shannon",
    2: "q = 2, Simpson",
}

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "order": pl.Utf8,
    "q": pl.Float64,
    "d": pl.Float64,
    "d_lower": pl.Float64,
    "d_upper": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Keep the integer orders 0, 1 and 2 and label them."""
    df = sources["diversity"]
    subject = (
        pl.col("subject_id").cast(pl.Utf8)
        if "subject_id" in df.columns
        else pl.lit("all", dtype=pl.Utf8).alias("subject_id")
    )
    out = df.select(
        pl.col("sample_id").cast(pl.Utf8),
        subject,
        *[pl.col(c).cast(pl.Float64) for c in ("q", "d", "d_lower", "d_upper")],
    )
    # The q grid is a float sequence (0, 0.1, ...): match the named orders with a
    # tolerance rather than exact equality.
    q_int = pl.col("q").round(0)
    out = out.filter(((pl.col("q") - q_int).abs() < 1e-6) & q_int.is_in(list(ORDER_LABELS)))
    out = out.with_columns(
        pl.col("q")
        .round(0)
        .cast(pl.Int64)
        .replace_strict(ORDER_LABELS, return_dtype=pl.Utf8)
        .alias("order")
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["q", "sample_id"])
