"""nf-core/genomeqc catalog recipes on small synthetic outputs.

The template reads BUSCO's batch summaries in two modes, tidk's search windows,
AGAT's sp_statistics report, RepeatMasker's ``.tbl``, three OrthoFinder summary
tables, the FCS-GX and FCS-adaptor reports and Tiara's classes. These tests pin
what the dashboard reads off them: the BUSCO mode a run name carries, the
window starts and sequence lengths tidk gives, the two isoform views of AGAT,
the RepeatMasker class ranks (classes partition, families and summaries do
not), the orthogroup membership matrix, the "none" row of a clean screen and
Tiara's merged class. The pipeline recipes (karyotype, gene overlaps, genome
hub) are in ``test_genomeqc_project_recipes.py``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe

BUSCO_HEADER = (
    "Input_file\tDataset\tComplete\tSingle\tDuplicated\tFragmented\tMissing\tn_markers"
    "\tInternal stop codon percent\tScaffold N50\tContigs N50\tPercent gaps\tNumber of scaffolds\n"
)

AGAT = """--------------------------------------------------------------------------------

------------------------------------ region ------------------------------------
Number of region                                            63
Longest region (bp)                                         27754200

------------------------------------- mrna -------------------------------------
Number of gene                                              100
Number of mrna                                              240
Number of exon                                              2000
Number gene overlapping                                     5
Number of single exon gene                                  4
mean mrnas per gene                                         2.4
mean exons per mrna                                         10.4
mean gene length (bp)                                       16890
median gene length (bp)                                     3989
mean mrna length (bp)                                       29744
mean exon length (bp)                                       357
mean intron in exon length (bp)                             2783
mean cds length (bp)                                        2445
Total gene length (bp)                                      1678000
90 percentile cds length (bp)                               na

mrna have isoforms! Here are the statistics without isoforms shortest isoforms excluded):

Number of gene                                              100
Number of mrna                                              100
mean exons per mrna                                         7.5
mean mrna length (bp)                                       15035
mean cds length (bp)                                        1823

------------------------------------- trna -------------------------------------
Number of gene                                              20
Number of trna                                              20
Number of exon                                              20
Number gene overlapping                                     0
mean trnas per gene                                         1.0
mean exons per trna                                         1.0
mean gene length (bp)                                       75
"""

TBL = """==================================================
file name: genome.fna
sequences:           177
total length:  225250884 bp  (223937270 bp excl N/X-runs)
GC level:         32.53 %
bases masked:   38935182 bp ( 17.29 %)
==================================================
               number of      length   percentage
               elements*    occupied  of sequence
--------------------------------------------------
Retroelements        18689      2803554 bp    1.24 %
   SINEs:              335        41217 bp    0.02 %
   LINEs:             7575       825602 bp    0.37 %
    CRE/SLACS            4         2032 bp    0.00 %
     L2/CR1/Rex       2394       171922 bp    0.08 %
   LTR elements:     10779      1936735 bp    0.86 %
     Gypsy/DIRS1      6459       769629 bp    0.34 %
       Retroviral      311        29253 bp    0.01 %

DNA transposons      47012      7984878 bp    3.54 %
   Tc1-IS630-Pogo    23213      4713298 bp    2.09 %
   Other (Mirage,      344        25903 bp    0.01 %
    P-element, Transib)

Unclassified:        99209     16873128 bp    7.49 %

Total interspersed repeats:    27682653 bp   12.29 %

Simple repeats:     188378      8525555 bp    3.78 %
==================================================

* most repeats fragmented by insertions or deletions
"""


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    _write(tmp_path, "agat/A/stats/A.stats.txt", AGAT)
    _write(tmp_path, "repeatmasker/A/A.tbl", TBL)
    for genome, size in (("A", 3), ("B", 2)):
        rows = ["id\twindow\tforward_repeat_number\treverse_repeat_number\ttelomeric_repeat"]
        for chrom, n in (("c1", size), ("c2", 1)):
            for i in range(1, n + 1):
                end = i * 10000 if i < n else (i - 1) * 10000 + 4321
                rows.append(f"{chrom}\t{end}\t{i}\t0\tTTAGG")
        _write(tmp_path, f"tidk/{genome}/search/aposteriori/{genome}.tsv", "\n".join(rows) + "\n")
    stats = "Orthofinder/Results_x/Comparative_Genomics_Statistics"
    _write(
        tmp_path,
        f"{stats}/Statistics_PerSpecies.tsv",
        "\tA\tB\nNumber of genes\t100\t200\nNumber of genes in orthogroups\t90\t150\n"
        "Number of unassigned genes\t10\t50\nPercentage of genes in orthogroups\t90.0\t75.0\n"
        "Number of species-specific orthogroups\t3\t7\n\n"
        "Number of genes per-species in orthogroup\tNumber of orthogroups\tNumber of orthogroups\n"
        "'0\t5\t6\n",
    )
    _write(
        tmp_path, f"{stats}/OrthologuesStats_one-to-one.tsv", "\tA\tB\nA\t0.0\t80.0\nB\t80.0\t0.0\n"
    )
    _write(
        tmp_path,
        "Orthofinder/Results_x/Orthogroups/Orthogroups.GeneCount.tsv",
        "Orthogroup\tA\tB\tTotal\nOG1\t1\t1\t2\nOG2\t2\t0\t2\nOG3\t0\t1\t1\nOG4\t3\t1\t4\n",
    )
    header = '##[["FCS genome report", 2, 1], {"run-info": {}}]\n'
    header += "#seq_id\tstart_pos\tend_pos\tseq_len\taction\tdiv\tagg_cont_cov\ttop_tax_name\n"
    _write(tmp_path, "decontamination/fcs-gx/A.fcs_gx_report.txt", header)
    _write(
        tmp_path,
        "decontamination/fcs-gx/B.fcs_gx_report.txt",
        header + "s9\t1\t2136\t2136\tEXCLUDE\tprok:CFB group bacteria\t89\tSome bacterium\n",
    )
    adaptor = "#accession\tlength\taction\trange\tname\n"
    _write(tmp_path, "decontamination/fcs-adaptor/A.fcs_adaptor_report.txt", adaptor)
    _write(
        tmp_path,
        "decontamination/fcs-adaptor/B.fcs_adaptor_report.txt",
        adaptor + "s1\t5000\tACTION_TRIM\t1..25,4990..5000\t"
        "CONTAMINATION_SOURCE_TYPE_ADAPTOR:NGB00972.1:Blunt Adapter\n",
    )
    tiara = "sequence_id\tclass_fst_stage\tclass_snd_stage\n"
    tiara += "c1 chromosome one\teukarya\tn/a\nc2 contig\tbacteria\tn/a\n"
    tiara += "m1 mito\torganelle\tmitochondrion\nu1\tunknown\tn/a\n"
    _write(tmp_path, "decontamination/tiara/raw/A.txt", tiara)
    _write(
        tmp_path,
        "decontamination/tiara/raw/log_A.txt",
        "First iteration statistics:\n\teukarya: 1\n",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# BUSCO: the mode a run name carries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "label", "mode"),
    [
        ("busco/genome/A/stats/A-hymen_odb10-genome-busco.batch_summary.txt", "A", "genome"),
        (
            "busco/protein/A_b/stats/A_b-hymen_odb10-proteins-busco.batch_summary.txt",
            "A_b",
            "proteins",
        ),
        ("s1/QC/BUSCO/s1_assembly-lineage_odb10-busco.batch_summary.txt", "s1_assembly", None),
        ("run/s1_ragtag-euk-busco/batch_summary.txt", "s1_ragtag", None),
    ],
)
def test_busco_run_name_gives_the_assembly_and_the_mode(
    path: str, label: str, mode: str | None
) -> None:
    module = load_recipe("busco/batch_summary.py")
    assert module.run_label(path) == label
    assert module.run_mode(path) == mode


def test_busco_keeps_the_genome_and_protein_runs_of_one_assembly(tmp_path: Path) -> None:
    raw = pl.DataFrame(
        {
            "Input_file": ["GCF_1_genomic.fna", "A.fasta"],
            "Dataset": ["lin_odb10", "lin_odb10"],
            "Complete": ["99.3", "98.8"],
            "Single": ["99.2", "98.6"],
            "Duplicated": ["0.1", "0.2"],
            "Fragmented": ["0.1", "0.3"],
            "Missing": ["0.6", "0.9"],
            "n_markers": ["5991", "5991"],
            "source_path": [
                "busco/genome/A/stats/A-lin_odb10-genome-busco.batch_summary.txt",
                "busco/protein/A/stats/A-lin_odb10-proteins-busco.batch_summary.txt",
            ],
        }
    )
    df = execute_recipe("busco/batch_summary.py", tmp_path, extra_sources={"summaries": raw})
    assert df.select("assembly_id", "busco_mode", "complete_pct").rows() == [
        ("A", "genome", 99.3),
        ("A", "proteins", 98.8),
    ]
    comp = execute_recipe("busco/composition.py", tmp_path, extra_sources={"summary": df})
    assert comp["run_id"].unique().sort().to_list() == ["A (genome)", "A (proteins)"]
    assert comp.group_by("run_id").agg(pl.col("percent").sum())["percent"].to_list() == [
        pytest.approx(100.0),
        pytest.approx(100.0),
    ]


def test_busco_composition_of_a_summary_without_mode_keeps_the_assembly_label(
    tmp_path: Path,
) -> None:
    summary = pl.DataFrame(
        {
            "assembly_id": ["s1"],
            "lineage": ["x_odb12"],
            "single_pct": [90.0],
            "duplicated_pct": [5.0],
            "fragmented_pct": [3.0],
            "missing_pct": [2.0],
        }
    )
    comp = execute_recipe("busco/composition.py", tmp_path, extra_sources={"summary": summary})
    assert comp["run_id"].unique().to_list() == ["s1"]
    assert comp["busco_mode"].null_count() == comp.height


# ---------------------------------------------------------------------------
# tidk
# ---------------------------------------------------------------------------


def test_tidk_windows_start_where_the_last_ended_and_carry_the_length(run_dir: Path) -> None:
    df = execute_recipe("tidk/search_windows.py", run_dir)
    a1 = df.filter((pl.col("genome") == "A") & (pl.col("sequence") == "c1")).sort("start")
    assert a1.select("start", "end").rows() == [(0, 10000), (10000, 20000), (20000, 24321)]
    assert a1["sequence_length"].unique().to_list() == [24321]
    assert a1["repeats"].to_list() == [1, 2, 3]
    assert df["search"].unique().to_list() == ["aposteriori"]
    assert df["repeat_unit"].unique().to_list() == ["TTAGG"]


def test_tidk_keeps_the_apriori_search_when_both_ran(run_dir: Path) -> None:
    src = run_dir / "tidk/A/search/aposteriori/A.tsv"
    apriori = run_dir / "tidk/A/search/apriori/TTAGG/A.tsv"
    apriori.parent.mkdir(parents=True)
    apriori.write_text(src.read_text())
    df = execute_recipe("tidk/search_windows.py", run_dir)
    assert df.filter(pl.col("genome") == "A")["search"].unique().to_list() == ["apriori"]
    assert df.filter(pl.col("genome") == "B")["search"].unique().to_list() == ["aposteriori"]


# ---------------------------------------------------------------------------
# AGAT
# ---------------------------------------------------------------------------


def test_agat_statistics_tag_the_longest_isoform_block(run_dir: Path) -> None:
    df = execute_recipe("agat/statistics.py", run_dir)
    mrna = df.filter(pl.col("feature_type") == "mrna")
    assert set(mrna["isoforms"]) == {"all", "longest"}
    exons = mrna.filter(pl.col("metric") == "mean exons per mrna")
    assert dict(exons.select("isoforms", "value").rows()) == {"all": 10.4, "longest": 7.5}
    assert mrna.filter(pl.col("metric") == "90 percentile cds length (bp)")["value"].to_list() == [
        None
    ]
    assert df["genome"].unique().to_list() == ["A"]


def test_agat_gene_models_read_counts_whole_and_shape_on_the_longest_isoform(run_dir: Path) -> None:
    df = execute_recipe("agat/gene_models.py", run_dir)
    assert set(df["feature_type"]) == {"mrna", "trna"}  # region has no genes
    mrna = df.filter(pl.col("feature_type") == "mrna").row(0, named=True)
    assert mrna["genes"] == 100 and mrna["transcripts"] == 240
    assert mrna["exons_per_transcript"] == pytest.approx(7.5)
    assert mrna["mean_cds_length"] == pytest.approx(1823)
    assert mrna["single_exon_gene_pct"] == pytest.approx(4.0)
    trna = df.filter(pl.col("feature_type") == "trna").row(0, named=True)
    # No single-exon line printed: none, not unknown; and no longest block to read.
    assert trna["single_exon_genes"] == 0
    assert trna["exons_per_transcript"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# RepeatMasker
# ---------------------------------------------------------------------------


def test_repeatmasker_ranks_classes_families_and_summaries(run_dir: Path) -> None:
    df = execute_recipe("repeatmasker/repeat_classes.py", run_dir)
    rank = dict(df.select("repeat_class", "rank").rows())
    assert rank["Retroelements"] == "Summary"
    assert rank["Total interspersed repeats"] == "Summary"
    for name in (
        "SINEs",
        "LINEs",
        "LTR elements",
        "DNA transposons",
        "Unclassified",
        "Simple repeats",
    ):
        assert rank[name] == "Class"
    for name in ("CRE/SLACS", "L2/CR1/Rex", "Tc1-IS630-Pogo", "Retroviral"):
        assert rank[name] == "Family"
    parent = dict(df.select("repeat_class", "parent_class").rows())
    # The drifting indent (CRE/SLACS at 4, its siblings at 5) keeps both under LINEs.
    assert parent["CRE/SLACS"] == "LINEs" and parent["L2/CR1/Rex"] == "LINEs"
    assert parent["Retroviral"] == "Gypsy/DIRS1"
    assert "Other (Mirage, P-element, Transib)" in rank
    total = df.filter(pl.col("repeat_class") == "Total interspersed repeats").row(0, named=True)
    assert total["elements"] is None and total["genome_pct"] == pytest.approx(12.29)


def test_repeatmasker_summary_reads_the_header_and_the_main_shares(run_dir: Path) -> None:
    row = execute_recipe("repeatmasker/masking_summary.py", run_dir).row(0, named=True)
    assert row["genome"] == "A" and row["sequences"] == 177
    assert row["total_length"] == 225250884 and row["length_excl_n"] == 223937270
    assert row["masked_pct"] == pytest.approx(17.29) and row["gc_pct"] == pytest.approx(32.53)
    assert row["interspersed_pct"] == pytest.approx(12.29)
    assert row["dna_transposons_pct"] == pytest.approx(3.54)


# ---------------------------------------------------------------------------
# OrthoFinder
# ---------------------------------------------------------------------------


def test_orthofinder_species_stats_transpose_the_first_table(run_dir: Path) -> None:
    df = execute_recipe("orthofinder/species_stats.py", run_dir)
    assert df["genome"].to_list() == ["A", "B"]
    b = df.row(1, named=True)
    assert b["genes"] == 200 and b["unassigned_genes"] == 50
    assert b["genes_in_orthogroups_pct"] == pytest.approx(75.0)
    assert b["species_specific_orthogroups"] == 7
    assert b["orthogroups"] is None  # not in the file


def test_orthofinder_orthogroup_matrix_is_binary_per_species(run_dir: Path) -> None:
    df = execute_recipe("orthofinder/orthogroup_matrix.py", run_dir)
    rows = {r["orthogroup"]: r for r in df.iter_rows(named=True)}
    assert (rows["OG1"]["A"], rows["OG1"]["B"]) == (1, 1)
    assert (rows["OG2"]["A"], rows["OG2"]["B"]) == (1, 0)
    assert rows["OG1"]["copy_class"] == "single-copy" and rows["OG1"]["sharing"] == "core"
    assert rows["OG4"]["copy_class"] == "multi-copy" and rows["OG4"]["total_genes"] == 4
    assert rows["OG3"]["n_genomes"] == 1 and rows["OG3"]["sharing"] == "unique"
    assert "Total" not in df.columns


def test_orthofinder_orthologue_matrix_nulls_the_diagonal(run_dir: Path) -> None:
    df = execute_recipe("orthofinder/orthologue_matrix.py", run_dir)
    assert df.columns == ["genome", "A", "B"]
    assert df.rows() == [("A", None, 80), ("B", 80, None)]


# ---------------------------------------------------------------------------
# FCS-GX, FCS-adaptor, Tiara
# ---------------------------------------------------------------------------


def test_fcsgx_keeps_a_none_row_for_a_clean_assembly(run_dir: Path) -> None:
    df = execute_recipe("fcsgx/actions.py", run_dir)
    clean = df.filter(pl.col("genome") == "A").row(0, named=True)
    assert clean["action"] == "none" and clean["flagged_bp"] == 0 and clean["seq_id"] is None
    hit = df.filter(pl.col("genome") == "B").row(0, named=True)
    assert hit["action"] == "EXCLUDE" and hit["flagged_bp"] == 2136
    assert hit["division_group"] == "prok" and hit["contaminant_cov"] == pytest.approx(89.0)


def test_fcsadaptor_splits_ranges_and_names_the_adaptor(run_dir: Path) -> None:
    df = execute_recipe("fcsadaptor/actions.py", run_dir)
    b = df.filter(pl.col("genome") == "B").sort("start")
    assert b.select("start", "end", "flagged_bp").rows() == [(1, 25, 25), (4990, 5000, 11)]
    assert b["action"].unique().to_list() == ["TRIM"]
    assert b["adaptor"].unique().to_list() == ["Blunt Adapter"]
    assert b["source_type"].unique().to_list() == ["ADAPTOR"]
    assert df.filter(pl.col("genome") == "A")["action"].to_list() == ["none"]


def test_tiara_merges_the_organelle_call_and_skips_the_log(run_dir: Path) -> None:
    df = execute_recipe("tiara/classifications.py", run_dir)
    assert df["sequence"].to_list() == ["c1", "c2", "m1", "u1"]
    classes = dict(df.select("sequence", "tiara_class").rows())
    assert classes == {"c1": "eukarya", "c2": "bacteria", "m1": "mitochondrion", "u1": "unknown"}
    assert dict(df.select("sequence", "is_eukaryotic").rows()) == {
        "c1": True,
        "c2": False,
        "m1": True,
        "u1": False,
    }
    assert df["stage"].unique().to_list() == ["raw"]
