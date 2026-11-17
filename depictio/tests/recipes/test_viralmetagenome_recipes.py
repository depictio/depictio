"""Catalog recipes for nf-core/viralmetagenome outputs, on a tiny run laid out as the pipeline writes it.

Covers the pipeline's own tables (``viralmetagenome/*``: the four overview
tables, the contig classification, the clusters and the contigs) and the tool
recipes added with it (``checkv/quality_summary``, ``ivar/variants_tsv``,
``mosdepth/per_base_bins``, ``mosdepth/cumulative_coverage``), plus the name
parsing they share (``depictio.recipes.lib.viralmetagenome``). Every file name
carries the run's ``--global_prefix``, as on the megatest.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe
from depictio.recipes.lib.viralmetagenome import (
    split_mapping_name,
    strip_global_prefix,
    tidy_genome_overview,
)

PREFIX = "test_20260101_1.2.0_happy_turing-"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _tsv(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(r) for r in rows) + "\n"


# ---------------------------------------------------------------------------
# Name parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "sample", "expected"),
    [
        (f"{PREFIX}S1_REF1-CONSTRAINT_constraint", "S1", ("REF1", "constraint", None)),
        ("S1_REF1-CONSTRAINT", "S1", ("REF1", "constraint", None)),
        (
            "S1_REF1-CONSTRAINT_itvariant-calling.consensus_ivar",
            "S1",
            ("REF1", "constraint", "itvariant-calling"),
        ),
        (f"{PREFIX}S1_cl0_it1", "S1", ("cl0", "de novo", "it1")),
        ("S1_cl0_it1.consensus_bcftools", "S1", ("cl0", "de novo", "it1")),
        ("S1_cl2_consensus", "S1", ("cl2", "de novo", "consensus")),
        ("S1_REF1_constraint", "S1", ("REF1", "constraint", None)),
        ("S1", "S1", (None, None, None)),
    ],
)
def test_split_mapping_name(name: str, sample: str, expected: tuple) -> None:
    assert split_mapping_name(name, sample) == expected


def test_strip_global_prefix_keeps_a_plain_name() -> None:
    assert strip_global_prefix(f"{PREFIX}S-1_megahit") == "S-1_megahit"
    assert strip_global_prefix("S-1_megahit") == "S-1_megahit"


# ---------------------------------------------------------------------------
# Overview tables
# ---------------------------------------------------------------------------

SAMPLES_HEADER = [
    "sample",
    "FastQC (Raw). Seqs (R1,R2)",
    "FastQC (Raw). Dups",
    "fastp. Reads After Filtering (R1+R2)",
    "fastp. % > Q30",
    "fastp. % Duplication",
    "FastQC (Post-trimming). Seqs (R1,R2)",
    "Kraken2 (Host-removal). Unclassified",
    "FastQC (post-Host-removal). Seqs (R1,R2)",
    "Quast (Megahit). Assembly Length (Mbp)",
    "Quast (SPAdes). Assembly Length (Mbp)",
    "Quast (Megahit). N50 (Kbp)",
    "Cluster Summary. # Clusters",
    "Cluster Summary. # Removed clusters",
    "Consensus Count. # Final denovo clusters",
    "Sample metadata. sample_alias",
]


def _overview_row(**over: str) -> dict[str, str]:
    base = {
        "index": "S1_cl0_it1",
        "sample": "S1",
        "cluster": "cl0",
        "step": "it1",
        "(annotation) name": "Some virus",
        "(annotation) acronym": "SV",
        "(annotation) pident": "0.981",
        "(blast) qlen": "1000",
        "(blast) length": "900",
        "(blast) pident": "99.5",
        "(checkv) contig_length": "1000.0",
        "(checkv) checkv_quality": "Not-determined",
        "(quast) % N's": "1.5",
        "(picard) % duplication": "0.0125",
        "(general_stats) mosdepth Mean read depth": "80.5",
        "(general_stats) mosdepth 10X coverage": "96.0",
        "(bcftools) number of SNPs": "12.0",
        "(bcftools) transistions/transversions ratio": "1.8",
    }
    base.update(over)
    return base


def _overview_tsv(rows: list[dict[str, str]]) -> str:
    cols = list(rows[0])
    return _tsv([cols] + [[r.get(c, "") for c in cols] for r in rows])


@pytest.fixture()
def run(tmp_path: Path) -> Path:
    ov = tmp_path / "overview-tables"
    _write(
        ov / f"{PREFIX}samples_overview.tsv",
        _tsv(
            [
                [f'"{h}"' for h in SAMPLES_HEADER],
                [
                    "S1",
                    "1000.0",
                    "30.5",
                    "1980.0",
                    "0.995",
                    "0.5",
                    "990",
                    "99.0",
                    "980",
                    "29000.0",
                    "31000",
                    "29000.0",
                    "1",
                    "0",
                    "1.0",
                    "alias_a",
                ],
                [
                    "S2",
                    "200.0",
                    "2.0",
                    "380.0",
                    "0.99",
                    "0.2",
                    "190",
                    "90.0",
                    "171",
                    "2000.0",
                    "",
                    "900.0",
                    "1",
                    "5",
                    "",
                    "alias_b",
                ],
            ]
        ),
    )
    _write(ov / f"{PREFIX}contigs_overview.tsv", _overview_tsv([_overview_row()]))
    _write(
        ov / f"{PREFIX}contigs_overview-with-iterations.tsv",
        _overview_tsv(
            [
                _overview_row(
                    index="S1_cl0_consensus", step="consensus", **{"(quast) % N's": "0.3"}
                ),
                _overview_row(),
                _overview_row(
                    index="S1_cl0_itvariant-calling",
                    step="itvariant-calling",
                    **{"(quast) % N's": "2.0"},
                ),
            ]
        ),
    )
    _write(
        ov / f"{PREFIX}mapping_overview.tsv",
        _overview_tsv(
            [
                _overview_row(
                    index="S1_REF1_constraint",
                    cluster="REF1",
                    step="constraint",
                    **{"(annotation) acronym": "NA", "(annotation) name": ""},
                )
            ]
        ),
    )

    # Contigs: idxstats, the merged classification, the clusters.
    _write(
        tmp_path / f"assembly/assemblers/megahit/idxstats/{PREFIX}S1_megahit.idxstats",
        _tsv(
            [
                ["megahit_scaffold1|size1200", "1200", "90", "0"],
                ["megahit_scaffold2|size400", "400", "10", "0"],
                ["megahit_scaffold3|size300", "300", "0", "0"],
                ["*", "0", "0", "5"],
            ]
        ),
    )
    _write(
        tmp_path
        / f"assembly/polishing/intermediate/precluster/merged_classifications/{PREFIX}S1.resolved.txt",
        _tsv(
            [
                ["C", "megahit_scaffold1|size1200", "123"],
                ["U", "megahit_scaffold2|size400", "0"],
                ["C", "POOL-REF-1", "123"],
            ]
        ),
    )
    cluster_dir = tmp_path / "assembly/polishing/intermediate/cluster/S1"
    _write(
        cluster_dir / f"{PREFIX}S1.clusters.tsv",
        _tsv(
            [
                [
                    "sample",
                    "cluster",
                    "taxon-id",
                    "centroid",
                    "number of members",
                    "cumulative read depth - megahit [%]",
                    "members",
                ],
                ["S1", "cl0", "123.0", "POOL-REF-1", "1", "90.0", "megahit_scaffold1|size1200"],
                ["S1", "cl1", "0", "megahit_scaffold2|size400", "0", "10.0", ""],
            ]
        ),
    )
    _write(cluster_dir / f"{PREFIX}S1_cl0_cluster.json", '{\n  "cluster_id": "cl0"\n}\n')
    return tmp_path


def test_samples_overview_reads_units_and_metadata(run: Path) -> None:
    out = execute_recipe("viralmetagenome/samples_overview.py", run)
    s1, s2 = out.row(0, named=True), out.row(1, named=True)
    assert s1["raw_read_pairs"] == 1000 and s1["trimmed_reads"] == 1980
    # fastp's Q30 rate is a fraction; read as a percentage.
    assert s1["q30_pct"] == pytest.approx(99.5)
    assert s1["host_pct"] == pytest.approx(1.0)
    assert s1["retained_pct"] == pytest.approx(98.0)
    # The longest assembly across the assemblers.
    assert s1["assembly_length"] == 31000
    assert s2["denovo_consensus"] is None and s2["removed_clusters"] == 5
    assert out["meta_sample_alias"].to_list() == ["alias_a", "alias_b"]


def test_contigs_overview_keys_genomes_and_reads_percentages(run: Path) -> None:
    out = execute_recipe("viralmetagenome/contigs_overview.py", run)
    row = out.row(0, named=True)
    assert row["genome_id"] == "S1_cl0"
    assert row["route"] == "de novo" and row["step"] == "it1"
    assert row["annotation_identity_pct"] == pytest.approx(98.1)
    assert row["dup_pct"] == pytest.approx(1.25)
    assert row["blast_query_cover_pct"] == pytest.approx(90.0)
    assert row["virus"] == "SV"


def test_mapping_overview_is_the_constraint_route(run: Path) -> None:
    out = execute_recipe("viralmetagenome/mapping_overview.py", run)
    row = out.row(0, named=True)
    assert (row["genome_id"], row["route"], row["step"]) == ("S1_REF1", "constraint", None)
    # An annotation written as NA leaves the genome unnamed, not named "NA".
    assert row["virus"] == "Unclassified"


def test_contig_iterations_orders_the_steps(run: Path) -> None:
    out = execute_recipe("viralmetagenome/contig_iterations.py", run)
    assert out["step"].to_list() == ["consensus", "it1", "itvariant-calling"]
    assert out["step_order"].to_list() == [0, 1, 2]
    assert out["n_pct"].to_list() == [0.3, 1.5, 2.0]


def test_tidy_overview_of_an_empty_table_keeps_the_schema() -> None:
    out = tidy_genome_overview(pl.DataFrame(), "de novo")
    assert out.is_empty() and "genome_id" in out.columns


# ---------------------------------------------------------------------------
# Contigs, classification, clusters
# ---------------------------------------------------------------------------


def _with_upstream(run: Path) -> pl.DataFrame:
    classes = execute_recipe("viralmetagenome/contig_classes.py", run)
    clusters = execute_recipe("viralmetagenome/clusters.py", run)
    module = load_recipe("viralmetagenome/contigs.py")
    frames = {"vmg_contig_classes": classes, "vmg_clusters": clusters}
    extra = {s.ref: frames[s.dc_ref] for s in module.SOURCES if s.dc_ref in frames}
    return execute_recipe("viralmetagenome/contigs.py", run, extra_sources=extra)


def test_contig_classes_strip_the_prefix(run: Path) -> None:
    out = execute_recipe("viralmetagenome/contig_classes.py", run)
    assert set(out["sample"]) == {"S1"}
    calls = dict(zip(out["contig"], out["classification"], strict=True))
    assert calls["megahit_scaffold2|size400"] == "Unclassified"
    assert out.filter(pl.col("classification") == "Unclassified")["taxid"].to_list() == [None]


def test_clusters_read_status_from_the_kept_json(run: Path) -> None:
    out = execute_recipe("viralmetagenome/clusters.py", run)
    assert out["status"].to_list() == ["Refined", "Filtered out"]
    assert out["cluster_type"].to_list() == ["Reference-anchored", "Contig-only"]
    assert out["member_bp"].to_list() == [1200, None]
    assert out["taxid"].to_list() == ["123", "0"]


def test_contigs_join_their_call_and_cluster(run: Path) -> None:
    out = _with_upstream(run)
    assert out["contig"].to_list() == [
        "megahit_scaffold1|size1200",
        "megahit_scaffold2|size400",
        "megahit_scaffold3|size300",
    ]
    assert out["sample"].unique().to_list() == ["S1"]
    assert out["assembler"].unique().to_list() == ["megahit"]
    assert out["classification"].to_list() == ["Classified", "Unclassified", "Not classified"]
    assert out["cluster_role"].to_list() == ["Member", "Centroid", "Not clustered"]
    assert out["read_share_pct"].to_list() == [90.0, 10.0, 0.0]
    assert out["length_class"].to_list() == ["1 to 5 kb", "under 500 bp", "under 500 bp"]


def test_contigs_without_the_optional_collections(run: Path) -> None:
    out = execute_recipe("viralmetagenome/contigs.py", run)
    assert set(out["classification"]) == {"Not classified"}
    assert set(out["cluster_role"]) == {"Not clustered"}


# ---------------------------------------------------------------------------
# CheckV, iVar, mosdepth
# ---------------------------------------------------------------------------

CHECKV_HEADER = [
    "contig_id",
    "contig_length",
    "provirus",
    "proviral_length",
    "gene_count",
    "viral_genes",
    "host_genes",
    "checkv_quality",
    "miuvig_quality",
    "completeness",
    "completeness_method",
    "contamination",
    "kmer_freq",
    "warnings",
]


def test_checkv_reads_sample_and_run_from_folders(tmp_path: Path) -> None:
    row = [
        "S1_REF1-CONSTRAINT_itvariant-calling.consensus_ivar",
        "1000",
        "No",
        "NA",
        "3",
        "2",
        "0",
        "High-quality",
        "High-quality",
        "97.5",
        "AAI-based (high-confidence)",
        "0.0",
        "1.0",
        "",
    ]
    _write(
        tmp_path
        / f"consensus/quality_control/checkv/S1/{PREFIX}S1_REF1-CONSTRAINT/quality_summary.tsv",
        _tsv([CHECKV_HEADER, row]),
    )
    # A flat layout: checkv/<sample>/quality_summary.tsv.
    _write(
        tmp_path / "other/checkv/S2/quality_summary.tsv", _tsv([CHECKV_HEADER, ["c1", *row[1:]]])
    )
    out = execute_recipe("checkv/quality_summary.py", tmp_path)
    assert out.select("sample", "checkv_run").rows() == [("S1", "S1_REF1-CONSTRAINT"), ("S2", "S2")]
    assert out["completeness"].to_list() == [97.5, 97.5]
    assert out["proviral_length"].to_list() == [None, None]


IVAR_HEADER = [
    "REGION",
    "POS",
    "REF",
    "ALT",
    "REF_DP",
    "REF_RV",
    "REF_QUAL",
    "ALT_DP",
    "ALT_RV",
    "ALT_QUAL",
    "ALT_FREQ",
    "TOTAL_DP",
    "PVAL",
    "PASS",
    "GFF_FEATURE",
    "REF_CODON",
    "REF_AA",
    "ALT_CODON",
    "ALT_AA",
    "POS_AA",
]


def _ivar_rows() -> list[list[str]]:
    return [
        IVAR_HEADER,
        [
            "chr",
            "10",
            "A",
            "G",
            "0",
            "0",
            "0",
            "50",
            "20",
            "38",
            "1",
            "50",
            "0",
            "TRUE",
            "gene1",
            "AAA",
            "K",
            "AGA",
            "R",
            "4",
        ],
        [
            "chr",
            "10",
            "A",
            "G",
            "0",
            "0",
            "0",
            "50",
            "20",
            "38",
            "1",
            "50",
            "0",
            "TRUE",
            "gene1",
            "AAA",
            "K",
            "AGA",
            "R",
            "4",
        ],
        [
            "chr",
            "20",
            "C",
            "+TT",
            "40",
            "20",
            "38",
            "10",
            "5",
            "38",
            "0.2",
            "50",
            "0.4",
            "FALSE",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
        ],
        [
            "chr",
            "30",
            "G",
            "-A",
            "20",
            "10",
            "38",
            "30",
            "15",
            "38",
            "0.6",
            "50",
            "0.01",
            "TRUE",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
        ],
    ]


def test_ivar_variants_split_sample_and_reference(tmp_path: Path) -> None:
    _write(
        tmp_path / f"variants/ivar/S1/{PREFIX}S1_REF1-CONSTRAINT_constraint.tsv", _tsv(_ivar_rows())
    )
    _write(tmp_path / f"variants/ivar/S1/{PREFIX}S1_cl0_it1.tsv", _tsv(_ivar_rows()[:2]))
    out = execute_recipe("ivar/variants_tsv.py", tmp_path)
    constraint = out.filter(pl.col("reference") == "REF1")
    # The repeated feature row collapses to one variant.
    assert constraint.height == 3
    assert constraint["variant_type"].to_list() == ["SNV", "Insertion", "Deletion"]
    assert constraint["frequency_class"].to_list() == ["Fixed", "Minor", "Major"]
    assert constraint["filter"].to_list() == ["PASS", "Filtered", "PASS"]
    assert constraint["aa_change"].to_list() == ["K4R", None, None]
    assert set(out["genome_id"]) == {"S1_REF1", "S1_cl0"}
    assert out.filter(pl.col("genome_id") == "S1_cl0")["route"].to_list() == ["de novo"]


def test_ivar_variants_flat_layout_has_no_reference(tmp_path: Path) -> None:
    _write(tmp_path / "variants/ivar/SAMPLE_A.tsv", _tsv(_ivar_rows()[:2]))
    out = execute_recipe("ivar/variants_tsv.py", tmp_path)
    assert out.select("sample", "reference", "genome_id").rows() == [("SAMPLE_A", None, "SAMPLE_A")]


def _gz(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write(text)


def test_per_base_bins_weight_by_overlap(tmp_path: Path) -> None:
    mos = tmp_path / "variants/mapping-info/metrics/mosdepth/S1"
    # 100 bp reference: 0-30 at depth 0, 30-100 at depth 10. Bins of 50 bp.
    _gz(
        mos / f"{PREFIX}S1_REF1-CONSTRAINT_constraint.per-base.bed.gz",
        "ref\t0\t30\t0\nref\t30\t100\t10\n",
    )
    out = execute_recipe("mosdepth/per_base_bins.py", tmp_path)
    assert out.select("start", "end").rows() == [(0, 50), (50, 100)]
    assert out["mean_depth"].to_list() == [4.0, 10.0]
    assert out["min_depth"].to_list() == [0, 10]
    assert out["genome_id"].unique().to_list() == ["S1_REF1"]


def test_cumulative_coverage_keeps_the_total(tmp_path: Path) -> None:
    mos = tmp_path / "variants/mapping-info/metrics/mosdepth/S1"
    _write(
        mos / f"{PREFIX}S1_cl0_it1.mosdepth.global.dist.txt",
        "ref\t2\t0.50\nref\t1\t0.90\nref\t0\t1.00\ntotal\t2\t0.50\ntotal\t1\t0.90\ntotal\t0\t1.00\n",
    )
    out = execute_recipe("mosdepth/cumulative_coverage.py", tmp_path)
    assert out.select("depth", "bases_pct").rows() == [(0, 100.0), (1, 90.0), (2, 50.0)]
    assert out["genome_id"].unique().to_list() == ["S1_cl0"]
