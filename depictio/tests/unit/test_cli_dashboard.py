"""
Unit Tests for Dashboard CLI Commands.

Tests the CLI commands for YAML validation, conversion, and the full
YAML → DashboardDataLite → DashboardData conversion pipeline.
"""

import json
from pathlib import Path

import pytest
from bson import ObjectId
from typer.testing import CliRunner

from depictio.cli.cli.commands.dashboard import app, validate_yaml_with_pydantic
from depictio.models.models.dashboards import DashboardData, DashboardDataLite
from depictio.models.models.users import Permission

runner = CliRunner()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def valid_yaml_content() -> str:
    """Valid dashboard YAML content."""
    return """
title: "Test Dashboard"
subtitle: "Testing the conversion pipeline"
components:
  - tag: scatter-1
    component_type: figure
    workflow_tag: python/iris_workflow
    data_collection_tag: iris_table
    visu_type: scatter
    dict_kwargs:
      x: sepal.length
      y: sepal.width
      color: variety
  - tag: card-1
    component_type: card
    workflow_tag: python/iris_workflow
    data_collection_tag: iris_table
    aggregation: average
    column_name: sepal.length
    column_type: float64
  - tag: filter-1
    component_type: interactive
    workflow_tag: python/iris_workflow
    data_collection_tag: iris_table
    interactive_component_type: MultiSelect
    column_name: variety
    column_type: object
  - tag: table-1
    component_type: table
    workflow_tag: python/iris_workflow
    data_collection_tag: iris_table
"""


@pytest.fixture
def invalid_yaml_content() -> str:
    """Invalid YAML syntax."""
    return """
title: [unclosed bracket
components: []
"""


@pytest.fixture
def invalid_schema_yaml() -> str:
    """YAML with missing required fields."""
    return """
components:
  - tag: test
    component_type: figure
"""


@pytest.fixture
def full_dashboard_json() -> dict:
    """Full dashboard JSON as would be exported from MongoDB."""
    return {
        "dashboard_id": {"$oid": "6824cb3b89d2b72169309737"},
        "title": "Iris Dashboard",
        "subtitle": "Demonstrating the Iris dataset",
        "stored_metadata": [
            {
                "index": "uuid-scatter-1",
                "component_type": "figure",
                "visu_type": "scatter",
                "dict_kwargs": {"x": "sepal.length", "y": "sepal.width", "color": "variety"},
                "wf_id": "wf-123",
                "dc_id": "dc-456",
                "dc_config": {"data_collection_tag": "iris_table"},
            },
            {
                "index": "uuid-card-1",
                "component_type": "card",
                "aggregation": "average",
                "column_name": "sepal.length",
                "column_type": "float64",
            },
            {
                "index": "uuid-interactive-1",
                "component_type": "interactive",
                "interactive_component_type": "RangeSlider",
                "column_name": "sepal.length",
                "column_type": "float64",
            },
            {
                "index": "uuid-table-1",
                "component_type": "table",
                "columns": [],
                "page_size": 10,
            },
        ],
    }


@pytest.fixture
def sample_permission() -> Permission:
    """Sample Permission for DashboardData tests."""
    return Permission(owners=[], editors=[], viewers=[])


@pytest.fixture
def sample_project_id() -> str:
    """Sample project ID for DashboardData tests."""
    return str(ObjectId())


@pytest.fixture
def valid_yaml_file(tmp_path: Path, valid_yaml_content: str) -> Path:
    """Create a temporary valid YAML file."""
    yaml_file = tmp_path / "dashboard.yaml"
    yaml_file.write_text(valid_yaml_content, encoding="utf-8")
    return yaml_file


@pytest.fixture
def invalid_yaml_file(tmp_path: Path, invalid_yaml_content: str) -> Path:
    """Create a temporary invalid YAML file."""
    yaml_file = tmp_path / "invalid.yaml"
    yaml_file.write_text(invalid_yaml_content, encoding="utf-8")
    return yaml_file


@pytest.fixture
def full_json_file(tmp_path: Path, full_dashboard_json: dict) -> Path:
    """Create a temporary JSON file with full dashboard data."""
    json_file = tmp_path / "dashboard.json"
    json_file.write_text(json.dumps(full_dashboard_json, indent=2), encoding="utf-8")
    return json_file


# ============================================================================
# Test validate_yaml_with_pydantic function
# ============================================================================


class TestValidateYamlWithPydantic:
    """Tests for the validate_yaml_with_pydantic helper function."""

    def test_valid_yaml(self, valid_yaml_file: Path):
        """Valid YAML should return valid=True with no errors."""
        result = validate_yaml_with_pydantic(valid_yaml_file)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_invalid_yaml_syntax(self, invalid_yaml_file: Path):
        """Invalid YAML syntax should return valid=False with errors."""
        result = validate_yaml_with_pydantic(invalid_yaml_file)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_file_not_found(self, tmp_path: Path):
        """Non-existent file should return valid=False."""
        result = validate_yaml_with_pydantic(tmp_path / "nonexistent.yaml")
        assert result["valid"] is False
        assert "File not found" in result["errors"][0]["message"]

    def test_missing_required_field(self, tmp_path: Path):
        """Missing required 'title' field should fail validation."""
        yaml_file = tmp_path / "no_title.yaml"
        yaml_file.write_text("components: []", encoding="utf-8")
        result = validate_yaml_with_pydantic(yaml_file)
        assert result["valid"] is False


# ============================================================================
# Test CLI validate command
# ============================================================================


class TestCLIValidateCommand:
    """Tests for the 'depictio dashboard validate' CLI command."""

    def test_validate_valid_file(self, valid_yaml_file: Path):
        """Valid YAML file should pass validation."""
        result = runner.invoke(app, ["validate", str(valid_yaml_file)])
        assert result.exit_code == 0
        assert "Validation passed" in result.output

    def test_validate_invalid_file(self, invalid_yaml_file: Path):
        """Invalid YAML file should fail validation."""
        result = runner.invoke(app, ["validate", str(invalid_yaml_file)])
        assert result.exit_code == 1
        assert "Validation failed" in result.output

    def test_validate_nonexistent_file(self):
        """Non-existent file should fail with error."""
        result = runner.invoke(app, ["validate", "/nonexistent/path/dashboard.yaml"])
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_validate_verbose(self, valid_yaml_file: Path):
        """Verbose flag should work without errors."""
        result = runner.invoke(app, ["validate", str(valid_yaml_file), "--verbose"])
        assert result.exit_code == 0


# ============================================================================
# Test CLI convert command (JSON → YAML)
# ============================================================================


class TestCLIConvertCommand:
    """Tests for the 'depictio dashboard convert' CLI command."""

    def test_convert_json_to_yaml(self, full_json_file: Path, tmp_path: Path):
        """Convert JSON to YAML should succeed."""
        output_file = tmp_path / "output.yaml"
        result = runner.invoke(app, ["convert", str(full_json_file), "-o", str(output_file)])
        assert result.exit_code == 0
        assert "Converted to minimal YAML format" in result.output
        assert output_file.exists()

        # Verify output is valid YAML
        content = output_file.read_text()
        assert "title:" in content
        assert "components:" in content

    def test_convert_default_output(self, full_json_file: Path):
        """Convert without -o should create .yaml with same name."""
        result = runner.invoke(app, ["convert", str(full_json_file)])
        assert result.exit_code == 0

        # Check that .yaml file was created
        expected_output = full_json_file.with_suffix(".yaml")
        assert expected_output.exists()

        # Cleanup
        expected_output.unlink()

    def test_convert_nonexistent_file(self):
        """Non-existent JSON file should fail."""
        result = runner.invoke(app, ["convert", "/nonexistent/dashboard.json"])
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_convert_invalid_json(self, tmp_path: Path):
        """Invalid JSON should fail."""
        invalid_json = tmp_path / "invalid.json"
        invalid_json.write_text("{ invalid json }", encoding="utf-8")

        result = runner.invoke(app, ["convert", str(invalid_json)])
        assert result.exit_code == 1
        assert "Invalid JSON" in result.output


# ============================================================================
# Test CLI from-yaml command (YAML → JSON)
# ============================================================================


class TestCLIFromYamlCommand:
    """Tests for the 'depictio dashboard from-yaml' CLI command."""

    def test_from_yaml_to_json(self, valid_yaml_file: Path, tmp_path: Path):
        """Convert YAML to JSON should succeed."""
        output_file = tmp_path / "output.json"
        result = runner.invoke(app, ["from-yaml", str(valid_yaml_file), "-o", str(output_file)])
        assert result.exit_code == 0
        assert "Converted to full dashboard JSON" in result.output
        assert output_file.exists()

        # Verify output is valid JSON
        with output_file.open() as f:
            data = json.load(f)
        assert "title" in data
        assert "stored_metadata" in data
        assert len(data["stored_metadata"]) == 4

    def test_from_yaml_default_output(self, valid_yaml_file: Path):
        """from-yaml without -o should create .json with same name."""
        result = runner.invoke(app, ["from-yaml", str(valid_yaml_file)])
        assert result.exit_code == 0

        # Check that .json file was created
        expected_output = valid_yaml_file.with_suffix(".json")
        assert expected_output.exists()

        # Cleanup
        expected_output.unlink()

    def test_from_yaml_nonexistent_file(self):
        """Non-existent YAML file should fail."""
        result = runner.invoke(app, ["from-yaml", "/nonexistent/dashboard.yaml"])
        assert result.exit_code == 1
        assert "File not found" in result.output


# ============================================================================
# Test CLI schema command
# ============================================================================


class TestCLISchemaCommand:
    """Tests for the 'depictio dashboard schema' CLI command."""

    def test_schema_output(self, tmp_path: Path):
        """Schema command should output JSON schema.

        Note: We use file output to avoid Rich console escape codes in stdout.
        """
        output_file = tmp_path / "schema_output.json"
        result = runner.invoke(app, ["schema", "-o", str(output_file)])
        assert result.exit_code == 0
        assert output_file.exists()

        # Verify it's valid JSON with expected structure
        with output_file.open() as f:
            schema = json.load(f)
        assert "properties" in schema
        assert "title" in schema["properties"]

    def test_schema_to_file(self, tmp_path: Path):
        """Schema command should write to file when -o specified."""
        output_file = tmp_path / "schema.json"
        result = runner.invoke(app, ["schema", "-o", str(output_file)])
        assert result.exit_code == 0
        assert output_file.exists()
        assert "Schema written to" in result.output

        # Verify content
        with output_file.open() as f:
            schema = json.load(f)
        assert "properties" in schema


# ============================================================================
# Test Full Conversion Pipeline: YAML → DashboardDataLite → DashboardData
# ============================================================================


class TestFullConversionPipeline:
    """Tests for the complete YAML → DashboardDataLite → DashboardData pipeline."""

    def test_yaml_to_lite(self, valid_yaml_content: str):
        """YAML should convert to DashboardDataLite successfully."""
        lite = DashboardDataLite.from_yaml(valid_yaml_content)

        assert lite.title == "Test Dashboard"
        assert lite.subtitle == "Testing the conversion pipeline"
        assert len(lite.components) == 4

    def test_lite_to_full_dict(self, valid_yaml_content: str):
        """DashboardDataLite should convert to full dict."""
        lite = DashboardDataLite.from_yaml(valid_yaml_content)
        full_dict = lite.to_full()

        assert full_dict["title"] == "Test Dashboard"
        assert "stored_metadata" in full_dict
        assert len(full_dict["stored_metadata"]) == 4
        assert "stored_layout_data" in full_dict
        assert len(full_dict["stored_layout_data"]) == 4

    def test_full_dict_to_dashboard_data(
        self, valid_yaml_content: str, sample_permission: Permission, sample_project_id: str
    ):
        """Full dict should convert to DashboardData with required fields."""
        lite = DashboardDataLite.from_yaml(valid_yaml_content)
        full_dict = lite.to_full()

        # Add required fields for DashboardData
        full_dict["project_id"] = sample_project_id
        full_dict["permissions"] = sample_permission.model_dump()
        full_dict["dashboard_id"] = str(ObjectId())

        dashboard = DashboardData.model_validate(full_dict)

        assert dashboard.title == "Test Dashboard"
        assert len(dashboard.stored_metadata) == 4
        assert dashboard.project_id is not None

    def test_yaml_to_dashboard_data_direct(
        self, valid_yaml_content: str, sample_permission: Permission, sample_project_id: str
    ):
        """YAML should convert directly to DashboardData via from_yaml()."""
        dashboard = DashboardData.from_yaml(
            valid_yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )

        assert isinstance(dashboard, DashboardData)
        assert dashboard.title == "Test Dashboard"
        assert len(dashboard.stored_metadata) == 4

    def test_yaml_to_dashboard_data_missing_project_id(
        self, valid_yaml_content: str, sample_permission: Permission
    ):
        """DashboardData.from_yaml() should raise ValueError without project_id."""
        with pytest.raises(ValueError, match="project_id is required"):
            DashboardData.from_yaml(valid_yaml_content, permissions=sample_permission.model_dump())

    def test_yaml_to_dashboard_data_uses_default_permissions(
        self, valid_yaml_content: str, sample_project_id: str
    ):
        """DashboardData.from_yaml() uses default permissions when not provided."""
        # to_full() provides default permissions, so this should work
        dashboard = DashboardData.from_yaml(valid_yaml_content, project_id=sample_project_id)
        # Verify default permissions are used
        assert dashboard.permissions.owners == []
        assert dashboard.permissions.editors == []
        assert dashboard.permissions.viewers == []

    def test_roundtrip_yaml_lite_yaml(self, valid_yaml_content: str):
        """YAML → Lite → YAML should preserve essential data."""
        lite = DashboardDataLite.from_yaml(valid_yaml_content)
        yaml_output = lite.to_yaml()
        lite2 = DashboardDataLite.from_yaml(yaml_output)

        assert lite2.title == lite.title
        assert len(lite2.components) == len(lite.components)

    def test_roundtrip_full_pipeline(
        self, valid_yaml_content: str, sample_permission: Permission, sample_project_id: str
    ):
        """Full roundtrip: YAML → Lite → Full → DashboardData → Lite → YAML."""
        # YAML → Lite
        lite = DashboardDataLite.from_yaml(valid_yaml_content)

        # Lite → Full dict
        full_dict = lite.to_full()
        full_dict["project_id"] = sample_project_id
        full_dict["permissions"] = sample_permission.model_dump()
        full_dict["dashboard_id"] = str(ObjectId())

        # Full dict → DashboardData
        dashboard = DashboardData.model_validate(full_dict)

        # DashboardData → Lite (via to_lite())
        lite2 = dashboard.to_lite()

        # Lite → YAML
        yaml_output = lite2.to_yaml()

        # Verify the output is still valid
        lite3 = DashboardDataLite.from_yaml(yaml_output)
        assert lite3.title == "Test Dashboard"
        assert len(lite3.components) == 4

    def test_component_types_preserved(
        self, valid_yaml_content: str, sample_permission: Permission, sample_project_id: str
    ):
        """Component types should be preserved through the pipeline."""
        dashboard = DashboardData.from_yaml(
            valid_yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )

        component_types = [comp.get("component_type") for comp in dashboard.stored_metadata]
        assert "figure" in component_types
        assert "card" in component_types
        assert "interactive" in component_types
        assert "table" in component_types

    def test_figure_dict_kwargs_preserved(
        self, valid_yaml_content: str, sample_permission: Permission, sample_project_id: str
    ):
        """Figure dict_kwargs should be preserved through the pipeline."""
        dashboard = DashboardData.from_yaml(
            valid_yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )

        figure = next(
            comp for comp in dashboard.stored_metadata if comp.get("component_type") == "figure"
        )
        assert figure["dict_kwargs"]["x"] == "sepal.length"
        assert figure["dict_kwargs"]["y"] == "sepal.width"
        assert figure["dict_kwargs"]["color"] == "variety"

    def test_card_aggregation_preserved(
        self, valid_yaml_content: str, sample_permission: Permission, sample_project_id: str
    ):
        """Card aggregation settings should be preserved through the pipeline."""
        dashboard = DashboardData.from_yaml(
            valid_yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )

        card = next(
            comp for comp in dashboard.stored_metadata if comp.get("component_type") == "card"
        )
        assert card["aggregation"] == "average"
        assert card["column_name"] == "sepal.length"
        assert card["column_type"] == "float64"


# ============================================================================
# Test Edge Cases and Error Handling
# ============================================================================


# ============================================================================
# Test CLI import command (dry-run mode only - no API required)
# ============================================================================


class TestCLIImportCommand:
    """Tests for the 'depictio dashboard import' CLI command (dry-run mode)."""

    def test_import_dry_run(self, valid_yaml_file: Path):
        """Import with --dry-run should validate but not upload."""
        result = runner.invoke(
            app,
            [
                "import",
                str(valid_yaml_file),
                "--project",
                "646b0f3c1e4a2d7f8e5b8c9a",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Validation passed" in result.output
        assert "Dry run mode" in result.output

    def test_import_nonexistent_file(self):
        """Import with non-existent file should fail."""
        result = runner.invoke(
            app,
            [
                "import",
                "/nonexistent/dashboard.yaml",
                "--project",
                "646b0f3c1e4a2d7f8e5b8c9a",
                "--dry-run",
            ],
        )
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_import_invalid_yaml(self, invalid_yaml_file: Path):
        """Import with invalid YAML should fail validation."""
        result = runner.invoke(
            app,
            [
                "import",
                str(invalid_yaml_file),
                "--project",
                "646b0f3c1e4a2d7f8e5b8c9a",
                "--dry-run",
            ],
        )
        assert result.exit_code == 1
        assert "Validation failed" in result.output

    def test_import_shows_component_count(self, valid_yaml_file: Path):
        """Import should show component count during validation."""
        result = runner.invoke(
            app,
            [
                "import",
                str(valid_yaml_file),
                "--project",
                "646b0f3c1e4a2d7f8e5b8c9a",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Components:" in result.output


# ============================================================================
# Test Edge Cases and Error Handling
# ============================================================================


class TestEdgeCasesAndErrors:
    """Tests for edge cases and error handling."""

    def test_empty_components(self, sample_permission: Permission, sample_project_id: str):
        """Dashboard with empty components list should work."""
        yaml_content = """
title: Empty Dashboard
components: []
"""
        dashboard = DashboardData.from_yaml(
            yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )
        assert dashboard.title == "Empty Dashboard"
        assert len(dashboard.stored_metadata) == 0

    def test_minimal_figure_component(self, sample_permission: Permission, sample_project_id: str):
        """Minimal figure component (just tag and component_type) should work."""
        yaml_content = """
title: Minimal Test
components:
  - tag: fig-1
    component_type: figure
"""
        dashboard = DashboardData.from_yaml(
            yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )
        assert len(dashboard.stored_metadata) == 1
        assert dashboard.stored_metadata[0]["component_type"] == "figure"
        assert dashboard.stored_metadata[0]["visu_type"] == "scatter"  # default

    def test_all_component_types(self, sample_permission: Permission, sample_project_id: str):
        """All four component types should be supported."""
        yaml_content = """
title: All Types
components:
  - tag: fig-1
    component_type: figure
  - tag: card-1
    component_type: card
    aggregation: count
    column_name: id
  - tag: filter-1
    component_type: interactive
    interactive_component_type: MultiSelect
    column_name: category
  - tag: table-1
    component_type: table
"""
        dashboard = DashboardData.from_yaml(
            yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )
        assert len(dashboard.stored_metadata) == 4

    def test_special_characters_in_title(
        self, sample_permission: Permission, sample_project_id: str
    ):
        """Special characters in title should be preserved."""
        yaml_content = """
title: "Dashboard with 'quotes' & <special> chars"
components: []
"""
        dashboard = DashboardData.from_yaml(
            yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )
        assert "quotes" in dashboard.title
        assert "&" in dashboard.title

    def test_unicode_in_content(self, sample_permission: Permission, sample_project_id: str):
        """Unicode characters should be preserved."""
        yaml_content = """
title: "测试 Dashboard 日本語"
components: []
"""
        dashboard = DashboardData.from_yaml(
            yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )
        assert "测试" in dashboard.title
        assert "日本語" in dashboard.title

    def test_layout_auto_generation(
        self, valid_yaml_content: str, sample_permission: Permission, sample_project_id: str
    ):
        """Layout should be auto-generated for all components."""
        dashboard = DashboardData.from_yaml(
            valid_yaml_content,
            project_id=sample_project_id,
            permissions=sample_permission.model_dump(),
        )

        # stored_layout_data should have one entry per component
        assert len(dashboard.stored_layout_data) == len(dashboard.stored_metadata)

        # Each layout item should have position/size properties
        for layout in dashboard.stored_layout_data:
            assert "i" in layout
            assert "x" in layout
            assert "y" in layout
            assert "w" in layout
            assert "h" in layout
