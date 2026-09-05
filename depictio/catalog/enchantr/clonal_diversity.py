"""Hill diversity profiles per sample, from the enchantR repertoire analysis report.

``clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/clonal_diversity.tsv``
is alakazam's ``alphaDiversity`` output: for every sample and diversity order
``q`` (0 = richness, 1 = exponential Shannon, 2 = inverse Simpson, sampled on a
fine grid) the bootstrapped Hill number ``d`` with its standard deviation and
confidence band, plus the evenness ``e`` (``d`` divided by ``d`` at q = 0) with
its own band.

The table stays long, one row per sample and q, which is what a profile curve
per sample needs. Filtered to a single q it also reads as one bar with
confidence whiskers per sample.
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

_FLOAT_COLS = ["q", "d", "d_sd", "d_lower", "d_upper", "e", "e_lower", "e_upper"]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    **{c: pl.Float64 for c in _FLOAT_COLS},
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A report without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8)
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cast the diversity profile to a stable schema and order it by sample and q."""
    df = sources["diversity"]
    out = df.select(
        pl.col("sample_id").cast(pl.Utf8),
        _subject(df),
        *[pl.col(c).cast(pl.Float64) for c in _FLOAT_COLS if c in df.columns],
    )
    return out.sort(["sample_id", "q"])
