"""Contig order shared by the recipes whose output is read along a contig axis.

A text sort puts ``chr10`` before ``chr2``, so a bar or a line drawn per contig
reads out of order. The karyotype order is the one a reader expects: numbered
chromosomes by number, then X, Y, the mitochondrion, then everything else
(unplaced, alt, decoy) in name order, and mosdepth's ``total`` roll-up last.
The ``chr`` prefix and the case are read through, so a UCSC and an Ensembl
reference sort the same way.
"""

from __future__ import annotations

import polars as pl

#: Rank of the groups after the numbered chromosomes.
_SEX_RANK = {"X": 1, "Y": 2}
_MITO_NAMES = ("M", "MT")
_TOTAL = "TOTAL"


def contig_rank(column: str = "chrom") -> pl.Expr:
    """Sort key of a contig column: numbered chromosomes first, then X, Y, M, the rest, ``total``.

    Numbered chromosomes rank by their number (1 to 999), so the key is
    comparable across references. Use it with the name as a tie-breaker:
    ``df.sort([contig_rank("chrom"), "chrom"])``.
    """
    name = pl.col(column).str.replace(r"(?i)^chr", "").str.to_uppercase()
    number = name.str.extract(r"^(\d{1,3})$", 1).cast(pl.Int64, strict=False)
    return (
        pl.when(number.is_not_null())
        .then(number)
        .when(name == "X")
        .then(pl.lit(1000 + _SEX_RANK["X"]))
        .when(name == "Y")
        .then(pl.lit(1000 + _SEX_RANK["Y"]))
        .when(name.is_in(_MITO_NAMES))
        .then(pl.lit(1003))
        .when(name == _TOTAL)
        .then(pl.lit(9999))
        .otherwise(pl.lit(2000))
        .cast(pl.Int64)
        .alias("_contig_rank")
    )


def sort_contigs(df: pl.DataFrame, column: str = "chrom", *by: str) -> pl.DataFrame:
    """Sort ``df`` by the ``by`` columns, then by contig in karyotype order, then by name."""
    return df.sort([*by, contig_rank(column), column])
