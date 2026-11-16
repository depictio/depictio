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
    # declared sections in order, then the persistent "Raw Data" section it
    # pins to the bottom of every tab — written once, at the bottom of the
    # first tab that shows it, not after the last tab where it would read as
    # part of that one — then the child tab.
    assert names == [
        "Species",
        "Cohort",
        "Morphometrics",
        "Composition",
        "Raw Data",
        "Island & Season",
        "Island composition",
        "Across seasons",
    ]
    levels = {h.text: h.level for h in headings}
    assert levels["Species"] == 1
    assert levels["Cohort"] == 2
    assert levels["Island & Season"] == 2
    assert levels["Island composition"] == 3
    assert levels["Raw Data"] == 2
    raw = next(h for h in headings if h.text == "Raw Data")
    assert raw.persistent and raw.collapsed  # the dashboard opens it folded
    persistent = [u for u in units if isinstance(u, ComponentUnit) and u.persistent]
    assert [u.meta["component_type"] for u in persistent] == ["text", "table"]


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
    # The tab's loose tiles come before its sections, as the grid draws them.
    assert order == ["u2", "u1", "a", "c", "b", "z"]


def test_grid_layout_orders_tiles_when_the_metadata_carries_none():
    """Seeds and the editor store positions in `right_panel_layout_data`."""
    tab = {
        "title": "T",
        "is_main_tab": True,
        "stored_metadata": [
            {"index": "late", "component_type": "figure"},
            {"index": "early", "component_type": "figure"},
        ],
        "right_panel_layout_data": [
            {"i": "box-late", "x": 0, "y": 9},
            {"i": "box-early", "x": 0, "y": 1},
        ],
    }
    order = [u.meta["index"] for u in ordered_units([tab]) if isinstance(u, ComponentUnit)]
    assert order == ["early", "late"]


def test_live_tab_order_text_then_pinned_top_then_tiles_then_sections():
    main = {
        "dashboard_id": "m",
        "title": "Main",
        "is_main_tab": True,
        "grid_sections": [
            {"name": "Own", "collapsed": True},
            {"name": "Shared", "persistent": True, "pin": "top"},
            {"name": "Foot", "persistent": True, "pin": "bottom", "exclude_tabs": ["Main"]},
        ],
        "stored_metadata": [
            {"index": "own", "component_type": "figure", "section": "Own"},
            {"index": "shared", "component_type": "table", "section": "Shared"},
            {"index": "foot", "component_type": "table", "section": "Foot"},
            {"index": "map", "component_type": "map", "placement": "floating"},
            {"index": "intro", "component_type": "text", "layout": {"x": 0, "y": 0}},
            {"index": "loose", "component_type": "figure", "layout": {"x": 0, "y": 5}},
        ],
    }
    child = {
        "dashboard_id": "c",
        "title": "Child",
        "parent_dashboard_id": "m",
        "tab_order": 1,
        "stored_metadata": [{"index": "kid", "component_type": "figure"}],
    }
    units = ordered_units([main, child])
    flat = [u.text if isinstance(u, MarkdownUnit) else u.meta["index"] for u in units]
    assert flat == [
        "Main",
        "intro",
        "Shared",
        "shared",
        "loose",
        "map",
        "Own",
        "own",
        "Child",
        "kid",
        # Excluded from the main tab: the first tab that shows it hosts it.
        "Foot",
        "foot",
    ]
    own = next(u for u in units if isinstance(u, MarkdownUnit) and u.text == "Own")
    assert own.collapsed
    foot = next(u for u in units if isinstance(u, MarkdownUnit) and u.text == "Foot")
    assert foot.persistent and foot.exclude_tabs == ("Main",)


def test_ampliseq_overview_reads_like_the_live_tab(ampliseq_tabs):
    units = ordered_units(ampliseq_tabs)
    first_child = next(
        i for i, u in enumerate(units) if isinstance(u, MarkdownUnit) and u.kind == "tab" and i
    )
    overview = [
        u.text if isinstance(u, MarkdownUnit) else u.meta["index"] for u in units[:first_child]
    ]
    assert overview[:5] == ["Overview", "ov-hero", "ov-about", "ov-run", "ov-steps"]
    assert overview.index("Key figures") < overview.index("Findings")
    assert overview.index("Findings") < overview.index("How to read this dashboard")
    findings = overview[
        overview.index("Findings") + 1 : overview.index("How to read this dashboard")
    ]
    assert findings == [
        "ov-findings",
        "ov-hl-composition",
        "ov-hl-volcano",
        "ov-hl-ordination",
        "ov-tree",
    ]
    # Excluded from the Overview, so not in its part.
    assert "Sample sheet" not in overview


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


def test_each_tab_leads_with_its_own_subtitle(ampliseq_tabs):
    tabs = [
        u for u in ordered_units(ampliseq_tabs) if isinstance(u, MarkdownUnit) and u.kind == "tab"
    ]
    by_name = {t.text: t.description for t in tabs}
    assert by_name["Overview"].startswith("Ammer catchment")
    assert by_name["Phylogeny"] == "How are the ASVs related, and how deeply are they classified?"
