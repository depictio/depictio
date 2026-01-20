"""Pydantic models for MVP YAML dashboard format validation."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ============================================================================
# Component Type Models
# ============================================================================


class VisualizationConfig(BaseModel):
    """Visualization configuration for figure components."""

    chart: str = Field(..., description="Chart type (scatter, box, histogram, etc.)")
    x: str | None = None
    y: str | None = None
    color: str | None = None
    size: str | None = None
    style: dict[str, Any] | None = None

    model_config = {"extra": "allow"}  # Allow additional fields


class AggregationConfig(BaseModel):
    """Aggregation configuration for card components."""

    column: str = Field(..., description="Column to aggregate")
    function: str = Field(..., description="Aggregation function (average, sum, count, etc.)")
    column_type: str = Field(..., description="Data type of column")

    model_config = {"extra": "allow"}


class FilterConfig(BaseModel):
    """Filter configuration for interactive components."""

    column: str = Field(..., description="Column to filter on")
    type: str = Field(..., description="Filter type (RangeSlider, MultiSelect, etc.)")
    column_type: str = Field(..., description="Data type of column")

    model_config = {"extra": "allow"}


class StylingConfig(BaseModel):
    """Optional styling configuration for components."""

    model_config = {"extra": "allow"}  # Allow any styling fields


# ============================================================================
# Component Models
# ============================================================================


class BaseComponent(BaseModel):
    """Base component with common fields."""

    id: str = Field(..., description="Component identifier")
    type: Literal["figure", "card", "interactive", "table"] = Field(
        ..., description="Component type"
    )
    workflow: str = Field(..., description="Workflow tag (human-readable name, not wf_* reference)")
    data_collection: str = Field(
        ..., description="Data collection tag (human-readable name, not dc_* reference)"
    )
    title: str | None = None
    styling: StylingConfig | None = None

    @field_validator("workflow")
    @classmethod
    def validate_workflow_tag(cls, v: str) -> str:
        """Ensure workflow is a tag name, not a tag reference."""
        if v.startswith("wf_"):
            raise ValueError(
                f"Invalid workflow '{v}' - must use tag name (e.g., 'python/iris_workflow'), "
                f"not tag reference (wf_*)"
            )
        return v

    @field_validator("data_collection")
    @classmethod
    def validate_data_collection_tag(cls, v: str) -> str:
        """Ensure data_collection is a tag name, not a tag reference."""
        if v.startswith("dc_"):
            raise ValueError(
                f"Invalid data_collection '{v}' - must use tag name (e.g., 'iris_table'), "
                f"not tag reference (dc_*)"
            )
        return v


class FigureComponent(BaseComponent):
    """Figure component with visualization config."""

    type: Literal["figure"] = "figure"
    visualization: VisualizationConfig = Field(..., description="Visualization configuration")


class CardComponent(BaseComponent):
    """Card component with aggregation config."""

    type: Literal["card"] = "card"
    aggregation: AggregationConfig = Field(..., description="Aggregation configuration")


class InteractiveComponent(BaseComponent):
    """Interactive component with filter config."""

    type: Literal["interactive"] = "interactive"
    filter: FilterConfig = Field(..., description="Filter configuration")


class TableComponent(BaseComponent):
    """Table component (no additional config required)."""

    type: Literal["table"] = "table"


# Union type for any component
Component = FigureComponent | CardComponent | InteractiveComponent | TableComponent


# ============================================================================
# Dashboard Model
# ============================================================================


class MVPDashboard(BaseModel):
    """MVP YAML dashboard format."""

    dashboard: str = Field(..., description="Dashboard ID")
    title: str = Field(..., description="Dashboard title")
    components: list[Component] = Field(
        default_factory=list, description="List of dashboard components"
    )
