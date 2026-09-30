"""Shared helpers of the nf-core/proteinannotator recipes.

Several recipes of ``depictio/catalog/proteinannotator/`` need the same two
things: the fixed list of annotation databases the pipeline searches (so a
skipped database still gets its column, full of zeros, rather than a missing
one), and the residues each domain span covers. Recipes may not import one
another, so both live here.
"""

from __future__ import annotations

import polars as pl

#: The databases nf-core/proteinannotator searches, in the order the pipeline
#: runs them: four HMM libraries through hmmsearch, then InterProScan.
DATABASES: tuple[str, ...] = ("pfam", "funfam", "nmpfams", "metagroot", "interproscan")


def covered_positions(domains: pl.DataFrame, by: tuple[str, ...] = ("entity",)) -> pl.DataFrame:
    """One row per residue a domain span covers: ``by`` columns + ``position``.

    Spans are 1-based and inclusive. Overlapping spans of the same ``by`` key
    are counted once, so ``len()`` per key is the number of covered residues.
    """
    keys = list(by)
    if domains.is_empty():
        return pl.DataFrame(
            schema={**{k: domains.schema.get(k, pl.Utf8) for k in keys}, "position": pl.Int64}
        )
    spans = domains.filter(
        pl.col("start").is_not_null()
        & pl.col("end").is_not_null()
        & (pl.col("end") >= pl.col("start"))
    )
    return (
        spans.select(*keys, pl.int_ranges(pl.col("start"), pl.col("end") + 1).alias("position"))
        .explode("position")
        .with_columns(pl.col("position").cast(pl.Int64))
        .unique()
    )
