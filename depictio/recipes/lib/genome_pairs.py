"""Keys of a pairwise genome alignment: the ``<target>___<query>`` pair id.

nf-core/pairgenomealign aligns every query genome of the samplesheet to one
target genome and names each alignment output ``<target>___<query>``, with the
target name from ``--targetName`` and the query from the samplesheet ``sample``
column. The query is the per-row key every table of a run joins on (one query
per samplesheet row), the target is the same on every row of a run.

The helpers take the pair id from a column when the table carries one
(``o2o.tsv``, ``train.tsv``) and from the file name otherwise (``matrix.txt``,
PSL exports), and never fail on an id without the separator: such an id is read
as a query aligned to an unnamed target.
"""

from __future__ import annotations

import polars as pl

PAIR_SEPARATOR = "___"


def pair_from_path(path_col: str, suffix: str) -> pl.Expr:
    """``alignment/T___Q.o2o.matrix.txt`` -> ``T___Q`` (the basename minus ``suffix``)."""
    return pl.col(path_col).str.split("/").list.last().str.strip_suffix(suffix)


def split_pair(pair: pl.Expr) -> list[pl.Expr]:
    """``pair``, ``target`` and ``query`` columns from a ``<target>___<query>`` id.

    The split is on the LAST separator, so a target name that itself holds
    ``___`` still leaves the query intact; an id without the separator yields a
    null target and the whole id as the query.
    """
    has_sep = pair.str.contains(PAIR_SEPARATOR, literal=True)
    parts = pair.str.split(PAIR_SEPARATOR)
    query = pl.when(has_sep).then(parts.list.last()).otherwise(pair)
    target = (
        pl.when(has_sep)
        .then(parts.list.slice(0, parts.list.len() - 1).list.join(PAIR_SEPARATOR))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
    )
    return [pair.alias("pair"), target.alias("target"), query.alias("query")]
