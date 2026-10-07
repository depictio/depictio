"""E1 phasing in `cooltools/eigenvector.py`.

cooltools eigs-cis without a phasing track returns each chromosome's E1 with an
arbitrary sign, so two resolutions of one run can call the same bins A and B.
The recipe orients E1 so it correlates positively with bin coverage
(``1 / weight``); these tests pin that rule.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

RECIPE = "cooltools/eigenvector.py"


def _vecs(sample: str, resolution: int, chrom: str, e1: list[float], coverage: list[float]):
    n = len(e1)
    return pl.DataFrame(
        {
            "chrom": [chrom] * n,
            "start": [str(i * resolution) for i in range(n)],
            "end": [str((i + 1) * resolution) for i in range(n)],
            "weight": [str(1.0 / c) for c in coverage],
            "E1": [str(v) for v in e1],
            "E2": ["nan"] * n,
            "E3": [""] * n,
            "source_path": [f"compartments/{sample}.{resolution}_compartments.cis.vecs.tsv"] * n,
        }
    )


def _run(tmp_path: Path, *frames: pl.DataFrame) -> pl.DataFrame:
    return execute_recipe(RECIPE, tmp_path, extra_sources={"vecs": pl.concat(frames)})


def test_e1_is_flipped_when_it_anticorrelates_with_coverage(tmp_path: Path) -> None:
    coverage = [10.0, 12.0, 30.0, 32.0]
    out = _run(tmp_path, _vecs("S1", 500000, "chr1", [0.5, 0.4, -0.3, -0.6], coverage))
    assert out.get_column("E1").to_list() == [-0.5, -0.4, 0.3, 0.6]
    assert out.get_column("compartment").to_list() == ["B", "B", "A", "A"]


def test_two_resolutions_agree_on_the_same_bins(tmp_path: Path) -> None:
    coverage = [10.0, 30.0]
    fine = _vecs("S1", 250000, "chr2", [-0.2, -0.3, 0.4, 0.5], [10.0, 10.0, 30.0, 30.0])
    coarse = _vecs("S1", 500000, "chr2", [0.25, -0.45], coverage)
    out = _run(tmp_path, fine, coarse)
    fine_calls = out.filter(pl.col("resolution") == 250000).get_column("compartment").to_list()
    coarse_calls = out.filter(pl.col("resolution") == 500000).get_column("compartment").to_list()
    assert fine_calls == ["B", "B", "A", "A"]
    assert coarse_calls == ["B", "A"]


def test_masked_bins_stay_null_and_keep_the_sign_rule(tmp_path: Path) -> None:
    frame = _vecs("S1", 500000, "chr3", [0.5, 0.2, -0.4], [30.0, 20.0, 10.0]).with_columns(
        pl.when(pl.col("start") == "500000").then(pl.lit("nan")).otherwise(pl.col("E1")).alias("E1")
    )
    out = _run(tmp_path, frame)
    assert out.get_column("E1").to_list() == [0.5, None, -0.4]
    assert out.get_column("compartment").to_list() == ["A", None, "B"]
