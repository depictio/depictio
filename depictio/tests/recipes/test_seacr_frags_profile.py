"""`seacr/frags_profile.py`: fragment pile-up around the SEACR summits.

The recipe serves two tiles from one table (a metagene matrix keyed on
peak_id x offset and a coverage track keyed on chr x bin), so the tests pin
the bin arithmetic, the per-million scaling, and the non-maximum suppression
that keeps every genomic bin unique per sample.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.catalog.seacr.frags_profile import BIN_BP, HALF_WINDOW
from depictio.recipes import execute_recipe

RECIPE = "seacr/frags_profile.py"
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
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": frags, "peaks": peaks})

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
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": frags, "peaks": peaks})

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
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"fragments": frags, "peaks": peaks})

    assert out["sample"].unique().to_list() == ["a_R1"]
