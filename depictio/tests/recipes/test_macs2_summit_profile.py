"""`macs2/summit_profile.py`: the summit-centred aggregate of the peak calls.

The recipe has no read coverage to work from, only the narrowPeak intervals and
their summits, so the tests pin the two quantities it derives from them: the
share of a sample's calls covering each offset from their own summit, and the
other samples' summits counted around it (never the sample's own).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.catalog.macs2.summit_profile import BIN_BP, HALF_WINDOW_BP
from depictio.recipes import execute_recipe

RECIPE = "macs2/summit_profile.py"
N_BINS = 2 * HALF_WINDOW_BP // BIN_BP + 1


def _peaks(rows: list[tuple[str, str, int, int, int]]) -> pl.DataFrame:
    """`(sample, chr, start, end, summit)` in the macs2_peaks collection's shape."""
    return pl.DataFrame(
        {
            "sample": [r[0] for r in rows],
            "peak_id": [f"{r[0]}_peak_{i}" for i, r in enumerate(rows)],
            "chr": [r[1] for r in rows],
            "start": [r[2] for r in rows],
            "end": [r[3] for r in rows],
            "width": [r[3] - r[2] for r in rows],
            "summit": [r[4] for r in rows],
        }
    )


def _at(out: pl.DataFrame, sample: str, offset: int, column: str) -> float:
    return out.filter((pl.col("sample") == sample) & (pl.col("offset_bp") == offset))[column].item()


def test_one_row_per_sample_and_bin_centred_on_the_summit(tmp_path: Path) -> None:
    peaks = _peaks([("a", "chr1", 1_000, 1_200, 1_101), ("b", "chr1", 5_000, 5_100, 5_051)])
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"peaks": peaks})

    assert out.height == 2 * N_BINS
    offsets = out.filter(pl.col("sample") == "a")["offset_bp"].to_list()
    assert offsets[0] == -HALF_WINDOW_BP and offsets[-1] == HALF_WINDOW_BP
    assert 0 in offsets
    assert set(out["n_summits"].to_list()) == {1}


def test_footprint_is_the_share_of_calls_covering_each_offset(tmp_path: Path) -> None:
    # Summit base 0-based 1100 in [1000, 1200): covers -100 to +99.
    # Second call [2000, 2400) with summit base 2100: covers -100 to +299.
    peaks = _peaks([("a", "chr1", 1_000, 1_200, 1_101), ("a", "chr1", 2_000, 2_400, 2_101)])
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"peaks": peaks})

    assert _at(out, "a", 0, "peak_footprint") == 1.0
    assert _at(out, "a", -100, "peak_footprint") == 1.0
    assert _at(out, "a", 100, "peak_footprint") == 0.5
    assert _at(out, "a", 250, "peak_footprint") == 0.5
    assert _at(out, "a", 300, "peak_footprint") == 0.0
    assert _at(out, "a", -150, "peak_footprint") == 0.0


def test_neighbour_density_counts_other_samples_only(tmp_path: Path) -> None:
    peaks = _peaks(
        [
            ("a", "chr1", 900, 1_300, 1_101),
            # A second call of `a` 500 bp away: its own sample, never counted.
            ("a", "chr1", 1_400, 1_800, 1_601),
            # `b` agrees on the summit, `c` sits 500 bp downstream, `d` is on
            # another chromosome and must not count at all.
            ("b", "chr1", 1_000, 1_200, 1_101),
            ("c", "chr1", 1_550, 1_650, 1_601),
            ("d", "chr2", 1_000, 1_200, 1_101),
        ]
    )
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"peaks": peaks})

    per_kb = BIN_BP / 1000
    # Anchor 1100: b at 0, c at +500. Anchor 1600: b at -500, c at 0.
    # Two anchors, so each hit is 1 / 2 anchors / 0.05 kb.
    assert _at(out, "a", 0, "neighbour_summit_density") == pytest.approx(2 / 2 / per_kb)
    assert _at(out, "a", 500, "neighbour_summit_density") == pytest.approx(1 / 2 / per_kb)
    assert _at(out, "a", -500, "neighbour_summit_density") == pytest.approx(1 / 2 / per_kb)
    assert out.filter(pl.col("sample") == "a")["neighbour_summit_density"].sum() == pytest.approx(
        4 / 2 / per_kb
    )
    # `d` is alone on chr2.
    assert out.filter(pl.col("sample") == "d")["neighbour_summit_density"].sum() == 0.0


def test_an_empty_peak_table_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        execute_recipe(RECIPE, tmp_path, extra_sources={"peaks": _peaks([])})
