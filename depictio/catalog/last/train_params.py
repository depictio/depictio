"""Alignment scoring parameters ``last-train`` fitted for each genome pair (``*.train.tsv``).

Before aligning a query genome, ``last-train`` estimates the substitution and gap
costs from a sample of its alignments to the target, and writes the fitted values
for MultiQC as one row: the substitution percent identity of the training
alignments and the ``lastal`` options it will use. The costs follow divergence:
a closer genome gets higher gap costs (gaps are rarer relative to matches), so a
pair whose costs sit apart from genomes of similar identity is worth a look.

The row id is ``<target>___<query>.train``; the ``.train`` suffix is dropped and
the id split into ``target`` and ``query``. The ``lastal`` option names are
spelled out: ``-a`` / ``-A`` are the deletion / insertion opening costs, ``-b`` /
``-B`` the extension costs, ``-t`` the score scale, ``-S`` the strand parameter.

Output columns:
    pair, target, query, training_percent_identity, score_scale,
    deletion_open_cost, insertion_open_cost, deletion_extend_cost,
    insertion_extend_cost, strand_setting
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.genome_pairs import split_pair

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="train",
        glob_pattern="alignment/*.train.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "pair": pl.Utf8,
    "target": pl.Utf8,
    "query": pl.Utf8,
    "training_percent_identity": pl.Float64,
    "score_scale": pl.Float64,
    "deletion_open_cost": pl.Int64,
    "insertion_open_cost": pl.Int64,
    "deletion_extend_cost": pl.Int64,
    "insertion_extend_cost": pl.Int64,
    "strand_setting": pl.Int64,
}

_COLUMNS: dict[str, tuple[str, type[pl.DataType]]] = {
    "substitution_percent_identity": ("training_percent_identity", pl.Float64),
    "last -t": ("score_scale", pl.Float64),
    "last -a": ("deletion_open_cost", pl.Int64),
    "last -A": ("insertion_open_cost", pl.Int64),
    "last -b": ("deletion_extend_cost", pl.Int64),
    "last -B": ("insertion_extend_cost", pl.Int64),
    "last -S": ("strand_setting", pl.Int64),
}


def _value(src: str, dtype: type[pl.DataType], df: pl.DataFrame) -> pl.Expr:
    if src not in df.columns:
        return pl.lit(None, dtype=dtype)
    # Costs are written as floats by some LAST versions ("26.0").
    as_float = pl.col(src).cast(pl.Float64, strict=False)
    return as_float.round(0).cast(pl.Int64) if dtype == pl.Int64 else as_float.round(3)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["train"]
    id_col = "id" if "id" in df.columns else df.columns[0]
    pair = pl.col(id_col).cast(pl.Utf8).str.strip_chars().str.strip_suffix(".train")
    out = df.select(
        *split_pair(pair),
        *[_value(src, dtype, df).alias(dst) for src, (dst, dtype) in _COLUMNS.items()],
    )
    return out.select(list(EXPECTED_SCHEMA)).unique("pair", keep="first").sort("query")
