"""nf-core/rnavar catalog recipes on small synthetic outputs.

The template reads STAR's own reports (``Log.final.out``, ``SJ.out.tab``),
samtools idxstats, Picard MarkDuplicates and the HaplotypeCaller VCFs. These
tests pin what the dashboard reads off them: the STAR read fate and splice
shares, the junction motif folding, the contig classes and the one stage kept
per sample, the stage tokens rnavar puts in its report names (``.md``,
``.aligned``), and the four per-callset summaries built from the VCF rows,
the variant density for the ideogram included. The pipeline recipes (calls,
navigator windows, sample hub) are in ``test_rnavar_project_recipes.py``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe
from depictio.recipes.lib.sample_ids import strip_stage_suffixes
from depictio.recipes.lib.star_logs import parse_log_final, sample_from_path

LOG_FINAL = """                                 Started job on |\tJun 01 16:30:34
                          Number of input reads |\t{reads}
                      Average input read length |\t152
                                    UNIQUE READS:
                   Uniquely mapped reads number |\t{unique}
                        Uniquely mapped reads % |\t{unique_pct}%
                          Average mapped length |\t150.82
                       Number of splices: Total |\t1000
            Number of splices: Annotated (sjdb) |\t{annotated}
                       Number of splices: GT/AG |\t980
                       Number of splices: GC/AG |\t10
                       Number of splices: AT/AC |\t5
                       Number of splices: Non-canonical |\t5
                      Mismatch rate per base, % |\t0.52%
                         Deletion rate per base |\t0.02%
                        Insertion rate per base |\t0.00%
                             MULTI-MAPPING READS:
        Number of reads mapped to multiple loci |\t100
             % of reads mapped to multiple loci |\t10.00%
        Number of reads mapped to too many loci |\t10
             % of reads mapped to too many loci |\t1.00%
                                  UNMAPPED READS:
  Number of reads unmapped: too many mismatches |\t0
       % of reads unmapped: too many mismatches |\t0.00%
            Number of reads unmapped: too short |\t40
                 % of reads unmapped: too short |\t4.00%
                Number of reads unmapped: other |\t10
                     % of reads unmapped: other |\t1.00%
                                  CHIMERIC READS:
                       Number of chimeric reads |\t0
                            % of chimeric reads |\t0.00%
"""

# chrom, intron start, end, strand, motif, annotated, unique reads, multi reads, overhang
SJ_ROWS = [
    ("chr1", 100, 200, 1, 1, 1, 50, 2, 30),  # GT/AG annotated
    ("chr1", 300, 400, 2, 2, 1, 30, 0, 30),  # CT/AC = GT/AG on the minus strand
    ("chr1", 500, 600, 1, 3, 0, 2, 0, 12),  # GC/AG novel
    ("chr2", 100, 900, 0, 0, 0, 1, 3, 8),  # non-canonical novel
]

IDXSTATS = "chr1\t248956422\t9000\t10\nchrX\t156040895\t500\t0\nchrY\t57227415\t5\t0\nchrM\t16569\t400\t0\nchrUn_GL000220v1\t161802\t95\t0\n*\t0\t0\t1000\n"

VCF_HEADER = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n"


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    for sample, reads, unique, annotated in (("S1", 1000, 840, 990), ("S2", 2000, 1600, 0)):
        star = tmp_path / "reports" / "star" / sample
        star.mkdir(parents=True)
        (star / f"{sample}.Log.final.out").write_text(
            LOG_FINAL.format(
                reads=reads,
                unique=unique,
                unique_pct=f"{unique * 100 / reads:.2f}",
                annotated=annotated,
            )
        )
        (star / f"{sample}.SJ.out.tab").write_text(
            "\n".join("\t".join(str(f) for f in row) for row in SJ_ROWS) + "\n"
        )
        sam = tmp_path / "reports" / "samtools" / sample
        sam.mkdir(parents=True)
        (sam / f"{sample}.md.idxstats").write_text(IDXSTATS)
        # The aligned twin holds other counts: the md stage must win.
        (sam / f"{sample}.aligned.idxstats").write_text(IDXSTATS.replace("9000", "1"))
    return tmp_path


def _variants() -> pl.DataFrame:
    """A long ``vcf/variants`` frame: two samples, PASS and filtered calls."""
    rows = [
        # sample, chrom, pos, ref, alt, type, qual, filter, pass, gt, dp, vaf
        ("S1", "chr1", 1_000, "A", "G", "SNP", 300.0, "PASS", True, "0/1", 20, 0.5),
        ("S1", "chr1", 2_000, "T", "C", "SNP", 300.0, "PASS", True, "1/1", 30, 1.0),
        ("S1", "chr1", 1_500_000, "C", "T", "SNP", 200.0, "PASS", True, "0/1", 10, 0.4),
        ("S1", "chr1", 3_000, "G", "T", "SNP", 50.0, "QD", False, "0/1", 4, 0.25),
        ("S1", "chr2", 5_000, "AT", "A", "INDEL", 90.0, "FS;QD", False, "0/1", 8, 0.5),
        ("S1", "chrUn_GL000220v1", 10, "A", "G", "SNP", 99.0, "PASS", True, "0/1", 50, 0.5),
        ("S2", "chr1", 1_000, "A", "G", "SNP", 300.0, "PASS", True, "0/1", 22, 0.45),
        ("S2", "chr2", 7_000, "C", "A", "SNP", 300.0, "PASS", True, "1/1", 25, 1.0),
        ("S2", "chr2", 8_000, "G", "GA,GAA", "INDEL", 300.0, "PASS", True, "1/2", 25, 0.4),
    ]
    frame = pl.DataFrame(
        rows,
        schema=[
            "sample",
            "chrom",
            "pos",
            "ref",
            "alt",
            "variant_type",
            "qual",
            "filter_status",
            "is_pass",
            "gt",
            "dp",
            "vaf",
        ],
        orient="row",
    )
    return frame.with_columns(
        pl.lit("haplotypecaller").alias("caller"),
        pl.concat_str(
            [
                pl.col("chrom"),
                pl.col("pos").cast(pl.Utf8),
                pl.col("ref"),
                pl.col("alt").str.split(",").list.first(),
            ],
            separator=":",
        ).alias("variant_key"),
    )


# ---------------------------------------------------------------------------
# STAR
# ---------------------------------------------------------------------------


def test_star_sample_comes_off_the_report_name() -> None:
    assert sample_from_path("reports/star/GM_1/GM_1.Log.final.out") == "GM_1"
    assert sample_from_path("x/S.1.SJ.out.tab") == "S.1"


def test_log_final_reads_counts_shares_and_derives_the_splice_shares(run_dir: Path) -> None:
    df = execute_recipe("star/log_final.py", run_dir)
    assert df["sample"].to_list() == ["S1", "S2"]
    s1 = df.row(0, named=True)
    assert s1["input_reads"] == 1000 and s1["uniquely_mapped"] == 840
    assert s1["uniquely_mapped_pct"] == pytest.approx(84.0)
    assert s1["mapped_pct"] == pytest.approx(94.0)
    assert s1["unmapped_pct"] == pytest.approx(5.0)
    assert s1["splices_annotated_pct"] == pytest.approx(99.0)
    assert s1["splices_noncanonical_pct"] == pytest.approx(0.5)
    assert s1["mismatch_rate_pct"] == pytest.approx(0.52)
    assert df.row(1, named=True)["splices_annotated_pct"] == 0.0


def test_log_final_without_splices_reads_the_share_as_null() -> None:
    raw = pl.DataFrame(
        {
            "raw_line": ["  Number of input reads |\t10", "  Number of splices: Total |\t0"],
            "source_path": ["a/S.Log.final.out"] * 2,
        }
    )
    logs = parse_log_final(raw)
    assert logs["input_reads"].to_list() == [10]
    assert logs["uniquely_mapped_pct"].to_list() == [None]  # absent key, not a failure


def test_read_fate_sums_to_the_input(run_dir: Path) -> None:
    df = execute_recipe("star/read_fate.py", run_dir).filter(pl.col("sample") == "S1")
    assert df["fate"].to_list()[0] == "Uniquely mapped"
    assert df["fate_order"].to_list() == [1, 2, 3, 4, 5, 6]
    assert df["reads_pct"].sum() == pytest.approx(100.0)


def test_junctions_fold_the_strand_readings_of_a_motif(run_dir: Path) -> None:
    df = execute_recipe("star/junctions.py", run_dir).filter(pl.col("sample") == "S1")
    cells = {(r["motif_class"], r["annotation"]): r for r in df.iter_rows(named=True)}
    assert cells[("GT/AG", "annotated")]["junctions"] == 2  # motif 1 and 2 together
    assert cells[("GT/AG", "annotated")]["unique_reads"] == 80
    assert cells[("GC/AG", "novel")]["junctions"] == 1
    assert cells[("non-canonical", "novel")]["multimapping_reads"] == 3
    assert df["junctions_pct"].sum() == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# samtools idxstats, Picard and the stage tokens
# ---------------------------------------------------------------------------


def test_idxstats_classes_contigs_and_keeps_the_duplicate_marked_stage(run_dir: Path) -> None:
    df = execute_recipe("samtools/idxstats.py", run_dir)
    assert df["stage"].unique().to_list() == ["md"]
    s1 = {r["contig"]: r for r in df.filter(pl.col("sample") == "S1").iter_rows(named=True)}
    assert "*" not in s1
    assert s1["chr1"]["mapped_reads"] == 9000 and s1["chr1"]["contig_class"] == "autosome"
    assert s1["chrM"]["contig_class"] == "mitochondrion"
    assert s1["chrUn_GL000220v1"]["contig_class"] == "other"
    assert s1["chrM"]["mapped_pct"] == pytest.approx(4.0)
    assert sum(r["mapped_pct"] for r in s1.values()) == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("name", "sample"),
    [
        ("GM_REP1.md", "GM_REP1"),
        ("GM_REP1.aligned", "GM_REP1"),
        ("NA12878.md.cram", "NA12878.md.cram"),  # cram is not a stage token
        ("md", "md"),  # never emptied
    ],
)
def test_rnavar_stage_tokens_are_stripped(name: str, sample: str) -> None:
    assert strip_stage_suffixes(name) == sample


def test_picard_report_name_drops_the_md_stage(tmp_path: Path) -> None:
    report = (
        "## htsjdk.samtools.metrics.StringHeader\n"
        "## METRICS CLASS\tpicard.sam.DuplicationMetrics\n"
        "LIBRARY\tUNPAIRED_READS_EXAMINED\tREAD_PAIRS_EXAMINED\tUNPAIRED_READ_DUPLICATES\t"
        "READ_PAIR_DUPLICATES\tPERCENT_DUPLICATION\n"
        "lib\t10\t100\t2\t50\t0.5\n"
    )
    raw = pl.DataFrame(
        {
            "raw": report.splitlines(),
            "source_path": ["reports/picard/S1/S1.md.metrics.txt"] * len(report.splitlines()),
        }
    )
    df = execute_recipe(
        "picard/markduplicates_metrics.py", tmp_path, extra_sources={"reports": raw}
    )
    assert df["sample"].to_list() == ["S1"]
    assert df["percent_duplication"].to_list() == [0.5]


# ---------------------------------------------------------------------------
# Per-callset summaries from the VCF rows
# ---------------------------------------------------------------------------


def test_callset_summary_counts_pass_calls_and_ratios(tmp_path: Path) -> None:
    df = execute_recipe("vcf/callset_summary.py", tmp_path, extra_sources={"variants": _variants()})
    s1 = df.filter(pl.col("sample") == "S1").row(0, named=True)
    assert s1["calls"] == 6 and s1["pass_calls"] == 4
    assert s1["pass_pct"] == pytest.approx(66.67)
    assert s1["snvs"] == 4 and s1["indels"] == 0
    assert s1["transitions"] == 4 and s1["transversions"] == 0
    assert s1["ts_tv"] is None  # no transversion: null, never 0
    assert s1["het"] == 3 and s1["hom_alt"] == 1 and s1["het_hom_ratio"] == pytest.approx(3.0)
    s2 = df.filter(pl.col("sample") == "S2").row(0, named=True)
    assert s2["multiallelic"] == 1 and s2["het"] == 2  # 0/1 and 1/2 are both heterozygous
    assert s2["ts_tv"] == pytest.approx(1.0)


def test_substitution_spectrum_folds_onto_pyrimidines(tmp_path: Path) -> None:
    df = execute_recipe(
        "vcf/substitution_spectrum.py", tmp_path, extra_sources={"variants": _variants()}
    )
    s1 = {
        r["substitution_class"]: r
        for r in df.filter(pl.col("sample") == "S1").iter_rows(named=True)
    }
    assert len(s1) == 6  # every class, 0 when absent
    assert s1["T to C"]["count"] == 3  # A>G twice (folded) and T>C once
    assert s1["C to T"]["count"] == 1
    assert s1["C to A"]["count"] == 0 and s1["C to A"]["mutation_class"] == "transversion"
    assert sum(r["fraction"] for r in s1.values()) == pytest.approx(1.0)


def test_filter_breakdown_partitions_the_callset(tmp_path: Path) -> None:
    df = execute_recipe(
        "vcf/filter_breakdown.py", tmp_path, extra_sources={"variants": _variants()}
    )
    s1 = {r["filter_label"]: r for r in df.filter(pl.col("sample") == "S1").iter_rows(named=True)}
    assert set(s1) == {"PASS", "QD", "FS;QD"}
    assert s1["PASS"]["is_pass"] and s1["PASS"]["failed_filters"] == 0
    assert s1["FS;QD"]["failed_filters"] == 2 and s1["FS;QD"]["indels"] == 1
    assert sum(r["calls_pct"] for r in s1.values()) == pytest.approx(100.0, abs=0.01)


def test_variant_density_bins_pass_calls_on_primary_contigs(tmp_path: Path) -> None:
    df = execute_recipe(
        "vcf/variant_density.py",
        tmp_path,
        extra_sources={"variants": _variants()},
        params={"bin_size": "1000000"},
    )
    assert df.columns == ["chrom", "start", "end", "value", "sample"]
    s1 = df.filter(pl.col("sample") == "S1").sort(["chrom", "start"])
    # Two PASS calls in chr1:0-1Mb, one in chr1:1-2Mb; the filtered chr1 and
    # chr2 calls and the unplaced contig are left out.
    assert s1.select("chrom", "start", "end", "value").rows() == [
        ("chr1", 0, 1_000_000, 2),
        ("chr1", 1_000_000, 2_000_000, 1),
    ]
    assert "chrUn_GL000220v1" not in df["chrom"].to_list()


def test_variant_density_bin_size_comes_from_the_template_params(tmp_path: Path) -> None:
    df = execute_recipe(
        "vcf/variant_density.py",
        tmp_path,
        extra_sources={"variants": _variants()},
        params={"bin_size": "10000000"},
    )
    s1 = df.filter(pl.col("sample") == "S1")
    assert s1.rows() == [("chr1", 0, 10_000_000, 3, "S1")]
