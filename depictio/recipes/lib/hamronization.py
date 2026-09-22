"""Fold hAMRonization's per-tool drug-class vocabularies onto one label.

hAMRonization passes each tool's own ``drug_class`` through untouched, so the
field arrives either semicolon separated and lower case from CARD
("macrolide antibiotic; lincosamide antibiotic; streptogramin antibiotic; ...",
up to 126 characters) or slash separated and upper case from AMRFinderPlus
("LINCOSAMIDE/OXAZOLIDINONE/PHENICOL/..."). Both the gene matrix (as a row
annotation strip) and the class matrix (as the row itself) need the two
spellings collapsed onto one short label, and recipes may not import each
other, so the normalisation lives here.
"""

from __future__ import annotations

import polars as pl


def primary_class(col: pl.Expr) -> pl.Expr:
    """The leading drug class, folded across the tool vocabularies.

    Take the first class of a semicolon or slash separated field, drop the
    trailing "antibiotic" and upper-case what is left, so CARD's lower-case
    prose and AMRFinderPlus's upper-case slashes collapse onto one label
    instead of three. Plotly sizes an annotation strip's margin from its
    longest label, so binding the raw field makes the margin exceed the tile;
    this brings a run from 42 labels of up to 126 characters down to 29 of up
    to 35, and leaves the full field on the row for the table to show.
    """
    return (
        col.str.split_exact(";", 1)
        .struct.field("field_0")
        .str.split_exact("/", 1)
        .struct.field("field_0")
        .str.strip_chars()
        .str.replace(r"(?i)\s+antibiotic$", "")
        .str.to_uppercase()
    )
