"""`bowtie2/spikein_factors.py`: two log sets in, one factor per sample out.

The recipe reads Bowtie 2's prose summary, so the tests here are mostly about
parsing: that the two log sets are told apart by the `.spikein.` infix and not
by a directory, that a paired-end and a single-end summary both yield an
aligned count, and that a library with no spike-in read gets a null factor
rather than an infinity.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.catalog.bowtie2.spikein_factors import NORMALISATION_C
from depictio.recipes import execute_recipe

RECIPE = "bowtie2/spikein_factors.py"


def _paired_log(total: int, unique: int, multi: int, rate: float) -> str:
    return (
        f"{total} reads; of these:\n"
        f"  {total} (100.00%) were paired; of these:\n"
        f"    {total - unique - multi} (11.08%) aligned concordantly 0 times\n"
        f"    {unique} (84.75%) aligned concordantly exactly 1 time\n"
        f"    {multi} (4.18%) aligned concordantly >1 times\n"
        f"{rate}% overall alignment rate\n"
    )


def _single_log(total: int, unique: int, multi: int, rate: float) -> str:
    return (
        f"{total} reads; of these:\n"
        f"  {total} (100.00%) were unpaired; of these:\n"
        f"    {total - unique - multi} (10.00%) aligned 0 times\n"
        f"    {unique} (80.00%) aligned exactly 1 time\n"
        f"    {multi} (10.00%) aligned >1 times\n"
        f"{rate}% overall alignment rate\n"
    )


def _raw(logs: dict[str, str]) -> pl.DataFrame:
    """The frame the raw scan DC builds: one line per row plus its file path."""
    rows = [
        {"line": line, "source_path": f"/run/02_alignment/bowtie2/{name}"}
        for name, text in logs.items()
        for line in text.splitlines()
    ]
    return pl.DataFrame(rows, schema={"line": pl.Utf8, "source_path": pl.Utf8})


def test_two_log_sets_become_one_row_per_sample(tmp_path: Path) -> None:
    raw = _raw(
        {
            "target/log/s1.bowtie2.log": _paired_log(1_000_000, 800_000, 40_000, 88.9),
            "spikein/log/s1.spikein.bowtie2.log": _paired_log(1_000_000, 240, 10, 0.03),
            "target/log/s2.bowtie2.log": _paired_log(500_000, 400_000, 20_000, 85.0),
            "spikein/log/s2.spikein.bowtie2.log": _paired_log(500_000, 1_000, 0, 0.2),
        }
    )
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"logs": raw})

    assert out.height == 2
    assert out["sample"].to_list() == ["s1", "s2"]

    s1 = out.filter(pl.col("sample") == "s1").row(0, named=True)
    assert s1["total_pairs"] == 1_000_000
    assert s1["target_aligned"] == 840_000
    assert s1["spikein_aligned"] == 250
    assert s1["scale_factor"] == pytest.approx(NORMALISATION_C / 250)
    assert s1["target_per_spikein"] == pytest.approx(840_000 / 250, rel=1e-3)
    assert s1["spikein_fraction"] == pytest.approx(250 / 1_000_000, abs=1e-6)


def test_the_target_log_is_not_matched_by_the_spikein_name(tmp_path: Path) -> None:
    """`<sample>.bowtie2.log` also matches `<sample>.spikein.bowtie2.log`.

    Without the explicit exclusion the spike-in file would be read a second
    time as a target log for a sample called `s1.spikein`, and the join would
    then be against the wrong depth.
    """
    raw = _raw(
        {
            "s1.bowtie2.log": _paired_log(100, 80, 4, 88.0),
            "s1.spikein.bowtie2.log": _paired_log(100, 5, 1, 6.0),
        }
    )
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"logs": raw})
    assert out["sample"].to_list() == ["s1"]
    assert out["target_aligned"].to_list() == [84]
    assert out["spikein_aligned"].to_list() == [6]


def test_single_end_summaries_are_read_too(tmp_path: Path) -> None:
    raw = _raw(
        {
            "s1.bowtie2.log": _single_log(1_000, 800, 100, 90.0),
            "s1.spikein.bowtie2.log": _single_log(1_000, 40, 10, 5.0),
        }
    )
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"logs": raw})
    assert out["target_aligned"].to_list() == [900]
    assert out["spikein_aligned"].to_list() == [50]
    assert out["scale_factor"].to_list() == [pytest.approx(NORMALISATION_C / 50)]


def test_a_library_with_no_spikein_read_gets_no_factor(tmp_path: Path) -> None:
    """Dividing by zero would print an infinity that dominates every mean."""
    raw = _raw(
        {
            "s1.bowtie2.log": _paired_log(1_000, 800, 40, 88.0),
            "s1.spikein.bowtie2.log": _paired_log(1_000, 0, 0, 0.0),
        }
    )
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"logs": raw})
    assert out["spikein_aligned"].to_list() == [0]
    assert out["scale_factor"].to_list() == [None]
    assert out["target_per_spikein"].to_list() == [None]


def test_a_run_without_spikein_logs_is_refused(tmp_path: Path) -> None:
    raw = _raw({"s1.bowtie2.log": _paired_log(1_000, 800, 40, 88.0)})
    with pytest.raises(Exception, match="spike-in"):
        execute_recipe(RECIPE, tmp_path, extra_sources={"logs": raw})
