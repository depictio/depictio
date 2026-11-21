"""Palette assignment for the complex-heatmap annotation strips.

Each annotation column used to enumerate its own value universe from index 0 of
the same palette, so on the chipseq consensus tile ``consensus_set=EZH2_IP`` and
``support=2`` both landed on the same colour. Two strips painted in the same colours
in the same order read as two views of one variable rather than two variables.
Colours now come from ``palettes.assign_colors`` over the union of the universes:
one value, one colour, wherever it shows.
"""

from __future__ import annotations

from depictio.api.v1.celery_tasks import _heatmap_scale_kind, _stable_palette_map
from depictio.models import palettes
from depictio.models.palette_tracks import is_reserved_colour, track_palette, track_pins

_PALETTE = track_palette("diverging")


def test_two_annotation_columns_get_disjoint_colours() -> None:
    colors = _stable_palette_map(
        {"consensus_set": ["EZH2_IP", "FOXA1_IP"], "support": ["2", "3", "4"]},
        _PALETTE,
    )
    used_by_set = set(colors["consensus_set"].values())
    used_by_support = set(colors["support"].values())
    assert used_by_set.isdisjoint(used_by_support)
    assert colors["consensus_set"]["EZH2_IP"] != colors["support"]["2"]
    assert colors["consensus_set"]["FOXA1_IP"] != colors["support"]["3"]


def test_colours_are_the_shared_assignment() -> None:
    universes = {"consensus_set": ["EZH2_IP", "FOXA1_IP"], "support": ["2", "3", "4"]}
    expected = palettes.assign_colors({v for u in universes.values() for v in u}, palette=_PALETTE)
    colors = _stable_palette_map(universes, _PALETTE)
    for col, universe in universes.items():
        assert colors[col] == {v: expected[v] for v in universe}


def test_a_shared_value_keeps_one_colour_across_columns() -> None:
    colors = _stable_palette_map({"a": ["x", "y"], "b": ["y", "z"]}, _PALETTE)
    assert colors["a"]["y"] == colors["b"]["y"]


def test_a_value_colour_does_not_depend_on_the_column_order() -> None:
    forward = _stable_palette_map({"a": ["x", "y"], "b": ["z"]}, _PALETTE)
    backward = _stable_palette_map({"b": ["z"], "a": ["x", "y"]}, _PALETTE)
    assert forward == backward


def test_every_value_keeps_a_colour_once_the_palette_is_used_up() -> None:
    """More values than hues is a grey tail, not a gap: the track must stay total."""
    universe = [f"v{i:02d}" for i in range(12)]
    colors = _stable_palette_map({"a": universe}, _PALETTE)
    assert set(colors["a"]) == set(universe)
    assert colors["a"]["v05"] == _PALETTE[5]
    assert colors["a"]["v06"] == palettes.semantic("other")


def test_reserved_values_take_their_grey() -> None:
    colors = _stable_palette_map({"phylum": ["Bacteroidota", "Unclassified"]}, _PALETTE)
    assert colors["phylum"]["Unclassified"] == palettes.semantic("unclassified")
    assert colors["phylum"]["Bacteroidota"] == _PALETTE[0]


def test_dark_mode_uses_the_dark_variant() -> None:
    colors = _stable_palette_map({"a": ["x"]}, track_palette("diverging", "dark"), mode="dark")
    assert colors["a"]["x"] == track_palette("diverging", "dark")[0]


def test_no_columns_yields_no_colours() -> None:
    assert _stable_palette_map({}, _PALETTE) == {}


def test_tracks_avoid_the_ends_of_the_scale() -> None:
    cat = palettes.categorical()
    assert cat[1] not in track_palette("diverging")
    assert cat[2] not in track_palette("diverging")
    assert cat[0] not in track_palette("sequential")
    assert cat[0] in track_palette("diverging")
    assert track_palette(None) == cat


def test_scale_kind_follows_the_named_colorscale() -> None:
    assert _heatmap_scale_kind(None) == "diverging"
    assert _heatmap_scale_kind("RdBu_r") == "diverging"
    assert _heatmap_scale_kind("Viridis") == "sequential"


def test_counts_rank_the_commonest_values_onto_the_first_slots() -> None:
    universes = {"a": ["alpha", "beta", "gamma"]}
    counts = {"a": {"alpha": 1, "beta": 50, "gamma": 7}}
    colors = _stable_palette_map(universes, _PALETTE, counts=counts)
    assert colors["a"]["beta"] == _PALETTE[0]
    assert colors["a"]["gamma"] == _PALETTE[1]
    assert colors["a"]["alpha"] == _PALETTE[2]


def test_counts_are_summed_over_the_columns() -> None:
    universes = {"a": ["x", "y"], "b": ["y", "z"]}
    counts = {"a": {"x": 5, "y": 3}, "b": {"y": 4, "z": 6}}
    colors = _stable_palette_map(universes, _PALETTE, counts=counts)
    # totals: y=7, z=6, x=5
    assert [colors["a"]["y"], colors["b"]["z"], colors["a"]["x"]] == _PALETTE[:3]


def test_a_pin_wins_and_frees_no_other_pinned_slot() -> None:
    pinned = {"a": {"x": _PALETTE[0]}}
    colors = _stable_palette_map({"a": ["x", "y"]}, _PALETTE, pinned=pinned)
    assert colors["a"]["x"] == _PALETTE[0]
    assert colors["a"]["y"] == _PALETTE[1]


def test_a_free_value_takes_no_colour_any_column_pins() -> None:
    """One value pinned differently in two columns: both hues stay theirs.

    Only the first pin per shared value used to leave the union, so the other
    column's pin stayed a free slot and an unrelated value could draw it —
    two different values in one colour on the same tile.
    """
    cat = palettes.categorical()
    pinned = {"group": {"X": cat[1]}, "cohort": {"X": cat[0]}}
    colors = _stable_palette_map({"group": ["X", "Y"], "cohort": ["X", "Z"]}, cat, pinned=pinned)
    # Each column keeps its own pin for the shared value.
    assert colors["group"]["X"] == cat[1]
    assert colors["cohort"]["X"] == cat[0]
    # No free value draws a colour any column pins.
    pinned_colours = {cat[0], cat[1]}
    assert colors["group"]["Y"] not in pinned_colours
    assert colors["cohort"]["Z"] not in pinned_colours


def test_track_pins_match_the_column_case_insensitively() -> None:
    pins = track_pins({"Kingdom": {"Bacteria": "#123456"}}, ["kingdom", "other"], "diverging")
    assert pins == {"kingdom": {"Bacteria": "#123456"}}


def test_track_pins_drop_the_colours_of_the_scale_ends() -> None:
    cat = palettes.categorical()
    category_colors = {
        "grp": {
            "a": cat[2].lower(),  # the low-end teal, any case
            "b": cat[1],  # the high-end orange
            "c": "#123456",  # free
        }
    }
    assert track_pins(category_colors, ["grp"], "diverging") == {"grp": {"c": "#123456"}}
    # The same pins are fine next to a sequential scale, except slot 0.
    kept = track_pins(category_colors, ["grp"], "sequential")["grp"]
    assert set(kept) == {"a", "b", "c"}


def test_a_colour_close_to_a_reserved_one_is_reserved_too() -> None:
    teal = palettes.categorical()[2]
    r, g, b = (int(teal[i : i + 2], 16) for i in (1, 3, 5))
    near = f"#{r:02x}{g:02x}{min(b + 6, 255):02x}"
    assert is_reserved_colour(near, "diverging")
    assert is_reserved_colour(f"rgb({r}, {g}, {b})", "diverging")
    assert not is_reserved_colour("#123456", "diverging")


def test_a_dropped_pin_value_gets_a_free_track_slot() -> None:
    cat = palettes.categorical()
    pins = track_pins({"grp": {"a": cat[2]}}, ["grp"], "diverging")
    colors = _stable_palette_map({"grp": ["a", "b"]}, _PALETTE, pinned=pins)
    assert colors["grp"]["a"] in _PALETTE
    assert colors["grp"]["a"] not in (cat[1], cat[2])
