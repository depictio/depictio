"""nf-core/eager recipes: lane stats, library QC and MAPQ across the reference."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

LANE_STATS_RECIPE = "nf-core/eager/lane_stats.py"

SHEET = (
    "Sample_Name\tLibrary_ID\tLane\tColour_Chemistry\tSeqType\tOrganism\tStrandedness\t"
    "UDG_Treatment\tR1\tR2\tBAM\n"
    "COD076\tCOD076E1bL1\t7\t4\tPE\thuman\tdouble\tnone\t"
    "s3://bucket/ERR1943600_R1.fastq.gz\ts3://bucket/ERR1943600_R2.fastq.gz\tNA\n"
    "COD076\tCOD076E1bL1\t8\t4\tPE\thuman\tdouble\tnone\t"
    "s3://bucket/ERR1943600_R1.fastq.gz\ts3://bucket/ERR1943600_R2.fastq.gz\tNA\n"
)


def _lanes(ids: list[str]) -> pl.DataFrame:
    """The adapterremoval_settings collection: `sample` plus the counts."""
    n = len(ids)
    return pl.DataFrame(
        {
            "sample": ids,
            "total_read_pairs": [1000] * n,
            "total_reads": [2000] * n,
            "discarded_reads": [100] * n,
            "collapsed_pairs": [600] * n,
            "retained_reads": [1300] * n,
            "retained_nucleotides": [65000] * n,
            "average_retained_length": [50.0] * n,
            "collapse_rate": [0.6] * n,
            "discard_rate": [0.05] * n,
        }
    )


def test_two_lanes_of_one_accession_keep_their_own_lane(tmp_path: Path) -> None:
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "benchmarking_vikingfish.tsv").write_text(SHEET)
    # The sheet spells R1 as `_R1`, the reports as `_1`: both lanes take the fallback.
    lanes = _lanes(["ERR1943600_1.fastq_L7", "ERR1943600_1.fastq_L8"])

    out = execute_recipe(LANE_STATS_RECIPE, tmp_path, extra_sources={"lanes": lanes}).sort(
        "lane_id"
    )

    assert out["sample_id"].to_list() == ["COD076E1bL1", "COD076E1bL1"]
    assert out["run_accession"].to_list() == ["ERR1943600", "ERR1943600"]
    assert out["lane"].to_list() == ["7", "8"]
    assert out["seq_type"].to_list() == ["PE", "PE"]


LIBRARY_QC_RECIPE = "nf-core/eager/library_qc.py"


def _endogenous() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": ["LIB_A", "LIB_B"],
            "endogenous_dna": [35.2, 36.2],
            "endogenous_dna_post": [23.5, 23.4],
            "endogenous_dna_loss": [11.7, 12.8],
            "off_target_pct": [64.8, 63.8],
        }
    )


def test_joins_and_scales_every_tool(tmp_path: Path) -> None:
    dedup = pl.DataFrame({"sample": ["LIB_A", "LIB_B"], "percent_duplication": [0.278, 0.16]})
    bamqc = pl.DataFrame(
        {
            "sample": ["LIB_A", "LIB_B"],
            "mean_coverage": [0.89, 0.99],
            "mean_mapping_quality": [35.7, 36.1],
            "general_error_rate": [0.0154, 0.01],
            "gc_percentage": [47.9, 50.1],
        }
    )
    damage = pl.DataFrame(
        {"sample": ["LIB_A", "LIB_B"], "ct_5p_first": [0.1436, 0.0593], "mean_length": [49.4, 48.8]}
    )

    out = execute_recipe(
        LIBRARY_QC_RECIPE,
        tmp_path,
        extra_sources={
            "endogenous": _endogenous(),
            "dedup": dedup,
            "bamqc": bamqc,
            "damage": damage,
        },
    )

    assert out["sample"].to_list() == ["LIB_A", "LIB_B"]
    assert out["clonality_pct"].to_list() == pytest.approx([27.8, 16.0])
    assert out["error_rate_pct"].to_list() == pytest.approx([1.54, 1.0])
    assert out["ct_5p_first_pct"].to_list() == pytest.approx([14.36, 5.93])
    assert out["mean_length"].to_list() == pytest.approx([49.4, 48.8])


def test_missing_tools_leave_nulls_not_gaps(tmp_path: Path) -> None:
    dedup = pl.DataFrame({"sample": ["LIB_A"], "percent_duplication": [0.2]})

    out = execute_recipe(
        LIBRARY_QC_RECIPE, tmp_path, extra_sources={"endogenous": _endogenous(), "dedup": dedup}
    )

    assert out.height == 2
    assert out.filter(pl.col("sample") == "LIB_B")["clonality_pct"].to_list() == [None]
    assert out["mean_coverage"].null_count() == 2
    assert out["ct_5p_first_pct"].dtype == pl.Float64


MAPQ_RECIPE = "nf-core/eager/mapq_across_reference.py"
DIR = "qualimap/LIB_A_rmdup_stats"


def _lines(path: str, lines: list[str]) -> pl.DataFrame:
    return pl.DataFrame({"raw": lines, "source_path": [path] * len(lines)})


def _windows() -> pl.DataFrame:
    return _lines(
        f"{DIR}/raw_data_qualimapReport/mapping_quality_across_reference.txt",
        ["500.0\t36.4", "1500.0\t35.9", "2500.0\t20.0"],
    )


def test_windows_land_on_their_contig(tmp_path: Path) -> None:
    reports = _lines(
        f"{DIR}/genome_results.txt",
        [
            ">>>>>>> Coverage per contig",
            "",
            "\tchr1\t2000\t1800\t0.9\t1.2",
            "\tchr2\t1000\t700\t0.7\t1.1",
        ],
    )

    out = execute_recipe(
        MAPQ_RECIPE, tmp_path, extra_sources={"windows": _windows(), "reports": reports}
    )

    assert out["sample"].unique().to_list() == ["LIB_A"]
    assert out["chromosome"].to_list() == ["chr1", "chr1", "chr2"]
    assert out["position"].to_list() == [500, 1500, 500]
    assert out["global_position"].to_list() == [500, 1500, 2500]
    assert out["mapping_quality"].to_list() == [36.4, 35.9, 20.0]


def test_without_the_contig_map_one_pseudo_contig(tmp_path: Path) -> None:
    out = execute_recipe(MAPQ_RECIPE, tmp_path, extra_sources={"windows": _windows()})

    assert out["chromosome"].unique().to_list() == ["genome"]
    assert out["position"].to_list() == out["global_position"].to_list()
