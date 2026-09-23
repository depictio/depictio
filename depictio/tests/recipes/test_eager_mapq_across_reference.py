"""`nf-core/eager/mapq_across_reference.py`: MAPQ windows placed on their contig.

Qualimap writes the window centre on the concatenated reference. With the
`Coverage per contig` block of genome_results.txt the recipe subtracts each
contig's start offset, so the column names and coordinates match the depth
collection the Coverage tab's locus navigator emits its region on.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

RECIPE = "nf-core/eager/mapq_across_reference.py"
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
        RECIPE, tmp_path, extra_sources={"windows": _windows(), "reports": reports}
    )

    assert out["sample"].unique().to_list() == ["LIB_A"]
    assert out["chromosome"].to_list() == ["chr1", "chr1", "chr2"]
    assert out["position"].to_list() == [500, 1500, 500]
    assert out["global_position"].to_list() == [500, 1500, 2500]
    assert out["mapping_quality"].to_list() == [36.4, 35.9, 20.0]


def test_without_the_contig_map_one_pseudo_contig(tmp_path: Path) -> None:
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"windows": _windows()})

    assert out["chromosome"].unique().to_list() == ["genome"]
    assert out["position"].to_list() == out["global_position"].to_list()
