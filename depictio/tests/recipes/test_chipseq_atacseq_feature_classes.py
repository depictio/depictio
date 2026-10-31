"""`nf-core/{chipseq,atacseq}/feature_classes.py`: peaks per library and HOMER class.

The recipe counts the per-peak HOMER annotation into the long form the
`stacked_taxonomy` tile reads, one row per library and feature class.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

PIPELINES = ["chipseq", "atacseq"]


def _annotation() -> pl.DataFrame:
    rows = [
        ("a", "promoter-TSS"),
        ("a", "promoter-TSS"),
        ("a", "intron"),
        ("a", None),
        ("b", "intron"),
        ("b", ""),
    ]
    return pl.DataFrame(
        {
            "sample": [r[0] for r in rows],
            "annotation_class": [r[1] for r in rows],
        }
    )


@pytest.mark.parametrize("pipeline", PIPELINES)
def test_counts_peaks_per_library_and_class(pipeline: str, tmp_path: Path) -> None:
    out = execute_recipe(
        f"nf-core/{pipeline}/feature_classes.py",
        tmp_path,
        extra_sources={"peaks": _annotation()},
    )
    assert out.columns == ["sample", "annotation_class", "peak_count", "rank"]
    assert out["rank"].unique().to_list() == ["Feature class"]
    assert out.schema["peak_count"] == pl.Int64
    got = {(r["sample"], r["annotation_class"]): r["peak_count"] for r in out.to_dicts()}
    assert got == {
        ("a", "promoter-TSS"): 2,
        ("a", "intron"): 1,
        ("a", "Unclassified"): 1,
        ("b", "intron"): 1,
        ("b", "Unclassified"): 1,
    }


@pytest.mark.parametrize("pipeline", PIPELINES)
def test_every_peak_is_counted_once(pipeline: str, tmp_path: Path) -> None:
    out = execute_recipe(
        f"nf-core/{pipeline}/feature_classes.py",
        tmp_path,
        extra_sources={"peaks": _annotation()},
    )
    assert out["peak_count"].sum() == _annotation().height
