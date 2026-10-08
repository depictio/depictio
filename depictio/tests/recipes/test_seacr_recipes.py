"""SEACR recipes: the nucleosome binning of the fragment ladder and the fragment pile-up around
the summits.
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
from depictio.catalog.seacr.frags_profile import BIN_BP, HALF_WINDOW
from depictio.recipes import execute_recipe

CLASSES_RECIPE = "seacr/fragment_classes.py"


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
    out = execute_recipe(CLASSES_RECIPE, tmp_path, extra_sources={"fragments": ladder})

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
    out = execute_recipe(CLASSES_RECIPE, tmp_path, extra_sources={"fragments": ladder})

    assert out.height == 4
    empty = out.filter(pl.col("fragment_class") == DINUCLEOSOMAL)
    assert empty["n_fragments"].to_list() == [0]
    assert empty["fraction"].to_list() == [0.0]
    assert out["fraction"].sum() == pytest.approx(1.0)


def test_the_class_median_is_weighted_by_the_histogram(tmp_path: Path) -> None:
    """A histogram bin is many fragments, so the median is not the middle bin."""
    ladder = _ladder([("s1", 130, 1), ("s1", 200, 98), ("s1", 240, 1)])
    out = execute_recipe(CLASSES_RECIPE, tmp_path, extra_sources={"fragments": ladder})

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
    out = execute_recipe(CLASSES_RECIPE, tmp_path, extra_sources={"fragments": ladder})

    ratios = {
        row["sample"]: row["mono_to_sub"]
        for row in out.unique(subset="sample").iter_rows(named=True)
    }
    assert ratios["sharp_R1"] == pytest.approx(0.25)
    assert ratios["broad_R1"] == pytest.approx(9.0)


def test_a_sample_with_no_sub_nucleosomal_fragments_has_no_ratio(tmp_path: Path) -> None:
    ladder = _ladder([("s1", 200, 100)])
    out = execute_recipe(CLASSES_RECIPE, tmp_path, extra_sources={"fragments": ladder})
    assert out["mono_to_sub"].unique().to_list() == [None]


def test_a_padded_class_takes_the_samples_real_target(tmp_path: Path) -> None:
    """The cross join pads the missing classes with null targets; the fill
    must reach past them to the sample's first real one."""
    ladder = _ladder([("s1_R1", 100, 10), ("s1_R1", 200, 30)])
    out = execute_recipe(CLASSES_RECIPE, tmp_path, extra_sources={"fragments": ladder})
    assert out["target"].to_list() == ["s1"] * 4


def test_the_sample_median_is_weighted_by_fragments_not_by_rows(tmp_path: Path) -> None:
    # Three lengths, but most fragments are short: the row median (the middle of
    # the x axis) would be 300, the fragment median is 100.
    ladder = _ladder([("s1", 100, 8), ("s1", 300, 1), ("s1", 500, 1), ("s2", 200, 1)])
    out = execute_recipe(CLASSES_RECIPE, tmp_path, extra_sources={"fragments": ladder})

    medians = dict(zip(out["sample"].to_list(), out["sample_median_length"].to_list()))
    assert medians == {"s1": 100.0, "s2": 200.0}
    # Repeated on each of the four class rows, so a card weighs every sample once.
    assert out.group_by("sample").len()["len"].to_list() == [4, 4]


PROFILE_RECIPE = "seacr/frags_profile.py"
N_BINS = 2 * (HALF_WINDOW // BIN_BP) + 1


def _frags(sample: str, rows: list[tuple[str, int, int]]) -> pl.DataFrame:
    """Raw scan shape: chr/start/end as text plus the source path."""
    return pl.DataFrame(
        {
            "chr": [r[0] for r in rows],
            "start": [str(r[1]) for r in rows],
            "end": [str(r[2]) for r in rows],
            "source_path": [f"/run/06_fragments_from_bams/{sample}.frags.cut.bed"] * len(rows),
        }
    )


def _peaks(rows: list[tuple[str, str, int, float]]) -> pl.DataFrame:
    """(sample, chr, summit, total_signal) in the seacr_peaks shape."""
    return pl.DataFrame(
        {
            "sample": [r[0] for r in rows],
            "peak_id": [f"{r[0]}:{r[1]}:{r[2]}" for r in rows],
            "chr": [r[1] for r in rows],
            "summit": [r[2] for r in rows],
            "total_signal": [r[3] for r in rows],
        }
    )


def test_fragments_land_in_the_bins_they_overlap(tmp_path: Path) -> None:
    # Summit at 10_050 -> centre bin 10_000..10_100. One fragment spans the
    # centre bin and the next one, a second sits 1 kb downstream.
    frags = _frags("h3k4me3_R1", [("chr1", 10_020, 10_180), ("chr1", 11_010, 11_090)])
    peaks = _peaks([("h3k4me3_R1", "chr1", 10_050, 5.0)])
    out = execute_recipe(
        PROFILE_RECIPE, tmp_path, extra_sources={"fragments": frags, "peaks": peaks}
    )

    assert out.height == N_BINS
    hit = dict(zip(out["offset_bp"].to_list(), out["fragments"].to_list()))
    assert hit[0] == 1 and hit[BIN_BP] == 1 and hit[1000] == 1
    assert sum(hit.values()) == 3
    centre = out.filter(pl.col("offset_bp") == 0).row(0, named=True)
    assert (centre["bin_start"], centre["bin_end"]) == (10_000, 10_100)
    # Two fragments in the library: one fragment in a bin is half a million per million.
    assert centre["cpm"] == 500_000.0
    assert centre["target"] == "h3k4me3"


def test_overlapping_windows_keep_only_the_stronger_region(tmp_path: Path) -> None:
    frags = _frags("s_R1", [("chr1", 50_000, 50_100)])
    peaks = _peaks(
        [
            ("s_R1", "chr1", 50_000, 10.0),
            ("s_R1", "chr1", 52_000, 99.0),  # stronger, 2 kb away: wins
            ("s_R1", "chr1", 80_000, 1.0),  # far enough: kept
        ]
    )
    out = execute_recipe(
        PROFILE_RECIPE, tmp_path, extra_sources={"fragments": frags, "peaks": peaks}
    )

    ranks = out.select("peak_id", "peak_rank").unique().sort("peak_rank")
    assert ranks["peak_id"].to_list() == ["s_R1:chr1:52000", "s_R1:chr1:80000"]
    # Every genomic bin appears once per sample, so a coverage track over the
    # same rows never draws a bin twice.
    assert out.group_by("sample", "chr", "bin_start").len()["len"].max() == 1


def test_a_sample_without_peaks_is_left_out(tmp_path: Path) -> None:
    frags = pl.concat(
        [_frags("a_R1", [("chr2", 100, 200)]), _frags("igg_R1", [("chr2", 100, 200)])]
    )
    peaks = _peaks([("a_R1", "chr2", 150, 1.0)])
    out = execute_recipe(
        PROFILE_RECIPE, tmp_path, extra_sources={"fragments": frags, "peaks": peaks}
    )

    assert out["sample"].unique().to_list() == ["a_R1"]
