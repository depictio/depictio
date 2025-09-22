"""
Minimal alternative to draggable.py without dash dynamic grid layout.
Simple row-based layout using basic DMC components.
"""

import dash
import dash_mantine_components as dmc
from dash import ALL, MATCH, Input, Output, State, html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.utils import generate_unique_index


def design_draggable_minimal(
    init_layout: dict,
    init_children: list[dict],
    dashboard_id: str,
    local_data: dict,
    cached_project_data: dict | None = None,
    edit_mode: bool = True,
):
    """
    Minimal draggable layout with two panels:
    - Left panel (1/4): Filters with Create Filter button
    - Right panel (3/4): Sections with Create Section button
    """
    logger.info("🔧 MINIMAL: Creating two-panel minimal draggable layout")

    # Load persisted components from database if available
    components_by_section = {}
    if dashboard_id and local_data and local_data.get("access_token"):
        from depictio.dash.layouts.draggable_minimal_layouts.dashboard_events import (
            load_dashboard_components,
            render_persisted_component,
        )

        try:
            user_token = local_data["access_token"]
            components_data = load_dashboard_components(dashboard_id, user_token)

            # Group components by section_id
            for component_data in components_data:
                section_id = component_data.get("section_id", "default")
                if section_id not in components_by_section:
                    components_by_section[section_id] = []
                components_by_section[section_id].append(render_persisted_component(component_data))

            logger.info(
                f"🔧 MINIMAL: Loaded {len(components_data)} persisted components grouped by {len(components_by_section)} sections"
            )

        except Exception as e:
            logger.error(f"🔧 MINIMAL: Error loading persisted components: {e}")
    else:
        logger.info(
            "🔧 MINIMAL: No dashboard_id or access_token available, skipping component loading"
        )

    # Left Panel (1/4) - Filters
    create_filter_button = dmc.Button(
        "Create Filter",
        id="create-filter-button",
        leftSection=dmc.Text("🔍"),
        variant="filled",
        color="green",
        fullWidth=True,
        mb="md",
    )

    # Initial filter welcome message
    initial_filters = [
        dmc.Paper(
            children=[
                dmc.Text("Filters Panel", size="lg", fw="bold"),
                dmc.Text("Click 'Create Filter' to add filters", size="sm", c="gray"),
            ],
            p="md",
            radius="md",
            withBorder=True,
            mb="xs",
        )
    ]

    filters_container = html.Div(
        children=initial_filters,
        id="filters-container",
    )

    left_panel = dmc.Paper(
        children=[
            dmc.Text("Filters", size="xl", fw="bold", mb="md"),
            create_filter_button,
            filters_container,
        ],
        p="lg",
        radius="md",
        withBorder=True,
        h="100%",
    )

    # Right Panel (3/4) - Sections
    create_section_button = dmc.Button(
        "Create Section",
        id="create-section-button",
        leftSection=dmc.Text("📊"),
        variant="filled",
        color="blue",
        fullWidth=True,
        mb="md",
    )

    # Use restored sections from Pydantic models or show welcome message
    sections_container = html.Div(
        children=init_children
        or [
            dmc.Paper(
                children=[
                    dmc.Text("Sections Panel", size="lg", fw="bold"),
                    dmc.Text("Click 'Create Section' to add sections", size="sm", c="gray"),
                ],
                p="md",
                radius="md",
                withBorder=True,
                mb="xs",
            )
        ],
        id="sections-container",
    )

    # Add missing save button to fix callback error
    save_button = dmc.Button(
        "Save Dashboard",
        id="save-button-dashboard",
        leftSection=dmc.Text("💾"),
        variant="filled",
        color="green",
        fullWidth=True,
        mb="md",
    )

    right_panel = dmc.Paper(
        children=[
            dmc.Text("Sections", size="xl", fw="bold", mb="md"),
            create_section_button,
            save_button,  # Add save button to fix callback error
            sections_container,
        ],
        p="lg",
        radius="md",
        withBorder=True,
        h="100%",
    )

    # Add missing modal for save callbacks
    success_modal = dmc.Modal(
        id="success-modal-dashboard",
        title="Dashboard Saved",
        children=[
            dmc.Text("Your dashboard has been saved successfully!"),
        ],
        opened=False,
    )

    # Dashboard Event Store for generic event-driven system

    from depictio.dash.layouts.draggable_minimal_layouts.dashboard_events import (
        create_auto_save_status_store,
        create_dashboard_event_store,
    )

    dashboard_event_store = create_dashboard_event_store()
    auto_save_status_store = create_auto_save_status_store()

    # Two-panel layout using DMC Grid
    main_container = html.Div(
        children=[
            dashboard_event_store,  # Add the event store for component creation
            auto_save_status_store,  # Add the auto-save status store
            success_modal,  # Add the modal
            dmc.Grid(
                children=[
                    dmc.GridCol(left_panel, span=3),  # 1/4 width (3/12)
                    dmc.GridCol(right_panel, span=9),  # 3/4 width (9/12)
                ],
                gutter="md",
            ),
        ],
        id="minimal-draggable-container",
    )

    return main_container


def create_filter_component(text: str, index: int):
    """Create a filter component."""
    return dmc.Paper(
        id=f"filter-{index}",
        children=[
            dmc.Group(
                children=[
                    dmc.Text("🔍", size="lg"),
                    dmc.Text(f"#{index + 1}", fw="bold", c="green"),
                    dmc.Text(text, size="md"),
                ],
                justify="flex-start",
                align="center",
                gap="xs",
            ),
            dmc.Text(f"Filter ID: filter-{index}", size="xs", c="gray", mt="xs"),
        ],
        p="md",
        radius="md",
        withBorder=True,
        mb="xs",
    )


def create_section_component(text: str, index: int):
    """Create a section component."""
    return dmc.Paper(
        id=f"section-{index}",
        children=[
            dmc.Group(
                children=[
                    dmc.Text("📊", size="lg"),
                    dmc.Text(f"#{index + 1}", fw="bold", c="blue"),
                    dmc.Text(text, size="lg"),
                ],
                justify="flex-start",
                align="center",
                gap="xs",
            ),
            dmc.Text(f"Section ID: section-{index}", size="xs", c="gray", mt="xs"),
        ],
        p="md",
        radius="md",
        withBorder=True,
        mb="xs",
    )


def create_minimal_row_component(text: str, index: int):
    """Create a simple row component with text and index (legacy function)."""
    return dmc.Paper(
        children=[
            dmc.Group(
                children=[
                    dmc.Text(f"#{index + 1}", w=700, c="blue"),
                    dmc.Text(text, size="lg"),
                    dmc.Text(f"Component ID: minimal-{index}", size="xs", c="gray"),
                ],
                justify="space-between",
                align="center",
            )
        ],
        p="md",
        radius="md",
        withBorder=True,
    )


def register_minimal_callbacks(app):
    """Register callbacks for the minimal draggable system."""

    # Minimal save callback compatible with minimal layout
    @app.callback(
        Output("success-modal-dashboard", "opened"),
        Input("save-button-dashboard", "n_clicks"),
        prevent_initial_call=True,
    )
    def minimal_save_dashboard(n_clicks):
        """Minimal save functionality for the minimal layout."""
        if not n_clicks:
            return dash.no_update

        logger.info(f"🔧 MINIMAL SAVE: Save button clicked {n_clicks} times")
        # For now, just show success modal - no actual saving needed for minimal demo
        return True

    # Register the dashboard event system
    from depictio.dash.layouts.draggable_minimal_layouts.dashboard_events import (
        register_dashboard_event_system,
    )

    register_dashboard_event_system(app)

    @app.callback(
        Output("filters-container", "children"),
        Input("create-filter-button", "n_clicks"),
        State("filters-container", "children"),
        prevent_initial_call=True,
    )
    def add_new_filter(n_clicks, current_filters):
        """Add a new filter component when Create Filter button is clicked."""
        if not n_clicks:
            return current_filters

        logger.info(f"🔧 MINIMAL: Create Filter button clicked {n_clicks} times")

        # Calculate new filter index (excluding welcome message)
        current_filters = current_filters or []
        # Count actual filter components (exclude welcome message)
        filter_count = len(
            [
                f
                for f in current_filters
                if isinstance(f, dict) and f.get("props", {}).get("id", "").startswith("filter-")
            ]
        )
        filter_letter = chr(65 + filter_count)  # A, B, C, etc.

        # Create new filter component
        new_filter = create_filter_component(f"Filter {filter_letter}", filter_count)

        # If this is the first filter, replace welcome message
        if filter_count == 0:
            updated_filters = [new_filter]
        else:
            updated_filters = current_filters + [new_filter]

        logger.info(
            f"🔧 MINIMAL: Added Filter {filter_letter}, total filters: {len(updated_filters)}"
        )
        return updated_filters

    # DEBUG callback - DISABLED: moved to stepper.py to test component existence theory
    # @app.callback(
    #     Output("dashboard-debug-store", "data"),
    #     Input({"type": "btn-done", "index": ALL}, "n_clicks"),
    #     prevent_initial_call=True,
    # )
    # def debug_btn_done(n_clicks_list):
    #     logger.info(f"CTX Triggered ID: {ctx.triggered_id}")
    #     logger.info(f"CTX triggered: {ctx.triggered}")
    #     logger.info(f"n_clicks_list: {n_clicks_list}")
    #     return 1

    @app.callback(
        Output("dashboard-event-store", "data", allow_duplicate=True),
        Input("create-section-button", "n_clicks"),
        State("sections-container", "children"),
        prevent_initial_call=True,
    )
    def emit_section_creation_event(n_clicks, current_sections):
        """Emit section creation event when Create Section button is clicked."""
        if not n_clicks:
            return dash.no_update

        logger.info(f"🔧 MINIMAL: Create Section button clicked {n_clicks} times")

        # Calculate section index for naming
        current_sections = current_sections or []
        section_count = len([s for s in current_sections])
        section_letter = chr(65 + section_count)  # A, B, C, etc.

        # Emit event through the event store using helper function
        from depictio.dash.layouts.draggable_minimal_layouts.dashboard_creators import (
            generate_section_id,
        )
        from depictio.dash.layouts.draggable_minimal_layouts.dashboard_events import emit_event
        from depictio.dash.layouts.draggable_minimal_layouts.event_models import EventType

        # Generate section ID and choose section type
        section_id = generate_section_id()
        section_type = "mixed"  # Default to mixed for now

        event_data = emit_event(
            EventType.SECTION_STRUCTURE_CREATED,
            {
                "section_id": section_id,
                "section_name": f"Section {section_letter}",
                "section_type": section_type,
                "icon": "📦",
                "trigger": "create_section_button",
            },
        )

        logger.info(f"🎯 EVENT SYSTEM: Emitting section_created event: {event_data}")
        return event_data

    @app.callback(
        Output({"type": "dashboard-section", "section_id": MATCH}, "children"),
        Input({"type": "create-component-in-section-debug", "section_id": MATCH}, "n_clicks"),
        State({"type": "create-component-in-section-debug", "section_id": MATCH}, "id"),
        State({"type": "dashboard-section", "section_id": MATCH}, "children"),
        prevent_initial_call=False,
    )
    def debug_create_component_in_section(n_clicks_list, section_id, current_children):
        """Debug callback to log clicks on section component creation buttons."""
        logger.info(f"🔧 SECTION COMPONENT DEBUG: n_clicks_list: {n_clicks_list}")
        logger.info(f"🔧 SECTION COMPONENT DEBUG: section_id: {section_id}")
        logger.info(f"🔧 SECTION COMPONENT DEBUG: current_children: {current_children}")
        # Extend just to show it was clicked
        if not n_clicks_list:
            logger.info("🔧 SECTION COMPONENT DEBUG: No clicks detected, returning no_update")
            return dash.no_update
        new_child = dmc.Text(f"Button clicked {n_clicks_list} times", c="red")
        updated_children = current_children + [new_child]
        return updated_children

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "create-component-in-section", "section_id": ALL}, "n_clicks"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def redirect_to_component_creation_from_section(n_clicks_list, current_pathname):
        """Redirect to component creation when section's Add Component button is clicked."""
        logger.info(f"🔧 SECTION COMPONENT: Callback triggered with n_clicks_list: {n_clicks_list}")
        logger.info(f"🔧 SECTION COMPONENT: Current pathname: {current_pathname}")

        if not n_clicks_list or not any(n_clicks_list):
            logger.info("🔧 SECTION COMPONENT: No clicks detected, returning no_update")
            return dash.no_update

        # Find which button was clicked
        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update

        triggered_id = ctx.triggered[0]["prop_id"]
        logger.info(f"🔧 SECTION COMPONENT: Button triggered: {triggered_id}")

        # Extract section_id from the triggered component
        import json

        try:
            # Parse the ID structure like {"index":0,"type":"create-component-in-section","section_id":"sect-abc123"}
            id_dict = json.loads(triggered_id.split(".")[0])
            section_id = id_dict.get("section_id")
        except Exception as e:
            logger.error(f"🔧 SECTION COMPONENT: Could not parse triggered ID: {triggered_id}: {e}")
            return dash.no_update

        logger.info(
            f"🔧 SECTION COMPONENT: Redirecting to create component for section {section_id}"
        )

        # Extract dashboard_id from current pathname
        if current_pathname and current_pathname.startswith("/dashboard/"):
            path_parts = current_pathname.strip("/").split("/")
            if len(path_parts) >= 2:
                dashboard_id = path_parts[1]

                # Generate unique component ID
                component_id = generate_unique_index()

                # Create the new URL pattern: /dashboard/{dashboard_id}/{component_id}/create
                # Only add section_id parameter (component_type will be selected in stepper)
                new_pathname = (
                    f"/dashboard/{dashboard_id}/{component_id}/create?section_id={section_id}"
                )

                logger.info(f"🔧 SECTION COMPONENT: Redirecting to {new_pathname}")
                return new_pathname

        logger.warning(
            f"🔧 SECTION COMPONENT: Could not parse dashboard ID from pathname: {current_pathname}"
        )
        return current_pathname

    # REMOVED: Legacy callback that conflicted with dashboard-event-store system
    # The stepper now emits to dashboard-event-store and the event handler in
    # dashboard_events.py handles adding components to sections

    @app.callback(
        Output("success-modal-dashboard", "opened", allow_duplicate=True),
        Input("dashboard-event-store", "data"),
        State("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def auto_save_on_section_created(event_data, current_pathname, token_data):
        """Automatically save dashboard when a section is created."""
        if not event_data:
            return dash.no_update

        # Check if this is a section creation event
        event_type = event_data.get("event_type")
        if event_type != "section_structure_created":
            return dash.no_update

        logger.info("🔄 AUTO-SAVE: Section created, triggering auto-save")

        # Extract dashboard ID from URL
        if not current_pathname or not current_pathname.startswith("/dashboard/"):
            logger.warning("🔄 AUTO-SAVE: Invalid pathname for auto-save")
            return dash.no_update

        try:
            path_parts = current_pathname.strip("/").split("/")
            if len(path_parts) >= 2:
                dashboard_id = path_parts[1]
            else:
                logger.error(
                    f"🔄 AUTO-SAVE: Could not extract dashboard ID from: {current_pathname}"
                )
                return dash.no_update
        except Exception as e:
            logger.error(f"🔄 AUTO-SAVE: Error parsing pathname: {e}")
            return dash.no_update

        # Trigger save using the minimal save function
        from depictio.dash.layouts.save import save_dashboard_minimal

        if not token_data or not token_data.get("access_token"):
            logger.warning("🔄 AUTO-SAVE: No access token available")
            return dash.no_update

        try:
            success, message = save_dashboard_minimal(
                dashboard_id=dashboard_id,
                user_token=token_data.get("access_token"),
                event_store_data=event_data,  # Pass the event store data instead of UI children
                filters_container_children=[],  # No filters for now
            )

            if success:
                logger.info(f"🔄 AUTO-SAVE: Successfully auto-saved dashboard: {message}")
                return True  # Show success modal briefly
            else:
                logger.error(f"🔄 AUTO-SAVE: Failed to auto-save dashboard: {message}")
                return dash.no_update

        except Exception as e:
            logger.error(f"🔄 AUTO-SAVE: Error during auto-save: {e}")
            return dash.no_update

    # Add callback to trigger stepper button population for URL-based component creation
    @app.callback(
        Output("stored-add-button", "data", allow_duplicate=True),
        Input("stepper-trigger-interval", "n_intervals"),
        State("force-stepper-trigger", "data"),
        prevent_initial_call=True,
    )
    def trigger_stepper_buttons(n_intervals, trigger_data):
        """Force trigger the stepper buttons callback by updating the store."""
        if n_intervals and trigger_data:
            component_id = trigger_data.get("component_id")
            if component_id:
                logger.info(f"🔧 MINIMAL: Triggering stepper buttons for {component_id}")
                # Update timestamp to ensure callback fires
                import time

                return {"_id": component_id, "count": 1, "timestamp": time.time()}
        return dash.no_update
