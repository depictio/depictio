"""Set columns named by pattern, and rows that fall outside every drawn set.

A template whose sets are one column per sample of the run names them by
pattern, because a list written against one run fails on every other. The
consensus matrix such a pattern reads can hold two consensus sets side by side,
so the rows of the set the pattern leaves out are all-zero across the drawn
columns, and plotly-upset draws those as a degree-0 bar. These tests pin the
resolution and that such rows never reach the plot.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.celery_tasks import (
    _narrow_wide_matrix_columns,
    _resolve_upset_set_columns,
    _upset_result_from_frame,
)

LIBRARY = r"\.mLb\.clN$"
_BINARY = ["T15_R1.mLb.clN", "T0_R1.mLb.clN", "T15.mRp.clN", "T0.mRp.clN"]


def _consensus() -> pl.DataFrame:
    """Library-level rows set only `.mLb.clN` columns, replicate-level rows only `.mRp.clN`."""
    return pl.DataFrame(
        {
            "peak_id": ["lib:1", "lib:2", "lib:3", "rep:1", "rep:2"],
            "consensus_set": ["lib", "lib", "lib", "rep", "rep"],
            "start": [100, 200, 300, 100, 400],
            "num_samples": [2, 1, 2, 1, 2],
            # Matches the pattern by name but counts peaks, so it is not a set.
            "merged.mLb.clN": [3, 1, 2, 4, 5],
            # Frame order is deliberately not alphabetical.
            "T15_R1.mLb.clN": [1, 0, 1, 0, 0],
            "T0_R1.mLb.clN": [1, 1, 0, 0, 0],
            "T15.mRp.clN": [0, 0, 0, 0, 1],
            "T0.mRp.clN": [0, 0, 0, 1, 1],
        }
    ).with_columns(pl.col(_BINARY).cast(pl.Int8))


def _figure(df: pl.DataFrame, set_columns: list[str] | None) -> dict:
    return _upset_result_from_frame(
        df,
        set_columns=set_columns,
        sort_by="cardinality",
        sort_order="descending",
        min_size=1,
        max_degree=None,
        show_set_sizes=True,
        show_values=False,
        color_intersections_by="none",
        set_colors=None,
        annotation_cols=[],
    )


def _intersection_sizes(result: dict) -> list[int]:
    bars = [
        t
        for t in result["figure"]["data"]
        if t.get("type") == "bar" and t.get("name") == "Intersection Size"
    ]
    assert len(bars) == 1
    return [int(v) for v in bars[0]["y"]]


def test_pattern_resolves_binary_columns_in_frame_order() -> None:
    assert _resolve_upset_set_columns(_consensus(), None, LIBRARY) == [
        "T15_R1.mLb.clN",
        "T0_R1.mLb.clN",
    ]


def test_pattern_matching_nothing_names_the_pattern() -> None:
    pattern = "^GM12878_"
    with pytest.raises(ValueError) as exc:
        _resolve_upset_set_columns(_consensus(), None, pattern)
    assert repr(pattern) in str(exc.value)
    assert "matches none" in str(exc.value)


def test_pattern_matching_only_non_binary_columns_is_no_match() -> None:
    with pytest.raises(ValueError, match="matches none"):
        _resolve_upset_set_columns(_consensus(), None, r"^merged\.")


def test_without_a_pattern_set_columns_pass_through() -> None:
    assert _resolve_upset_set_columns(_consensus(), None, None) is None
    assert _resolve_upset_set_columns(_consensus(), ["T0.mRp.clN"], None) == ["T0.mRp.clN"]


def test_list_and_pattern_together_are_rejected() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        _resolve_upset_set_columns(_consensus(), ["T0.mRp.clN"], LIBRARY)


def test_narrowing_applies_to_the_resolved_sets() -> None:
    sets = _resolve_upset_set_columns(_consensus(), None, LIBRARY)
    filters = [{"column_name": "sample", "value": ["T0_R1.mLb.clN"]}]
    assert _narrow_wide_matrix_columns(sets, filters) == ["T0_R1.mLb.clN"]


def test_rows_outside_every_drawn_set_are_dropped() -> None:
    df = _consensus()
    result = _figure(df, _resolve_upset_set_columns(df, None, LIBRARY))
    # The two replicate-level rows are all-zero over the library columns; kept,
    # they would add a degree-0 bar of size 2.
    assert result["row_count"] == 3
    assert sum(_intersection_sizes(result)) == 3


def test_sets_covering_every_row_keep_every_row() -> None:
    result = _figure(_consensus(), _BINARY)
    assert result["row_count"] == 5
    assert sum(_intersection_sizes(result)) == 5


def _annotated(frame: pl.DataFrame, **kwargs) -> dict:
    return _upset_result_from_frame(
        frame,
        set_columns=["S1", "S2", "S3"],
        sort_by="cardinality",
        sort_order="descending",
        min_size=1,
        max_degree=None,
        show_set_sizes=True,
        show_values=False,
        color_intersections_by="none",
        set_colors=None,
        annotation_cols=["phylum"],
        **kwargs,
    )


def _phylum_frame(counts: dict[str, int]) -> pl.DataFrame:
    phyla = [p for p, n in counts.items() for _ in range(n)]
    n = len(phyla)
    return pl.DataFrame(
        {
            "phylum": phyla,
            "S1": [1] * n,
            "S2": [i % 2 for i in range(n)],
            "S3": [(i // 2) % 2 for i in range(n)],
        }
    ).with_columns(pl.col(["S1", "S2", "S3"]).cast(pl.Int8))


def _track_colours(result: dict) -> dict[str, str]:
    """``{category: colour}`` of the ``phylum`` track's legend bars."""
    return {
        t["name"].removeprefix("phylum: "): t["marker"]["color"]
        for t in result["figure"]["data"]
        if t.get("type") == "bar" and str(t.get("name", "")).startswith("phylum: ")
    }


def test_annotation_track_colours_follow_frequency_rank() -> None:
    from depictio.models.palette_tracks import track_palette

    result = _annotated(_phylum_frame({"A": 2, "B": 9, "C": 5}))
    colours = _track_colours(result)
    palette = track_palette("sets")
    assert [colours["B"], colours["C"], colours["A"]] == palette[:3]


def test_annotation_tail_folds_into_other() -> None:
    from depictio.models import palettes
    from depictio.models.palette_tracks import track_palette

    counts = {f"P{i}": 20 - i for i in range(10)} | {"Unclassified": 3}
    colours = _track_colours(_annotated(_phylum_frame(counts)))
    slots = len(track_palette("sets"))
    assert {f"P{i}" for i in range(slots)} <= set(colours)
    assert {f"P{i}" for i in range(slots, 10)}.isdisjoint(colours)
    assert colours["Other"] == palettes.semantic("other")
    assert colours["Unclassified"] == palettes.semantic("unclassified")
    assert len(colours) == slots + 2


def test_annotation_pins_win_and_match_the_column_case_insensitively() -> None:
    frame = _phylum_frame({"A": 2, "B": 9, "C": 5})
    result = _annotated(frame, category_colors={"Phylum": {"A": "#123456"}})
    assert _track_colours(result)["A"] == "#123456"
