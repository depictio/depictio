"""Filter bar (`display: strip` on a grid section) and `category_colors`.

A grid section drawn as a filter bar holds the interactive components that name
it, rendered as one compact row. The model only has to carry three things for
that — the section's `display`, two per-filter presentation fields
(`strip_label`, `strip_icon`) and the dashboard's `category_colors` — and keep
all of them through the YAML import, the full document and the export.
"""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite, FilterSectionSpec


def _interactive(tag: str, **kwargs) -> dict:
    return {
        "tag": tag,
        "component_type": "interactive",
        "workflow_tag": "nf-core/ampliseq",
        "data_collection_tag": "metadata",
        "interactive_component_type": "MultiSelect",
        "column_name": "habitat",
        "column_type": "object",
        **kwargs,
    }


def _dashboard(components: list[dict], **kwargs) -> DashboardDataLite:
    return DashboardDataLite(title="Strip", components=components, **kwargs)


# ---------------------------------------------------------------------------
# FilterSectionSpec.display
# ---------------------------------------------------------------------------


class TestSectionDisplay:
    def test_defaults_to_unset(self):
        assert FilterSectionSpec(name="Filters").display is None

    @pytest.mark.parametrize("display", ["grid", "strip"])
    def test_accepts_each_display(self, display):
        assert FilterSectionSpec(name="Filters", display=display).display == display

    def test_rejects_an_unknown_display(self):
        with pytest.raises(ValidationError):
            FilterSectionSpec(name="Filters", display="carousel")

    def test_round_trips_through_full_and_yaml(self):
        dash = _dashboard(
            [_interactive("habitat", section="Filters")],
            grid_sections=[{"name": "Filters", "display": "strip"}],
        )
        assert dash.to_full()["grid_sections"][0]["display"] == "strip"
        assert DashboardDataLite.from_yaml(dash.to_yaml()).grid_sections[0].display == "strip"
        assert DashboardDataLite.from_full(dash.to_full()).grid_sections[0].display == "strip"

    def test_unset_is_not_exported(self):
        dash = _dashboard(
            [_interactive("habitat", section="Filters")],
            grid_sections=[{"name": "Filters"}],
        )
        assert "display" not in dash.to_yaml()
        assert "display" not in DashboardDataLite.from_full(dash.to_full()).to_yaml()

    def test_strip_member_keeps_its_section_and_left_layout(self):
        """The model does not move a strip member anywhere: it keeps its
        `section`, and its layout entry stays in the left panel's list (the
        viewer ignores coordinates for strip members)."""
        dash = _dashboard(
            [_interactive("habitat", section="Filters")],
            grid_sections=[{"name": "Filters", "display": "strip"}],
        )
        full = dash.to_full()
        assert full["stored_metadata"][0]["section"] == "Filters"
        assert len(full["left_panel_layout_data"]) == 1
        assert full["right_panel_layout_data"] == []


# ---------------------------------------------------------------------------
# strip_label / strip_icon
# ---------------------------------------------------------------------------


class TestStripPresentationFields:
    def test_unset_by_default(self):
        meta = _dashboard([_interactive("habitat")]).to_full()["stored_metadata"][0]
        assert "strip_label" not in meta
        assert "strip_icon" not in meta

    def test_reach_the_full_document_from_the_display_block(self):
        comp = _interactive("habitat", display={"strip_label": "Habitat", "strip_icon": False})
        meta = _dashboard([comp]).to_full()["stored_metadata"][0]
        assert meta["strip_label"] == "Habitat"
        assert meta["strip_icon"] is False

    def test_reach_the_full_document_as_top_level_fields(self):
        comp = _interactive("habitat", strip_label="Habitat", strip_icon=True)
        meta = _dashboard([comp]).to_full()["stored_metadata"][0]
        assert meta["strip_label"] == "Habitat"
        assert meta["strip_icon"] is True

    def test_survive_a_round_trip(self):
        comp = _interactive("habitat", display={"strip_label": "Habitat", "strip_icon": False})
        back = DashboardDataLite.from_full(_dashboard([comp]).to_full())
        display = back.components[0].display  # type: ignore[union-attr]
        assert display["strip_label"] == "Habitat"
        # `False` is the only value of `strip_icon` worth writing down, and the
        # one a truthiness filter would drop.
        assert display["strip_icon"] is False

    def test_default_icon_is_not_exported(self):
        comp = _interactive("habitat", display={"strip_icon": True})
        assert (
            "strip_icon" not in DashboardDataLite.from_full(_dashboard([comp]).to_full()).to_yaml()
        )


# ---------------------------------------------------------------------------
# category_colors
# ---------------------------------------------------------------------------


COLORS = {"habitat": {"Groundwater": "#45b8c9", "Soil": "#f0a04b"}}


class TestCategoryColors:
    def test_defaults_to_unset(self):
        dash = _dashboard([_interactive("habitat")])
        assert dash.category_colors is None
        assert dash.to_full()["category_colors"] is None
        assert "category_colors" not in dash.to_yaml()

    def test_round_trips_through_full_and_yaml(self):
        dash = _dashboard([_interactive("habitat")], category_colors=COLORS)
        assert dash.to_full()["category_colors"] == COLORS
        assert DashboardDataLite.from_yaml(dash.to_yaml()).category_colors == COLORS
        assert DashboardDataLite.from_full(dash.to_full()).category_colors == COLORS

    def test_listed_with_the_optional_dashboard_fields(self):
        yaml_str = _dashboard([_interactive("habitat")], category_colors=COLORS).to_yaml()
        optional_at = yaml_str.index("# --- optional ---")
        assert optional_at < yaml_str.index("category_colors:") < yaml_str.index("components:")

    def test_rejects_a_non_string_colour(self):
        with pytest.raises(ValidationError):
            _dashboard([_interactive("habitat")], category_colors={"habitat": {"Soil": 3}})

    def test_the_full_model_accepts_it(self):
        """The editor saves through `DashboardData`, which forbids unknown
        keys: without the field a dashboard carrying colours could not save."""
        from depictio.models.models.dashboards import DashboardData

        full = _dashboard([_interactive("habitat")], category_colors=COLORS).to_full()
        doc = DashboardData(
            **{
                **full,
                "dashboard_id": "507f1f77bcf86cd799439011",
                "project_id": "507f1f77bcf86cd799439012",
                "permissions": {"owners": [], "editors": [], "viewers": []},
            }
        )
        assert doc.category_colors == COLORS
        assert doc.inherited_category_colors is None
