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
        assert spec.color is None

    def test_spec_accepts_an_unvalidated_palette_name(self):
        """Colour is a Mantine palette name the frontend Select constrains. The
        model stays permissive so a hand-written YAML never fails on it."""
        assert FilterSectionSpec(name="Quality", color="teal").color == "teal"
        assert FilterSectionSpec(name="Quality", color="not-a-palette").color == "not-a-palette"

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
            filter_sections=[{"name": "Quality", "icon": "mdi:check-decagram", "color": "teal"}],
        )
        full = dash.to_full()
        assert full["filter_sections"] == [
            {
                "name": "Quality",
                "icon": "mdi:check-decagram",
                "color": "teal",
                "description": None,
                "collapsed": False,
                "persistent": False,
                "pin": "top",
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
            filter_sections=[
                {
                    "name": "Quality",
                    "icon": "mdi:check-decagram",
                    "color": "teal",
                    "collapsed": True,
                }
            ],
        )
        back = DashboardDataLite.from_full(dash.to_full())
        assert len(back.filter_sections) == 1
        assert back.filter_sections[0].name == "Quality"
        assert back.filter_sections[0].icon == "mdi:check-decagram"
        assert back.filter_sections[0].color == "teal"
        assert back.filter_sections[0].collapsed is True

    def test_exported_yaml_carries_the_panel_structure(self):
        """The export route is `from_full(...).to_yaml()`, so pin the artifact
        users actually get rather than only the intermediate model."""
        dash = _dashboard(
            [_interactive("a", section="Quality", group="Depth")],
            filter_sections=[{"name": "Quality", "icon": "mdi:check-decagram", "color": "teal"}],
        )
        yaml_text = DashboardDataLite.from_full(dash.to_full()).to_yaml()
        assert "filter_sections:" in yaml_text
        assert "name: Quality" in yaml_text
        assert "color: teal" in yaml_text
        assert "section: Quality" in yaml_text
        assert "group: Depth" in yaml_text

    def test_dashboard_without_sections_round_trips_clean(self):
        dash = _dashboard([_interactive("a")])
        back = DashboardDataLite.from_full(dash.to_full())
        assert back.filter_sections == []
        assert back.components[0].section is None  # type: ignore[union-attr]
        assert back.components[0].group is None  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# `section` on every component type — the main grid groups by it too
# ---------------------------------------------------------------------------


def _figure(tag: str, **kwargs) -> dict:
    return {
        "tag": tag,
        "component_type": "figure",
        "visu_type": "scatter",
        "figure_params": {"x": "sepal.length", "y": "sepal.width"},
        **kwargs,
    }


class TestSectionOnEveryType:
    """`section` lives on `BaseLiteComponent`: the left panel groups its
    interactive controls by it, the main grid groups everything else."""

    def test_figure_accepts_a_section(self):
        dash = _dashboard([_figure("f", section="Quality")])
        assert dash.to_full()["stored_metadata"][0]["section"] == "Quality"

    def test_section_survives_a_round_trip_on_a_figure(self):
        dash = _dashboard([_figure("f", section="Quality")])
        comp = DashboardDataLite.from_full(dash.to_full()).components[0]
        assert comp.section == "Quality"  # type: ignore[union-attr]

    def test_group_stays_interactive_only(self):
        """A figure's `group` is not validated against the group-size cap — only
        interactive components share a card."""
        comps = [_figure(f"f{i}", group="Anything") for i in range(MAX_INTERACTIVE_GROUP_SIZE + 3)]
        assert len(_dashboard(comps).components) == MAX_INTERACTIVE_GROUP_SIZE + 3

    def test_every_type_defaults_to_no_section(self):
        full = _dashboard([_figure("f"), _interactive("a")]).to_full()
        assert [c["section"] for c in full["stored_metadata"]] == [None, None]


class TestGridSections:
    def test_defaults_to_empty(self):
        assert _dashboard([_figure("f")]).grid_sections == []

    def test_kept_separate_from_filter_sections(self):
        """Same model, distinct lists: a section named "QC" in the filter panel
        and one in the grid are two different placements."""
        dash = _dashboard(
            [_figure("f", section="QC"), _interactive("a", section="QC")],
            filter_sections=[{"name": "QC", "icon": "mdi:filter", "color": "indigo"}],
            grid_sections=[{"name": "QC", "icon": "mdi:chart-box", "color": "orange"}],
        )
        full = dash.to_full()
        assert full["filter_sections"][0]["icon"] == "mdi:filter"
        assert full["filter_sections"][0]["color"] == "indigo"
        assert full["grid_sections"][0]["icon"] == "mdi:chart-box"
        assert full["grid_sections"][0]["color"] == "orange"

    def test_survives_a_round_trip(self):
        dash = _dashboard(
            [_figure("f", section="QC")],
            grid_sections=[{"name": "QC", "collapsed": True}],
        )
        back = DashboardDataLite.from_full(dash.to_full())
        assert len(back.grid_sections) == 1
        assert back.grid_sections[0].name == "QC"
        assert back.grid_sections[0].collapsed is True


# ---------------------------------------------------------------------------
# `persistent` — cross-tab fan-out flag
# ---------------------------------------------------------------------------


class TestPersistentFlag:
    """A section marked persistent renders on every tab of its dashboard family
    (grid sections above the sibling tabs' grids, filter sections' controls in
    every tab's panel). The flag is presentation-only server-side: it must
    default off, parse from YAML, and survive both round-trip directions."""

    def test_defaults_to_false(self):
        assert FilterSectionSpec(name="Sample metadata").persistent is False

    def test_parses_from_dashboard_yaml_shape(self):
        dash = _dashboard(
            [_figure("f", section="Sample metadata")],
            grid_sections=[{"name": "Sample metadata", "persistent": True}],
        )
        assert dash.grid_sections[0].persistent is True

    def test_reaches_the_full_dashboard(self):
        dash = _dashboard(
            [_interactive("a", section="Sample filters")],
            filter_sections=[{"name": "Sample filters", "persistent": True}],
        )
        assert dash.to_full()["filter_sections"][0]["persistent"] is True

    def test_survives_a_round_trip(self):
        dash = _dashboard(
            [_figure("f", section="Sample metadata")],
            grid_sections=[{"name": "Sample metadata", "persistent": True}],
        )
        back = DashboardDataLite.from_full(dash.to_full())
        assert back.grid_sections[0].persistent is True

    def test_exported_yaml_carries_the_flag(self):
        dash = _dashboard(
            [_figure("f", section="Sample metadata")],
            grid_sections=[{"name": "Sample metadata", "persistent": True}],
        )
        yaml_text = DashboardDataLite.from_full(dash.to_full()).to_yaml()
        assert "persistent: true" in yaml_text


class TestPinField:
    """`pin` says which edge a persistent section sits at, on every tab of the
    family including the one that owns it. It exists so "shows everywhere" and
    "leads the page" stop being the same decision: a reference table wants the
    first, not the second."""

    def test_defaults_to_top(self):
        """The placement persistent sections had before `pin` existed."""
        assert FilterSectionSpec(name="Sample metadata").pin == "top"

    def test_accepts_bottom(self):
        assert FilterSectionSpec(name="Sample metadata", pin="bottom").pin == "bottom"

    def test_rejects_any_other_edge(self):
        with pytest.raises(ValidationError):
            FilterSectionSpec(name="Sample metadata", pin="middle")  # type: ignore[arg-type]

    def test_survives_a_round_trip(self):
        dash = _dashboard(
            [_figure("f", section="Sample metadata")],
            grid_sections=[{"name": "Sample metadata", "persistent": True, "pin": "bottom"}],
        )
        back = DashboardDataLite.from_full(dash.to_full())
        assert back.grid_sections[0].pin == "bottom"

    def test_exported_yaml_carries_the_edge(self):
        dash = _dashboard(
            [_figure("f", section="Sample metadata")],
            grid_sections=[{"name": "Sample metadata", "persistent": True, "pin": "bottom"}],
        )
        yaml_text = DashboardDataLite.from_full(dash.to_full()).to_yaml()
        assert "pin: bottom" in yaml_text


# ---------------------------------------------------------------------------
# Text components carry no data binding through an export
# ---------------------------------------------------------------------------


class TestTextComponentExport:
    """`to_full` binds neither a workflow nor a data collection to a text
    component. An export that inherited a collection tag from a leftover
    `dc_config` produced a component the import could not resolve — no
    `workflow_tag` to resolve it against — so every text component was dropped
    on the way back in, which is what broke the iris YAML round-trip."""

    def _full_with_text(self, **extra) -> dict:
        return {
            "title": "Test",
            "stored_metadata": [
                {
                    "index": "text-1",
                    "component_type": "text",
                    "title": "Intro",
                    "data_collection_tag": "",
                    "workflow_tag": "",
                    **extra,
                }
            ],
        }

    def test_leftover_dc_config_is_not_exported(self):
        full = self._full_with_text(dc_config={"data_collection_tag": "iris_table"})
        comp = DashboardDataLite.from_full(full).components[0]
        assert comp.data_collection_tag in (None, "")  # type: ignore[union-attr]
        assert comp.workflow_tag in (None, "")  # type: ignore[union-attr]

    def test_a_bound_figure_still_exports_its_tags(self):
        full = {
            "title": "Test",
            "stored_metadata": [
                {
                    "index": "fig-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "workflow_tag": "python/iris_workflow",
                    "dc_config": {"data_collection_tag": "iris_table"},
                }
            ],
        }
        comp = DashboardDataLite.from_full(full).components[0]
        assert comp.data_collection_tag == "iris_table"  # type: ignore[union-attr]
        assert comp.workflow_tag == "python/iris_workflow"  # type: ignore[union-attr]
