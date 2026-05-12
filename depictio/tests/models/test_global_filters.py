"""Schema-level tests for the cross-tab Global Filters & Stories feature.

These exercise the new Pydantic models in isolation — they don't touch the
``user_dashboard_state`` MongoDB collection or the API routes. End-to-end
coverage of the endpoints lives in the existing
``tests/api/v1/endpoints/dashboards_endpoints`` tree (added separately) and
requires a mongomock fixture.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboards import (
    GlobalFilterDef,
    GlobalFilterLink,
    Story,
)
from depictio.models.models.user_dashboard_state import UserDashboardState


def _make_filter(**overrides) -> GlobalFilterDef:
    base = dict(
        id="gf_abc",
        label="Sample ID",
        source_component_index="comp-uuid-1",
        source_tab_id=PyObjectId(),
        interactive_component_type="MultiSelect",
        column_type="object",
        default_state=None,
        links=[
            GlobalFilterLink(
                wf_id="wf-1",
                dc_id="dc-1",
                column_name="sample_id",
            )
        ],
    )
    base.update(overrides)
    return GlobalFilterDef(**base)


class TestGlobalFilterLink:
    def test_minimal_round_trip(self):
        link = GlobalFilterLink(wf_id="wf1", dc_id="dc1", column_name="x")
        dumped = link.model_dump()
        assert dumped == {"wf_id": "wf1", "dc_id": "dc1", "column_name": "x"}
        assert GlobalFilterLink(**dumped) == link

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            GlobalFilterLink(wf_id="wf1", dc_id="dc1", column_name="x", bogus="nope")


class TestGlobalFilterDef:
    def test_minimal_construction(self):
        f = _make_filter()
        assert f.id == "gf_abc"
        assert f.label == "Sample ID"
        assert len(f.links) == 1
        assert f.links[0].column_name == "sample_id"

    def test_source_tab_id_serialized_as_string(self):
        f = _make_filter()
        dumped = f.model_dump(mode="json")
        assert isinstance(dumped["source_tab_id"], str)
        # ObjectId-shaped — 24 hex chars
        assert len(dumped["source_tab_id"]) == 24

    def test_round_trip_through_model_dump(self):
        original = _make_filter(
            links=[
                GlobalFilterLink(wf_id="wf1", dc_id="dc1", column_name="sample"),
                GlobalFilterLink(wf_id="wf2", dc_id="dc2", column_name="sample_id"),
            ]
        )
        dumped = original.model_dump(mode="json")
        # Re-coerce source_tab_id (string) back into PyObjectId
        rebuilt = GlobalFilterDef(**dumped)
        assert rebuilt.id == original.id
        assert len(rebuilt.links) == 2
        assert {link.dc_id for link in rebuilt.links} == {"dc1", "dc2"}

    def test_multiple_links_for_cross_dc_propagation(self):
        f = _make_filter(
            links=[
                GlobalFilterLink(wf_id="wf1", dc_id="dc-genes", column_name="gene_id"),
                GlobalFilterLink(wf_id="wf1", dc_id="dc-locations", column_name="gene"),
            ]
        )
        assert len(f.links) == 2
        # Different column names per DC — the whole point of multi-link
        assert f.links[0].column_name != f.links[1].column_name

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            _make_filter(unrelated="value")


class TestStory:
    def test_construct_and_serialize(self):
        story = Story(
            id="story_1",
            name="Genes → Locations",
            description="Walk from a gene of interest to its spatial footprint.",
            icon="tabler:dna",
            color="blue",
            tab_order=[PyObjectId(), PyObjectId()],
            default_global_filter_ids=["gf_abc"],
            pinned=True,
        )
        dumped = story.model_dump(mode="json")
        assert dumped["name"] == "Genes → Locations"
        assert dumped["pinned"] is True
        assert isinstance(dumped["tab_order"], list)
        assert all(isinstance(x, str) for x in dumped["tab_order"])

    def test_defaults(self):
        story = Story(id="s1", name="bare")
        assert story.tab_order == []
        assert story.default_global_filter_ids == []
        assert story.pinned is False
        assert story.icon is None
        assert story.color is None

    def test_same_tab_can_appear_in_two_stories_at_different_positions(self):
        """Stories.tab_order is independent of DashboardData.tab_order — the
        same child tab id can appear at position 0 in story A and position 2
        in story B. This test asserts the model doesn't accidentally
        deduplicate or canonicalize the order."""
        shared_tab = PyObjectId()
        other_a = PyObjectId()
        other_b = PyObjectId()
        story_a = Story(id="A", name="A", tab_order=[shared_tab, other_a])
        story_b = Story(id="B", name="B", tab_order=[other_b, shared_tab])
        assert story_a.tab_order[0] == shared_tab
        assert story_b.tab_order[1] == shared_tab


class TestUserDashboardState:
    def test_default_empty_values(self):
        state = UserDashboardState(
            user_id=PyObjectId(),
            parent_dashboard_id=PyObjectId(),
        )
        assert state.global_filter_values == {}
        assert state.last_active_story_id is None
        assert state.last_active_tab_id is None

    def test_round_trip_values(self):
        state = UserDashboardState(
            user_id=PyObjectId(),
            parent_dashboard_id=PyObjectId(),
            global_filter_values={"gf_a": ["x", "y"], "gf_b": [0, 100]},
            last_active_story_id="story_1",
        )
        dumped = state.model_dump(mode="json")
        assert isinstance(dumped["user_id"], str)
        assert isinstance(dumped["parent_dashboard_id"], str)
        assert dumped["global_filter_values"] == {"gf_a": ["x", "y"], "gf_b": [0, 100]}
        assert dumped["last_active_story_id"] == "story_1"


class TestDashboardDataIntegration:
    """Make sure adding the new fields to DashboardData didn't break defaults
    or older-document loading."""

    def test_dashboard_data_defaults_new_fields_to_empty(self):
        from depictio.models.models.dashboards import DashboardData
        from depictio.models.models.users import Permission

        dash = DashboardData(
            dashboard_id=PyObjectId(),
            project_id=PyObjectId(),
            title="t",
            permissions=Permission(),
        )
        assert dash.global_filters == []
        assert dash.stories == []

    def test_dashboard_data_round_trip(self):
        from depictio.models.models.dashboards import DashboardData
        from depictio.models.models.users import Permission

        dash = DashboardData(
            dashboard_id=PyObjectId(),
            project_id=PyObjectId(),
            title="t",
            permissions=Permission(),
            global_filters=[_make_filter()],
            stories=[Story(id="s1", name="story 1")],
        )
        dumped = dash.model_dump(mode="json")
        assert len(dumped["global_filters"]) == 1
        assert dumped["global_filters"][0]["id"] == "gf_abc"
        assert len(dumped["stories"]) == 1
        assert dumped["stories"][0]["name"] == "story 1"
