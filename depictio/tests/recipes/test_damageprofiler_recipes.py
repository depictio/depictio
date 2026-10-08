"""DamageProfiler recipes: the short-fragment cut-off of `authenticity.py` and the tolerant
length parsing of `lgdistribution.py`.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.catalog.damageprofiler.authenticity import (
    SHORT_FRAGMENT_BP,
    short_fragment_cutoff,
)
from depictio.recipes import execute_recipe

AUTHENTICITY_RECIPE = "damageprofiler/authenticity.py"


def _sources() -> dict[str, pl.DataFrame]:
    damage = pl.DataFrame(
        {
            "sample": ["L1"] * 4,
            "end": ["5p", "5p", "3p", "3p"],
            "position": [0, 0, 0, 0],
            "base_change": ["C>T", "other", "G>A", "other"],
            "frequency": [0.2, 0.01, 0.1, 0.01],
        }
    )
    # 10 fragments at 40 bp, 30 at 60 bp, 60 at 80 bp.
    lengths = pl.DataFrame(
        {"sample": ["L1"] * 3, "length": [40, 60, 80], "occurrences": [10, 30, 60]}
    )
    return {"damage": damage, "lengths": lengths}


def test_default_cutoff_is_70bp(tmp_path: Path) -> None:
    out = execute_recipe(AUTHENTICITY_RECIPE, tmp_path, extra_sources=_sources())
    assert out["fraction_under_70bp"].to_list() == pytest.approx([0.4])
    assert out["terminal_damage"].to_list() == pytest.approx([0.15])


def test_short_fragment_bp_param_sets_the_cutoff(tmp_path: Path) -> None:
    out = execute_recipe(
        AUTHENTICITY_RECIPE, tmp_path, extra_sources=_sources(), params={"short_fragment_bp": "50"}
    )
    # Schema unchanged: the column keeps its name, the value follows the param.
    assert "fraction_under_70bp" in out.columns
    assert out["fraction_under_70bp"].to_list() == pytest.approx([0.1])


def test_unresolved_or_bad_param_falls_back(tmp_path: Path) -> None:
    out = execute_recipe(
        AUTHENTICITY_RECIPE,
        tmp_path,
        extra_sources=_sources(),
        params={"short_fragment_bp": "{SHORT_FRAGMENT_BP}"},
    )
    assert out["fraction_under_70bp"].to_list() == pytest.approx([0.4])
    for bad in ("", "abc", "0", "-5"):
        assert short_fragment_cutoff({"short_fragment_bp": bad}) == SHORT_FRAGMENT_BP
    assert short_fragment_cutoff(None) == SHORT_FRAGMENT_BP
    assert short_fragment_cutoff({"short_fragment_bp": "100"}) == 100


LGDISTRIBUTION_RECIPE = "damageprofiler/lgdistribution.py"
PATH = "damageprofiler/COD076E1bL1_rmdup/lgdistribution.txt"


def _raw(rows: list[tuple[str, str, str]]) -> pl.DataFrame:
    """The scanned table as text columns, the way a mixed-content scan lands."""
    return pl.DataFrame(
        {
            "Std": [r[0] for r in rows],
            "Length": [r[1] for r in rows],
            "Occurrences": [r[2] for r in rows],
            "source_path": [PATH] * len(rows),
        }
    )


def test_a_nan_length_or_na_count_costs_its_row_only(tmp_path: Path) -> None:
    raw = _raw(
        [
            ("+", "30", "60"),
            ("+", "nan", "5"),
            ("+", "31", "NA"),
            ("+", "32", "40"),
            ("-", "30", "10"),
        ]
    )
    out = execute_recipe(LGDISTRIBUTION_RECIPE, tmp_path, extra_sources={"lengths": raw})

    assert out["sample"].unique().to_list() == ["COD076E1bL1"]
    plus = out.filter(pl.col("strand") == "+")
    assert plus["length"].to_list() == [30, 32]
    assert plus["occurrences"].to_list() == [60, 40]
    assert plus["fraction"].to_list() == pytest.approx([0.6, 0.4])
    assert out.filter(pl.col("strand") == "-")["fraction"].to_list() == [1.0]
    assert out["series"].unique().sort().to_list() == ["COD076E1bL1 (+)", "COD076E1bL1 (-)"]
