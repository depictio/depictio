"""Unit tests for the pure helpers behind /ai/suggest-components.

No Mongo, no delta table, no LLM: the helpers take an InventoryEntry (or
plain dicts) and return prompt lines, candidate components, or the merged
list. The one external ranker (`suggest_viz_kinds`) is faked where the
test is about how its answer is turned into a component.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.endpoints.ai_endpoints import suggest
from depictio.api.v1.endpoints.ai_endpoints.context import InventoryEntry
from depictio.api.v1.endpoints.ai_endpoints.schemas import ComponentSuggestion
from depictio.models.components.advanced_viz.schemas import VizSuggestion
from depictio.models.components.constants import (
    AGGREGATION_COMPATIBILITY,
    ALLOWED_VISUALIZATIONS,
    INTERACTIVE_COMPATIBILITY,
)

DC_ID = "6" * 24


def _entry(columns: list[tuple[str, str]], **overrides) -> InventoryEntry:
    fields = {
        "data_collection_id": DC_ID,
        "data_collection_tag": "physical_features",
        "workflow_id": "7" * 24,
        "workflow_tag": "wf",
        "dc_type": "table",
        "description": None,
        "columns": columns,
        "on_dashboard": True,
    }
    fields.update(overrides)
    return InventoryEntry(**fields)


MIXED = [
    ("bill_length_mm", "float64"),
    ("n_eggs", "int32"),
    ("species", "object"),
    ("island", "utf8"),
    ("is_adult", "bool"),
    ("incubation", "time"),
    ("sampled_at", "datetime"),
]


class TestColumnTypeFor:
    @pytest.mark.parametrize(
        ("dtype", "expected"),
        [
            ("object", "object"),
            ("string", "object"),
            ("utf8", "object"),
            ("int64", "int64"),
            ("int32", "int64"),
            ("float32", "float64"),
            ("float64", "float64"),
            ("bool", "bool"),
            ("boolean", "bool"),
            ("date", "datetime"),
            ("datetime", "datetime"),
            ("time", "timedelta"),
            ("timedelta", "timedelta"),
            ("category", "category"),
            ("gizmo", None),
            ("", None),
            (None, None),
        ],
    )
    def test_stored_spec_vocabulary(self, dtype, expected):
        assert suggest.column_type_for(dtype) == expected

    def test_polars_names_and_parameters(self):
        assert suggest.column_type_for("Float64") == "float64"
        assert suggest.column_type_for("String") == "object"
        assert suggest.column_type_for("Datetime(time_unit='us')") == "datetime"
        assert suggest.column_type_for("datetime64[ns]") == "datetime"


class TestSpaces:
    def test_card_space_groups_columns_by_type_with_their_aggregations(self):
        space = suggest.card_space(_entry(MIXED))
        assert set(space) == {"float64", "int64", "object", "bool", "timedelta", "datetime"}
        assert space["object"] == (["species", "island"], AGGREGATION_COMPATIBILITY["object"])
        assert space["int64"][0] == ["n_eggs"]

    def test_interactive_space_skips_types_without_a_widget(self):
        space = suggest.interactive_space(_entry(MIXED))
        assert INTERACTIVE_COMPATIBILITY["bool"] == []
        assert INTERACTIVE_COMPATIBILITY["timedelta"] == []
        assert set(space) == {"float64", "int64", "object", "datetime"}
        assert space["datetime"] == (["sampled_at"], ["DateRangePicker", "Timeline"])

    def test_unmapped_dtypes_are_left_out(self):
        entry = _entry([("blob", "list<int64>"), ("species", "object")])
        assert set(suggest.card_space(entry)) == {"object"}

    def test_space_lines_follow_the_allowed_types(self):
        entry = _entry(MIXED)
        lines = suggest.space_lines(entry, ["card", "figure"])
        assert any(
            line.startswith("card: column_type object for species, island") for line in lines
        )
        assert any("aggregation in {count, mode, nunique}" in line for line in lines)
        assert not any(line.startswith("interactive:") for line in lines)
        figure = next(line for line in lines if line.startswith("figure:"))
        for visu in ALLOWED_VISUALIZATIONS:
            assert visu in figure
        assert "bill_length_mm" in figure

    def test_space_lines_map_needs_coordinates(self):
        entry = _entry([("lat", "float64"), ("lon", "float64"), ("site", "object")])
        assert suggest.space_lines(entry, ["map"], has_coords=False) == []
        (line,) = suggest.space_lines(entry, ["map"], has_coords=True)
        assert line == "map: map_type scatter_map with lat_column lat and lon_column lon"

    def test_space_lines_map_prefers_declared_coordinate_columns(self):
        entry = _entry(
            [("y", "float64"), ("x", "float64")],
            coordinate_columns=("y", "x"),
        )
        (line,) = suggest.space_lines(entry, ["map"], has_coords=True)
        assert "lat_column y and lon_column x" in line

    def test_space_lines_multiqc_is_capped(self):
        entry = _entry([], dc_type="multiqc")
        options = {
            "modules": [f"mod_{i:02d}" for i in range(20)],
            "plots": {f"mod_{i:02d}": [f"plot_{i}_a", f"plot_{i}_b"] for i in range(20)},
        }
        lines = suggest.space_lines(entry, ["multiqc"], options)
        assert len(lines) == suggest.MAX_MULTIQC_LINES
        assert lines[0] == "multiqc: selected_module mod_00; selected_plot in {plot_0_a, plot_0_b}"
        assert lines[-1].startswith("multiqc: (+9 more modules")

    def test_space_lines_advanced_viz_lists_kinds_with_their_config_keys(self):
        candidates = [
            {
                "viz_kind": f"kind_{i}",
                "config": {"viz_kind": f"kind_{i}", "a_col": "x", "b_col": "y"},
            }
            for i in range(6)
        ]
        lines = suggest.space_lines(
            _entry([("x", "float64")]), ["advanced_viz"], advanced_viz_candidates=candidates
        )
        assert len(lines) == suggest.MAX_ADVANCED_VIZ_SPACE_KINDS + 1
        assert lines[0] == 'advanced_viz kind "kind_0": config keys a_col=x, b_col=y'
        assert lines[-1].startswith("advanced_viz: the component carries viz_kind and a config")
        assert "extra keys are rejected" in lines[-1]
        # Not in the allowed types, or nothing ranked: no lines.
        assert suggest.space_lines(_entry([]), ["card"], advanced_viz_candidates=candidates) == []
        assert suggest.space_lines(_entry([]), ["advanced_viz"], advanced_viz_candidates=[]) == []

    def test_space_lines_multiqc_general_stats_has_its_own_plot(self):
        entry = _entry([], dc_type="multiqc")
        options = {"modules": ["general_stats"], "plots": {}}
        assert suggest.space_lines(entry, ["multiqc"], options) == [
            "multiqc: selected_module general_stats; selected_plot in {general_stats}"
        ]


class TestLlmTypesFor:
    def test_open_type_asks_for_everything_but_table(self):
        allowed = ["figure", "card", "interactive", "table", "text", "advanced_viz"]
        assert suggest.llm_types_for(allowed, None) == [
            "figure",
            "card",
            "interactive",
            "text",
            "advanced_viz",
        ]

    @pytest.mark.parametrize("pinned", ["advanced_viz", "table"])
    def test_pinned_ranked_type_means_no_llm_call(self, pinned):
        assert suggest.llm_types_for([pinned], pinned) == []

    def test_pinned_llm_type_is_asked_alone(self):
        assert suggest.llm_types_for(["card"], "card") == ["card"]


class TestTableComponent:
    def test_first_eight_columns_on_a_short_page_and_validates(self):
        columns = [(f"c{i}", "float64") for i in range(12)]
        component = suggest.table_component(_entry(columns))
        assert component["columns"] == [f"c{i}" for i in range(8)]
        assert component["page_size"] == 10
        assert component["title"] == "Browse physical_features"
        validated = suggest.validate_candidate(component)
        assert validated is not None
        assert validated["component_type"] == "table"
        assert validated["columns"] == component["columns"]
        assert validated["page_size"] == 10
        assert validated["workflow_tag"] == "wf"
        assert validated["data_collection_tag"] == "physical_features"

    def test_missing_workflow_tag_still_validates(self):
        component = suggest.table_component(_entry([("a", "int64")], workflow_tag=None))
        assert suggest.validate_candidate(component) is not None


class TestAdvancedVizComponents:
    def test_binds_required_roles_under_config_keys_and_drops_unmet(self, monkeypatch):
        def fake_ranker(schema, min_confidence=0.0, dc_type=None):
            assert schema == {"gene_id": "String", "log2FoldChange": "Float64", "padj": "Float64"}
            return [
                VizSuggestion(
                    viz_kind="manhattan",
                    score=0.9,
                    role_candidates={"chr": ["gene_id"], "pos": [], "score": ["padj"]},
                    unmet_roles=["pos"],
                    weak_roles=[],
                ),
                VizSuggestion(
                    viz_kind="volcano",
                    score=0.95,
                    role_candidates={
                        "feature_id": ["gene_id"],
                        "effect_size": ["log2FoldChange", "padj"],
                        "significance": ["padj", "log2FoldChange"],
                        # Optional roles must not be bound.
                        "label": ["gene_id"],
                    },
                    unmet_roles=[],
                    weak_roles=[],
                ),
                VizSuggestion(
                    viz_kind="qq",
                    score=0.5,
                    role_candidates={"p_value": ["padj"]},
                    unmet_roles=[],
                    weak_roles=[],
                ),
            ]

        monkeypatch.setattr(suggest, "suggest_viz_kinds", fake_ranker)
        entry = _entry([], data_collection_tag="de_results")
        schema = {"gene_id": "String", "log2FoldChange": "Float64", "padj": "Float64"}
        out = suggest.advanced_viz_components(entry, schema)
        assert [c["viz_kind"] for c in out] == ["volcano"]
        (volcano,) = out
        assert volcano["component_type"] == "advanced_viz"
        assert volcano["title"] == "Volcano plot of de_results"
        assert volcano["config"] == {
            "viz_kind": "volcano",
            "feature_id_col": "gene_id",
            "effect_size_col": "log2FoldChange",
            "significance_col": "padj",
        }
        assert suggest.validate_candidate(volcano) is not None

    def test_uses_the_renderer_config_key_not_role_col(self, monkeypatch):
        monkeypatch.setattr(
            suggest,
            "suggest_viz_kinds",
            lambda schema, min_confidence=0.0, dc_type=None: [
                VizSuggestion(
                    viz_kind="complex_heatmap",
                    score=0.9,
                    role_candidates={"index": ["sample_id"]},
                    unmet_roles=[],
                    weak_roles=[],
                )
            ],
        )
        (heatmap,) = suggest.advanced_viz_components(_entry([]), {"sample_id": "String"})
        assert "index_column" in heatmap["config"]
        assert "index_col" not in heatmap["config"]

    def test_strong_matches_lead_weak_ones(self, monkeypatch):
        monkeypatch.setattr(
            suggest,
            "suggest_viz_kinds",
            lambda schema, min_confidence=0.0, dc_type=None: [
                VizSuggestion(
                    viz_kind="ma",
                    score=0.9,
                    role_candidates={
                        "feature_id": ["gene_id"],
                        "avg_log_intensity": ["padj"],
                        "log2_fold_change": ["log2FoldChange"],
                    },
                    unmet_roles=[],
                    weak_roles=["avg_log_intensity"],
                ),
                VizSuggestion(
                    viz_kind="qq",
                    score=0.85,
                    role_candidates={"p_value": ["padj"]},
                    unmet_roles=[],
                    weak_roles=[],
                ),
            ],
        )
        out = suggest.advanced_viz_components(_entry([]), {"padj": "Float64"})
        assert [c["viz_kind"] for c in out] == ["qq", "ma"]

    def test_real_ranker_on_a_de_table(self):
        entry = _entry([], data_collection_tag="de_results")
        schema = {"gene_id": "String", "log2FoldChange": "Float64", "padj": "Float64"}
        kinds = [c["viz_kind"] for c in suggest.advanced_viz_components(entry, schema)]
        assert "volcano" in kinds
        for candidate in suggest.advanced_viz_components(entry, schema):
            assert suggest.validate_candidate(candidate) is not None


class TestValidateCandidate:
    def _card(self, aggregation: str) -> dict:
        return {
            "component_type": "card",
            "workflow_tag": "wf",
            "data_collection_tag": "physical_features",
            "title": "Species",
            "aggregation": aggregation,
            "column_name": "species",
            "column_type": "object",
        }

    def test_illegal_aggregation_for_the_column_type_is_dropped(self):
        assert suggest.validate_candidate(self._card("average")) is None

    def test_legal_card_comes_back_as_the_validated_dict(self):
        validated = suggest.validate_candidate(self._card("count"))
        assert validated is not None
        assert validated["component_type"] == "card"
        assert validated["aggregation"] == "count"
        assert validated["title"] == "Species"
        assert validated["workflow_tag"] == "wf"

    def test_unknown_type_is_dropped(self):
        assert suggest.validate_candidate({"component_type": "gizmo", "title": "x"}) is None


def _suggestion(
    component_type: str,
    title: str,
    origin: str,
    dc_id: str | None = DC_ID,
) -> ComponentSuggestion:
    return ComponentSuggestion(
        component_type=component_type,  # type: ignore[arg-type]
        data_collection_id=dc_id,
        data_collection_tag="physical_features" if dc_id else None,
        workflow_id="7" * 24 if dc_id else None,
        title=title,
        rationale="because",
        component={"component_type": component_type, "title": title},
        origin=origin,  # type: ignore[arg-type]
    )


class TestMerge:
    def setup_method(self):
        self.av1 = _suggestion("advanced_viz", "Volcano plot of physical_features", "ranked")
        self.av2 = _suggestion("advanced_viz", "QQ plot of physical_features", "ranked")
        self.table = _suggestion("table", "Browse physical_features", "ranked")
        self.card = _suggestion("card", "Species count", "llm")
        self.widget = _suggestion("interactive", "Species filter", "llm")
        self.text = _suggestion("text", "Overview", "llm", dc_id=None)

    def test_pinned_ranked_type_ignores_llm_items(self):
        out = suggest.merge([self.av1, self.av2], [self.card], 4, "advanced_viz")
        assert out == [self.av1, self.av2]
        out = suggest.merge([self.table], [self.card], 4, "table")
        assert out == [self.table]

    def test_auto_is_llm_items_then_tables_with_no_ranked_advanced_viz(self):
        out = suggest.merge(
            [self.av1, self.av2, self.table], [self.card, self.widget, self.text], 8, None
        )
        assert out == [self.card, self.widget, self.text, self.table]

    def test_auto_keeps_an_llm_proposed_advanced_viz(self):
        proposed = _suggestion("advanced_viz", "Volcano of the DE table", "llm")
        out = suggest.merge([self.av1, self.table], [self.card, proposed], 8, None)
        assert out == [self.card, proposed, self.table]

    def test_pinned_llm_type_never_surfaces_ranked_advanced_viz(self):
        out = suggest.merge([self.av1, self.table], [self.card, self.widget], 8, "card")
        assert out == [self.card, self.widget, self.table]

    def test_caps_at_n(self):
        out = suggest.merge([self.av1, self.table], [self.card, self.widget, self.text], 2, None)
        assert out == [self.card, self.widget]

    def test_tables_only_fill_the_room_left(self):
        out = suggest.merge([self.table], [self.card, self.widget], 2, None)
        assert out == [self.card, self.widget]
        out = suggest.merge([self.table], [self.card], 2, None)
        assert out == [self.card, self.table]

    def test_dedupes_on_type_collection_and_title(self):
        twin = _suggestion("card", "  species COUNT ", "llm")
        other_dc = _suggestion("card", "Species count", "llm", dc_id="8" * 24)
        out = suggest.merge([], [self.card, twin, other_dc], 8, None)
        assert out == [self.card, other_dc]

    def test_nothing_in_gives_nothing_out(self):
        assert suggest.merge([], [], 4, None) == []
