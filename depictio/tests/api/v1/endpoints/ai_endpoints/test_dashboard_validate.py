"""Unit tests for the generated-dashboard validators.

`validate_envelope` is the CLI's offline loader; `check_against_schema` is
the server port of the CLI's online schema check, run against `DataContext`
objects built the way test_prompts.py builds them (with a distinct count per
column so the MultiSelect cardinality rule can fire).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.api.v1.endpoints.ai_endpoints.context import ColumnSummary, DataContext
from depictio.api.v1.endpoints.ai_endpoints.dashboard_validate import (
    MULTISELECT_MAX_DISTINCT,
    check_against_schema,
    validate_envelope,
)
from depictio.models.models.dashboards import DashboardDataLite

DC = "iris_table"
WF = "python/iris_workflow"

# name -> (stored dtype, distinct count)
IRIS = {
    "sepal.length": ("float64", 35),
    "sepal.width": ("float64", 23),
    "petal.length": ("float64", 43),
    "petal.width": ("float64", 22),
    "variety": ("object", 3),
    "sample_id": ("String", 150),
    "n_flowers": ("Int32", 9),
    "measured_at": ("Datetime(time_unit='us')", 12),
}


def _ctx(columns: dict[str, tuple[str, int]], tag: str = DC) -> DataContext:
    return DataContext(
        data_collection_id="6" * 24,
        workflow_id="7" * 24,
        project_name="Iris",
        project_description=None,
        dc_name=tag,
        dc_description=None,
        columns=[
            ColumnSummary(name=name, dtype=dtype, null_pct=0.0, nunique=nunique)
            for name, (dtype, nunique) in columns.items()
        ],
        sample_rows=[],
        row_count=150,
        workflow_tag=WF,
        data_collection_tag=tag,
    )


@pytest.fixture()
def contexts() -> dict[str, DataContext]:
    return {DC: _ctx(IRIS)}


def _comp(component_type: str, tag: str = "c", **fields) -> dict:
    base = {"tag": tag, "component_type": component_type}
    if component_type != "text":
        base.update({"workflow_tag": WF, "data_collection_tag": DC})
    base.update(fields)
    return base


def _envelope(*components: dict) -> dict:
    return {"title": "Iris", "components": list(components)}


def _lite(*components: dict) -> DashboardDataLite:
    return validate_envelope(_envelope(*components))


def _findings(contexts, *components: dict) -> list[dict]:
    return check_against_schema(_lite(*components), contexts)


def _fields(findings: list[dict]) -> list[tuple[str, str]]:
    return [(f["component_id"], f["field"]) for f in findings]


IRIS_DASHBOARD = [
    _comp(
        "interactive",
        tag="variety-filter",
        section="Cohort",
        interactive_component_type="MultiSelect",
        column_name="variety",
        column_type="object",
        layout={"x": 0, "y": 0, "w": 1, "h": 3},
    ),
    _comp(
        "interactive",
        tag="sepal-length-filter",
        section="Measurements",
        interactive_component_type="RangeSlider",
        column_name="sepal.length",
        column_type="float64",
    ),
    _comp(
        "text", tag="hdr", section="Metrics", title="Iris at a glance", order=3, body="150 flowers"
    ),
    _comp(
        "card",
        tag="avg-sepal",
        section="Metrics",
        aggregation="average",
        column_name="sepal.length",
        column_type="float64",
        secondary_layout="top_n",
        breakdown_col="variety",
        layout={"x": 0, "y": 1, "w": 2, "h": 2},
    ),
    _comp(
        "card",
        tag="n-flowers",
        section="Metrics",
        aggregation="count",
        column_name="variety",
        secondary_layout="coverage",
        coverage_max=150,
    ),
    _comp(
        "figure",
        tag="scatter",
        section="Analysis",
        visu_type="scatter",
        dict_kwargs={
            "x": "sepal.length",
            "y": "sepal.width",
            "color": "variety",
            "hover_data": ["sample_id"],
        },
    ),
    _comp("table", tag="raw", section="Raw data", columns=["sample_id", "variety", "sepal.length"]),
]


class TestValidateEnvelope:
    def test_iris_shaped_envelope_loads_with_typed_components(self):
        lite = validate_envelope(
            {
                "title": "Iris",
                "subtitle": "demo",
                "filter_sections": [
                    {"name": "Cohort", "icon": "mdi:filter-variant"},
                    {"name": "Measurements"},
                ],
                "grid_sections": [
                    {"name": "Metrics"},
                    {"name": "Analysis"},
                    {"name": "Raw data", "collapsed": True},
                ],
                "components": IRIS_DASHBOARD,
            }
        )
        assert isinstance(lite, DashboardDataLite)
        assert [c.tag for c in lite.components] == [c["tag"] for c in IRIS_DASHBOARD]
        assert all(not isinstance(c, dict) for c in lite.components)
        assert lite.grid_sections[-1].collapsed is True
        assert lite.components[0].section == "Cohort"

    def test_component_the_cli_rejects_raises_validation_error(self):
        bad = _comp("card", aggregation="average", column_name="variety", column_type="object")
        with pytest.raises(ValidationError):
            validate_envelope(_envelope(bad))

    def test_missing_title_raises_validation_error(self):
        with pytest.raises(ValidationError):
            validate_envelope({"components": []})

    def test_unknown_section_spec_key_raises(self):
        with pytest.raises(ValidationError):
            validate_envelope(
                {"title": "x", "grid_sections": [{"name": "A", "emoji": "x"}], "components": []}
            )


class TestCleanDashboard:
    def test_iris_dashboard_has_no_findings(self, contexts):
        assert _findings(contexts, *IRIS_DASHBOARD) == []

    def test_text_is_never_checked(self, contexts):
        assert _findings(contexts, _comp("text", title="Hello")) == []

    def test_multiqc_and_advanced_viz_are_skipped(self, contexts):
        comps = [
            _comp(
                "multiqc",
                tag="mq",
                data_collection_tag="multiqc_reports",
                selected_module="fastqc",
                selected_plot="x",
            ),
            # Columns and collection deliberately unknown: the catalog schema
            # owns advanced_viz bindings, so the column checks must not run.
            _comp(
                "advanced_viz",
                tag="volcano",
                data_collection_tag="other",
                viz_kind="volcano",
                config={
                    "viz_kind": "volcano",
                    "feature_id_col": "gene",
                    "effect_size_col": "lfc",
                    "significance_col": "padj",
                },
            ),
        ]
        assert _findings(contexts, *comps) == []


class TestUnknownColumns:
    def test_card_column_name(self, contexts):
        findings = _findings(contexts, _comp("card", aggregation="count", column_name="colour"))
        assert _fields(findings) == [("c", "column_name")]
        assert "colour" in findings[0]["message"]
        assert "sepal.length" in findings[0]["message"]

    def test_interactive_column_name_short_circuits_the_type_checks(self, contexts):
        findings = _findings(
            contexts,
            _comp("interactive", interactive_component_type="MultiSelect", column_name="nope"),
        )
        assert _fields(findings) == [("c", "column_name")]

    def test_figure_kwargs_are_checked_key_by_key(self, contexts):
        findings = _findings(
            contexts,
            _comp(
                "figure",
                visu_type="scatter",
                dict_kwargs={
                    "x": "sepal.length",
                    "y": "petal_length",
                    "color": "species",
                    "hover_data": ["sample_id", "site"],
                },
            ),
        )
        assert _fields(findings) == [
            ("c", "dict_kwargs.y"),
            ("c", "dict_kwargs.color"),
            ("c", "dict_kwargs.hover_data"),
        ]

    def test_table_columns(self, contexts):
        findings = _findings(contexts, _comp("table", columns=["variety", "genus"]))
        assert _fields(findings) == [("c", "columns")]
        assert "genus" in findings[0]["message"]

    def test_card_breakdown_and_trend_columns(self, contexts):
        findings = _findings(
            contexts,
            _comp(
                "card",
                aggregation="count",
                column_name="variety",
                breakdown_col="species",
                trend_col="date",
            ),
        )
        assert _fields(findings) == [("c", "breakdown_col"), ("c", "trend_col")]

    def test_map_columns(self, contexts):
        findings = _findings(
            contexts,
            _comp(
                "map",
                map_type="scatter_map",
                lat_column="lat",
                lon_column="sepal.width",
                hover_columns=["variety", "zzz"],
            ),
        )
        assert _fields(findings) == [("c", "lat_column"), ("c", "hover_columns")]

    def test_image_column(self, contexts):
        findings = _findings(contexts, _comp("image", image_column="thumbnail"))
        assert _fields(findings) == [("c", "image_column")]


class TestTypeCompatibility:
    def test_average_on_an_object_column(self, contexts):
        findings = _findings(contexts, _comp("card", aggregation="average", column_name="variety"))
        assert _fields(findings) == [("c", "aggregation")]
        assert "object" in findings[0]["message"]
        assert "count" in findings[0]["message"]

    def test_secondary_aggregations_are_checked_too(self, contexts):
        findings = _findings(
            contexts,
            _comp(
                "card", aggregation="count", column_name="variety", aggregations=["nunique", "sum"]
            ),
        )
        assert _fields(findings) == [("c", "aggregations")]
        assert "'sum'" in findings[0]["message"]

    def test_range_slider_on_an_object_column(self, contexts):
        findings = _findings(
            contexts,
            _comp("interactive", interactive_component_type="RangeSlider", column_name="variety"),
        )
        assert _fields(findings) == [("c", "interactive_component_type")]
        assert "Select" in findings[0]["message"]

    def test_polars_dtype_names_are_mapped(self, contexts):
        ok = _findings(
            contexts,
            _comp("card", tag="n", aggregation="sum", column_name="n_flowers"),
            _comp(
                "interactive",
                tag="d",
                interactive_component_type="DateRangePicker",
                column_name="measured_at",
            ),
        )
        assert ok == []
        bad = _findings(
            contexts,
            _comp(
                "interactive", interactive_component_type="MultiSelect", column_name="measured_at"
            ),
        )
        assert _fields(bad) == [("c", "interactive_component_type")]

    def test_declared_column_type_that_contradicts_the_store(self, contexts):
        findings = _findings(
            contexts,
            _comp("card", aggregation="count", column_name="variety", column_type="float64"),
        )
        assert ("c", "column_type") in _fields(findings)

    def test_object_and_category_are_interchangeable(self):
        contexts = {DC: _ctx({"variety": ("category", 3)})}
        findings = _findings(
            contexts,
            _comp("card", aggregation="count", column_name="variety", column_type="object"),
        )
        assert findings == []


class TestSecondaryLayoutCompanions:
    @pytest.mark.parametrize("layout", ["top_n", "concentration", "composition", "donut"])
    def test_breakdown_layouts_need_breakdown_col(self, contexts, layout):
        findings = _findings(
            contexts,
            _comp("card", aggregation="count", column_name="variety", secondary_layout=layout),
        )
        assert _fields(findings) == [("c", "breakdown_col")]
        assert layout in findings[0]["message"]

    @pytest.mark.parametrize("layout", ["coverage", "gauge"])
    def test_coverage_layouts_need_coverage_max(self, contexts, layout):
        findings = _findings(
            contexts,
            _comp("card", aggregation="count", column_name="variety", secondary_layout=layout),
        )
        assert _fields(findings) == [("c", "coverage_max")]

    def test_trend_needs_trend_col(self, contexts):
        findings = _findings(
            contexts,
            _comp("card", aggregation="count", column_name="variety", secondary_layout="trend"),
        )
        assert _fields(findings) == [("c", "trend_col")]

    def test_threshold_needs_threshold_value(self, contexts):
        findings = _findings(
            contexts,
            _comp(
                "card",
                aggregation="average",
                column_name="sepal.length",
                secondary_layout="threshold",
            ),
        )
        assert _fields(findings) == [("c", "threshold_value")]

    def test_satisfied_companions_pass(self, contexts):
        comps = [
            _comp(
                "card",
                tag="a",
                aggregation="count",
                column_name="variety",
                secondary_layout="donut",
                breakdown_col="variety",
            ),
            _comp(
                "card",
                tag="b",
                aggregation="count",
                column_name="variety",
                secondary_layout="gauge",
                coverage_max=150,
            ),
            _comp(
                "card",
                tag="c",
                aggregation="average",
                column_name="sepal.length",
                secondary_layout="trend",
                trend_col="measured_at",
            ),
            _comp(
                "card",
                tag="d",
                aggregation="average",
                column_name="sepal.length",
                secondary_layout="threshold",
                threshold_value=5.0,
            ),
            _comp(
                "card",
                tag="e",
                aggregation="average",
                column_name="sepal.length",
                secondary_layout="histogram",
            ),
        ]
        assert _findings(contexts, *comps) == []


class TestCardinality:
    def test_multiselect_on_a_high_cardinality_column(self, contexts):
        findings = _findings(
            contexts,
            _comp("interactive", interactive_component_type="MultiSelect", column_name="sample_id"),
        )
        assert _fields(findings) == [("c", "interactive_component_type")]
        assert "150 distinct" in findings[0]["message"]
        assert str(MULTISELECT_MAX_DISTINCT) in findings[0]["message"]

    def test_the_limit_itself_is_allowed(self):
        contexts = {DC: _ctx({"site": ("object", MULTISELECT_MAX_DISTINCT)})}
        findings = _findings(
            contexts,
            _comp("interactive", interactive_component_type="MultiSelect", column_name="site"),
        )
        assert findings == []

    def test_select_is_not_subject_to_the_rule(self, contexts):
        findings = _findings(
            contexts,
            _comp("interactive", interactive_component_type="Select", column_name="sample_id"),
        )
        assert findings == []


class TestCollections:
    def test_unknown_data_collection_tag(self, contexts):
        findings = _findings(
            contexts,
            _comp("card", aggregation="count", column_name="variety", data_collection_tag="other"),
        )
        assert _fields(findings) == [("c", "data_collection_tag")]
        assert DC in findings[0]["message"]

    def test_missing_data_collection_tag(self, contexts):
        findings = _findings(
            contexts,
            _comp("card", aggregation="count", column_name="variety", data_collection_tag=""),
        )
        assert _fields(findings) == [("c", "data_collection_tag")]

    def test_second_collection_is_looked_up_by_its_own_tag(self, contexts):
        contexts["penguins"] = _ctx(
            {"species": ("object", 3), "body_mass_g": ("Int64", 94)}, tag="penguins"
        )
        comps = [
            _comp(
                "card",
                tag="p",
                data_collection_tag="penguins",
                aggregation="average",
                column_name="body_mass_g",
            ),
            _comp(
                "card",
                tag="q",
                data_collection_tag="penguins",
                aggregation="average",
                column_name="sepal.length",
            ),
        ]
        findings = _findings(contexts, *comps)
        assert _fields(findings) == [("q", "column_name")]
        assert "penguins" in findings[0]["message"]

    def test_components_without_a_tag_are_keyed_by_position(self, contexts):
        comp = _comp("card", aggregation="average", column_name="variety")
        comp.pop("tag")
        findings = _findings(contexts, _comp("text", tag="hdr"), comp)
        assert _fields(findings) == [("component[1]", "aggregation")]
