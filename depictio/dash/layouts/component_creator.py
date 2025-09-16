"""
Component Creator Layout

This module provides a stepper-inspired UX for creating dashboard components.
It offers a 2-step process: component type selection and component configuration.
"""

import uuid
from typing import Optional

import dash
import dash_mantine_components as dmc
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.models.card_component_config import (
    CardColorOption,
    CardIconOption,
    FontSizeOption,
)


def create_component_creator_layout(
    dashboard_id: str, component_id: Optional[str] = None
) -> dmc.Container:
    """
    Create the main layout for the component creator stepper interface.

    Args:
        dashboard_id: ID of the dashboard to add component to
        component_id: Optional component ID for editing existing components

    Returns:
        html.Div: The complete component creator layout
    """

    # Generate unique session ID for this creator instance
    session_id = str(uuid.uuid4())

    # Create stepper component
    stepper = dmc.Stepper(
        id={"type": "component-creator-stepper", "session": session_id},
        active=0,
        color="blue",
        children=[
            # Step 1: Component Type Selection
            dmc.StepperStep(
                label="Select Component Type",
                description="Choose the type of component you want to create",
                children=create_component_type_selection(session_id),
            ),
            # Step 2: Configure Component
            dmc.StepperStep(
                label="Configure Component",
                description="Set up your component with data and styling",
                children=create_component_configuration(session_id),
            ),
            # Step 3: Complete
            dmc.StepperCompleted(
                children=create_completion_step(session_id),
            ),
        ],
    )

    # Navigation buttons
    navigation = dmc.Group(
        justify="space-between",
        mt="xl",
        children=[
            dmc.Button(
                "Back",
                id={"type": "stepper-back-btn", "session": session_id},
                variant="subtle",
                leftSection=DashIconify(icon="mdi:arrow-left", width=16),
            ),
            dmc.Button(
                "Next",
                id={"type": "stepper-next-btn", "session": session_id},
                leftSection=DashIconify(icon="mdi:arrow-right", width=16),
                disabled=True,  # Initially disabled
            ),
        ],
    )

    # Create the main layout
    layout = dmc.Container(
        size="xl",
        px="md",
        children=[
            # Header
            dmc.Group(
                justify="space-between",
                align="center",
                mb="xl",
                children=[
                    html.Div(
                        [
                            dmc.Title("Add New Component", order=2, mb="xs"),
                            dmc.Text(
                                f"Dashboard: {dashboard_id}",
                                size="sm",
                                c="gray",
                            ),
                        ]
                    ),
                    dmc.Button(
                        "Cancel",
                        id={"type": "creator-cancel-btn", "session": session_id},
                        variant="subtle",
                        color="gray",
                        leftSection=DashIconify(icon="mdi:close", width=16),
                    ),
                ],
            ),
            # Stepper
            stepper,
            # Navigation
            navigation,
            # Hidden stores for state management
            dcc.Store(
                id={"type": "creator-state-store", "session": session_id},
                data={
                    "dashboard_id": dashboard_id,
                    "component_id": component_id,
                    "session_id": session_id,
                    "current_step": 0,
                    "component_type": None,
                    "component_config": None,
                },
            ),
            dcc.Store(
                id={"type": "creator-data-store", "session": session_id},
                data={},
            ),
        ],
    )

    return layout


def create_component_type_selection(session_id: str) -> html.Div:
    """Create the component type selection interface."""

    component_types = [
        {
            "type": "Card",
            "icon": "formkit:number",
            "color": "blue",
            "description": "Display aggregated data values with customizable styling",
        },
        {
            "type": "Figure",
            "icon": "mdi:chart-line",
            "color": "green",
            "description": "Create interactive charts and visualizations",
        },
        {
            "type": "Table",
            "icon": "mdi:table",
            "color": "orange",
            "description": "Show tabular data with sorting and filtering",
        },
        {
            "type": "Interactive",
            "icon": "mdi:tune",
            "color": "purple",
            "description": "Add interactive controls for dashboard filtering",
        },
        {
            "type": "Text",
            "icon": "mdi:text",
            "color": "teal",
            "description": "Add rich text content and documentation",
        },
    ]

    # Create component type selection cards
    type_cards = []
    for comp_type in component_types:
        # Wrap card in a button for click handling
        card = dmc.Button(
            children=dmc.Card(
                children=[
                    dmc.CardSection(
                        dmc.Center(
                            DashIconify(
                                icon=comp_type["icon"],
                                width=48,
                                height=48,
                                color=f"var(--mantine-color-{comp_type['color']}-6)",
                            ),
                            h=80,
                        ),
                        withBorder=True,
                        pb="md",
                    ),
                    dmc.Text(
                        comp_type["type"],
                        fw="bold",
                        size="lg",
                        ta="center",
                        mb="xs",
                    ),
                    dmc.Text(
                        comp_type["description"],
                        size="sm",
                        c="gray",
                        ta="center",
                    ),
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                style={
                    "transition": "all 0.2s ease",
                },
                className="component-type-card",
            ),
            id={
                "type": "component-type-card",
                "session": session_id,
                "value": comp_type["type"],
            },
            variant="subtle",
            fullWidth=True,
            style={
                "padding": 0,
                "height": "auto",
                "textAlign": "left",
            },
            n_clicks=0,
        )
        type_cards.append(card)

    return html.Div(
        [
            dmc.Text(
                "Select the type of component you want to add to your dashboard:",
                size="md",
                mb="xl",
                ta="center",
            ),
            dmc.SimpleGrid(
                cols={"base": 1, "sm": 2, "md": 3, "lg": 5},
                spacing="lg",
                children=type_cards,
            ),
        ]
    )


def create_component_configuration(session_id: str) -> html.Div:
    """Create the component configuration interface."""

    return html.Div(
        id={"type": "component-config-container", "session": session_id},
        children=[
            dmc.Center(
                [
                    DashIconify(icon="mdi:cog", width=48, color="gray"),
                    dmc.Text(
                        "Select a component type to configure",
                        size="lg",
                        c="gray",
                        mt="md",
                    ),
                ],
                h=200,
            ),
        ],
    )


def create_card_configuration_interface(session_id: str) -> dmc.Grid:
    """Create the card-specific configuration interface."""

    # Define default sample dataframe columns (matching dashboard prototype)
    sample_columns = [
        "revenue",
        "sales",
        "customers",
        "orders",
        "conversion_rate",
        "avg_order_value",
        "profit_margin",
        "units_sold",
        "returns",
        "satisfaction_score",
    ]

    return dmc.Grid(
        [
            # Left column: Configuration form
            dmc.GridCol(
                span=6,
                children=[
                    dmc.Title("Card Configuration", order=4, mb="lg"),
                    # Basic settings
                    dmc.TextInput(
                        label="Card Title",
                        placeholder="Enter a descriptive title",
                        id={"type": "card-config-title", "session": session_id},
                        required=True,
                        mb="md",
                    ),
                    # Hidden stores for default workflow/datacollection
                    dcc.Store(
                        id={"type": "card-config-workflow", "session": session_id},
                        data="default-workflow",
                    ),
                    dcc.Store(
                        id={"type": "card-config-datacollection", "session": session_id},
                        data="default-datacollection",
                    ),
                    # Column selection with pre-populated sample data
                    dmc.Select(
                        label="Select Column",
                        placeholder="Choose column to aggregate...",
                        id={"type": "card-config-column", "session": session_id},
                        data=[
                            {"label": col.replace("_", " ").title(), "value": col}
                            for col in sample_columns
                        ],
                        mb="md",
                    ),
                    dmc.Select(
                        label="Aggregation Type",
                        placeholder="Choose aggregation method...",
                        id={"type": "card-config-aggregation", "session": session_id},
                        data=[
                            {"label": "Sum", "value": "sum"},
                            {"label": "Average", "value": "average"},
                            {"label": "Count", "value": "count"},
                            {"label": "Min", "value": "min"},
                            {"label": "Max", "value": "max"},
                            {"label": "Median", "value": "median"},
                        ],
                        mb="lg",
                    ),
                    # Styling options
                    dmc.Title("Styling Options", order=5, mb="md"),
                    dmc.Select(
                        label="Color Theme",
                        id={"type": "card-config-color", "session": session_id},
                        data=[
                            {"label": name.title(), "value": value.value}
                            for name, value in CardColorOption.__members__.items()
                        ],
                        value=CardColorOption.BLUE.value,
                        mb="md",
                    ),
                    dmc.Select(
                        label="Icon",
                        id={"type": "card-config-icon", "session": session_id},
                        data=[
                            {"label": name.replace("_", " ").title(), "value": value.value}
                            for name, value in CardIconOption.__members__.items()
                        ],
                        value=CardIconOption.NUMBER.value,
                        mb="md",
                    ),
                    dmc.Select(
                        label="Font Size",
                        id={"type": "card-config-fontsize", "session": session_id},
                        data=[
                            {"label": name.replace("_", " ").title(), "value": value.value}
                            for name, value in FontSizeOption.__members__.items()
                        ],
                        value=FontSizeOption.LARGE.value,
                        mb="md",
                    ),
                ],
            ),
            # Right column: Live preview
            dmc.GridCol(
                span=6,
                children=[
                    dmc.Title("Live Preview", order=4, mb="lg"),
                    dmc.Paper(
                        children=[
                            html.Div(
                                id={"type": "card-preview-container", "session": session_id},
                                children=[
                                    dmc.Center(
                                        [
                                            DashIconify(icon="mdi:eye-off", width=32, color="gray"),
                                            dmc.Text(
                                                "Configure card to see preview",
                                                size="sm",
                                                c="gray",
                                                mt="sm",
                                            ),
                                        ],
                                        h=150,
                                    ),
                                ],
                            ),
                        ],
                        withBorder=True,
                        shadow="sm",
                        radius="md",
                        p="lg",
                        h=400,
                    ),
                ],
            ),
        ],
        gutter="xl",
    )


def create_completion_step(session_id: str) -> dmc.Center:
    """Create the completion step interface."""

    return dmc.Center(
        [
            dmc.Stack(
                [
                    DashIconify(
                        icon="mdi:check-circle",
                        width=64,
                        color="green",
                    ),
                    dmc.Title(
                        "Component Ready!",
                        order=3,
                        ta="center",
                        c="green",
                    ),
                    dmc.Text(
                        "Your component has been configured and is ready to be added to the dashboard.",
                        size="lg",
                        ta="center",
                        c="gray",
                        mb="xl",
                    ),
                    dmc.Button(
                        "Add to Dashboard",
                        id={"type": "add-component-btn", "session": session_id},
                        size="lg",
                        color="green",
                        leftSection=DashIconify(icon="mdi:plus-circle", width=20),
                    ),
                ],
                align="center",
                gap="md",
            ),
        ],
        h=300,
    )


def register_component_creator_callbacks(app):
    """Register callbacks for the component creator interface."""

    # Component type selection callback
    @app.callback(
        [
            Output({"type": "creator-state-store", "session": MATCH}, "data"),
            Output({"type": "stepper-next-btn", "session": MATCH}, "disabled"),
            Output({"type": "component-creator-stepper", "session": MATCH}, "active"),
        ],
        [
            Input({"type": "component-type-card", "session": MATCH, "value": ALL}, "n_clicks"),
            Input({"type": "stepper-next-btn", "session": MATCH}, "n_clicks"),
            Input({"type": "stepper-back-btn", "session": MATCH}, "n_clicks"),
        ],
        [
            State({"type": "creator-state-store", "session": MATCH}, "data"),
            State({"type": "component-creator-stepper", "session": MATCH}, "active"),
        ],
        prevent_initial_call=True,
    )
    def handle_stepper_navigation(
        type_card_clicks, next_clicks, back_clicks, state_data, current_step
    ):
        """Handle stepper navigation and component type selection."""

        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # Handle component type selection
        if "component-type-card" in trigger_id:
            import json

            trigger_dict = json.loads(trigger_id)
            selected_type = trigger_dict["value"]

            state_data["component_type"] = selected_type
            state_data["current_step"] = 0

            return state_data, False, current_step  # Enable next button

        # Handle navigation
        elif "stepper-next-btn" in trigger_id:
            new_step = min(current_step + 1, 2)
            state_data["current_step"] = new_step

            # Check if we can proceed (basic validation)
            next_disabled = True
            if new_step == 1 and state_data.get("component_type"):
                next_disabled = False
            elif new_step == 2:
                next_disabled = False  # Allow completion

            return state_data, next_disabled, new_step

        elif "stepper-back-btn" in trigger_id:
            new_step = max(current_step - 1, 0)
            state_data["current_step"] = new_step

            return state_data, False, new_step

        raise dash.exceptions.PreventUpdate

    # Component configuration interface update
    @app.callback(
        Output({"type": "component-config-container", "session": MATCH}, "children"),
        Input({"type": "creator-state-store", "session": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_component_configuration(state_data):
        """Update the component configuration interface based on selected type."""

        component_type = state_data.get("component_type")
        # Get the session_id from the triggered context
        triggered_id = ctx.triggered_id if ctx.triggered_id else {}
        session_id = triggered_id.get("session", state_data.get("session_id", "default"))

        if not component_type:
            return dmc.Center(
                [
                    DashIconify(icon="mdi:cog", width=48, color="gray"),
                    dmc.Text(
                        "Select a component type to configure",
                        size="lg",
                        c="gray",
                        mt="md",
                    ),
                ],
                h=200,
            )

        if component_type == "Card":
            return create_card_configuration_interface(session_id)
        else:
            return dmc.Center(
                [
                    DashIconify(icon="mdi:construction", width=48, color="orange"),
                    dmc.Text(
                        f"{component_type} configuration coming soon!",
                        size="lg",
                        c="orange",
                        mt="md",
                    ),
                ],
                h=200,
            )

    # Simplified callbacks - no longer needed for workflow/datacollection selection
    # These are kept as placeholders to avoid breaking the callback chain

    # Card preview callback
    @app.callback(
        Output({"type": "card-preview-container", "session": MATCH}, "children"),
        [
            Input({"type": "card-config-title", "session": MATCH}, "value"),
            Input({"type": "card-config-column", "session": MATCH}, "value"),
            Input({"type": "card-config-aggregation", "session": MATCH}, "value"),
            Input({"type": "card-config-color", "session": MATCH}, "value"),
            Input({"type": "card-config-icon", "session": MATCH}, "value"),
        ],
        [
            State({"type": "card-config-workflow", "session": MATCH}, "data"),
            State({"type": "card-config-datacollection", "session": MATCH}, "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_card_preview(
        title, column_name, aggregation, color, icon, workflow_id, datacollection_id, local_store
    ):
        """Update the live preview of the card component with sample data."""

        # Show placeholder if required fields are missing
        if not all([title, column_name, aggregation]):
            return dmc.Center(
                [
                    DashIconify(icon="mdi:eye-off", width=32, color="gray"),
                    dmc.Text(
                        "Complete configuration to see preview",
                        size="sm",
                        c="gray",
                        mt="sm",
                    ),
                ],
                h=150,
            )

        try:
            # Generate sample preview value based on aggregation type
            sample_values = {
                "sum": 125430,
                "average": 4521.5,
                "count": 1234,
                "min": 10,
                "max": 9999,
                "median": 456,
            }

            preview_value = sample_values.get(aggregation, 999)

            # Create a simple preview card without needing actual data
            preview_card = dmc.Card(
                children=[
                    dmc.Text(
                        title,
                        size="md",
                        c=color if color else "gray",
                        fw="bold",
                        mb="xs",
                    ),
                    dmc.Group(
                        [
                            DashIconify(
                                icon=icon if icon else "formkit:number",
                                width=24,
                                color=color if color else "blue",
                            ),
                            dmc.Text(
                                str(preview_value),
                                size="xl",
                                fw="bold",
                                c=color if color else None,
                            ),
                        ],
                        gap="xs",
                    ),
                    dmc.Text(
                        f"{aggregation.title()} of {column_name.replace('_', ' ').title()}",
                        size="xs",
                        c="gray",
                    ),
                ],
                withBorder=False,
                p="md",
                style={"height": "100%"},
            )

            return preview_card

        except Exception as e:
            logger.error(f"Error generating card preview: {e}")
            return dmc.Center(
                [
                    DashIconify(icon="mdi:alert-circle", width=32, color="red"),
                    dmc.Text(
                        "Error generating preview",
                        size="sm",
                        c="red",
                        mt="sm",
                    ),
                ],
                h=150,
            )

    # Next button state callback for card configuration
    @app.callback(
        Output({"type": "stepper-next-btn", "session": MATCH}, "disabled", allow_duplicate=True),
        [
            Input({"type": "card-config-title", "session": MATCH}, "value"),
            Input({"type": "card-config-column", "session": MATCH}, "value"),
            Input({"type": "card-config-aggregation", "session": MATCH}, "value"),
        ],
        State({"type": "creator-state-store", "session": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_next_button_card(title, column, aggregation, state_data):
        """Enable/disable next button based on card configuration completeness."""

        current_step = state_data.get("current_step", 0)

        # Only apply this logic on the configuration step for cards
        if current_step == 1 and state_data.get("component_type") == "Card":
            return not all([title, column, aggregation])

        return False

    # Add component to dashboard callback
    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "add-component-btn", "session": ALL}, "n_clicks"),
        [
            State({"type": "card-config-title", "session": ALL}, "value"),
            State({"type": "card-config-workflow", "session": ALL}, "data"),
            State({"type": "card-config-datacollection", "session": ALL}, "data"),
            State({"type": "card-config-column", "session": ALL}, "value"),
            State({"type": "card-config-aggregation", "session": ALL}, "value"),
            State({"type": "card-config-color", "session": ALL}, "value"),
            State({"type": "card-config-icon", "session": ALL}, "value"),
            State({"type": "card-config-fontsize", "session": ALL}, "value"),
            State({"type": "creator-state-store", "session": ALL}, "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def add_component_to_dashboard(
        n_clicks_list,
        title_list,
        workflow_id_list,
        datacollection_id_list,
        column_name_list,
        aggregation_list,
        color_list,
        icon_list,
        font_size_list,
        state_data_list,
        local_store,
    ):
        """Add the configured component to the dashboard."""

        # Find which button was clicked (if any)
        if not n_clicks_list or not any(n_clicks_list):
            raise dash.exceptions.PreventUpdate

        # Get the index of the clicked button
        clicked_idx = None
        for idx, clicks in enumerate(n_clicks_list):
            if clicks and clicks > 0:
                clicked_idx = idx
                break

        if clicked_idx is None:
            raise dash.exceptions.PreventUpdate

        # Extract values for the clicked session
        title = title_list[clicked_idx] if clicked_idx < len(title_list) else None
        workflow_id = workflow_id_list[clicked_idx] if clicked_idx < len(workflow_id_list) else None
        datacollection_id = (
            datacollection_id_list[clicked_idx]
            if clicked_idx < len(datacollection_id_list)
            else None
        )
        column_name = column_name_list[clicked_idx] if clicked_idx < len(column_name_list) else None
        aggregation = aggregation_list[clicked_idx] if clicked_idx < len(aggregation_list) else None
        color = color_list[clicked_idx] if clicked_idx < len(color_list) else None
        icon = icon_list[clicked_idx] if clicked_idx < len(icon_list) else None
        font_size = font_size_list[clicked_idx] if clicked_idx < len(font_size_list) else None
        state_data = state_data_list[clicked_idx] if clicked_idx < len(state_data_list) else {}

        # Debug logging - Enhanced visibility
        logger.info("🎯 ADD COMPONENT VALUES EXTRACTED:")
        logger.info(f"  title: {title}")
        logger.info(f"  workflow_id: {workflow_id}")
        logger.info(f"  datacollection_id: {datacollection_id}")
        logger.info(f"  column_name: {column_name}")
        logger.info(f"  aggregation: {aggregation}")
        logger.info(f"  color: {color}")
        logger.info(f"  icon: {icon}")
        logger.info(f"  font_size: {font_size}")
        logger.info(f"  state_data: {state_data}")

        # Also print to console for immediate visibility
        print("🎯 ADD COMPONENT VALUES EXTRACTED:")
        print(f"  title: {title}")
        print(f"  font_size: {font_size}")
        print(f"  color: {color}")
        print(f"  aggregation: {aggregation}")

        if not all([title, workflow_id, datacollection_id, column_name, aggregation]):
            raise dash.exceptions.PreventUpdate

        dashboard_id = state_data.get("dashboard_id")
        component_type = state_data.get("component_type")

        if not dashboard_id or component_type != "Card":
            raise dash.exceptions.PreventUpdate

        try:
            TOKEN = local_store["access_token"]

            # For prototype, use default workflow/datacollection IDs
            workflow_id = workflow_id or "default-workflow"
            datacollection_id = datacollection_id or "default-datacollection"

            # Type guards to ensure values are not None (already checked above)
            assert column_name is not None
            assert aggregation is not None
            assert title is not None

            # Use the component_id from state_data (which was passed from URL)
            component_index = state_data.get("component_id")
            if not component_index:
                # Fallback: generate one if not provided (shouldn't happen normally)
                from depictio.dash.utils import generate_unique_index

                component_index = generate_unique_index()

            # Add component metadata for dashboard storage (complete metadata)
            component_metadata = {
                "index": str(component_index),
                "component_type": "card",
                "title": title,
                "wf_id": workflow_id,
                "dc_id": datacollection_id,
                "column_name": column_name,
                "column_type": "float64",  # Default for prototype
                "aggregation": aggregation,
                "color": color,
                "icon": icon,
                "font_size": font_size,
                "dc_config": {"type": "table", "metatype": "prototype"},  # Mock config
                "build_frame": True,
                "refresh": True,
                "stepper": False,
                "filter_applied": False,
                "value": None,  # Will be computed when rendered
                "parent_index": None,
            }

            logger.info(f"📋 FINAL COMPONENT METADATA: {component_metadata}")
            print(
                f"📋 FINAL COMPONENT METADATA: {component_metadata}"
            )  # Ensure visibility in console

            # Add component to dashboard by updating dashboard data directly
            from depictio.dash.api_calls import api_call_save_dashboard
            from depictio.dash.utils import load_depictio_data_mongo

            # Load current dashboard data
            dashboard_data = load_depictio_data_mongo(dashboard_id, TOKEN=TOKEN)

            # Add new component to stored metadata
            if "stored_metadata" not in dashboard_data:
                dashboard_data["stored_metadata"] = []

            dashboard_data["stored_metadata"].append(component_metadata)

            # Save updated dashboard
            api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)

            logger.info(f"Successfully added card component to dashboard {dashboard_id}")

            # Redirect back to dashboard
            return f"/dashboard/{dashboard_id}"

        except Exception as e:
            logger.error(f"Error adding component to dashboard: {e}")
            # Stay on current page if error occurs
            return f"/dashboard/{dashboard_id}/add_component"

    # Cancel button callback
    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "creator-cancel-btn", "session": ALL}, "n_clicks"),
        State({"type": "creator-state-store", "session": ALL}, "data"),
        prevent_initial_call=True,
    )
    def cancel_component_creation(n_clicks_list, state_data_list):
        """Handle cancel button to return to dashboard."""

        # Find which button was clicked (if any)
        if not n_clicks_list or not any(n_clicks_list):
            raise dash.exceptions.PreventUpdate

        # Get the index of the clicked button
        clicked_idx = None
        for idx, clicks in enumerate(n_clicks_list):
            if clicks and clicks > 0:
                clicked_idx = idx
                break

        if clicked_idx is None:
            raise dash.exceptions.PreventUpdate

        state_data = state_data_list[clicked_idx] if clicked_idx < len(state_data_list) else {}

        dashboard_id = state_data.get("dashboard_id")
        if not dashboard_id:
            return "/dashboards"

        return f"/dashboard/{dashboard_id}"
