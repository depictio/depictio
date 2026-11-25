"""One taxonomy from two nf-core/ampliseq runs of the same reads: SILVA and PR2.

An 18S/16S amplicon run classified against SILVA leaves about half of a
plankton community in an unresolved ``Eukaryota;`` group, which PR2 resolves;
PR2 in turn knows nothing useful about bacteria. Run twice on the same reads
(same ASVs, same counts), the two runs differ only in their taxonomy, and the
merged view takes each database where it is strong. Per ASV:

* PR2 calls it Eukaryota (its ``Domain`` starts with ``Eukaryota``, organelle
  labels such as ``Eukaryota:plas`` included) -> the PR2 lineage;
* else -> the SILVA lineage, as it is: Bacteria and Archaea, and the ASVs
  neither database assigns, so every sample still sums to 1.

The merged lineage keeps SILVA's seven slots (Kingdom … Species), so every
recipe downstream reads it as a SILVA table and its Phylum sits at collapse
level 2. PR2 has nine ranks (Domain, Supergroup, Division, Subdivision, Class,
…), two more than SILVA above the Phylum, which is the shift to keep in mind
with its own collapsed outputs: PR2's level 4 (Subdivision) is what SILVA's
level 2 (Phylum) is. For a PR2 ASV the Kingdom slot takes the Domain, the
Phylum slot ``euk_phylum_rank`` (Subdivision by default), and the next PR2 ranks
fill Class … Species in order. For the clades in :data:`DEEPEN` (Metazoa, a
Subdivision holding a quarter of the reads) every slot reads one rank further
down, so the animals show as Arthropoda, Mollusca … rather than one block.

The rule is the one ``bin/build_trec_dualtax.py`` applied by hand on the TREC
AML 2024 project. Abundances come from the SILVA run's table, so the merged
view stays consistent with that run's diversity results.
"""

from __future__ import annotations

import polars as pl

#: SILVA's rank slots, the merged table's rank columns.
SLOTS: tuple[str, ...] = ("Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species")
#: PR2 5.x ranks, as nf-core/ampliseq writes them.
PR2_RANKS: tuple[str, ...] = (
    "Domain",
    "Supergroup",
    "Division",
    "Subdivision",
    "Class",
    "Order",
    "Family",
    "Genus",
    "Species",
)
#: PR2 ranks that may sit in the Phylum slot.
EUK_PHYLUM_RANKS: tuple[str, ...] = ("Division", "Subdivision", "Class")
DEFAULT_EUK_PHYLUM_RANK = "Subdivision"
#: Clades read one PR2 rank deeper (see the module docstring).
DEEPEN: tuple[str, ...] = ("Metazoa",)
PROKARYOTES: tuple[str, ...] = ("Bacteria", "Archaea")
#: Collapse level of the merged Phylum: always SILVA's.
MERGED_PHYLUM_LEVEL = 2

#: Which database named each ASV: ``pr2``, ``silva``, or ``fallback`` (neither
#: assigned it a domain; the SILVA label is kept).
SOURCE_COLUMN = "taxonomy_source"
SOURCES = ("pr2", "silva", "fallback")


def pr2_level(euk_phylum_rank: str = DEFAULT_EUK_PHYLUM_RANK) -> int:
    """PR2's collapse level for ``euk_phylum_rank`` (4 for Subdivision).

    PR2 level N collapses its first N ranks: the level its ANCOM-BC slices and
    barplots must be read at to match the merged (SILVA level 2) Phylum.
    """
    return PR2_RANKS.index(euk_phylum_rank) + 1


def _blank_to_null(col: str) -> pl.Expr:
    """ampliseq writes an unassigned rank as an empty string, DADA2 as NA."""
    return (
        pl.when(pl.col(col).cast(pl.Utf8).str.strip_chars() == "")
        .then(None)
        .otherwise(pl.col(col).cast(pl.Utf8))
        .alias(col)
    )


def merge_pr2(
    asv: pl.DataFrame,
    pr2: pl.DataFrame,
    euk_phylum_rank: str = DEFAULT_EUK_PHYLUM_RANK,
) -> pl.DataFrame:
    """The SILVA ASV table with PR2's lineage on its eukaryotes.

    Args:
        asv: the SILVA run's ASV table (``ID``, the seven rank slots,
            ``confidence``, any other columns, e.g. one per sample). Its rows
            and other columns come back unchanged.
        pr2: the PR2 run's taxonomy of the same ASVs: ``ID`` (or ``ASV_ID``),
            the nine PR2 ranks and ``confidence``. ASVs it lacks keep SILVA's.
        euk_phylum_rank: the PR2 rank placed in the Phylum slot.

    Returns:
        ``asv`` with the rank slots and ``confidence`` replaced where PR2 names
        a eukaryote, blanks as nulls, and :data:`SOURCE_COLUMN` added.
    """
    if euk_phylum_rank not in EUK_PHYLUM_RANKS:
        raise ValueError(
            f"euk_phylum_rank must be one of {list(EUK_PHYLUM_RANKS)}, got {euk_phylum_rank!r}"
        )
    if "ASV_ID" in pr2.columns and "ID" not in pr2.columns:
        pr2 = pr2.rename({"ASV_ID": "ID"})
    missing = [c for c in ("ID", *PR2_RANKS) if c not in pr2.columns]
    if missing:
        raise ValueError(f"the PR2 taxonomy lacks {missing}: is it a PR2 run? ({pr2.columns})")
    absent_slots = [c for c in ("ID", "Kingdom") if c not in asv.columns]
    if absent_slots:
        raise ValueError(f"the SILVA ASV table lacks {absent_slots}")

    pr2 = pr2.select(
        pl.col("ID").cast(pl.Utf8),
        *[_blank_to_null(r).alias(f"_pr2_{r}") for r in PR2_RANKS],
        (
            pl.col("confidence").cast(pl.Float64, strict=False)
            if "confidence" in pr2.columns
            else pl.lit(None, pl.Float64)
        ).alias("_pr2_confidence"),
    ).unique(subset=["ID"], keep="first")
    present = [s for s in SLOTS if s in asv.columns]
    df = asv.with_columns(
        *[_blank_to_null(s) for s in present],
        *[pl.lit(None, pl.Utf8).alias(s) for s in SLOTS if s not in asv.columns],
    ).join(pr2, on="ID", how="left")

    is_euk = pl.col("_pr2_Domain").str.starts_with("Eukaryota").fill_null(False)
    is_prok = pl.col("Kingdom").is_in(PROKARYOTES).fill_null(False)
    df = df.with_columns(
        pl.when(is_euk)
        .then(pl.lit("pr2"))
        .when(is_prok)
        .then(pl.lit("silva"))
        .otherwise(pl.lit("fallback"))
        .alias(SOURCE_COLUMN)
    )

    start = PR2_RANKS.index(euk_phylum_rank)
    # Slot -> PR2 rank: Kingdom = Domain, Phylum = euk_phylum_rank, then the next
    # PR2 ranks in order; slots past the last PR2 rank stay empty.
    plain = ["Domain", *PR2_RANKS[start : start + len(SLOTS) - 1]]
    deep = ["Domain", *PR2_RANKS[start + 1 : start + len(SLOTS)]]
    plain += [None] * (len(SLOTS) - len(plain))
    deep += [None] * (len(SLOTS) - len(deep))
    deeper = PR2_RANKS[start + 1] if start + 1 < len(PR2_RANKS) else None
    deepen = (
        (pl.col(SOURCE_COLUMN) == "pr2")
        & pl.col(f"_pr2_{euk_phylum_rank}").is_in(DEEPEN)
        & (pl.col(f"_pr2_{deeper}").is_not_null() if deeper else pl.lit(False))
    )

    def from_pr2(rank: str | None) -> pl.Expr:
        return pl.col(f"_pr2_{rank}") if rank else pl.lit(None, pl.Utf8)

    out = df.with_columns(
        *[
            pl.when(deepen)
            .then(from_pr2(d))
            .when(pl.col(SOURCE_COLUMN) == "pr2")
            .then(from_pr2(p))
            .otherwise(pl.col(slot))
            .alias(slot)
            for slot, p, d in zip(SLOTS, plain, deep, strict=True)
        ],
        pl.when(pl.col(SOURCE_COLUMN) == "pr2")
        .then(pl.col("_pr2_confidence"))
        .otherwise(
            pl.col("confidence").cast(pl.Float64, strict=False)
            if "confidence" in df.columns
            else pl.lit(None, pl.Float64)
        )
        .alias("confidence"),
    )
    return out.drop([c for c in out.columns if c.startswith("_pr2_")])


def lineage(level: int) -> pl.Expr:
    """QIIME2's collapsed label: the first ``level`` slots, blanks kept (``Bacteria;;``)."""
    return pl.concat_str([pl.col(s).fill_null("") for s in SLOTS[:level]], separator=";")


def collapse(asv: pl.DataFrame, samples: list[str], level: int) -> pl.DataFrame:
    """A ``rel-table-<level>.tsv`` frame from an ASV table: ``#OTU ID`` + samples.

    Sums the ASVs sharing a lineage, as QIIME2's ``taxa collapse`` does: on a
    SILVA run's own ASV table it gives back QIIME2's rel-tables (the TREC
    ``--self-check`` verified it to 1e-9 on 127,845 ASVs).
    """
    if not 1 <= level <= len(SLOTS):
        raise ValueError(f"level must be 1..{len(SLOTS)}, got {level}")
    return (
        asv.select(
            lineage(level).alias("#OTU ID"),
            *[pl.col(s).cast(pl.Float64, strict=False).fill_null(0.0) for s in samples],
        )
        .group_by("#OTU ID")
        .agg(pl.col(samples).sum())
        .sort("#OTU ID")
    )
