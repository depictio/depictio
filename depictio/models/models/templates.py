"""
Models for the project template system.

Templates allow users to reuse predefined project configurations (e.g., nf-core/ampliseq)
with their own data by providing a data root directory. The template system resolves
path variables like {DATA_ROOT} throughout the project config at runtime.

Key concepts:
- TemplateMetadata: Declared in template project.yaml, describes the template identity
- TemplateOrigin: Stored on Project model to track that a template was used
- TemplateVariable: A required variable (e.g., DATA_ROOT) with description
- TemplateConditional: Optional-variable rules for DC removal and dashboard selection
"""

from datetime import datetime
from typing import Any

from bson import ObjectId
from pydantic import BaseModel, Field, field_validator


def _require_nonempty(v: str, label: str) -> str:
    """Strip and validate that a string field is non-empty."""
    if not v or not v.strip():
        raise ValueError(f"{label} cannot be empty")
    return v.strip()


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


class TemplateConditional(BaseModel):
    """A conditional rule applied during template resolution based on variable presence.

    Rules fire when the named optional variable is absent or present. Matching rules
    remove listed DCs (and links that reference them) and override the dashboard list.

    Example YAML:
        conditional:
          - if_var_absent: "METADATA_FILE"
            remove_dc_tags: ["metadata", "ancombc_results"]
            dashboards: ["dashboards/base.yaml"]
          - if_var_present: "METADATA_FILE"
            dashboards: ["dashboards/base.yaml", "dashboards/extended.yaml"]
    """

    if_var_absent: str | None = Field(
        default=None,
        description="Variable name: rule fires when this variable is NOT provided",
    )
    if_var_present: str | None = Field(
        default=None,
        description="Variable name: rule fires when this variable IS provided",
    )
    remove_dc_tags: list[str] = Field(
        default_factory=list,
        description="DC tags to remove from all workflows when this rule fires",
    )
    dashboards: list[str] = Field(
        default_factory=list,
        description="Dashboard paths to use when this rule fires (overrides template default)",
    )


class TemplateMetadata(BaseModel):
    """Metadata section declared in a template project.yaml.

    This section is parsed from the top-level 'template' key in the YAML file.
    It describes the template identity and required variables.

    Example YAML:
        template:
          template_id: "nf-core/ampliseq/2.16.0"
          description: "nf-core/ampliseq microbial community analysis template"
          version: "1.0.0"
          variables:
            - name: "DATA_ROOT"
              description: "Root directory containing ampliseq output data"
              required: true
            - name: "METADATA_FILE"
              description: "Path to metadata TSV (optional)"
              required: false
          dashboards:
            - "dashboards/base.yaml"
          conditional:
            - if_var_absent: "METADATA_FILE"
              remove_dc_tags: ["metadata", "ancombc_results"]
              dashboards: ["dashboards/base.yaml"]
            - if_var_present: "METADATA_FILE"
              dashboards: ["dashboards/base.yaml", "dashboards/extended.yaml"]
    """

    template_id: str = Field(
        ..., description="Unique template identifier (e.g., 'nf-core/ampliseq/2.16.0')"
    )
    description: str = Field(..., description="Human-readable description of this template")
    version: str = Field(..., description="Template schema version (semver)")
    variables: list[TemplateVariable] = Field(
        default_factory=list, description="Variables required by this template"
    )
    dashboards: list[str] = Field(
        default_factory=list,
        description=(
            "Relative paths to dashboard YAML files bundled with this template "
            "(e.g., 'dashboards/base.yaml'). Imported automatically after "
            "project setup unless overridden via --dashboard CLI flag."
        ),
    )
    conditional: list[TemplateConditional] = Field(
        default_factory=list,
        description=(
            "Conditional rules applied during resolution based on optional variable presence. "
            "Each rule fires when its if_var_absent / if_var_present condition matches."
        ),
    )

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        return _require_nonempty(v, "Template ID")

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        return _require_nonempty(v, "Template version")

    def get_required_variable_names(self) -> list[str]:
        """Return names of all required variables."""
        return [var.name for var in self.variables if var.required]


class TemplateOrigin(BaseModel):
    """Stored on Project model to track that a template was used to create the project.

    This enables the DB and UI to distinguish template-instantiated projects from
    manually configured ones, and to show which template was used.
    """

    template_id: str = Field(
        ..., description="Template identifier (e.g., 'nf-core/ampliseq/2.16.0')"
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

    @field_validator("config_snapshot", mode="before")
    @classmethod
    def sanitize_objectids(cls, v: Any) -> Any:
        """Recursively convert bson ObjectId values to strings for JSON serialization."""

        def _convert(obj: Any) -> Any:
            if isinstance(obj, ObjectId):
                return str(obj)
            if isinstance(obj, dict):
                return {k: _convert(val) for k, val in obj.items()}
            if isinstance(obj, list):
                return [_convert(item) for item in obj]
            return obj

        return _convert(v)

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        return _require_nonempty(v, "Template ID")

    @field_validator("data_root")
    @classmethod
    def validate_data_root(cls, v: str) -> str:
        return _require_nonempty(v, "Data root")
