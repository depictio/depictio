"""The two nf-core/mag assembly views built from the contig depth tables.

`nx_curve.py` reads contig lengths off the raw depth scan (header rows included
as data) and must agree with QUAST's N50 at x = 50; `assembly_recruitment.py`
pivots the per-contig depths into one column per read sample.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe


def _raw_depths(path: str, lengths: list[int]) -> pl.DataFrame:
    """A depth table as the scan reads it: no header, the header line as row one."""
    names = ["contigName", *[f"c{i}" for i in range(len(lengths))]]
    lens = ["contigLen", *[str(v) for v in lengths]]
    n = len(names)
    frame = {"f0": names, "f1": lens}
    for i in range(2, 9):
        frame[f"f{i}"] = ["x"] * n
    frame["source_path"] = [path] * n
    return pl.DataFrame(frame)


def test_nx_curve_matches_n50_and_drops_the_header_and_short_contigs(tmp_path: Path) -> None:
    raw = _raw_depths(
        "GenomeBinning/depths/contigs/MEGAHIT-CAPES_S7-depth.txt.gz",
        [100, 1000, 2000, 3000, 4000],
    )
    out = execute_recipe("nf-core/mag/nx_curve.py", tmp_path, extra_sources={"depths": raw})

    assert out.height == 101
    row = {r["nx"]: r for r in out.iter_rows(named=True)}
    # 100 bp is under the 500 bp floor: total is 10 000, N50 is the 3 kbp contig.
    assert row[50.0]["total_length"] == 10_000
    assert row[50.0]["contig_length"] == 3000
    assert row[50.0]["n_contigs"] == 2
    assert row[0.0]["contig_length"] == 4000
    assert row[100.0]["contig_length"] == 1000
    assert row[100.0]["n_contigs"] == 4
    assert out["assembler"].unique().to_list() == ["MEGAHIT"]
    assert out["sample"].unique().to_list() == ["CAPES_S7"]


def test_assembly_recruitment_is_one_column_per_read_sample(tmp_path: Path) -> None:
    depths = pl.DataFrame(
        {
            "assembly_id": ["SPAdes-S1"] * 4,
            "assembler": ["SPAdes"] * 4,
            "sample": ["S1"] * 4,
            "contig_id": ["a", "a", "b", "b"],
            "contig_length": [1000, 1000, 3000, 3000],
            "read_sample": ["S1", "S2", "S1", "S2"],
            "depth": [10.0, 0.0, 2.0, 4.0],
        }
    )
    out = execute_recipe(
        "nf-core/mag/assembly_recruitment.py", tmp_path, extra_sources={"depths": depths}
    )

    assert out.columns == ["assembly_id", "assembler", "sample", "S1", "S2"]
    # Length-weighted: (10*1000 + 2*3000) / 4000 and (0*1000 + 4*3000) / 4000.
    assert out.row(0, named=True)["S1"] == 4.0
    assert out.row(0, named=True)["S2"] == 3.0
