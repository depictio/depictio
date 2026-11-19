"""nf-core/viralmetagenome on a segmented, multi-virus run.

The template was first checked on one unsegmented virus (the SARS-CoV-2
megatest). These tests stand in for a segmented run: Lassa virus (S, L),
CCHFV (S, M, L) and an influenza segment 8 BLAST matched to a reference much
longer than the segment, plus a run called with ``--variant_caller bcftools``.
They cover:

* segments as their own genomes (``segment``, ``virus_segment``) and the BLAST
  reference cover that replaces CheckV as the completeness reading;
* the sample x segment matrix and the de novo / constraint comparison;
* the caller-agnostic variant table, the intra-host entropy and the UMI logs;
* the genome browser's track manifest and loci, and the genome-end depth.
"""

from __future__ import annotations

import gzip
import math
from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe
from depictio.recipes.lib.viralmetagenome import (
    COMPLETENESS_COMPLETE,
    COMPLETENESS_FRAGMENT,
    COMPLETENESS_MISMATCH,
    COMPLETENESS_NO_HIT,
    COMPLETENESS_PARTIAL,
    GENOME_SCHEMA,
    ROUTE_CONSTRAINT,
    ROUTE_DENOVO,
    tidy_genome_overview,
)

PREFIX = "test_20260101_1.2.0_happy_turing-"


def _run(recipe: str, root: Path, frames: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """The recipe's output on ``root``, its dc_ref sources fed from ``frames`` (keyed by DC tag)."""
    module = load_recipe(recipe)
    extra = {s.ref: frames[s.dc_ref] for s in module.SOURCES if frames.get(s.dc_ref) is not None}
    return execute_recipe(recipe, root, extra_sources=extra)


def _write(path: Path, text: str, *, gz: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if gz:
        with gzip.open(path, "wt") as fh:
            fh.write(text)
    else:
        path.write_text(text)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        _write(root / rel, "x")


# ---------------------------------------------------------------------------
# Segments and reference cover
# ---------------------------------------------------------------------------


def _overview_row(
    sample: str,
    cluster: str,
    acronym: str,
    segment: str,
    qlen: int,
    slen: int,
    sstart: int,
    send: int,
    aligned: int,
    step: str = "it2",
) -> dict[str, str]:
    return {
        "sample": sample,
        "cluster": cluster,
        "step": step,
        "(annotation) acronym": acronym,
        "(annotation) segment": segment,
        "(blast) qlen": str(qlen),
        "(blast) slen": str(slen),
        "(blast) sstart": str(sstart),
        "(blast) send": str(send),
        "(blast) length": str(aligned),
    }


@pytest.fixture()
def segmented() -> pl.DataFrame:
    rows = [
        # Lassa S and L: two genomes of one virus, both whole.
        _overview_row("S1", "cl0", "LASV", "S", 3400, 3402, 1, 3402, 3398),
        _overview_row("S1", "cl1", "LASV", "L", 7270, 7279, 7279, 5, 7262),
        # CCHFV M, three quarters of it aligned; S with a dash for its segment.
        _overview_row("S2", "cl0", "CCHFV", "segment M", 5000, 5366, 1, 4000, 3990),
        _overview_row("S2", "cl1", "CCHFV", "-", 1600, 1672, 30, 300, 270),
        # Influenza segment 8 (~890 nt) whose best hit is a 2349 nt reference:
        # it aligns end to end, but covers 38 % of the hit.
        _overview_row("S3", "cl0", "H5N1", "8", 890, 2349, 1, 890, 885),
        # No BLAST hit at all.
        {"sample": "S3", "cluster": "cl1", "step": "it1", "(annotation) acronym": "NA"},
    ]
    return pl.DataFrame(rows).with_columns(pl.all().cast(pl.Utf8))


def test_segments_are_their_own_genomes(segmented: pl.DataFrame) -> None:
    out = tidy_genome_overview(segmented, ROUTE_DENOVO).sort("genome_id")
    by_id = {r["genome_id"]: r for r in out.iter_rows(named=True)}
    assert by_id["S1_cl0"]["virus_segment"] == "LASV S"
    assert by_id["S1_cl1"]["virus_segment"] == "LASV L"
    # "segment M" reads M; a placeholder segment leaves the virus alone.
    assert by_id["S2_cl0"]["segment"] == "M"
    assert by_id["S2_cl1"]["segment"] is None
    assert by_id["S2_cl1"]["virus_segment"] == "CCHFV"
    assert by_id["S3_cl1"]["virus_segment"] == "Unclassified"


def test_reference_cover_reads_completeness_per_segment(segmented: pl.DataFrame) -> None:
    out = tidy_genome_overview(segmented, ROUTE_DENOVO)
    by_id = {r["genome_id"]: r for r in out.iter_rows(named=True)}
    # (|send - sstart| + 1) / slen, on either strand.
    assert by_id["S1_cl0"]["ref_cover_pct"] == 100.0
    assert by_id["S1_cl1"]["ref_cover_pct"] == pytest.approx(100.0 * 7275 / 7279, abs=0.01)
    assert by_id["S1_cl1"]["len_minus_ref"] == -9
    assert by_id["S1_cl0"]["completeness_call"] == COMPLETENESS_COMPLETE
    assert by_id["S1_cl1"]["completeness_call"] == COMPLETENESS_COMPLETE
    assert by_id["S2_cl0"]["completeness_call"] == COMPLETENESS_PARTIAL
    assert by_id["S2_cl1"]["completeness_call"] == COMPLETENESS_FRAGMENT
    # Influenza segment 8: aligned end to end on a longer hit, flagged, not
    # read as a fragment.
    assert by_id["S3_cl0"]["ref_cover_pct"] == pytest.approx(37.89, abs=0.01)
    assert by_id["S3_cl0"]["completeness_call"] == COMPLETENESS_MISMATCH
    assert by_id["S3_cl1"]["completeness_call"] == COMPLETENESS_NO_HIT
    assert set(out.columns) == set(GENOME_SCHEMA)


def _genomes(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame([{c: r.get(c) for c in GENOME_SCHEMA} for r in rows], schema=GENOME_SCHEMA)


def test_genome_hub_names_what_each_genome_was_built_on(tmp_path: Path) -> None:
    denovo = _genomes(
        [
            {"genome_id": "S1_cl0", "sample": "S1", "reference": "cl0", "route": ROUTE_DENOVO},
            {"genome_id": "S1_cl1", "sample": "S1", "reference": "cl1", "route": ROUTE_DENOVO},
        ]
    )
    constraint = _genomes(
        [{"genome_id": "S1_REF", "sample": "S1", "reference": "REF", "route": ROUTE_CONSTRAINT}]
    )
    clusters = pl.DataFrame(
        {
            "sample": ["S1", "S1"],
            "cluster": ["cl0", "cl1"],
            "cluster_type": ["Reference-anchored", "Contig-only"],
        }
    )
    hub = _run(
        "nf-core/viralmetagenome/genomes.py",
        tmp_path,
        {
            "vmg_contigs_overview": denovo,
            "vmg_mapping_overview": constraint,
            "vmg_clusters": clusters,
        },
    )
    assert dict(zip(hub["genome_id"], hub["cluster_type"], strict=True)) == {
        "S1_cl0": "Reference-anchored",
        "S1_cl1": "Contig-only",
        "S1_REF": "Constraint reference",
    }


def _hub(rows: list[dict]) -> pl.DataFrame:
    base = {"virus": None, "segment": None, "n_pct": None, "completeness_call": None}
    return pl.DataFrame([{**base, **r} for r in rows]).with_columns(
        pl.col("ref_cover_pct").cast(pl.Float64), pl.col("n_pct").cast(pl.Float64)
    )


def test_genome_matrix_puts_segments_against_samples(tmp_path: Path) -> None:
    hub = _hub(
        [
            {
                "genome_id": "a",
                "sample": "S-1",
                "virus": "LASV",
                "virus_segment": "LASV S",
                "ref_cover_pct": 99.0,
                "route": ROUTE_DENOVO,
            },
            {
                "genome_id": "b",
                "sample": "S-1",
                "virus": "LASV",
                "virus_segment": "LASV S",
                "ref_cover_pct": 80.0,
                "route": ROUTE_CONSTRAINT,
            },
            {
                "genome_id": "c",
                "sample": "S-1",
                "virus": "LASV",
                "virus_segment": "LASV L",
                "ref_cover_pct": 40.0,
                "route": ROUTE_DENOVO,
            },
            {
                "genome_id": "d",
                "sample": "S2",
                "virus": "LASV",
                "virus_segment": "LASV S",
                "ref_cover_pct": 97.0,
                "route": ROUTE_DENOVO,
            },
        ]
    )
    m = _run("nf-core/viralmetagenome/genome_matrix.py", tmp_path, {"genomes": hub})
    # Sample columns are store-safe; the best genome of a segment wins; a
    # segment a sample has no genome of reads 0.
    assert m.columns == ["virus_segment", "virus", "s_1", "s2"]
    rows = {r["virus_segment"]: r for r in m.iter_rows(named=True)}
    assert rows["LASV S"]["s_1"] == 99.0
    assert rows["LASV L"]["s2"] == 0.0


def test_route_comparison_lines_up_the_two_routes(tmp_path: Path) -> None:
    hub = _hub(
        [
            {
                "genome_id": "S1_cl0",
                "sample": "S1",
                "reference": "cl0",
                "virus_segment": "LASV L",
                "ref_cover_pct": 60.0,
                "route": ROUTE_DENOVO,
            },
            {
                "genome_id": "S1_L",
                "sample": "S1",
                "reference": "L",
                "virus_segment": "LASV L",
                "ref_cover_pct": 99.0,
                "route": ROUTE_CONSTRAINT,
            },
            {
                "genome_id": "S1_cl1",
                "sample": "S1",
                "reference": "cl1",
                "virus_segment": "LASV S",
                "ref_cover_pct": 99.0,
                "route": ROUTE_DENOVO,
            },
            {
                "genome_id": "S1_S",
                "sample": "S1",
                "reference": "S",
                "virus_segment": "LASV S",
                "ref_cover_pct": 98.5,
                "route": ROUTE_CONSTRAINT,
            },
            {
                "genome_id": "S2_cl0",
                "sample": "S2",
                "reference": "cl0",
                "virus_segment": "LASV S",
                "ref_cover_pct": 90.0,
                "route": ROUTE_DENOVO,
            },
        ]
    )
    out = _run("nf-core/viralmetagenome/route_comparison.py", tmp_path, {"genomes": hub})
    rows = {(r["sample"], r["virus_segment"]): r for r in out.iter_rows(named=True)}
    assert rows[("S1", "LASV L")]["better_route"] == ROUTE_CONSTRAINT
    assert rows[("S1", "LASV L")]["cover_gain"] == 39.0
    assert rows[("S1", "LASV L")]["constraint_reference"] == "L"
    assert rows[("S1", "LASV S")]["better_route"] == "similar"
    assert rows[("S2", "LASV S")]["better_route"] == "de novo only"


# ---------------------------------------------------------------------------
# Variants from either caller
# ---------------------------------------------------------------------------

_VCF_HEAD = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"


def _bcftools_run(root: Path) -> None:
    body = (
        _VCF_HEAD
        + "LASV_L\t100\t.\tA\tG\t200\t.\tDP=50\tGT:PL:DP:AD\t1:0,255:50:2,48\n"
        + "LASV_L\t200\t.\tAT\tA\t90\tPASS\tDP=40\tGT:PL:DP:AD\t1:0,255:40:10,30\n"
    )
    name = f"{PREFIX}S1_LASVL-CONSTRAINT_constraint"
    _write(root / f"variants/bcftools/S1/{name}.filtered.vcf.gz", body, gz=True)
    # Calls before the frequency filter, minor ones included.
    norm = body + "LASV_L\t300\t.\tC\tT\t30\t.\tDP=100\tGT:PL:DP:AD\t0:0,255:100:50,50\n"
    _write(root / f"variants/bcftools/S1/{name}.norm.vcf.gz", norm, gz=True)


def test_variants_read_a_bcftools_run(tmp_path: Path) -> None:
    _bcftools_run(tmp_path)
    hub = pl.DataFrame(
        {
            "genome_id": ["S1_LASVL"],
            "virus": ["LASV"],
            "segment": ["L"],
            "virus_segment": ["LASV L"],
        }
    )
    calls = _run("nf-core/viralmetagenome/variants.py", tmp_path, {"genomes": hub})
    # The filtered VCF only: the .norm one holds the calls before the filter.
    assert calls["pos"].to_list() == [100, 200]
    assert set(calls["caller"]) == {"bcftools"}
    assert set(calls["genome_id"]) == {"S1_LASVL"}
    assert set(calls["route"]) == {ROUTE_CONSTRAINT}
    assert calls["af"].to_list() == [0.96, 0.75]
    assert calls["variant_type"].to_list() == ["SNV", "Deletion"]
    assert calls["filter"].to_list() == ["PASS", "PASS"]
    assert calls["virus_segment"].to_list() == ["LASV L", "LASV L"]


def test_variants_never_count_an_ivar_call_twice(tmp_path: Path) -> None:
    ivar_vcf = _VCF_HEAD + (
        "REF\t5\t.\tG\tA\t.\tPASS\tTYPE=SNP\tGT:DP:REF_DP:ALT_DP:ALT_FREQ\t1:20:0:20:1\n"
    )
    _write(tmp_path / f"variants/ivar/S1/{PREFIX}S1_cl0_it1.filtered.vcf.gz", ivar_vcf, gz=True)
    ivar_table = pl.DataFrame(
        {
            "genome_id": ["S1_cl0", "S1_cl0"],
            "sample": ["S1", "S1"],
            "reference": ["cl0", "cl0"],
            "route": [ROUTE_DENOVO] * 2,
            "chrom": ["REF", "REF"],
            "pos": [5, 9],
            "ref": ["G", "C"],
            "alt": ["A", "T"],
            "af": [1.0, 0.1],
            "total_dp": [20, 30],
            "filter": ["PASS", "Filtered"],
        }
    )
    calls = _run("nf-core/viralmetagenome/variants.py", tmp_path, {"ivar_variants": ivar_table})
    assert calls["pos"].to_list() == [5, 9]
    assert set(calls["caller"]) == {"ivar"}
    # Without the table, iVar's own VCF stands in for it.
    alone = _run("nf-core/viralmetagenome/variants.py", tmp_path, {})
    assert alone["pos"].to_list() == [5]
    assert alone["af"].to_list() == [1.0]


def test_intrahost_entropy_from_bcftools_calls(tmp_path: Path) -> None:
    _bcftools_run(tmp_path)
    out = _run("nf-core/viralmetagenome/intrahost_diversity.py", tmp_path, {})
    by_pos = dict(zip(out["pos"], out["entropy"], strict=True))
    # Two alleles at half each: ln 2.
    assert by_pos[300] == pytest.approx(math.log(2), abs=1e-3)
    assert by_pos[100] == pytest.approx(-(0.96 * math.log(0.96) + 0.04 * math.log(0.04)), abs=1e-3)


def test_intrahost_entropy_from_the_ivar_table(tmp_path: Path) -> None:
    ivar_table = pl.DataFrame(
        {
            "genome_id": ["g"] * 4,
            "sample": ["S1"] * 4,
            "chrom": ["c"] * 4,
            "pos": [10, 10, 20, 30],
            "ref": ["A", "A", "C", "G"],
            "alt": ["G", "T", "T", "A"],
            "af": [0.25, 0.25, 0.5, 0.5],
            "total_dp": [100, 100, 100, 5],
        }
    )
    out = _run(
        "nf-core/viralmetagenome/intrahost_diversity.py", tmp_path, {"ivar_variants": ivar_table}
    )
    rows = {r["pos"]: r for r in out.iter_rows(named=True)}
    # Three alleles at 0.5 / 0.25 / 0.25; position 30 sits on too few reads.
    assert rows[10]["entropy"] == pytest.approx(1.0397, abs=1e-3)
    assert rows[10]["n_alt_alleles"] == 2
    assert rows[10]["minor_af"] == 0.25
    assert 30 not in rows


# ---------------------------------------------------------------------------
# UMIs
# ---------------------------------------------------------------------------


def test_umi_stats_read_the_umi_tools_logs(tmp_path: Path) -> None:
    _write(
        tmp_path / f"preprocessing/umi/umitools/log/{PREFIX}S1.umi_extract.log",
        "# UMI-tools version: 1.1.5\n2024 INFO Input Reads: 1000\n2024 INFO Reads output: 950\n",
    )
    _write(
        tmp_path
        / f"variants/mapping-info/deduplicate/log/S1/{PREFIX}S1_LASVL-CONSTRAINT_constraint.umi_deduplicated.log",
        "2024 INFO Reads: Input Reads: 800, Read pairs: 800\n"
        "2024 INFO Number of reads out: 200\n"
        "2024 INFO Total number of positions deduplicated: 150\n"
        "2024 INFO Mean number of unique UMIs per position: 1.25\n"
        "2024 INFO Max. number of unique UMIs per position: 4\n",
    )
    out = _run("nf-core/viralmetagenome/umi_stats.py", tmp_path, {})
    rows = {r["step"]: r for r in out.iter_rows(named=True)}
    assert rows["extract"]["sample"] == "S1"
    assert rows["extract"]["removed_pct"] == 5.0
    assert rows["dedup"]["genome_id"] == "S1_LASVL"
    assert rows["dedup"]["removed_pct"] == 75.0
    assert rows["dedup"]["mean_umis_per_position"] == 1.25
    assert rows["dedup"]["max_umis_per_position"] == 4


# ---------------------------------------------------------------------------
# Genome browser and genome ends
# ---------------------------------------------------------------------------


def test_tracks_list_the_indexed_files_of_each_genome(tmp_path: Path) -> None:
    dedup = (
        f"variants/mapping-info/deduplicate/bam/S1/{PREFIX}S1_LASVL-CONSTRAINT_constraint.dedup.bam"
    )
    raw = f"variants/mapping-info/bwamem2/bam/S1/{PREFIX}S1_LASVL-CONSTRAINT_constraint.bam"
    depth = f"variants/mapping-info/metrics/mosdepth/S1/{PREFIX}S1_LASVL-CONSTRAINT_constraint.per-base.bed.gz"
    vcf = f"variants/ivar/S1/{PREFIX}S1_LASVL-CONSTRAINT_constraint.vcf"
    _touch(
        tmp_path,
        dedup,
        dedup + ".bai",
        raw,
        raw + ".bai",
        depth,
        depth + ".csi",
        vcf,
        f"variants/ivar/S1/{PREFIX}S1_LASVL-CONSTRAINT_constraint_all_hap.vcf",
        # A bgzipped VCF without its index is not a track.
        f"variants/ivar/S1/{PREFIX}S1_LASVL-CONSTRAINT_constraint.filtered.vcf.gz",
        # A BAM of a genome the hub does not hold is not either.
        f"variants/mapping-info/deduplicate/bam/S1/{PREFIX}S1_OTHER-CONSTRAINT_constraint.dedup.bam",
    )
    hub = pl.DataFrame({"genome_id": ["S1_LASVL"], "sample": ["S1"], "reference": ["LASVL"]})
    out = _run("nf-core/viralmetagenome/tracks.py", tmp_path, {"genomes": hub})
    assert out["kind"].to_list() == ["alignments", "depth", "variants"]
    assert out["uri"].to_list() == [dedup, depth, vcf]
    assert out["index_uri"].to_list() == [dedup + ".bai", depth + ".csi", None]
    assert out["format"].to_list() == ["bam", "bedgraph", "vcf"]
    assert out["order"].to_list() == [1, 2, 3]


def test_genome_loci_open_the_whole_genome_and_its_ends(tmp_path: Path) -> None:
    bins = pl.DataFrame(
        {
            "genome_id": ["g", "g", "short"],
            "sample": ["S1", "S1", "S1"],
            "chrom": ["L", "L", "S"],
            "end": [5000, 7279, 300],
        }
    )
    out = _run("nf-core/viralmetagenome/genome_loci.py", tmp_path, {"coverage_bins": bins})
    g = out.filter(pl.col("genome_id") == "g")
    assert g["region"].to_list() == ["Whole genome", "5' end", "3' end"]
    assert list(zip(g["start"], g["end"], strict=True)) == [(1, 7279), (1, 200), (7080, 7279)]
    s = out.filter(pl.col("genome_id") == "short")
    assert s["length"].to_list() == [300, 300, 300]


def test_genome_ends_bin_the_first_and_last_bases_finely(tmp_path: Path) -> None:
    runs = "L\t0\t5\t0\nL\t5\t995\t40\nL\t995\t1000\t2\n"
    _write(
        tmp_path
        / f"variants/mapping-info/metrics/mosdepth/S1/{PREFIX}S1_LASVL-CONSTRAINT_constraint.per-base.bed.gz",
        runs,
        gz=True,
    )
    out = _run("nf-core/viralmetagenome/genome_ends.py", tmp_path, {})
    five = out.filter(pl.col("end_region") == "5' end").sort("start")
    three = out.filter(pl.col("end_region") == "3' end").sort("start")
    assert five.height == 20 and three.height == 20
    # First bin: 5 bases at 0X and 5 at 40X.
    assert five["mean_depth"][0] == 20.0
    assert five["end_offset"][0] == 5
    assert three["start"].to_list()[0] == 800
    # Last bin, read from the 3' tip inwards.
    assert three["mean_depth"][-1] == 21.0
    assert three["end_offset"][-1] == 5
    assert set(out["genome_id"]) == {"S1_LASVL"}


# ---------------------------------------------------------------------------
# Regressions
# ---------------------------------------------------------------------------


def test_split_multiallelic_records_read_alt_over_depth(tmp_path: Path) -> None:
    # One tri-allelic site after `norm --multiallelics -any`: each record's AD
    # holds the reference and its own allele only. Plus the `<*>` record
    # `call --keep-alts` writes, which is not a call.
    body = _VCF_HEAD + (
        "L\t50\t.\tC\tA\t90\t.\tDP=100\tGT:PL:DP:AD\t1:0,255:100:10,45\n"
        "L\t50\t.\tC\tG\t90\t.\tDP=100\tGT:PL:DP:AD\t1:0,255:100:10,45\n"
        "L\t60\t.\tC\t<*>\t0\t.\tDP=100\tGT:PL:DP:AD\t0:0,255:100:100,0\n"
    )
    name = f"{PREFIX}S1_L-CONSTRAINT_constraint"
    _write(tmp_path / f"variants/bcftools/S1/{name}.norm.vcf.gz", body, gz=True)
    _write(tmp_path / f"variants/bcftools/S1/{name}.filtered.vcf.gz", body, gz=True)
    calls = _run("nf-core/viralmetagenome/variants.py", tmp_path, {})
    assert calls["pos"].to_list() == [50, 50]
    assert calls["af"].to_list() == [0.45, 0.45]
    div = _run("nf-core/viralmetagenome/intrahost_diversity.py", tmp_path, {})
    row = div.row(0, named=True)
    assert row["minor_af"] == 0.45
    expected = -(2 * 0.45 * math.log(0.45) + 0.1 * math.log(0.1))
    assert row["entropy"] == pytest.approx(expected, abs=1e-3)


def test_a_run_prefix_holding_the_sample_name_is_stripped_first(tmp_path: Path) -> None:
    name = "lassa_20260916_1.2.0_run-lassa_L-CONSTRAINT_constraint"
    body = _VCF_HEAD + "L\t5\t.\tA\tG\t90\t.\tDP=20\tGT:PL:DP:AD\t1:0,255:20:0,20\n"
    _write(tmp_path / f"variants/bcftools/lassa/{name}.filtered.vcf.gz", body, gz=True)
    calls = _run("nf-core/viralmetagenome/variants.py", tmp_path, {})
    assert calls["genome_id"].to_list() == ["lassa_L"]
    assert calls["reference"].to_list() == ["L"]


def test_tracks_keep_a_reference_with_a_version(tmp_path: Path) -> None:
    bam = f"variants/mapping-info/deduplicate/bam/S1/{PREFIX}S1_MN908947.3-CONSTRAINT_constraint.dedup.sorted.bam"
    _touch(tmp_path, bam, bam + ".bai")
    hub = pl.DataFrame(
        {"genome_id": ["S1_MN908947.3"], "sample": ["S1"], "reference": ["MN908947.3"]}
    )
    out = _run("nf-core/viralmetagenome/tracks.py", tmp_path, {"genomes": hub})
    assert out["uri"].to_list() == [bam]


def test_genome_loci_halve_a_short_genome(tmp_path: Path) -> None:
    bins = pl.DataFrame({"genome_id": ["g"], "sample": ["S1"], "chrom": ["c"], "end": [300]})
    out = _run("nf-core/viralmetagenome/genome_loci.py", tmp_path, {"coverage_bins": bins})
    assert list(zip(out["start"], out["end"], strict=True)) == [(1, 300), (1, 150), (151, 300)]
