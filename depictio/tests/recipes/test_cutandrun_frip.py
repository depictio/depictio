"""`cutandrun/frip.py`: the signal budget of a CUT&RUN library.

The interesting part is the spike-in correction. SEACR reads a bedGraph the
pipeline has already scaled, so the summed region signal is in scaled units
while the fragment histogram is in raw base pairs; the fraction only means
anything once the factor is divided back out. These tests pin that, plus the
long two-rows-per-sample shape the composition card reads.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.catalog.cutandrun.frip import IN_PEAKS, OUTSIDE_PEAKS
from depictio.recipes import execute_recipe

RECIPE = "cutandrun/frip.py"


def _fragments(sample: str = "s1", length: int = 100, count: int = 1_000) -> pl.DataFrame:
    """A one-bin histogram, so the total coverage is `length * count` exactly."""
    return pl.DataFrame(
        {
            "sample": [sample],
            "target": ["mark"],
            "fragment_length": [length],
            "count": [count],
            "fraction": [1.0],
            "cumulative_fraction": [1.0],
        }
    )


def _peaks(sample: str = "s1", total_signal: float = 50_000.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": [sample],
            "peak_id": [f"{sample}:chr1:0-1000"],
            "chr": ["chr1"],
            "start": [0],
            "end": [1_000],
            "total_signal": [total_signal],
        }
    )


def _factors(sample: str = "s1", scale_factor: float = 1.0) -> pl.DataFrame:
    return pl.DataFrame({"sample": [sample], "scale_factor": [scale_factor]})


def _sources(**over) -> dict[str, pl.DataFrame]:
    sources = {
        "fragments": _fragments(),
        "peaks": _peaks(),
        "factors": _factors(),
    }
    sources.update(over)
    return sources


def test_the_split_is_two_rows_that_sum_to_one(tmp_path: Path) -> None:
    # 1000 fragments of 100 bp = 100 000 bp of coverage; 50 000 of it in peaks.
    out = execute_recipe(RECIPE, tmp_path, extra_sources=_sources())

    assert out.height == 2
    assert out["signal_class"].to_list() == [IN_PEAKS, OUTSIDE_PEAKS]
    assert out["fragment_bp"].to_list() == [100_000.0, 100_000.0]
    assert out["coverage_bp"].to_list() == [50_000.0, 50_000.0]
    assert out["fraction"].sum() == pytest.approx(1.0)
    # The sample-level FRiP rides on both rows, so a card can gauge it.
    assert out["frip"].unique().to_list() == [0.5]


def test_the_spikein_factor_is_divided_back_out(tmp_path: Path) -> None:
    """A scaled bedGraph gives a scaled signal; without the correction the
    fraction is the factor rather than a fraction."""
    scaled = execute_recipe(
        RECIPE,
        tmp_path,
        extra_sources=_sources(
            peaks=_peaks(total_signal=500_000.0),
            factors=_factors(scale_factor=10.0),
        ),
    )
    assert scaled["frip"].unique().to_list() == [0.5]
    assert scaled["scale_factor"].unique().to_list() == [10.0]


def test_no_factor_collection_means_an_unscaled_bedgraph(tmp_path: Path) -> None:
    """`--skip_spikein_norm` is a real route: 1.0 is the honest identity."""
    out = execute_recipe(
        RECIPE,
        tmp_path,
        extra_sources={"fragments": _fragments(), "peaks": _peaks()},
    )
    assert out["scale_factor"].unique().to_list() == [1.0]
    assert out["frip"].unique().to_list() == [0.5]


def test_the_fraction_is_clipped_at_one(tmp_path: Path) -> None:
    """A peak set cannot hold more coverage than the library produced, so an
    imperfect factor degrades to a saturated split rather than to a fraction
    above 1."""
    out = execute_recipe(
        RECIPE,
        tmp_path,
        extra_sources=_sources(peaks=_peaks(total_signal=10_000_000.0)),
    )
    assert out["frip"].unique().to_list() == [1.0]
    outside = out.filter(pl.col("signal_class") == OUTSIDE_PEAKS)
    assert outside["coverage_bp"].to_list() == [0.0]


def test_a_sample_without_both_halves_is_dropped(tmp_path: Path) -> None:
    """The IgG controls have no peaks and no fragment histogram in a cutandrun
    run, so they must not appear with a zero or a null fraction."""
    fragments = pl.concat([_fragments("s1"), _fragments("igg")], how="vertical")
    out = execute_recipe(
        RECIPE,
        tmp_path,
        extra_sources=_sources(fragments=fragments),
    )
    assert out["sample"].unique().to_list() == ["s1"]
