"""Rank parsing must survive a reference database that adds a rank.

nf-core/ampliseq 2.18.0 switched its default DADA2 database to ``sbdi-gtdb``,
whose taxlevels start ``Domain,Kingdom,Phylum,…`` — one rank deeper than the
7-rank databases (rdp, silva) earlier releases defaulted to. QIIME2's collapsed
outputs are addressed by *depth*, so the same "level 2" file holds
``Bacteria;Proteobacteria`` under one database and ``Bacteria;Bacteria`` under
the other.

The template pins which level is the Phylum for the release it ships (a
``source_overrides`` entry); these tests pin the other half of the contract —
that the recipes read the rank off the *tail* of whatever lineage they get, so
both dialects land on the same Kingdom/Phylum columns and nothing silently
labels a Domain as a Kingdom.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import load_recipe, resolve_sources
from depictio.recipes.lib.lineage import (
    UNCLASSIFIED,
    asv_table_to_ranks,
    kingdom_phylum,
    parent_rank,
)

# (lineage, expected Kingdom, expected Phylum)
_LINEAGES = [
    # 7-rank dialect: level-2 lineage is Kingdom;Phylum.
    ("Bacteria;Proteobacteria", "Bacteria", "Proteobacteria"),
    ("Archaea;Crenarchaeota", "Archaea", "Crenarchaeota"),
    # 8-rank dialect (sbdi-gtdb): level-3 lineage is Domain;Kingdom;Phylum.
    ("Bacteria;Bacteria;Pseudomonadota", "Bacteria", "Pseudomonadota"),
    ("Archaea;Archaea;Nanoarchaeota", "Archaea", "Nanoarchaeota"),
    # Unknown leaf: QIIME2 writes a trailing empty segment.
    ("Bacteria;", "Bacteria", UNCLASSIFIED),
    ("Bacteria;Bacteria;", "Bacteria", UNCLASSIFIED),
    # Wholly unclassified rows exist in both dialects.
    (";", UNCLASSIFIED, UNCLASSIFIED),
    # A blank intermediate rank falls back to the deepest named ancestor.
    ("Bacteria;;Pseudomonadota", "Bacteria", "Pseudomonadota"),
    # Single-segment lineage: it is its own root, and has no Phylum.
    ("Bacteria", "Bacteria", UNCLASSIFIED),
]


def test_kingdom_phylum_reads_both_rank_dialects() -> None:
    df = pl.DataFrame({"taxonomy": [lineage for lineage, _, _ in _LINEAGES]})
    got = df.with_columns(kingdom_phylum(pl.col("taxonomy")))
    assert got["Kingdom"].to_list() == [k for _, k, _ in _LINEAGES]
    assert got["Phylum"].to_list() == [p for _, _, p in _LINEAGES]


def test_parent_rank_never_returns_the_domain_of_an_8_rank_lineage() -> None:
    """The Domain and Kingdom segments are equal in sbdi-gtdb, but a deeper
    lineage must still resolve its Kingdom to the segment above the leaf."""
    df = pl.DataFrame({"lineage": ["Bacteria;Bacteria;Pseudomonadota;Alphaproteobacteria"]})
    assert df.with_columns(parent_rank(pl.col("lineage")).alias("k"))["k"].to_list() == [
        "Pseudomonadota"
    ]


def _run(recipe: str, data_dir: Path, extra: dict[str, pl.DataFrame] | None = None) -> pl.DataFrame:
    module = load_recipe(recipe)
    sources = resolve_sources(module, data_dir)
    for source in module.SOURCES:
        if source.dc_ref is not None:
            sources[source.ref] = (extra or {}).get(source.dc_ref)  # type: ignore[assignment]
    return module.transform(sources)


def _write_rel_table(path: Path, lineages: list[str]) -> None:
    """A QIIME2 collapsed rel-table: banner line, then taxa × samples."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"{lineage}\t0.6\t0.4" for lineage in lineages)
    path.write_text(f"# Constructed from biom file\n#OTU ID\tS1\tS2\n{rows}\n")


@pytest.mark.parametrize(
    "lineages,expected_phyla",
    [
        (["Bacteria;Proteobacteria", "Archaea;Crenarchaeota"], {"Proteobacteria", "Crenarchaeota"}),
        (
            ["Bacteria;Bacteria;Pseudomonadota", "Archaea;Archaea;Nanoarchaeota"],
            {"Pseudomonadota", "Nanoarchaeota"},
        ),
    ],
    ids=["7-rank", "8-rank"],
)
def test_taxonomy_rel_abundance_labels_the_phylum_in_both_dialects(
    tmp_path: Path, lineages: list[str], expected_phyla: set[str]
) -> None:
    _write_rel_table(tmp_path / "qiime2/rel_abundance_tables/rel-table-2.tsv", lineages)
    out = _run("nf-core/ampliseq/taxonomy_rel_abundance.py", tmp_path)
    assert set(out["Phylum"].to_list()) == expected_phyla
    assert set(out["Kingdom"].to_list()) == {"Bacteria", "Archaea"}


def test_stacked_taxonomy_drops_a_level_the_pipeline_does_not_emit(tmp_path: Path) -> None:
    """Under an 8-rank database the template points the refs one level deeper,
    so the Genus source lands on a rel-table-7 that ampliseq never writes. The
    recipe must degrade to the ranks it does have rather than fail."""
    tables = tmp_path / "qiime2/rel_abundance_tables"
    for level, depth in ((2, 2), (3, 3), (4, 4), (5, 5)):
        _write_rel_table(
            tables / f"rel-table-{level}.tsv",
            [";".join(["Bacteria", "Bacteria", "Pseudomonadota", "Alphaproteobacteria"][:depth])],
        )
    # phylum..family are rel-table-2..5 here; the genus source (rel-table-6) is absent.
    module = load_recipe("qiime2/stacked_taxonomy_canonical.py")
    sources = resolve_sources(module, tmp_path)
    sources["metadata"] = None  # type: ignore[assignment]
    out = module.transform(sources)
    assert sources["genus"] is None, "the missing deepest level must resolve to None, not raise"
    assert "Genus" not in out["rank"].unique().to_list()
    assert {"Kingdom", "Phylum"} <= set(out["rank"].unique().to_list())
    # Kingdom is derived from the segment above the Phylum leaf, not segment 0.
    assert out.filter(pl.col("rank") == "Kingdom")["taxon"].unique().to_list() == ["Bacteria"]


def test_asv_table_to_ranks_sums_per_taxon_tuple() -> None:
    """The hierarchical DCs read named rank columns, so they need no lineage
    parsing at all — and two ASVs of the same genus collapse into one row."""
    asv = pl.DataFrame(
        {
            "ID": ["asv1", "asv2", "asv3"],
            "Domain": ["Bacteria", "Bacteria", "Bacteria"],
            "Kingdom": ["Bacteria", "Bacteria", "Bacteria"],
            "Phylum": ["Pseudomonadota", "Pseudomonadota", "Bacteroidota"],
            "Class": ["Alphaproteobacteria", "Alphaproteobacteria", "Bacteroidia"],
            "Order": ["Rhizobiales", "Rhizobiales", "Flavobacteriales"],
            "Family": ["Beijerinckiaceae", "Beijerinckiaceae", "Weeksellaceae"],
            "Genus": ["Microvirga", "Microvirga", ""],
            "confidence": ["0.98", "0.91", "0.80"],
            "sequence": ["ACGT", "ACGT", "TGCA"],
            "S1": ["0.5", "0.2", "0.3"],
            "S2": ["0.1", "0.1", "0.8"],
        }
    )
    out = asv_table_to_ranks(asv)
    # Domain is not a canonical rank: it duplicates Kingdom where it exists.
    assert "Domain" not in out.columns
    s1 = out.filter(pl.col("sample_id") == "S1")
    assert s1.height == 2, "the two Microvirga ASVs must collapse into one row"
    assert s1.filter(pl.col("Genus") == "Microvirga")["abundance"].item() == pytest.approx(0.7)
    # A blank rank cell reads as Unclassified rather than an empty string.
    assert s1.filter(pl.col("Phylum") == "Bacteroidota")["Genus"].item() == UNCLASSIFIED
    # Relative abundances still sum to 1 per sample.
    totals = out.group_by("sample_id").agg(pl.col("abundance").sum())["abundance"].to_list()
    assert all(t == pytest.approx(1.0) for t in totals)
