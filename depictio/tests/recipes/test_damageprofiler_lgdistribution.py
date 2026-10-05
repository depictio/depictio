"""`damageprofiler/lgdistribution.py`: a length row that is not a number is dropped, not fatal."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

RECIPE = "damageprofiler/lgdistribution.py"
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
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"lengths": raw})

    assert out["sample"].unique().to_list() == ["COD076E1bL1"]
    plus = out.filter(pl.col("strand") == "+")
    assert plus["length"].to_list() == [30, 32]
    assert plus["occurrences"].to_list() == [60, 40]
    assert plus["fraction"].to_list() == pytest.approx([0.6, 0.4])
    assert out.filter(pl.col("strand") == "-")["fraction"].to_list() == [1.0]
    assert out["series"].unique().sort().to_list() == ["COD076E1bL1 (+)", "COD076E1bL1 (-)"]
