"""
Figure Component - Render Callbacks

This module contains callbacks for rendering figure previews during design/creation mode.
These callbacks listen to parameter changes and update the figure preview in real-time.
"""

import dash
from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


def register_render_callbacks(app):
    """Register figure rendering callbacks for preview mode."""

    @app.callback(
        Output({"type": "figure-design-preview", "index": MATCH}, "figure"),
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            Input({"type": "reflines-store", "index": MATCH}, "data"),
            Input({"type": "highlights-store", "index": MATCH}, "data"),
            Input({"type": "axis-scale-x", "index": MATCH}, "value"),
            Input({"type": "axis-scale-y", "index": MATCH}, "value"),
        ],
        [
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
            State({"type": "figure-design-preview", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("theme-store", "data"),
        ],
        prevent_initial_call=True,
        background=True,  # CRITICAL: Must use background to prevent UI blocking during render
    )
    def render_figure_preview(
        dict_kwargs,
        visu_type,
        reflines_data,
        highlights_data,
        axis_scale_x,
        axis_scale_y,
        workflow,
        data_collection,
        metadata,
        graph_id,
        local_data,
        theme_data,
    ):
        """
        Render figure preview when parameters change.

        This callback fires when:
        1. Parameters change in dict_kwargs store (user selects x, y, color, etc.)
        2. Visualization type changes

        It loads the data and generates a Plotly figure for preview.

        NOTE: Runs in background via Celery, so all imports must be inside function.
        """
        if not local_data:
            raise dash.exceptions.PreventUpdate

        # Skip if no visualization type selected yet
        if not visu_type:
            logger.info("🚫 RENDER: No visualization type selected")
            raise dash.exceptions.PreventUpdate

        logger.info("=" * 80)
        logger.info(f"📁 Workflow: {workflow}")
        logger.info(f"📁 Data Collection: {data_collection}")
        logger.info("=" * 80)

        try:
            # Import dependencies
            from depictio.api.v1.deltatables_utils import load_deltatable_lite
            from depictio.dash.modules.figure_component.utils import render_figure

            TOKEN = local_data["access_token"]

            # Get workflow and data collection IDs from metadata if not provided
            wf_id = workflow or (metadata.get("wf_id") if metadata else None)
            dc_id = data_collection or (metadata.get("dc_id") if metadata else None)

            if not wf_id or not dc_id:
                logger.warning("🚫 RENDER: Missing workflow or data collection ID")
                return {}

            # Load data
            df = load_deltatable_lite(workflow_id=wf_id, data_collection_id=dc_id, TOKEN=TOKEN)

            if df is None or df.height == 0:
                logger.warning("🚫 RENDER: No data loaded")
                return {}

            # Extract theme from theme_data
            current_theme = "light"  # Default
            if theme_data and isinstance(theme_data, dict):
                current_theme = theme_data.get("theme", "light")
            elif isinstance(theme_data, str):
                current_theme = theme_data

            # Build customizations from stores
            customizations = {}

            # Add axis scales
            if axis_scale_x or axis_scale_y:
                customizations["axes"] = {}
                if axis_scale_x and axis_scale_x != "linear":
                    customizations["axes"]["x"] = {"scale": axis_scale_x}
                if axis_scale_y and axis_scale_y != "linear":
                    customizations["axes"]["y"] = {"scale": axis_scale_y}

            # Add reference lines
            if reflines_data and isinstance(reflines_data, list):
                customizations["reference_lines"] = []
                for line in reflines_data:
                    line_config = {
                        "type": line.get("type", "hline"),
                        "line_color": line.get("color", "red"),
                        "line_dash": line.get("dash", "dash"),
                        "line_width": line.get("width", 2),
                    }
                    # Add position based on line type
                    if line.get("type") == "hline":
                        line_config["y"] = line.get("position", 0)
                    else:  # vline
                        line_config["x"] = line.get("position", 0)

                    # Add annotation if present and not empty
                    if line.get("annotation") and line.get("annotation").strip():
                        line_config["annotation_text"] = line.get("annotation")

                    customizations["reference_lines"].append(line_config)

            # Add highlights
            if highlights_data and isinstance(highlights_data, list):
                customizations["highlights"] = []
                for hl in highlights_data:
                    if not hl.get("column"):
                        continue  # Skip highlights without column selection

                    # Map condition to operator
                    condition_map = {
                        "equals": "eq",
                        "greater than": "gt",
                        "less than": "lt",
                        "contains": "contains",
                    }
                    operator = condition_map.get(hl.get("condition", "equals"), "eq")

                    # Build style dict with type safety
                    style_dict = {
                        "marker_color": hl.get("color", "red"),
                        "marker_size": hl.get("size", 12),
                        "dim_opacity": 0.3,
                    }

                    # Add outline if specified
                    if hl.get("outline"):
                        style_dict["marker_line_color"] = hl.get("outline")
                        style_dict["marker_line_width"] = 2

                    highlight_config = {
                        "conditions": [
                            {
                                "column": hl.get("column", ""),
                                "operator": operator,
                                "value": hl.get("value", ""),
                            }
                        ],
                        "logic": "and",
                        "style": style_dict,
                    }

                    customizations["highlights"].append(highlight_config)

            # Render figure
            try:
                figure, trace_metadata = render_figure(
                    dict_kwargs=dict_kwargs or {},
                    visu_type=visu_type,
                    df=df,
                    theme=current_theme,
                    customizations=customizations if customizations else None,
                )
                return figure
            except Exception as render_error:
                logger.error(f"❌ RENDER: render_figure failed: {render_error}")
                raise  # Re-raise to outer exception handler

        except Exception as e:
            logger.error(f"❌ RENDER ERROR: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")

            # Return empty figure with error message
            return {
                "data": [],
                "layout": {
                    "title": f"Error: {str(e)}",
                    "annotations": [
                        {
                            "text": f"Failed to render figure:<br>{str(e)}",
                            "xref": "paper",
                            "yref": "paper",
                            "showarrow": False,
                            "font": {"size": 14, "color": "red"},
                        }
                    ],
                },
            }
