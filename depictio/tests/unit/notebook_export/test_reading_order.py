"""The 2D → 1D reading order, on the seeded penguins family."""

from depictio.api.v1.services.notebook_export.reading_order import (
    ComponentUnit,
    MarkdownUnit,
    order_tabs,
    ordered_units,
)


def _titles(units):
    return [
        (u.kind, u.level, u.text)
        if isinstance(u, MarkdownUnit)
        else ("tile", u.meta["component_type"], (u.meta.get("title") or "")[:20])
        for u in units
    ]


def test_main_tab_comes_first_even_when_listed_last(penguins_tabs):
    reordered = list(reversed(penguins_tabs))
    assert order_tabs(reordered)[0]["title"] == "Penguins Species Analysis"


def test_penguins_family_order(penguins_tabs):
    units = ordered_units(penguins_tabs)
    headings = [u for u in units if isinstance(u, MarkdownUnit)]
    names = [h.text for h in headings]
    # Main tab (under its own sidebar label, not the dashboard's title), its
    # declared sections in order, then the child tab, then the persistent
    # "Raw Data" section pinned bottom by the parent.
    assert names == [
        "Species",
        "Cohort",
        "Morphometrics",
        "Composition",
        "Island & Season",
        "Island composition",
        "Across seasons",
        "Raw Data",
    ]
    levels = {h.text: h.level for h in headings}
    assert levels["Species"] == 1
    assert levels["Cohort"] == 2
    assert levels["Island & Season"] == 2
    assert levels["Island composition"] == 3
    assert levels["Raw Data"] == 2  # persistent: rendered at family level
    # The last two units are the Raw Data text and table.
    tail = [u for u in units if isinstance(u, ComponentUnit)][-2:]
    assert [u.meta["component_type"] for u in tail] == ["text", "table"]
    assert all(u.persistent for u in tail)


def test_filters_are_not_tiles_and_every_tile_appears_once(penguins_tabs):
    units = ordered_units(penguins_tabs)
    tiles = [u for u in units if isinstance(u, ComponentUnit)]
    assert all(u.meta["component_type"] != "interactive" for u in tiles)
    indexes = [u.meta["index"] for u in tiles]
    assert len(indexes) == len(set(indexes))
    expected = {
        m["index"]
        for tab in penguins_tabs
        for m in tab["stored_metadata"]
        if m["component_type"] != "interactive"
    }
    assert set(indexes) == expected


def test_layout_sorts_within_a_section_and_falls_back_to_stored_order():
    tab = {
        "title": "T",
        "is_main_tab": True,
        "grid_sections": [{"name": "S"}],
        "stored_metadata": [
            {"index": "c", "component_type": "card", "section": "S", "layout": {"x": 4, "y": 0}},
            {"index": "a", "component_type": "card", "section": "S", "layout": {"x": 0, "y": 0}},
            {"index": "b", "component_type": "card", "section": "S", "layout": {"x": 0, "y": 1}},
            {"index": "z", "component_type": "text", "section": "S"},  # no layout → last
            {"index": "u2", "component_type": "figure"},
            {"index": "u1", "component_type": "figure"},
        ],
    }
    units = ordered_units([tab])
    order = [u.meta["index"] for u in units if isinstance(u, ComponentUnit)]
    assert order == ["a", "c", "b", "z", "u2", "u1"]


def test_undeclared_sections_follow_declared_ones():
    tab = {
        "title": "T",
        "is_main_tab": True,
        "grid_sections": [{"name": "Declared"}],
        "stored_metadata": [
            {"index": "x", "component_type": "card", "section": "Mystery"},
            {"index": "y", "component_type": "card", "section": "Declared"},
        ],
    }
    names = [u.text for u in ordered_units([tab]) if isinstance(u, MarkdownUnit)]
    assert names == ["T", "Declared", "Mystery"]


def test_ampliseq_seeds_flatten_without_losing_tiles(ampliseq_tabs):
    units = ordered_units(ampliseq_tabs)
    tiles = [u for u in units if isinstance(u, ComponentUnit)]
    expected = {
        m["index"]
        for tab in ampliseq_tabs
        for m in tab["stored_metadata"]
        if m["component_type"] != "interactive"
    }
    assert {u.meta["index"] for u in tiles} == expected
