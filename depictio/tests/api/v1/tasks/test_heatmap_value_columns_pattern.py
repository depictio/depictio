"""Heatmap value columns named by pattern.

A template whose heatmap columns are one per sample of the run names them by
pattern, because a list written against one run fails on every other. The
consensus matrix such a pattern reads holds library-level and replicate-level
columns side by side, next to label and annotation columns, so these tests pin
that the pattern only ever picks numeric value columns, in frame order.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.celery_tasks import _resolve_heatmap_value_columns

LIBRARY = r"\.mLb\.clN$"
EXCLUDED = {"region", "support.mLb.clN"}


def _consensus() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "region": ["chr1:1-10", "chr1:20-30"],
            # A numeric row annotation whose name matches the pattern.
            "support.mLb.clN": [2, 1],
            # Frame order is deliberately not alphabetical.
            "T15_R1.mLb.clN": [1.5, 0.0],
            "T0_R1.mLb.clN": [2.0, 3.1],
            "T15.mRp.clN": [1.0, 0.0],
            # Matches the pattern by name but holds labels, so it is not a value column.
            "label.mLb.clN": ["a", "b"],
        }
    )


def _resolve(value_columns: list[str] | None, pattern: str | None) -> list[str]:
    return _resolve_heatmap_value_columns(_consensus(), value_columns, pattern, excluded=EXCLUDED)


def test_pattern_resolves_numeric_columns_in_frame_order() -> None:
    assert _resolve(None, LIBRARY) == ["T15_R1.mLb.clN", "T0_R1.mLb.clN"]


def test_pattern_matching_nothing_names_the_pattern() -> None:
    pattern = "^GM12878_"
    with pytest.raises(ValueError) as exc:
        _resolve(None, pattern)
    assert repr(pattern) in str(exc.value)
    assert "matches none" in str(exc.value)


def test_pattern_matching_only_non_value_columns_is_no_match() -> None:
    with pytest.raises(ValueError, match="matches none"):
        _resolve(None, r"^(label|support)\.")


def test_without_a_pattern_every_numeric_column_is_drawn() -> None:
    assert _resolve(None, None) == ["T15_R1.mLb.clN", "T0_R1.mLb.clN", "T15.mRp.clN"]


def test_a_list_passes_through() -> None:
    assert _resolve(["T15.mRp.clN"], None) == ["T15.mRp.clN"]


def test_list_and_pattern_together_are_rejected() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        _resolve(["T15.mRp.clN"], LIBRARY)
