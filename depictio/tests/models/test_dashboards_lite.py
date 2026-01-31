"""
Unit Tests for DashboardDataLite and Lite Component Models.

Tests the lightweight dashboard and component models used for YAML import/export.
"""

import uuid

import pytest
from pydantic import ValidationError

from depictio.models.components.figure import FigureComponent
from depictio.models.components.lite import (
    BaseLiteComponent,
    CardLiteComponent,
    FigureLiteComponent,
    InteractiveLiteComponent,
    TableLiteComponent,
)
from depictio.models.models.dashboards import DashboardDataLite

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
        """Default column_type should be 'float64'."""
        comp = CardLiteComponent(
            aggregation="count",
            column_name="items",
        )
        assert comp.column_type == "float64"

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
        """Various aggregation types should be accepted."""
        for agg in ["average", "sum", "count", "min", "max", "first", "last"]:
            comp = CardLiteComponent(aggregation=agg, column_name="col")
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
        """Default column_type should be 'object'."""
        comp = InteractiveLiteComponent(
            interactive_component_type="MultiSelect",
            column_name="col",
        )
        assert comp.column_type == "object"

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
        """from_full() should generate readable tags."""
        lite = DashboardDataLite.from_full(sample_full_dashboard_dict)
        assert lite.title == "Test Dashboard"
        assert len(lite.components) == 2
        # Check that tags were generated
        tags = [c["tag"] if isinstance(c, dict) else c.tag for c in lite.components]
        assert "figure-1" in tags
        assert "card-1" in tags

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
        """to_full() should auto-generate layout data."""
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
        assert "stored_layout_data" in full
        assert len(full["stored_layout_data"]) == 2

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
