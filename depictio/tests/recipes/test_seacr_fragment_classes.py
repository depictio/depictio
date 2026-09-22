"""`seacr/fragment_classes.py`: the nucleosome binning of the fragment ladder.

The recipe collapses a 600-point histogram into four classes, so the tests pin
the boundaries, the weighted median inside a class, the ratio that contrasts a
sharp mark against a broad one, and the rule that an empty class keeps its row.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.catalog.seacr.fragment_classes import (
    DINUCLEOSOMAL,
    MONONUCLEOSOMAL,
    MULTINUCLEOSOMAL,
    SUB_NUCLEOSOMAL,
)
from depictio.recipes import execute_recipe

RECIPE = "seacr/fragment_classes.py"


def _ladder(rows: list[tuple[str, int, int]]) -> pl.DataFrame:
    """`(sample, fragment_length, count)` in the tidy collection's shape."""
    return pl.DataFrame(
        {
            "sample": [r[0] for r in rows],
            "target": [r[0].rsplit("_R", 1)[0] for r in rows],
            "fragment_length": [r[1] for r in rows],
            "count": [r[2] for r in rows],
            "fraction": [0.0] * len(rows),
            "cumulative_fraction": [0.0] * len(rows),
        }
    )


def test_the_boundaries_are_the_conventional_mnase_ones(tmp_path: Path) -> None:
    # One fragment on each side of every cut point.
    ladder = _ladder(
        [
            ("s1", 119, 1),  # sub-nucleosomal, last bp
            ("s1", 120, 1),  # mononucleosomal, first bp
            ("s1", 250, 1),  # mononucleosomal, last bp
            ("s1", 251, 1),  # dinucleosomal, first bp
            ("s1", 450, 1),  # dinucleosomal, last bp
            ("s1", 451, 1),  # multi-nucleosomal, first bp
        ]
    )
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": ladder})

    counts = dict(zip(out["fragment_class"].to_list(), out["n_fragments"].to_list()))
    assert counts == {
        SUB_NUCLEOSOMAL: 1,
        MONONUCLEOSOMAL: 2,
        DINUCLEOSOMAL: 2,
        MULTINUCLEOSOMAL: 1,
    }
    # class_order sorts the stacked bar by length, not alphabetically.
    assert out["class_order"].to_list() == [1, 2, 3, 4]


def test_an_empty_class_keeps_its_row(tmp_path: Path) -> None:
    """A library with no dinucleosomal fragments is a finding, not a gap."""
    ladder = _ladder([("s1", 100, 10), ("s1", 200, 30)])
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": ladder})

    assert out.height == 4
    empty = out.filter(pl.col("fragment_class") == DINUCLEOSOMAL)
    assert empty["n_fragments"].to_list() == [0]
    assert empty["fraction"].to_list() == [0.0]
    assert out["fraction"].sum() == pytest.approx(1.0)


def test_the_class_median_is_weighted_by_the_histogram(tmp_path: Path) -> None:
    """A histogram bin is many fragments, so the median is not the middle bin."""
    ladder = _ladder([("s1", 130, 1), ("s1", 200, 98), ("s1", 240, 1)])
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": ladder})

    mono = out.filter(pl.col("fragment_class") == MONONUCLEOSOMAL)
    assert mono["median_length"].to_list() == [200.0]


def test_the_ratio_contrasts_a_sharp_mark_against_a_broad_one(tmp_path: Path) -> None:
    ladder = _ladder(
        [
            # Sharp: mostly sub-nucleosomal.
            ("sharp_R1", 80, 80),
            ("sharp_R1", 200, 20),
            # Broad: mostly mononucleosomal.
            ("broad_R1", 80, 10),
            ("broad_R1", 200, 90),
        ]
    )
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": ladder})

    ratios = {
        row["sample"]: row["mono_to_sub"]
        for row in out.unique(subset="sample").iter_rows(named=True)
    }
    assert ratios["sharp_R1"] == pytest.approx(0.25)
    assert ratios["broad_R1"] == pytest.approx(9.0)


def test_a_sample_with_no_sub_nucleosomal_fragments_has_no_ratio(tmp_path: Path) -> None:
    ladder = _ladder([("s1", 200, 100)])
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": ladder})
    assert out["mono_to_sub"].unique().to_list() == [None]


def test_a_padded_class_takes_the_samples_real_target(tmp_path: Path) -> None:
    """The cross join pads the missing classes with null targets; the fill
    must reach past them to the sample's first real one."""
    ladder = _ladder([("s1_R1", 100, 10), ("s1_R1", 200, 30)])
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": ladder})
    assert out["target"].to_list() == ["s1"] * 4
