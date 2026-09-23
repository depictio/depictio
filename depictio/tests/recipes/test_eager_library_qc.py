"""`nf-core/eager/library_qc.py`: one row per library from four tools' collections.

The endogenous collection sets the library list; the other three are optional
and left-joined, so a library a tool never saw keeps its row with nulls. The
fractions Picard, Qualimap and DamageProfiler write are turned into percents.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

RECIPE = "nf-core/eager/library_qc.py"


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
        RECIPE,
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
        RECIPE, tmp_path, extra_sources={"endogenous": _endogenous(), "dedup": dedup}
    )

    assert out.height == 2
    assert out.filter(pl.col("sample") == "LIB_B")["clonality_pct"].to_list() == [None]
    assert out["mean_coverage"].null_count() == 2
    assert out["ct_5p_first_pct"].dtype == pl.Float64
