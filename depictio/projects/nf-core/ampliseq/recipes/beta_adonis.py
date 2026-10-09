"""Collect ampliseq's PERMANOVA (adonis) tables into one row per metric and term.

With ``--qiime_adonis_formula`` set, ampliseq runs ``qiime diversity adonis`` on
each beta-diversity distance matrix and writes
``qiime2/diversity/beta_diversity/adonis/<metric>_distance_matrix-<formula>/adonis.tsv``.
Each table is R's ``anova`` layout: one row per formula term, then ``Residual``
and ``Total``, with the term in an unnamed first column (so the header holds
one name fewer than the rows hold fields).

The recipe reads the rows without the header, names the six fields, takes the
metric and formula from the folder name, and keeps the term rows: ``r2`` is the
share of between-sample variation the term explains, ``p_value`` its permutation
p-value. Residual and Total carry no test and are dropped.

With a ``group_col`` param only that term's rows are kept, so a dashboard can
read the grouping factor's R² without naming the column in a ``filter_expr``:
without metadata ``GROUP_COL`` resolves to the ``__no_group__`` sentinel, which
the filter guard rejects. The sentinel matches no term, so the optional DC is
skipped.

Output columns:
    metric, formula, term, df, sum_of_squares, r2, f_stat, p_value
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

_SOURCE_PATH = "_source_path"
_FIELDS = ["term", "df", "sum_of_squares", "r2", "f_stat", "p_value"]
# `adonis/bray_curtis_distance_matrix-habitat/adonis.tsv` -> (bray_curtis, habitat)
_FOLDER = r"adonis/([^/]+)_distance_matrix-([^/]+)/adonis\.tsv$"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="adonis",
        glob_pattern="qiime2/diversity/beta_diversity/adonis/*/adonis.tsv",
        format="TSV",
        source_path=_SOURCE_PATH,
        read_kwargs={
            "has_header": False,
            "skip_rows": 1,
            "new_columns": _FIELDS,
            "infer_schema_length": 0,
            "null_values": ["NA", ""],
        },
        input_schema={field: pl.Utf8 for field in _FIELDS},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "metric": pl.Utf8,
    "formula": pl.Utf8,
    "term": pl.Utf8,
    "df": pl.Int64,
    "sum_of_squares": pl.Float64,
    "r2": pl.Float64,
    "f_stat": pl.Float64,
    "p_value": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """One row per distance metric and formula term (only ``group_col``'s when set)."""
    df = sources["adonis"]
    df = df.filter(~pl.col("term").is_in(["Residual", "Total"]))
    if group_col := (params or {}).get("group_col"):
        df = df.filter(pl.col("term") == group_col)
    return df.select(
        pl.col(_SOURCE_PATH).str.extract(_FOLDER, 1).alias("metric"),
        pl.col(_SOURCE_PATH).str.extract(_FOLDER, 2).alias("formula"),
        pl.col("term"),
        pl.col("df").cast(pl.Int64, strict=False),
        pl.col("sum_of_squares").cast(pl.Float64, strict=False),
        pl.col("r2").cast(pl.Float64, strict=False),
        pl.col("f_stat").cast(pl.Float64, strict=False),
        pl.col("p_value").cast(pl.Float64, strict=False),
    ).sort("metric", "formula", "term")
