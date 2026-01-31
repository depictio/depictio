"""
Lite Component Models.

Minimal component models for user-defined dashboards (YAML/Python).
Full component models inherit from these and add runtime fields.

Architecture:
    FigureLiteComponent (user-definable, YAML-friendly)
        ↓ inherits
    FigureComponent (adds runtime/rendering fields)
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BaseLiteComponent(BaseModel):
    """Base class for lite dashboard components.

    Contains only the fields users need to define a component.
    Runtime fields (wf_id, dc_id, dc_config, etc.) are added by full components.
    """

    model_config = ConfigDict(extra="allow")

    # Component identification
    index: str = Field(..., description="Component identifier (e.g., 'scatter-1')")
    component_type: str = Field(..., description="Component type")

    # Display
    title: str = Field(default="", description="Component title")

    # Data source references (human-readable tags)
    workflow_tag: str = Field(..., description="Workflow tag (e.g., 'python/iris_workflow')")
    data_collection_tag: str = Field(..., description="Data collection tag (e.g., 'iris_table')")


class FigureLiteComponent(BaseLiteComponent):
    """Lite figure component for user definition.

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


class CardLiteComponent(BaseLiteComponent):
    """Lite card component for user definition.

    Example YAML:
        - index: card-1
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
    column_type: str = Field(default="float64", description="Data type of column")

    # Styling (optional)
    icon_name: str | None = Field(default=None, description="Iconify icon name")
    icon_color: str | None = Field(default=None, description="Icon color")
    title_color: str | None = Field(default=None, description="Title text color")
    title_font_size: str | None = Field(default=None, description="Title font size")
    value_font_size: str | None = Field(default=None, description="Value font size")


class InteractiveLiteComponent(BaseLiteComponent):
    """Lite interactive component for user definition.

    Example YAML:
        - index: filter-1
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
    column_type: str = Field(default="object", description="Data type of column")

    # Styling (optional)
    title_size: str | None = Field(default=None, description="Title size")
    custom_color: str | None = Field(default=None, description="Custom accent color")
    icon_name: str | None = Field(default=None, description="Iconify icon name")


class TableLiteComponent(BaseLiteComponent):
    """Lite table component for user definition.

    Example YAML:
        - index: table-1
          component_type: table
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
    """

    component_type: Literal["table"] = "table"

    # Table options (optional)
    columns: list[str] = Field(default_factory=list, description="Columns to display (empty = all)")
    page_size: int = Field(default=10, description="Rows per page")
    sortable: bool = Field(default=True, description="Enable column sorting")
    filterable: bool = Field(default=True, description="Enable column filtering")


# Union type for any lite component
LiteComponent = (
    FigureLiteComponent | CardLiteComponent | InteractiveLiteComponent | TableLiteComponent
)
