"""Shared helpers of the nf-core/proteinannotator recipes.

Several recipes of ``depictio/catalog/proteinannotator/`` need the same three
things: the fixed list of annotation databases the pipeline searches (so a
skipped database still gets its column, full of zeros, rather than a missing
one), the residues each domain span covers, and the one spelling of a protein
id every table keys the protein on. Recipes may not import one another, so
all three live here.
"""

from __future__ import annotations

import re

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


#: Characters a protein id may keep: the ones ``indexed_file.sample_from_path`` keeps
#: of a sample id (it is cut into a single S3 path segment), so the id of a protein
#: and the id of a structure file named after it are the same string.
_UNSAFE_ID_CHARS = r"[^A-Za-z0-9._+-]+"


def protein_entity(identifier: str) -> str:
    """The ``entity`` of a protein: its sequence id with every unsafe run turned into ``_``.

    FASTA headers carry ids such as ``GI|225038609|EFDID|719595|FULL`` or
    ``sp|P12345|NAME_HUMAN``, and nf-core/proteinannotator names its S4PRED file
    after them. The same rule as a sample id of an ``indexed_file`` collection
    (``sample_from_path``), so a structure file kept for the protein would
    carry the very same entity: ``GI_225038609_EFDID_719595_FULL``. Leading and
    trailing ``.`` and ``_`` are dropped; an id left empty is returned as written.
    Ids made of safe characters are unchanged.
    """
    return re.sub(_UNSAFE_ID_CHARS, "_", identifier).strip("._") or identifier


def protein_entity_expr(column: str | pl.Expr) -> pl.Expr:
    """:func:`protein_entity` as an expression, for the recipes that work on frames."""
    ident = pl.col(column) if isinstance(column, str) else column
    cleaned = ident.str.replace_all(_UNSAFE_ID_CHARS, "_").str.strip_chars("._")
    return pl.when(cleaned == "").then(ident).otherwise(cleaned)
