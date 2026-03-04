"""
Models for the project template system.

Templates allow users to reuse predefined project configurations (e.g., nf-core/ampliseq)
with their own data by providing a data root directory. The template system resolves
path variables like {DATA_ROOT} and validates that user data matches the expected structure.

Key concepts:
- TemplateMetadata: Declared in template project.yaml, describes variables and expected structure
- TemplateOrigin: Stored on Project model to track that a template was used
- TemplateVariable: A required variable (e.g., DATA_ROOT) with description
- ExpectedFile/ExpectedDirectory: Used by the validator to check user data placement
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TemplateVariable(BaseModel):
    """A variable required by a template (e.g., DATA_ROOT).

    Variables are declared in the template metadata section and must be provided
    by the user at template instantiation time (e.g., via --data-root CLI flag).
    """

    name: str = Field(..., description="Variable name (e.g., 'DATA_ROOT')")
    description: str = Field(..., description="Human-readable description of this variable")
    required: bool = Field(default=True, description="Whether this variable must be provided")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure variable name is non-empty and uppercase with underscores."""
        if not v or not v.strip():
            raise ValueError("Variable name cannot be empty")
        v = v.strip()
        if not all(c.isalnum() or c == "_" for c in v):
            raise ValueError(
                "Variable name must contain only alphanumeric characters and underscores"
            )
        return v


class ExpectedFile(BaseModel):
    """A file expected at a relative path under DATA_ROOT.

    Used by the template validator to verify that user data is correctly placed.
    The relative_path is relative to DATA_ROOT (e.g., 'merged_metadata.tsv').
    """

    relative_path: str = Field(
        ..., description="Path relative to DATA_ROOT (e.g., 'merged_metadata.tsv')"
    )
    description: str = Field(..., description="Human-readable description of this file")
    format: str | None = Field(
        default=None, description="Expected file format (e.g., 'TSV', 'parquet')"
    )
    columns: list[str] = Field(
        default_factory=list, description="Expected column names (for deep validation)"
    )

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, v: str) -> str:
        """Ensure relative path is non-empty and not absolute."""
        if not v or not v.strip():
            raise ValueError("Relative path cannot be empty")
        v = v.strip()
        if v.startswith("/"):
            raise ValueError("Expected file path must be relative, not absolute")
        return v


class ExpectedDirectory(BaseModel):
    """A directory expected under DATA_ROOT.

    Supports glob patterns for directories with variable names (e.g., 'run_*').
    """

    relative_path: str = Field(
        ..., description="Path relative to DATA_ROOT (e.g., 'run_*/multiqc_data')"
    )
    description: str = Field(..., description="Human-readable description of this directory")
    glob_pattern: bool = Field(
        default=False, description="Whether relative_path contains wildcards (*, ?, **)"
    )

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, v: str) -> str:
        """Ensure relative path is non-empty and not absolute."""
        if not v or not v.strip():
            raise ValueError("Relative path cannot be empty")
        v = v.strip()
        if v.startswith("/"):
            raise ValueError("Expected directory path must be relative, not absolute")
        return v


class TemplateMetadata(BaseModel):
    """Metadata section declared in a template project.yaml.

    This section is parsed from the top-level 'template' key in the YAML file.
    It describes the template identity, required variables, and expected data structure.

    Example YAML:
        template:
          template_id: "nf-core/ampliseq/2.14.0"
          description: "nf-core/ampliseq microbial community analysis template"
          version: "1.0.0"
          variables:
            - name: "DATA_ROOT"
              description: "Root directory containing ampliseq output data"
          expected_files:
            - relative_path: "merged_metadata.tsv"
              description: "Sample metadata file"
              format: "TSV"
              columns: ["sample", "name", "habitat"]
    """

    template_id: str = Field(
        ..., description="Unique template identifier (e.g., 'nf-core/ampliseq/2.14.0')"
    )
    description: str = Field(..., description="Human-readable description of this template")
    version: str = Field(..., description="Template schema version (semver)")
    variables: list[TemplateVariable] = Field(
        default_factory=list, description="Variables required by this template"
    )
    expected_files: list[ExpectedFile] = Field(
        default_factory=list, description="Files expected under DATA_ROOT"
    )
    expected_directories: list[ExpectedDirectory] = Field(
        default_factory=list, description="Directories expected under DATA_ROOT"
    )

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        """Ensure template_id is non-empty."""
        if not v or not v.strip():
            raise ValueError("Template ID cannot be empty")
        return v.strip()

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Ensure version is non-empty."""
        if not v or not v.strip():
            raise ValueError("Template version cannot be empty")
        return v.strip()

    def get_required_variable_names(self) -> list[str]:
        """Return names of all required variables."""
        return [var.name for var in self.variables if var.required]


class TemplateOrigin(BaseModel):
    """Stored on Project model to track that a template was used to create the project.

    This enables the DB and UI to distinguish template-instantiated projects from
    manually configured ones, and to show which template was used.
    """

    template_id: str = Field(
        ..., description="Template identifier (e.g., 'nf-core/ampliseq/2.14.0')"
    )
    template_version: str = Field(..., description="Template schema version at time of use")
    data_root: str = Field(..., description="The actual --data-root value provided by the user")
    applied_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        description="Timestamp when template was applied",
    )
    config_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Frozen copy of the resolved template config (for reproducibility)",
    )

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        """Ensure template_id is non-empty."""
        if not v or not v.strip():
            raise ValueError("Template ID cannot be empty")
        return v.strip()

    @field_validator("data_root")
    @classmethod
    def validate_data_root(cls, v: str) -> str:
        """Ensure data_root is non-empty."""
        if not v or not v.strip():
            raise ValueError("Data root cannot be empty")
        return v.strip()
