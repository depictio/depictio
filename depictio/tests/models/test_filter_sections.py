"""Left filter panel structure: interactive `group`, `section`, `filter_sections`.

The panel renders section (accordion) → group (collapsible card) → control.
Both levels are optional, so the main thing worth pinning down is that a
dashboard declaring neither still behaves exactly as it did before sections
existed, and that the shapes the renderer cannot draw are rejected at import.
"""

import pytest
from pydantic import ValidationError

from depictio.models.components.constants import MAX_INTERACTIVE_GROUP_SIZE
from depictio.models.components.lite import InteractiveLiteComponent
from depictio.models.models.dashboards import DashboardDataLite, FilterSectionSpec


def _interactive(tag: str, **kwargs) -> dict:
    """Minimal valid interactive component, overridable per test."""
    return {
        "tag": tag,
        "component_type": "interactive",
        "interactive_component_type": "MultiSelect",
        "column_name": "variety",
        "column_type": "object",
        **kwargs,
    }


def _dashboard(components: list[dict], **kwargs) -> DashboardDataLite:
    return DashboardDataLite(title="Test", components=components, **kwargs)


# ---------------------------------------------------------------------------
# Component fields
# ---------------------------------------------------------------------------


class TestInteractiveSectionField:
    def test_section_defaults_to_none(self):
        comp = InteractiveLiteComponent(**_interactive("a"))
        assert comp.section is None
        assert comp.group is None

    def test_section_round_trips(self):
        comp = InteractiveLiteComponent(**_interactive("a", section="Quality"))
        assert comp.section == "Quality"


# ---------------------------------------------------------------------------
# validate_interactive_groups
# ---------------------------------------------------------------------------


class TestGroupSize:
    def test_group_at_the_limit_is_accepted(self):
        comps = [_interactive(f"c{i}", group="Shape") for i in range(MAX_INTERACTIVE_GROUP_SIZE)]
        dash = _dashboard(comps)
        assert len(dash.components) == MAX_INTERACTIVE_GROUP_SIZE

    def test_group_over_the_limit_is_rejected(self):
        comps = [
            _interactive(f"c{i}", group="Shape") for i in range(MAX_INTERACTIVE_GROUP_SIZE + 1)
        ]
        with pytest.raises(ValidationError, match="exceed the maximum size"):
            _dashboard(comps)

    def test_ungrouped_components_are_never_capped(self):
        comps = [_interactive(f"c{i}") for i in range(MAX_INTERACTIVE_GROUP_SIZE + 5)]
        dash = _dashboard(comps)
        assert len(dash.components) == MAX_INTERACTIVE_GROUP_SIZE + 5

    def test_separate_groups_are_counted_separately(self):
        comps = [_interactive(f"a{i}", group="A") for i in range(MAX_INTERACTIVE_GROUP_SIZE)]
        comps += [_interactive(f"b{i}", group="B") for i in range(MAX_INTERACTIVE_GROUP_SIZE)]
        assert len(_dashboard(comps).components) == MAX_INTERACTIVE_GROUP_SIZE * 2


class TestGroupSectionConsistency:
    def test_group_within_one_section_is_accepted(self):
        comps = [
            _interactive("a", group="Shape", section="Morphology"),
            _interactive("b", group="Shape", section="Morphology"),
        ]
        assert len(_dashboard(comps).components) == 2

    def test_group_spanning_two_sections_is_rejected(self):
        comps = [
            _interactive("a", group="Shape", section="Morphology"),
            _interactive("b", group="Shape", section="Quality"),
        ]
        with pytest.raises(ValidationError, match="must sit in a single section"):
            _dashboard(comps)

    def test_group_half_in_a_section_is_rejected(self):
        """A member with no section is a distinct bucket, not a wildcard."""
        comps = [
            _interactive("a", group="Shape", section="Morphology"),
            _interactive("b", group="Shape"),
        ]
        with pytest.raises(ValidationError, match="must sit in a single section"):
            _dashboard(comps)

    def test_same_group_name_is_allowed_across_dashboards_not_sections(self):
        """Two different groups may each sit in their own section."""
        comps = [
            _interactive("a", group="Shape", section="Morphology"),
            _interactive("b", group="Depth", section="Quality"),
        ]
        assert len(_dashboard(comps).components) == 2


# ---------------------------------------------------------------------------
# filter_sections
# ---------------------------------------------------------------------------


class TestFilterSections:
    def test_defaults_to_empty(self):
        assert _dashboard([_interactive("a")]).filter_sections == []

    def test_spec_defaults_to_expanded(self):
        spec = FilterSectionSpec(name="Quality")
        assert spec.collapsed is False
        assert spec.icon is None

    def test_spec_rejects_unknown_keys(self):
        """extra='forbid' turns a typo into an import error, not a silent no-op."""
        with pytest.raises(ValidationError):
            FilterSectionSpec(name="Quality", collapsable=True)  # type: ignore[call-arg]

    def test_specs_parse_from_dashboard(self):
        dash = _dashboard(
            [_interactive("a", section="Quality")],
            filter_sections=[{"name": "Quality", "icon": "mdi:check-decagram", "collapsed": True}],
        )
        assert dash.filter_sections[0].name == "Quality"
        assert dash.filter_sections[0].collapsed is True

    def test_specs_need_not_match_any_component(self):
        """The panel skips empty sections rather than failing the import."""
        dash = _dashboard([_interactive("a")], filter_sections=[{"name": "Unused"}])
        assert dash.filter_sections[0].name == "Unused"


# ---------------------------------------------------------------------------
# to_full() passthrough — what the React viewer actually reads
# ---------------------------------------------------------------------------


class TestToFullPassthrough:
    def test_section_and_group_reach_stored_metadata(self):
        dash = _dashboard(
            [_interactive("a", section="Quality", group="Depth")],
            filter_sections=[{"name": "Quality", "icon": "mdi:check-decagram"}],
        )
        full = dash.to_full()
        comp = full["stored_metadata"][0]
        assert comp["section"] == "Quality"
        assert comp["group"] == "Depth"
        assert comp["placement"] == "left"

    def test_filter_sections_reach_the_full_dashboard(self):
        dash = _dashboard(
            [_interactive("a", section="Quality")],
            filter_sections=[{"name": "Quality", "icon": "mdi:check-decagram"}],
        )
        full = dash.to_full()
        assert full["filter_sections"] == [
            {
                "name": "Quality",
                "icon": "mdi:check-decagram",
                "description": None,
                "collapsed": False,
            }
        ]

    def test_dashboard_without_sections_is_unchanged(self):
        """The additive guarantee: no section anywhere, nothing new to render."""
        full = _dashboard([_interactive("a")]).to_full()
        assert full["filter_sections"] == []
        assert full["stored_metadata"][0]["section"] is None
        assert full["stored_metadata"][0]["group"] is None


# ---------------------------------------------------------------------------
# from_full() round-trip — export must not flatten the panel
# ---------------------------------------------------------------------------


class TestFromFullRoundTrip:
    """`from_full` used to drop every placement field, so exporting a dashboard
    flattened its left panel back into one ungrouped list."""

    def test_section_and_group_survive_a_round_trip(self):
        dash = _dashboard([_interactive("a", section="Quality", group="Depth")])
        comp = DashboardDataLite.from_full(dash.to_full()).components[0]
        assert comp.section == "Quality"  # type: ignore[union-attr]
        assert comp.group == "Depth"  # type: ignore[union-attr]

    def test_top_placement_survives_a_round_trip(self):
        """`placement='top'` is allow-listed to Timeline, which also carries
        `timescale` and `show_marks` — the other two fields the export dropped."""
        dash = _dashboard(
            [
                _interactive(
                    "t",
                    interactive_component_type="Timeline",
                    column_name="acquired_at",
                    column_type="datetime",
                    placement="top",
                    timescale="day",
                    show_marks=True,
                )
            ]
        )
        comp = DashboardDataLite.from_full(dash.to_full()).components[0]
        assert comp.placement == "top"  # type: ignore[union-attr]
        assert comp.timescale == "day"  # type: ignore[union-attr]
        assert comp.show_marks is True  # type: ignore[union-attr]

    def test_filter_sections_survive_a_round_trip(self):
        dash = _dashboard(
            [_interactive("a", section="Quality")],
            filter_sections=[{"name": "Quality", "icon": "mdi:check-decagram", "collapsed": True}],
        )
        back = DashboardDataLite.from_full(dash.to_full())
        assert len(back.filter_sections) == 1
        assert back.filter_sections[0].name == "Quality"
        assert back.filter_sections[0].icon == "mdi:check-decagram"
        assert back.filter_sections[0].collapsed is True

    def test_exported_yaml_carries_the_panel_structure(self):
        """The export route is `from_full(...).to_yaml()`, so pin the artifact
        users actually get rather than only the intermediate model."""
        dash = _dashboard(
            [_interactive("a", section="Quality", group="Depth")],
            filter_sections=[{"name": "Quality", "icon": "mdi:check-decagram"}],
        )
        yaml_text = DashboardDataLite.from_full(dash.to_full()).to_yaml()
        assert "filter_sections:" in yaml_text
        assert "name: Quality" in yaml_text
        assert "section: Quality" in yaml_text
        assert "group: Depth" in yaml_text

    def test_dashboard_without_sections_round_trips_clean(self):
        dash = _dashboard([_interactive("a")])
        back = DashboardDataLite.from_full(dash.to_full())
        assert back.filter_sections == []
        assert back.components[0].section is None  # type: ignore[union-attr]
        assert back.components[0].group is None  # type: ignore[union-attr]
