"""Schema-level tests for the cross-tab Global Filters & Journeys feature.

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
    Journey,
    JourneyStop,
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


class TestJourneyStop:
    def test_construct_minimal(self):
        stop = JourneyStop(
            id="stop_1",
            name="All samples",
            anchor_tab_id=PyObjectId(),
        )
        assert stop.global_filter_state == {}
        assert stop.local_filter_state == []
        assert stop.description is None

    def test_serialize_anchor_tab_id_as_str(self):
        stop = JourneyStop(id="s", name="n", anchor_tab_id=PyObjectId())
        dumped = stop.model_dump(mode="json")
        assert isinstance(dumped["anchor_tab_id"], str)
        assert len(dumped["anchor_tab_id"]) == 24

    def test_filter_state_round_trip(self):
        """`global_filter_state` and `local_filter_state` are opaque
        payloads — verify both survive JSON round-trip without coercion."""
        stop = JourneyStop(
            id="s",
            name="n",
            anchor_tab_id=PyObjectId(),
            global_filter_state={"gf_a": ["x", "y"], "gf_b": [0.5, 100]},
            local_filter_state=[
                {"index": "comp-1", "value": ["foo"], "column_name": "name"},
                {"index": "comp-2", "value": [10, 20]},
            ],
        )
        dumped = stop.model_dump(mode="json")
        rebuilt = JourneyStop(**dumped)
        assert rebuilt.global_filter_state == stop.global_filter_state
        assert rebuilt.local_filter_state == stop.local_filter_state


class TestJourney:
    def test_construct_and_serialize(self):
        tab_a = PyObjectId()
        tab_b = PyObjectId()
        journey = Journey(
            id="journey_1",
            name="Genes → Locations",
            description="From gene-level filter to spatial footprint.",
            icon="tabler:route",
            color="blue",
            stops=[
                JourneyStop(id="s1", name="Start", anchor_tab_id=tab_a),
                JourneyStop(id="s2", name="Spatial", anchor_tab_id=tab_b),
            ],
            pinned=True,
        )
        dumped = journey.model_dump(mode="json")
        assert dumped["name"] == "Genes → Locations"
        assert dumped["pinned"] is True
        assert len(dumped["stops"]) == 2
        assert isinstance(dumped["stops"][0]["anchor_tab_id"], str)

    def test_defaults(self):
        journey = Journey(id="j", name="bare")
        assert journey.stops == []
        assert journey.pinned is False
        assert journey.icon is None
        assert journey.color is None

    def test_single_tab_journey_supported(self):
        """A journey with every stop anchored to the same tab is a
        within-tab funnel — this is the user's "narrow from top list to
        short list" case."""
        anchor = PyObjectId()
        journey = Journey(
            id="j",
            name="Cohort funnel",
            stops=[
                JourneyStop(id="s1", name="All", anchor_tab_id=anchor),
                JourneyStop(id="s2", name="Filtered", anchor_tab_id=anchor),
            ],
        )
        assert journey.stops[0].anchor_tab_id == anchor
        assert journey.stops[1].anchor_tab_id == anchor

    def test_multi_tab_journey_supported(self):
        """Different anchor per stop = multi-tab journey — walks tabs in
        narrative order without duplicating the sidebar tab nav."""
        tab_a, tab_b, tab_c = PyObjectId(), PyObjectId(), PyObjectId()
        journey = Journey(
            id="j",
            name="QC → Community → Differential",
            stops=[
                JourneyStop(id="s1", name="QC", anchor_tab_id=tab_a),
                JourneyStop(id="s2", name="Community", anchor_tab_id=tab_b),
                JourneyStop(id="s3", name="Differential", anchor_tab_id=tab_c),
            ],
        )
        anchors = [s.anchor_tab_id for s in journey.stops]
        assert len(set(anchors)) == 3


class TestUserDashboardState:
    def test_default_empty_values(self):
        state = UserDashboardState(
            user_id=PyObjectId(),
            parent_dashboard_id=PyObjectId(),
        )
        assert state.global_filter_values == {}
        assert state.last_active_journey_id is None
        assert state.last_active_journey_stop_id is None
        assert state.journey_stops == {}
        assert state.last_active_tab_id is None

    def test_round_trip_values(self):
        state = UserDashboardState(
            user_id=PyObjectId(),
            parent_dashboard_id=PyObjectId(),
            global_filter_values={"gf_a": ["x", "y"], "gf_b": [0, 100]},
            last_active_journey_id="journey_1",
            last_active_journey_stop_id="stop_2",
            journey_stops={"journey_1": "stop_2", "journey_2": "stop_a"},
        )
        dumped = state.model_dump(mode="json")
        assert isinstance(dumped["user_id"], str)
        assert isinstance(dumped["parent_dashboard_id"], str)
        assert dumped["global_filter_values"] == {"gf_a": ["x", "y"], "gf_b": [0, 100]}
        assert dumped["last_active_journey_id"] == "journey_1"
        assert dumped["last_active_journey_stop_id"] == "stop_2"
        assert dumped["journey_stops"]["journey_2"] == "stop_a"


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
        assert dash.journeys == []

    def test_dashboard_data_round_trip(self):
        from depictio.models.models.dashboards import DashboardData
        from depictio.models.models.users import Permission

        dash = DashboardData(
            dashboard_id=PyObjectId(),
            project_id=PyObjectId(),
            title="t",
            permissions=Permission(),
            global_filters=[_make_filter()],
            journeys=[
                Journey(
                    id="j1",
                    name="journey 1",
                    stops=[JourneyStop(id="s1", name="start", anchor_tab_id=PyObjectId())],
                )
            ],
        )
        dumped = dash.model_dump(mode="json")
        assert len(dumped["global_filters"]) == 1
        assert dumped["global_filters"][0]["id"] == "gf_abc"
        assert len(dumped["journeys"]) == 1
        assert dumped["journeys"][0]["name"] == "journey 1"
        assert len(dumped["journeys"][0]["stops"]) == 1
