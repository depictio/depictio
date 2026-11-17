"""A section keeps its highlights when its one data-bound tile is pruned.

The sarek Overview's Findings section holds a somatic genome view (bound to a
collection a germline-only run lacks) next to highlights that draw figures of
other tabs. Pruning the genome view used to orphan the section and take the
highlights, which the run could still draw, with it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

import depictio.api.v1.endpoints.dashboards_endpoints.routes as routes  # noqa: E402


def _stored() -> dict:
    return {
        "stored_metadata": [
            {"index": "text", "component_type": "text", "section": "Findings"},
            {
                "index": "hl",
                "component_type": "highlight",
                "section": "Findings",
                "source_tab": "Variant yield",
                "source_component": "vy-spectrum-sbs",
            },
            {
                "index": "genome",
                "component_type": "advanced_viz",
                "section": "Findings",
                "data_collection_tag": "somatic_variants",
                "dc_id": None,
            },
        ],
        "right_panel_layout_data": [],
        "grid_sections": [{"name": "Findings"}],
    }


def test_a_highlight_counts_as_data_bound():
    sections = routes._data_bound_sections([{"component_type": "highlight", "section": "Findings"}])
    assert sections == {("grid", "Findings")}


def test_the_section_survives_when_only_the_bound_tile_is_pruned(monkeypatch):
    monkeypatch.setattr(routes, "_build_dc_meta", lambda project_id: {})
    stored = _stored()
    routes._filter_unresolved_components(stored, None)
    assert [c["index"] for c in stored["stored_metadata"]] == ["text", "hl"]
    assert [s["name"] for s in stored["grid_sections"]] == ["Findings"]


def test_a_text_only_section_is_still_left_alone():
    sections = routes._data_bound_sections([{"component_type": "text", "section": "About"}])
    assert sections == set()
