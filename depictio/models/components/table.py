"""
Table Component Model.

Represents a data table component for displaying tabular data with AG Grid.
Inherits from TableLiteComponent and adds runtime fields.
"""

import uuid
from typing import Any

from pydantic import Field, field_validator

from depictio.models.components.lite import TableLiteComponent


class TableComponent(TableLiteComponent):
    """A data table component for displaying tabular data.

    Extends TableLiteComponent with runtime fields for rendering.

    Example YAML:
        - index: table-1
          component_type: table
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
    """

    # Override to auto-generate UUID
    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Override to be optional (resolved at runtime)
    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    # Runtime: resolved IDs
    wf_id: str | None = None
    dc_id: str | None = None
    project_id: str | None = None

    # Runtime: full data collection config
    dc_config: dict[str, Any] = Field(default_factory=dict)

    # Runtime: column metadata
    cols_json: dict[str, Any] = Field(default_factory=dict)

    # Runtime: parent reference
    parent_index: str | None = None

    # Panel placement (for dual-panel layouts)
    panel: str | None = Field(default=None, description="Panel placement ('left' or 'right')")

    # Styling
    striped: bool = Field(default=True, description="Alternate row colors")
    compact: bool = Field(default=False, description="Use compact row height")

    # Export options
    export_csv: bool = Field(default=False, description="Show CSV export button")

    @field_validator("cols_json", mode="before")
    @classmethod
    def validate_cols_json_schema(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate cols_json against AG Grid column configuration schema.

        This performs structural validation of column configurations to ensure
        they follow the expected AG Grid format with proper filter types.
        """
        if v is None or not v:
            return v

        from depictio.models.validation.ag_grid import validate_cols_json

        is_valid, errors, _ = validate_cols_json(v)
        if not is_valid:
            # Log warnings but don't fail - allows for backward compatibility
            # with existing dashboards that may have non-standard configs
            import logging

            logger = logging.getLogger(__name__)
            for error in errors:
                logger.warning(f"AG Grid cols_json validation warning: {error}")

        return v

    def get_validated_cols_json(self) -> dict[str, Any] | None:
        """Get cols_json with full validation.

        Unlike the field validator which only warns, this method performs
        strict validation and returns validated column configurations.

        Returns:
            Validated column configurations or None

        Raises:
            ValidationError: If cols_json is invalid
        """
        if not self.cols_json:
            return None

        from depictio.models.validation.ag_grid import validate_cols_json

        is_valid, errors, validated = validate_cols_json(self.cols_json, raise_on_error=True)
        if validated:
            return {name: config.model_dump() for name, config in validated.items()}
        return None

    def to_column_defs(self) -> list[dict[str, Any]]:
        """Convert cols_json to AG Grid columnDefs format.

        Returns:
            List of AG Grid column definition dictionaries
        """
        from depictio.models.validation.ag_grid import cols_json_to_column_defs

        if not self.cols_json:
            return [{"field": "ID", "maxWidth": 100}]

        return cols_json_to_column_defs(self.cols_json)
