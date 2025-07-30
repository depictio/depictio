"""
Pydantic models for robust figure component parameter handling.

This module provides type-safe parameter definitions for Plotly Express
visualizations, replacing the fragile docstring parsing approach.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, validator


class ParameterType(str, Enum):
    """Supported parameter types for UI components."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    COLUMN = "column"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    COLOR = "color"
    RANGE = "range"


class ParameterCategory(str, Enum):
    """Parameter categories for organizing UI."""

    CORE = "core"  # Essential parameters (x, y, color)
    COMMON = "common"  # Shared across visualizations
    SPECIFIC = "specific"  # Visualization-specific
    ADVANCED = "advanced"  # Advanced/rarely used parameters


class VisualizationGroup(str, Enum):
    """Visualization groups for organizing dropdown."""

    CORE = "core"  # Basic/standard visualizations (scatter, bar, line, etc.)
    ADVANCED = "advanced"  # Advanced statistical plots
    THREE_D = "3d"  # 3D visualizations
    GEOGRAPHIC = "geographic"  # Map-based visualizations
    CLUSTERING = "clustering"  # Clustering and dimensionality reduction
    SPECIALIZED = "specialized"  # Specialized/niche visualizations


class ParameterDefinition(BaseModel):
    """Definition of a single parameter for a visualization."""

    name: str = Field(..., description="Parameter name")
    type: ParameterType = Field(..., description="Parameter type")
    category: ParameterCategory = Field(..., description="Parameter category")
    label: str = Field(..., description="Human-readable label")
    description: str = Field("", description="Parameter description")
    default: Optional[Any] = Field(None, description="Default value")
    required: bool = Field(False, description="Whether parameter is required")
    options: Optional[List[Union[str, int, float]]] = Field(
        None, description="Available options for select types"
    )
    min_value: Optional[Union[int, float]] = Field(
        None, description="Minimum value for numeric types"
    )
    max_value: Optional[Union[int, float]] = Field(
        None, description="Maximum value for numeric types"
    )
    depends_on: Optional[List[str]] = Field(None, description="Parameters this depends on")

    @validator("options")
    def validate_options(cls, v, values):
        """Validate that options are provided for select types."""
        param_type = values.get("type")
        # Only require options for SELECT parameters - MULTI_SELECT can be populated dynamically
        if param_type == ParameterType.SELECT and not v:
            raise ValueError("Options required for ParameterType.SELECT parameters")
        # For MULTI_SELECT, allow None/empty and convert to empty list
        if param_type == ParameterType.MULTI_SELECT and not v:
            return []
        return v


class VisualizationDefinition(BaseModel):
    """Complete definition of a visualization type."""

    name: str = Field(..., description="Visualization name")
    function_name: str = Field(..., description="Plotly Express function name")
    label: str = Field(..., description="Human-readable label")
    description: str = Field("", description="Visualization description")
    parameters: List[ParameterDefinition] = Field(..., description="Parameter definitions")
    icon: str = Field("mdi:chart-line", description="Icon for UI")
    group: VisualizationGroup = Field(VisualizationGroup.CORE, description="Visualization group")

    @property
    def core_params(self) -> List[ParameterDefinition]:
        """Get core parameters."""
        return [p for p in self.parameters if p.category == ParameterCategory.CORE]

    @property
    def common_params(self) -> List[ParameterDefinition]:
        """Get common parameters."""
        return [p for p in self.parameters if p.category == ParameterCategory.COMMON]

    @property
    def specific_params(self) -> List[ParameterDefinition]:
        """Get specific parameters."""
        return [p for p in self.parameters if p.category == ParameterCategory.SPECIFIC]

    @property
    def advanced_params(self) -> List[ParameterDefinition]:
        """Get advanced parameters."""
        return [p for p in self.parameters if p.category == ParameterCategory.ADVANCED]


class FigureComponentState(BaseModel):
    """State management for figure components."""

    component_id: str = Field(..., description="Unique component identifier")
    visualization_type: str = Field(..., description="Selected visualization type")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameter values")
    data_collection_id: str = Field(..., description="Data collection ID")
    workflow_id: str = Field(..., description="Workflow ID")
    theme: Literal["light", "dark"] = Field("light", description="Theme setting")
    is_editing: bool = Field(False, description="Whether component is in edit mode")
    last_updated: Optional[str] = Field(None, description="Last update timestamp")

    @field_validator("parameters")
    def validate_parameters(cls, v):
        """Ensure parameters is always a dictionary."""
        if not isinstance(v, dict):
            # If parameters is not a dict, convert it to an empty dict
            return {}
        return v

    def get_parameter_value(self, param_name: str, default: Any = None) -> Any:
        """Get parameter value with fallback to default."""
        return self.parameters.get(param_name, default)

    def set_parameter_value(self, param_name: str, value: Any) -> None:
        """Set parameter value."""
        self.parameters[param_name] = value

    def clear_parameters(self) -> None:
        """Clear all parameter values."""
        self.parameters.clear()


class ComponentConfig(BaseModel):
    """Configuration for the figure component system."""

    max_data_points: int = Field(100000, description="Maximum data points before sampling")
    enable_caching: bool = Field(True, description="Enable parameter and data caching")
    cache_ttl: int = Field(3600, description="Cache TTL in seconds")
    auto_update: bool = Field(
        True, description="Enable automatic figure updates on parameter change"
    )
    responsive_sizing: bool = Field(True, description="Enable responsive figure sizing")
    show_advanced_params: bool = Field(False, description="Show advanced parameters by default")


# Define core parameters that are common across visualizations
CORE_PARAMETERS = [
    ParameterDefinition(
        name="x",
        type=ParameterType.COLUMN,
        category=ParameterCategory.CORE,
        label="X Axis",
        description="Column for x-axis values",
        required=True,
    ),
    ParameterDefinition(
        name="y",
        type=ParameterType.COLUMN,
        category=ParameterCategory.CORE,
        label="Y Axis",
        description="Column for y-axis values",
    ),
    ParameterDefinition(
        name="color",
        type=ParameterType.COLUMN,
        category=ParameterCategory.CORE,
        label="Color",
        description="Column for color encoding",
    ),
]

# Define common parameters shared across many visualizations
COMMON_PARAMETERS = [
    ParameterDefinition(
        name="title",
        type=ParameterType.STRING,
        category=ParameterCategory.COMMON,
        label="Title",
        description="Figure title",
    ),
    ParameterDefinition(
        name="width",
        type=ParameterType.INTEGER,
        category=ParameterCategory.COMMON,
        label="Width",
        description="Figure width in pixels",
        min_value=100,
        max_value=2000,
        default=None,
    ),
    ParameterDefinition(
        name="height",
        type=ParameterType.INTEGER,
        category=ParameterCategory.COMMON,
        label="Height",
        description="Figure height in pixels",
        min_value=100,
        max_value=2000,
        default=None,
    ),
    ParameterDefinition(
        name="template",
        type=ParameterType.SELECT,
        category=ParameterCategory.COMMON,
        label="Template",
        description="Plotly template to use",
        options=[
            "plotly",
            "plotly_white",
            "plotly_dark",
            "ggplot2",
            "seaborn",
            "simple_white",
            "mantine_white",
            "mantine_dark",
        ],
        default=None,
    ),
    ParameterDefinition(
        name="opacity",
        type=ParameterType.FLOAT,
        category=ParameterCategory.COMMON,
        label="Opacity",
        description="Marker opacity",
        min_value=0.0,
        max_value=1.0,
        default=None,
    ),
]

# Advanced parameters
ADVANCED_PARAMETERS = [
    ParameterDefinition(
        name="log_x",
        type=ParameterType.BOOLEAN,
        category=ParameterCategory.ADVANCED,
        label="Log X Scale",
        description="Use logarithmic scale for x-axis",
        default=False,
    ),
    ParameterDefinition(
        name="log_y",
        type=ParameterType.BOOLEAN,
        category=ParameterCategory.ADVANCED,
        label="Log Y Scale",
        description="Use logarithmic scale for y-axis",
        default=False,
    ),
    ParameterDefinition(
        name="range_x",
        type=ParameterType.RANGE,
        category=ParameterCategory.ADVANCED,
        label="X Range",
        description="X-axis range",
    ),
    ParameterDefinition(
        name="range_y",
        type=ParameterType.RANGE,
        category=ParameterCategory.ADVANCED,
        label="Y Range",
        description="Y-axis range",
    ),
]
