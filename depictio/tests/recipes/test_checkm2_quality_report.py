"""CheckM2's own report name carries no ids; the bin name still does.

nf-core/mag republishes ``quality_report.tsv`` as
``<assembler>-<binner>-<refinement>-<sample>_checkm2_report.tsv`` and the recipe
reads the three ids off that name. On the plain spelling the name says nothing,
and the ids must come from the bin name instead of landing null on every row.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe


def _raw(path: str, names: list[str]) -> pl.DataFrame:
    n = len(names)
    return pl.DataFrame(
        {
            "Name": names,
            "Completeness": ["95.0", "60.0"][:n],
            "Contamination": ["1.0", "12.0"][:n],
            "Coding_Density": ["0.9"] * n,
            "Contig_N50": ["50000"] * n,
            "Genome_Size": ["3000000"] * n,
            "GC_Content": ["0.5"] * n,
            "Total_Coding_Sequences": ["3000"] * n,
            "Total_Contigs": ["100"] * n,
            "Max_Contig_Length": ["200000"] * n,
            "Completeness_Model_Used": ["Neural Network (Specific Model)"] * n,
            "source_path": [path] * n,
        }
    )


def test_plain_checkm2_spelling_takes_the_ids_from_the_bin_name(tmp_path: Path) -> None:
    raw = _raw(
        "run/checkm2/quality_report.tsv",
        ["METAMDBG-MetaBAT2-CAPES_S21.1", "FLYE-SemiBin2-CAPES_S11_10"],
    )
    out = execute_recipe("checkm2/quality_report.py", tmp_path, extra_sources={"reports": raw})
    out = out.sort("bin_id")

    assert out["assembler"].to_list() == ["FLYE", "METAMDBG"]
    assert out["binner"].to_list() == ["SemiBin2", "MetaBAT2"]
    assert out["sample"].to_list() == ["CAPES_S11", "CAPES_S21"]
    assert out["quality_tier"].to_list() == ["Contaminated", "High quality"]


def test_nf_core_spelling_still_reads_the_file_name(tmp_path: Path) -> None:
    raw = _raw(
        "run/METAMDBG-MetaBAT2-unclassified-unrefined-CAPES_S21_checkm2_report.tsv",
        ["METAMDBG-MetaBAT2-CAPES_S21.1"],
    )
    out = execute_recipe("checkm2/quality_report.py", tmp_path, extra_sources={"reports": raw})
    assert out.row(0, named=True)["sample"] == "CAPES_S21"
    assert out.row(0, named=True)["assembler"] == "METAMDBG"
