"""A `molecule_3d` tile may float over the dashboard, as a map does.

`placement: floating` lifts the tile out of the grid into a panel reachable from
every tab. It is limited to the kinds in `FLOATING_ADVANCED_VIZ_KINDS` (a protein
structure today), so the panel stays a light module rather than a second grid.

Three layers hold the rule and each is tested here: the component model, the
dashboard model (a component that fails any check falls through the union to a
plain dict, which the component model's own validator never sees), and the
lite/full conversion the importer and the exporter share.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
from depictio.models.components.constants import FLOATING_ADVANCED_VIZ_KINDS
from depictio.models.models.dashboards import DashboardDataLite

_STRUCTURE: dict[str, Any] = {
    "tag": "fold",
    "component_type": "advanced_viz",
    "workflow_tag": "wf/x",
    "data_collection_tag": "residues",
    "viz_kind": "molecule_3d",
    "config": {
        "viz_kind": "molecule_3d",
        "structure_source": "resolve",
        "uniprot_col": "accession",
    },
}

_VOLCANO: dict[str, Any] = {
    "tag": "volcano-1",
    "component_type": "advanced_viz",
    "workflow_tag": "wf/x",
    "data_collection_tag": "de",
    "viz_kind": "volcano",
    "config": {
        "viz_kind": "volcano",
        "feature_id_col": "feature_id",
        "effect_size_col": "effect_size",
        "significance_col": "significance",
    },
}

_CARD: dict[str, Any] = {
    "tag": "n",
    "component_type": "card",
    "workflow_tag": "wf/x",
    "data_collection_tag": "residues",
    "aggregation": "count",
    "column_name": "position",
}


def _dashboard(*components: dict[str, Any]) -> DashboardDataLite:
    return DashboardDataLite(dashboard_id="d1", title="T", components=list(components))


def _stored(full: dict[str, Any], viz_kind: str) -> dict[str, Any]:
    return next(c for c in full["stored_metadata"] if c.get("viz_kind") == viz_kind)


class TestComponentModel:
    def test_defaults_to_a_grid_tile(self):
        comp = AdvancedVizLiteComponent.model_validate(_STRUCTURE)
        assert comp.placement == "grid"
        assert comp.floating_initial_state == "compact"

    def test_molecule_3d_may_float(self):
        comp = AdvancedVizLiteComponent.model_validate({**_STRUCTURE, "placement": "floating"})
        assert comp.placement == "floating"

    @pytest.mark.parametrize("state", ["compact", "expanded", "docked", "hidden"])
    def test_every_opening_state_is_accepted(self, state: str):
        comp = AdvancedVizLiteComponent.model_validate(
            {**_STRUCTURE, "placement": "floating", "floating_initial_state": state}
        )
        assert comp.floating_initial_state == state

    def test_a_floating_kind_that_arrives_through_use_is_accepted(self):
        """`use:` expands to a kind before validation, so the rule sees the real one."""
        comp = AdvancedVizLiteComponent.model_validate(
            {
                "tag": "fold",
                "component_type": "advanced_viz",
                "workflow_tag": "wf/x",
                "data_collection_tag": "residues",
                "use": "famsa/conservation_structure",
                "placement": "floating",
            }
        )
        assert comp.viz_kind == "molecule_3d"
        assert comp.placement == "floating"

    def test_another_kind_is_rejected_with_the_reason(self):
        with pytest.raises(ValidationError) as exc:
            AdvancedVizLiteComponent.model_validate({**_VOLCANO, "placement": "floating"})
        message = str(exc.value)
        assert "Invalid placement 'floating'" in message
        assert "only viz_kind molecule_3d may float" in message
        assert "'volcano'" in message

    def test_another_kind_is_fine_on_the_grid(self):
        comp = AdvancedVizLiteComponent.model_validate({**_VOLCANO, "placement": "grid"})
        assert comp.placement == "grid"

    def test_rejects_unknown_placement(self):
        """'top' is the interactive placement, 'left' the filter panel's."""
        with pytest.raises(ValidationError, match="Invalid placement 'top'"):
            AdvancedVizLiteComponent.model_validate({**_STRUCTURE, "placement": "top"})

    def test_rejects_unknown_floating_initial_state(self):
        with pytest.raises(ValidationError, match="Invalid floating_initial_state 'huge'"):
            AdvancedVizLiteComponent.model_validate(
                {**_STRUCTURE, "placement": "floating", "floating_initial_state": "huge"}
            )

    def test_the_allow_list_is_what_the_message_names(self):
        """Widening the tuple is the only change a new kind needs."""
        assert FLOATING_ADVANCED_VIZ_KINDS == ("molecule_3d",)


class TestDashboardModel:
    def test_accepts_a_floating_structure(self):
        dashboard = _dashboard({**_STRUCTURE, "placement": "floating"}, _CARD)
        assert isinstance(dashboard.components[0], AdvancedVizLiteComponent)

    def test_rejects_another_kind_that_floats(self):
        with pytest.raises(ValidationError) as exc:
            _dashboard({**_VOLCANO, "placement": "floating"})
        message = str(exc.value)
        assert "[volcano-1] placement:" in message
        assert "only viz_kind molecule_3d may float" in message

    def test_rejects_it_when_the_component_fell_through_to_a_dict(self):
        """A config the model refuses leaves a dict behind, which the component
        validator never saw; the kind it carries is still judged."""
        broken = {
            **_VOLCANO,
            "placement": "floating",
            "config": {"viz_kind": "volcano", "no_such_field": 1},
        }
        with pytest.raises(ValidationError, match="only viz_kind molecule_3d may float"):
            _dashboard(broken)

    def test_a_dict_of_no_resolvable_kind_is_left_to_the_check_that_failed_it(self):
        """No kind to judge: its own problem is reported elsewhere, not a kind of None."""
        unresolved = {**_STRUCTURE, "placement": "floating", "config": {"no_such_field": 1}}
        del unresolved["viz_kind"]
        dashboard = _dashboard(unresolved)
        assert isinstance(dashboard.components[0], dict)

    def test_a_grid_tile_of_any_kind_is_untouched(self):
        dashboard = _dashboard(_VOLCANO, _STRUCTURE)
        assert [c.placement for c in dashboard.components] == ["grid", "grid"]  # type: ignore[union-attr]


class TestLiteToFull:
    """A floating tile reaches stored_metadata and claims no grid slot."""

    def test_floating_structure_leaves_the_grid_but_not_the_dashboard(self):
        full = _dashboard({**_STRUCTURE, "placement": "floating"}, _CARD).to_full()
        stored = _stored(full, "molecule_3d")
        assert stored["placement"] == "floating"
        assert stored["floating_initial_state"] == "compact"
        indices = {item["i"] for item in full["right_panel_layout_data"]}
        assert f"box-{stored['index']}" not in indices
        assert len(indices) == 1, "only the card occupies the grid"

    def test_the_opening_state_travels(self):
        full = _dashboard(
            {**_STRUCTURE, "placement": "floating", "floating_initial_state": "docked"}
        ).to_full()
        assert _stored(full, "molecule_3d")["floating_initial_state"] == "docked"

    def test_floating_structure_leaves_no_gap_in_the_grid(self):
        """Skipping it must not consume an auto-layout row the grid then renders blank."""
        full = _dashboard({**_STRUCTURE, "placement": "floating"}, _CARD).to_full()
        assert full["right_panel_layout_data"][0]["y"] == 0

    def test_a_grid_tile_stores_neither_key(self):
        """Written only when floating: every advanced viz already stored keeps its
        shape, and with it its snapshot hash."""
        full = _dashboard(_STRUCTURE, _VOLCANO).to_full()
        for stored in full["stored_metadata"]:
            assert "placement" not in stored
            assert "floating_initial_state" not in stored
        assert len(full["right_panel_layout_data"]) == 2


class TestFullToLite:
    """Export writes what the author set and nothing else."""

    @staticmethod
    def _exported(**overrides: Any) -> dict[str, Any]:
        stored = {
            "index": "fold-1",
            "component_type": "advanced_viz",
            "wf_id": "wf",
            "dc_id": "dc",
            "viz_kind": "molecule_3d",
            "config": dict(_STRUCTURE["config"]),
            **overrides,
        }
        lite = DashboardDataLite.from_full(
            {
                "dashboard_id": "d1",
                "title": "T",
                "project_id": "p1",
                "version": "1.0.0",
                "stored_metadata": [stored],
            }
        )
        comp = lite.components[0]
        return comp if isinstance(comp, dict) else comp.model_dump(exclude_unset=True)

    def test_a_grid_tile_exports_no_placement(self):
        comp = self._exported(placement="grid", floating_initial_state="compact")
        assert "placement" not in comp
        assert "floating_initial_state" not in comp

    def test_a_tile_that_never_set_it_exports_none(self):
        comp = self._exported()
        assert "placement" not in comp
        assert "floating_initial_state" not in comp

    def test_floating_is_exported_and_a_default_state_is_not(self):
        comp = self._exported(placement="floating", floating_initial_state="compact")
        assert comp["placement"] == "floating"
        assert "floating_initial_state" not in comp

    def test_a_chosen_opening_state_is_exported(self):
        comp = self._exported(placement="floating", floating_initial_state="hidden")
        assert comp["placement"] == "floating"
        assert comp["floating_initial_state"] == "hidden"


class TestRoundTrip:
    @pytest.mark.parametrize("state", ["compact", "expanded", "docked", "hidden"])
    def test_lite_to_full_to_lite_keeps_the_placement(self, state: str):
        lite = _dashboard(
            {**_STRUCTURE, "placement": "floating", "floating_initial_state": state}, _CARD
        )
        back = DashboardDataLite.from_full(lite.to_full())
        comp = back.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump()
        assert comp["viz_kind"] == "molecule_3d"
        assert comp["placement"] == "floating"
        assert comp["floating_initial_state"] == state

    def test_a_second_pass_changes_nothing(self):
        """Export then import then export lands on the same stored component, so a
        re-import never moves a floating tile or loses its opening state."""
        lite = _dashboard(
            {**_STRUCTURE, "placement": "floating", "floating_initial_state": "expanded"}
        )
        first = lite.to_full()
        second = DashboardDataLite.from_full(first).to_full()
        keys = ("placement", "floating_initial_state", "viz_kind", "config")
        assert {k: _stored(first, "molecule_3d")[k] for k in keys} == {
            k: _stored(second, "molecule_3d")[k] for k in keys
        }
        assert second["right_panel_layout_data"] == []

    def test_survives_a_yaml_round_trip(self):
        lite = _dashboard(
            {**_STRUCTURE, "placement": "floating", "floating_initial_state": "docked"}
        )
        reimported = DashboardDataLite(**yaml.safe_load(lite.to_yaml()))
        comp = reimported.components[0]
        assert isinstance(comp, AdvancedVizLiteComponent)
        assert comp.placement == "floating"
        assert comp.floating_initial_state == "docked"
