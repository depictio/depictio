"""Unit tests for the dashboard plan model, its tolerant parser and its normaliser.

No LLM, no Mongo: `parse_plan` and `normalize_plan` are pure functions of
the planner's JSON and the two limits the settings carry.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.api.v1.endpoints.ai_endpoints import dashboard_plan as dp
from depictio.api.v1.endpoints.ai_endpoints.dashboard_plan import (
    FALLBACK_ICON,
    SECTION_COLORS,
    SECTION_ICONS,
    DashboardPlan,
    PlannedComponent,
    SectionSpec,
    normalize_plan,
    parse_plan,
    section_rank,
)

DC = "iris_table"


def _pc(tag: str, section: str, component_type: str = "card", **overrides) -> PlannedComponent:
    fields = {
        "tag": tag,
        "section": section,
        "component_type": component_type,
        "data_collection_tag": None if component_type == "text" else DC,
        "intent": f"show {tag}",
    }
    fields.update(overrides)
    return PlannedComponent(**fields)


def _plan(
    filter_sections: list[str] | None = None,
    grid_sections: list[str] | None = None,
    components: list[PlannedComponent] | None = None,
    **overrides,
) -> DashboardPlan:
    fields = {
        "title": "Iris overview",
        "filter_sections": [SectionSpec(name=n) for n in (filter_sections or [])],
        "grid_sections": [SectionSpec(name=n) for n in (grid_sections or [])],
        "components": components or [],
    }
    fields.update(overrides)
    return DashboardPlan(**fields)


def _norm(plan: DashboardPlan, *, max_components: int = 16, max_sections: int = 4):
    return normalize_plan(plan, max_components=max_components, max_sections=max_sections)


class TestAllowlists:
    def test_icon_list_matches_the_viewer_picker(self):
        # 37 ids in sectionIcons.ts; the fallback is one of them.
        assert len(SECTION_ICONS) == 37
        assert len(set(SECTION_ICONS)) == len(SECTION_ICONS)
        assert FALLBACK_ICON in SECTION_ICONS
        assert all(icon.startswith("mdi:") for icon in SECTION_ICONS)

    def test_colour_list_is_the_palette_without_dark(self):
        assert len(SECTION_COLORS) == 13
        assert "dark" not in SECTION_COLORS
        assert {"teal", "orange", "gray"} <= set(SECTION_COLORS)


class TestParsePlan:
    def test_strict_shape_round_trips(self):
        raw = {
            "title": "Iris",
            "subtitle": "Sepals and petals",
            "filter_sections": [{"name": "Cohort", "icon": "mdi:filter-variant", "color": "blue"}],
            "grid_sections": [{"name": "Metrics"}, {"name": "Raw data", "description": "rows"}],
            "components": [
                {
                    "tag": "variety",
                    "section": "Cohort",
                    "component_type": "interactive",
                    "data_collection_tag": DC,
                    "intent": "pick varieties",
                },
                {
                    "tag": "n",
                    "section": "Metrics",
                    "component_type": "card",
                    "data_collection_tag": DC,
                },
                {"tag": "hdr", "section": "Metrics", "component_type": "text"},
            ],
        }
        plan = parse_plan(raw)
        assert plan.title == "Iris"
        assert plan.subtitle == "Sepals and petals"
        assert [s.name for s in plan.filter_sections] == ["Cohort"]
        assert plan.filter_sections[0].icon == "mdi:filter-variant"
        assert [s.name for s in plan.grid_sections] == ["Metrics", "Raw data"]
        assert plan.grid_sections[1].description == "rows"
        assert [c.tag for c in plan.components] == ["variety", "n", "hdr"]
        assert plan.components[0].component_type == "interactive"
        assert plan.components[2].data_collection_tag is None

    def test_single_sections_list_is_split_by_what_each_holds(self):
        raw = {
            "title": "Iris",
            "sections": ["Cohort", "Metrics", {"name": "Mixed"}],
            "components": [
                {
                    "tag": "v",
                    "section": "Cohort",
                    "component_type": "interactive",
                    "data_collection_tag": DC,
                },
                {
                    "tag": "n",
                    "section": "Metrics",
                    "component_type": "card",
                    "data_collection_tag": DC,
                },
                {
                    "tag": "s",
                    "section": "Mixed",
                    "component_type": "interactive",
                    "data_collection_tag": DC,
                },
                {
                    "tag": "f",
                    "section": "Mixed",
                    "component_type": "figure",
                    "data_collection_tag": DC,
                },
            ],
        }
        plan = parse_plan(raw)
        assert [s.name for s in plan.filter_sections] == ["Cohort", "Mixed"]
        assert [s.name for s in plan.grid_sections] == ["Metrics", "Mixed"]

    def test_single_sections_list_honours_an_explicit_kind(self):
        raw = {
            "title": "Iris",
            "sections": [{"name": "Left", "kind": "filter"}, {"name": "Right", "panel": "grid"}],
            "components": [],
        }
        plan = parse_plan(raw)
        assert [s.name for s in plan.filter_sections] == ["Left"]
        assert [s.name for s in plan.grid_sections] == ["Right"]
        assert not hasattr(plan.filter_sections[0], "_kind")

    def test_string_sections_and_alias_keys(self):
        raw = {
            "title": "Iris",
            "filter_sections": ["Cohort"],
            "grid_sections": ["Metrics"],
            "components": [
                {"tag": "v", "section": {"name": "Cohort"}, "type": "Interactive", "dc": DC},
                {
                    "id": "n",
                    "section": ["Metrics"],
                    "type": "card",
                    "data_collection": DC,
                    "description": "count rows",
                },
                {"section": "Metrics", "type": "text", "purpose": "header"},
            ],
        }
        plan = parse_plan(raw)
        v, n, t = plan.components
        assert v.component_type == "interactive"
        assert v.section == "Cohort"
        assert v.data_collection_tag == DC
        assert n.tag == "n"
        assert n.section == "Metrics"
        assert n.intent == "count rows"
        assert t.tag == "text-3"
        assert t.intent == "header"

    def test_plan_wrapper_is_unwrapped(self):
        plan = parse_plan({"plan": {"title": "Wrapped", "grid_sections": ["A"], "components": []}})
        assert plan.title == "Wrapped"
        assert [s.name for s in plan.grid_sections] == ["A"]

    def test_unknown_component_type_raises(self):
        raw = {
            "title": "Iris",
            "grid_sections": ["A"],
            "components": [
                {"tag": "x", "section": "A", "component_type": "gauge", "data_collection_tag": DC}
            ],
        }
        with pytest.raises(ValidationError):
            parse_plan(raw)

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            parse_plan({"grid_sections": ["A"], "components": []})


class TestSectionRank:
    @pytest.mark.parametrize(
        ("name", "types", "rank"),
        [
            ("Cohort", set(), dp.RANK_COHORT),
            ("Sample filters", {"interactive"}, dp.RANK_COHORT),
            ("Key metrics", {"card"}, dp.RANK_METRICS),
            ("At a glance", {"card"}, dp.RANK_METRICS),
            ("Distributions", {"figure"}, dp.RANK_ANALYSIS),
            ("Trends over time", {"figure"}, dp.RANK_ANALYSIS),
            ("Raw data", {"table"}, dp.RANK_REFERENCE),
            ("Reference", set(), dp.RANK_REFERENCE),
        ],
    )
    def test_keywords_decide(self, name, types, rank):
        assert section_rank(name, types) == rank

    def test_types_decide_when_the_name_says_nothing(self):
        assert section_rank("Zebra", {"interactive"}) == dp.RANK_COHORT
        assert section_rank("Zebra", {"card"}) == dp.RANK_METRICS
        assert section_rank("Zebra", {"card", "figure"}) == dp.RANK_ANALYSIS
        assert section_rank("Zebra", {"advanced_viz"}) == dp.RANK_ANALYSIS
        assert section_rank("Zebra", {"table"}) == dp.RANK_REFERENCE
        assert section_rank("Zebra", {"card", "table"}) == dp.RANK_REFERENCE

    def test_unknown_sits_in_the_middle(self):
        assert section_rank("Zebra", set()) == dp.RANK_ANALYSIS
        assert section_rank("Zebra", {"text"}) == dp.RANK_ANALYSIS

    def test_name_keywords_win_over_types(self):
        # A "Summary" section that happens to hold a table is still metrics.
        assert section_rank("Summary", {"card", "table"}) == dp.RANK_METRICS


class TestNormalizeOrder:
    def test_grid_sections_follow_the_funnel(self):
        plan = _plan(
            grid_sections=["Raw data", "Distributions", "Key numbers"],
            components=[
                _pc("t", "Raw data", "table"),
                _pc("f", "Distributions", "figure"),
                _pc("c", "Key numbers", "card"),
            ],
        )
        norm, _ = _norm(plan)
        assert [s.name for s in norm.grid_sections] == ["Key numbers", "Distributions", "Raw data"]

    def test_filter_sections_put_the_cohort_first(self):
        plan = _plan(
            filter_sections=["Measurements", "Cohort"],
            components=[
                _pc("len", "Measurements", "interactive"),
                _pc("variety", "Cohort", "interactive"),
            ],
        )
        norm, _ = _norm(plan)
        assert [s.name for s in norm.filter_sections] == ["Cohort", "Measurements"]

    def test_unknown_sections_keep_plan_order_between_metrics_and_reference(self):
        plan = _plan(
            grid_sections=["Raw data", "Zeta", "Alpha", "Overview"],
            components=[
                _pc("t", "Raw data", "table"),
                _pc("z", "Zeta", "figure"),
                _pc("a", "Alpha", "figure"),
                _pc("o", "Overview", "card"),
            ],
        )
        norm, _ = _norm(plan)
        assert [s.name for s in norm.grid_sections] == ["Overview", "Zeta", "Alpha", "Raw data"]

    def test_sort_is_stable_and_idempotent(self):
        plan = _plan(
            grid_sections=["B charts", "A charts", "Totals"],
            components=[
                _pc("b", "B charts", "figure"),
                _pc("a", "A charts", "figure"),
                _pc("t", "Totals", "card"),
            ],
        )
        once, _ = _norm(plan)
        twice, warnings = _norm(once)
        assert [s.name for s in once.grid_sections] == ["Totals", "B charts", "A charts"]
        assert twice == once
        assert warnings == []


class TestNormalizeClamps:
    def test_component_count_is_cut_in_plan_order(self):
        plan = _plan(
            grid_sections=["Metrics"],
            components=[_pc(f"c{i}", "Metrics") for i in range(5)],
        )
        norm, warnings = _norm(plan, max_components=3)
        assert [c.tag for c in norm.components] == ["c0", "c1", "c2"]
        assert any("'c3'" in w and "'c4'" in w for w in warnings)

    def test_section_count_is_cut_per_list_and_takes_the_components_along(self):
        plan = _plan(
            filter_sections=["Cohort", "More filters", "Even more"],
            grid_sections=["Metrics", "Charts", "Raw data"],
            components=[
                _pc("v", "Cohort", "interactive"),
                _pc("w", "More filters", "interactive"),
                _pc("x", "Even more", "interactive"),
                _pc("c", "Metrics"),
                _pc("f", "Charts", "figure"),
                _pc("t", "Raw data", "table"),
            ],
        )
        norm, warnings = _norm(plan, max_sections=2)
        assert [s.name for s in norm.filter_sections] == ["Cohort", "More filters"]
        assert [s.name for s in norm.grid_sections] == ["Metrics", "Charts"]
        assert [c.tag for c in norm.components] == ["v", "w", "c", "f"]
        assert any("'Even more'" in w for w in warnings)
        assert any("'t'" in w and "'Raw data'" in w for w in warnings)

    def test_unknown_section_drops_the_component(self):
        plan = _plan(grid_sections=["Metrics"], components=[_pc("c", "Nowhere")])
        norm, warnings = _norm(plan)
        assert norm.components == []
        assert any("'c'" in w and "'Nowhere'" in w for w in warnings)

    def test_section_names_match_case_and_space_insensitively(self):
        plan = _plan(grid_sections=["Key  Metrics"], components=[_pc("c", "key metrics")])
        norm, _ = _norm(plan)
        assert norm.grid_sections[0].name == "Key Metrics"
        assert norm.components[0].section == "Key Metrics"

    def test_data_bound_types_need_a_collection_but_text_does_not(self):
        plan = _plan(
            grid_sections=["Metrics"],
            components=[
                _pc("c", "Metrics", data_collection_tag=None),
                _pc("f", "Metrics", "figure", data_collection_tag="  "),
                _pc("hdr", "Metrics", "text"),
            ],
        )
        norm, warnings = _norm(plan)
        assert [c.tag for c in norm.components] == ["hdr"]
        assert sum("needs a data_collection_tag" in w for w in warnings) == 2

    def test_empty_sections_are_dropped(self):
        plan = _plan(
            filter_sections=["Cohort"],
            grid_sections=["Metrics", "Charts"],
            components=[_pc("c", "Metrics")],
        )
        norm, warnings = _norm(plan)
        assert norm.filter_sections == []
        assert [s.name for s in norm.grid_sections] == ["Metrics"]
        assert any("empty filter section 'Cohort'" in w for w in warnings)
        assert any("empty grid section 'Charts'" in w for w in warnings)

    def test_duplicate_section_names_are_merged(self):
        plan = _plan(
            grid_sections=["Metrics", "metrics"],
            components=[_pc("a", "Metrics"), _pc("b", "metrics")],
        )
        norm, warnings = _norm(plan)
        assert [s.name for s in norm.grid_sections] == ["Metrics"]
        assert [c.section for c in norm.components] == ["Metrics", "Metrics"]
        assert any("duplicate grid section" in w for w in warnings)


class TestNormalizeMembership:
    def test_interactive_in_a_grid_only_section_gets_the_section_copied_to_the_panel(self):
        plan = _plan(
            grid_sections=["Cohort"],
            components=[_pc("v", "Cohort", "interactive"), _pc("c", "Cohort")],
        )
        norm, warnings = _norm(plan)
        assert [s.name for s in norm.filter_sections] == ["Cohort"]
        assert [s.name for s in norm.grid_sections] == ["Cohort"]
        assert any("added it to the filter panel" in w for w in warnings)

    def test_tile_in_a_filter_only_section_gets_the_section_copied_to_the_grid(self):
        plan = _plan(
            filter_sections=["Cohort"],
            components=[_pc("v", "Cohort", "interactive"), _pc("f", "Cohort", "figure")],
        )
        norm, warnings = _norm(plan)
        assert [s.name for s in norm.grid_sections] == ["Cohort"]
        assert any("added it to the grid" in w for w in warnings)


class TestNormalizeTags:
    def test_duplicates_get_numbered_suffixes(self):
        plan = _plan(
            grid_sections=["Charts"],
            components=[_pc("fig", "Charts", "figure") for _ in range(3)],
        )
        norm, warnings = _norm(plan)
        assert [c.tag for c in norm.components] == ["fig", "fig-2", "fig-3"]
        assert sum("Renamed tag 'fig'" in w for w in warnings) == 2

    def test_suffix_skips_a_tag_already_taken(self):
        plan = _plan(
            grid_sections=["Charts"],
            components=[
                _pc("fig", "Charts", "figure"),
                _pc("fig-2", "Charts", "figure"),
                _pc("fig", "Charts", "figure"),
            ],
        )
        norm, _ = _norm(plan)
        assert [c.tag for c in norm.components] == ["fig", "fig-2", "fig-3"]

    def test_tags_are_cleaned_and_empty_ones_derived(self):
        plan = _plan(
            grid_sections=["Charts"],
            components=[
                _pc("Sepal length / width", "Charts", "figure"),
                _pc("   ", "Charts", "figure"),
            ],
        )
        norm, _ = _norm(plan)
        assert norm.components[0].tag == "Sepal-length-width"
        assert norm.components[1].tag == "figure-2"


class TestNormalizeStyle:
    def test_unknown_icon_falls_back_and_warns(self):
        plan = _plan(
            grid_sections=[],
            components=[_pc("c", "Metrics")],
        )
        plan = plan.model_copy(
            update={"grid_sections": [SectionSpec(name="Metrics", icon="mdi:not-a-real-icon")]}
        )
        norm, warnings = _norm(plan)
        assert norm.grid_sections[0].icon == FALLBACK_ICON
        assert any("mdi:not-a-real-icon" in w for w in warnings)

    def test_known_icon_is_kept(self):
        plan = _plan(components=[_pc("c", "Metrics")]).model_copy(
            update={"grid_sections": [SectionSpec(name="Metrics", icon="mdi:counter")]}
        )
        norm, warnings = _norm(plan)
        assert norm.grid_sections[0].icon == "mdi:counter"
        assert warnings == []

    def test_blank_icon_gets_a_stage_default(self):
        plan = _plan(
            filter_sections=["Cohort"],
            grid_sections=["Metrics", "Charts", "Raw data"],
            components=[
                _pc("v", "Cohort", "interactive"),
                _pc("c", "Metrics"),
                _pc("f", "Charts", "figure"),
                _pc("t", "Raw data", "table"),
            ],
        )
        norm, _ = _norm(plan)
        assert norm.filter_sections[0].icon == "mdi:filter-variant"
        assert [s.icon for s in norm.grid_sections] == [
            "mdi:counter",
            "mdi:chart-box-outline",
            "mdi:table",
        ]
        assert all(s.icon in SECTION_ICONS for s in norm.grid_sections)

    def test_colours_are_lowercased_or_dropped(self):
        plan = _plan(components=[_pc("a", "A"), _pc("b", "B"), _pc("c", "C")]).model_copy(
            update={
                "grid_sections": [
                    SectionSpec(name="A", color="Teal"),
                    SectionSpec(name="B", color="#159090"),
                    SectionSpec(name="C", color="dark"),
                ]
            }
        )
        norm, warnings = _norm(plan)
        colours = {s.name: s.color for s in norm.grid_sections}
        assert colours == {"A": "teal", "B": None, "C": None}
        assert sum("is not a palette name" in w for w in warnings) == 2

    def test_title_and_description_whitespace_are_collapsed(self):
        plan = _plan(components=[_pc("c", "A")], title="  Iris   overview ").model_copy(
            update={"grid_sections": [SectionSpec(name="A", description="  two   words ")]}
        )
        norm, _ = _norm(plan)
        assert norm.title == "Iris overview"
        assert norm.grid_sections[0].description == "two words"

    def test_blank_title_gets_a_fallback(self):
        plan = _plan(components=[_pc("c", "A")], grid_sections=["A"], title="   ")
        norm, warnings = _norm(plan)
        assert norm.title == "Generated dashboard"
        assert any("no title" in w for w in warnings)


class TestNormalizePurity:
    def test_input_plan_is_not_mutated(self):
        plan = _plan(
            grid_sections=["Raw data", "Metrics"],
            components=[_pc("fig", "Metrics", "figure"), _pc("fig", "Raw data", "table")],
        )
        before = plan.model_dump()
        _norm(plan)
        assert plan.model_dump() == before
