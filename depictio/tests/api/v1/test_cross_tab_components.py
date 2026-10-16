"""Contract for ``GET /dashboards/cross_tab_components/{dashboard_id}``.

The endpoint is the viewer's single family request per page load: everything a
tab renders on behalf of its siblings (floating maps and 3D structures, plus
every section marked ``persistent: true``), with each member paired to its
*owning* tab's id so render calls target the owner while viewing a sibling.

It shares its family-resolution prologue (``_resolve_tab_family``) with
``/floating_components``; the refusals are tested here since no other test
covers that helper.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes

MAIN_ID = "507f1f77bcf86cd799439021"
CHILD_ID = "507f1f77bcf86cd799439022"
PROJECT_ID = "507f1f77bcf86cd799439012"


def _main_tab(**overrides) -> dict:
    tab = {
        "dashboard_id": MAIN_ID,
        "project_id": PROJECT_ID,
        "parent_dashboard_id": None,
        "title": "Main",
        "tab_order": 0,
        "stored_metadata": [
            {
                "index": "sample-filter",
                "component_type": "interactive",
                "section": "Sample filters",
                "dc_id": "dc-meta",
                "column_name": "sample",
            },
            {"index": "qc-figure", "component_type": "figure", "section": None},
        ],
        "filter_sections": [{"name": "Sample filters", "persistent": True}],
        "grid_sections": [],
        "right_panel_layout_data": [],
    }
    tab.update(overrides)
    return tab


def _child_tab(**overrides) -> dict:
    tab = {
        "dashboard_id": CHILD_ID,
        "project_id": PROJECT_ID,
        "parent_dashboard_id": MAIN_ID,
        "title": "Community",
        "tab_order": 1,
        "stored_metadata": [
            {"index": "metadata-table", "component_type": "table", "section": "Sample metadata"},
            {
                "index": "floaty",
                "component_type": "map",
                "placement": "floating",
                "section": None,
            },
        ],
        "filter_sections": [],
        "grid_sections": [
            {"name": "Sample metadata", "persistent": True},
            {"name": "Not shared", "persistent": False},
        ],
        "right_panel_layout_data": [
            {"i": "box-metadata-table", "x": 0, "y": 4, "w": 8, "h": 6},
            {"i": "unrelated", "x": 0, "y": 0, "w": 2, "h": 2},
        ],
    }
    tab.update(overrides)
    return tab


class _Ctx:
    """Patches the collection + permission gate the endpoint reaches for."""

    def __init__(self, tabs: list[dict], *, permitted: bool = True, lookup_id: str = MAIN_ID):
        by_id = {t["dashboard_id"]: t for t in tabs}
        found = by_id.get(lookup_id)

        class _Collection:
            def find_one(_self, *a, **k):
                return found

            def find(_self, *a, **k):
                return list(tabs)

        self._patches = [
            patch.object(routes, "dashboards_collection", _Collection()),
            patch.object(routes, "check_project_permission", lambda *a, **k: permitted),
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


def _call(dashboard_id: str = MAIN_ID):
    return routes.get_cross_tab_components(dashboard_id, current_user=None)


# ---------------------------------------------------------------------------
# Family-resolution prologue (shared with /floating_components)
# ---------------------------------------------------------------------------


def test_unknown_dashboard_is_404() -> None:
    with _Ctx([], lookup_id="nope"), pytest.raises(HTTPException) as exc:
        _call()
    assert exc.value.status_code == 404


def test_permission_denied_is_403() -> None:
    with _Ctx([_main_tab()], permitted=False), pytest.raises(HTTPException) as exc:
        _call()
    assert exc.value.status_code == 403


def test_main_tab_is_its_own_parent() -> None:
    with _Ctx([_main_tab()]):
        assert _call()["parent_dashboard_id"] == MAIN_ID


def test_child_tab_resolves_the_family_parent() -> None:
    with _Ctx([_main_tab(), _child_tab()], lookup_id=CHILD_ID):
        assert _call(CHILD_ID)["parent_dashboard_id"] == MAIN_ID


# ---------------------------------------------------------------------------
# Fan-out shape
# ---------------------------------------------------------------------------


def test_persistent_sections_carry_owner_kind_members_and_layouts() -> None:
    with _Ctx([_main_tab(), _child_tab()]):
        result = _call()

    by_key = {
        (s["owner_dashboard_id"], s["kind"], s["spec"]["name"]): s
        for s in result["persistent_sections"]
    }
    assert set(by_key) == {
        (MAIN_ID, "filter", "Sample filters"),
        (CHILD_ID, "grid", "Sample metadata"),
    }

    filt = by_key[(MAIN_ID, "filter", "Sample filters")]
    assert [c["metadata"]["index"] for c in filt["components"]] == ["sample-filter"]
    assert filt["components"][0]["dashboard_id"] == MAIN_ID
    assert filt["layouts"] == []  # filter sections carry no grid geometry

    grid = by_key[(CHILD_ID, "grid", "Sample metadata")]
    assert [c["metadata"]["index"] for c in grid["components"]] == ["metadata-table"]
    assert grid["components"][0]["dashboard_id"] == CHILD_ID
    assert grid["owner_tab_title"] == "Community"
    # Only the owner-tab layout entries for the section's members, raw
    # (``box-`` prefix intact) so the client reuses its normal parsing.
    assert grid["layouts"] == [{"i": "box-metadata-table", "x": 0, "y": 4, "w": 8, "h": 6}]


def test_non_persistent_sections_are_not_fanned_out() -> None:
    with _Ctx([_main_tab(), _child_tab()]):
        names = {s["spec"]["name"] for s in _call()["persistent_sections"]}
    assert "Not shared" not in names


def test_membership_splits_interactive_from_grid() -> None:
    """An interactive component sharing a grid section's name must not leak
    into the grid fan-out (mirrors the viewer's ``isFilterMember`` rule)."""
    child = _child_tab()
    child["stored_metadata"].append(
        {"index": "stray-control", "component_type": "interactive", "section": "Sample metadata"}
    )
    with _Ctx([_main_tab(), child]):
        result = _call()
    grid = next(s for s in result["persistent_sections"] if s["kind"] == "grid")
    assert [c["metadata"]["index"] for c in grid["components"]] == ["metadata-table"]


def test_floating_maps_stay_out_of_persistent_sections() -> None:
    """A floating map already fans out through ``floating`` — listing it in a
    persistent section too would render it twice."""
    child = _child_tab()
    child["stored_metadata"][1]["section"] = "Sample metadata"
    with _Ctx([_main_tab(), child]):
        result = _call()
    grid = next(s for s in result["persistent_sections"] if s["kind"] == "grid")
    assert [c["metadata"]["index"] for c in grid["components"]] == ["metadata-table"]
    assert [c["metadata"]["index"] for c in result["floating"]] == ["floaty"]


def _structure(**overrides) -> dict:
    meta = {
        "index": "fold",
        "component_type": "advanced_viz",
        "viz_kind": "molecule_3d",
        "placement": "floating",
        "floating_initial_state": "compact",
        "section": None,
    }
    meta.update(overrides)
    return meta


def test_floating_structures_fan_out_beside_floating_maps() -> None:
    """A floating molecule_3d is served like a floating map: same shape, paired
    with the tab that owns it, in tab order."""
    main = _main_tab()
    main["stored_metadata"].append(_structure())
    with _Ctx([main, _child_tab()]):
        result = _call()
    floating = result["floating"]
    assert [(c["dashboard_id"], c["metadata"]["index"]) for c in floating] == [
        (MAIN_ID, "fold"),
        (CHILD_ID, "floaty"),
    ]
    assert floating[0]["tab_title"] == "Main"
    assert floating[0]["metadata"]["viz_kind"] == "molecule_3d"
    # The map path is unchanged.
    assert floating[1]["metadata"]["component_type"] == "map"


def test_advanced_viz_on_the_grid_or_of_another_kind_does_not_float() -> None:
    """Stored metadata never met the lite model's check: a grid tile, and a tile
    of a kind the panel cannot hold, both stay on the grid the viewer draws."""
    main = _main_tab()
    main["stored_metadata"] += [
        _structure(index="on-grid", placement="grid"),
        _structure(index="no-placement", placement=None),
        _structure(index="volcano", viz_kind="volcano"),
    ]
    with _Ctx([main, _child_tab()]):
        result = _call()
    assert [c["metadata"]["index"] for c in result["floating"]] == ["floaty"]


def test_floating_structures_stay_out_of_persistent_sections() -> None:
    """Like a floating map, a floating structure fans out through `floating`; a
    persistent section naming it would draw it a second time."""
    child = _child_tab()
    child["stored_metadata"].append(_structure(section="Sample metadata"))
    with _Ctx([_main_tab(), child]):
        result = _call()
    grid = next(s for s in result["persistent_sections"] if s["kind"] == "grid")
    assert [c["metadata"]["index"] for c in grid["components"]] == ["metadata-table"]
    assert "fold" in [c["metadata"]["index"] for c in result["floating"]]


def test_a_grid_structure_in_a_persistent_section_still_fans_out_there() -> None:
    child = _child_tab()
    child["stored_metadata"].append(
        _structure(index="grid-fold", placement="grid", section="Sample metadata")
    )
    with _Ctx([_main_tab(), child]):
        result = _call()
    grid = next(s for s in result["persistent_sections"] if s["kind"] == "grid")
    assert [c["metadata"]["index"] for c in grid["components"]] == [
        "metadata-table",
        "grid-fold",
    ]


def test_floating_slice_matches_the_floating_components_endpoint() -> None:
    with _Ctx([_main_tab(), _child_tab()]):
        cross = _call()
        legacy = routes.get_floating_components(MAIN_ID, current_user=None)
    assert cross["floating"] == legacy["components"]
    assert cross["parent_dashboard_id"] == legacy["parent_dashboard_id"]


def test_family_without_persistent_sections_returns_empty_list() -> None:
    child = _child_tab(grid_sections=[])
    main = _main_tab(filter_sections=[])
    with _Ctx([main, child]):
        assert _call()["persistent_sections"] == []


def test_pin_reaches_the_client_verbatim() -> None:
    """`pin` decides which edge the viewer's host renders the section at, so it
    has to survive the fan-out — the endpoint hands the spec back untouched."""
    child = _child_tab(
        grid_sections=[{"name": "Sample metadata", "persistent": True, "pin": "bottom"}]
    )
    with _Ctx([_main_tab(), child]):
        result = _call()
    grid = next(s for s in result["persistent_sections"] if s["kind"] == "grid")
    assert grid["spec"]["pin"] == "bottom"


def test_filter_bar_members_fan_out_with_their_grid_section() -> None:
    """A grid section drawn as a filter bar (`display: strip`) holds the
    interactive components naming it, so a persistent one fans those out as
    grid members — and they must not also appear under a same-named filter
    section, which would render them twice on the sibling tab."""
    main = _main_tab(
        filter_sections=[{"name": "Filters", "persistent": True}],
        grid_sections=[{"name": "Filters", "persistent": True, "display": "strip"}],
    )
    main["stored_metadata"][0]["section"] = "Filters"
    with _Ctx([main, _child_tab()]):
        result = _call()
    by_kind = {
        s["kind"]: s for s in result["persistent_sections"] if s["owner_dashboard_id"] == MAIN_ID
    }
    assert [c["metadata"]["index"] for c in by_kind["grid"]["components"]] == ["sample-filter"]
    assert by_kind["filter"]["components"] == []
    assert by_kind["grid"]["spec"]["display"] == "strip"


def test_section_filter_bar_members_fan_out_with_their_grid_section() -> None:
    """A grid section with its own filter bar (`filter_bar: true`) holds the
    interactive components naming it, exactly like a `display: strip` bar: a
    persistent one fans them out with its tiles, never under the same-named
    filter section."""
    main = _main_tab(
        filter_sections=[{"name": "Key figures", "persistent": True}],
        grid_sections=[{"name": "Key figures", "persistent": True, "filter_bar": True}],
    )
    main["stored_metadata"][0]["section"] = "Key figures"
    main["stored_metadata"][1]["section"] = "Key figures"
    with _Ctx([main, _child_tab()]):
        result = _call()
    by_kind = {
        s["kind"]: s for s in result["persistent_sections"] if s["owner_dashboard_id"] == MAIN_ID
    }
    assert [c["metadata"]["index"] for c in by_kind["grid"]["components"]] == [
        "sample-filter",
        "qc-figure",
    ]
    assert by_kind["filter"]["components"] == []
    assert by_kind["grid"]["spec"]["filter_bar"] is True
