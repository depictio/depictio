"""Component ids must survive a YAML re-import.

``index`` is what addresses a component from outside the dashboard: an export
URL, a saved embed, a host page pinning one panel. It used to be a fresh UUID
minted on every import, so editing one line of a YAML silently invalidated every
external reference to every component on that dashboard — with no error, because
the new dashboard is perfectly valid; it just is not the one anybody linked to.

These tests pin the identity rule rather than the mechanism, since the failure
is only ever visible from outside.
"""

import uuid

import pytest

from depictio.models.components.lite import FigureLiteComponent, InteractiveLiteComponent
from depictio.models.models.dashboards import DashboardDataLite


def test_tag_becomes_the_index():
    component = FigureLiteComponent(
        tag="pr-demo-viz",
        component_type="figure",
        visu_type="scatter",
    )
    assert component.index == "pr-demo-viz"


def test_index_is_stable_across_repeated_construction():
    """The property that actually matters: import twice, get the same id."""
    first = FigureLiteComponent(tag="pr-demo-viz", component_type="figure", visu_type="scatter")
    second = FigureLiteComponent(tag="pr-demo-viz", component_type="figure", visu_type="scatter")
    assert first.index == second.index


def test_explicit_index_wins_over_tag():
    """A dashboard exported from the UI carries a real index; it must survive."""
    component = FigureLiteComponent(
        tag="pr-demo-viz",
        index="0640486e-aadd-45fb-b9c5-d47df32ab5d9",
        component_type="figure",
        visu_type="scatter",
    )
    assert component.index == "0640486e-aadd-45fb-b9c5-d47df32ab5d9"


def test_untagged_component_still_gets_a_uuid():
    """Old YAML without tags must keep working, just without stable ids."""
    component = FigureLiteComponent(component_type="figure", visu_type="scatter")
    uuid.UUID(str(component.index))  # raises if it is not a UUID


def test_duplicate_tags_are_rejected():
    """Two components sharing a tag would share an index and collide silently."""
    with pytest.raises(ValueError, match="unique"):
        DashboardDataLite(
            title="dupes",
            components=[
                InteractiveLiteComponent(
                    tag="same",
                    component_type="interactive",
                    interactive_component_type="MultiSelect",
                    column_name="tool",
                ),
                InteractiveLiteComponent(
                    tag="same",
                    component_type="interactive",
                    interactive_component_type="MultiSelect",
                    column_name="fp",
                ),
            ],
        )


def test_distinct_tags_are_accepted():
    dashboard = DashboardDataLite(
        title="fine",
        components=[
            InteractiveLiteComponent(
                tag="filter-tool",
                component_type="interactive",
                interactive_component_type="MultiSelect",
                column_name="tool",
            ),
            InteractiveLiteComponent(
                tag="filter-fp",
                component_type="interactive",
                interactive_component_type="RangeSlider",
                column_name="fp",
            ),
        ],
    )
    assert [c.index for c in dashboard.components] == ["filter-tool", "filter-fp"]
