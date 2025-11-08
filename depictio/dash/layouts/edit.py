import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
from dash import html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.header import _is_different_from_default
from depictio.dash.layouts.stepper import create_stepper_output_edit
from depictio.dash.utils import get_component_data


def register_partial_data_button_callbacks(app):
    """Register callbacks to update partial data warning popover content with real counts."""

    # NOTE: The popover content update callback has been moved to frontend.py
    # (update_partial_data_popover_from_interactive) to avoid duplicate callbacks
    # and ensure it's closer to the data source for better synchronization.
    #
    # @app.callback(
    #     Output({"type": "partial-data-popover-content", "index": MATCH}, "children"),
    #     Input({"type": "stored-metadata-component", "index": MATCH}, "data"),
    #     State({"type": "partial-data-popover-content", "index": MATCH}, "id"),
    #     prevent_initial_call=False,
    # )
    # def update_partial_data_popover(metadata, component_id):
    #     """Update the partial data warning popover with actual data counts."""
    #     from dash import callback_context
    #
    #     from depictio.dash.modules.figure_component.utils import ComponentConfig
    #
    #     config = ComponentConfig()
    #     cutoff = config.max_data_points
    #
    #     # Extract counts from metadata
    #     displayed_count = cutoff
    #     total_count = cutoff
    #     was_sampled = False
    #
    #     if metadata:
    #         displayed_count = metadata.get("displayed_data_count", cutoff)
    #         total_count = metadata.get("total_data_count", cutoff)
    #         was_sampled = metadata.get("was_sampled", False)
    #
    #     # Get component index for logging
    #     ctx = callback_context
    #     trigger = ctx.triggered[0]["prop_id"] if ctx.triggered else "initial"
    #     component_index = component_id.get("index", "unknown") if component_id else "unknown"
    #
    #     logger.info(
    #         f"📊 [{component_index}] Popover update triggered by: {trigger}, data: displayed={displayed_count:,}, total={total_count:,}, sampled={was_sampled}"
    #     )
    #
    #     # Create updated children - include values in keys to force React re-render
    #     updated_children = html.Div(
    #         [
    #             html.Div(
    #                 f"Showing: {displayed_count:,} points",
    #                 key=f"showing-{component_index}-{displayed_count}",
    #             ),
    #             html.Div(
    #                 f"Total: {total_count:,} points", key=f"total-{component_index}-{total_count}"
    #             ),
    #             html.Div(
    #                 "Full dataset available for analysis",
    #                 style={"marginTop": "8px", "fontStyle": "italic", "fontSize": "0.9em"},
    #                 key=f"footer-{component_index}",
    #             ),
    #         ],
    #         key=f"content-wrapper-{component_index}-{displayed_count}-{total_count}",
    #     )
    #
    #     logger.info(
    #         f"📊 [{component_index}] Returning updated children to partial-data-popover-content"
    #     )
    #
    #     return updated_children

    # Server-side callback to control button wrapper visibility
    # DISABLED FOR PERFORMANCE TESTING - Phase 4C
    # This callback was being triggered frequently, contributing to overhead
    # @app.callback(
    #     Output({"type": "partial-data-button-wrapper", "index": MATCH}, "style"),
    #     Input({"type": "stored-metadata-component", "index": MATCH}, "data"),
    #     State({"type": "partial-data-button-wrapper", "index": MATCH}, "id"),
    #     prevent_initial_call=False,
    # )
    # def update_partial_data_button_visibility(metadata, wrapper_id):
    #     """Show/hide the partial data warning button based on whether data was sampled."""
    #     # Default: hidden
    #     hidden_style = {"display": "none", "visibility": "hidden"}
    #     visible_style = {"display": "inline-flex", "visibility": "visible"}
    #
    #     if not metadata:
    #         logger.info("📊 No metadata yet, keeping button hidden")
    #         return hidden_style
    #
    #     # Extract sampling information
    #     was_sampled = metadata.get("was_sampled", False)
    #     displayed_count = metadata.get("displayed_data_count", 0)
    #     total_count = metadata.get("total_data_count", 0)
    #
    #     # Show button only if data was actually sampled
    #     should_show = was_sampled and (displayed_count < total_count)
    #
    #     component_index = wrapper_id.get("index", "unknown") if wrapper_id else "unknown"
    #
    #     logger.info(
    #         f"📊 [{component_index}] Button visibility: sampled={was_sampled}, "
    #         f"displayed={displayed_count:,}, total={total_count:,}, show={should_show}"
    #     )
    #
    #     return visible_style if should_show else hidden_style
    pass  # Placeholder to keep function structure valid


def register_reset_button_callbacks(app):
    """
    Register callbacks to update reset button colors based on filter activity.

    ⚠️ TEMPORARILY DISABLED FOR DEBUGGING
    """
    logger.info("⚠️ Reset button callback DISABLED for debugging")
    pass


def _check_component_filter_activity(interactive_values, component_index):
    """Check if a specific component has active filters."""
    logger.info(f"🔍 _check_component_filter_activity for component {component_index}")

    if not interactive_values:
        logger.info("📭 No interactive_values provided")
        return False

    # Handle different possible structures in interactive_values
    interactive_values_data = []

    if "interactive_components_values" in interactive_values:
        interactive_values_data = interactive_values["interactive_components_values"]
        logger.info(f"📦 Found interactive_components_values: {len(interactive_values_data)} items")
    elif isinstance(interactive_values, dict):
        # Look for any values that might be interactive components
        for key, value in interactive_values.items():
            if isinstance(value, dict) and "value" in value:
                interactive_values_data.append(value)
        logger.info(f"📦 Extracted from dict structure: {len(interactive_values_data)} items")

    if not interactive_values_data:
        logger.info("📭 No interactive component data found")
        return False

    logger.info(
        f"🔍 Searching for component {component_index} among {len(interactive_values_data)} components"
    )

    # Find the specific component by index
    for i, component_data in enumerate(interactive_values_data):
        if isinstance(component_data, dict):
            component_metadata = component_data.get("metadata", {})
            component_id = component_metadata.get("index")

            logger.info(f"  Component {i}: ID={component_id}, looking for {component_index}")

            # Check if this is the component we're looking for
            if str(component_id) == str(component_index):
                component_value = component_data.get("value")
                default_state = component_metadata.get("default_state", {})

                logger.info(f"  ✅ Found target component {component_index}")
                logger.info(f"    Current value: {component_value}")
                logger.info(f"    Default state: {default_state}")

                if component_value is None or not default_state:
                    logger.info("  ❌ No value or default_state, returning False")
                    return False

                # Use the same logic as the header reset button
                is_different = _is_different_from_default(component_value, default_state)
                logger.info(f"  🎯 Is different from default: {is_different}")
                return is_different

    logger.info(f"❌ Component {component_index} not found in interactive values")
    return False


# REMOVED: Position menu functions (_create_position_menu_vertical and _create_position_menu_grid)
# Replaced with drag & drop using DashGridLayout for all component positioning
# Components now use drag handles instead of button-based position controls


def _create_component_buttons(
    component_type,
    component_data,
    btn_index,
    create_drag_handle,
    create_remove_button,
    create_edit_button,
    create_duplicate_button,
    create_reset_button,
    create_alignment_button=None,
    create_metadata_button=None,
    create_partial_data_warning_button=None,
):
    """Create action buttons based on component type and configuration.

    Returns:
        tuple: (edit_buttons_group, view_buttons_group)
            - edit_buttons_group: ActionIconGroup with edit-only buttons (hidden in view mode)
            - view_buttons_group: ActionIconGroup with view-accessible buttons (always visible)
    """
    # Define button configurations for different component types
    # Buttons are categorized:
    # - edit_only: drag, duplicate, edit, remove, alignment (hidden in view mode)
    # - view_accessible: reset, metadata, partial_data (visible in view mode)

    button_configs = {
        "figure": {
            "orientation": "vertical",
            "edit_only": ["drag", "duplicate", "edit", "remove"],
            "view_accessible": ["metadata"],
            "scatter_edit_only": ["partial_data", "drag", "duplicate", "edit", "remove"],
            "scatter_view_accessible": ["metadata", "reset"],
        },
        "interactive": {
            "orientation": "horizontal",
            "edit_only": ["drag", "duplicate", "edit", "remove"],
            "view_accessible": ["metadata", "reset"],
        },
        "card": {
            "orientation": "horizontal",
            "edit_only": ["drag", "duplicate", "edit", "remove"],
            "view_accessible": ["metadata"],
        },
        "table": {
            "orientation": "horizontal",
            "edit_only": ["drag", "remove"],
            "view_accessible": ["metadata"],
        },
        "jbrowse": {
            "orientation": "horizontal",
            "edit_only": ["drag", "remove"],
            "view_accessible": ["metadata"],
        },
        "multiqc": {
            "orientation": "vertical",
            "edit_only": ["drag", "remove"],
            "view_accessible": ["metadata"],
        },
        "text": {
            "orientation": "horizontal",
            "edit_only": ["drag", "duplicate", "alignment", "remove"],
            "view_accessible": ["metadata"],
        },
        "default": {
            "orientation": "horizontal",
            "edit_only": ["drag", "remove"],
            "view_accessible": ["metadata"],
        },
    }

    # Get configuration for this component type
    config = button_configs.get(component_type, button_configs["default"])

    # Special handling for scatter plot figures
    if component_type == "figure":
        visu_type = component_data.get("visu_type", None) if component_data else None
        if visu_type and visu_type.lower() == "scatter":
            edit_only_list = config.get("scatter_edit_only", config["edit_only"])
            view_accessible_list = config.get("scatter_view_accessible", config["view_accessible"])
        else:
            edit_only_list = config["edit_only"]
            view_accessible_list = config["view_accessible"]
    else:
        edit_only_list = config["edit_only"]
        view_accessible_list = config["view_accessible"]

    # Map button names to functions
    button_functions = {
        "drag": create_drag_handle,
        "remove": create_remove_button,
        "edit": create_edit_button,
        "duplicate": create_duplicate_button,
        "reset": create_reset_button,
    }

    # Add alignment button only if the function is provided
    if create_alignment_button is not None:
        button_functions["alignment"] = create_alignment_button

    # Add metadata button only if the function is provided
    if create_metadata_button is not None:
        button_functions["metadata"] = create_metadata_button

    # Add partial data warning button only if the function is provided
    if create_partial_data_warning_button is not None:
        button_functions["partial_data"] = create_partial_data_warning_button

    # Create edit-only button components
    edit_only_components = [
        button_functions[btn]() for btn in edit_only_list if btn in button_functions
    ]

    # Create view-accessible button components
    view_accessible_components = [
        button_functions[btn]() for btn in view_accessible_list if btn in button_functions
    ]

    # Log configuration for debugging
    if component_type:
        logger.debug(
            f"Creating {config['orientation']} buttons for {component_type}:"
            f"\n  Edit-only: {edit_only_list}"
            f"\n  View-accessible: {view_accessible_list}"
        )

    # Return both button groups
    edit_buttons_group = (
        dmc.ActionIconGroup(edit_only_components, orientation=config["orientation"])
        if edit_only_components
        else None
    )
    view_buttons_group = (
        dmc.ActionIconGroup(view_accessible_components, orientation=config["orientation"])
        if view_accessible_components
        else None
    )

    return edit_buttons_group, view_buttons_group


def edit_component(index, parent_id, active=0, component_data=None, TOKEN=None):
    logger.info("=== EDIT COMPONENT ===")
    logger.info("Function parameters:")
    logger.info(f"  index: {index}")
    logger.info(f"  parent_id: {parent_id}")
    logger.info(f"  active: {active}")
    logger.info(f"  component_data type: {type(component_data)}")
    logger.info(f"  component_data: {component_data}")
    logger.info(f"  TOKEN: {'***' if TOKEN else None}")

    current_draggable_children = create_stepper_output_edit(
        index, parent_id, active, component_data, TOKEN
    )

    return current_draggable_children


def enable_box_edit_mode(
    box,
    switch_state=True,
    dashboard_id=None,
    fresh=False,
    component_data=dict(),
    TOKEN=None,
):
    # Extract component ID from native Dash component or JSON
    def extract_component_id(component):
        """Extract component ID from native Dash component or JSON representation."""
        # Handle native Dash components
        if hasattr(component, "id") and component.id:
            if isinstance(component.id, dict) and "index" in component.id:
                return component.id["index"]
            elif isinstance(component.id, str):
                return component.id

        # Handle JSON representation (legacy)
        if isinstance(component, dict) and "props" in component:
            try:
                return component["props"]["id"]["index"]
            except (KeyError, TypeError):
                pass

        # Fallback: generate a unique index
        import uuid

        fallback_id = str(uuid.uuid4())
        logger.warning(f"Component missing id, generated fallback: {fallback_id}")
        return fallback_id

    # Prioritize component_data index if available, otherwise extract from component
    if component_data and "index" in component_data:
        btn_index = component_data["index"]
        logger.debug(f"ENABLE BOX EDIT MODE - Using index from component_data: {btn_index}")
    else:
        btn_index = extract_component_id(box)
        logger.debug(f"ENABLE BOX EDIT MODE - Extracted index from component: {btn_index}")

    component_type = None
    if not component_data:
        if dashboard_id and TOKEN:
            component_data = get_component_data(
                input_id=btn_index, dashboard_id=dashboard_id, TOKEN=TOKEN
            )
            if component_data:
                component_type = component_data.get("component_type", None)
    else:
        component_type = component_data.get("component_type", None)

    def create_drag_handle():
        return dmc.ActionIcon(
            id={"type": "drag-handle", "index": f"{btn_index}"},
            # Use style override instead of color parameter to avoid type errors
            variant="filled",
            size="sm",
            children=DashIconify(
                icon="mdi:dots-grid", width=14, color="black"
            ),  # More subtle grid icon
            className="react-grid-dragHandle",  # This tells DashGridLayout it's a drag handle
            style={"cursor": "grab", "backgroundColor": "#f2f2f2"},
        )

    def create_remove_button():
        return dmc.ActionIcon(
            id={"type": "remove-box-button", "index": f"{btn_index}"},
            color="red",
            variant="filled",
            size="sm",
            children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        )

    def create_edit_button():
        return dmc.ActionIcon(
            id={"type": "edit-box-button", "index": f"{btn_index}"},
            color="blue",
            variant="filled",
            size="sm",
            children=DashIconify(icon="mdi:pen", width=16, color="white"),
        )

    def create_duplicate_button():
        return dmc.ActionIcon(
            id={"type": "duplicate-box-button", "index": f"{btn_index}"},
            color="gray",
            variant="filled",
            size="sm",
            children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
        )

    # category_button = dmc.Select(
    #     # label="Category",
    #     placeholder="Select category type",
    #     value="Default category",
    #     data=[
    #         {"label": "Default category", "value": "Default category"},
    #         {"label": "Custom", "value": "Custom"},
    #     ],
    #     id={"type": "category-box-button", "index": f"{btn_index}"},
    #     variant="filled",
    #     # size="sm",
    #     # leftSection=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    # )

    def create_reset_button():
        return dmc.ActionIcon(
            id={"type": "reset-selection-graph-button", "index": f"{btn_index}"},
            color="orange",
            variant="filled",
            size="sm",
            children=DashIconify(icon="bx:reset", width=16, color="white"),
        )

    def create_alignment_button():
        from depictio.dash.component_metadata import get_dmc_button_color

        return dmc.Menu(
            [
                dmc.MenuTarget(
                    dmc.ActionIcon(
                        DashIconify(icon="tabler:align-left", width=16),
                        id={"type": "alignment-menu-btn", "index": f"{btn_index}"},
                        color=get_dmc_button_color("text"),
                        variant="filled",
                        size="sm",
                    )
                ),
                dmc.MenuDropdown(
                    [
                        dmc.MenuItem(
                            "Align Left",
                            id={"type": "align-left-btn", "index": f"{btn_index}"},
                            leftSection=DashIconify(icon="tabler:align-left", width=16),
                            n_clicks=0,
                        ),
                        dmc.MenuItem(
                            "Align Center",
                            id={"type": "align-center-btn", "index": f"{btn_index}"},
                            leftSection=DashIconify(icon="tabler:align-center", width=16),
                            n_clicks=0,
                        ),
                        dmc.MenuItem(
                            "Align Right",
                            id={"type": "align-right-btn", "index": f"{btn_index}"},
                            leftSection=DashIconify(icon="tabler:align-right", width=16),
                            n_clicks=0,
                        ),
                    ]
                ),
            ],
            id={"type": "alignment-menu", "index": f"{btn_index}"},
        )

    def create_metadata_button():
        """Create metadata info button with Popover to display component metadata."""
        import json

        # Get metadata from component_data if available
        metadata_dict = {}
        if component_data:
            # Base metadata for all components
            metadata_dict = {
                "index": component_data.get("index", btn_index),
                "component_type": component_data.get("component_type", "unknown"),
            }

            # Add workflow and data collection info
            if component_data.get("wf_id"):
                metadata_dict["wf_id"] = str(component_data["wf_id"])
            if component_data.get("dc_id"):
                metadata_dict["dc_id"] = str(component_data["dc_id"])

            # Component-specific metadata
            component_type_value = component_data.get("component_type")

            if component_type_value == "figure":
                # Figure component metadata
                metadata_dict["visu_type"] = component_data.get("visu_type", "N/A")
                metadata_dict["mode"] = component_data.get("mode", "ui")

                # Add code_content for code-mode figures (truncated for display)
                if component_data.get("mode") == "code" and "code_content" in component_data:
                    code_content = component_data["code_content"]
                    # Truncate code if too long for display
                    max_code_length = 200
                    if len(code_content) > max_code_length:
                        metadata_dict["code_content"] = (
                            code_content[:max_code_length] + "... (truncated)"
                        )
                    else:
                        metadata_dict["code_content"] = code_content

                # Add dict_kwargs if available (most important for figures)
                if "dict_kwargs" in component_data and component_data["dict_kwargs"]:
                    dict_kwargs = component_data["dict_kwargs"]
                    metadata_dict["plot_parameters"] = {}

                    # Extract common plot parameters
                    for key in [
                        "x",
                        "y",
                        "z",
                        "color",
                        "size",
                        "facet_col",
                        "facet_row",
                        "hover_data",
                    ]:
                        if key in dict_kwargs and dict_kwargs[key]:
                            metadata_dict["plot_parameters"][key] = dict_kwargs[key]

                    # Add aggregation info if present
                    if "aggregation_col" in dict_kwargs and dict_kwargs["aggregation_col"]:
                        metadata_dict["plot_parameters"]["aggregation"] = {
                            "column": dict_kwargs["aggregation_col"],
                            "method": dict_kwargs.get("aggregation_method", "N/A"),
                        }

                    # Add other important kwargs
                    for key in ["title", "labels", "color_discrete_map", "category_orders"]:
                        if key in dict_kwargs and dict_kwargs[key]:
                            metadata_dict["plot_parameters"][key] = dict_kwargs[key]

                # Add filter status
                metadata_dict["filter_applied"] = component_data.get("filter_applied", False)

            elif component_type_value == "interactive":
                # Interactive component metadata
                metadata_dict["interactive_type"] = component_data.get(
                    "interactive_component_type", "N/A"
                )
                if "default_state" in component_data:
                    metadata_dict["default_state"] = component_data["default_state"]

            elif component_type_value == "card":
                # Card component metadata
                if "column_name" in component_data:
                    metadata_dict["column_name"] = component_data["column_name"]
                if "aggregation" in component_data:
                    metadata_dict["aggregation"] = component_data["aggregation"]
                if "card_value" in component_data:
                    metadata_dict["card_value"] = component_data["card_value"]

            elif component_type_value == "table":
                # Table component metadata
                if "columns" in component_data:
                    metadata_dict["columns"] = component_data["columns"]

            # Add last updated timestamp
            if component_data.get("last_updated"):
                metadata_dict["last_updated"] = component_data["last_updated"]

        # Format as JSON string
        metadata_json = json.dumps(metadata_dict, indent=2, default=str)

        return html.Div(
            dmc.Popover(
                [
                    dmc.PopoverTarget(
                        dmc.Tooltip(
                            label="Component metadata",
                            position="top",
                            openDelay=300,
                            children=dmc.ActionIcon(
                                id={"type": "metadata-info-button", "index": f"{btn_index}"},
                                color="cyan",
                                variant="filled",
                                size="sm",
                                radius=0,
                                children=DashIconify(
                                    icon="mdi:information-outline", width=16, color="white"
                                ),
                            ),
                        )
                    ),
                    dmc.PopoverDropdown(
                        dmc.Stack(
                            [
                                dmc.Text("Component Configuration", size="sm", fw="bold", mb="xs"),
                                dmc.CodeHighlight(
                                    code=metadata_json,
                                    language="json",
                                    copyLabel="Copy metadata",
                                    copiedLabel="Copied!",
                                    style={
                                        "maxWidth": "450px",
                                        "fontSize": "10px",
                                        "maxHeight": "400px",
                                        "overflow": "auto",
                                    },
                                ),
                            ],
                            gap="xs",
                        )
                    ),
                ],
                width=500,
                position="bottom",
                withArrow=True,
                shadow="md",
            ),
            className="metadata-button-wrapper",
            style={"display": "inline-flex"},  # Ensure it doesn't add extra spacing
        )

    def create_partial_data_warning_button():
        """Create partial data warning button with Popover for figure components.

        Uses a Popover instead of Tooltip so the content can be updated dynamically
        via callback when stored-metadata-component receives actual data counts.
        """
        from depictio.dash.modules.figure_component.utils import ComponentConfig

        config = ComponentConfig()
        cutoff = config.max_data_points

        # Try to get initial counts from component_data if available
        displayed_count = cutoff
        total_count = cutoff

        if component_data:
            displayed_count = component_data.get("displayed_data_count", cutoff)
            total_count = component_data.get("total_data_count", cutoff)

        logger.info(
            f"🎨 Creating partial data button with initial values: {displayed_count:,} / {total_count:,}"
        )

        # Initial content with best available data - will be updated by callback
        # Structure: Stack > (Title, Content Div with children)
        # Include values in keys to force React re-render when counts change
        initial_content = dmc.Stack(
            [
                dmc.Text("⚠️ Partial Data Displayed", size="sm", fw="bold", mb="xs"),
                html.Div(
                    # Content div that will be replaced by callback
                    html.Div(
                        [
                            html.Div(
                                f"Showing: {displayed_count:,} points",
                                key=f"showing-{btn_index}-{displayed_count}",
                            ),
                            html.Div(
                                f"Total: {total_count:,} points",
                                key=f"total-{btn_index}-{total_count}",
                            ),
                            html.Div(
                                "Full dataset available for analysis",
                                style={
                                    "marginTop": "8px",
                                    "fontStyle": "italic",
                                    "fontSize": "0.9em",
                                },
                                key=f"footer-{btn_index}",
                            ),
                        ],
                        key=f"content-wrapper-{btn_index}-{displayed_count}-{total_count}",
                    ),
                    id={"type": "partial-data-popover-content", "index": f"{btn_index}"},
                ),
            ],
            gap="xs",
        )

        return html.Div(
            dmc.Popover(
                [
                    dmc.PopoverTarget(
                        dmc.Tooltip(
                            label="Partial data displayed",
                            position="top",
                            openDelay=300,
                            children=dmc.ActionIcon(
                                id={"type": "partial-data-warning-button", "index": f"{btn_index}"},
                                color="red",
                                variant="filled",
                                size="sm",
                                radius=0,
                                children=DashIconify(
                                    icon="mdi:alert-circle-outline", width=16, color="white"
                                ),
                            ),
                        )
                    ),
                    dmc.PopoverDropdown(initial_content),
                ],
                width=300,
                position="bottom",
                withArrow=True,
                shadow="md",
            ),
            id={"type": "partial-data-button-wrapper", "index": f"{btn_index}"},
            className="partial-data-button-wrapper",
            # Start hidden - will be shown by callback only if data was sampled
            style={"display": "none", "visibility": "hidden"},
        )

    # ALWAYS create buttons regardless of edit mode - CSS will control visibility
    # DISABLED FOR PERFORMANCE TESTING - Phase 4C
    # Conditionally create partial data warning button only for scatter plots with large datasets
    # partial_data_button_func = None
    # if component_type == "figure" and component_data:
    #     visu_type = component_data.get("visu_type", None)
    #     # Check if this is a scatter plot that might have partial data
    #     # The actual check for data size will happen at render time
    #     if visu_type and visu_type.lower() == "scatter":
    #         partial_data_button_func = create_partial_data_warning_button

    # Explicitly set to None to disable popover button creation
    partial_data_button_func = None

    # Get both button groups (edit-only and view-accessible)
    edit_buttons, view_buttons = _create_component_buttons(
        component_type,
        component_data,
        btn_index,
        create_drag_handle,
        create_remove_button,
        create_edit_button,
        create_duplicate_button,
        create_reset_button,
        create_alignment_button,
        create_metadata_button,
        partial_data_button_func,
    )

    # Handle native Dash component - wrap in list for consistent processing
    if hasattr(box, "children") or hasattr(box, "figure") or hasattr(box, "id"):
        # Native Dash component
        box_components_list = box
    else:
        # JSON representation (legacy)
        box_components_list = box

    # Create a DraggableWrapper for dash-dynamic-grid-layout
    # This preserves the UUID and makes the component draggable

    # Generate proper UUID for the draggable component (following prototype pattern)
    box_uuid = f"box-{str(btn_index)}"

    logger.info(f"Creating DraggableWrapper with UUID: {box_uuid}")

    # Create content div with embedded buttons - CSS will handle visibility based on edit mode
    # Button visibility controlled by .drag-handles-hidden CSS class (see draggable-grid.css)
    content_children = []

    # Add component content - handle both native components and lists
    if (
        hasattr(box_components_list, "children")
        or hasattr(box_components_list, "figure")
        or hasattr(box_components_list, "id")
    ):
        # Native Dash component
        content_children.append(box_components_list)
    elif isinstance(box_components_list, list):
        # List of components
        content_children.extend(box_components_list)
    else:
        # Single component or JSON
        content_children.append(box_components_list)

    # Add buttons positioned absolutely - always present in DOM, CSS controls visibility
    # Two separate button groups:
    # 1. Edit-only buttons (hidden in view mode via CSS .component-action-buttons)
    # 2. View-accessible buttons (always visible - reset, metadata)

    button_containers = []

    # Add edit-only buttons (drag, duplicate, edit, remove) - hidden in view mode
    if edit_buttons:
        button_containers.append(
            html.Div(
                edit_buttons,
                className="component-action-buttons",  # Hidden in view mode by CSS
                style={
                    "position": "absolute",
                    "top": "4px",
                    "right": "8px",
                    # z-index managed by CSS: .react-grid-item .mantine-ActionIconGroup-root { z-index: 1001 !important; }
                    "alignItems": "center",
                    "height": "auto",
                    "background": "transparent",
                    "borderRadius": "6px",
                    "padding": "4px",
                },
            )
        )

    # Add view-accessible buttons (reset, metadata) - always visible
    if view_buttons:
        button_containers.append(
            html.Div(
                view_buttons,
                className="component-view-buttons",  # Always visible (not hidden by CSS)
                style={
                    "position": "absolute",
                    "top": "4px",
                    "right": "8px",  # Position on right side with edit buttons
                    # z-index managed by CSS
                    "alignItems": "center",
                    "height": "auto",
                    "background": "transparent",
                    "borderRadius": "6px",
                    "padding": "4px",
                },
            )
        )

    # Add both button containers to content
    content_children.extend(button_containers)

    content_div = html.Div(
        content_children,
        id=f"content-{box_uuid}",
        key=f"content-{btn_index}",  # Stable key for React reconciliation
        className="dashboard-component-hover responsive-content",
        style={
            "overflow": "visible",
            "width": "100%",
            "height": "100%",
            "boxSizing": "border-box",
            "padding": "5px",
            "border": "1px solid transparent",
            "borderRadius": "8px",
            "position": "relative",
            "minHeight": "100px",
            "transition": "all 0.3s ease",
            # Critical flexbox properties for vertical growing
            "display": "flex",
            "flexDirection": "column",
        },
    )

    # Create DraggableWrapper with the UUID as ID (like in the prototype)
    # Note: DraggableWrapper doesn't support 'key' prop - we'll add it to the outer wrapper instead
    draggable_wrapper = dgl.DraggableWrapper(
        id=box_uuid,  # Use UUID as ID for layout tracking
        children=[content_div],
        handleText="Drag",  # Handle text for dragging
    )

    # Return with responsive-wrapper class to match working prototype pattern
    return html.Div(
        draggable_wrapper,
        id=box_uuid,  # CRITICAL: Add the ID to the outer wrapper so it can be found for duplication
        key=f"wrapper-{btn_index}",  # Stable key for outer wrapper
        className="responsive-wrapper",  # Critical: This class makes it work!
        style={
            "position": "relative",
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "flex": "1",  # Critical: Allow vertical growing
        },
    )
