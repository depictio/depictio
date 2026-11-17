"""nf-core/rnaseq general_stats: `pct_trimmed` from MultiQC's trim_galore module.

rnaseq 3.28's MultiQC reports Trim Galore with its own module: the general
stats lose `cutadapt-percent_trimmed`, and the share of bases trimmed has to
come from `multiqc_trim_galore.txt` (bp written over bp processed, per read
file, averaged per library).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import polars as pl
import pytest

_RECIPE = (
    Path(__file__).resolve().parents[2]
    / "projects"
    / "nf-core"
    / "rnaseq"
    / "recipes"
    / "general_stats.py"
)


@pytest.fixture(scope="module")
def recipe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rnaseq_general_stats", _RECIPE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stats(rows: list[dict[str, str]]) -> pl.DataFrame:
    return pl.DataFrame(rows).cast(pl.Utf8)


def test_cutadapt_reports_keep_their_own_share(recipe: ModuleType) -> None:
    stats = _stats([{"Sample": "ctrl_REP1", "cutadapt-percent_trimmed": "2.5"}])
    out = recipe.transform({"stats": stats})
    assert out["pct_trimmed"].to_list() == [2.5]


def test_trim_galore_reports_compute_it_per_read_file(recipe: ModuleType) -> None:
    stats = _stats(
        [
            {"Sample": "ctrl_1", "trim_galore-tg_pct_with_adapter": "30"},
            {"Sample": "ctrl_1_1", "trim_galore-tg_pct_with_adapter": "29"},
            {"Sample": "ctrl_1_2", "trim_galore-tg_pct_with_adapter": "31"},
            {"Sample": "wt", "trim_galore-tg_pct_with_adapter": "20"},
        ]
    )
    trim_galore = _stats(
        [
            # a library itself named `ctrl_1`: its read files are ctrl_1_1/_2
            {"Sample": "ctrl_1_1", "total_bp_processed": "1000", "total_bp_written": "980"},
            {"Sample": "ctrl_1_2", "total_bp_processed": "1000", "total_bp_written": "960"},
            {"Sample": "wt", "total_bp_processed": "2000", "total_bp_written": "1900"},
            {"Sample": "elsewhere", "total_bp_processed": "10", "total_bp_written": "1"},
        ]
    )
    out = recipe.transform({"stats": stats, "trim_galore": trim_galore})
    got = dict(zip(out["sample"].to_list(), out["pct_trimmed"].to_list(), strict=True))
    assert got == pytest.approx({"ctrl_1": 3.0, "wt": 5.0})


def test_without_the_trim_galore_file_the_share_stays_null(recipe: ModuleType) -> None:
    stats = _stats([{"Sample": "wt", "trim_galore-tg_pct_with_adapter": "20"}])
    out = recipe.transform({"stats": stats})
    assert out["pct_trimmed"].to_list() == [None]
