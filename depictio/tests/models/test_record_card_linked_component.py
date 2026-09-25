"""`RecordCardConfig.linked_component`: tag resolution at import and its validation."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.configs import RecordCardConfig
from depictio.models.components.advanced_viz.record_link import (
    LinkedComponentError,
    emitted_selection_column,
    resolve_linked_components,
    side_panel_pairs,
)
from depictio.models.models.dashboards import DashboardDataLite

pytestmark = pytest.mark.no_db


def _table(tag: str, index: str | None = None, **extra: Any) -> dict[str, Any]:
    comp: dict[str, Any] = {
        "tag": tag,
        "component_type": "table",
        "workflow_tag": "demo",
        "data_collection_tag": "samples",
        "row_selection_enabled": True,
        "row_selection_column": "sample",
        "layout": {"x": 0, "y": 0, "w": 5, "h": 6},
        **extra,
    }
    if index:
        comp["index"] = index
    return comp


def _card(linked: str | None, tag: str = "sample-card") -> dict[str, Any]:
    config: dict[str, Any] = {"viz_kind": "record_card", "id_col": "sample"}
    if linked is not None:
        config["linked_component"] = linked
    return {
        "tag": tag,
        "component_type": "advanced_viz",
        "workflow_tag": "demo",
        "data_collection_tag": "samples",
        "viz_kind": "record_card",
        "config": config,
        "layout": {"x": 5, "y": 0, "w": 3, "h": 6},
    }


def _dashboard(*components: dict[str, Any]) -> dict[str, Any]:
    return {"title": "Demo", "components": list(components)}


def test_config_field_defaults_to_none_and_accepts_a_tag():
    assert RecordCardConfig().linked_component is None
    assert RecordCardConfig(linked_component="samples-table").linked_component == "samples-table"


def test_config_still_forbids_unknown_keys():
    with pytest.raises(ValidationError):
        RecordCardConfig.model_validate({"linked_components": "samples-table"})


def test_to_full_rewrites_the_tag_to_the_source_index():
    lite = DashboardDataLite.model_validate(
        _dashboard(_table("samples-table"), _card("samples-table"))
    )
    full = lite.to_full()
    table, card = full["stored_metadata"]
    assert card["config"]["linked_component"] == table["index"]
    # The lite model is left as written, so a second conversion resolves again.
    again = lite.to_full()["stored_metadata"]
    assert again[1]["config"]["linked_component"] == again[0]["index"]


def test_to_full_resolves_an_explicit_semantic_index():
    lite = DashboardDataLite.model_validate(
        _dashboard(_table("samples-table", index="samples-table-idx"), _card("samples-table-idx"))
    )
    card = lite.to_full()["stored_metadata"][1]
    assert card["config"]["linked_component"] == "samples-table-idx"


def test_unknown_tag_is_a_validation_error_naming_the_card():
    with pytest.raises(ValidationError) as exc:
        DashboardDataLite.model_validate(_dashboard(_table("samples-table"), _card("nope")))
    assert "[sample-card] config.linked_component: 'nope' matches no component" in str(exc.value)


def test_self_link_is_refused():
    with pytest.raises(LinkedComponentError, match="cannot link to itself"):
        resolve_linked_components([_card("sample-card")])


def test_unlinked_cards_resolve_to_nothing():
    assert resolve_linked_components([_table("t"), _card(None)]) == {}


def test_side_panel_pairs_need_same_row_section_and_touching_edges():
    assert side_panel_pairs([_table("t"), _card("t")]) == [(0, 1)]
    left_card = {**_card("t"), "layout": {"x": 0, "y": 0, "w": 3, "h": 6}}
    right_table = _table("t", layout={"x": 3, "y": 0, "w": 5, "h": 6})
    assert side_panel_pairs([right_table, left_card]) == [(0, 1)]
    apart = {**_card("t"), "layout": {"x": 6, "y": 0, "w": 2, "h": 6}}
    assert side_panel_pairs([_table("t"), apart]) == []
    other_section = {**_card("t"), "section": "Elsewhere"}
    assert side_panel_pairs([_table("t"), other_section]) == []


@pytest.mark.parametrize(
    ("comp", "expected"),
    [
        (_table("t"), "sample"),
        (_table("t", row_selection_enabled=False), None),
        (
            {"component_type": "figure", "selection_enabled": True, "selection_column": "run"},
            "run",
        ),
        ({"component_type": "figure", "selection_column": "run"}, None),
        (
            {
                "component_type": "advanced_viz",
                "config": {
                    "viz_kind": "embedding",
                    "selection_enabled": True,
                    "sample_id_col": "s",
                },
            },
            "s",
        ),
        (
            {
                "component_type": "advanced_viz",
                "config": {"viz_kind": "volcano", "selection_enabled": True},
            },
            None,
        ),
        ({"component_type": "card"}, None),
    ],
)
def test_emitted_selection_column(comp: dict[str, Any], expected: str | None):
    assert emitted_selection_column(comp) == expected
