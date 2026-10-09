"""Component identity has to survive a re-import.

Every feature that follows a component through time — version history,
restoring one component, comparing a chart against its former self — matches on
`index` across snapshots. When ids are regenerated per import, none of them can
match anything, and the symptom is not an error: the component-history modal
calmly reports "this component did not exist in that version" about a component
that plainly did.

These tests pin the property that prevents that, and the boundaries around it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.models.components.lite import index_from_tag
from depictio.models.models.dashboards import DashboardDataLite

_YAML = """
title: "Fixture"
project_tag: "demo"
components:
  - tag: intro
    component_type: text
    title: "{intro_title}"
    body: "hello"
    layout: {{x: 0, y: 0, w: 8, h: 1}}

  - tag: count-card
    component_type: card
    workflow_tag: python/wf
    data_collection_tag: dc
    aggregation: count
    column_name: variety
    column_type: object
    title: "{card_title}"
    layout: {{x: 0, y: 1, w: 4, h: 2}}
"""


def _indices(**kwargs) -> dict[str, str]:
    text = _YAML.format(
        intro_title=kwargs.get("intro_title", "Intro"), card_title=kwargs.get("card_title", "Count")
    )
    full = DashboardDataLite.from_yaml(text).to_full()
    return {c["title"]: c["index"] for c in full["stored_metadata"]}


def test_the_same_tag_yields_the_same_index() -> None:
    assert index_from_tag("count-card") == index_from_tag("count-card")


def test_different_tags_do_not_collide() -> None:
    assert index_from_tag("count-card") != index_from_tag("count-card-2")


def test_reimporting_the_same_yaml_keeps_component_ids() -> None:
    assert _indices() == _indices()


def test_ids_survive_a_component_being_retitled() -> None:
    """The demo retypes a card between versions: same component, new question.

    If the id moved with the title, that card would look like a deletion plus
    an addition, and its history would be empty on both sides.
    """
    before = _indices(card_title="Mean Petal Length")
    after = _indices(card_title="Varieties Surveyed")

    assert set(before.values()) == set(after.values())


def test_untagged_components_still_get_unique_ids() -> None:
    """No tag means nothing stable to derive from.

    A shared constant would be worse than randomness here: every untagged
    component in the dashboard would become the same component.
    """
    assert index_from_tag(None) != index_from_tag(None)
    assert index_from_tag("") != index_from_tag("")
    assert index_from_tag("   ") != index_from_tag("   ")


def test_an_explicit_index_still_wins() -> None:
    """Documents that already carry an id keep it.

    Existing dashboards were imported before this rule existed; re-importing
    one must not silently renumber its components and orphan their history.
    """
    text = """
title: "Fixture"
project_tag: "demo"
components:
  - tag: intro
    index: "already-assigned-id"
    component_type: text
    title: "Intro"
    body: "hello"
    layout: {x: 0, y: 0, w: 8, h: 1}
"""
    full = DashboardDataLite.from_yaml(text).to_full()
    assert full["stored_metadata"][0]["index"] == "already-assigned-id"


def test_derived_ids_are_uuid_shaped() -> None:
    """Downstream code sniffs UUID-ness to decide what is auto-generated.

    `_regenerate_component_indices` replaces UUID-like indices on import and
    preserves semantic ones. A derived id must read as generated, or the tag
    would have to be unique across every dashboard in the instance.
    """
    index = index_from_tag("count-card")

    assert len(index) == 36
    assert index.count("-") == 4
    assert DashboardDataLite._is_uuid_like(index)


# ── ids are unique within a tab family ─────────────────────────────────────
#
# A child tab reusing a tag of its main tab once derived the same id, so the
# family held two components under one index: the component-history modal and
# a single-component restore found whichever came first, often on the wrong
# tab. A child tab's ids are now scoped by its title; a main tab's are not, so
# every existing main-tab id is unchanged.

_PROJECTS = Path(__file__).resolve().parents[2] / "projects" / "init"


def _child(text: str, title: str = "Petal") -> str:
    return f"is_main_tab: false\nparent_dashboard_tag: Fixture\n{text.replace('Fixture', title, 1)}"


def _ids(text: str) -> list[str]:
    return [c["index"] for c in DashboardDataLite.from_yaml(text).to_full()["stored_metadata"]]


def test_a_main_tab_keeps_its_unscoped_ids() -> None:
    assert set(_indices().values()) == {index_from_tag("intro"), index_from_tag("count-card")}


def test_a_child_tab_scopes_its_ids_by_its_title() -> None:
    text = _YAML.format(intro_title="Intro", card_title="Count")

    main, child = _ids(text), _ids(_child(text))

    assert child == [index_from_tag("intro", "Petal"), index_from_tag("count-card", "Petal")]
    assert not set(main) & set(child)
    # Re-importing the same tab lands on the same ids.
    assert _ids(_child(text)) == child


def test_the_iris_family_shares_no_component_id() -> None:
    """The shipped family that reuses eight tags across its two tabs."""
    main = DashboardDataLite.from_yaml_file(_PROJECTS / "iris/dashboards/overview.yaml").to_full()
    child = DashboardDataLite.from_yaml_file(
        _PROJECTS / "iris/dashboards/petal_analysis.yaml"
    ).to_full()

    main_ids = {c["index"] for c in main["stored_metadata"]}
    child_ids = {c["index"] for c in child["stored_metadata"]}

    assert len(main_ids) == len(main["stored_metadata"])
    assert len(child_ids) == len(child["stored_metadata"])
    assert not main_ids & child_ids


def test_a_child_tabs_explicit_index_is_kept() -> None:
    """An export of a tab whose ids predate scoping states them, and keeps them."""
    text = _child(_YAML.format(intro_title="Intro", card_title="Count")).replace(
        "  - tag: intro\n", f"  - tag: intro\n    index: {index_from_tag('intro')}\n"
    )

    assert _ids(text)[0] == index_from_tag("intro")


def test_two_components_sharing_a_tag_on_one_tab_are_refused() -> None:
    text = _YAML.format(intro_title="Intro", card_title="Count").replace(
        "tag: count-card", "tag: intro"
    )

    with pytest.raises(ValueError, match="tags must be unique within a tab.*'intro'"):
        DashboardDataLite.from_yaml(text)


# ── an export re-imports onto the same ids ─────────────────────────────────


def _round_trip(full: dict) -> dict:
    return DashboardDataLite.from_yaml(DashboardDataLite.from_full(full).to_yaml()).to_full()


def test_export_then_import_keeps_every_id_of_the_iris_versioned_dashboard() -> None:
    full = DashboardDataLite.from_yaml_file(
        _PROJECTS / "iris_versioned/dashboards/v4_complete.yaml"
    ).to_full()

    again = _round_trip(full)

    assert [c["index"] for c in again["stored_metadata"]] == [
        c["index"] for c in full["stored_metadata"]
    ]


def test_export_keeps_the_id_of_a_component_made_in_the_editor() -> None:
    """No tag, so export generates one from the content, and that tag derives
    some other id: the id itself has to be written out, or re-importing the
    export turns the component into a new one with no history."""
    full = DashboardDataLite.from_yaml(_YAML.format(intro_title="I", card_title="C")).to_full()
    made_in_editor = "3f1c2a4e-9b7d-4c1e-8a2f-5d6e7f8a9b0c"
    card = full["stored_metadata"][1]
    old, card["index"] = card["index"], made_in_editor
    card.pop("tag", None)
    for item in full.get("right_panel_layout_data") or []:
        if str(item.get("i", "")).removeprefix("box-") == old:
            item["i"] = f"box-{made_in_editor}"

    again = _round_trip(full)

    assert made_in_editor in [c["index"] for c in again["stored_metadata"]]


def test_export_of_a_child_tab_keeps_its_scoped_ids() -> None:
    full = DashboardDataLite.from_yaml(
        _child(_YAML.format(intro_title="Intro", card_title="Count"))
    ).to_full()

    again = _round_trip(full)

    assert [c["index"] for c in again["stored_metadata"]] == [
        c["index"] for c in full["stored_metadata"]
    ]


# ── the import keeps what the YAML derives or states ───────────────────────


def test_an_import_keeps_a_stated_index_and_a_scoped_one() -> None:
    """``_tag_derived_indices`` lists the ids ``_regenerate_component_indices``
    must leave alone. Listing only ``index_from_tag(tag)`` regenerated an index
    the YAML stated (an export of an editor-made component), and every child
    tab id once scoping applies."""
    # The CLI package's job runs this suite without the API's dependencies.
    pytest.importorskip("fastapi")
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _regenerate_component_indices,
        _tag_derived_indices,
    )

    stated = "3f1c2a4e-9b7d-4c1e-8a2f-5d6e7f8a9b0c"
    text = _child(_YAML.format(intro_title="Intro", card_title="Count")).replace(
        "  - tag: intro\n", f"  - tag: intro\n    index: {stated}\n"
    )
    lite = DashboardDataLite.from_yaml(text)
    full = lite.to_full()
    expected = [c["index"] for c in full["stored_metadata"]]

    _regenerate_component_indices(full, keep_indices=_tag_derived_indices(lite))

    assert [c["index"] for c in full["stored_metadata"]] == expected
    assert expected == [stated, index_from_tag("count-card", "Petal")]
