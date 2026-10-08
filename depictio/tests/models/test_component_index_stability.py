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
