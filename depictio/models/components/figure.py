"""
Figure Component Model.

Represents a Plotly-based visualization component.
Inherits from FigureLiteComponent and adds runtime fields.
"""

import uuid
from typing import Any

from pydantic import Field, model_validator

from depictio.models.components.lite import FigureLiteComponent
from depictio.models.components.types import ChartType, FigureMode


class FigureComponent(FigureLiteComponent):
    """A figure/chart component for data visualization.

    Extends FigureLiteComponent with runtime fields for rendering.

    Example YAML:
        - index: scatter-1
          component_type: figure
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          visu_type: scatter
          dict_kwargs:
            x: sepal.length
            y: sepal.width
            color: variety
    """

    # Override to auto-generate UUID
    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Override to be optional (resolved at runtime)
    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    # Override visu_type with type alias
    visu_type: ChartType | str = "scatter"

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

    # Figure mode
    mode: FigureMode | str = Field(
        default="ui",
        description="'ui' for visual configuration, 'code' for custom Python",
    )

    # Code mode content (when mode='code')
    code_content: str | None = Field(
        default=None,
        description="Custom Python code for figure generation (code mode only)",
    )

    # Timestamp for caching/updates
    last_updated: str | None = Field(default=None, description="Last update timestamp")

    # Rendering state (populated at render time)
    displayed_data_count: int = Field(default=0, description="Number of data points displayed")
    total_data_count: int = Field(default=0, description="Total data points available")
    was_sampled: bool = Field(default=False, description="Whether data was sampled")
    full_data_loaded: bool = Field(default=False, description="Whether full data was loaded")
    filter_applied: bool = Field(default=False, description="Whether filter was applied")

    # Advanced configuration
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Plotly figure config options",
    )

    @model_validator(mode="after")
    def validate_dict_kwargs_params(self) -> "FigureComponent":
        """Validate dict_kwargs against Plotly Express signature."""
        if self.mode == "code":
            return self

        if not self.dict_kwargs:
            return self

        from depictio.models.validation.plotly_express import validate_dict_kwargs

        is_valid, errors = validate_dict_kwargs(self.visu_type, self.dict_kwargs)
        if not is_valid:
            import logging

            logger = logging.getLogger(__name__)
            for error in errors:
                logger.warning(f"Plotly dict_kwargs validation warning: {error['msg']}")

        return self

    def get_validated_dict_kwargs(self) -> tuple[bool, list[dict[str, Any]]]:
        """Get validation result for dict_kwargs."""
        from depictio.models.validation.plotly_express import validate_dict_kwargs

        return validate_dict_kwargs(self.visu_type, self.dict_kwargs)
