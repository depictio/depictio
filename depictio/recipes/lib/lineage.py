"""QIIME2 lineage helpers shared by the taxonomy recipes.

**Why this exists.** QIIME2's collapsed tables (``rel_abundance_tables/rel-table-N.tsv``,
``barplot/level-N.csv``, ``ancombc/differentials/…-level-N/``) are addressed by
*depth*, not by rank name: level N holds the N-th taxonomic rank of whatever
reference database the run classified against. That depth is not a constant.
DADA2 databases declare their own ``taxlevels``:

* ``rdp``, ``silva`` … → ``Domain,Kingdom,Phylum,…`` collapsed to 7 emitted ranks,
  so a level-2 lineage reads ``Bacteria;Proteobacteria`` — leaf = Phylum.
* ``sbdi-gtdb`` (nf-core/ampliseq's default from 2.18.0) → 8 ranks with Domain
  *and* Kingdom, so level-2 reads ``Bacteria;Bacteria`` and the Phylum only
  appears at level 3 (``Bacteria;Bacteria;Pseudomonadota``).

A recipe that reads ranks by absolute position (``segment 0 = Kingdom``,
``segment 1 = Phylum``) therefore silently mislabels every taxon as soon as the
run's database has a different depth — no schema changes, no error, just wrong
names on every chart. Reading from the *tail* instead is stable: whatever table
depth the template points at, the last segment is the rank that table collapses
to and the one before it is its parent.

Templates still choose the level (that is a pipeline-version fact, pinned in
``template.yaml``); these helpers make the parsing of whatever comes back
independent of how many ranks sit above it.
"""

from __future__ import annotations

import polars as pl

UNCLASSIFIED = "Unclassified"

# Non-abundance columns of ``rel-table-ASV_with-*-tax.tsv``. Everything else in
# that table is a per-sample abundance column. ``Domain`` and ``Species_exact``
# only appear for some databases/versions — listing them here keeps them out of
# the sample set rather than having them read as an all-null abundance column.
ASV_META_COLS: tuple[str, ...] = (
    "ID",
    "Domain",
    "Kingdom",
    "Phylum",
    "Class",
    "Order",
    "Family",
    "Genus",
    "Species",
    "Species_exact",
    "confidence",
    "sequence",
    # Added by the SILVA + PR2 merge (lib/dual_taxonomy.py), never a sample.
    "taxonomy_source",
)

# The ranks depictio's taxonomy DCs expose, in hierarchy order. ``Domain`` is
# deliberately absent: it duplicates ``Kingdom`` on the databases that emit both,
# and a rank that exists for only some runs cannot be a stable dashboard column.
CANONICAL_RANKS: tuple[str, ...] = ("Kingdom", "Phylum", "Class", "Order", "Family", "Genus")


def _segments(lineage: pl.Expr) -> pl.Expr:
    """``"a;b;c"`` → ``["a", "b", "c"]``, whitespace stripped."""
    return lineage.str.split(";").list.eval(pl.element().str.strip_chars())


def _nonempty(segment: pl.Expr) -> pl.Expr:
    """Null out a missing-or-blank segment so ``coalesce`` can skip it."""
    return pl.when(segment.is_null() | (segment == "")).then(None).otherwise(segment)


def rank_at(lineage: pl.Expr, position: int) -> pl.Expr:
    """The ``position``-th rank of a collapsed lineage, ``Unclassified`` when blank.

    Positional, for the collapsed ``rel-table-N`` fallbacks that carry no rank
    names. An 8-rank database (sbdi-gtdb) writes its Domain *and* Kingdom, so
    a lineage opens ``Bacteria;Bacteria;Pseudomonadota``: that repeated top
    segment is dropped first, or every rank below it shifts by one (the Phylum
    lands in the Class column and the Kingdom ring is drawn twice).
    """
    segments = _segments(lineage)
    first = segments.list.get(0, null_on_oob=True)
    second = segments.list.get(1, null_on_oob=True)
    deduped = (
        pl.when(first.is_not_null() & (first != "") & (first == second))
        .then(segments.list.slice(1))
        .otherwise(segments)
    )
    return _nonempty(deduped.list.get(position, null_on_oob=True)).fill_null(UNCLASSIFIED)


def leaf_rank(lineage: pl.Expr) -> pl.Expr:
    """The rank the table collapses to: the last non-empty lineage segment.

    QIIME2 writes unknown ranks as empty segments (``Bacteria;`` or
    ``Bacteria;Bacteria;``), which become ``Unclassified``.
    """
    segments = _segments(lineage)
    return (
        pl.when(segments.list.len() < 2)
        .then(pl.lit(UNCLASSIFIED))
        .otherwise(_nonempty(segments.list.get(-1, null_on_oob=True)).fill_null(UNCLASSIFIED))
    )


def parent_rank(lineage: pl.Expr) -> pl.Expr:
    """The rank directly above the leaf, falling back to the lineage root.

    A single-segment lineage (``Bacteria``) *is* its own root, and a lineage
    whose parent segment is blank (``Bacteria;;Pseudomonadota``) falls back to
    the deepest ancestor that is named.
    """
    segments = _segments(lineage)
    root = _nonempty(segments.list.first())
    parent = _nonempty(segments.list.get(-2, null_on_oob=True))
    return (
        pl.when(segments.list.len() < 2)
        .then(root.fill_null(UNCLASSIFIED))
        .otherwise(pl.coalesce(parent, root, pl.lit(UNCLASSIFIED)))
    )


def root_rank(lineage: pl.Expr) -> pl.Expr:
    """The first named segment of the lineage: its Kingdom or Domain, whatever the depth.

    `parent_rank` is the Kingdom only at Phylum depth, where the leaf's parent is
    the root. A table collapsed deeper (PR2 at its Subdivision, ``Eukaryota;TSAR;
    Alveolata;Dinoflagellata``) has the Supergroup there instead.
    """
    return _nonempty(_segments(lineage).list.first()).fill_null(UNCLASSIFIED)


def kingdom_phylum(lineage: pl.Expr) -> list[pl.Expr]:
    """``[Kingdom, Phylum]`` expressions for a table collapsed at Phylum depth.

    Use with ``with_columns``. The template is responsible for pointing the
    recipe at the level that *is* Phylum for the run's database; this reads that
    level's leaf as the Phylum and its parent as the Kingdom, so both the 7-rank
    (``Bacteria;Proteobacteria``) and 8-rank (``Bacteria;Bacteria;Pseudomonadota``)
    dialects land on the same two columns.
    """
    return [parent_rank(lineage).alias("Kingdom"), leaf_rank(lineage).alias("Phylum")]


def asv_sample_columns(asv_tax: pl.DataFrame) -> list[str]:
    """Per-sample abundance columns of an ASV × taxonomy table.

    nf-core/ampliseq >= 3.0 adds one ``<rank>_confidence`` column per rank next
    to ``confidence``; those are not samples either.
    """
    return [c for c in asv_tax.columns if c not in ASV_META_COLS and not c.endswith("_confidence")]


def with_kingdom(asv_tax: pl.DataFrame) -> pl.DataFrame:
    """The table's top rank as ``Kingdom``, the name the taxonomy DCs expose.

    nf-core/ampliseq >= 3.0 names the top rank after what the database holds:
    ``Domain`` for GTDB, SILVA 138, RDP, Greengenes2 and sbdi-gtdb (whose 2.x
    tables repeated it as ``Domain`` *and* ``Kingdom``). A table with both keeps
    its ``Kingdom``; one with only a ``Domain`` reads it as the top rank.
    """
    if "Kingdom" in asv_tax.columns or "Domain" not in asv_tax.columns:
        return asv_tax
    return asv_tax.rename({"Domain": "Kingdom"})


def asv_table_to_ranks(
    asv_tax: pl.DataFrame, ranks: tuple[str, ...] = CANONICAL_RANKS
) -> pl.DataFrame:
    """Aggregate ``rel-table-ASV_with-DADA2-tax.tsv`` to ``(sample_id, *ranks, abundance)``.

    The ASV table carries its ranks as **named columns**, so it needs no
    positional lineage parsing and stays correct whatever depth the run's
    database has — which is why the hierarchical DCs (sunburst, Sankey) prefer
    it over the deepest collapsed ``rel-table-N``: under an 8-rank database that
    table stops at Family and there is no rel-table-7 to reach the Genus.

    Abundances are summed per taxon tuple, reproducing exactly what a collapsed
    table at that depth holds. Blank rank cells become ``Unclassified``.
    """
    asv_tax = with_kingdom(asv_tax)
    present = [r for r in ranks if r in asv_tax.columns]
    if not present:
        raise ValueError(
            f"ASV taxonomy table carries none of the expected ranks {ranks}; got {asv_tax.columns}"
        )
    sample_cols = asv_sample_columns(asv_tax)
    if not sample_cols:
        raise ValueError("ASV taxonomy table has no per-sample abundance columns")

    long = asv_tax.select([*present, *sample_cols]).unpivot(
        on=sample_cols,
        index=present,
        variable_name="sample_id",
        value_name="abundance",
    )
    return (
        long.with_columns(
            [
                pl.when(pl.col(r).is_null() | (pl.col(r).cast(pl.Utf8).str.strip_chars() == ""))
                .then(pl.lit(UNCLASSIFIED))
                .otherwise(pl.col(r).cast(pl.Utf8))
                .alias(r)
                for r in present
            ]
            + [
                pl.col("sample_id").cast(pl.Utf8),
                pl.col("abundance").cast(pl.Float64, strict=False),
            ]
        )
        .group_by(["sample_id", *present])
        .agg(pl.col("abundance").sum())
        .select(["sample_id", *present, "abundance"])
    )
