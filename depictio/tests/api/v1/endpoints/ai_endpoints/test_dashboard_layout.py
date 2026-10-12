"""Unit tests for the deterministic funnel layout of a generated dashboard.

`layout_dashboard` is pure: a normalised plan plus the filled component
dicts in, the same dicts with `section` and `layout` out. The last test
pushes the result through `DashboardDataLite.to_full()` to prove the boxes
fit the 8-column grid the viewer draws.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from depictio.api.v1.endpoints.ai_endpoints.dashboard_layout import (
    GRID_COLS,
    card_rows,
    layout_dashboard,
)
from depictio.api.v1.endpoints.ai_endpoints.dashboard_plan import (
    DashboardPlan,
    PlannedComponent,
    SectionSpec,
)
from depictio.models.models.dashboards import DashboardDataLite

DC = "iris_table"
WF = "python/iris_workflow"


def _plan(sections: dict[str, list[tuple[str, str]]], *, filters: list[str] | None = None):
    """Plan from {section: [(tag, type), ...]}; sections named in `filters` go to the panel."""
    filters = filters or []
    components = [
        PlannedComponent(
            tag=tag,
            section=section,
            component_type=component_type,
            data_collection_tag=None if component_type == "text" else DC,
        )
        for section, members in sections.items()
        for tag, component_type in members
    ]
    return DashboardPlan(
        title="Iris",
        filter_sections=[SectionSpec(name=n) for n in sections if n in filters],
        grid_sections=[SectionSpec(name=n) for n in sections if n not in filters],
        components=components,
    )


def _comp(tag: str, component_type: str, **extra) -> dict:
    """The smallest valid lite dict of each type, as validate_single would hand it over."""
    base = {"tag": tag, "component_type": component_type, "title": tag}
    if component_type != "text":
        base.update({"workflow_tag": WF, "data_collection_tag": DC})
    if component_type == "card":
        base.update({"aggregation": "count", "column_name": "variety"})
    elif component_type == "figure":
        base.update(
            {"visu_type": "scatter", "dict_kwargs": {"x": "sepal.length", "y": "sepal.width"}}
        )
    elif component_type == "interactive":
        base.update({"interactive_component_type": "MultiSelect", "column_name": "variety"})
    elif component_type == "table":
        base.update({"columns": []})
    elif component_type == "text":
        base.update({"order": 3, "body": "intro"})
    base.update(extra)
    return base


def _components(plan: DashboardPlan) -> list[dict]:
    return [_comp(c.tag, c.component_type) for c in plan.components]


def _boxes(components: list[dict], section: str, component_type: str | None = None) -> list[dict]:
    return [
        c["layout"]
        for c in components
        if c["section"] == section
        and (component_type is None or c["component_type"] == component_type)
    ]


def _rows(boxes: list[dict]) -> dict[int, list[dict]]:
    rows: dict[int, list[dict]] = {}
    for box in boxes:
        rows.setdefault(box["y"], []).append(box)
    return {y: sorted(row, key=lambda b: b["x"]) for y, row in sorted(rows.items())}


class TestCardRows:
    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8, 9])
    def test_every_row_sums_to_the_grid_width(self, n):
        rows = card_rows(n)
        assert sum(len(r) for r in rows) == n
        assert all(sum(r) == GRID_COLS for r in rows)

    def test_remainders_are_the_documented_splits(self):
        assert card_rows(4) == [[2, 2, 2, 2]]
        assert card_rows(5) == [[2, 2, 2, 2], [8]]
        assert card_rows(6) == [[2, 2, 2, 2], [4, 4]]
        assert card_rows(7) == [[2, 2, 2, 2], [3, 3, 2]]
        assert card_rows(0) == []


class TestGridSection:
    @pytest.mark.parametrize("n", [4, 5, 6, 7])
    def test_card_rows_are_always_full_and_contiguous(self, n):
        plan = _plan({"Metrics": [(f"c{i}", "card") for i in range(n)]})
        out, _, _ = layout_dashboard(plan, _components(plan))
        rows = _rows(_boxes(out, "Metrics", "card"))
        for row in rows.values():
            assert sum(b["w"] for b in row) == GRID_COLS
            x = 0
            for box in row:
                assert box["x"] == x
                assert box["h"] == 2
                x += box["w"]
        assert list(rows) == ([0, 2] if n > 4 else [0])

    def test_header_comes_first_and_cards_start_below_it(self):
        plan = _plan({"Metrics": [("c1", "card"), ("hdr", "text"), ("c2", "card")]})
        out, _, _ = layout_dashboard(plan, _components(plan))
        section = [c for c in out if c["section"] == "Metrics"]
        assert section[0]["tag"] == "hdr"
        assert section[0]["layout"] == {"x": 0, "y": 0, "w": GRID_COLS, "h": 1}
        assert [c["layout"]["y"] for c in section[1:]] == [1, 1]
        assert [c["layout"]["w"] for c in section[1:]] == [4, 4]

    def test_figures_pair_up_and_a_lone_trailing_one_is_widened(self):
        plan = _plan({"Analysis": [("f1", "figure"), ("f2", "figure"), ("f3", "figure")]})
        out, _, _ = layout_dashboard(plan, _components(plan))
        boxes = _boxes(out, "Analysis")
        assert boxes[0] == {"x": 0, "y": 0, "w": 4, "h": 5}
        assert boxes[1] == {"x": 4, "y": 0, "w": 4, "h": 5}
        assert boxes[2] == {"x": 0, "y": 5, "w": 8, "h": 5}

    def test_single_figure_fills_the_row(self):
        plan = _plan({"Analysis": [("f1", "figure")]})
        out, _, _ = layout_dashboard(plan, _components(plan))
        assert _boxes(out, "Analysis") == [{"x": 0, "y": 0, "w": 8, "h": 5}]

    def test_maps_and_images_share_the_chart_slot(self):
        plan = _plan({"Analysis": [("m", "map"), ("i", "image")]})
        comps = [
            _comp("m", "map", map_type="scatter_map", lat_column="lat", lon_column="lon"),
            _comp("i", "image", image_column="path"),
        ]
        out, _, _ = layout_dashboard(plan, comps)
        assert [b["x"] for b in _boxes(out, "Analysis")] == [0, 4]
        assert {b["w"] for b in _boxes(out, "Analysis")} == {4}

    def test_advanced_viz_is_full_width_and_tall(self):
        plan = _plan({"Analysis": [("f1", "figure"), ("hm", "advanced_viz")]})
        comps = [_comp("f1", "figure"), _comp("hm", "advanced_viz", viz_kind="heatmap")]
        out, _, _ = layout_dashboard(plan, comps)
        boxes = _boxes(out, "Analysis")
        assert boxes[0]["w"] == 8  # lone figure
        assert boxes[1] == {"x": 0, "y": 5, "w": 8, "h": 8}

    def test_table_is_last_in_its_section(self):
        plan = _plan({"Reference": [("t", "table"), ("c", "card"), ("f", "figure")]})
        out, _, _ = layout_dashboard(plan, _components(plan))
        section = [c for c in out if c["section"] == "Reference"]
        assert [c["tag"] for c in section] == ["c", "f", "t"]
        assert section[-1]["layout"] == {"x": 0, "y": 7, "w": 8, "h": 5}

    def test_type_groups_follow_the_documented_order_within_a_section(self):
        plan = _plan(
            {
                "All": [
                    ("t", "table"),
                    ("hm", "advanced_viz"),
                    ("f", "figure"),
                    ("c", "card"),
                    ("hdr", "text"),
                ]
            }
        )
        comps = [
            _comp("t", "table"),
            _comp("hm", "advanced_viz"),
            _comp("f", "figure"),
            _comp("c", "card"),
            _comp("hdr", "text"),
        ]
        out, _, _ = layout_dashboard(plan, comps)
        assert [c["tag"] for c in out] == ["hdr", "c", "f", "hm", "t"]
        ys = [c["layout"]["y"] for c in out]
        assert ys == sorted(ys)


class TestFilterPanel:
    def test_interactives_stack_at_x0_in_full_height_steps(self):
        plan = _plan(
            {"Cohort": [("a", "interactive"), ("b", "interactive"), ("c", "interactive")]},
            filters=["Cohort"],
        )
        out, _, _ = layout_dashboard(plan, _components(plan))
        assert _boxes(out, "Cohort") == [
            {"x": 0, "y": 0, "w": 1, "h": 3},
            {"x": 0, "y": 3, "w": 1, "h": 3},
            {"x": 0, "y": 6, "w": 1, "h": 3},
        ]

    def test_each_filter_section_restarts_its_y(self):
        plan = _plan(
            {
                "Cohort": [("a", "interactive")],
                "Ranges": [("b", "interactive"), ("c", "interactive")],
            },
            filters=["Cohort", "Ranges"],
        )
        out, _, _ = layout_dashboard(plan, _components(plan))
        assert [b["y"] for b in _boxes(out, "Cohort")] == [0]
        assert [b["y"] for b in _boxes(out, "Ranges")] == [0, 3]

    def test_filters_are_emitted_before_the_grid(self):
        plan = _plan(
            {"Metrics": [("c", "card")], "Cohort": [("v", "interactive")]},
            filters=["Cohort"],
        )
        out, _, _ = layout_dashboard(plan, _components(plan))
        assert [c["tag"] for c in out] == ["v", "c"]


class TestSections:
    def test_sections_come_out_in_plan_order_with_their_style(self):
        plan = DashboardPlan(
            title="Iris",
            filter_sections=[SectionSpec(name="Cohort", icon="mdi:filter-variant", color="blue")],
            grid_sections=[
                SectionSpec(name="Metrics", icon="mdi:counter", color="teal", description="counts"),
                SectionSpec(name="Analysis"),
                SectionSpec(name="Raw data", icon="mdi:table"),
            ],
            components=[
                PlannedComponent(
                    tag="v", section="Cohort", component_type="interactive", data_collection_tag=DC
                ),
                PlannedComponent(
                    tag="c", section="Metrics", component_type="card", data_collection_tag=DC
                ),
                PlannedComponent(
                    tag="f", section="Analysis", component_type="figure", data_collection_tag=DC
                ),
                PlannedComponent(tag="hdr", section="Raw data", component_type="text"),
                PlannedComponent(
                    tag="t", section="Raw data", component_type="table", data_collection_tag=DC
                ),
            ],
        )
        _, filter_specs, grid_specs = layout_dashboard(plan, _components(plan))
        assert filter_specs == [{"name": "Cohort", "icon": "mdi:filter-variant", "color": "blue"}]
        assert grid_specs == [
            {"name": "Metrics", "icon": "mdi:counter", "color": "teal", "description": "counts"},
            {"name": "Analysis"},
            {"name": "Raw data", "icon": "mdi:table", "collapsed": True},
        ]

    def test_a_section_mixing_tables_and_tiles_is_not_collapsed(self):
        plan = _plan({"Reference": [("t", "table"), ("c", "card")]})
        _, _, grid_specs = layout_dashboard(plan, _components(plan))
        assert grid_specs == [{"name": "Reference"}]

    def test_sections_nothing_landed_in_are_omitted(self):
        plan = _plan({"Metrics": [("c", "card")], "Analysis": [], "Cohort": []}, filters=["Cohort"])
        _, filter_specs, grid_specs = layout_dashboard(plan, _components(plan))
        assert filter_specs == []
        assert grid_specs == [{"name": "Metrics"}]

    def test_unplanned_component_keeps_its_own_section(self):
        plan = _plan({"Metrics": [("c", "card")]})
        comps = _components(plan) + [_comp("extra", "figure", section="Charts")]
        out, _, grid_specs = layout_dashboard(plan, comps)
        assert [s["name"] for s in grid_specs] == ["Metrics", "Charts"]
        assert out[-1]["section"] == "Charts"

    def test_unplanned_component_without_a_section_falls_back(self):
        plan = _plan(
            {
                "Cohort": [("v", "interactive")],
                "Metrics": [("c", "card")],
                "Analysis": [("f", "figure")],
            },
            filters=["Cohort"],
        )
        comps = _components(plan) + [_comp("t", "table"), _comp("w", "interactive")]
        out, filter_specs, grid_specs = layout_dashboard(plan, comps)
        by_tag = {c["tag"]: c for c in out}
        assert by_tag["t"]["section"] == "Analysis"  # last grid section
        assert by_tag["w"]["section"] == "Cohort"  # first filter section
        assert [s["name"] for s in filter_specs] == ["Cohort"]
        assert [s["name"] for s in grid_specs] == ["Metrics", "Analysis"]

    def test_no_plan_sections_at_all_creates_defaults(self):
        plan = DashboardPlan(title="Iris")
        out, filter_specs, grid_specs = layout_dashboard(
            plan, [_comp("v", "interactive"), _comp("c", "card")]
        )
        assert filter_specs == [{"name": "Filters"}]
        assert grid_specs == [{"name": "Overview"}]
        assert {c["section"] for c in out} == {"Filters", "Overview"}


class TestPurity:
    def test_deterministic_and_non_mutating(self):
        plan = _plan(
            {
                "Cohort": [("v", "interactive")],
                "Metrics": [("hdr", "text")] + [(f"c{i}", "card") for i in range(5)],
                "Analysis": [("f1", "figure"), ("f2", "figure"), ("f3", "figure")],
                "Raw data": [("t", "table")],
            },
            filters=["Cohort"],
        )
        comps = _components(plan)
        snapshot = deepcopy(comps)
        first = layout_dashboard(plan, comps)
        second = layout_dashboard(plan, comps)
        assert first == second
        assert comps == snapshot
        assert all("layout" not in c for c in comps)


class TestToFull:
    def test_every_box_fits_the_eight_column_grid(self):
        plan = _plan(
            {
                "Cohort": [("v", "interactive"), ("w", "interactive")],
                "Metrics": [("hdr", "text")] + [(f"c{i}", "card") for i in range(7)],
                "Analysis": [("f1", "figure"), ("f2", "figure"), ("f3", "figure")],
                "Raw data": [("t", "table")],
            },
            filters=["Cohort"],
        )
        components, filter_specs, grid_specs = layout_dashboard(plan, _components(plan))
        lite = DashboardDataLite.model_validate(
            {
                "title": "Iris",
                "filter_sections": filter_specs,
                "grid_sections": grid_specs,
                "components": components,
            }
        )
        full = lite.to_full()
        right = full["right_panel_layout_data"]
        left = full["left_panel_layout_data"]
        assert len(right) == 1 + 7 + 3 + 1
        assert len(left) == 2
        assert all(box["w"] <= GRID_COLS for box in right)
        assert all(box["x"] + box["w"] <= GRID_COLS for box in right)
        assert all(box["w"] == 1 and box["x"] == 0 for box in left)
        assert full["grid_sections"][-1]["collapsed"] is True
        assert {c["section"] for c in full["stored_metadata"]} == {
            "Cohort",
            "Metrics",
            "Analysis",
            "Raw data",
        }
