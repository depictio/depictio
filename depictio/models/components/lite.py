"""
Lite Component Models.

Minimal component models for user-defined dashboards (YAML/Python).
Full component models inherit from these and add runtime fields.

Architecture:
    FigureLiteComponent (user-definable, YAML-friendly)
        ↓ inherits
    FigureComponent (adds runtime/rendering fields)

Index vs Tag:
    - `tag`: User-friendly identifier written in YAML (e.g., 'scatter-1', 'my-chart')
    - `index`: Internal UUID, auto-generated if not provided

    Users write `tag` in YAML, system manages `index` as UUID internally.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from depictio.models.components.constants import (
    AGGREGATION_COMPATIBILITY,
    COLUMN_TYPES,
    INTERACTIVE_COMPATIBILITY,
    VISU_TYPES,
)


class BaseLiteComponent(BaseModel):
    """Base class for lite dashboard components.

    Contains only the fields users need to define a component.
    Runtime fields (wf_id, dc_id, dc_config, etc.) are added by full components.

    Users should provide `tag` for identification. The `index` (UUID) is
    auto-generated if not provided.
    """

    model_config = ConfigDict(extra="allow")

    # Component identification
    tag: str | None = Field(
        default=None, description="User-friendly identifier (e.g., 'scatter-1')"
    )
    index: str | None = Field(
        default=None, description="Internal UUID (auto-generated if not provided)"
    )
    component_type: str = Field(..., description="Component type")

    # Display
    title: str = Field(default="", description="Component title")

    # Data source references (human-readable tags)
    workflow_tag: str = Field(default="", description="Workflow tag (e.g., 'python/iris_workflow')")
    data_collection_tag: str = Field(
        default="", description="Data collection tag (e.g., 'iris_table')"
    )

    @model_validator(mode="after")
    def ensure_index(self) -> "BaseLiteComponent":
        """Auto-generate index UUID if not provided."""
        if not self.index:
            self.index = str(uuid.uuid4())
        return self


class FigureLiteComponent(BaseLiteComponent):
    """Lite figure component for user definition.

    Example YAML:
        - tag: scatter-1
          component_type: figure
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          visu_type: scatter
          dict_kwargs:
            x: sepal.length
            y: sepal.width
            color: variety
          selection_enabled: true
          selection_column: sample_id
          customizations:
            preset: volcano
            preset_params:
              significance_threshold: 0.05
              fold_change_threshold: 1.0

        Or with inline customizations:
          customizations:
            reference_lines:
              - type: hline
                y: 0.05
                line_color: red
                line_dash: dash
                linked_slider: pvalue-slider
            highlights:
              - name: significant
                conditions:
                  - name: pvalue
                    column: pvalue
                    operator: lt
                    value: 0.05
                  - name: condition
                    column: condition
                    operator: eq
                    value: treated
                logic: and
                style:
                  marker_color: red
                  marker_size: 10
                  dim_opacity: 0.3
                link_type: dynamic
    """

    component_type: Literal["figure"] = "figure"

    # Visualization type
    visu_type: str = Field(
        default="scatter", description="Chart type (scatter, box, histogram, etc.)"
    )

    # Plotly Express parameters
    dict_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters passed to Plotly Express (x, y, color, etc.)",
    )

    # Code mode (alternative to dict_kwargs for custom transformations)
    mode: str = Field(default="ui", description="Rendering mode: 'ui' or 'code'")
    code_content: str | None = Field(default=None, description="Python code for code mode figures")

    # Selection filtering (enables scatter selection to filter other components)
    selection_enabled: bool = Field(default=False, description="Enable scatter selection filtering")
    selection_column: str | None = Field(
        default=None, description="Column to extract from selected points"
    )

    # Figure customizations (reference lines, highlights, axes, etc.)
    customizations: dict[str, Any] | None = Field(
        default=None,
        description="Figure customizations: reference lines, highlights, axes, presets, etc. "
        "Accepts a FigureCustomizations-compatible dict or preset shorthand.",
    )

    @model_validator(mode="after")
    def validate_figure_constraints(self) -> "FigureLiteComponent":
        """Validate figure-specific cross-field constraints."""
        if self.mode == "ui":
            if self.visu_type not in VISU_TYPES:
                valid = ", ".join(VISU_TYPES)
                raise ValueError(
                    f"Invalid visu_type '{self.visu_type}' for mode='ui'. Valid values: {valid}"
                )
        elif self.mode == "code":
            if not self.code_content or not self.code_content.strip():
                raise ValueError("code_content is required and must be non-empty when mode='code'")
        else:
            raise ValueError(f"Invalid mode '{self.mode}'. Valid values: 'ui', 'code'")

        if self.selection_enabled and not self.selection_column:
            raise ValueError("selection_column is required when selection_enabled=True")

        return self


class CardLiteComponent(BaseLiteComponent):
    """Lite card component for user definition.

    Example YAML:
        - tag: card-1
          component_type: card
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          aggregation: average
          column_name: sepal.length
          column_type: float64
    """

    component_type: Literal["card"] = "card"

    # Aggregation configuration
    aggregation: str = Field(..., description="Aggregation function (average, sum, count, etc.)")
    column_name: str = Field(..., description="Column to aggregate")
    column_type: str | None = Field(
        default=None,
        description="Data type of column (int64, float64, bool, datetime, timedelta, "
        "category, object). When provided, aggregation compatibility is validated.",
    )

    # Styling (optional)
    icon_name: str | None = Field(default=None, description="Iconify icon name")
    icon_color: str | None = Field(default=None, description="Icon color")
    title_color: str | None = Field(default=None, description="Title text color")
    title_font_size: str | None = Field(default=None, description="Title font size")
    value_font_size: str | None = Field(default=None, description="Value font size")

    @field_validator("column_type")
    @classmethod
    def validate_column_type(cls, v: str | None) -> str | None:
        if v is not None and v not in COLUMN_TYPES:
            valid = ", ".join(COLUMN_TYPES)
            raise ValueError(f"Invalid column_type '{v}'. Valid values: {valid}")
        return v

    @model_validator(mode="after")
    def validate_aggregation_for_column_type(self) -> "CardLiteComponent":
        """Validate aggregation × column_type compatibility when column_type is provided."""
        if self.column_type is None:
            return self
        valid_aggs = AGGREGATION_COMPATIBILITY.get(self.column_type, [])
        if valid_aggs and self.aggregation not in valid_aggs:
            valid = ", ".join(valid_aggs)
            raise ValueError(
                f"Invalid aggregation '{self.aggregation}' for column_type='{self.column_type}'. "
                f"Valid aggregations: {valid}"
            )
        return self


class InteractiveLiteComponent(BaseLiteComponent):
    """Lite interactive component for user definition.

    Example YAML:
        - tag: filter-1
          component_type: interactive
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          interactive_component_type: MultiSelect
          column_name: variety
          column_type: object
    """

    component_type: Literal["interactive"] = "interactive"

    # Filter configuration
    interactive_component_type: str = Field(
        ..., description="Filter type (RangeSlider, MultiSelect, etc.)"
    )
    column_name: str = Field(..., description="Column to filter on")
    column_type: str | None = Field(
        default=None,
        description="Data type of column (int64, float64, bool, datetime, timedelta, "
        "category, object). When provided, component type compatibility is validated.",
    )

    # Styling (optional)
    title_size: str | None = Field(default=None, description="Title size")
    custom_color: str | None = Field(default=None, description="Custom accent color")
    icon_name: str | None = Field(default=None, description="Iconify icon name")

    @field_validator("column_type")
    @classmethod
    def validate_column_type(cls, v: str | None) -> str | None:
        if v is not None and v not in COLUMN_TYPES:
            valid = ", ".join(COLUMN_TYPES)
            raise ValueError(f"Invalid column_type '{v}'. Valid values: {valid}")
        return v

    @model_validator(mode="after")
    def validate_interactive_type_for_column_type(self) -> "InteractiveLiteComponent":
        """Validate interactive_component_type × column_type when column_type is provided."""
        if self.column_type is None:
            return self
        valid_types = INTERACTIVE_COMPATIBILITY.get(self.column_type, [])
        if not valid_types:
            raise ValueError(
                f"No interactive components are supported for column_type='{self.column_type}'"
            )
        if self.interactive_component_type not in valid_types:
            valid = ", ".join(valid_types)
            raise ValueError(
                f"Invalid interactive_component_type '{self.interactive_component_type}' "
                f"for column_type='{self.column_type}'. "
                f"Valid types: {valid}"
            )
        return self


class TableLiteComponent(BaseLiteComponent):
    """Lite table component for user definition.

    Example YAML:
        - tag: table-1
          component_type: table
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          row_selection_enabled: true
          row_selection_column: sample_id
    """

    component_type: Literal["table"] = "table"

    # Table options (optional)
    columns: list[str] = Field(default_factory=list, description="Columns to display (empty = all)")
    page_size: int = Field(default=10, description="Rows per page")
    sortable: bool = Field(default=True, description="Enable column sorting")
    filterable: bool = Field(default=True, description="Enable column filtering")

    # Row selection filtering (enables table row selection to filter other components)
    row_selection_enabled: bool = Field(default=False, description="Enable row selection filtering")
    row_selection_column: str | None = Field(
        default=None, description="Column to extract from selected rows"
    )

    # Highlight filter for ref_line_slider-linked tables
    # When set, the table shows only rows matching these conditions (driven by slider values)
    highlight_filter: dict[str, Any] | None = Field(
        default=None,
        description="Filter conditions linked to ref_line_slider components. "
        "Dict with 'conditions' (list of {column, operator, value|linked_slider}) "
        "and 'logic' ('and'|'or').",
    )


class ImageLiteComponent(BaseLiteComponent):
    """Lite image component for user definition.

    Example YAML:
        - tag: image-gallery-1
          component_type: image
          workflow_tag: python/image_workflow
          data_collection_tag: image_table
          image_column: image_path
          thumbnail_size: 150
          columns: 4
          max_images: 20
    """

    component_type: Literal["image"] = "image"

    # Image configuration
    image_column: str = Field(..., description="Column containing image paths")
    s3_base_folder: str | None = Field(
        default=None, description="Base S3 folder for images (defaults to data collection folder)"
    )

    # Display options
    thumbnail_size: int = Field(default=150, description="Grid thumbnail size in pixels")
    columns: int = Field(default=4, description="Number of grid columns")
    max_images: int = Field(default=20, description="Maximum images to display")


class MultiQCLiteComponent(BaseLiteComponent):
    """Lite MultiQC component for user definition.

    Both selected_module and selected_plot are required: without them the
    component cannot render a specific plot and the YAML would be ambiguous.
    At runtime the Dash model allows None (auto-selects), but in user-defined
    YAML the choice must be explicit.

    Example YAML:
        - tag: fastqc-quality
          component_type: multiqc
          workflow_tag: python/nf_workflow
          data_collection_tag: multiqc_report
          selected_module: fastqc
          selected_plot: per_base_sequence_quality
    """

    component_type: Literal["multiqc"] = "multiqc"

    selected_module: str = Field(..., description="MultiQC module to display (e.g. 'fastqc')")
    selected_plot: str = Field(
        ..., description="Plot within the module (e.g. 'per_base_sequence_quality')"
    )


class RefLineLiteComponent(BaseLiteComponent):
    """Lite ref-line slider component for user definition.

    A standalone slider that controls reference line positions and dynamic
    highlight thresholds in linked figure components. Decoupled from data
    filtering (unlike interactive components).

    Example YAML:
        - tag: width-threshold
          component_type: ref_line_slider
          label: "Sepal Width Threshold"
          min: 2.0
          max: 4.5
          default: 3.8
          step: 0.1
    """

    component_type: Literal["ref_line_slider"] = "ref_line_slider"

    # workflow_tag and data_collection_tag are not needed for this component type
    # but are inherited from BaseLiteComponent with empty defaults

    # Slider configuration
    label: str = Field(default="Threshold", description="Display label for the slider")
    min: float = Field(default=0.0, description="Minimum slider value")
    max: float = Field(default=100.0, description="Maximum slider value")
    default: float = Field(default=50.0, description="Initial slider value")
    step: float | None = Field(
        default=None, description="Step size (auto-calculated as 1% of range if None)"
    )


# Union type for any lite component
LiteComponent = (
    FigureLiteComponent
    | CardLiteComponent
    | InteractiveLiteComponent
    | TableLiteComponent
    | ImageLiteComponent
    | MultiQCLiteComponent
    | RefLineLiteComponent
)
