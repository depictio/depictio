"""deepTools plotCorrelation matrix as a square table, one row per sample.

``plotCorrelation --outFileCorMatrix`` writes the pairwise correlation of the
``multiBamSummary`` bin counts: a comment line, then a header naming every
sample and one row per sample holding its correlation with each of them. The
names are single-quoted in both the header and the first column, which is a
quirk of the R writer rather than data, so they are unquoted here.

The frame is left square rather than melted into (row, column, value) triples
because that is the shape ``complex_heatmap`` binds: an index column plus one
value column per sample.

Output schema:
    sample : Utf8       library the row belongs to
    <sample> : Float64  one column per library, its correlation with the row
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="matrix",
        glob_pattern="**/*.plotCorrelation.mat.tab",
        format="TSV",
        read_kwargs={"infer_schema_length": 0, "comment_prefix": "#", "quote_char": None},
    ),
]

# The row-label column is the only fixed one: every other column is a sample of
# the run, so the schema is declared by the index alone and the rest is checked
# by `validate_output` against the fixture.
EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
}


def _unquote(name: str) -> str:
    return name.strip().strip("'\"")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unquote the labels and name the row column `sample`."""
    raw = sources["matrix"]
    if raw.is_empty():
        raise ValueError("deeptools_correlation_matrix: the matched matrix file is empty")
    if len(raw.columns) < 2:
        raise ValueError(
            f"deeptools_correlation_matrix: expected a label column and at least one "
            f"sample, got {raw.columns}"
        )

    label_column, *value_columns = raw.columns
    return raw.select(
        pl.col(label_column).cast(pl.Utf8).str.strip_chars("'\" ").alias("sample"),
        *[pl.col(c).cast(pl.Float64, strict=False).alias(_unquote(c)) for c in value_columns],
    ).sort("sample")
