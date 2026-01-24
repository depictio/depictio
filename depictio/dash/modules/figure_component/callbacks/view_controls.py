"""
View mode controls for interactive figure customization.

This module provides collapsible control panels for adjusting figure
customizations (reference lines, axis scales) in view/edit mode after
components have been saved to dashboards.

Key features:
- Collapsible control panel positioned as overlay (top-right)
- Reference line sliders with auto-calculated bounds
- Axis scale toggles (linear/log)
- Theme-aware DMC 2.0+ components
- Pattern-matching callbacks for multi-figure support
- Integration with batch rendering system
"""

from typing import Any, Dict, List, Optional, Tuple

import dash_mantine_components as dmc
from dash import Input, Output, State, clientside_callback, dcc, html
from dash.dependencies import ALL, MATCH

from depictio.models.logging import logger

# =============================================================================
# Layout Builders
# =============================================================================


def wrap_figure_with_controls(
    graph_component: dcc.Graph,
    index: str,
    customization_ui_state: Dict[str, Any],
    default_axis_ranges: Dict[str, Tuple[float, float]],
) -> html.Div:
    """
    Wrap a figure component with interactive controls for view mode.

    Creates a collapsible control panel with:
    - Toggle button (top-right, outside graph area)
    - Axis scale controls (linear/log)
    - Reference line sliders (if show_slider=True)

    Args:
        graph_component: The dcc.Graph component to wrap
        index: Unique component index
        customization_ui_state: UI state dict with scale_control and reference_line_controls
        default_axis_ranges: Default axis ranges {"x": (min, max), "y": (min, max)}

    Returns:
        html.Div containing graph + control panel + toggle button
    """
    # Validate input
    if not customization_ui_state or not isinstance(customization_ui_state, dict):
        logger.warning(f"Invalid customization_ui_state for figure {index}")
        return graph_component

    # Extract control configurations
    scale_config = customization_ui_state.get("scale_control")
    refline_controls = customization_ui_state.get("reference_line_controls", [])

    logger.info(
        f"🎛️  Controls check for {index}: scale={bool(scale_config)}, "
        f"reflines={len(refline_controls)}, "
        f"sliders_enabled={[rl.get('show_slider', False) for rl in refline_controls]}"
    )

    # If no controls to show, return unwrapped graph
    has_controls = bool(scale_config) or any(
        rl.get("show_slider", False) for rl in refline_controls
    )
    if not has_controls:
        logger.warning(f"🎛️  No controls to show for {index} - returning unwrapped graph")
        return graph_component

    logger.info(f"🎛️  Building controls UI for {index}")

    # Build control panel content
    control_sections = []

    # Section 1: Axis scale controls
    if scale_config and scale_config.get("enabled"):
        control_sections.append(_build_scale_control(index, scale_config))

    # Section 2: Reference line sliders
    refline_sliders = _build_refline_sliders(index, refline_controls, default_axis_ranges)
    if refline_sliders:
        control_sections.append(refline_sliders)

    logger.info(
        f"🎛️  Controls built successfully for {index}. "
        f"Sections: {len(control_sections)}, Creating wrapper with tune icon..."
    )

    # Debug: Log the IDs that will be created
    logger.info(f"🎛️  Creating stores with index: {index}")
    logger.info(
        f"🎛️  - controls-panel-visible: {{'type': 'controls-panel-visible', 'index': '{index}'}}"
    )
    logger.info(
        f"🎛️  - controls-panel-container: {{'type': 'controls-panel-container', 'index': '{index}'}}"
    )
    logger.info(f"🎛️  - toggle-controls-btn: {{'type': 'toggle-controls-btn', 'index': '{index}'}}")

    # Build complete layout
    # NOTE: Toggle button is now in the ActionIcon group (edit.py), not overlaid on the graph
    return html.Div(
        style={"position": "relative", "width": "100%", "height": "100%"},
        children=[
            # Original graph component (full width/height)
            graph_component,
            # Store for panel visibility state
            dcc.Store(
                id={"type": "controls-panel-visible", "index": index},
                data=False,  # Initially hidden
            ),
            # Control panel container (collapsible)
            html.Div(
                id={"type": "controls-panel-container", "index": index},
                style={"display": "none"},  # Hidden by default
                children=[
                    dmc.Paper(
                        shadow="lg",
                        p="xs",  # Extra small padding for very compact display
                        withBorder=True,
                        radius="md",
                        style={
                            "position": "absolute",
                            "top": "4px",  # Closer to top
                            "right": "4px",  # Closer to edge
                            "width": "240px",  # Even narrower
                            "maxHeight": "300px",  # Smaller max height
                            "overflowY": "auto",
                            "overflowX": "hidden",  # Prevent horizontal overflow
                            "zIndex": 1001,  # Higher z-index to ensure visibility
                        },
                        children=[
                            dmc.Stack(
                                gap="xs",  # Extra small gap
                                children=control_sections,
                            )
                        ],
                    )
                ],
            ),
        ],
    )


def _build_scale_control(index: str, scale_config: Dict[str, Any]) -> dmc.Stack:
    """Build axis scale control (linear/log toggle)."""
    axis = scale_config.get("axis", "y")
    current_scale = scale_config.get("current_scale", "linear")

    return dmc.Stack(
        gap="xs",
        children=[
            dmc.Text(
                f"{axis.upper()}-Axis Scale",
                size="sm",
                fw=500,
                # No custom styling - let DMC theme handle colors
            ),
            dmc.SegmentedControl(
                id={"type": "axis-scale-control", "index": index},
                data=[
                    {"value": "linear", "label": "Linear"},
                    {"value": "log", "label": "Log"},
                ],
                value=current_scale,
                fullWidth=True,
            ),
        ],
    )


def _build_refline_sliders(
    index: str,
    refline_controls: List[Dict[str, Any]],
    axis_ranges: Dict[str, Tuple[float, float]],
) -> Optional[dmc.Stack]:
    """Build reference line slider controls."""
    sliders = []

    for idx, line_control in enumerate(refline_controls):
        # Only create slider if show_slider is True
        if not line_control.get("show_slider", False):
            continue

        line_type = line_control.get("type", "hline")
        current_value = line_control.get("current_value", 0)

        # Calculate slider bounds
        slider_min, slider_max, step = _calculate_slider_bounds(
            line_control, axis_ranges, line_type
        )

        # Clamp current value to bounds
        current_value = max(slider_min, min(slider_max, current_value))

        # Determine axis label
        axis_label = "Y" if line_type == "hline" else "X"

        sliders.append(
            dmc.Stack(
                gap="xs",
                children=[
                    dmc.Group(
                        justify="space-between",
                        children=[
                            dmc.Text(
                                f"{axis_label}-Axis Line {idx + 1}",
                                size="sm",
                                fw=500,
                                # No custom styling - let DMC theme handle colors
                            ),
                            dmc.Text(
                                id={"type": "refline-value", "index": index, "line_idx": idx},
                                children=f"{current_value:.2f}",
                                size="xs",
                                c="dimmed",  # DMC's dimmed color - theme aware
                            ),
                        ],
                    ),
                    dmc.Slider(
                        id={"type": "refline-slider", "index": index, "line_idx": idx},
                        value=current_value,
                        min=slider_min,
                        max=slider_max,
                        step=step,
                        size="sm",  # Smaller slider size
                        # No marks - keeps it compact, value shown above
                    ),
                ],
            )
        )

    if not sliders:
        return None

    return dmc.Stack(
        gap="md",
        children=[
            dmc.Divider(label="Reference Lines", labelPosition="center"),
            *sliders,
        ],
    )


def _calculate_slider_bounds(
    line_control: Dict[str, Any],
    axis_ranges: Dict[str, Tuple[float, float]],
    line_type: str,
) -> Tuple[float, float, float]:
    """
    Calculate appropriate min/max/step for reference line slider.

    Args:
        line_control: Line control configuration
        axis_ranges: Axis ranges {"x": (min, max), "y": (min, max)}
        line_type: "hline" or "vline"

    Returns:
        Tuple of (min, max, step)
    """
    current_value = line_control.get("current_value", 0)

    # Determine which axis range to use
    axis = "y" if line_type == "hline" else "x"
    axis_min, axis_max = axis_ranges.get(axis, (0, 100))

    # If axis range is invalid, use sensible defaults around current value
    if axis_min >= axis_max or axis_min == 0 and axis_max == 100:
        # Fallback: create range around current value
        if current_value == 0:
            slider_min, slider_max = 0, 100
        else:
            # Range from 0 to 2x current value
            slider_min = 0
            slider_max = current_value * 2
    else:
        # Use axis range with 10% padding
        range_size = axis_max - axis_min
        padding = range_size * 0.1
        slider_min = axis_min - padding
        slider_max = axis_max + padding

    # Calculate appropriate step size (1% of range)
    range_size = slider_max - slider_min
    step = range_size / 100

    # Ensure step is reasonable
    step = max(step, 0.01)

    # Ensure min < max
    if slider_min >= slider_max:
        slider_min = 0
        slider_max = 100
        step = 1

    return slider_min, slider_max, step


# =============================================================================
# Callback Registration
# =============================================================================

# Track if view control callbacks have been registered
_view_control_callbacks_registered = False


def register_view_control_callbacks(app):
    """
    Register all view mode control callbacks.

    Includes:
    - Clientside toggle callback (show/hide panel)
    - Axis scale control callback (update scale)
    - Reference line slider callback (update position)

    Returns:
        bool: True if callbacks were registered, False if already registered
    """
    global _view_control_callbacks_registered

    if _view_control_callbacks_registered:
        logger.debug("View control callbacks already registered, skipping duplicate registration")
        return False

    logger.info("Registering view control callbacks for figure component")
    _register_toggle_callback(app)
    _register_scale_callback(app)
    _register_refline_callback(app)
    _register_refline_value_display_callback(app)

    _view_control_callbacks_registered = True
    logger.info("View control callbacks registered successfully")
    return True


def _register_toggle_callback(app):
    """Register clientside callback to toggle control panel visibility."""
    logger.info("📝 Registering toggle callback for controls-panel-visible")

    # TEMPORARY DEBUG: Server-side callback to verify button clicks are detected
    @app.callback(
        Output({"type": "controls-panel-visible", "index": MATCH}, "data"),
        Input({"type": "toggle-controls-btn", "index": MATCH}, "n_clicks"),
        State({"type": "controls-panel-visible", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def debug_toggle_controls(n_clicks, current_visible):
        """Debug callback to test if button clicks are detected."""
        from dash import ctx

        logger.warning(
            f"🔥 DEBUG: Toggle button clicked! n_clicks={n_clicks}, current={current_visible}"
        )
        logger.warning(f"🔥 DEBUG: Triggered by: {ctx.triggered_id}")
        new_state = not current_visible
        logger.warning(f"🔥 DEBUG: Setting visibility to: {new_state}")
        return new_state

    # Companion callback to update container display based on visibility state
    # TEMPORARY DEBUG: Server-side callback
    @app.callback(
        Output({"type": "controls-panel-container", "index": MATCH}, "style"),
        Input({"type": "controls-panel-visible", "index": MATCH}, "data"),
    )
    def debug_update_panel_style(is_visible):
        """Debug callback to update panel visibility."""
        from dash import ctx

        logger.warning(f"🔥 DEBUG STYLE: Updating panel style, is_visible={is_visible}")
        logger.warning(f"🔥 DEBUG STYLE: Triggered by: {ctx.triggered_id}")
        style = {} if is_visible else {"display": "none"}
        logger.warning(f"🔥 DEBUG STYLE: Returning style: {style}")
        return style


def _register_scale_callback(app):
    """Register callback to update axis scale when user changes control."""

    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True),
        Output({"type": "figure-trigger", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "axis-scale-control", "index": MATCH}, "value"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        State({"type": "figure-trigger", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_axis_scale(
        scale_value: str, stored_metadata: Dict[str, Any], current_trigger: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Update axis scale in customizations when user changes scale control.

        This updates the stored metadata, which triggers the batch rendering
        callback to re-render the figure with the new scale.
        """
        if not stored_metadata or not scale_value:
            logger.warning("Missing stored_metadata or scale_value in scale callback")
            from dash import no_update

            return stored_metadata or {}, no_update

        try:
            # Extract current customizations
            customizations = stored_metadata.get("customizations", {})
            axes = customizations.get("axes", {})

            # Determine which axis to update from customization_ui_state
            customization_ui_state = stored_metadata.get("customization_ui_state", {})
            scale_config = customization_ui_state.get("scale_control", {})
            axis = scale_config.get("axis", "y")

            # Update axis scale
            if axis not in axes:
                axes[axis] = {}
            axes[axis]["scale"] = scale_value

            # Update customizations
            customizations["axes"] = axes
            stored_metadata["customizations"] = customizations

            # Also update UI state to track current scale
            scale_config["current_scale"] = scale_value
            customization_ui_state["scale_control"] = scale_config
            stored_metadata["customization_ui_state"] = customization_ui_state

            # Update trigger to force re-render
            import time

            new_trigger = current_trigger or {}
            new_trigger["timestamp"] = time.time()
            new_trigger["source"] = "axis_scale"

            logger.debug(f"Updated axis scale for {axis}-axis to {scale_value}")
            return stored_metadata, new_trigger

        except Exception as e:
            logger.error(f"Error updating axis scale: {e}")
            from dash import no_update

            return stored_metadata, no_update


def _register_refline_callback(app):
    """Register callback to update reference line positions from sliders."""

    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True),
        Output({"type": "figure-trigger", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "refline-slider", "index": MATCH, "line_idx": ALL}, "value"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        State({"type": "figure-trigger", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_refline_positions(
        slider_values: List[Optional[float]],
        stored_metadata: Dict[str, Any],
        current_trigger: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Update reference line positions when user adjusts sliders.

        This updates the stored metadata, which triggers the batch rendering
        callback to re-render the figure with updated reference lines.
        """
        from dash import ctx

        logger.warning(f"🔥 SLIDER CALLBACK: Fired! slider_values={slider_values}")
        logger.warning(f"🔥 SLIDER CALLBACK: Triggered by: {ctx.triggered_id}")

        if not stored_metadata or not slider_values:
            logger.warning("Missing stored_metadata or slider_values in refline callback")
            from dash import no_update

            return stored_metadata or {}, no_update

        try:
            # Extract current customizations
            customizations = stored_metadata.get("customizations", {})
            reference_lines = customizations.get("reference_lines", [])

            # Also get UI state to track which lines have sliders
            customization_ui_state = stored_metadata.get("customization_ui_state", {})
            refline_controls = customization_ui_state.get("reference_line_controls", [])

            # Update positions for lines with sliders
            slider_idx = 0
            for line_idx, line in enumerate(reference_lines):
                # Check if this line has a slider
                if line_idx < len(refline_controls):
                    control = refline_controls[line_idx]
                    if control.get("show_slider", False):
                        if (
                            slider_idx < len(slider_values)
                            and slider_values[slider_idx] is not None
                        ):
                            new_value = slider_values[slider_idx]

                            # Update the appropriate position field (y for hline, x for vline)
                            line_type = line.get("type", "hline")
                            if line_type == "hline":
                                line["y"] = new_value
                            else:  # vline
                                line["x"] = new_value

                            # Update UI state current_value
                            refline_controls[line_idx]["current_value"] = new_value

                            logger.warning(
                                f"🔥 SLIDER: Updated {line_type} line {line_idx}: "
                                f"{'y' if line_type == 'hline' else 'x'}={new_value}"
                            )

                        slider_idx += 1

            # Update customizations
            customizations["reference_lines"] = reference_lines
            stored_metadata["customizations"] = customizations

            # Update UI state
            customization_ui_state["reference_line_controls"] = refline_controls
            stored_metadata["customization_ui_state"] = customization_ui_state

            # Update trigger to force re-render
            import time

            new_trigger = current_trigger or {}
            new_trigger["timestamp"] = time.time()
            new_trigger["source"] = "refline_slider"

            logger.warning("🔥 SLIDER: Returning updated metadata + trigger, forcing batch render")
            return stored_metadata, new_trigger

        except Exception as e:
            logger.error(f"Error updating reference line positions: {e}")
            from dash import no_update

            return stored_metadata, no_update


def _register_refline_value_display_callback(app):
    """Register clientside callback to update slider value displays."""
    clientside_callback(
        """
        function(slider_value) {
            if (slider_value === null || slider_value === undefined) {
                return window.dash_clientside.no_update;
            }
            return slider_value.toFixed(2);
        }
        """,
        Output({"type": "refline-value", "index": MATCH, "line_idx": MATCH}, "children"),
        Input({"type": "refline-slider", "index": MATCH, "line_idx": MATCH}, "value"),
        prevent_initial_call=True,
    )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "wrap_figure_with_controls",
    "register_view_control_callbacks",
]
