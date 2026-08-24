"""Unit tests for self-adapting dashboard layout helpers.

Covers the two engine guarantees added for per-run nf-core dashboards:

* ``_recompact_main_grid`` — after components are dropped, the main grid re-flows
  so no half-width card is left alone on a row and horizontal gaps are closed.
* ``_tab_meets_minimum`` — a tab survives only if it keeps at least one filter
  and one non-metadata visualisation component.

All three helpers are pure (no DB), so they are tested directly.
"""

from __future__ import annotations

from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _GRID_COLS,
    _component_has_data,
    _recompact_main_grid,
    _tab_has_visualization_components,
    _tab_meets_minimum,
)


def _rows(items):
    """Group repacked items by their y (row) for assertions."""
    by_y: dict[int, list[dict]] = {}
    for it in items:
        by_y.setdefault(it["y"], []).append(it)
    return by_y


# --------------------------------------------------------------------------- #
# _recompact_main_grid
# --------------------------------------------------------------------------- #


def test_recompact_empty_is_noop():
    assert _recompact_main_grid([]) == []


def test_recompact_widens_lone_half_width_card():
    # Two w:4 cards shared a row; the right one was dropped, leaving a lone w:4.
    items = [{"i": "box-a", "x": 0, "y": 1, "w": 4, "h": 2, "static": True}]
    out = _recompact_main_grid(items)
    assert len(out) == 1
    assert out[0]["w"] == _GRID_COLS  # widened to fill the row
    assert out[0]["x"] == 0
    assert out[0]["static"] is True  # non-geometry keys preserved


def test_recompact_packs_survivors_onto_one_row():
    # Two w:4 cards originally on different rows (a w:8 figure between them was
    # dropped) should pack side-by-side rather than each sitting alone.
    items = [
        {"i": "box-a", "x": 0, "y": 0, "w": 4, "h": 2},
        {"i": "box-b", "x": 0, "y": 6, "w": 4, "h": 2},
    ]
    out = _recompact_main_grid(items)
    rows = _rows(out)
    assert len(rows) == 1
    row = sorted(rows[0], key=lambda it: it["x"])
    assert [it["i"] for it in row] == ["box-a", "box-b"]
    assert [it["x"] for it in row] == [0, 4]
    assert all(it["w"] == 4 for it in row)  # not widened — row is full


def test_recompact_full_width_items_stack_in_order():
    items = [
        {"i": "box-text", "x": 0, "y": 0, "w": 8, "h": 1},
        {"i": "box-fig", "x": 0, "y": 1, "w": 8, "h": 6},
        {"i": "box-table", "x": 0, "y": 7, "w": 8, "h": 4},
    ]
    out = _recompact_main_grid(items)
    # Reading order preserved, no gaps, each on its own row.
    assert [it["i"] for it in out] == ["box-text", "box-fig", "box-table"]
    assert [it["y"] for it in out] == [0, 1, 7]
    assert all(it["x"] == 0 for it in out)


def test_recompact_row_height_is_max_of_row():
    # A row of two items with differing heights advances y by the taller one.
    items = [
        {"i": "box-a", "x": 0, "y": 0, "w": 4, "h": 2},
        {"i": "box-b", "x": 4, "y": 0, "w": 4, "h": 5},
        {"i": "box-c", "x": 0, "y": 5, "w": 8, "h": 3},
    ]
    out = _recompact_main_grid(items)
    by_i = {it["i"]: it for it in out}
    assert by_i["box-a"]["y"] == 0 and by_i["box-b"]["y"] == 0
    assert by_i["box-c"]["y"] == 5  # below the h:5 item, not the h:2 one


def test_recompact_clamps_oversized_width():
    items = [{"i": "box-a", "x": 0, "y": 0, "w": 99, "h": 4}]
    out = _recompact_main_grid(items)
    assert out[0]["w"] == _GRID_COLS


# --------------------------------------------------------------------------- #
# _recompact_main_grid — section awareness
# --------------------------------------------------------------------------- #


def test_recompact_without_sections_is_unchanged():
    """A dashboard that declares no section packs as one grid, as it always did."""
    items = [
        {"i": "box-a", "x": 0, "y": 0, "w": 4, "h": 2},
        {"i": "box-b", "x": 0, "y": 2, "w": 4, "h": 2},
    ]
    flat = _recompact_main_grid(items)
    sectionless = _recompact_main_grid(items, {"box-a": None, "box-b": None})
    assert flat == sectionless
    # Both survivors pack onto one row rather than each sitting alone.
    assert len(_rows(flat)) == 1


def test_recompact_never_packs_across_a_section_boundary():
    """Two half-width cards in different sections must not share a row: each
    section draws its own sub-grid, so that row would straddle two headers."""
    items = [
        {"i": "box-a", "x": 0, "y": 0, "w": 4, "h": 2},
        {"i": "box-b", "x": 0, "y": 2, "w": 4, "h": 2},
    ]
    out = _recompact_main_grid(items, {"box-a": "QC", "box-b": "Taxonomy"})
    by_i = {it["i"]: it for it in out}
    assert by_i["box-a"]["y"] != by_i["box-b"]["y"]
    # Alone in its section, each is widened to the full grid.
    assert by_i["box-a"]["w"] == _GRID_COLS
    assert by_i["box-b"]["w"] == _GRID_COLS


def test_recompact_stacks_sections_without_overlap():
    """Sections stack, so the flat array stays valid as one grid — which is what
    the dashboard falls back to if its sections are later removed."""
    items = [
        {"i": "box-a", "x": 0, "y": 0, "w": 8, "h": 3},
        {"i": "box-b", "x": 0, "y": 3, "w": 8, "h": 2},
    ]
    out = _recompact_main_grid(items, {"box-a": "QC", "box-b": "Taxonomy"})
    by_i = {it["i"]: it for it in out}
    assert by_i["box-a"]["y"] == 0
    assert by_i["box-b"]["y"] == 3  # starts below the first section's bottom


def test_recompact_packs_within_a_section():
    """Inside one section the existing shelf-packing still applies."""
    items = [
        {"i": "box-a", "x": 0, "y": 0, "w": 4, "h": 2},
        {"i": "box-b", "x": 0, "y": 2, "w": 4, "h": 2},
        {"i": "box-c", "x": 0, "y": 4, "w": 8, "h": 2},
    ]
    out = _recompact_main_grid(items, {"box-a": "QC", "box-b": "QC", "box-c": "Taxonomy"})
    by_i = {it["i"]: it for it in out}
    assert by_i["box-a"]["y"] == by_i["box-b"]["y"]  # same section → same row
    assert by_i["box-c"]["y"] == 2


# --------------------------------------------------------------------------- #
# _tab_meets_minimum / _tab_has_visualization_components
# --------------------------------------------------------------------------- #


def _tab(*components):
    return {"stored_metadata": list(components)}


def test_tab_meets_minimum_filter_plus_viz():
    dc_meta = {"taxonomy": {"metatype": "Aggregated"}}
    tab = _tab(
        {"component_type": "interactive", "data_collection_tag": "taxonomy"},
        {"component_type": "figure", "data_collection_tag": "taxonomy"},
    )
    assert _tab_meets_minimum(tab, dc_meta) is True


def test_tab_below_minimum_when_no_filter():
    # One lonely plot, no filter (the nanopore Sample-QC case) → dropped.
    dc_meta = {"nextclade": {"metatype": "Aggregated"}}
    tab = _tab({"component_type": "figure", "data_collection_tag": "nextclade"})
    assert _tab_meets_minimum(tab, dc_meta) is False


def test_tab_below_minimum_when_only_metadata_viz():
    # Filter present but the only surviving viz is a metadata table → dropped.
    dc_meta = {"metadata": {"metatype": "Metadata"}}
    tab = _tab(
        {"component_type": "interactive", "data_collection_tag": "metadata"},
        {"component_type": "table", "data_collection_tag": "metadata"},
    )
    assert _tab_has_visualization_components(tab, dc_meta) is False
    assert _tab_meets_minimum(tab, dc_meta) is False


def test_tab_below_minimum_when_no_viz():
    tab = _tab({"component_type": "interactive", "data_collection_tag": "x"})
    assert _tab_meets_minimum(tab, {}) is False


def test_tab_below_minimum_when_viz_but_no_filter():
    # Mandatory minimum: every surviving tab must keep a filter. A tab with viz
    # but no surviving filter is dropped — templates are curated so each tab has
    # a route-surviving filter (e.g. Ordination's Phylum filter on the heatmap DC),
    # so this only fires when the tab's data is genuinely gone.
    dc_meta = {"pcoa": {"metatype": "Aggregated"}, "heatmap": {"metatype": "Aggregated"}}
    tab = _tab(
        {"component_type": "advanced_viz", "data_collection_tag": "pcoa"},
        {"component_type": "advanced_viz", "data_collection_tag": "heatmap"},
    )
    assert _tab_meets_minimum(tab, dc_meta) is False


# --------------------------------------------------------------------------- #
# _component_has_data — MultiQC module/plot-aware hiding
# --------------------------------------------------------------------------- #


def _mqc(module, plot):
    return {
        "component_type": "multiqc",
        "data_collection_tag": "multiqc_data",
        "dc_id": "deadbeef",
        "selected_module": module,
        "selected_plot": plot,
    }


def _mqc_meta(modules, plots):
    return {"multiqc_data": {"type": "MultiQC", "mqc_modules": modules, "mqc_plots": plots}}


def test_mqc_general_stats_always_kept():
    # Synthetic module is exempt even with empty module/plot metadata.
    assert _component_has_data(_mqc("general_stats", "general_stats"), _mqc_meta(set(), {})) is True


def test_mqc_absent_module_hidden():
    meta = _mqc_meta({"fastp", "fastqc"}, {})
    assert _component_has_data(_mqc("ivar_variants", "ivar_variants-section"), meta) is False


def test_mqc_present_module_missing_plot_hidden():
    # Nanopore snpeff: module present, but the pinned plot was not produced.
    meta = _mqc_meta(
        {"snpeff"}, {"snpeff": {"Variants by Genomic Region", "Variants by Effect Types"}}
    )
    assert _component_has_data(_mqc("snpeff", "Variant Effects by Impact"), meta) is False


def test_mqc_present_module_and_plot_kept():
    meta = _mqc_meta(
        {"snpeff"},
        {"snpeff": {"Variant Effects by Impact", "Variants by Genomic Region"}},
    )
    assert _component_has_data(_mqc("snpeff", "Variant Effects by Impact"), meta) is True


def test_mqc_no_ingestion_record_keeps_component():
    # Unknown module/plot set (no record) -> keep so a genuine gap still surfaces.
    assert (
        _component_has_data(_mqc("snpeff", "Variant Effects by Impact"), _mqc_meta(None, None))
        is True
    )
