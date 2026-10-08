"""`category_colors: auto`: a colour for every value of a column, from its data.

`assign_category_colors` is the pure part (which value gets which slot); the
Lite model is where a template states it (`auto`, or `"*": auto` beside pins).
"""

import random

import pytest
from pydantic import ValidationError

from depictio.models.components.category_palette import (
    CATEGORY_PALETTE,
    assign_category_colors,
    natural_sort_key,
)
from depictio.models.models.dashboards import (
    DashboardData,
    DashboardDataLite,
    strip_auto_category_colors,
)

P = CATEGORY_PALETTE


class TestAssignCategoryColors:
    def test_slots_follow_the_natural_order_of_the_values(self):
        assert assign_category_colors(["S10", "S2", "S1"]) == {"S1": P[0], "S2": P[1], "S10": P[2]}

    def test_natural_sort_ignores_case_and_reads_numbers(self):
        assert sorted(["b", "A10", "a2", "B1"], key=natural_sort_key) == ["a2", "A10", "b", "B1"]

    def test_deterministic_whatever_the_read_order(self):
        values = [f"group_{i}" for i in range(7)]
        expected = assign_category_colors(values)
        for seed in range(5):
            shuffled = values[:]
            random.Random(seed).shuffle(shuffled)
            assert assign_category_colors(shuffled + shuffled[:2]) == expected

    def test_a_pin_keeps_its_colour_and_its_slot_is_skipped(self):
        colours = assign_category_colors(["a", "b", "c"], pinned={"b": P[0]})
        assert colours == {"a": P[1], "b": P[0], "c": P[2]}

    def test_a_pin_off_the_palette_takes_no_slot(self):
        colours = assign_category_colors(["a", "control"], pinned={"control": "#868e96"})
        assert colours == {"a": P[0], "control": "#868e96"}

    def test_a_pin_absent_from_the_data_is_kept(self):
        assert assign_category_colors(["a"], pinned={"z": "#000000"}) == {
            "a": P[0],
            "z": "#000000",
        }

    def test_previous_colours_are_carried_over_and_win_over_pins(self):
        colours = assign_category_colors(
            ["a", "b", "new"], pinned={"a": "#111111"}, previous={"a": P[3], "b": P[0]}
        )
        assert colours["a"] == P[3]
        assert colours["b"] == P[0]
        # The first slot neither the pin nor the previous colours use.
        assert colours["new"] == P[1]

    def test_previous_colours_of_values_gone_from_the_data_are_not_kept(self):
        assert assign_category_colors(["a"], previous={"gone": P[0]}) == {"a": P[0]}

    def test_every_slot_used_when_the_values_fit(self):
        colours = assign_category_colors([f"v{i}" for i in range(len(P))])
        assert list(colours.values()) == list(P)

    def test_more_values_than_free_slots_generates_nothing(self):
        assert assign_category_colors([f"v{i}" for i in range(len(P) + 1)]) == {}

    def test_over_the_cap_pins_and_previous_still_hold(self):
        values = [f"v{i}" for i in range(len(P))]
        # One pinned palette colour leaves 7 slots for the 7 other values: fits.
        fits = assign_category_colors(values, pinned={"v0": P[0]})
        assert len(fits) == len(P)
        # Pins off the palette take no slot, but one previous colour on it
        # leaves 7 slots for the 8 other values: none generated.
        over = assign_category_colors(
            [*values, "v8", "x", "y"],
            pinned={"x": "#000001", "y": "#000002"},
            previous={"v0": P[5]},
        )
        assert over == {"v0": P[5], "x": "#000001", "y": "#000002"}

    def test_no_values_returns_the_pins(self):
        assert assign_category_colors([], pinned={"a": "#123456"}) == {"a": "#123456"}


class TestLiteCategoryColorsAuto:
    def test_a_bare_auto_is_the_star_map(self):
        lite = DashboardDataLite(title="T", category_colors={"condition": "auto"})
        assert lite.category_colors == {"condition": {"*": "auto"}}

    def test_star_beside_pins_and_static_maps_are_accepted(self):
        colors = {"condition": {"*": "auto", "control": "#868e96"}, "Kingdom": {"B": "#1098ad"}}
        assert DashboardDataLite(title="T", category_colors=colors).category_colors == colors

    def test_star_with_a_colour_is_refused(self):
        with pytest.raises(ValidationError, match=r"'\*' only takes `auto`"):
            DashboardDataLite(title="T", category_colors={"condition": {"*": "#ffffff"}})

    def test_auto_for_one_value_is_refused(self):
        with pytest.raises(ValidationError, match="colours a whole column"):
            DashboardDataLite(title="T", category_colors={"condition": {"treated": "auto"}})

    def test_auto_survives_the_full_round_trip_and_yaml(self):
        lite = DashboardDataLite(
            title="T", category_colors={"c": "auto", "g": {"*": "auto", "x": "#000000"}}
        )
        back = DashboardDataLite.from_full(lite.to_full())
        assert back.category_colors == lite.category_colors
        assert DashboardDataLite.from_yaml(back.to_yaml()).category_colors == lite.category_colors

    def test_yaml_with_a_template_key(self):
        lite = DashboardDataLite.from_yaml(
            'title: T\ncategory_colors:\n  "{GROUP_COL}": auto\n  Kingdom: {B: "#1098ad"}\n'
        )
        assert lite.category_colors == {"{GROUP_COL}": {"*": "auto"}, "Kingdom": {"B": "#1098ad"}}


class TestStoredDashboardsHoldNoStar:
    def test_leftover_auto_entries_are_stripped(self):
        assert strip_auto_category_colors(
            {"a": {"*": "auto"}, "b": {"*": "auto", "x": "#000000"}, "c": "auto", "d": {"y": "#1"}}
        ) == {"b": {"x": "#000000"}, "d": {"y": "#1"}}
        assert strip_auto_category_colors({"a": {"*": "auto"}}) is None

    def test_the_full_model_strips_them(self):
        lite = DashboardDataLite(title="T", category_colors={"c": "auto", "k": {"B": "#1098ad"}})
        full = {
            **lite.to_full(),
            "dashboard_id": "507f1f77bcf86cd799439011",
            "project_id": "507f1f77bcf86cd799439012",
        }
        assert DashboardData.model_validate(full).category_colors == {"k": {"B": "#1098ad"}}
