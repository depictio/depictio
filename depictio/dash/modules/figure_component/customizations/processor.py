"""
Processor for applying customizations to Plotly figures.

This module contains the logic for applying FigureCustomizations to
Plotly figure objects, transforming the declarative configuration
into actual figure modifications.
"""

from typing import Any, Dict, List, Optional, Union

import pandas as pd
import plotly.graph_objects as go

from depictio.models.logging import logger

from .models import (
    AnnotationConfig,
    AnnotationPosition,
    AxisConfig,
    AxisScale,
    ColorbarConfig,
    FigureCustomizations,
    HighlightCondition,
    HighlightConditionOperator,
    HighlightConfig,
    HoverConfig,
    LegendConfig,
    LineStyle,
    ReferenceLineConfig,
    ReferenceLineType,
    ShapeConfig,
)

# =============================================================================
# Utility Functions
# =============================================================================


def _line_style_to_plotly(style: LineStyle) -> str:
    """Convert LineStyle enum to Plotly dash string."""
    return style.value


def _annotation_position_to_coords(
    position: AnnotationPosition,
) -> tuple[str, str]:
    """Convert AnnotationPosition to xanchor/yanchor values."""
    mapping = {
        AnnotationPosition.TOP_LEFT: ("left", "top"),
        AnnotationPosition.TOP_CENTER: ("center", "top"),
        AnnotationPosition.TOP_RIGHT: ("right", "top"),
        AnnotationPosition.MIDDLE_LEFT: ("left", "middle"),
        AnnotationPosition.MIDDLE_CENTER: ("center", "middle"),
        AnnotationPosition.MIDDLE_RIGHT: ("right", "middle"),
        AnnotationPosition.BOTTOM_LEFT: ("left", "bottom"),
        AnnotationPosition.BOTTOM_CENTER: ("center", "bottom"),
        AnnotationPosition.BOTTOM_RIGHT: ("right", "bottom"),
    }
    return mapping.get(position, ("auto", "auto"))


def _evaluate_condition(
    df: pd.DataFrame,
    condition: HighlightCondition,
) -> pd.Series:
    """Evaluate a highlight condition against a DataFrame."""
    column = condition.column
    operator = condition.operator
    value = condition.value

    if column not in df.columns:
        logger.warning(f"Column '{column}' not found in DataFrame for highlighting")
        return pd.Series([False] * len(df), index=df.index)

    col_data = df[column]

    if operator == HighlightConditionOperator.EQ:
        return col_data == value
    elif operator == HighlightConditionOperator.NE:
        return col_data != value
    elif operator == HighlightConditionOperator.GT:
        return col_data > value
    elif operator == HighlightConditionOperator.GE:
        return col_data >= value
    elif operator == HighlightConditionOperator.LT:
        return col_data < value
    elif operator == HighlightConditionOperator.LE:
        return col_data <= value
    elif operator == HighlightConditionOperator.IN:
        return col_data.isin(value)
    elif operator == HighlightConditionOperator.NOT_IN:
        return ~col_data.isin(value)
    elif operator == HighlightConditionOperator.CONTAINS:
        return col_data.astype(str).str.contains(str(value), na=False)
    elif operator == HighlightConditionOperator.REGEX:
        return col_data.astype(str).str.match(str(value), na=False)
    else:
        logger.warning(f"Unknown operator: {operator}")
        return pd.Series([False] * len(df), index=df.index)


# =============================================================================
# Axis Application
# =============================================================================


def _apply_axis_config(
    fig: go.Figure,
    axis_name: str,
    config: AxisConfig,
) -> None:
    """Apply axis configuration to a figure."""
    update_dict: Dict[str, Any] = {}

    # Handle scale
    if config.scale == AxisScale.LOG:
        update_dict["type"] = "log"
    elif config.scale == AxisScale.SYMLOG:
        # Plotly doesn't have native symlog, use log with special handling
        update_dict["type"] = "log"
        # Note: True symlog would need custom tick handling
    elif config.scale == AxisScale.SQRT:
        # Plotly doesn't have native sqrt scale
        # This would need data transformation
        logger.warning("SQRT scale not natively supported in Plotly, using linear")
        update_dict["type"] = "linear"
    elif config.scale == AxisScale.REVERSE:
        update_dict["autorange"] = "reversed"
    else:
        update_dict["type"] = "linear"

    # Title
    if config.title is not None:
        update_dict["title"] = {"text": config.title}

    # Range
    if config.range is not None:
        update_dict["range"] = config.range

    # Autorange (only if not already set)
    if config.autorange is not None and "autorange" not in update_dict:
        update_dict["autorange"] = config.autorange

    # Tick settings
    if config.dtick is not None:
        update_dict["dtick"] = config.dtick
    if config.tick0 is not None:
        update_dict["tick0"] = config.tick0
    if config.tickmode is not None:
        update_dict["tickmode"] = config.tickmode

    # Custom ticks
    if config.ticks is not None:
        if not config.ticks.show:
            update_dict["showticklabels"] = False
        if config.ticks.values is not None:
            update_dict["tickmode"] = "array"
            update_dict["tickvals"] = config.ticks.values
        if config.ticks.labels is not None:
            update_dict["ticktext"] = config.ticks.labels
        if config.ticks.format is not None:
            update_dict["tickformat"] = config.ticks.format
        if config.ticks.angle is not None:
            update_dict["tickangle"] = config.ticks.angle
        if config.ticks.font_size is not None:
            update_dict["tickfont"] = {"size": config.ticks.font_size}

    # Grid
    if config.gridlines is not None:
        update_dict["showgrid"] = config.gridlines
    if config.gridcolor is not None:
        update_dict["gridcolor"] = config.gridcolor

    # Zero line
    if config.zeroline is not None:
        update_dict["zeroline"] = config.zeroline
    if config.zerolinecolor is not None:
        update_dict["zerolinecolor"] = config.zerolinecolor

    # Spikes
    if config.showspikes is not None:
        update_dict["showspikes"] = config.showspikes
    if config.spikecolor is not None:
        update_dict["spikecolor"] = config.spikecolor
    if config.spikethickness is not None:
        update_dict["spikethickness"] = config.spikethickness

    # Apply to figure
    if axis_name == "x":
        fig.update_xaxes(**update_dict)
    elif axis_name == "y":
        fig.update_yaxes(**update_dict)
    elif axis_name == "z":
        # For 3D plots
        fig.update_layout(scene={"zaxis": update_dict})
    elif axis_name in ("x2", "y2"):
        # Secondary axes
        fig.update_layout({f"{axis_name}axis": update_dict})


def _apply_axes(fig: go.Figure, axes_config: Any) -> None:
    """Apply all axes configurations."""
    if axes_config.x is not None:
        _apply_axis_config(fig, "x", axes_config.x)
    if axes_config.y is not None:
        _apply_axis_config(fig, "y", axes_config.y)
    if axes_config.z is not None:
        _apply_axis_config(fig, "z", axes_config.z)
    if axes_config.x2 is not None:
        _apply_axis_config(fig, "x2", axes_config.x2)
    if axes_config.y2 is not None:
        _apply_axis_config(fig, "y2", axes_config.y2)


# =============================================================================
# Reference Lines
# =============================================================================


def _apply_reference_line(
    fig: go.Figure,
    config: ReferenceLineConfig,
) -> None:
    """Apply a single reference line to the figure."""
    if config.type == ReferenceLineType.HLINE:
        if config.y is None:
            logger.warning("hline requires 'y' value")
            return

        # Note: x0/x1 in config are for partial lines, but add_hline draws full-width by default
        # For partial horizontal lines, use shapes instead

        fig.add_hline(
            y=config.y,
            line_color=config.line_color,
            line_width=config.line_width,
            line_dash=_line_style_to_plotly(config.line_dash),
            opacity=config.opacity,
            annotation_text=config.annotation_text,
            annotation_position=config.annotation_position.value
            if config.annotation_text
            else None,
            annotation_font_size=config.annotation_font_size,
            annotation_font_color=config.annotation_font_color,
            layer=config.layer,
        )

    elif config.type == ReferenceLineType.VLINE:
        if config.x is None:
            logger.warning("vline requires 'x' value")
            return

        fig.add_vline(
            x=config.x,
            line_color=config.line_color,
            line_width=config.line_width,
            line_dash=_line_style_to_plotly(config.line_dash),
            opacity=config.opacity,
            annotation_text=config.annotation_text,
            annotation_position=config.annotation_position.value
            if config.annotation_text
            else None,
            annotation_font_size=config.annotation_font_size,
            annotation_font_color=config.annotation_font_color,
            layer=config.layer,
        )

    elif config.type == ReferenceLineType.DIAGONAL:
        # Add y=x diagonal line
        # Need to determine axis ranges from the figure
        x_range = _get_axis_range(fig, "x")
        y_range = _get_axis_range(fig, "y")

        if x_range and y_range:
            min_val = max(x_range[0], y_range[0])
            max_val = min(x_range[1], y_range[1])

            fig.add_shape(
                type="line",
                x0=min_val,
                y0=min_val,
                x1=max_val,
                y1=max_val,
                line=dict(
                    color=config.line_color,
                    width=config.line_width,
                    dash=_line_style_to_plotly(config.line_dash),
                ),
                opacity=config.opacity,
                layer=config.layer,
            )

            if config.annotation_text:
                fig.add_annotation(
                    x=max_val,
                    y=max_val,
                    text=config.annotation_text,
                    showarrow=False,
                    font=dict(
                        size=config.annotation_font_size,
                        color=config.annotation_font_color,
                    ),
                )

    elif config.type == ReferenceLineType.TREND:
        # Trend line would need access to the data
        logger.warning("Trend line customization requires data access, skipping")


def _get_axis_range(
    fig: go.Figure,
    axis: str,
) -> Optional[List[float]]:
    """Get the range of an axis from the figure."""
    try:
        # Try to get from layout
        layout = fig.layout
        axis_obj = getattr(layout, f"{axis}axis", None)
        if axis_obj and axis_obj.range:
            return list(axis_obj.range)

        # Try to infer from data
        all_values: List[float] = []
        for trace in fig.data:
            trace_data = getattr(trace, axis, None)
            if trace_data is not None:
                all_values.extend([v for v in trace_data if v is not None])

        if all_values:
            return [min(all_values), max(all_values)]

        return None
    except Exception as e:
        logger.warning(f"Could not determine {axis} axis range: {e}")
        return None


# =============================================================================
# Point Highlighting
# =============================================================================


def _apply_highlights(
    fig: go.Figure,
    highlights: List[HighlightConfig],
    df: Optional[pd.DataFrame] = None,
) -> None:
    """
    Apply point highlighting to the figure.

    For highlighting to work, we need either:
    1. Access to the original DataFrame
    2. The trace customdata to contain the relevant columns

    This function modifies trace marker properties based on conditions.
    """
    if df is None:
        logger.warning(
            "Highlighting requires DataFrame access. "
            "Pass the DataFrame to apply_customizations() for highlighting support."
        )
        return

    if df.empty:
        return

    for highlight_config in highlights:
        # Evaluate all conditions
        masks = [_evaluate_condition(df, condition) for condition in highlight_config.conditions]

        if not masks:
            continue

        # Combine masks based on logic
        if highlight_config.logic == "and":
            combined_mask = masks[0]
            for mask in masks[1:]:
                combined_mask = combined_mask & mask
        else:  # "or"
            combined_mask = masks[0]
            for mask in masks[1:]:
                combined_mask = combined_mask | mask

        # Apply highlighting to traces
        _apply_highlight_to_traces(fig, combined_mask, highlight_config, df)


def _apply_highlight_to_traces(
    fig: go.Figure,
    mask: pd.Series,
    config: HighlightConfig,
    df: pd.DataFrame,
) -> None:
    """Apply highlighting styles to figure traces."""
    style = config.style
    highlight_indices = set(mask[mask].index.tolist())

    for trace in fig.data:
        # Check if this is a scatter-like trace with markers
        if not hasattr(trace, "marker"):
            continue

        # Get the number of points in this trace
        n_points = 0
        if hasattr(trace, "x") and trace.x is not None:
            n_points = len(trace.x)
        elif hasattr(trace, "y") and trace.y is not None:
            n_points = len(trace.y)

        if n_points == 0:
            continue

        # Determine which points to highlight
        # This assumes trace points correspond to DataFrame rows
        if n_points != len(df):
            logger.debug(
                f"Trace has {n_points} points but DataFrame has {len(df)} rows. "
                "Highlighting may not align correctly."
            )

        # Create color and size arrays for all points
        current_marker = trace.marker or {}
        current_color = current_marker.get("color")
        current_size = current_marker.get("size", 8)

        # Build new arrays
        colors: List[Optional[str]] = []
        sizes: List[float] = []
        opacities: List[float] = []

        # Convert current_size to list if scalar
        if isinstance(current_size, (int, float)):
            current_size_list = [current_size] * n_points
        else:
            current_size_list = list(current_size)

        # Convert current_color to list if single value
        if isinstance(current_color, str) or current_color is None:
            current_color_list: List[Optional[str]] = [current_color] * n_points
        elif hasattr(current_color, "__iter__"):
            current_color_list = list(current_color)
        else:
            current_color_list = [str(current_color)] * n_points

        for i in range(n_points):
            is_highlighted = i in highlight_indices

            if is_highlighted:
                # Apply highlight style
                colors.append(style.marker_color or current_color_list[i])
                sizes.append(
                    style.marker_size
                    if style.marker_size is not None
                    else (current_size_list[i] if i < len(current_size_list) else 8)
                )
                opacities.append(style.marker_opacity or 1.0)
            else:
                # Apply dim style
                colors.append(
                    style.dim_color if style.dim_color is not None else current_color_list[i]
                )
                sizes.append(current_size_list[i] if i < len(current_size_list) else 8)
                opacities.append(style.dim_opacity or 0.3)

        # Update the trace
        marker_update: Dict[str, Any] = {"opacity": opacities}

        if style.marker_color is not None or style.dim_color is not None:
            marker_update["color"] = colors

        if style.marker_size is not None:
            marker_update["size"] = sizes

        if style.marker_symbol is not None:
            # Only set symbol for highlighted points
            symbols = [
                style.marker_symbol if i in highlight_indices else "circle" for i in range(n_points)
            ]
            marker_update["symbol"] = symbols

        if style.marker_line_color is not None:
            line_colors = [
                style.marker_line_color if i in highlight_indices else None for i in range(n_points)
            ]
            marker_update["line"] = {
                "color": line_colors,
                "width": style.marker_line_width or 1,
            }

        trace.update(marker=marker_update)

        # Add text labels if requested
        if config.show_labels and config.label_column:
            labels = []
            for i in range(min(n_points, len(df))):
                if i in highlight_indices:
                    labels.append(str(df.iloc[i].get(config.label_column, "")))
                else:
                    labels.append("")
            trace.update(text=labels, textposition="top center")


# =============================================================================
# Annotations
# =============================================================================


def _apply_annotations(
    fig: go.Figure,
    annotations: List[AnnotationConfig],
) -> None:
    """Apply annotations to the figure."""
    for config in annotations:
        annotation_dict: Dict[str, Any] = {
            "text": config.text,
            "x": config.x,
            "y": config.y,
            "xref": config.xref,
            "yref": config.yref,
            "font": {
                "size": config.font_size,
            },
            "textangle": config.textangle,
            "align": config.align,
            "xanchor": config.xanchor,
            "yanchor": config.yanchor,
            "showarrow": config.showarrow,
            "opacity": config.opacity,
        }

        # Optional font properties
        if config.font_color:
            annotation_dict["font"]["color"] = config.font_color
        if config.font_family:
            annotation_dict["font"]["family"] = config.font_family

        # Arrow properties
        if config.showarrow:
            annotation_dict["arrowhead"] = config.arrowhead
            annotation_dict["arrowsize"] = config.arrowsize
            annotation_dict["arrowwidth"] = config.arrowwidth
            if config.arrowcolor:
                annotation_dict["arrowcolor"] = config.arrowcolor
            if config.ax is not None:
                annotation_dict["ax"] = config.ax
            if config.ay is not None:
                annotation_dict["ay"] = config.ay

        # Background
        if config.bgcolor:
            annotation_dict["bgcolor"] = config.bgcolor
        if config.bordercolor:
            annotation_dict["bordercolor"] = config.bordercolor
        if config.borderwidth:
            annotation_dict["borderwidth"] = config.borderwidth
        if config.borderpad:
            annotation_dict["borderpad"] = config.borderpad

        fig.add_annotation(**annotation_dict)


# =============================================================================
# Shapes
# =============================================================================


def _apply_shapes(
    fig: go.Figure,
    shapes: List[ShapeConfig],
) -> None:
    """Apply shapes to the figure."""
    for config in shapes:
        shape_dict: Dict[str, Any] = {
            "type": config.type,
            "xref": config.xref,
            "yref": config.yref,
            "fillcolor": config.fillcolor,
            "opacity": config.opacity,
            "line": {
                "color": config.line_color,
                "width": config.line_width,
                "dash": _line_style_to_plotly(config.line_dash),
            },
            "layer": config.layer,
        }

        # Position
        if config.type == "path":
            shape_dict["path"] = config.path
        else:
            shape_dict["x0"] = config.x0
            shape_dict["y0"] = config.y0
            shape_dict["x1"] = config.x1
            shape_dict["y1"] = config.y1

        fig.add_shape(**shape_dict)


# =============================================================================
# Legend
# =============================================================================


def _apply_legend(
    fig: go.Figure,
    config: LegendConfig,
) -> None:
    """Apply legend configuration to the figure."""
    legend_dict: Dict[str, Any] = {
        "visible": config.show,
        "orientation": config.orientation,
        "itemsizing": config.itemsizing,
    }

    if config.title:
        legend_dict["title"] = {"text": config.title}
    if config.x is not None:
        legend_dict["x"] = config.x
    if config.y is not None:
        legend_dict["y"] = config.y
    if config.xanchor:
        legend_dict["xanchor"] = config.xanchor
    if config.yanchor:
        legend_dict["yanchor"] = config.yanchor
    if config.bgcolor:
        legend_dict["bgcolor"] = config.bgcolor
    if config.bordercolor:
        legend_dict["bordercolor"] = config.bordercolor
    if config.borderwidth:
        legend_dict["borderwidth"] = config.borderwidth
    if config.font_size:
        legend_dict["font"] = {"size": config.font_size}
    if config.traceorder:
        legend_dict["traceorder"] = config.traceorder

    fig.update_layout(legend=legend_dict)


# =============================================================================
# Colorbar
# =============================================================================


def _apply_colorbar(
    fig: go.Figure,
    config: ColorbarConfig,
) -> None:
    """Apply colorbar configuration to the figure."""
    colorbar_dict: Dict[str, Any] = {}

    if config.title:
        colorbar_dict["title"] = {"text": config.title}
    if config.tickformat:
        colorbar_dict["tickformat"] = config.tickformat
    if config.tickvals is not None:
        colorbar_dict["tickvals"] = config.tickvals
    if config.ticktext is not None:
        colorbar_dict["ticktext"] = config.ticktext
    if config.len is not None:
        colorbar_dict["len"] = config.len
    if config.thickness is not None:
        colorbar_dict["thickness"] = config.thickness
    if config.x is not None:
        colorbar_dict["x"] = config.x
    if config.y is not None:
        colorbar_dict["y"] = config.y
    if config.xanchor:
        colorbar_dict["xanchor"] = config.xanchor
    if config.yanchor:
        colorbar_dict["yanchor"] = config.yanchor
    if config.orientation:
        colorbar_dict["orientation"] = config.orientation

    # Apply to all traces with colorbars
    for trace in fig.data:
        if hasattr(trace, "marker") and trace.marker:
            trace.update(marker={"colorbar": colorbar_dict})


# =============================================================================
# Hover
# =============================================================================


def _apply_hover(
    fig: go.Figure,
    config: HoverConfig,
) -> None:
    """Apply hover configuration to the figure."""
    layout_dict: Dict[str, Any] = {}

    if config.mode:
        layout_dict["hovermode"] = config.mode

    hoverlabel_dict: Dict[str, Any] = {}
    if config.bgcolor:
        hoverlabel_dict["bgcolor"] = config.bgcolor
    if config.bordercolor:
        hoverlabel_dict["bordercolor"] = config.bordercolor
    if config.font_size or config.font_color:
        hoverlabel_dict["font"] = {}
        if config.font_size:
            hoverlabel_dict["font"]["size"] = config.font_size
        if config.font_color:
            hoverlabel_dict["font"]["color"] = config.font_color
    if config.align:
        hoverlabel_dict["align"] = config.align

    if hoverlabel_dict:
        layout_dict["hoverlabel"] = hoverlabel_dict

    if layout_dict:
        fig.update_layout(**layout_dict)

    # Apply hover template to traces
    if config.template:
        for trace in fig.data:
            trace.update(hovertemplate=config.template)


# =============================================================================
# Main Application Function
# =============================================================================


def apply_customizations(
    fig: go.Figure,
    customizations: Union[FigureCustomizations, Dict[str, Any]],
    df: Optional[pd.DataFrame] = None,
) -> go.Figure:
    """
    Apply customizations to a Plotly figure.

    This is the main entry point for the customization system. It takes
    a figure and a customization configuration, and returns the modified
    figure.

    Args:
        fig: The Plotly figure to customize
        customizations: Either a FigureCustomizations object or a dict
                       that can be converted to one
        df: Optional DataFrame for data-dependent customizations like
            highlighting (required for highlight feature)

    Returns:
        The modified figure (same object, modified in place)

    Example:
        >>> import plotly.express as px
        >>> from depictio.dash.modules.figure_component.customizations import (
        ...     apply_customizations,
        ...     FigureCustomizations,
        ... )
        >>>
        >>> fig = px.scatter(df, x="x", y="y")
        >>> customizations = FigureCustomizations(
        ...     axes=AxesConfig(
        ...         x=AxisConfig(scale=AxisScale.LOG, title="Log X"),
        ...         y=AxisConfig(range=[0, 100]),
        ...     ),
        ...     reference_lines=[
        ...         ReferenceLineConfig(
        ...             type=ReferenceLineType.HLINE,
        ...             y=0.05,
        ...             line_color="red",
        ...             line_dash=LineStyle.DASH,
        ...             annotation_text="p=0.05",
        ...         ),
        ...     ],
        ... )
        >>> fig = apply_customizations(fig, customizations)
    """
    # Convert dict to FigureCustomizations if needed
    if isinstance(customizations, dict):
        try:
            customizations = FigureCustomizations.model_validate(customizations)
        except Exception as e:
            logger.error(f"Failed to parse customizations dict: {e}")
            return fig

    # Check if there are any customizations
    if not customizations.has_customizations():
        return fig

    logger.debug("Applying figure customizations")

    try:
        # Apply axes configuration
        if customizations.axes:
            _apply_axes(fig, customizations.axes)

        # Apply reference lines
        if customizations.reference_lines:
            for ref_line in customizations.reference_lines:
                _apply_reference_line(fig, ref_line)

        # Apply highlights (requires DataFrame)
        if customizations.highlights:
            _apply_highlights(fig, customizations.highlights, df)

        # Apply annotations
        if customizations.annotations:
            _apply_annotations(fig, customizations.annotations)

        # Apply shapes
        if customizations.shapes:
            _apply_shapes(fig, customizations.shapes)

        # Apply legend configuration
        if customizations.legend:
            _apply_legend(fig, customizations.legend)

        # Apply colorbar configuration
        if customizations.colorbar:
            _apply_colorbar(fig, customizations.colorbar)

        # Apply hover configuration
        if customizations.hover:
            _apply_hover(fig, customizations.hover)

        # Apply raw layout overrides (advanced)
        if customizations.layout_overrides:
            fig.update_layout(**customizations.layout_overrides)

        # Apply raw trace overrides (advanced)
        if customizations.trace_overrides:
            fig.update_traces(**customizations.trace_overrides)

        logger.debug("Successfully applied all customizations")

    except Exception as e:
        logger.error(f"Error applying customizations: {e}", exc_info=True)
        # Return the figure even if customizations failed partially

    return fig
