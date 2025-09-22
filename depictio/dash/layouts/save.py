"""
Minimal save functionality for dashboards using the new Pydantic structure.
Provides simple save operations for the structured dashboard format.
"""

from datetime import datetime
from typing import Optional

from dash import Input, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_get_dashboard,
    api_call_save_dashboard,
    api_call_screenshot_dashboard,
)
from depictio.models.models.dashboard_structure import DashboardTabStructure


def collect_dashboard_structure_from_event_store(
    event_store_data: Optional[dict],
    dashboard_id: str,
    existing_structure: Optional[DashboardTabStructure] = None,
) -> DashboardTabStructure:
    """
    Collect dashboard structure from the event store metadata.
    Use event store data instead of parsing UI elements.

    Args:
        event_store_data: Dashboard event store data containing section metadata
        dashboard_id: ID of the dashboard

    Returns:
        DashboardTabStructure: Structured representation of the dashboard
    """
    logger.info("💾 SAVE: Collecting dashboard structure from event store metadata")

    # Start with existing structure or create new one
    structure = existing_structure or DashboardTabStructure()

    # Ensure we have a default tab
    default_tab = structure.ensure_default_tab(dashboard_id)

    # Handle different event types
    event_type = event_store_data.get("event_type") if event_store_data else None

    # Extract section metadata from event store
    if event_type == "section_structure_created":
        payload = event_store_data.get("payload", {})

        if payload:
            logger.info(f"💾 SAVE: Processing section from event store: {payload}")

            # Import models
            from depictio.models.models.dashboard_structure import DashboardSection, SectionType

            # Extract section metadata from event payload
            section_id = payload.get("section_id")
            section_name = payload.get("section_name", "Untitled Section")
            section_type_str = payload.get("section_type", "mixed")

            # Parse section type
            try:
                section_type = SectionType(section_type_str)
            except ValueError:
                section_type = SectionType.MIXED
                logger.warning(f"💾 SAVE: Unknown section type '{section_type_str}', using MIXED")

            # Check if section already exists (avoid duplicates)
            existing_section = next((s for s in default_tab.sections if s.id == section_id), None)
            if not existing_section:
                # Create new section
                section = DashboardSection(
                    id=section_id,
                    name=section_name,
                    section_type=section_type,
                    description="Auto-saved section from event store",
                    components=[],
                )
                default_tab.add_section(section)
                logger.info(f"💾 SAVE: Added new section '{section_name}' (type: {section_type})")
            else:
                logger.info(f"💾 SAVE: Section '{section_id}' already exists, skipping duplicate")

    elif event_type == "component_created":
        # Handle component creation event
        payload = event_store_data.get("payload", {})

        if payload:
            logger.info(f"💾 SAVE: Processing component creation from event store: {payload}")

            # Import models
            from depictio.models.models.dashboard_structure import DashboardComponent

            # Extract component metadata
            component_id = payload.get("component_id")
            section_id = payload.get("section_id")
            metadata = payload.get("metadata", {})

            # All component details are in metadata
            component_type_str = metadata.get("component_type", "unknown")
            workflow_id = metadata.get("wf_id")
            datacollection_id = metadata.get("dc_id")

            logger.info(
                f"💾 SAVE: Creating component {component_id} of type {component_type_str} for section {section_id}"
            )
            logger.info(f"💾 SAVE: Component metadata: {metadata}")

            # Convert string to ComponentType enum
            from depictio.models.models.dashboard_structure import ComponentType

            try:
                component_type = ComponentType(component_type_str.lower())
            except ValueError:
                logger.warning(
                    f"💾 SAVE: Unknown component type '{component_type_str}', using TEXT as fallback"
                )
                component_type = ComponentType.TEXT

            # Find the section to add the component to
            if section_id:
                section = next((s for s in default_tab.sections if s.id == section_id), None)

                if section:
                    # Check if component already exists (avoid duplicates)
                    existing_component = next(
                        (c for c in section.components if c.id == component_id), None
                    )

                    if not existing_component:
                        # Create component configuration from metadata
                        component_config = {
                            "workflow_id": workflow_id,
                            "datacollection_id": datacollection_id,
                        }

                        # Add metadata to config if available
                        if metadata:
                            component_config.update(metadata)

                        # Create new component following DashboardComponent structure
                        component = DashboardComponent(
                            id=component_id,
                            type=component_type,  # Use ComponentType enum
                            config=component_config,  # Include workflow/dc IDs and metadata
                            position={
                                "x": 0,
                                "y": 0,
                                "width": 4,
                                "height": 3,
                            },  # Default position and size
                        )

                        section.add_component(component)
                        logger.info(
                            f"💾 SAVE: Added component '{component_id}' to section '{section_id}'"
                        )
                    else:
                        logger.info(
                            f"💾 SAVE: Component '{component_id}' already exists, skipping duplicate"
                        )
                else:
                    logger.warning(
                        f"💾 SAVE: Section '{section_id}' not found for component '{component_id}'"
                    )
            else:
                logger.warning(f"💾 SAVE: No section_id specified for component '{component_id}'")

    else:
        logger.info(f"💾 SAVE: Event type '{event_type}' not handled for structure collection")

    logger.info(f"💾 SAVE: Collected dashboard structure with {len(default_tab.sections)} sections")
    return structure


def save_dashboard_minimal(
    dashboard_id: str,
    user_token: str,
    event_store_data: Optional[dict] = None,
    filters_container_children: Optional[list] = None,
) -> tuple[bool, str]:
    """
    Save dashboard using the new structured format.

    Args:
        dashboard_id: ID of the dashboard to save
        user_token: User authentication token
        event_store_data: Dashboard event store data containing section metadata
        filters_container_children: Current filters UI state (optional)

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        logger.info(f"💾 SAVE: Starting minimal save for dashboard {dashboard_id}")

        # Fetch current dashboard data
        current_dashboard_dict = api_call_get_dashboard(dashboard_id, user_token)
        if not current_dashboard_dict:
            return False, "Failed to fetch current dashboard data"

        # Convert to Pydantic model
        from depictio.models.models.dashboards import DashboardData

        current_dashboard = DashboardData.from_mongo(current_dashboard_dict)

        # Collect dashboard structure from event store metadata, preserving existing sections
        existing_structure = current_dashboard.dashboard_structure
        dashboard_structure = collect_dashboard_structure_from_event_store(
            event_store_data, dashboard_id, existing_structure
        )

        # Update dashboard data with new structure
        current_dashboard.dashboard_structure = dashboard_structure
        current_dashboard.last_saved_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_dashboard.version = 2  # Set to new structure version

        # Ensure edit mode is enabled for dashboards with sections
        if not current_dashboard.buttons_data:
            current_dashboard.buttons_data = {}
        current_dashboard.buttons_data["edit_components_button"] = True
        current_dashboard.buttons_data["unified_edit_mode"] = True

        logger.info(
            f"💾 SAVE: Prepared save data with structure version {current_dashboard.version}"
        )

        # Save to database - use the full dashboard data object
        success = api_call_save_dashboard(
            dashboard_id=dashboard_id,
            dashboard_data=current_dashboard.model_dump(),
            token=user_token,
        )

        if success:
            logger.info(f"💾 SAVE: Successfully saved dashboard {dashboard_id}")

            # Take screenshot after successful save
            try:
                screenshot_success = api_call_screenshot_dashboard(dashboard_id)
                if screenshot_success:
                    logger.info("📸 SAVE: Successfully captured dashboard screenshot")
                else:
                    logger.warning("📸 SAVE: Failed to capture dashboard screenshot")
            except Exception as e:
                logger.warning(f"📸 SAVE: Screenshot failed: {e}")

            return True, "Dashboard saved successfully"
        else:
            logger.error(f"💾 SAVE: Failed to save dashboard {dashboard_id}")
            return False, "Failed to save dashboard to database"

    except Exception as e:
        logger.error(f"💾 SAVE: Error saving dashboard {dashboard_id}: {e}")
        return False, f"Save error: {str(e)}"


def register_minimal_save_callbacks(app):
    """Register minimal save callbacks for the dashboard."""

    # @app.callback(
    #     Output("success-modal-dashboard", "opened", allow_duplicate=True),
    #     Input("save-button-dashboard", "n_clicks"),
    #     State("dashboard-event-store", "data"),
    #     State("filters-container", "children"),
    #     State("url", "pathname"),
    #     State("local-store", "data"),
    #     prevent_initial_call=True,
    # )
    # def save_dashboard_callback(
    #     n_clicks,
    #     event_store_data,
    #     filters_children,
    #     current_pathname,
    #     token_data,
    # ):
    #     """Handle dashboard save button clicks."""
    #     if not n_clicks:
    #         return dash.no_update

    #     if not token_data or not current_pathname:
    #         logger.error("💾 SAVE: Missing token or pathname")
    #         return False

    #     # Extract dashboard ID from URL
    #     try:
    #         path_parts = current_pathname.strip("/").split("/")
    #         if len(path_parts) >= 2 and path_parts[0] == "dashboard":
    #             dashboard_id = path_parts[1]
    #         else:
    #             logger.error(f"💾 SAVE: Invalid pathname format: {current_pathname}")
    #             return False
    #     except Exception as e:
    #         logger.error(f"💾 SAVE: Error parsing pathname: {e}")
    #         return False

    #     # Perform save
    #     success, message = save_dashboard_minimal(
    #         dashboard_id=dashboard_id,
    #         user_token=token_data.get("access_token"),
    #         event_store_data=event_store_data,
    #         filters_container_children=filters_children,
    #     )

    #     if success:
    #         logger.info(f"💾 SAVE: {message}")
    #         return True  # Open success modal
    #     else:
    #         logger.error(f"💾 SAVE: {message}")
    #         return False  # Keep modal closed

    # Auto-save callback for component creation events
    @app.callback(
        # Output("auto-save-status", "data", allow_duplicate=True),
        Input("dashboard-event-store", "data"),
        State("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def auto_save_on_component_creation(event_store_data, current_pathname, token_data):
        """Automatically save dashboard when component_created events occur."""
        logger.info(f"💾 AUTO-SAVE: Callback triggered with event_store_data: {event_store_data}")

        if not event_store_data or not event_store_data.get("event_type"):
            logger.info("💾 AUTO-SAVE: No event_store_data or event_type, returning no_update")
            # return dash.no_update

        # Only auto-save for component creation events
        if event_store_data.get("event_type") != "component_created":
            logger.info(
                f"💾 AUTO-SAVE: Event type is '{event_store_data.get('event_type')}', not 'component_created', returning no_update"
            )
            # return dash.no_update

        if not token_data or not current_pathname:
            logger.error("💾 AUTO-SAVE: Missing token or pathname")
            # return dash.no_update

        logger.info("💾 AUTO-SAVE: Component creation detected, triggering auto-save")

        # Extract dashboard ID from URL
        path_parts = current_pathname.strip("/").split("/")
        if len(path_parts) < 2 or path_parts[0] != "dashboard":
            logger.error(f"💾 AUTO-SAVE: Invalid dashboard URL: {current_pathname}")
            # return dash.no_update

        dashboard_id = path_parts[1]
        access_token = token_data.get("access_token")

        if not access_token:
            logger.error("💾 AUTO-SAVE: No access token found")
            # return dash.no_update

        # Use the same save logic as the manual save button
        success, message = save_dashboard_minimal(
            dashboard_id=dashboard_id,
            user_token=access_token,
            event_store_data=event_store_data,
        )

        if success:
            logger.info(f"💾 AUTO-SAVE: Success - {message}")
        else:
            logger.error(f"💾 AUTO-SAVE: Failed - {message}")

        # return dash.no_update

    # logger.info(
    #     "💾 SAVE: Registered minimal save callbacks (2 callbacks: manual save and auto-save)"
    # )


# Alias for backward compatibility
register_callbacks_save = register_minimal_save_callbacks
