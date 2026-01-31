"""
Interactive Component Model.

Represents interactive filter components (selects, sliders, date pickers, etc.).
Inherits from InteractiveLiteComponent and adds runtime fields.
"""

import uuid
from typing import Any

from pydantic import Field, model_validator

from depictio.models.components.lite import InteractiveLiteComponent
from depictio.models.components.types import ColumnType, InteractiveType


class InteractiveComponent(InteractiveLiteComponent):
    """An interactive filter component for dashboard filtering.

    Extends InteractiveLiteComponent with runtime fields for rendering.

    Example YAML:
        - index: filter-1
          component_type: interactive
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          interactive_component_type: MultiSelect
          column_name: variety
          column_type: object
    """

    # Override to auto-generate UUID
    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Override to be optional (resolved at runtime)
    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    # Override with type alias
    interactive_component_type: InteractiveType | str
    column_type: ColumnType | str = "object"

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

    # State management
    default_state: dict[str, Any] | None = Field(
        default=None,
        description="Default state for the component (min/max, selected values, etc.)",
    )
    value: Any = Field(
        default=None,
        description="Current value of the interactive component",
    )

    # Range slider specific
    scale: str = Field(default="linear", description="Scale type (linear, log)")
    marks_number: int = Field(default=5, description="Number of marks to show on slider")

    # Select specific
    searchable: bool = Field(default=True, description="Enable search in select components")
    clearable: bool = Field(default=True, description="Allow clearing selection")

    @model_validator(mode="after")
    def validate_component_compatibility(self) -> "InteractiveComponent":
        """Validate component type and column type compatibility."""
        from depictio.models.validation.dash_mantine import validate_interactive_component

        config = {
            "use_log_scale": self.scale == "log",
            "marks_count": self.marks_number,
            "searchable": self.searchable,
        }

        is_valid, errors, warnings = validate_interactive_component(
            self.interactive_component_type,
            self.column_type,
            config=config,
        )

        if not is_valid or warnings:
            import logging

            logger = logging.getLogger(__name__)
            for error in errors:
                logger.warning(f"Interactive component validation: {error['msg']}")
            for warning in warnings:
                logger.warning(f"Interactive component: {warning}")

        return self

    def get_validation_result(self) -> tuple[bool, list[dict[str, Any]], list[str]]:
        """Get explicit validation result."""
        from depictio.models.validation.dash_mantine import validate_interactive_component

        config = {
            "use_log_scale": self.scale == "log",
            "marks_count": self.marks_number,
            "searchable": self.searchable,
        }

        return validate_interactive_component(
            self.interactive_component_type,
            self.column_type,
            config=config,
        )
