"""mosdepth file names carry the sample with or without a stage token.

sarek writes ``<sample>.<stage>.regions.bed.gz``; mosdepth's own default, which
methylseq, nanoseq, raredisease and circdna publish as is, is
``<prefix>.regions.bed.gz``. Both must yield a sample, or every row of a
single-token run carries a null key and every filter on it matches nothing.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.catalog.mosdepth.regions import NO_STAGE
from depictio.recipes import execute_recipe


def _regions(paths: list[str]) -> pl.DataFrame:
    rows = [(p, "chr1", "0", "1000", "30.0") for p in paths]
    return pl.DataFrame(
        rows, schema=["source_path", "chrom", "start", "end", "coverage"], orient="row"
    )


def _summary(paths: list[str]) -> pl.DataFrame:
    rows = [(p, "chr1", "1000", "30000", "30.0", "0", "60") for p in paths]
    return pl.DataFrame(
        rows,
        schema=["source_path", "chrom", "length", "bases", "mean", "min", "max"],
        orient="row",
    )


def test_regions_reads_both_spellings(tmp_path: Path) -> None:
    out = execute_recipe(
        "mosdepth/regions.py",
        tmp_path,
        extra_sources={
            "regions": _regions(["a/SAMPLE_A.regions.bed.gz", "b/NA12878.md.regions.bed.gz"])
        },
    ).sort("sample")
    assert out["sample"].to_list() == ["NA12878", "SAMPLE_A"]
    assert out["stage"].to_list() == ["md", NO_STAGE]
    assert out["sample_stage"].to_list() == ["NA12878 (md)", f"SAMPLE_A ({NO_STAGE})"]


def test_summary_reads_both_spellings(tmp_path: Path) -> None:
    out = execute_recipe(
        "mosdepth/summary.py",
        tmp_path,
        extra_sources={
            "summary": _summary(
                ["SAMPLE_A.mosdepth.summary.txt", "NA12878.recal.mosdepth.summary.txt"]
            )
        },
    ).sort("sample")
    assert out["sample"].to_list() == ["NA12878", "SAMPLE_A"]
    assert out["stage"].to_list() == ["recal", NO_STAGE]


def test_xy_check_names_the_columns_it_needs(tmp_path: Path) -> None:
    (tmp_path / "mosdepth-xy-coverage-plot.txt").write_text(
        "Sample\tchrX\tchrY\nS1.md\t30.0\t1.0\n"
    )
    with pytest.raises(ValueError, match="Chromosome X"):
        execute_recipe("mosdepth/xy_sex_check.py", tmp_path)
