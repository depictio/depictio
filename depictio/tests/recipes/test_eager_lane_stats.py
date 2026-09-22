"""`nf-core/eager/lane_stats.py`: one row per lane, joined to the samplesheet.

When the samplesheet's R1 spelling does not reach a report, the recipe falls
back to the run accession. That fallback keeps one sheet row per accession, so
the lane must come from the report id itself or every lane of the accession
would read as the first one.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

RECIPE = "nf-core/eager/lane_stats.py"

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

    out = execute_recipe(RECIPE, tmp_path, extra_sources={"lanes": lanes}).sort("lane_id")

    assert out["sample_id"].to_list() == ["COD076E1bL1", "COD076E1bL1"]
    assert out["run_accession"].to_list() == ["ERR1943600", "ERR1943600"]
    assert out["lane"].to_list() == ["7", "8"]
    assert out["seq_type"].to_list() == ["PE", "PE"]
