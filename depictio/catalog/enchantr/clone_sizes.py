"""Clone sizes with a within-sample rank and a clonal-homeostasis size class.

``clone_sizes_table.tsv`` from the enchantR repertoire analysis report lists
every clone of every sample with its sequence count and frequency. The recipe
adds two columns:

* ``rank``: the clone's position within its sample, 1 being the largest. This
  turns the table into a rank-abundance curve: rank against frequency on log
  axes separates a clonally expanded repertoire (a shallow head) from a
  polyclonal one.
* ``size_class``: the clone's frequency binned into the clonal-homeostasis
  classes (rare to hyperexpanded), so the same rows also read as a composition
  of how much of each repertoire sits in expanded clones.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="clone_sizes",
        path=(
            "clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/"
            "clone_sizes_table.tsv"
        ),
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "clone_id": pl.Utf8,
    "seq_count": pl.Int64,
    "seq_freq": pl.Float64,
    "rank": pl.Int64,
    "size_class": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# Clonal-homeostasis bins on clone frequency (upper bound inclusive), the
# convention immunarch's ``repClonality(.method = "homeo")`` popularised.
_SIZE_CLASSES: list[tuple[float, str]] = [
    (1e-5, "Rare (<0.001%)"),
    (1e-4, "Small (0.001-0.01%)"),
    (1e-3, "Medium (0.01-0.1%)"),
    (1e-2, "Large (0.1-1%)"),
]
_TOP_CLASS = "Hyperexpanded (>1%)"


def _size_class(freq: pl.Expr) -> pl.Expr:
    expr = pl.lit(_TOP_CLASS)
    for upper, label in reversed(_SIZE_CLASSES):
        expr = pl.when(freq <= upper).then(pl.lit(label)).otherwise(expr)
    return expr.cast(pl.Utf8)


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A report without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8)
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rank clones within each sample and attach the homeostasis size class."""
    df = sources["clone_sizes"]
    df = df.select(
        pl.col("sample_id").cast(pl.Utf8),
        _subject(df),
        pl.col("clone_id").cast(pl.Utf8),
        pl.col("seq_count").cast(pl.Int64),
        pl.col("seq_freq").cast(pl.Float64),
    )
    return df.sort(
        ["sample_id", "seq_count", "clone_id"], descending=[False, True, False]
    ).with_columns(
        pl.int_range(1, pl.len() + 1).over("sample_id").cast(pl.Int64).alias("rank"),
        _size_class(pl.col("seq_freq")).alias("size_class"),
    )
