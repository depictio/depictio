"""
Pydantic models for Plotly figure customizations.

This module defines the schema for declarative figure customizations
that can be expressed in YAML and applied to Plotly figures.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

# =============================================================================
# Enums for type safety
# =============================================================================


class AxisScale(str, Enum):
    """Supported axis scale types."""

    LINEAR = "linear"
    LOG = "log"
    SYMLOG = "symlog"  # Symmetric log scale (linear near zero)
    SQRT = "sqrt"  # Square root scale
    REVERSE = "reverse"  # Reversed linear scale


class LineStyle(str, Enum):
    """Line style options for reference lines."""

    SOLID = "solid"
    DASH = "dash"
    DOT = "dot"
    DASHDOT = "dashdot"
    LONGDASH = "longdash"
    LONGDASHDOT = "longdashdot"


class ReferenceLineType(str, Enum):
    """Type of reference line."""

    HLINE = "hline"  # Horizontal line
    VLINE = "vline"  # Vertical line
    DIAGONAL = "diagonal"  # y=x diagonal line
    TREND = "trend"  # Trend line through points


class HighlightConditionOperator(str, Enum):
    """Operators for highlight conditions."""

    EQ = "eq"  # Equal
    NE = "ne"  # Not equal
    GT = "gt"  # Greater than
    GE = "ge"  # Greater than or equal
    LT = "lt"  # Less than
    LE = "le"  # Less than or equal
    IN = "in"  # In list
    NOT_IN = "not_in"  # Not in list
    CONTAINS = "contains"  # String contains
    REGEX = "regex"  # Regex match


class AnnotationPosition(str, Enum):
    """Position options for annotations."""

    TOP_LEFT = "top left"
    TOP_CENTER = "top center"
    TOP_RIGHT = "top right"
    MIDDLE_LEFT = "middle left"
    MIDDLE_CENTER = "middle center"
    MIDDLE_RIGHT = "middle right"
    BOTTOM_LEFT = "bottom left"
    BOTTOM_CENTER = "bottom center"
    BOTTOM_RIGHT = "bottom right"


# =============================================================================
# Axis Configuration
# =============================================================================


class AxisTickConfig(BaseModel):
    """Configuration for axis ticks."""

    show: bool = Field(True, description="Whether to show ticks")
    values: Optional[List[Union[float, int, str]]] = Field(None, description="Custom tick values")
    labels: Optional[List[str]] = Field(None, description="Custom tick labels")
    format: Optional[str] = Field(None, description="D3 format string (e.g., '.2f', '%')")
    angle: Optional[float] = Field(None, description="Tick label rotation angle")
    font_size: Optional[int] = Field(None, description="Tick font size")


class AxisConfig(BaseModel):
    """Configuration for a single axis."""

    scale: AxisScale = Field(AxisScale.LINEAR, description="Axis scale type")
    title: Optional[str] = Field(None, description="Axis title override")
    range: Optional[List[Union[float, int, None]]] = Field(
        None, description="Axis range [min, max]"
    )
    autorange: Optional[Literal["reversed", True, False]] = Field(
        None, description="Autorange setting"
    )
    dtick: Optional[Union[float, int]] = Field(None, description="Tick interval")
    tick0: Optional[Union[float, int]] = Field(None, description="First tick position")
    tickmode: Optional[Literal["auto", "linear", "array"]] = Field(None, description="Tick mode")
    ticks: Optional[AxisTickConfig] = Field(None, description="Tick configuration")
    gridlines: Optional[bool] = Field(None, description="Show gridlines")
    gridcolor: Optional[str] = Field(None, description="Gridline color")
    zeroline: Optional[bool] = Field(None, description="Show zero line")
    zerolinecolor: Optional[str] = Field(None, description="Zero line color")
    showspikes: Optional[bool] = Field(None, description="Show spikes on hover")
    spikecolor: Optional[str] = Field(None, description="Spike color")
    spikethickness: Optional[int] = Field(None, description="Spike line thickness")

    @field_validator("range")
    @classmethod
    def validate_range(
        cls, v: Optional[List[Union[float, int, None]]]
    ) -> Optional[List[Union[float, int, None]]]:
        """Validate range has exactly 2 elements."""
        if v is not None:
            if len(v) != 2:
                raise ValueError("range must have exactly 2 elements [min, max]")
        return v


class AxesConfig(BaseModel):
    """Configuration for all axes."""

    x: Optional[AxisConfig] = Field(None, description="X-axis configuration")
    y: Optional[AxisConfig] = Field(None, description="Y-axis configuration")
    z: Optional[AxisConfig] = Field(None, description="Z-axis configuration (for 3D)")
    # Support for secondary axes
    x2: Optional[AxisConfig] = Field(None, description="Secondary X-axis")
    y2: Optional[AxisConfig] = Field(None, description="Secondary Y-axis")


# =============================================================================
# Reference Lines
# =============================================================================


class ReferenceLineConfig(BaseModel):
    """Configuration for a reference line (hline, vline, diagonal)."""

    type: ReferenceLineType = Field(..., description="Type of reference line")

    # Position (depends on type)
    y: Optional[Union[float, int, str]] = Field(None, description="Y position for hline")
    x: Optional[Union[float, int, str]] = Field(None, description="X position for vline")

    # Line styling
    line_color: str = Field("gray", description="Line color")
    line_width: float = Field(1.0, description="Line width")
    line_dash: LineStyle = Field(LineStyle.DASH, description="Line dash style")
    opacity: float = Field(0.8, description="Line opacity")

    # Range limits (for partial lines)
    x0: Optional[Union[float, int]] = Field(None, description="Start X position")
    x1: Optional[Union[float, int]] = Field(None, description="End X position")
    y0: Optional[Union[float, int]] = Field(None, description="Start Y position")
    y1: Optional[Union[float, int]] = Field(None, description="End Y position")

    # Annotation
    annotation_text: Optional[str] = Field(None, description="Annotation text")
    annotation_position: AnnotationPosition = Field(
        AnnotationPosition.TOP_RIGHT, description="Annotation position"
    )
    annotation_font_size: int = Field(10, description="Annotation font size")
    annotation_font_color: Optional[str] = Field(None, description="Annotation color")

    # Layer
    layer: Literal["above", "below"] = Field("below", description="Draw above or below traces")

    @field_validator("opacity")
    @classmethod
    def validate_opacity(cls, v: float) -> float:
        """Validate opacity is between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("opacity must be between 0 and 1")
        return v


# =============================================================================
# Point Highlighting
# =============================================================================


class HighlightCondition(BaseModel):
    """A single condition for highlighting points."""

    column: str = Field(..., description="Column to evaluate")
    operator: HighlightConditionOperator = Field(
        HighlightConditionOperator.EQ, description="Comparison operator"
    )
    value: Any = Field(..., description="Value to compare against")

    @field_validator("value")
    @classmethod
    def validate_value_for_operator(cls, v: Any, info: Any) -> Any:
        """Validate value matches operator requirements."""
        # Get operator from info if available
        operator = info.data.get("operator") if info.data else None
        if operator in (HighlightConditionOperator.IN, HighlightConditionOperator.NOT_IN):
            if not isinstance(v, list):
                raise ValueError(f"value must be a list for operator {operator}")
        return v


class HighlightStyle(BaseModel):
    """Style configuration for highlighted points."""

    marker_color: Optional[str] = Field(None, description="Marker color for highlights")
    marker_size: Optional[float] = Field(None, description="Marker size for highlights")
    marker_symbol: Optional[str] = Field(
        None, description="Marker symbol (circle, square, diamond, etc.)"
    )
    marker_opacity: Optional[float] = Field(None, description="Marker opacity")
    marker_line_color: Optional[str] = Field(None, description="Marker border color")
    marker_line_width: Optional[float] = Field(None, description="Marker border width")

    # For non-highlighted points
    dim_opacity: Optional[float] = Field(0.3, description="Opacity for non-highlighted points")
    dim_color: Optional[str] = Field(None, description="Color for non-highlighted points")


class HighlightConfig(BaseModel):
    """Configuration for highlighting specific points based on conditions."""

    conditions: List[HighlightCondition] = Field(
        ..., description="Conditions to match for highlighting"
    )
    logic: Literal["and", "or"] = Field("and", description="How to combine multiple conditions")
    style: HighlightStyle = Field(
        default_factory=HighlightStyle, description="Style for highlighted points"
    )
    label: Optional[str] = Field(None, description="Label for highlighted group in legend")
    show_labels: bool = Field(False, description="Show text labels for highlighted points")
    label_column: Optional[str] = Field(None, description="Column to use for point labels")


# =============================================================================
# Annotations
# =============================================================================


class AnnotationConfig(BaseModel):
    """Configuration for text annotations on the figure."""

    text: str = Field(..., description="Annotation text")

    # Position
    x: Union[float, int, str] = Field(..., description="X position")
    y: Union[float, int, str] = Field(..., description="Y position")
    xref: Literal["x", "paper"] = Field("x", description="X reference system")
    yref: Literal["y", "paper"] = Field("y", description="Y reference system")

    # Text styling
    font_size: int = Field(12, description="Font size")
    font_color: Optional[str] = Field(None, description="Font color")
    font_family: Optional[str] = Field(None, description="Font family")
    textangle: float = Field(0, description="Text rotation angle")
    align: Literal["left", "center", "right"] = Field("center", description="Text align")

    # Positioning
    xanchor: Literal["left", "center", "right", "auto"] = Field("auto", description="X anchor")
    yanchor: Literal["top", "middle", "bottom", "auto"] = Field("auto", description="Y anchor")

    # Arrow
    showarrow: bool = Field(False, description="Show arrow to point")
    arrowhead: int = Field(1, description="Arrow head style (0-8)")
    arrowsize: float = Field(1, description="Arrow size multiplier")
    arrowwidth: float = Field(1, description="Arrow line width")
    arrowcolor: Optional[str] = Field(None, description="Arrow color")

    # Position offsets when using arrow
    ax: Optional[Union[float, int]] = Field(None, description="Arrow X offset from annotation")
    ay: Optional[Union[float, int]] = Field(None, description="Arrow Y offset from annotation")

    # Background
    bgcolor: Optional[str] = Field(None, description="Background color")
    bordercolor: Optional[str] = Field(None, description="Border color")
    borderwidth: int = Field(0, description="Border width")
    borderpad: int = Field(1, description="Border padding")
    opacity: float = Field(1, description="Annotation opacity")


# =============================================================================
# Shapes
# =============================================================================


class ShapeConfig(BaseModel):
    """Configuration for shapes (rectangles, circles, lines, paths)."""

    type: Literal["rect", "circle", "line", "path"] = Field(..., description="Shape type")

    # Position (for rect, circle, line)
    x0: Optional[Union[float, int, str]] = Field(None, description="Start X")
    y0: Optional[Union[float, int, str]] = Field(None, description="Start Y")
    x1: Optional[Union[float, int, str]] = Field(None, description="End X")
    y1: Optional[Union[float, int, str]] = Field(None, description="End Y")

    # For path type
    path: Optional[str] = Field(None, description="SVG path for path type")

    # Reference systems
    xref: Literal["x", "paper"] = Field("x", description="X reference")
    yref: Literal["y", "paper"] = Field("y", description="Y reference")

    # Styling
    fillcolor: Optional[str] = Field(None, description="Fill color")
    opacity: float = Field(0.5, description="Shape opacity")
    line_color: Optional[str] = Field(None, description="Line/border color")
    line_width: float = Field(1, description="Line/border width")
    line_dash: LineStyle = Field(LineStyle.SOLID, description="Line dash style")

    # Layer
    layer: Literal["above", "below"] = Field("below", description="Draw above or below traces")


# =============================================================================
# Legend Configuration
# =============================================================================


class LegendConfig(BaseModel):
    """Configuration for the figure legend."""

    show: bool = Field(True, description="Show legend")
    title: Optional[str] = Field(None, description="Legend title")
    x: Optional[float] = Field(None, description="X position (0-1)")
    y: Optional[float] = Field(None, description="Y position (0-1)")
    xanchor: Optional[Literal["left", "center", "right", "auto"]] = Field(
        None, description="X anchor"
    )
    yanchor: Optional[Literal["top", "middle", "bottom", "auto"]] = Field(
        None, description="Y anchor"
    )
    orientation: Literal["v", "h"] = Field("v", description="Orientation")
    bgcolor: Optional[str] = Field(None, description="Background color")
    bordercolor: Optional[str] = Field(None, description="Border color")
    borderwidth: int = Field(0, description="Border width")
    font_size: Optional[int] = Field(None, description="Font size")
    itemsizing: Literal["trace", "constant"] = Field("trace", description="Item sizing mode")
    traceorder: Optional[Literal["normal", "reversed", "grouped"]] = Field(
        None, description="Trace order"
    )


# =============================================================================
# Colorbar Configuration
# =============================================================================


class ColorbarConfig(BaseModel):
    """Configuration for the colorbar."""

    title: Optional[str] = Field(None, description="Colorbar title")
    tickformat: Optional[str] = Field(None, description="Tick format string")
    tickvals: Optional[List[Union[float, int]]] = Field(None, description="Custom tick values")
    ticktext: Optional[List[str]] = Field(None, description="Custom tick labels")
    len: Optional[float] = Field(None, description="Length (0-1)")
    thickness: Optional[int] = Field(None, description="Thickness in pixels")
    x: Optional[float] = Field(None, description="X position")
    y: Optional[float] = Field(None, description="Y position")
    xanchor: Optional[Literal["left", "center", "right"]] = Field(None, description="X anchor")
    yanchor: Optional[Literal["top", "middle", "bottom"]] = Field(None, description="Y anchor")
    orientation: Optional[Literal["h", "v"]] = Field(None, description="Orientation")


# =============================================================================
# Hover Configuration
# =============================================================================


class HoverConfig(BaseModel):
    """Configuration for hover behavior."""

    mode: Optional[Literal["x", "y", "closest", "x unified", "y unified"]] = Field(
        None, description="Hover mode"
    )
    template: Optional[str] = Field(None, description="Custom hover template")
    bgcolor: Optional[str] = Field(None, description="Hover background color")
    bordercolor: Optional[str] = Field(None, description="Hover border color")
    font_size: Optional[int] = Field(None, description="Hover font size")
    font_color: Optional[str] = Field(None, description="Hover font color")
    align: Optional[Literal["left", "right", "auto"]] = Field(
        None, description="Hover text alignment"
    )


# =============================================================================
# Main Customizations Model
# =============================================================================


class FigureCustomizations(BaseModel):
    """
    Complete customization configuration for a Plotly figure.

    This is the top-level model that contains all customization options.
    It can be serialized to/from YAML as part of the dashboard configuration.
    """

    # Axis customizations
    axes: Optional[AxesConfig] = Field(None, description="Axis configurations")

    # Reference lines
    reference_lines: Optional[List[ReferenceLineConfig]] = Field(
        None, description="Reference lines (hline, vline, diagonal)"
    )

    # Point highlighting
    highlights: Optional[List[HighlightConfig]] = Field(
        None, description="Point highlighting configurations"
    )

    # Annotations
    annotations: Optional[List[AnnotationConfig]] = Field(None, description="Text annotations")

    # Shapes
    shapes: Optional[List[ShapeConfig]] = Field(
        None, description="Shapes (rectangles, circles, etc.)"
    )

    # Legend
    legend: Optional[LegendConfig] = Field(None, description="Legend configuration")

    # Colorbar
    colorbar: Optional[ColorbarConfig] = Field(None, description="Colorbar configuration")

    # Hover
    hover: Optional[HoverConfig] = Field(None, description="Hover configuration")

    # Layout overrides (for advanced users)
    layout_overrides: Optional[Dict[str, Any]] = Field(
        None, description="Raw layout dict overrides (advanced)"
    )

    # Trace overrides (for advanced users)
    trace_overrides: Optional[Dict[str, Any]] = Field(
        None, description="Raw trace dict overrides (advanced)"
    )

    class Config:
        """Pydantic model configuration."""

        extra = "forbid"  # Prevent unknown fields

    def has_customizations(self) -> bool:
        """Check if any customizations are defined."""
        return any(
            [
                self.axes,
                self.reference_lines,
                self.highlights,
                self.annotations,
                self.shapes,
                self.legend,
                self.colorbar,
                self.hover,
                self.layout_overrides,
                self.trace_overrides,
            ]
        )

    def to_yaml_dict(self) -> Dict[str, Any]:
        """Convert to YAML-serializable dictionary, excluding None values."""
        data = self.model_dump(exclude_none=True, mode="json")
        # Convert enum values to strings
        return self._convert_enums(data)

    def _convert_enums(self, data: Any) -> Any:
        """Recursively convert enum values to strings."""
        if isinstance(data, dict):
            return {k: self._convert_enums(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._convert_enums(item) for item in data]
        elif isinstance(data, Enum):
            return data.value
        return data

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "FigureCustomizations":
        """Create from YAML dictionary."""
        return cls.model_validate(data)
