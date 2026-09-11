"""Palette assignment for the complex-heatmap annotation strips.

Each annotation column used to enumerate its own value universe from index 0 of
the same palette, so on the chipseq consensus tile ``consensus_set=EZH2_IP`` and
``support=2`` both landed on ``#66c2a5`` and ``FOXA1_IP`` / ``3`` both on
``#fc8d62``. Two strips painted in the same colours in the same order read as
two views of one variable rather than two variables. The palette index has to
run across the columns, not restart within each.
"""

from __future__ import annotations

from depictio.api.v1.celery_tasks import _stable_palette_map

# Set2 pastel, as used for the row-annotation strips.
_PALETTE = [
    "#66c2a5",
    "#fc8d62",
    "#8da0cb",
    "#e78ac3",
    "#a6d854",
    "#ffd92f",
    "#e5c494",
    "#b3b3b3",
]


def test_two_annotation_columns_get_disjoint_colours() -> None:
    colors = _stable_palette_map(
        {"consensus_set": ["EZH2_IP", "FOXA1_IP"], "support": ["2", "3", "4"]},
        _PALETTE,
    )
    used_by_set = set(colors["consensus_set"].values())
    used_by_support = set(colors["support"].values())
    assert used_by_set.isdisjoint(used_by_support)
    # The regression, spelled out: these four pairs collided before.
    assert colors["consensus_set"]["EZH2_IP"] != colors["support"]["2"]
    assert colors["consensus_set"]["FOXA1_IP"] != colors["support"]["3"]


def test_the_offset_is_the_running_universe_size() -> None:
    colors = _stable_palette_map(
        {"consensus_set": ["EZH2_IP", "FOXA1_IP"], "support": ["2", "3", "4"]},
        _PALETTE,
    )
    assert colors["consensus_set"] == {"EZH2_IP": "#66c2a5", "FOXA1_IP": "#fc8d62"}
    assert colors["support"] == {"2": "#8da0cb", "3": "#e78ac3", "4": "#a6d854"}


def test_every_value_keeps_a_colour_once_the_palette_wraps() -> None:
    """More values than hues is a wrap, not a gap — the track must stay total."""
    universe = [f"v{i}" for i in range(12)]
    colors = _stable_palette_map({"a": universe}, _PALETTE)
    assert set(colors["a"]) == set(universe)
    assert colors["a"]["v8"] == _PALETTE[0]


def test_a_single_column_is_unchanged_by_the_offset() -> None:
    colors = _stable_palette_map({"habitat": ["Soil", "Water"]}, _PALETTE)
    assert colors["habitat"] == {"Soil": "#66c2a5", "Water": "#fc8d62"}


def test_no_columns_yields_no_colours() -> None:
    assert _stable_palette_map({}, _PALETTE) == {}
