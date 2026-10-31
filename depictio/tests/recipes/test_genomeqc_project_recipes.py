"""nf-core/genomeqc pipeline recipes: the karyotype, the gene overlaps, the Tiara counts and the hub.

genomeqc publishes its BUSCO ideogram as complete BUSCOs per sequence with no
sequence length, so the karyotype must take each length from tidk and leave a
sequence tidk does not know out; the gene overlap tables must transpose into
one row per assembly; and the hub must key on the assembly name the pipeline's
directories use (not the FASTA name QUAST prints), survive every optional
source being absent, and carry the design columns, or one constant group
without a design table.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _lengths(rows: list[tuple[str, str, int]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=["genome", "sequence", "sequence_length"], orient="row")


# ---------------------------------------------------------------------------
# Karyotype
# ---------------------------------------------------------------------------


def test_karyotype_draws_each_sequence_to_its_tidk_length(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "busco/protein/A/ideogram/A.csv",
        '"Chr","Complete_BUSCOs"\n"c1",30\n"c2",10\n"c9",5\n',
    )
    # A genome-only run writes the ideogram under busco/genome/ with the lineage in its name.
    _write(tmp_path, "busco/genome/B/ideogram/B_lin_odb10.csv", '"Chr","Complete_BUSCOs"\n"b1",8\n')
    lengths = _lengths(
        [
            ("A", "c1", 2_000_000),
            ("A", "c1", 1_000_000),
            ("A", "c2", 500_000),
            ("B", "b1", 4_000_000),
        ]
    )
    df = execute_recipe(
        "nf-core/genomeqc/busco_karyotype.py", tmp_path, extra_sources={"lengths": lengths}
    )
    rows = {(r["genome"], r["sequence"]): r for r in df.iter_rows(named=True)}
    assert ("A", "c9") not in rows  # no tidk length, no bar
    c1 = rows[("A", "c1")]
    assert (c1["start"], c1["end"], c1["sequence_length"]) == (0, 2_000_000, 2_000_000)
    assert c1["busco_mode"] == "proteins" and c1["sequence_rank"] == 1
    assert c1["buscos_per_mb"] == pytest.approx(15.0)
    assert c1["busco_share_pct"] == pytest.approx(75.0)
    assert rows[("B", "b1")]["busco_mode"] == "genome"


def test_karyotype_path_parts_read_genome_and_mode() -> None:
    module = load_recipe("nf-core/genomeqc/busco_karyotype.py")
    assert module.path_parts("busco/protein/A_b/ideogram/A_b.csv") == ("A_b", "proteins")
    assert module.path_parts("out/busco/genome/G/ideogram/G_x_odb10.csv") == ("G", "genome")


# ---------------------------------------------------------------------------
# Gene overlaps
# ---------------------------------------------------------------------------


def test_gene_overlaps_transpose_into_one_row_per_assembly(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "gene_overlaps/A.counts.tsv",
        "Statistic\tCount\nTotal number of genes\t200\nNumber of genes with unresolved strand\t0\n"
        "Number of genes fully contained in same strand direction\t10\n"
        "Number of genes fully contained in opposite strand direction\t20\n"
        "Total number of overlapping genes\t50\n",
    )
    row = execute_recipe("nf-core/genomeqc/gene_overlaps.py", tmp_path).row(0, named=True)
    assert row["genome"] == "A" and row["total_genes"] == 200
    assert row["overlapping_pct"] == pytest.approx(25.0)
    assert row["contained_same_strand_pct"] == pytest.approx(5.0)
    # The four parts the Annotation tab stacks add up to the genes.
    assert (row["not_overlapping_genes"], row["overlapping_not_nested"]) == (150, 20)
    parts = ("not_overlapping_genes", "overlapping_not_nested", "contained_opposite_strand")
    assert sum(row[c] for c in parts) + row["contained_same_strand"] == row["total_genes"]


def test_tiara_class_counts_count_sequences_per_assembly_and_class(tmp_path: Path) -> None:
    classes = pl.DataFrame(
        {
            "genome": ["A", "A", "A", "A", "B", None],
            "tiara_class": [
                "eukarya",
                "eukarya",
                "bacteria",
                "mitochondrion",
                "eukarya",
                "eukarya",
            ],
        }
    )
    df = execute_recipe(
        "nf-core/genomeqc/tiara_class_counts.py", tmp_path, extra_sources={"classes": classes}
    )
    rows = {(r["genome"], r["tiara_class"]): r for r in df.iter_rows(named=True)}
    assert len(rows) == 4  # the row without an assembly is left out
    assert rows[("A", "eukarya")]["sequences"] == 2
    assert rows[("A", "eukarya")]["share_pct"] == pytest.approx(50.0)
    assert rows[("B", "eukarya")]["share_pct"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Genome hub
# ---------------------------------------------------------------------------


@pytest.fixture
def hub_sources() -> dict[str, pl.DataFrame]:
    quast_raw = pl.DataFrame(
        {
            "Assembly": ["GCF_1_genomic", "GCF_2_genomic"],
            "N90": ["100", "50"],
            "L90": ["14", "300"],
            "source_path": [
                "quast/A/A.quast/transposed_report.tsv",
                "quast/B/B.quast/transposed_report.tsv",
            ],
        }
    )
    quast = pl.DataFrame(
        {
            "assembly_id": ["GCF_1_genomic", "GCF_2_genomic"],
            "n_contigs": [177, 3000],
            "total_length": [225_000_000, 210_000_000],
            "n50": [13_000_000, 500_000],
            "l50": [7, 100],
            "gc_percent": [32.5, 32.1],
        }
    )
    busco = pl.DataFrame(
        {
            "assembly_id": ["A", "A", "B"],
            "lineage": ["x_odb10"] * 3,
            "busco_mode": ["genome", "proteins", "genome"],
            "complete_pct": [99.3, 98.8, 97.6],
            "single_pct": [99.2, 98.6, 97.3],
            "duplicated_pct": [0.1, 0.2, 0.4],
            "fragmented_pct": [0.1, 0.3, 0.4],
            "missing_pct": [0.6, 0.9, 2.0],
        }
    )
    tiara = pl.DataFrame(
        {
            "genome": ["A"] * 4,
            "stage": ["raw", "raw", "raw", "cleaned"],
            "tiara_class": ["eukarya", "bacteria", "unknown", "bacteria"],
            "is_eukaryotic": [True, False, False, False],
        }
    )
    gx = pl.DataFrame(
        {"genome": ["A", "B"], "action": ["none", "EXCLUDE"], "flagged_bp": [0, 2136]}
    )
    return {
        "quast_raw": quast_raw,
        "quast": quast,
        "busco": busco,
        "tiara": tiara,
        "gx": gx,
        "synteny": pl.DataFrame({"Species": ["A", "B"], "Syntenic_Chromosomes": [33, 589]}),
        "metadata": pl.DataFrame({"sample": ["A", "B"], "family": ["F1", "F2"]}),
    }


def test_hub_keys_on_the_assembly_directory_and_joins_every_source(
    tmp_path: Path, hub_sources: dict
) -> None:
    df = execute_recipe("nf-core/genomeqc/genomes.py", tmp_path, extra_sources=hub_sources)
    assert df.columns[:3] == ["genome", "family", "assembly_label"]
    a = df.row(0, named=True)
    assert a["genome"] == "A" and a["assembly_label"] == "GCF_1_genomic"
    assert a["n50"] == 13_000_000 and a["n90"] == 100 and a["l90"] == 14
    assert a["busco_complete_pct"] == pytest.approx(99.3)
    assert a["protein_complete_pct"] == pytest.approx(98.8)
    # Tiara's raw stage only: one bacterial and one unknown of three.
    assert (a["tiara_sequences"], a["prokaryotic_sequences"], a["unknown_sequences"]) == (3, 1, 1)
    assert (a["gx_flagged_ranges"], a["gx_flagged_bp"]) == (0, 0)
    b = df.row(1, named=True)
    assert b["protein_complete_pct"] is None
    assert (b["gx_flagged_ranges"], b["gx_flagged_bp"], b["syntenic_sequences"]) == (1, 2136, 589)


def test_hub_without_design_or_optional_sources_keeps_one_group(
    tmp_path: Path, hub_sources: dict
) -> None:
    sources = {"quast_raw": hub_sources["quast_raw"], "quast": hub_sources["quast"]}
    df = execute_recipe("nf-core/genomeqc/genomes.py", tmp_path, extra_sources=sources)
    assert df["genome"].to_list() == ["A", "B"]
    assert df["__no_group__"].unique().to_list() == ["All genomes"]
    assert df["busco_complete_pct"].null_count() == 2
    assert df["genes"].null_count() == 2


def test_hub_falls_back_to_the_quast_label_under_a_run_level_directory() -> None:
    module = load_recipe("nf-core/genomeqc/genomes.py")
    assert module.genome_from_quast_path("quast/A/A.quast/transposed_report.tsv", "x") == "A"
    assert module.genome_from_quast_path("run/QUAST/transposed_report.tsv", "asm_1") == "asm_1"
