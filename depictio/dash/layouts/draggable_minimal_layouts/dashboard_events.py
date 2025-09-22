"""
Generic event-driven system for dashboard interactions.
Handles dashboard events through a centralized event store.
"""

from datetime import datetime

import dash
import dash_mantine_components as dmc
import httpx
from dash import Input, Output, State

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.draggable_minimal_layouts.dashboard_creators import (
    create_dashboard_component,
    create_dashboard_section,
    create_demo_component_config,
    render_section_ui,
)
from depictio.dash.layouts.draggable_minimal_layouts.event_models import (
    ComponentAddedToSectionPayload,
    ComponentCreatedPayload,
    DashboardEvent,
    DashboardEventStore,
    EventType,
    SectionCreatedPayload,
    SectionStructureCreatedPayload,
)
from depictio.models.models.dashboard_structure import (
    ComponentType,
    SectionType,
)


def save_component_to_database(
    payload: ComponentCreatedPayload, dashboard_id: str, user_token: str
):
    """Save component metadata to the database by updating dashboard structure."""
    try:
        logger.info(f"💾 DB SAVE: Saving component {payload.component_id} to database")

        # Step 1: Get current dashboard data using correct endpoint
        get_response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        if get_response.status_code != 200:
            logger.error(
                f"💾 DB SAVE: Failed to get dashboard - {get_response.status_code}: {get_response.text}"
            )
            return False, f"Failed to get dashboard: {get_response.status_code}"

        dashboard_data = get_response.json()
        logger.info(
            f"💾 DB SAVE: Retrieved dashboard data with {len(dashboard_data.get('dashboard_structure', {}).get('tabs', []))} tabs"
        )

        # Step 2: Find the target section and add component
        dashboard_structure = dashboard_data.get("dashboard_structure", {})
        tabs = dashboard_structure.get("tabs", [])

        component_added = False
        target_section_id = payload.section_id

        # Look for stored_metadata for this component in the dashboard
        component_metadata = {}
        stored_metadata = dashboard_data.get("stored_metadata", [])
        for metadata in stored_metadata:
            if metadata.get("index") == payload.component_id:
                component_metadata = metadata
                break

        # Create component data to add to section
        component_data = {
            "_id": payload.component_id,
            "component_id": payload.component_id,
            "component_type": payload.component_type,
            "workflow_id": payload.workflow_id,
            "datacollection_id": payload.datacollection_id,
            "metadata": {
                "created_via": payload.trigger,
                "created_url": payload.url,
                "created_at": datetime.now().isoformat(),
            },
            "component_metadata": component_metadata,  # Add the actual component metadata
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        # Search through tabs and sections to find the target section
        for tab in tabs:
            sections = tab.get("sections", [])
            for section in sections:
                if section.get("_id") == target_section_id:
                    # Add component to this section
                    if "components" not in section:
                        section["components"] = []
                    section["components"].append(component_data)
                    section["updated_at"] = datetime.now().isoformat()
                    component_added = True
                    logger.info(f"💾 DB SAVE: Added component to section {target_section_id}")
                    break
            if component_added:
                break

        if not component_added:
            logger.warning(
                f"💾 DB SAVE: Could not find target section {target_section_id}, adding to first available section"
            )
            # Fallback: add to first section if target not found
            if tabs and len(tabs) > 0 and "sections" in tabs[0] and len(tabs[0]["sections"]) > 0:
                first_section = tabs[0]["sections"][0]
                if "components" not in first_section:
                    first_section["components"] = []
                first_section["components"].append(component_data)
                first_section["updated_at"] = datetime.now().isoformat()
                component_added = True
                logger.info(
                    f"💾 DB SAVE: Added component to fallback section {first_section.get('_id')}"
                )

        if not component_added:
            logger.error("💾 DB SAVE: No sections available to add component")
            return False, "No sections available to add component"

        # Step 3: Save the updated dashboard data
        save_response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
            json=dashboard_data,
            headers={"Authorization": f"Bearer {user_token}"},
        )

        if save_response.status_code in [200, 201]:
            logger.info(
                f"💾 DB SAVE: Successfully saved component {payload.component_id} to dashboard structure"
            )
            return True, "Component saved successfully to dashboard structure"
        else:
            logger.error(
                f"💾 DB SAVE: Failed to save dashboard - {save_response.status_code}: {save_response.text}"
            )
            return False, f"Save API error: {save_response.status_code}"

    except Exception as e:
        logger.error(f"💾 DB SAVE: Exception saving component: {e}")
        return False, f"Exception: {str(e)}"


def load_dashboard_components(dashboard_id: str, user_token: str):
    """Load saved components from database for dashboard initialization by extracting from dashboard structure."""
    try:
        logger.info(f"📁 DB LOAD: Loading components for dashboard {dashboard_id}")

        # Get the full dashboard data using correct endpoint
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        if response.status_code == 200:
            dashboard_data = response.json()
            logger.info("📁 DB LOAD: Loaded dashboard data successfully")

            # Extract components from dashboard structure
            all_components = []
            dashboard_structure = dashboard_data.get("dashboard_structure", {})
            tabs = dashboard_structure.get("tabs", [])

            for tab in tabs:
                sections = tab.get("sections", [])
                for section in sections:
                    components = section.get("components", [])
                    for component in components:
                        # Add section context to component
                        component["section_id"] = section.get("_id") or section.get("id")
                        all_components.append(component)

            logger.info(
                f"📁 DB LOAD: Extracted {len(all_components)} components from dashboard structure"
            )
            return all_components
        else:
            logger.warning(
                f"📁 DB LOAD: Failed to load dashboard - {response.status_code}: {response.text}"
            )
            return []

    except Exception as e:
        logger.error(f"📁 DB LOAD: Exception loading components: {e}")
        return []


def render_persisted_component(component_data: dict):
    """Render a component from persisted database data."""
    component_icon_map = {
        "figure": "📊",
        "card": "📋",
        "table": "📋",
        "interactive": "🎛️",
        "text": "📝",
        "unknown": "⚙️",
    }

    component_type = component_data.get("component_type", "unknown")
    component_icon = component_icon_map.get(component_type.lower(), "⚙️")
    component_id = component_data.get("component_id", "unknown")

    metadata = component_data.get("metadata", {})
    created_at = metadata.get("created_at", "Unknown")
    created_via = metadata.get("created_via", "Unknown")

    return dmc.Paper(
        id=f"component-{component_id}",
        children=[
            dmc.Stack(
                [
                    # Component header with icon and type
                    dmc.Group(
                        [
                            dmc.Text(component_icon, size="lg"),
                            dmc.Text(f"{component_type.title()} Component", fw="bold", size="md"),
                        ],
                        justify="flex-start",
                        align="center",
                        gap="sm",
                    ),
                    # Component metadata
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    dmc.Text("🆔", size="sm"),
                                    dmc.Text(
                                        f"Component ID: {component_id}",
                                        size="sm",
                                        c="gray",
                                        fw="bold",
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("🔗", size="sm"),
                                    dmc.Text(
                                        f"Workflow: {component_data.get('workflow_id', 'Not specified')}",
                                        size="sm",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("📊", size="sm"),
                                    dmc.Text(
                                        f"Data Collection: {component_data.get('datacollection_id', 'Not specified')}",
                                        size="sm",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("🎯", size="sm"),
                                    dmc.Text(
                                        f"Section: {component_data.get('section_id', 'Auto-assigned')}",
                                        size="sm",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="xs",
                    ),
                    # Component metadata
                    dmc.Group(
                        [
                            dmc.Text("📋", size="sm"),
                            dmc.Text(
                                f"Component Metadata: {component_data.get('component_metadata', {})}",
                                size="sm",
                                c="gray",
                            ),
                        ],
                        gap="xs",
                    ),
                    # Status and timestamp
                    dmc.Group(
                        [
                            dmc.Text("💾", size="sm"),
                            dmc.Text("Loaded from database", size="sm", c="blue", fw="bold"),
                            dmc.Text(
                                f"created {created_at[:10] if len(created_at) > 10 else created_at}",
                                size="xs",
                                c="dimmed",
                            ),
                        ],
                        gap="xs",
                    ),
                ],
                gap="sm",
            ),
        ],
        p="md",
        radius="md",
        withBorder=True,
        mb="md",
        style={
            "backgroundColor": "var(--mantine-color-blue-0)",
            "borderColor": "var(--mantine-color-blue-3)",
        },
    )


def register_dashboard_event_system(app):
    """Register the generic dashboard event system callbacks."""

    # Generic Event Listener - Listens to dashboard-event-store and processes events
    @app.callback(
        Output("sections-container", "children", allow_duplicate=True),
        Input("dashboard-event-store", "data"),
        State("sections-container", "children"),
        State("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def handle_dashboard_events(event_store_data, current_sections, pathname, local_store):
        """Generic event handler for dashboard events."""
        logger.info(
            "🎯 EVENT SYSTEM: Received event store update"
            f" with data: {event_store_data}"
            f" and current sections: {current_sections}"
        )
        if not event_store_data or not event_store_data.get("event_type"):
            return dash.no_update

        try:
            # Parse the event store data into a DashboardEventStore model
            event_store = DashboardEventStore(**event_store_data)

            if not event_store.event_type:
                return dash.no_update

            logger.info(
                f"🎯 EVENT SYSTEM: Processing event '{event_store.event_type}' at {event_store.timestamp}"
            )
            logger.info(f"🎯 EVENT SYSTEM: Payload: {event_store.payload}")

            # Handle different event types
            if event_store.event_type == EventType.COMPONENT_CREATED:
                payload = ComponentCreatedPayload(**event_store.payload)

                # Extract dashboard_id from pathname for database saving
                dashboard_id = None
                if pathname and pathname.startswith("/dashboard/"):
                    path_parts = pathname.strip("/").split("/")
                    if len(path_parts) >= 2:
                        dashboard_id = path_parts[1]

                # Save to database if we have user token and dashboard_id
                if dashboard_id and local_store and local_store.get("access_token"):
                    user_token = local_store["access_token"]
                    save_success, save_message = save_component_to_database(
                        payload, dashboard_id, user_token
                    )
                    if save_success:
                        logger.info(f"💾 DB SAVE: {save_message}")
                    else:
                        logger.error(f"💾 DB SAVE: {save_message}")

                return _handle_component_created_event(payload, current_sections)
            elif event_store.event_type == EventType.SECTION_CREATED:
                payload = SectionCreatedPayload(**event_store.payload)
                return _handle_section_created_event(payload, current_sections)
            elif event_store.event_type == EventType.SECTION_STRUCTURE_CREATED:
                payload = SectionStructureCreatedPayload(**event_store.payload)
                return _handle_section_structure_created_event(payload, current_sections)
            elif event_store.event_type == EventType.COMPONENT_ADDED_TO_SECTION:
                payload = ComponentAddedToSectionPayload(**event_store.payload)
                return _handle_component_added_to_section_event(payload, current_sections)
            # Future events can be added here
            # elif event_store.event_type == EventType.COMPONENT_DELETED:
            #     payload = ComponentDeletedPayload(**event_store.payload)
            #     return _handle_component_deleted_event(payload, current_sections)
            # elif event_store.event_type == EventType.COMPONENT_UPDATED:
            #     payload = ComponentUpdatedPayload(**event_store.payload)
            #     return _handle_component_updated_event(payload, current_sections)
            else:
                logger.warning(f"🎯 EVENT SYSTEM: Unknown event type: {event_store.event_type}")
                return dash.no_update
        except Exception as e:
            logger.error(f"🎯 EVENT SYSTEM: Error processing event data: {e}")
            return dash.no_update


def _handle_component_created_event(payload: ComponentCreatedPayload, current_sections):
    """Handle component creation events."""
    logger.info("🎯 EVENT SYSTEM: Handling component_created event")
    logger.info(f"🎯 EVENT SYSTEM: Target section_id: {payload.section_id}")
    logger.info(f"🎯 EVENT SYSTEM: Component metadata: {payload}")

    # Create metadata component with comprehensive information
    component_icon_map = {
        "figure": "📊",
        "card": "📋",
        "table": "📋",
        "interactive": "🎛️",
        "text": "📝",
        "unknown": "⚙️",
    }

    component_icon = component_icon_map.get(payload.component_type.lower(), "⚙️")

    built_component = dmc.Paper(
        id=f"component-{payload.component_id}",  # Give it a proper ID for potential interactions
        children=[
            dmc.Stack(
                [
                    # Component header with icon and type
                    dmc.Group(
                        [
                            dmc.Text(component_icon, size="lg"),
                            dmc.Text(
                                f"{payload.component_type.title()} Component", fw="bold", size="md"
                            ),
                        ],
                        justify="flex-start",
                        align="center",
                        gap="sm",
                    ),
                    # Component metadata
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    dmc.Text("🆔", size="sm"),
                                    dmc.Text(
                                        f"Component ID: {payload.component_id}",
                                        size="sm",
                                        c="gray",
                                        fw="bold",
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("🔗", size="sm"),
                                    dmc.Text(
                                        f"Workflow: {payload.workflow_id or 'Not specified'}",
                                        size="sm",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("📊", size="sm"),
                                    dmc.Text(
                                        f"Data Collection: {payload.datacollection_id or 'Not specified'}",
                                        size="sm",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("🎯", size="sm"),
                                    dmc.Text(
                                        f"Section: {payload.section_id or 'Auto-assigned'}",
                                        size="sm",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="xs",
                    ),
                    # Component metadata (will be captured when saved)
                    dmc.Group(
                        [
                            dmc.Text("📋", size="sm"),
                            dmc.Text(
                                "Component metadata will be captured from stored_metadata when saved to DB",
                                size="sm",
                                c="orange",
                            ),
                        ],
                        gap="xs",
                    ),
                    # Timestamp and status
                    dmc.Group(
                        [
                            dmc.Text("✅", size="sm"),
                            dmc.Text("Created successfully", size="sm", c="green", fw="bold"),
                            dmc.Text(f"via {payload.trigger}", size="xs", c="dimmed"),
                        ],
                        gap="xs",
                    ),
                ],
                gap="sm",
            ),
        ],
        p="md",
        radius="md",
        withBorder=True,
        mb="md",
        style={
            "backgroundColor": "var(--mantine-color-green-0)",
            "borderColor": "var(--mantine-color-green-3)",
        },
    )

    current_sections = current_sections or []

    # If section_id is provided, add component to that specific section
    if payload.section_id:
        logger.info(f"🎯 EVENT SYSTEM: Adding component to existing section {payload.section_id}")

        updated_sections = []
        component_added = False

        for section_dict in current_sections:
            if (
                isinstance(section_dict, dict)
                and section_dict.get("props", {}).get("id") == payload.section_id
            ):
                # This is the target section - add the component
                section_props = section_dict.get("props", {})
                section_children = section_props.get("children", [])

                # Add the component to the section's children
                section_children.append(built_component)

                updated_sections.append(section_dict)
                component_added = True
                logger.info(
                    f"🎯 EVENT SYSTEM: Added component {payload.component_id} to section {payload.section_id}"
                )
            else:
                updated_sections.append(section_dict)

        if not component_added:
            logger.warning(
                f"🎯 EVENT SYSTEM: Section {payload.section_id} not found, creating new section"
            )
            # Fallback: create new section if target section not found
            return _create_new_section_with_component(payload, current_sections, built_component)

        return updated_sections
    else:
        # No section_id provided, create new section (original behavior)
        logger.info("🎯 EVENT SYSTEM: No section_id provided, creating new section")
        return _create_new_section_with_component(payload, current_sections, built_component)


def _create_new_section_with_component(
    payload: ComponentCreatedPayload, current_sections, built_component
):
    """Helper function to create a new section with the component."""
    section_count = len(
        [
            s
            for s in current_sections
            if isinstance(s, dict) and s.get("props", {}).get("id", "").startswith("section-")
        ]
    )

    section_letter = chr(65 + section_count)  # A, B, C, etc.

    new_section = dmc.Paper(
        id=f"section-{section_count}",
        children=[
            dmc.Group(
                [
                    dmc.Text("🎯", size="lg"),
                    dmc.Text(f"#{section_count + 1}", fw="bold", c="green"),
                    dmc.Text(f"Section {section_letter} - Via Event System", size="lg"),
                ],
                justify="flex-start",
                align="center",
                gap="xs",
            ),
            dmc.Text(
                f"Section ID: section-{section_count}",
                size="xs",
                c="gray",
                mt="xs",
            ),
            dmc.Stack(
                [
                    dmc.Text(
                        "Component (via event system):",
                        fw="bold",
                        size="sm",
                    ),
                    built_component,
                ],
                gap="sm",
                mt="md",
            ),
        ],
        p="md",
        radius="md",
        withBorder=True,
        mb="xs",
    )

    # Update sections
    if section_count == 0:
        updated_sections = [new_section]
    else:
        updated_sections = current_sections + [new_section]

    logger.info(
        f"🎯 EVENT SYSTEM: Created Section {section_letter} with component {payload.component_id}"
    )
    return updated_sections


def _handle_section_created_event(payload: SectionCreatedPayload, current_sections):
    """Handle section creation events (from Create Section button)."""
    from depictio.dash.layouts.draggable_minimal import create_section_component

    logger.info("🎯 EVENT SYSTEM: Handling section_created event")

    current_sections = current_sections or []
    section_count = len(
        [
            s
            for s in current_sections
            if isinstance(s, dict) and s.get("props", {}).get("id", "").startswith("section-")
        ]
    )

    # Create new section component
    new_section = create_section_component(payload.section_name, section_count)

    # If this is the first section, replace welcome message
    if section_count == 0:
        updated_sections = [new_section]
    else:
        updated_sections = current_sections + [new_section]

    logger.info(
        f"🎯 EVENT SYSTEM: Created section '{payload.section_name}', total sections: {len(updated_sections)}"
    )
    return updated_sections


def _handle_section_structure_created_event(
    payload: SectionStructureCreatedPayload, current_sections
):
    """Handle section creation events using the new structure."""
    logger.info("🎯 EVENT SYSTEM: Handling section_structure_created event")

    # Parse section type from payload
    try:
        section_type = SectionType(payload.section_type)
    except ValueError:
        section_type = SectionType.MIXED

    # Create the new section using dashboard creators
    new_section = create_dashboard_section(
        name=payload.section_name,
        section_type=section_type,
        section_id=payload.section_id,
        icon=payload.icon,
    )

    # Render the section UI
    section_ui = render_section_ui(new_section, include_create_component_button=True)

    # Add to sections
    current_sections = current_sections or []
    section_count = len(current_sections)

    # If this is the first section, replace welcome message
    if section_count == 0:
        updated_sections = [section_ui]
    else:
        updated_sections = current_sections + [section_ui]

    logger.info(
        f"🎯 EVENT SYSTEM: Created structured {section_type} section '{payload.section_name}' with ID {payload.section_id}"
    )
    return updated_sections


def _handle_component_added_to_section_event(
    payload: ComponentAddedToSectionPayload, current_sections
):
    """Handle adding a component to a specific section."""
    logger.info(
        f"🎯 EVENT SYSTEM: Handling component_added_to_section event for section {payload.section_id}"
    )

    # Parse component type
    try:
        component_type = ComponentType(payload.component_type)
    except ValueError:
        logger.error(f"🎯 EVENT SYSTEM: Unknown component type: {payload.component_type}")
        return dash.no_update

    # Create demo component config
    component_config = create_demo_component_config(component_type)

    # Create the component
    create_dashboard_component(
        component_type=component_type,
        config=component_config,
        component_id=payload.component_id,
    )

    # Find the target section and update it
    # Note: This is a simplified approach. In a real implementation,
    # you would need to maintain section state and update the specific section
    current_sections = current_sections or []

    # For demo purposes, we'll add a component preview to the first section
    # In a full implementation, you'd need to track section instances
    logger.info(
        f"🎯 EVENT SYSTEM: Added {component_type} component {payload.component_id} to section {payload.section_id}"
    )

    # Return current sections for now (in real implementation, update the specific section)
    return current_sections


def emit_event(event_type: EventType, payload_data: dict) -> dict:
    """
    Create an event data structure for emitting through the event store.

    Args:
        event_type: Type of event (EventType enum)
        payload_data: Event-specific data as dictionary

    Returns:
        Event data dictionary for the event store (compatible with DashboardEventStore)
    """
    # Create the appropriate payload model based on event type
    if event_type == EventType.COMPONENT_CREATED:
        payload = ComponentCreatedPayload(**payload_data)
    elif event_type == EventType.SECTION_CREATED:
        payload = SectionCreatedPayload(**payload_data)
    elif event_type == EventType.SECTION_STRUCTURE_CREATED:
        payload = SectionStructureCreatedPayload(**payload_data)
    elif event_type == EventType.COMPONENT_ADDED_TO_SECTION:
        payload = ComponentAddedToSectionPayload(**payload_data)
    else:
        # For unknown event types, use raw dict (temporary fallback)
        payload = payload_data

    # Create the dashboard event
    event = DashboardEvent(
        event_type=event_type,
        timestamp=datetime.now(),
        payload=payload,
    )

    # Return in the format expected by the event store
    return {
        "event_type": event.event_type,  # EventType enum is already a string enum
        "timestamp": event.timestamp.isoformat(),
        "payload": payload.model_dump()
        if hasattr(payload, "model_dump") and callable(getattr(payload, "model_dump", None))
        else payload,
    }


def create_dashboard_event_store():
    """Create the dashboard event store component."""
    from dash import dcc

    return dcc.Store(
        id="dashboard-event-store",
        data={"event_type": None, "timestamp": None, "payload": {}},
        # Removed storage_type="session" - events should be transient, not persistent
    )


def create_auto_save_status_store():
    """Create the auto-save status store component."""
    from dash import dcc

    return dcc.Store(
        id="auto-save-status",
        data={"status": None, "message": None},
    )
