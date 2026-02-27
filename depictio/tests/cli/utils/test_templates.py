"""
Minimal tests for the project template system.

Tests cover the core template functions:
- Template location
- Variable substitution
- Template resolution
- Data root validation
"""

import tempfile
from pathlib import Path

import pytest

from depictio.cli.cli.utils.template_validator import validate_data_root
from depictio.cli.cli.utils.templates import (
    _strip_ids,
    locate_template,
    substitute_template_variables,
)
from depictio.models.models.templates import (
    ExpectedDirectory,
    ExpectedFile,
    TemplateMetadata,
    TemplateOrigin,
    TemplateVariable,
)


class TestLocateTemplate:
    """Tests for template file location."""

    def test_locate_known_template(self) -> None:
        """Locate the nf-core/ampliseq template that exists in the repo."""
        path = locate_template("nf-core/ampliseq/2.14.0")
        assert path.is_file()
        assert path.name == "project.yaml"

    def test_locate_unknown_template_raises(self) -> None:
        """Unknown template ID raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not found"):
            locate_template("nonexistent/template/1.0.0")


class TestSubstituteTemplateVariables:
    """Tests for recursive variable substitution."""

    def test_substitute_string(self) -> None:
        """Simple string substitution."""
        result = substitute_template_variables("{DATA_ROOT}/file.tsv", {"DATA_ROOT": "/my/data"})
        assert result == "/my/data/file.tsv"

    def test_substitute_nested_dict(self) -> None:
        """Substitution in nested dict structures."""
        config = {
            "locations": ["{DATA_ROOT}"],
            "scan": {
                "filename": "{DATA_ROOT}/metadata.tsv",
            },
        }
        result = substitute_template_variables(config, {"DATA_ROOT": "/data"})
        assert result["locations"] == ["/data"]
        assert result["scan"]["filename"] == "/data/metadata.tsv"

    def test_substitute_list(self) -> None:
        """Substitution in list elements."""
        result = substitute_template_variables(
            ["{DATA_ROOT}/a.tsv", "{DATA_ROOT}/b.tsv"],
            {"DATA_ROOT": "/root"},
        )
        assert result == ["/root/a.tsv", "/root/b.tsv"]

    def test_no_substitution_for_non_matching(self) -> None:
        """Strings without placeholders are unchanged."""
        result = substitute_template_variables("no_vars_here", {"DATA_ROOT": "/data"})
        assert result == "no_vars_here"

    def test_substitute_preserves_non_string_types(self) -> None:
        """Non-string values (int, bool, None) pass through unchanged."""
        config = {"count": 42, "enabled": True, "value": None}
        result = substitute_template_variables(config, {"DATA_ROOT": "/data"})
        assert result == config


class TestStripIds:
    """Tests for ID stripping from template configs."""

    def test_strip_top_level_id(self) -> None:
        """Top-level id field is removed."""
        config = {"id": "abc123", "name": "test"}
        result = _strip_ids(config)
        assert "id" not in result
        assert result["name"] == "test"

    def test_strip_nested_ids(self) -> None:
        """IDs in nested structures are removed."""
        config = {
            "workflows": [
                {
                    "id": "wf1",
                    "name": "ampliseq",
                    "data_collections": [
                        {"id": "dc1", "data_collection_tag": "metadata"},
                    ],
                }
            ]
        }
        result = _strip_ids(config)
        assert "id" not in result["workflows"][0]
        assert "id" not in result["workflows"][0]["data_collections"][0]
        assert result["workflows"][0]["name"] == "ampliseq"


class TestTemplateMetadataModel:
    """Tests for TemplateMetadata Pydantic model."""

    def test_valid_metadata(self) -> None:
        """Valid metadata parses successfully."""
        metadata = TemplateMetadata(
            template_id="nf-core/ampliseq/2.14.0",
            description="Test template",
            version="1.0.0",
            variables=[
                TemplateVariable(name="DATA_ROOT", description="Data root dir"),
            ],
        )
        assert metadata.template_id == "nf-core/ampliseq/2.14.0"
        assert len(metadata.variables) == 1

    def test_get_required_variable_names(self) -> None:
        """Required variable names are returned correctly."""
        metadata = TemplateMetadata(
            template_id="test",
            description="Test",
            version="1.0.0",
            variables=[
                TemplateVariable(name="DATA_ROOT", description="Root", required=True),
                TemplateVariable(name="OPTIONAL_VAR", description="Optional", required=False),
            ],
        )
        assert metadata.get_required_variable_names() == ["DATA_ROOT"]


class TestTemplateOriginModel:
    """Tests for TemplateOrigin Pydantic model."""

    def test_valid_origin(self) -> None:
        """Valid template origin creates successfully."""
        origin = TemplateOrigin(
            template_id="nf-core/ampliseq/2.14.0",
            template_version="1.0.0",
            data_root="/my/data",
            config_snapshot={"name": "test"},
        )
        assert origin.template_id == "nf-core/ampliseq/2.14.0"
        assert origin.data_root == "/my/data"
        assert origin.applied_at  # auto-generated timestamp


class TestValidateDataRoot:
    """Tests for data root validation."""

    def test_validate_existing_directory(self) -> None:
        """Valid directory with expected files passes validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create expected files
            (Path(tmpdir) / "metadata.tsv").write_text("sample\thabitat\nS1\tsoil")

            metadata = TemplateMetadata(
                template_id="test",
                description="Test",
                version="1.0.0",
                expected_files=[
                    ExpectedFile(
                        relative_path="metadata.tsv",
                        description="Metadata",
                        format="TSV",
                    ),
                ],
            )

            result = validate_data_root(metadata, tmpdir)
            assert result.valid
            assert len(result.errors) == 0

    def test_validate_missing_file(self) -> None:
        """Missing expected file produces an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = TemplateMetadata(
                template_id="test",
                description="Test",
                version="1.0.0",
                expected_files=[
                    ExpectedFile(
                        relative_path="nonexistent.tsv",
                        description="Missing file",
                    ),
                ],
            )

            result = validate_data_root(metadata, tmpdir)
            assert not result.valid
            assert any("nonexistent.tsv" in e for e in result.errors)

    def test_validate_nonexistent_directory(self) -> None:
        """Nonexistent data root produces an error."""
        metadata = TemplateMetadata(
            template_id="test",
            description="Test",
            version="1.0.0",
        )

        result = validate_data_root(metadata, "/nonexistent/path/12345")
        assert not result.valid
        assert any("does not exist" in e for e in result.errors)

    def test_validate_glob_directory_warning(self) -> None:
        """Missing glob-pattern directories produce warnings (not errors)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = TemplateMetadata(
                template_id="test",
                description="Test",
                version="1.0.0",
                expected_directories=[
                    ExpectedDirectory(
                        relative_path="run_*",
                        description="Run directories",
                        glob_pattern=True,
                    ),
                ],
            )

            result = validate_data_root(metadata, tmpdir)
            assert result.valid  # Glob patterns produce warnings, not errors
            assert len(result.warnings) > 0

    def test_deep_validation_checks_columns(self) -> None:
        """Deep validation checks column names in TSV files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a TSV with correct columns
            tsv_path = Path(tmpdir) / "data.tsv"
            tsv_path.write_text("sample\thabitat\nS1\tsoil")

            metadata = TemplateMetadata(
                template_id="test",
                description="Test",
                version="1.0.0",
                expected_files=[
                    ExpectedFile(
                        relative_path="data.tsv",
                        description="Data",
                        format="TSV",
                        columns=["sample", "habitat"],
                    ),
                ],
            )

            result = validate_data_root(metadata, tmpdir, deep=True)
            assert result.valid
            assert len(result.errors) == 0

    def test_deep_validation_missing_column(self) -> None:
        """Deep validation detects missing columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_path = Path(tmpdir) / "data.tsv"
            tsv_path.write_text("sample\tvalue\nS1\t42")

            metadata = TemplateMetadata(
                template_id="test",
                description="Test",
                version="1.0.0",
                expected_files=[
                    ExpectedFile(
                        relative_path="data.tsv",
                        description="Data",
                        format="TSV",
                        columns=["sample", "habitat", "missing_col"],
                    ),
                ],
            )

            result = validate_data_root(metadata, tmpdir, deep=True)
            assert not result.valid
            assert any("missing_col" in e for e in result.errors)
