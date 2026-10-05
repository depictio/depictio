"""The nanoseq Nx ladder recipe reads samtools stats RL rows into exact Nx rungs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import polars as pl

_RECIPE = (
    Path(__file__).resolve().parents[2] / "projects/nf-core/nanoseq/3.0.0/recipes/read_length_nx.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("read_length_nx", _RECIPE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nx_rungs_follow_the_bases_not_the_reads() -> None:
    recipe = _load()
    # 1 read of 1000 bp and 10 reads of 100 bp: 2000 bases, half in the long read.
    lines = ["SN\traw total sequences:\t11", "RL\t1000\t1", "RL\t100\t10", "COV\t[1-1]\t1\t5"]
    raw = pl.DataFrame({"raw_line": lines, "source_path": ["x/S1.sorted.bam.stats"] * len(lines)})
    out = recipe.transform({"raw": raw})

    assert dict(out.schema) == {k: v() for k, v in recipe.EXPECTED_SCHEMA.items()}
    assert out["sample"].unique().to_list() == ["S1"]
    assert out.height == 99
    by_rung = dict(zip(out["nx"].to_list(), out["read_length"].to_list(), strict=True))
    assert by_rung[10.0] == 1000.0
    assert by_rung[50.0] == 1000.0
    assert by_rung[51.0] == 100.0
    assert by_rung[99.0] == 100.0


def test_no_rl_rows_gives_an_empty_frame_with_the_schema() -> None:
    recipe = _load()
    raw = pl.DataFrame({"raw_line": ["SN\tx:\t1"], "source_path": ["S2.bam.stats"]})
    out = recipe.transform({"raw": raw})
    assert out.is_empty()
    assert list(out.columns) == list(recipe.EXPECTED_SCHEMA)
