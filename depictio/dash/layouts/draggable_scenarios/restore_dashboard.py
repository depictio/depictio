"""
Minimal restore functionality for dashboards using the new Pydantic structure.
Provides simple restoration operations for the structured dashboard format.
"""

from typing import List, Optional

import dash_mantine_components as dmc

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.draggable_minimal_layouts.dashboard_creators import (
    render_section_ui,
)
from depictio.models.models.dashboard_structure import (
    DashboardLoadResponse,
    DashboardTabStructure,
)
from depictio.models.models.dashboards import DashboardData


def restore_dashboard_structure_from_data(
    dashboard_data: DashboardData,
) -> Optional[DashboardTabStructure]:
    """
    Restore dashboard structure from saved data.

    Args:
        dashboard_data: DashboardData instance from database

    Returns:
        DashboardTabStructure or None if restoration fails
    """
    try:
        logger.info(
            f"🔄 RESTORE: Restoring dashboard structure for version {dashboard_data.version}"
        )

        # Check if we have the new structure
        if hasattr(dashboard_data, "dashboard_structure") and dashboard_data.dashboard_structure:
            structure = dashboard_data.dashboard_structure

            # Ensure we have at least a default tab
            if not structure.tabs:
                logger.info("🔄 RESTORE: No tabs found, creating default tab")
                structure.ensure_default_tab(str(dashboard_data.dashboard_id))

            logger.info(
                f"🔄 RESTORE: Successfully restored structure with {len(structure.tabs)} tabs"
            )
            return structure

        else:
            # Create new structure for dashboards without the new format
            logger.info("🔄 RESTORE: Creating new structure for legacy dashboard")
            structure = DashboardTabStructure()
            structure.ensure_default_tab(str(dashboard_data.dashboard_id))
            return structure

    except Exception as e:
        logger.error(f"🔄 RESTORE: Error restoring dashboard structure: {e}")
        return None


def render_dashboard_from_structure(
    dashboard_structure: DashboardTabStructure,
    dashboard_id: str,
) -> List[dict]:
    """
    Render dashboard UI from the structured format.

    Args:
        dashboard_structure: DashboardTabStructure to render
        dashboard_id: ID of the dashboard

    Returns:
        List of UI components for the dashboard
    """
    try:
        logger.info(f"🔄 RESTORE: Rendering dashboard {dashboard_id} from structure")

        # Get the current tab (for now, just use default tab)
        current_tab = dashboard_structure.get_default_tab()
        if not current_tab:
            logger.warning("🔄 RESTORE: No default tab found, creating empty dashboard")
            return [create_empty_dashboard_message()]

        logger.info(
            f"🔄 RESTORE: Rendering tab '{current_tab.name}' with {len(current_tab.sections)} sections"
        )

        # Render sections from the current tab
        rendered_sections = []

        if current_tab.sections:
            logger.info(f"🔄 RESTORE: Found {len(current_tab.sections)} saved sections to restore")
            for section in current_tab.sections:
                try:
                    section_ui = render_section_ui(section, include_create_component_button=True)
                    rendered_sections.append(section_ui)
                    logger.info(
                        f"🔄 RESTORE: Rendered section '{section.name}' (ID: {section.id}) with {len(section.components)} components"
                    )
                except Exception as e:
                    logger.error(f"🔄 RESTORE: Error rendering section {section.id}: {e}")
                    # Add error placeholder
                    rendered_sections.append(create_section_error_placeholder(section.name))

        else:
            # No sections, show welcome message
            logger.info("🔄 RESTORE: No sections found, showing welcome message")
            rendered_sections = [create_empty_dashboard_message()]

        logger.info(f"🔄 RESTORE: Successfully rendered {len(rendered_sections)} sections")
        return rendered_sections

    except Exception as e:
        logger.error(f"🔄 RESTORE: Error rendering dashboard: {e}")
        return [create_restore_error_message()]


def create_empty_dashboard_message() -> dmc.Paper:
    """Create a welcome message for empty dashboards."""
    return dmc.Paper(
        children=[
            dmc.Text("Welcome to your Dashboard", size="lg", fw="bold"),
            dmc.Text("Click 'Create Section' to add your first section", size="sm", c="gray"),
        ],
        p="md",
        radius="md",
        withBorder=True,
        mb="xs",
    )


def create_section_error_placeholder(section_name: str) -> dmc.Paper:
    """Create an error placeholder for sections that failed to render."""
    return dmc.Paper(
        children=[
            dmc.Group(
                [
                    dmc.Text("⚠️", size="lg"),
                    dmc.Text(f"Error loading section: {section_name}", fw="bold", c="red"),
                ],
                gap="xs",
            ),
            dmc.Text("This section could not be loaded", size="sm", c="gray"),
        ],
        p="md",
        radius="md",
        withBorder=True,
        mb="xs",
    )


def create_restore_error_message() -> dmc.Paper:
    """Create an error message for dashboard restoration failures."""
    return dmc.Paper(
        children=[
            dmc.Group(
                [
                    dmc.Text("❌", size="lg"),
                    dmc.Text("Failed to restore dashboard", fw="bold", c="red"),
                ],
                gap="xs",
            ),
            dmc.Text("There was an error loading your dashboard", size="sm", c="gray"),
            dmc.Text("Please try refreshing the page or contact support", size="sm", c="gray"),
        ],
        p="md",
        radius="md",
        withBorder=True,
        mb="xs",
    )


def restore_dashboard_minimal(dashboard_data: DashboardData, dashboard_id: str) -> List[dict]:
    """
    Main function to restore a dashboard using the minimal new approach.

    Args:
        dashboard_data: DashboardData instance from database
        dashboard_id: ID of the dashboard

    Returns:
        List of UI components representing the restored dashboard
    """
    try:
        logger.info(f"🔄 RESTORE: Starting minimal restore for dashboard {dashboard_id}")

        # Restore the dashboard structure
        dashboard_structure = restore_dashboard_structure_from_data(dashboard_data)
        if not dashboard_structure:
            logger.error("🔄 RESTORE: Failed to restore dashboard structure")
            return [create_restore_error_message()]

        # Render the dashboard from the structure
        ui_components = render_dashboard_from_structure(dashboard_structure, dashboard_id)

        logger.info(
            f"🔄 RESTORE: Successfully restored dashboard with {len(ui_components)} components"
        )
        return ui_components

    except Exception as e:
        logger.error(f"🔄 RESTORE: Error in minimal restore: {e}")
        return [create_restore_error_message()]


# Legacy function for backward compatibility
def render_dashboard(
    stored_metadata: list, edit_components_button: bool, dashboard_id: str, theme: str, TOKEN: str
) -> List[dict]:
    """
    Legacy function maintained for backward compatibility.
    Redirects to the new minimal restore approach.
    """
    logger.warning(
        "🔄 RESTORE: Using legacy render_dashboard function - consider updating to restore_dashboard_minimal"
    )

    # For now, return empty dashboard message
    # In a full implementation, you would convert legacy data to new structure
    return [create_empty_dashboard_message()]


def load_depictio_data_sync(
    dashboard_id: str, local_data: dict, theme: str = "light"
) -> DashboardLoadResponse:
    """
    Load dashboard data and render it using the new Pydantic structure.

    Args:
        dashboard_id (str): The ID of the dashboard to load
        local_data (dict): Local data containing access token
        theme (str): Theme to use for rendering

    Returns:
        DashboardLoadResponse: Pydantic model with dashboard data and UI components
    """
    logger.info(f"🔄 RESTORE: Loading dashboard {dashboard_id} with Pydantic structure")

    try:
        from depictio.api.v1.configs.config import settings
        from depictio.dash.api_calls import api_call_fetch_user_from_token, api_call_get_dashboard
        from depictio.models.models.dashboards import DashboardData

        # Rebuild the model to resolve forward references
        DashboardLoadResponse.model_rebuild()

        # Validate inputs
        if not local_data.get("access_token"):
            logger.warning("Access token not found.")
            return DashboardLoadResponse(
                dashboard_data=None,
                edit_components_button=False,
                theme=theme,
            )

        if not theme or theme == {} or theme == "{}":
            theme = "light"

        # Fetch dashboard data from API
        dashboard_data_dict = api_call_get_dashboard(dashboard_id, local_data["access_token"])
        if not dashboard_data_dict:
            logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
            raise ValueError(f"Failed to fetch dashboard data: {dashboard_id}")

        # Convert to Pydantic model
        dashboard_data = DashboardData.from_mongo(dashboard_data_dict)
        logger.info(f"🔄 RESTORE: Loaded dashboard version {dashboard_data.version}")

        # Ensure dashboard has the new structure
        dashboard_data.ensure_default_tab()

        # Get current user and determine permissions
        current_user = api_call_fetch_user_from_token(local_data["access_token"])

        # Check permissions
        owner = str(current_user.id) in [str(e.id) for e in dashboard_data.permissions.owners]
        viewer_ids = [str(e.id) for e in dashboard_data.permissions.viewers]
        is_viewer = str(current_user.id) in viewer_ids
        has_wildcard = "*" in dashboard_data.permissions.viewers
        viewer = is_viewer or has_wildcard

        # Determine edit mode based on permissions
        if not owner and viewer:
            edit_components_button = False
        else:
            edit_components_button = dashboard_data.buttons_data.get(
                "unified_edit_mode",
                dashboard_data.buttons_data.get("edit_components_button", False),
            )

        # Handle unauthenticated mode restrictions
        if settings.auth.unauthenticated_mode:
            if (
                hasattr(current_user, "is_anonymous")
                and current_user.is_anonymous
                and not getattr(current_user, "is_temporary", False)
            ):
                edit_components_button = False
            elif getattr(current_user, "is_temporary", False) and not owner:
                edit_components_button = False
        else:
            if not owner and not viewer:
                edit_components_button = False

        # Restore dashboard using new Pydantic structure
        ui_components = restore_dashboard_minimal(dashboard_data, dashboard_id)

        logger.info(
            f"🔄 RESTORE: Successfully loaded dashboard with {len(ui_components)} components"
        )

        # Return Pydantic model (UI rendering handled separately)
        return DashboardLoadResponse(
            dashboard_data=dashboard_data,
            edit_components_button=edit_components_button,
            theme=theme,
        )

    except Exception as e:
        logger.error(f"🔄 RESTORE: Error in load_depictio_data_sync: {e}")

        # Return error response as Pydantic model
        return DashboardLoadResponse(
            dashboard_data=None,
            edit_components_button=False,
            theme=theme,
        )
