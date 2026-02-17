"""
Unit Tests for DashboardDataLite and Lite Component Models.

Tests the lightweight dashboard and component models used for YAML import/export.
"""

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from depictio.models.components.figure import FigureComponent
from depictio.models.components.lite import (
    BaseLiteComponent,
    CardLiteComponent,
    FigureLiteComponent,
    ImageLiteComponent,
    InteractiveLiteComponent,
    MultiQCLiteComponent,
    TableLiteComponent,
)
from depictio.models.models.dashboards import DashboardDataLite

_VALIDATION_TESTS_DIR = (
    Path(__file__).parent.parent.parent / "projects" / "test" / "validation_tests"
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_figure_lite() -> FigureLiteComponent:
    """Sample FigureLiteComponent for reuse."""
    return FigureLiteComponent(
        tag="scatter-1",
        visu_type="scatter",
        dict_kwargs={"x": "col1", "y": "col2", "color": "col3"},
    )


@pytest.fixture
def sample_card_lite() -> CardLiteComponent:
    """Sample CardLiteComponent for reuse."""
    return CardLiteComponent(
        tag="card-1",
        aggregation="average",
        column_name="value",
        column_type="float64",
    )


@pytest.fixture
def sample_interactive_lite() -> InteractiveLiteComponent:
    """Sample InteractiveLiteComponent for reuse."""
    return InteractiveLiteComponent(
        tag="filter-1",
        interactive_component_type="MultiSelect",
        column_name="category",
        column_type="object",
    )


@pytest.fixture
def sample_table_lite() -> TableLiteComponent:
    """Sample TableLiteComponent for reuse."""
    return TableLiteComponent(
        tag="table-1",
    )


@pytest.fixture
def sample_dashboard_yaml() -> str:
    """Sample YAML content for parsing tests."""
    return """
dashboard_id: "test-dashboard-id"
title: "Test Dashboard"
components:
  - tag: scatter-1
    component_type: figure
    visu_type: scatter
    dict_kwargs:
      x: col1
      y: col2
  - tag: card-1
    component_type: card
    aggregation: average
    column_name: value
    column_type: float64
"""


@pytest.fixture
def sample_full_dashboard_dict() -> dict:
    """Sample MongoDB-style dashboard dict for from_full() tests."""
    return {
        "dashboard_id": {"$oid": "6824cb3b89d2b72169309737"},
        "title": "Test Dashboard",
        "subtitle": "",
        "stored_metadata": [
            {
                "index": "uuid-1",
                "component_type": "figure",
                "visu_type": "scatter",
                "dict_kwargs": {"x": "col1", "y": "col2"},
            },
            {
                "index": "uuid-2",
                "component_type": "card",
                "aggregation": "sum",
                "column_name": "amount",
                "column_type": "float64",
            },
        ],
    }


# ============================================================================
# TestBaseLiteComponent
# ============================================================================


class TestBaseLiteComponent:
    """Tests for BaseLiteComponent base class."""

    def test_auto_generate_index(self):
        """Index UUID should be auto-generated when not provided."""

        class TestComponent(BaseLiteComponent):
            component_type: str = "test"

        comp = TestComponent()
        assert comp.index is not None
        # Verify it's a valid UUID format
        uuid.UUID(comp.index)

    def test_preserve_provided_index(self):
        """Provided index should be preserved."""

        class TestComponent(BaseLiteComponent):
            component_type: str = "test"

        provided_index = "my-custom-index"
        comp = TestComponent(index=provided_index)
        assert comp.index == provided_index

    def test_tag_is_optional(self):
        """Tag should be optional and default to None."""

        class TestComponent(BaseLiteComponent):
            component_type: str = "test"

        comp = TestComponent()
        assert comp.tag is None

    def test_tag_can_be_set(self):
        """Tag should accept custom value."""

        class TestComponent(BaseLiteComponent):
            component_type: str = "test"

        comp = TestComponent(tag="my-tag")
        assert comp.tag == "my-tag"


# ============================================================================
# TestFigureLiteComponent
# ============================================================================


class TestFigureLiteComponent:
    """Tests for FigureLiteComponent."""

    def test_create_with_tag(self):
        """Create component with user-friendly tag."""
        comp = FigureLiteComponent(tag="scatter-1")
        assert comp.tag == "scatter-1"
        assert comp.component_type == "figure"

    def test_auto_generate_index(self):
        """Index UUID should be auto-generated."""
        comp = FigureLiteComponent(tag="test")
        assert comp.index is not None
        # Verify it's a valid UUID
        uuid.UUID(comp.index)

    def test_default_visu_type(self):
        """Default visu_type should be 'scatter'."""
        comp = FigureLiteComponent(tag="test")
        assert comp.visu_type == "scatter"

    def test_custom_visu_type(self):
        """Custom visu_type should be preserved."""
        comp = FigureLiteComponent(tag="test", visu_type="box")
        assert comp.visu_type == "box"

    def test_dict_kwargs_basic(self):
        """dict_kwargs should accept x, y, color parameters."""
        comp = FigureLiteComponent(
            tag="test",
            dict_kwargs={"x": "col1", "y": "col2", "color": "col3"},
        )
        assert comp.dict_kwargs["x"] == "col1"
        assert comp.dict_kwargs["y"] == "col2"
        assert comp.dict_kwargs["color"] == "col3"

    def test_dict_kwargs_with_all_params(self):
        """dict_kwargs should accept full plotly express params."""
        comp = FigureLiteComponent(
            tag="test",
            visu_type="histogram",
            dict_kwargs={
                "x": "value",
                "nbins": 20,
                "color": "category",
                "barmode": "overlay",
            },
        )
        assert comp.dict_kwargs["nbins"] == 20
        assert comp.dict_kwargs["barmode"] == "overlay"

    def test_dict_kwargs_default_empty(self):
        """dict_kwargs should default to empty dict."""
        comp = FigureLiteComponent(tag="test")
        assert comp.dict_kwargs == {}

    def test_workflow_tag(self):
        """workflow_tag should be stored correctly."""
        comp = FigureLiteComponent(
            tag="test",
            workflow_tag="python/my_workflow",
            data_collection_tag="my_table",
        )
        assert comp.workflow_tag == "python/my_workflow"
        assert comp.data_collection_tag == "my_table"


# ============================================================================
# TestFigureComponent (Full)
# ============================================================================


class TestFigureComponent:
    """Tests for FigureComponent (full model inheriting from lite)."""

    def test_mode_default_ui(self):
        """Default mode should be 'ui'."""
        comp = FigureComponent()
        assert comp.mode == "ui"

    def test_mode_code(self):
        """Mode 'code' should work with code_content."""
        comp = FigureComponent(
            mode="code",
            code_content="import plotly.express as px\nfig = px.scatter(df, x='x', y='y')",
        )
        assert comp.mode == "code"
        assert comp.code_content is not None

    def test_code_content_only_in_code_mode(self):
        """code_content should be used when mode='code'."""
        code = "import plotly.express as px\nfig = px.scatter(df)"
        comp = FigureComponent(mode="code", code_content=code)
        assert comp.code_content == code

    def test_inherits_from_lite(self):
        """FigureComponent should inherit from FigureLiteComponent."""
        assert issubclass(FigureComponent, FigureLiteComponent)
        comp = FigureComponent(visu_type="box", dict_kwargs={"x": "cat", "y": "val"})
        assert comp.visu_type == "box"
        assert comp.dict_kwargs["x"] == "cat"

    def test_runtime_fields(self):
        """Runtime fields (wf_id, dc_id, dc_config) should be optional."""
        comp = FigureComponent()
        assert comp.wf_id is None
        assert comp.dc_id is None
        assert comp.dc_config == {}

    def test_runtime_fields_can_be_set(self):
        """Runtime fields should be settable."""
        comp = FigureComponent(
            wf_id="workflow-123",
            dc_id="datacollection-456",
            dc_config={"config_key": "config_value"},
        )
        assert comp.wf_id == "workflow-123"
        assert comp.dc_id == "datacollection-456"
        assert comp.dc_config["config_key"] == "config_value"


# ============================================================================
# TestCardLiteComponent
# ============================================================================


class TestCardLiteComponent:
    """Tests for CardLiteComponent."""

    def test_create_minimal(self):
        """Create with required fields only."""
        comp = CardLiteComponent(
            aggregation="sum",
            column_name="amount",
        )
        assert comp.aggregation == "sum"
        assert comp.column_name == "amount"
        assert comp.component_type == "card"

    def test_default_column_type(self):
        """Default column_type should be None (optional, not required)."""
        comp = CardLiteComponent(
            aggregation="count",
            column_name="items",
        )
        assert comp.column_type is None

    def test_optional_styling(self):
        """Optional styling fields should work."""
        comp = CardLiteComponent(
            aggregation="average",
            column_name="price",
            icon_name="mdi:currency-usd",
            icon_color="green",
            title_color="blue",
            title_font_size="18px",
            value_font_size="24px",
        )
        assert comp.icon_name == "mdi:currency-usd"
        assert comp.icon_color == "green"
        assert comp.title_color == "blue"
        assert comp.title_font_size == "18px"
        assert comp.value_font_size == "24px"

    def test_aggregation_types(self):
        """Various valid aggregation types for float64 should be accepted."""
        for agg in ["average", "sum", "count", "min", "max", "variance", "std_dev"]:
            comp = CardLiteComponent(aggregation=agg, column_name="col", column_type="float64")
            assert comp.aggregation == agg


# ============================================================================
# TestInteractiveLiteComponent
# ============================================================================


class TestInteractiveLiteComponent:
    """Tests for InteractiveLiteComponent."""

    def test_create_range_slider(self):
        """Create RangeSlider component."""
        comp = InteractiveLiteComponent(
            tag="slider-1",
            interactive_component_type="RangeSlider",
            column_name="price",
            column_type="float64",
        )
        assert comp.interactive_component_type == "RangeSlider"
        assert comp.column_name == "price"
        assert comp.column_type == "float64"
        assert comp.component_type == "interactive"

    def test_create_multi_select(self):
        """Create MultiSelect component."""
        comp = InteractiveLiteComponent(
            tag="select-1",
            interactive_component_type="MultiSelect",
            column_name="category",
            column_type="object",
        )
        assert comp.interactive_component_type == "MultiSelect"
        assert comp.column_type == "object"

    def test_default_column_type(self):
        """Default column_type should be None (optional, not required)."""
        comp = InteractiveLiteComponent(
            interactive_component_type="MultiSelect",
            column_name="col",
        )
        assert comp.column_type is None

    def test_optional_styling(self):
        """Optional styling fields should work."""
        comp = InteractiveLiteComponent(
            interactive_component_type="MultiSelect",
            column_name="col",
            title_size="16px",
            custom_color="purple",
            icon_name="mdi:filter",
        )
        assert comp.title_size == "16px"
        assert comp.custom_color == "purple"
        assert comp.icon_name == "mdi:filter"


# ============================================================================
# TestTableLiteComponent
# ============================================================================


class TestTableLiteComponent:
    """Tests for TableLiteComponent."""

    def test_create_minimal(self):
        """Create with defaults."""
        comp = TableLiteComponent(tag="table-1")
        assert comp.tag == "table-1"
        assert comp.component_type == "table"
        assert comp.columns == []
        assert comp.page_size == 10
        assert comp.sortable is True
        assert comp.filterable is True

    def test_custom_page_size(self):
        """Custom page_size should be preserved."""
        comp = TableLiteComponent(tag="table-1", page_size=25)
        assert comp.page_size == 25

    def test_custom_columns(self):
        """Custom columns should be preserved."""
        comp = TableLiteComponent(
            tag="table-1",
            columns=["col1", "col2", "col3"],
        )
        assert comp.columns == ["col1", "col2", "col3"]

    def test_disable_features(self):
        """Sortable and filterable can be disabled."""
        comp = TableLiteComponent(
            tag="table-1",
            sortable=False,
            filterable=False,
        )
        assert comp.sortable is False
        assert comp.filterable is False


# ============================================================================
# TestDashboardDataLite
# ============================================================================


class TestDashboardDataLite:
    """Tests for DashboardDataLite."""

    def test_create_empty(self):
        """Create dashboard with no components."""
        dash = DashboardDataLite(title="Empty Dashboard")
        assert dash.title == "Empty Dashboard"
        assert dash.components == []
        assert dash.subtitle == ""

    def test_create_with_components(
        self, sample_figure_lite: FigureLiteComponent, sample_card_lite: CardLiteComponent
    ):
        """Create dashboard with components."""
        dash = DashboardDataLite(
            title="Test Dashboard",
            components=[sample_figure_lite, sample_card_lite],
        )
        assert len(dash.components) == 2

    def test_from_yaml(self, sample_dashboard_yaml: str):
        """Parse YAML string to model."""
        dash = DashboardDataLite.from_yaml(sample_dashboard_yaml)
        assert dash.title == "Test Dashboard"
        assert dash.dashboard_id == "test-dashboard-id"
        assert len(dash.components) == 2

    def test_from_yaml_invalid_yaml(self):
        """Invalid YAML should raise ValueError."""
        invalid_yaml = "title: [unclosed bracket"
        with pytest.raises(ValueError, match="Invalid YAML"):
            DashboardDataLite.from_yaml(invalid_yaml)

    def test_from_yaml_not_dict(self):
        """YAML that is not a dict should raise ValueError."""
        not_dict_yaml = "- item1\n- item2"
        with pytest.raises(ValueError, match="must contain a dictionary"):
            DashboardDataLite.from_yaml(not_dict_yaml)

    def test_from_yaml_missing_required(self):
        """Missing required fields should raise ValidationError."""
        missing_title = "components: []"
        with pytest.raises(ValidationError):
            DashboardDataLite.from_yaml(missing_title)

    def test_to_yaml(self, sample_figure_lite: FigureLiteComponent):
        """Export model to YAML string."""
        dash = DashboardDataLite(
            title="Export Test",
            components=[sample_figure_lite],
        )
        yaml_str = dash.to_yaml()
        assert "title: Export Test" in yaml_str
        assert "tag: scatter-1" in yaml_str
        assert "component_type: figure" in yaml_str

    def test_to_yaml_excludes_index(self, sample_figure_lite: FigureLiteComponent):
        """YAML output should use tag, not UUID index."""
        dash = DashboardDataLite(
            title="Test",
            components=[sample_figure_lite],
        )
        yaml_str = dash.to_yaml()
        # Index should not appear in YAML output
        assert "index:" not in yaml_str
        # Tag should appear
        assert "tag:" in yaml_str

    def test_from_full_generates_tags(self, sample_full_dashboard_dict: dict):
        """from_full() should generate readable tags with format {type}-{semantic_id}-{hash}."""
        lite = DashboardDataLite.from_full(sample_full_dashboard_dict)
        assert lite.title == "Test Dashboard"
        assert len(lite.components) == 2
        # Check that tags were generated with correct type prefix and 6-char hash suffix
        tags = [c["tag"] if isinstance(c, dict) else c.tag for c in lite.components]
        assert any(t.startswith("figure-") for t in tags)
        assert any(t.startswith("card-") for t in tags)
        # Each tag should end with a 6-char hash (e.g., "figure-uuid-1-d4feb7")
        for tag in tags:
            parts = tag.split("-")
            assert len(parts) >= 2, f"Tag '{tag}' should have at least type and hash parts"
            assert len(parts[-1]) == 6, f"Tag '{tag}' should end with a 6-char hash"

    def test_from_full_extracts_dashboard_id(self, sample_full_dashboard_dict: dict):
        """from_full() should extract dashboard_id from $oid format."""
        lite = DashboardDataLite.from_full(sample_full_dashboard_dict)
        assert lite.dashboard_id == "6824cb3b89d2b72169309737"

    def test_from_full_preserves_existing_tags(self):
        """from_full() should preserve existing tags if present."""
        full_dict = {
            "dashboard_id": "123",
            "title": "Test",
            "stored_metadata": [
                {
                    "index": "uuid-1",
                    "tag": "my-custom-tag",
                    "component_type": "figure",
                    "visu_type": "scatter",
                },
            ],
        }
        lite = DashboardDataLite.from_full(full_dict)
        tag = (
            lite.components[0]["tag"]
            if isinstance(lite.components[0], dict)
            else lite.components[0].tag
        )
        assert tag == "my-custom-tag"

    def test_validate_yaml_valid(self, sample_dashboard_yaml: str):
        """validate_yaml() should return (True, []) for valid YAML."""
        is_valid, errors = DashboardDataLite.validate_yaml(sample_dashboard_yaml)
        assert is_valid is True
        assert errors == []

    def test_validate_yaml_invalid_yaml(self):
        """validate_yaml() should return (False, errors) for invalid YAML."""
        invalid_yaml = "title: [unclosed"
        is_valid, errors = DashboardDataLite.validate_yaml(invalid_yaml)
        assert is_valid is False
        assert len(errors) > 0
        assert errors[0]["type"] == "yaml_error"

    def test_validate_yaml_invalid_schema(self):
        """validate_yaml() should return (False, errors) for schema violations."""
        invalid_schema = "components: []"  # Missing required 'title'
        is_valid, errors = DashboardDataLite.validate_yaml(invalid_schema)
        assert is_valid is False
        assert len(errors) > 0

    def test_to_full(self):
        """to_full() should convert lite format to full dashboard dict."""
        dash = DashboardDataLite(
            dashboard_id="test-id",
            title="Full Test",
            components=[
                {
                    "tag": "fig-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "dict_kwargs": {"x": "a", "y": "b"},
                }
            ],
        )
        full = dash.to_full()
        assert full["title"] == "Full Test"
        assert full["dashboard_id"] == "test-id"
        assert "stored_metadata" in full
        assert len(full["stored_metadata"]) == 1
        assert full["stored_metadata"][0]["visu_type"] == "scatter"

    def test_to_full_generates_layout(self):
        """to_full() should auto-generate layout data using split-panel system."""
        dash = DashboardDataLite(
            title="Layout Test",
            components=[
                {"tag": "fig-1", "component_type": "figure"},
                {
                    "tag": "card-1",
                    "component_type": "card",
                    "aggregation": "sum",
                    "column_name": "col",
                },
            ],
        )
        full = dash.to_full()
        # All dashboards use split-panel: figure + card → right_panel_layout_data
        assert "right_panel_layout_data" in full
        assert len(full["right_panel_layout_data"]) == 2
        assert len(full["stored_layout_data"]) == 0

    def test_roundtrip_yaml(self):
        """Test YAML export and re-import preserves data."""
        original = DashboardDataLite(
            title="Roundtrip Test",
            subtitle="Testing YAML roundtrip",
            components=[
                {
                    "tag": "scatter-main",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "workflow_tag": "python/test",
                    "data_collection_tag": "test_data",
                    "dict_kwargs": {"x": "col1", "y": "col2"},
                }
            ],
        )
        yaml_str = original.to_yaml()
        restored = DashboardDataLite.from_yaml(yaml_str)

        assert restored.title == original.title
        assert len(restored.components) == len(original.components)


# ============================================================================
# Test to_full() Tag Resolution Structure
# ============================================================================


class TestToFullTagResolution:
    """Tests for DashboardDataLite.to_full() tag handling for API import."""

    @pytest.fixture
    def yaml_with_tags(self) -> str:
        """YAML content with workflow and data collection tags."""
        return """
title: "Tag Resolution Test"
components:
  - tag: scatter-1
    component_type: figure
    workflow_tag: python/iris_workflow
    data_collection_tag: iris_table
    visu_type: scatter
    dict_kwargs:
      x: sepal.length
      y: sepal.width
  - tag: card-1
    component_type: card
    workflow_tag: python/iris_workflow
    data_collection_tag: iris_table
    aggregation: average
    column_name: sepal.length
    column_type: float64
"""

    def test_to_full_preserves_workflow_tag(self, yaml_with_tags: str):
        """to_full() should preserve workflow_tag in stored_metadata."""
        lite = DashboardDataLite.from_yaml(yaml_with_tags)
        full_dict = lite.to_full()

        # Check that workflow_tag is preserved
        for comp in full_dict["stored_metadata"]:
            if comp.get("workflow_tag"):
                assert comp["workflow_tag"] == "python/iris_workflow"

    def test_to_full_preserves_data_collection_tag(self, yaml_with_tags: str):
        """to_full() should preserve data_collection_tag in stored_metadata."""
        lite = DashboardDataLite.from_yaml(yaml_with_tags)
        full_dict = lite.to_full()

        # Check that data_collection_tag is preserved
        for comp in full_dict["stored_metadata"]:
            if comp.get("data_collection_tag"):
                assert comp["data_collection_tag"] == "iris_table"

    def test_to_full_sets_wf_id_to_none(self, yaml_with_tags: str):
        """to_full() should set wf_id to None (resolution happens at import)."""
        lite = DashboardDataLite.from_yaml(yaml_with_tags)
        full_dict = lite.to_full()

        # wf_id should be None - will be resolved at import time
        for comp in full_dict["stored_metadata"]:
            assert comp.get("wf_id") is None

    def test_to_full_sets_dc_id_to_none(self, yaml_with_tags: str):
        """to_full() should set dc_id to None (resolution happens at import)."""
        lite = DashboardDataLite.from_yaml(yaml_with_tags)
        full_dict = lite.to_full()

        # dc_id should be None - will be resolved at import time
        for comp in full_dict["stored_metadata"]:
            assert comp.get("dc_id") is None

    def test_to_full_initializes_dc_config(self, yaml_with_tags: str):
        """to_full() should initialize dc_config as empty dict."""
        lite = DashboardDataLite.from_yaml(yaml_with_tags)
        full_dict = lite.to_full()

        for comp in full_dict["stored_metadata"]:
            assert "dc_config" in comp
            assert isinstance(comp["dc_config"], dict)

    def test_to_full_generates_unique_indices(self, yaml_with_tags: str):
        """to_full() should generate unique UUID indices for all components."""
        lite = DashboardDataLite.from_yaml(yaml_with_tags)
        full_dict = lite.to_full()

        indices = [comp["index"] for comp in full_dict["stored_metadata"]]
        # All indices should be unique
        assert len(indices) == len(set(indices))
        # Indices should look like UUIDs (36 chars with hyphens)
        for idx in indices:
            assert len(idx) == 36
            assert idx.count("-") == 4

    def test_to_full_layout_references_match_indices(self, yaml_with_tags: str):
        """to_full() layout 'i' values should match component indices (split-panel)."""
        lite = DashboardDataLite.from_yaml(yaml_with_tags)
        full_dict = lite.to_full()

        comp_indices = {comp["index"] for comp in full_dict["stored_metadata"]}
        # All dashboards use split-panel: collect refs from both left and right panels
        layout_refs = {
            layout["i"].replace("box-", "")
            for panel_key in [
                "stored_layout_data",
                "left_panel_layout_data",
                "right_panel_layout_data",
            ]
            for layout in full_dict.get(panel_key, [])
        }

        # All layout references should point to valid component indices
        assert layout_refs == comp_indices


# ============================================================================
# Test Import Tag Resolution Logic (unit test without MongoDB)
# ============================================================================


class TestImportTagResolutionLogic:
    """Tests for the tag resolution logic used in the import endpoint."""

    def test_resolution_updates_wf_id_when_found(self):
        """When workflow is found, wf_id should be updated."""
        from bson import ObjectId

        # Simulate the resolution logic from routes.py
        component = {
            "workflow_tag": "python/test_workflow",
            "data_collection_tag": "test_table",
            "wf_id": None,
            "dc_id": None,
            "dc_config": {},
        }

        # Simulate finding a matching workflow
        mock_wf_id = ObjectId()
        mock_dc_id = ObjectId()

        # This mimics the resolution logic in import_dashboard_from_yaml
        wf_tag = component.get("workflow_tag")
        if wf_tag:
            wf_name = wf_tag.split("/", 1)[1] if "/" in wf_tag else wf_tag

            # Simulate finding a match
            if wf_name == "test_workflow":
                component["wf_id"] = mock_wf_id
                component["wf_tag"] = f"python/{wf_name}"

                # Simulate finding matching DC
                dc_tag = component.get("data_collection_tag")
                if dc_tag == "test_table":
                    component["dc_id"] = mock_dc_id
                    component["dc_config"] = {
                        "_id": mock_dc_id,
                        "data_collection_tag": "test_table",
                    }

        assert component["wf_id"] == mock_wf_id
        assert component["dc_id"] == mock_dc_id
        assert component["dc_config"]["_id"] == mock_dc_id

    def test_resolution_handles_engine_prefix(self):
        """Workflow tag with engine prefix should be parsed correctly."""
        # Test various workflow tag formats
        test_cases = [
            ("python/my_workflow", "my_workflow"),
            ("snakemake/pipeline", "pipeline"),
            ("nextflow/analysis", "analysis"),
            ("simple_workflow", "simple_workflow"),  # No prefix
        ]

        for wf_tag, expected_name in test_cases:
            wf_name = wf_tag.split("/", 1)[1] if "/" in wf_tag else wf_tag
            assert wf_name == expected_name, f"Failed for {wf_tag}"

    def test_resolution_preserves_tags_when_not_found(self):
        """When workflow/DC not found, tags should be preserved."""
        component = {
            "workflow_tag": "python/nonexistent",
            "data_collection_tag": "nonexistent_table",
            "wf_id": None,
            "dc_id": None,
            "dc_config": {},
        }

        # Simulate NOT finding any match - wf_id and dc_id stay None
        # but tags should remain for debugging/reference
        assert component["wf_id"] is None
        assert component["dc_id"] is None
        assert component["workflow_tag"] == "python/nonexistent"
        assert component["data_collection_tag"] == "nonexistent_table"


# ============================================================================
# TestDomainValidation — enum-like fields and cross-field constraints
# ============================================================================


class TestFigureDomainValidation:
    """Tests for FigureLiteComponent domain validation."""

    def test_invalid_visu_type_raises(self):
        """Invalid visu_type in ui mode should raise ValidationError."""
        with pytest.raises(ValidationError, match="visu_type"):
            FigureLiteComponent(tag="test", visu_type="invalid_chart")

    def test_all_valid_visu_types_pass(self):
        """All valid visu_types should pass validation."""
        for visu in ["scatter", "line", "bar", "box", "histogram"]:
            comp = FigureLiteComponent(tag="test", visu_type=visu)
            assert comp.visu_type == visu

    def test_code_mode_without_code_content_raises(self):
        """mode='code' without code_content should raise ValidationError."""
        with pytest.raises(ValidationError, match="code_content"):
            FigureLiteComponent(tag="test", mode="code")

    def test_code_mode_with_blank_code_content_raises(self):
        """mode='code' with blank code_content should raise ValidationError."""
        with pytest.raises(ValidationError, match="code_content"):
            FigureLiteComponent(tag="test", mode="code", code_content="   ")

    def test_code_mode_with_code_content_passes(self):
        """mode='code' with non-empty code_content should pass."""
        comp = FigureLiteComponent(
            tag="test",
            mode="code",
            code_content="import plotly.express as px\nfig = px.scatter(df)",
        )
        assert comp.mode == "code"

    def test_code_mode_ignores_visu_type_constraint(self):
        """In code mode, visu_type is not validated against allowed list."""
        comp = FigureLiteComponent(
            tag="test",
            mode="code",
            visu_type="arbitrary_type",
            code_content="fig = go.Figure()",
        )
        assert comp.visu_type == "arbitrary_type"

    def test_invalid_mode_raises(self):
        """Invalid mode value should raise ValidationError."""
        with pytest.raises(ValidationError, match="mode"):
            FigureLiteComponent(tag="test", mode="interactive")

    def test_selection_enabled_without_selection_column_raises(self):
        """selection_enabled=True without selection_column should raise ValidationError."""
        with pytest.raises(ValidationError, match="selection_column"):
            FigureLiteComponent(tag="test", selection_enabled=True)

    def test_selection_enabled_with_selection_column_passes(self):
        """selection_enabled=True with selection_column should pass."""
        comp = FigureLiteComponent(
            tag="test",
            selection_enabled=True,
            selection_column="sample_id",
        )
        assert comp.selection_column == "sample_id"

    def test_selection_disabled_without_column_passes(self):
        """selection_enabled=False without selection_column is fine."""
        comp = FigureLiteComponent(tag="test", selection_enabled=False)
        assert comp.selection_column is None


class TestCardDomainValidation:
    """Tests for CardLiteComponent domain validation."""

    def test_invalid_column_type_raises(self):
        """Invalid column_type should raise ValidationError."""
        with pytest.raises(ValidationError, match="column_type"):
            CardLiteComponent(aggregation="count", column_name="col", column_type="string")

    def test_all_valid_column_types_with_count_pass(self):
        """'count' aggregation is valid for every column_type."""
        for ct in ["int64", "float64", "bool", "datetime", "timedelta", "category", "object"]:
            comp = CardLiteComponent(aggregation="count", column_name="col", column_type=ct)
            assert comp.column_type == ct

    def test_average_invalid_for_object_raises(self):
        """'average' aggregation is not valid for 'object' column_type."""
        with pytest.raises(ValidationError, match="aggregation"):
            CardLiteComponent(aggregation="average", column_name="col", column_type="object")

    def test_average_invalid_for_bool_raises(self):
        """'average' aggregation is not valid for 'bool' column_type."""
        with pytest.raises(ValidationError, match="aggregation"):
            CardLiteComponent(aggregation="average", column_name="col", column_type="bool")

    def test_average_valid_for_float64_passes(self):
        """'average' aggregation is valid for 'float64'."""
        comp = CardLiteComponent(aggregation="average", column_name="col", column_type="float64")
        assert comp.aggregation == "average"

    def test_mode_valid_for_category_passes(self):
        """'mode' aggregation is valid for 'category'."""
        comp = CardLiteComponent(aggregation="mode", column_name="col", column_type="category")
        assert comp.aggregation == "mode"

    def test_sum_invalid_for_category_raises(self):
        """'sum' aggregation is not valid for 'category'."""
        with pytest.raises(ValidationError, match="aggregation"):
            CardLiteComponent(aggregation="sum", column_name="col", column_type="category")

    def test_variance_valid_for_int64_passes(self):
        """'variance' is valid for 'int64'."""
        comp = CardLiteComponent(aggregation="variance", column_name="col", column_type="int64")
        assert comp.aggregation == "variance"

    def test_no_column_type_skips_validation(self):
        """When column_type is None (not provided), aggregation is not validated."""
        # 'mode' would fail for 'float64', but with no column_type it's accepted
        comp = CardLiteComponent(aggregation="mode", column_name="variety")
        assert comp.column_type is None
        assert comp.aggregation == "mode"


class TestInteractiveDomainValidation:
    """Tests for InteractiveLiteComponent domain validation."""

    def test_invalid_column_type_raises(self):
        """Invalid column_type should raise ValidationError."""
        with pytest.raises(ValidationError, match="column_type"):
            InteractiveLiteComponent(
                interactive_component_type="Slider",
                column_name="col",
                column_type="integer",
            )

    def test_slider_valid_for_float64_passes(self):
        """Slider is valid for float64."""
        comp = InteractiveLiteComponent(
            interactive_component_type="Slider",
            column_name="col",
            column_type="float64",
        )
        assert comp.interactive_component_type == "Slider"

    def test_slider_valid_for_int64_passes(self):
        """Slider is valid for int64."""
        comp = InteractiveLiteComponent(
            interactive_component_type="Slider",
            column_name="col",
            column_type="int64",
        )
        assert comp.interactive_component_type == "Slider"

    def test_slider_invalid_for_object_raises(self):
        """Slider is not valid for object column_type."""
        with pytest.raises(ValidationError, match="interactive_component_type"):
            InteractiveLiteComponent(
                interactive_component_type="Slider",
                column_name="col",
                column_type="object",
            )

    # Checkbox/Switch not yet implemented in frontend — bool has no valid interactive components
    # def test_checkbox_valid_for_bool_passes(self):
    #     """Checkbox is valid for bool."""
    #     comp = InteractiveLiteComponent(
    #         interactive_component_type="Checkbox",
    #         column_name="col",
    #         column_type="bool",
    #     )
    #     assert comp.interactive_component_type == "Checkbox"

    # def test_checkbox_invalid_for_float64_raises(self):
    #     """Checkbox is not valid for float64. (Checkbox not yet implemented)"""
    #     with pytest.raises(ValidationError, match="interactive_component_type"):
    #         InteractiveLiteComponent(
    #             interactive_component_type="Checkbox",
    #             column_name="col",
    #             column_type="float64",
    #         )

    def test_date_range_picker_valid_for_datetime_passes(self):
        """DateRangePicker is valid for datetime."""
        comp = InteractiveLiteComponent(
            interactive_component_type="DateRangePicker",
            column_name="col",
            column_type="datetime",
        )
        assert comp.interactive_component_type == "DateRangePicker"

    def test_multiselect_valid_for_category_passes(self):
        """MultiSelect is valid for category."""
        comp = InteractiveLiteComponent(
            interactive_component_type="MultiSelect",
            column_name="col",
            column_type="category",
        )
        assert comp.interactive_component_type == "MultiSelect"

    def test_multiselect_valid_for_object_passes(self):
        """MultiSelect is valid for object."""
        comp = InteractiveLiteComponent(
            interactive_component_type="MultiSelect",
            column_name="col",
            column_type="object",
        )
        assert comp.interactive_component_type == "MultiSelect"

    def test_timedelta_raises_no_components(self):
        """timedelta column_type has no interactive components — should raise when specified."""
        with pytest.raises(ValidationError, match="No interactive components"):
            InteractiveLiteComponent(
                interactive_component_type="Slider",
                column_name="col",
                column_type="timedelta",
            )

    def test_no_column_type_skips_validation(self):
        """When column_type is None (not provided), compatibility is not validated."""
        # This would fail if column_type were "object" (Slider not valid for object)
        # but with None it's accepted — runtime/import will resolve the type
        comp = InteractiveLiteComponent(
            interactive_component_type="Slider",
            column_name="some_numeric_col",
        )
        assert comp.column_type is None
        assert comp.interactive_component_type == "Slider"

    def test_all_valid_interactive_types_for_object(self):
        """All valid interactive types for 'object' column_type should pass."""
        for it in ["Select", "MultiSelect", "SegmentedControl"]:
            comp = InteractiveLiteComponent(
                interactive_component_type=it,
                column_name="col",
                column_type="object",
            )
            assert comp.interactive_component_type == it

    def test_range_slider_invalid_for_category_raises(self):
        """RangeSlider is not valid for category."""
        with pytest.raises(ValidationError, match="interactive_component_type"):
            InteractiveLiteComponent(
                interactive_component_type="RangeSlider",
                column_name="col",
                column_type="category",
            )


# ---------------------------------------------------------------------------
# Image component
# ---------------------------------------------------------------------------


class TestImageLiteComponent:
    """Unit tests for ImageLiteComponent."""

    def test_valid_minimal_image(self):
        """Minimal valid image component with only required fields."""
        comp = ImageLiteComponent(
            tag="img-1",
            workflow_tag="python/iris_workflow",
            data_collection_tag="iris_table",
            image_column="image_path",
        )
        assert comp.component_type == "image"
        assert comp.image_column == "image_path"
        assert comp.thumbnail_size == 150
        assert comp.columns == 4
        assert comp.max_images == 20

    def test_valid_image_with_display_options(self):
        """Image component with non-default display options."""
        comp = ImageLiteComponent(
            tag="img-2",
            workflow_tag="python/iris_workflow",
            data_collection_tag="iris_table",
            image_column="thumb_path",
            thumbnail_size=200,
            columns=6,
            max_images=50,
        )
        assert comp.thumbnail_size == 200
        assert comp.columns == 6
        assert comp.max_images == 50

    def test_image_missing_image_column_raises(self):
        """image_column is required — omitting it must raise ValidationError."""
        with pytest.raises(ValidationError):
            ImageLiteComponent(
                tag="img-bad",
                workflow_tag="python/iris_workflow",
                data_collection_tag="iris_table",
            )

    def test_image_component_type_is_literal(self):
        """component_type is always 'image'."""
        comp = ImageLiteComponent(
            image_column="col",
            workflow_tag="wf",
            data_collection_tag="dc",
        )
        assert comp.component_type == "image"


# ---------------------------------------------------------------------------
# Validation YAML files — offline behaviour
# ---------------------------------------------------------------------------


class TestValidationYAMLFiles:
    """Verify that each test YAML file behaves as documented (offline only).

    These tests do NOT require a running server — they only exercise
    schema + domain validation (Pass 1 of validate_yaml).

    Online checks (Pass 2, column-name / type inference against server
    delta table schema) are not tested here.
    """

    # ------------------------------------------------------------------
    # test_01 — invalid visu_type values: must FAIL offline
    # ------------------------------------------------------------------

    def test_01_invalid_visu_type_fails_offline(self):
        """Pie, treemap, 3d_scatter are not valid visu_type values."""
        content = (_VALIDATION_TESTS_DIR / "test_01_invalid_visu_type.yaml").read_text()
        is_valid, errors = DashboardDataLite.validate_yaml(content)
        assert not is_valid, "Expected offline validation to fail"
        msgs = " ".join(e.get("msg", "") for e in errors)
        assert "visu_type" in msgs or "Invalid" in msgs

    # ------------------------------------------------------------------
    # test_02 — aggregation × column_type: PASS offline (no column_type)
    # ------------------------------------------------------------------

    def test_02_agg_mismatch_passes_offline(self):
        """Without explicit column_type the offline check is skipped — valid schema."""
        content = (_VALIDATION_TESTS_DIR / "test_02_agg_column_type_mismatch.yaml").read_text()
        is_valid, errors = DashboardDataLite.validate_yaml(content)
        assert is_valid, f"Expected offline validation to pass, got: {errors}"

    # ------------------------------------------------------------------
    # test_03 — interactive type × column_type: PASS offline (no column_type)
    # ------------------------------------------------------------------

    def test_03_interactive_mismatch_passes_offline(self):
        """Without explicit column_type the offline check is skipped — valid schema."""
        content = (_VALIDATION_TESTS_DIR / "test_03_interactive_type_mismatch.yaml").read_text()
        is_valid, errors = DashboardDataLite.validate_yaml(content)
        assert is_valid, f"Expected offline validation to pass, got: {errors}"

    # ------------------------------------------------------------------
    # test_04 — wrong wf/dc tags: PASS offline (free-text, no server lookup)
    # ------------------------------------------------------------------

    def test_04_wrong_wf_dc_tags_passes_offline(self):
        """Wrong workflow/dc tags are not caught offline — PASS."""
        content = (_VALIDATION_TESTS_DIR / "test_04_wrong_wf_dc_tags.yaml").read_text()
        is_valid, errors = DashboardDataLite.validate_yaml(content)
        assert is_valid, f"Expected offline validation to pass, got: {errors}"

    # ------------------------------------------------------------------
    # test_05 — code mode / selection errors: must FAIL offline
    # ------------------------------------------------------------------

    def test_05_code_mode_errors_fails_offline(self):
        """code_content missing and invalid mode must fail offline."""
        content = (
            _VALIDATION_TESTS_DIR / "test_05_code_mode_and_selection_errors.yaml"
        ).read_text()
        is_valid, errors = DashboardDataLite.validate_yaml(content)
        assert not is_valid, "Expected offline validation to fail"
        msgs = " ".join(e.get("msg", "") for e in errors)
        assert "code_content" in msgs or "mode" in msgs or "selection_column" in msgs

    def test_05_code_mode_errors_reports_all_components(self):
        """Each failing component gets its own error entry."""
        content = (
            _VALIDATION_TESTS_DIR / "test_05_code_mode_and_selection_errors.yaml"
        ).read_text()
        _, errors = DashboardDataLite.validate_yaml(content)
        # At least 3 failing components: code-no-content, invalid-mode, select-no-col
        assert len(errors) >= 3

    # ------------------------------------------------------------------
    # test_06 — image / multiqc required fields: must FAIL offline
    # ------------------------------------------------------------------

    def test_06_required_fields_fail_offline(self):
        """image_column, selected_module, selected_plot are all required."""
        content = (_VALIDATION_TESTS_DIR / "test_06_image_and_multiqc.yaml").read_text()
        is_valid, errors = DashboardDataLite.validate_yaml(content)
        assert not is_valid, "Expected offline validation to fail"
        tags = [e.get("tag", "") for e in errors]
        assert "image-missing-column" in tags
        assert "multiqc-missing-module" in tags
        assert "multiqc-missing-plot" in tags

    def test_06_valid_image_and_multiqc_pass(self):
        """Valid image + multiqc (both required fields) are accepted."""
        valid_yaml = """
title: "Inline test"
project_tag: "Test"
components:
  - tag: img-ok
    component_type: image
    workflow_tag: python/wf
    data_collection_tag: dc
    image_column: image_path
  - tag: mqc-ok
    component_type: multiqc
    workflow_tag: python/wf
    data_collection_tag: dc
    selected_module: fastqc
    selected_plot: per_base_sequence_quality
"""
        is_valid, errors = DashboardDataLite.validate_yaml(valid_yaml)
        assert is_valid, f"Expected to pass, got: {errors}"


# ---------------------------------------------------------------------------
# MultiQC component
# ---------------------------------------------------------------------------


class TestMultiQCLiteComponent:
    """Unit tests for MultiQCLiteComponent."""

    def test_valid_multiqc(self):
        """Both selected_module and selected_plot provided — must pass."""
        comp = MultiQCLiteComponent(
            tag="mqc-1",
            workflow_tag="python/nf_workflow",
            data_collection_tag="multiqc_report",
            selected_module="fastqc",
            selected_plot="per_base_sequence_quality",
        )
        assert comp.component_type == "multiqc"
        assert comp.selected_module == "fastqc"
        assert comp.selected_plot == "per_base_sequence_quality"

    def test_multiqc_missing_module_raises(self):
        """selected_module is required."""
        with pytest.raises(ValidationError):
            MultiQCLiteComponent(
                tag="mqc-bad",
                workflow_tag="python/wf",
                data_collection_tag="dc",
                selected_plot="some_plot",
            )

    def test_multiqc_missing_plot_raises(self):
        """selected_plot is required."""
        with pytest.raises(ValidationError):
            MultiQCLiteComponent(
                tag="mqc-bad",
                workflow_tag="python/wf",
                data_collection_tag="dc",
                selected_module="fastqc",
            )

    def test_multiqc_component_type_is_literal(self):
        """component_type is always 'multiqc'."""
        comp = MultiQCLiteComponent(
            workflow_tag="wf",
            data_collection_tag="dc",
            selected_module="mod",
            selected_plot="plot",
        )
        assert comp.component_type == "multiqc"
