"""`recipes/lib/qualimap_raw.contig_coverage_block`, the one parser both coverage recipes read.

`qualimap/coverage_per_contig.py` needs all four numbers of a contig line;
`qualimap/coverage_across_reference.py` needs only the length, to rebuild the
offsets of the concatenated axis. One parser serves both, and the tests pin what
each does with a line that carries a length but no depth.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe
from depictio.recipes.lib.qualimap_raw import CONTIG_BLOCK_SCHEMA, contig_coverage_block

REPORT = "qualimap/COD076E1bL1_rmdup_stats/genome_results.txt"
WINDOWS = "qualimap/COD076E1bL1_rmdup_stats/raw_data_qualimapReport/coverage_across_reference.txt"

REPORT_LINES = [
    "BamQC report",
    ">>>>>>> Coverage",
    "     mean coverageData = 1.5X",
    ">>>>>>> Coverage per contig",
    "\tchr1\t1000\t1500\t1.5\t0.5",
    "\tchr2\t500\tNA\tNA\tNA",
    "\tchr3\t250\t750\t3.0\t1.0",
    ">>>>>>> Something after",
    "\tignored\t99\t99\t9.0\t9.0",
]


def _raw(lines: list[str], path: str) -> pl.DataFrame:
    return pl.DataFrame({"raw": lines, "source_path": [path] * len(lines)})


def test_the_block_is_read_in_file_order_with_nulls_for_missing_numbers() -> None:
    block = contig_coverage_block(_raw(REPORT_LINES, REPORT), recipe="t")

    assert block.schema == pl.Schema(CONTIG_BLOCK_SCHEMA)
    assert block["sample"].unique().to_list() == ["COD076E1bL1"]
    assert block["chromosome"].to_list() == ["chr1", "chr2", "chr3"]
    assert block["length"].to_list() == [1000, 500, 250]
    assert block["mean_coverage"].to_list() == [1.5, None, 3.0]


def test_per_contig_drops_the_contig_without_a_depth(tmp_path: Path) -> None:
    out = execute_recipe(
        "qualimap/coverage_per_contig.py",
        tmp_path,
        extra_sources={"lines": _raw(REPORT_LINES, REPORT)},
    )

    assert out["chromosome"].to_list() == ["chr1", "chr3"]
    # Genome mean is over the contigs kept: (1500 + 750) / (1000 + 250) = 1.8.
    assert out["relative_coverage"].to_list() == pytest.approx([1.5 / 1.8, 3.0 / 1.8])


def test_across_reference_keeps_that_contig_as_an_offset(tmp_path: Path) -> None:
    windows = _raw(
        ["#Position (bp)\tCoverage\tStd", "500.0\t1.0\t0.1", "1200.0\t2.0\t0.2"], WINDOWS
    )
    out = execute_recipe(
        "qualimap/coverage_across_reference.py",
        tmp_path,
        extra_sources={"windows": windows, "reports": _raw(REPORT_LINES, REPORT)},
    )

    # chr1 spans 0-1000, chr2 1000-1500 (kept for its length), chr3 from 1500.
    assert out["chromosome"].to_list() == ["chr1", "chr2"]
    assert out["position"].to_list() == [500, 200]
    assert out["global_position"].to_list() == [500, 1200]
