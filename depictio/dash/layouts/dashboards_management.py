"""
Dashboard Management Module

This module provides the landing page and management interface for dashboards
in the Depictio application. It handles:
- Listing and displaying user-owned and accessible dashboards
- Creating new dashboards with customizable icons and settings
- Editing dashboard names and duplicating existing dashboards
- Deleting dashboards with confirmation dialogs
- Managing dashboard visibility (public/private status)

The module is organized into:
- Database interaction functions (load, insert, delete, edit)
- UI rendering functions for dashboard cards and sections
- Callback registration for user interactions
"""

import os
import shutil
from datetime import datetime

import dash
import dash_mantine_components as dmc
import httpx
from bson import ObjectId
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, api_get_project_from_id
from depictio.dash.colors import colors  # Import Depictio color palette
from depictio.dash.layouts.layouts_toolbox import (
    create_dashboard_modal,
    create_delete_confirmation_modal,
    create_edit_dashboard_modal,
    get_workflow_icon_color,
    get_workflow_icon_mapping,
)
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission

modal, modal_id = create_dashboard_modal()

layout = html.Div(
    [
        dcc.Store(id="dashboard-modal-store", storage_type="session", data={"title": ""}),
        dcc.Store(id="init-create-dashboard-button", storage_type="memory", data=False),
        modal,
        html.Div(id="landing-page"),  # Initially hidden
    ]
)


def load_dashboards_from_db(token: str) -> dict:
    """
    Load all accessible dashboards from the database via API.

    Args:
        token: Authentication token for API access.

    Returns:
        dict: Dictionary with 'dashboards' key containing list of dashboard data.

    Raises:
        ValueError: If token is not provided or API request fails.
    """
    if not token:
        raise ValueError("Token is required to load dashboards from the database.")

    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/list",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code == 200:
            dashboards = response.json()

            return {"dashboards": dashboards}

        else:
            raise ValueError(f"Failed to load dashboards from the database. Error: {response.text}")

    except Exception as e:
        logger.error(f"Error loading dashboards from the database: {e}")
        return {"dashboards": []}


def get_child_tabs_info(dashboard_id: str, token: str) -> dict:
    """
    Get information about child tabs for a dashboard.

    Args:
        dashboard_id: Parent dashboard ID to query child tabs for.
        token: Authentication token for API access.

    Returns:
        dict: Dictionary with 'count' (number of tabs) and 'tabs' (list of tab info).
    """
    if not token:
        logger.debug(f"No token provided for dashboard {dashboard_id}")
        return {"count": 0, "tabs": []}

    try:
        # Query all dashboards with include_child_tabs=True to get all tabs
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/list",
            headers={"Authorization": f"Bearer {token}"},
            params={"include_child_tabs": True},
        )

        if response.status_code == 200:
            all_dashboards = response.json()
            logger.debug(f"Fetched {len(all_dashboards)} total dashboards for tab filtering")

            # Filter child tabs that belong to this parent dashboard
            child_tabs = [
                d
                for d in all_dashboards
                if str(d.get("parent_dashboard_id")) == str(dashboard_id)
                and not d.get("is_main_tab", True)
            ]

            logger.debug(f"Found {len(child_tabs)} child tabs for parent dashboard {dashboard_id}")

            # Sort by tab_order
            child_tabs.sort(key=lambda x: x.get("tab_order", 0))

            return {
                "count": len(child_tabs),
                "tabs": [
                    {
                        "_id": tab.get("_id"),
                        "dashboard_id": tab.get("dashboard_id"),
                        "title": tab.get("title", "Untitled Tab"),
                        "tab_order": tab.get("tab_order", 0),
                    }
                    for tab in child_tabs
                ],
            }
        else:
            logger.warning(f"Failed to fetch child tabs: {response.status_code}")
            return {"count": 0, "tabs": []}

    except Exception as e:
        logger.error(f"Error getting child tabs info: {e}")
        return {"count": 0, "tabs": []}


def insert_dashboard(dashboard_id: str | PyObjectId, dashboard_data: dict, token: str) -> None:
    """
    Insert or update a dashboard in the database via API.

    Args:
        dashboard_id: Unique identifier for the dashboard (str or PyObjectId).
        dashboard_data: Dashboard configuration and content data.
        token: Authentication token for API access.

    Raises:
        ValueError: If required parameters are missing or API request fails.
    """
    logger.info(f"Inserting dashboard with ID: {dashboard_id} and data: {dashboard_data}")
    if not token:
        raise ValueError("Token is required to insert a dashboard into the database.")

    if not dashboard_data:
        raise ValueError("Dashboard data is required to insert a dashboard into the database.")

    if not dashboard_id:
        raise ValueError("Dashboard ID is required to insert a dashboard into the database.")
    dashboard_data = convert_objectid_to_str(dashboard_data)
    logger.debug(f"Inserting dashboard with ID: {dashboard_id} and data: {dashboard_data}")

    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
        headers={"Authorization": f"Bearer {token}"},
        json=dashboard_data,
    )

    if response.status_code == 200:
        logger.info(f"Successfully inserted dashboard: {dashboard_data}")

    else:
        raise ValueError(f"Failed to insert dashboard into the database. Error: {response.text}")


def delete_dashboard(dashboard_id: str, token: str) -> None:
    """
    Delete a dashboard from the database via API.

    Args:
        dashboard_id: Unique identifier of the dashboard to delete.
        token: Authentication token for API access.

    Raises:
        ValueError: If API request fails.
    """
    logger.info(f"Deleting dashboard with ID: {dashboard_id}")
    response = httpx.delete(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/delete/{dashboard_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code == 200:
        logger.info(f"Successfully deleted dashboard with ID: {dashboard_id}")

    else:
        raise ValueError(f"Failed to delete dashboard from the database. Error: {response.text}")


def edit_dashboard(
    dashboard_id: str,
    updates: dict,
    dashboards: list,
    token: str,
) -> list:
    """
    Edit dashboard properties and update in database.

    Args:
        dashboard_id: Unique identifier of the dashboard to edit.
        updates: Dictionary with fields to update (title, subtitle, icon, icon_color, workflow_system).
        dashboards: List of dashboard objects to update locally.
        token: Authentication token for API access.

    Returns:
        list: Updated list of dashboards with the edited dashboard.

    Raises:
        ValueError: If API request fails.
    """
    logger.info(f"Editing dashboard for dashboard ID: {dashboard_id}")
    logger.debug(f"Updates: {updates}")

    # Update local dashboard objects
    editable_fields = ("title", "subtitle", "icon", "icon_color", "workflow_system")
    for dashboard in dashboards:
        if str(dashboard.dashboard_id) == str(dashboard_id):
            logger.debug(f"Found dashboard to edit: {dashboard}")
            for field in editable_fields:
                if field in updates:
                    setattr(dashboard, field, updates[field])

    # Persist to database
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/edit/{dashboard_id}",
        headers={"Authorization": f"Bearer {token}"},
        json=updates,
    )

    if response.status_code != 200:
        raise ValueError(f"Failed to edit dashboard in the database. Error: {response.text}")

    logger.info(f"Successfully edited dashboard: {dashboard_id}")
    return dashboards


def render_welcome_section(email: str, is_anonymous: bool = False) -> dmc.Grid:
    """
    Render the welcome section with user avatar and create dashboard button.

    Args:
        email: User's email address for display and avatar.
        is_anonymous: Whether the user is anonymous (disables create button).

    Returns:
        dmc.Grid: Welcome section layout component.
    """
    # Check if user is anonymous and disable button accordingly
    button_disabled = is_anonymous
    button_text = "+ New Dashboard" if not is_anonymous else "Login to Create Dashboards"
    button_variant = "gradient" if not is_anonymous else "outline"
    button_color = {"from": "black", "to": "grey", "deg": 135} if not is_anonymous else "gray"

    return dmc.Grid(
        children=[
            dmc.GridCol(
                dcc.Link(
                    dmc.Tooltip(
                        dmc.Avatar(
                            src=f"https://ui-avatars.com/api/?format=svg&name={email}&background=AEC8FF&color=white&rounded=true&bold=true&format=svg&size=16",
                            size="lg",
                            radius="xl",
                        ),
                        withinPortal=False,
                        label=email,
                        position="bottom",
                    ),
                    href="/profile",
                ),
                span="auto",
            ),
            dmc.GridCol(
                [
                    dmc.Title(
                        f"Welcome, {email}!", order=2, ta="center"
                    ),  # align -> ta in DMC 2.0+
                    dmc.Center(
                        dmc.Button(
                            button_text,
                            id={"type": "create-dashboard-button", "index": email},
                            n_clicks=0,
                            variant=button_variant,
                            gradient=button_color if not is_anonymous else None,
                            color="gray" if is_anonymous else None,
                            style={"margin": "20px 0", "fontFamily": "Virgil"},
                            size="xl",
                            disabled=button_disabled,
                        ),
                    ),
                    dmc.Divider(style={"margin": "20px 0"}),
                    dmc.Title("Your Dashboards", order=3),
                    dmc.Divider(style={"margin": "20px 0"}),
                ],
                span="auto",
                style={"flex": "1"},
            ),
        ],
        gutter="xl",
    )


def render_dashboard_list_section(email: str) -> html.Div:
    """
    Render the container for the dashboard list.

    Args:
        email: User's email used as index for the component ID.

    Returns:
        html.Div: Container div for dashboard list content.
    """
    return html.Div(
        id={"type": "dashboard-list", "index": email},
        style={
            "padding": "30px",  # Consistent padding with header
            "minHeight": "calc(100vh - 80px)",  # Full height minus header (80px)
        },
    )


def register_callbacks_dashboards_management(app: dash.Dash) -> None:
    """
    Register all Dash callbacks for dashboard management functionality.

    Registers callbacks for:
    - Dashboard listing and filtering
    - Dashboard creation, deletion, and renaming
    - Dashboard card rendering and interactions
    - Modal dialogs for dashboard operations

    Args:
        app: The Dash application instance to register callbacks with.
    """

    def create_dashboards_view(dashboards: list) -> list:
        """
        Create a list view of dashboards as styled Paper components.

        Generates a simple list view of dashboards with basic information
        (title, version, owner) and action buttons (View, Delete).

        Args:
            dashboards: List of dashboard dictionaries containing dashboard
                metadata including title, version, permissions, and dashboard_id.

        Returns:
            list: List of dmc.Paper components, each representing a dashboard
                with its information and action buttons in a horizontal layout.
        """
        logger.debug(f"dashboards: {dashboards}")

        dashboards_view = [
            dmc.Paper(
                dmc.Group(
                    [
                        html.Div(
                            [
                                dmc.Center(dmc.Title(dashboard["title"], order=5)),
                                # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                                dmc.Text(f"Version: {dashboard['version']}"),
                                dmc.Text(
                                    f"Owner: {dashboard['permissions']['owners'][0]['email']}"
                                ),
                            ],
                            style={"flex": "1"},
                        ),
                        html.A(
                            dmc.Button(
                                "View",
                                id={
                                    "type": "view-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color="blue",
                            ),
                            href=f"/dashboard/{dashboard['dashboard_id']}",
                        ),
                        dmc.Button(
                            "Delete",
                            id={
                                "type": "delete-dashboard-button",
                                "index": dashboard["dashboard_id"],
                            },
                            variant="outline",
                            color="red",
                        ),
                    ],
                    align="center",
                    justify="space-between",
                    grow=False,
                    noWrap=False,
                    style={"width": "100%"},
                ),
                shadow="xs",
                p="md",
                style={"marginBottom": 20},
            )
            for dashboard in dashboards
        ]
        return dashboards_view

    def create_homepage_view(dashboards, user_id, token, current_user):
        """
        Create the main homepage view displaying all accessible dashboards.

        Renders the complete dashboard management homepage with dashboards
        organized into two sections: owned dashboards and accessed dashboards.
        Each dashboard is displayed as a card with thumbnail, metadata badges,
        and action buttons (view, edit, duplicate, delete, privacy toggle).

        This function orchestrates the rendering of dashboard cards by:
        1. Categorizing dashboards into owned vs accessed based on user_id
        2. Generating dashboard cards with thumbnails and action buttons
        3. Organizing cards into responsive grid layouts
        4. Caching project lookups to minimize API calls

        Args:
            dashboards: List of dashboard dictionaries containing full dashboard
                data including permissions, project_id, title, and customization.
            user_id: The current user's ID used to determine ownership status
                and enable/disable edit controls.
            token: Authentication token for API calls (e.g., project lookups).
            current_user: User object containing user context information
                including is_anonymous flag for permission checks.

        Returns:
            html.Div: Complete homepage layout with two sections:
                - Owned Dashboards: Dashboards where user is an owner
                - Accessed Dashboards: Dashboards user can view but doesn't own
                Both sections use responsive SimpleGrid layouts that adjust
                columns based on screen size (1/2/3 columns).
        """
        # Create project cache to avoid redundant API calls
        project_cache = {}

        def modal_edit_dashboard(dashboard):
            """
            Create a modal dialog for editing a dashboard's properties.

            Generates a comprehensive modal for editing all dashboard properties:
            title, subtitle, icon, icon_color, and workflow_system.

            Args:
                dashboard: Dashboard dictionary containing dashboard properties
                    including dashboard_id, title, subtitle, icon, icon_color,
                    and workflow_system.

            Returns:
                dmc.Modal: A Mantine modal component with full edit capabilities.
                    The modal uses pattern-matching IDs based on dashboard_id
                    for callback routing.
            """
            modal, _ = create_edit_dashboard_modal(
                dashboard_id=dashboard["dashboard_id"],
                title=dashboard.get("title", ""),
                subtitle=dashboard.get("subtitle", ""),
                icon=dashboard.get("icon", "mdi:view-dashboard"),
                icon_color=dashboard.get("icon_color", "orange"),
                workflow_system=dashboard.get("workflow_system", "none"),
                opened=False,
            )
            return modal

        def create_dashboad_view_header(dashboard, user_id, token):
            """
            Create the header section of a dashboard card.

            Generates the visual header for a dashboard card including:
            - Dashboard icon (either Iconify icon or workflow logo image)
            - Dashboard title and optional subtitle
            - Metadata badges for project, owner, and public/private status

            The header uses visual indicators to show ownership (blue badge
            for owned dashboards, gray for others) and visibility status
            (green for public, purple for private).

            Args:
                dashboard: Dashboard dictionary containing:
                    - is_public: Boolean visibility status
                    - permissions.owners: List of owner user objects
                    - project_id: ID of associated project
                    - title: Dashboard title text
                    - icon: Icon identifier (Iconify string or asset path)
                    - icon_color: Color for the icon display
                    - subtitle: Optional subtitle text
                user_id: Current user's ID for ownership badge coloring.
                token: Authentication token for project name API lookup.

            Returns:
                html.Div: Header component containing:
                    - Icon display (ActionIcon or html.Img for workflow logos)
                    - Title and subtitle text
                    - Stack of badges (Project, Owner, Public/Private status)
            """
            public = dashboard["is_public"]

            if str(user_id) in [str(owner["_id"]) for owner in dashboard["permissions"]["owners"]]:
                color_badge_ownership = colors["blue"]  # Use Depictio blue
            else:
                color_badge_ownership = "gray"
            badge_icon = "material-symbols:public" if public else "material-symbols:lock"

            # Owner badge with tooltip
            owner_email = dashboard["permissions"]["owners"][0]["email"]
            badge_owner = dmc.Tooltip(
                label=f"Owner: {owner_email}",
                children=dmc.Badge(
                    f"Owner: {owner_email}",
                    color=color_badge_ownership,
                    leftSection=DashIconify(icon="mdi:account", width=16, color="white"),
                    style={
                        "maxWidth": "100%",
                        "overflow": "hidden",
                        "textOverflow": "ellipsis",
                        "whiteSpace": "nowrap",
                    },
                ),
            )

            # Use project cache to avoid redundant API calls
            project_id_str = str(dashboard["project_id"])
            if project_id_str in project_cache:
                project_name = project_cache[project_id_str]
            else:
                response = api_get_project_from_id(project_id=dashboard["project_id"], token=token)
                if response.status_code == 200:
                    project = response.json()
                    project_name = project["name"]
                    project_cache[project_id_str] = project_name  # Cache for next use
                else:
                    logger.error(f"Failed to get project from ID: {dashboard['project_id']}")
                    project_name = "Unknown"
                    project_cache[project_id_str] = project_name  # Cache the failure too

            # Project badge with tooltip
            badge_project = dmc.Tooltip(
                label=f"Project: {project_name}",
                children=dmc.Badge(
                    f"Project: {project_name}",
                    color=colors["teal"],  # Use Depictio teal instead of green
                    leftSection=DashIconify(icon="mdi:jira", width=16, color="white"),
                    style={
                        "maxWidth": "100%",
                        "overflow": "hidden",
                        "textOverflow": "ellipsis",
                        "whiteSpace": "nowrap",
                    },
                ),
            )

            # Status badge with tooltip
            status_text = "Public" if public else "Private"
            badge_status = dmc.Tooltip(
                label=f"Visibility: {status_text}",
                children=dmc.Badge(
                    status_text,
                    color=colors["green"] if public else colors["purple"],  # Use Depictio colors
                    leftSection=DashIconify(icon=badge_icon, width=16, color="white"),
                ),
            )

            # Create last modified badge with tooltip
            last_modified = "Never"
            if dashboard.get("last_saved_ts"):
                try:
                    # Parse ISO format timestamp
                    dt = datetime.fromisoformat(dashboard["last_saved_ts"].replace("Z", "+00:00"))
                    last_modified = dt.strftime("%Y-%m-%d %H:%M")
                except Exception as e:
                    logger.warning(f"Failed to parse last_saved_ts: {e}")
                    last_modified = dashboard["last_saved_ts"]

            badge_last_modified = dmc.Tooltip(
                label=f"Last modified: {last_modified}",
                children=dmc.Badge(
                    f"Modified: {last_modified}",
                    color="gray",
                    variant="light",
                    leftSection=DashIconify(icon="mdi:clock-outline", width=16),
                ),
            )

            # Tab count badge (only show when > 1 total tab)
            tabs_info = get_child_tabs_info(str(dashboard["dashboard_id"]), token)
            child_tab_count = tabs_info["count"]  # Number of child tabs only

            # Total tabs = 1 (main) + child tabs count
            total_tab_count = 1 + child_tab_count

            logger.debug(
                f"Dashboard {dashboard['dashboard_id']}: "
                f"Found {child_tab_count} child tabs, total {total_tab_count} tabs"
            )

            # Only show badge when total > 1 (i.e., when there are child tabs)
            if total_tab_count > 1:
                badge_tab_count = dmc.Badge(
                    f"{total_tab_count} Tab{'s' if total_tab_count > 1 else ''}",
                    color=colors["orange"],
                    variant="light",
                    leftSection=DashIconify(icon="mdi:tab", width=16),
                )
            else:
                badge_tab_count = None

            # badge_tooltip_additional_info = dmc.HoverCard(
            #     [
            #         dmc.HoverCardTarget(
            #             dmc.Badge(
            #                 "Additional Info",
            #                 color="gray",
            #                 leftSection=DashIconify(
            #                     icon="material-symbols:info-outline",
            #                     width=16,
            #                     color="gray",
            #                 ),
            #             )
            #         ),
            #         dmc.HoverCardDropdown(
            #             [
            #                 dmc.Text(f"Dashboard ID: {dashboard['dashboard_id']}"),
            #                 dmc.Text(f"Last Modified: {dashboard['last_saved_ts']}"),
            #                 # dmc.Text(f"Version: {str(dashboard['version'])}"),
            #             ],
            #             style={"padding": "10px"},
            #         ),
            #     ]
            # )

            # Get dashboard customization fields with defaults
            dashboard_icon = dashboard.get("icon", "mdi:view-dashboard")
            dashboard_icon_color = dashboard.get("icon_color", "orange")
            dashboard_subtitle = dashboard.get("subtitle", "")

            # Icon button always uses filled variant
            icon_button_props = {
                "color": dashboard_icon_color,
                "radius": "xl",
                "size": "lg",
                "variant": "filled",
            }

            # Check if icon is an image path or Iconify icon
            if dashboard_icon and dashboard_icon.startswith("/assets/"):
                # Use html.Img for workflow logos
                icon_display = html.Img(
                    src=dashboard_icon,
                    style={
                        "width": "48px",
                        "height": "48px",
                        "objectFit": "contain",
                        "borderRadius": "50%",
                        "padding": "4px",
                    },
                )
            else:
                # Use DashIconify for regular icons
                icon_display = dmc.ActionIcon(
                    DashIconify(icon=dashboard_icon, width=24, height=24),
                    **icon_button_props,
                )

            group = html.Div(
                [
                    dmc.Space(h=10),
                    dmc.Group(
                        [
                            # Custom icon display
                            icon_display,
                            html.Div(
                                [
                                    dmc.Title(
                                        f"{dashboard['title']}",
                                        # f"{dashboard['title']} - {str(dashboard['dashboard_id'])}",
                                        order=4,  # Slightly smaller title (order=4 instead of 3)
                                        style={
                                            "maxWidth": "100%",
                                            "overflow": "visible",
                                            "whiteSpace": "normal",
                                            "wordWrap": "break-word",
                                            "marginBottom": "4px" if dashboard_subtitle else "0",
                                        },  # Allow title wrapping
                                        # ta="center",  # Center align the title
                                    ),
                                    # Subtitle
                                    dmc.Text(
                                        dashboard_subtitle,
                                        size="sm",
                                        c="gray",
                                        style={
                                            "maxWidth": "100%",
                                            "overflow": "visible",
                                            "whiteSpace": "normal",
                                            "wordWrap": "break-word",
                                        },
                                    )
                                    if dashboard_subtitle
                                    else None,
                                    # dmc.Title(dashboard["title"], order=5),
                                    # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                                    # dmc.Text(f"Version: {dashboard['version']}"),
                                    # dmc.Text(f"Owner: {dashboard['permissions']['owners'][0]['email']}"),
                                ],
                                style={"flex": "1"},
                            ),
                        ],
                        align="center",
                    ),
                    dmc.Space(h=10),
                    dmc.Stack(
                        children=[
                            item
                            for item in [
                                badge_project,
                                badge_owner,
                                badge_status,
                                badge_last_modified,
                                badge_tab_count,
                                # badge_tooltip_additional_info,
                            ]
                            if item is not None
                        ],
                        justify="center",
                        align="flex-start",
                        gap=4,  # Minimal gap between badges (4px instead of xs=10px)
                    ),
                    dmc.Space(h=10),
                ]
            )
            return group

        def create_buttons(dashboard, user_id, current_user):
            """
            Create the action buttons for a dashboard card.

            Generates a group of buttons for dashboard operations including
            View, Edit name, Duplicate, Delete, and Privacy toggle. Buttons
            are conditionally enabled/disabled based on user permissions:
            - Non-owners cannot edit, delete, or toggle privacy
            - Anonymous users cannot duplicate dashboards

            Args:
                dashboard: Dashboard dictionary containing:
                    - dashboard_id: Unique identifier for button IDs
                    - permissions.owners: List of owner objects for permission check
                    - is_public: Current visibility status for privacy button text
                user_id: Current user's ID for ownership permission check.
                current_user: User object with is_anonymous and is_temporary
                    attributes for anonymous user detection.

            Returns:
                html.Div: Container with a dmc.Group of action buttons:
                    - View: Link to dashboard page (always enabled)
                    - Edit name: Opens rename modal (owner only)
                    - Duplicate: Creates dashboard copy (authenticated users)
                    - Delete: Opens delete confirmation (owner only)
                    - Privacy toggle: Switches public/private (owner only, hidden)
                    All buttons use pattern-matching IDs with dashboard_id index.
            """
            disabled = (
                True
                if str(user_id)
                not in [str(owner["_id"]) for owner in dashboard["permissions"]["owners"]]
                else False
            )

            # Disable duplicate button for anonymous users in unauthenticated mode
            duplicate_disabled = (
                settings.auth.unauthenticated_mode
                and hasattr(current_user, "is_anonymous")
                and current_user.is_anonymous
                and not getattr(current_user, "is_temporary", False)
            )
            public = dashboard["is_public"]
            # public = True if "*" in [e for e in dashboard["permissions"]["viewers"]] else False
            privacy_button_title = "Make private" if public else "Make public"
            color_privacy_button = (
                colors["purple"] if public else colors["green"]
            )  # Use Depictio colors

            group = html.Div(
                [
                    dmc.Group(
                        [
                            html.A(
                                dmc.Button(
                                    "View",
                                    id={
                                        "type": "view-dashboard-button",
                                        "index": dashboard["dashboard_id"],
                                    },
                                    variant="outline",
                                    color=colors["blue"],  # Use Depictio blue
                                    size="xs",
                                    style={"padding": "2px 4px", "fontSize": "11px"},
                                ),
                                href=f"/dashboard/{dashboard['dashboard_id']}",
                            ),
                            dmc.Button(
                                "Edit",
                                id={
                                    "type": "edit-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color=colors["teal"],  # Use Depictio teal
                                disabled=disabled,
                                size="xs",
                                style={"padding": "2px 4px", "fontSize": "11px"},
                            ),
                            dmc.Button(
                                "Duplicate",
                                id={
                                    "type": "duplicate-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color=colors["pink"],  # Use Depictio gray
                                size="xs",
                                style={"padding": "2px 4px", "fontSize": "11px"},
                                disabled=duplicate_disabled,
                            ),
                            dmc.Button(
                                "Delete",
                                id={
                                    "type": "delete-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color=colors["red"],  # Use Depictio red
                                disabled=disabled,
                                size="xs",
                                style={"padding": "2px 4px", "fontSize": "11px"},
                            ),
                            dmc.Button(
                                privacy_button_title,
                                id={
                                    "type": "make-public-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color=color_privacy_button,
                                disabled=disabled,
                                size="xs",
                                style={"padding": "2px 4px", "fontSize": "11px", "display": "none"},
                            ),
                        ],
                        gap="xs",
                    ),
                ]
            )
            return group

        def return_thumbnail(user_id, dashboard, total_tab_count=1, child_tabs=None):
            """
            Generate the thumbnail image section for a dashboard card.

            Creates a clickable thumbnail display for a dashboard. If a
            screenshot exists in the static/screenshots folder, displays it
            with proper sizing and object-fit for 16:9 aspect ratio images.
            Otherwise, displays a default placeholder image with "No thumbnail
            available" text.

            When total_tab_count > 1, creates a Carousel with all tab thumbnails
            instead of a single image.

            The thumbnail is wrapped in a link to the dashboard view page,
            allowing users to click the image to open the dashboard.

            Args:
                user_id: Current user's ID (currently unused, kept for
                    potential future per-user thumbnail support).
                dashboard: Dashboard dictionary containing:
                    - _id: MongoDB ObjectId used for thumbnail filename
                    - dashboard_id: Used for the navigation link URL
                    - title: Used for image alt text
                total_tab_count: Total number of tabs (main + children). Default 1.
                child_tabs: List of child tab dictionaries. Default None.

            Returns:
                html.Div or html.A or dmc.CardSection: Thumbnail component:
                    - If total_tab_count > 1: dmc.CardSection with Carousel of all tabs
                    - If single tab with screenshot: html.A with single image
                    - If no thumbnail: html.Div with default placeholder
            """
            import os

            # If multiple tabs, create a carousel with all tab thumbnails
            if total_tab_count > 1 and child_tabs:
                output_folder = "/app/depictio/dash/static/screenshots"
                default_thumbnail = dash.get_asset_url("images/backgrounds/default_thumbnail.png")

                # Store slide data for both small and large carousels
                slide_data = []

                # Add main dashboard thumbnail as first slide (use dashboard_id for URL consistency)
                main_id = dashboard["_id"]
                main_dashboard_id = dashboard["dashboard_id"]

                # Check for theme-specific screenshots (use dashboard_id to match URL identifier)
                main_light_filename = f"{main_dashboard_id}_light.png"
                main_dark_filename = f"{main_dashboard_id}_dark.png"
                main_legacy_filename = f"{main_dashboard_id}.png"

                main_light_path = os.path.join(output_folder, main_light_filename)
                main_dark_path = os.path.join(output_folder, main_dark_filename)
                main_legacy_path = os.path.join(output_folder, main_legacy_filename)

                # Determine URLs for both themes
                main_light_url = (
                    f"/static/screenshots/{main_light_filename}"
                    if os.path.exists(main_light_path)
                    else None
                )
                main_dark_url = (
                    f"/static/screenshots/{main_dark_filename}"
                    if os.path.exists(main_dark_path)
                    else None
                )

                # Fallback logic
                if not main_light_url and not main_dark_url:
                    if os.path.exists(main_legacy_path):
                        main_light_url = main_dark_url = (
                            f"/static/screenshots/{main_legacy_filename}"
                        )
                    else:
                        main_light_url = main_dark_url = default_thumbnail

                # Use light theme as default initial display
                main_thumbnail_url = main_light_url

                # Store main dashboard data
                slide_data.append(
                    {
                        "id": main_id,
                        "dashboard_id": main_dashboard_id,
                        "title": f"Main: {dashboard['title']}",
                        "thumbnail_url": main_thumbnail_url,
                        "light_url": main_light_url,
                        "dark_url": main_dark_url,
                        "href": f"/dashboard/{dashboard['dashboard_id']}",
                    }
                )

                # Add child tab thumbnails
                for tab in child_tabs:
                    tab_id = tab.get("_id", tab.get("dashboard_id"))
                    tab_title = tab.get("title", "Untitled Tab")
                    tab_dashboard_id = tab.get("dashboard_id")

                    # Check for theme-specific screenshots (use dashboard_id for URL consistency)
                    tab_light_filename = f"{tab_dashboard_id}_light.png"
                    tab_dark_filename = f"{tab_dashboard_id}_dark.png"
                    tab_legacy_filename = f"{tab_dashboard_id}.png"

                    tab_light_path = os.path.join(output_folder, tab_light_filename)
                    tab_dark_path = os.path.join(output_folder, tab_dark_filename)
                    tab_legacy_path = os.path.join(output_folder, tab_legacy_filename)

                    # Determine URLs for both themes
                    tab_light_url = (
                        f"/static/screenshots/{tab_light_filename}"
                        if os.path.exists(tab_light_path)
                        else None
                    )
                    tab_dark_url = (
                        f"/static/screenshots/{tab_dark_filename}"
                        if os.path.exists(tab_dark_path)
                        else None
                    )

                    # Fallback logic
                    if not tab_light_url and not tab_dark_url:
                        if os.path.exists(tab_legacy_path):
                            tab_light_url = tab_dark_url = (
                                f"/static/screenshots/{tab_legacy_filename}"
                            )
                        else:
                            tab_light_url = tab_dark_url = default_thumbnail

                    # Use light theme as default initial display
                    tab_thumbnail_url = tab_light_url

                    # Store tab data
                    slide_data.append(
                        {
                            "id": tab_id,
                            "dashboard_id": tab_dashboard_id,
                            "title": f"Tab: {tab_title}",
                            "thumbnail_url": tab_thumbnail_url,
                            "light_url": tab_light_url,
                            "dark_url": tab_dark_url,
                            "href": f"/dashboard/{tab_dashboard_id}",
                        }
                    )

                # Build small carousel slides for card display
                carousel_slides = []
                for data in slide_data:
                    carousel_slides.append(
                        dmc.CarouselSlide(
                            html.A(
                                html.Div(
                                    dmc.Image(
                                        src=data["thumbnail_url"],
                                        style={
                                            "width": "100%",
                                            "height": "210px",
                                            "objectFit": "cover",
                                            "objectPosition": "center center",
                                        },
                                        alt=data["title"],
                                    ),
                                    **{
                                        "data-dashboard-id": data["id"],
                                        "data-light-src": data["light_url"],
                                        "data-dark-src": data["dark_url"],
                                    },
                                ),
                                href=data["href"],
                                style={"textDecoration": "none"},
                            )
                        )
                    )

                # Build large carousel slides for tooltip (same data, bigger dimensions)
                large_carousel_slides = []
                for data in slide_data:
                    large_carousel_slides.append(
                        dmc.CarouselSlide(
                            html.Div(
                                [
                                    dmc.Image(
                                        src=data["thumbnail_url"],
                                        style={
                                            "width": "600px",
                                            "height": "400px",
                                            "objectFit": "cover",
                                            "objectPosition": "center center",
                                        },
                                        alt=data["title"],
                                    ),
                                    # Text overlay with tab name (bottom left to avoid carousel indicators)
                                    html.Div(
                                        data["title"],
                                        style={
                                            "position": "absolute",
                                            "bottom": "12px",
                                            "left": "12px",
                                            "backgroundColor": "rgba(0, 0, 0, 0.75)",
                                            "color": "white",
                                            "padding": "8px 12px",
                                            "fontSize": "14px",
                                            "fontWeight": "500",
                                            "borderRadius": "6px",
                                            "backdropFilter": "blur(8px)",
                                            "maxWidth": "calc(100% - 120px)",  # Leave space for indicators
                                            "overflow": "hidden",
                                            "textOverflow": "ellipsis",
                                            "whiteSpace": "nowrap",
                                        },
                                    ),
                                ],
                                **{
                                    "data-dashboard-id": data["id"],
                                    "data-light-src": data["light_url"],
                                    "data-dark-src": data["dark_url"],
                                },
                                style={"position": "relative"},
                            )
                        )
                    )

                # Return carousel wrapped in HoverCard with larger carousel, then CardSection
                return dmc.CardSection(
                    dmc.HoverCard(
                        withArrow=True,
                        position="right",
                        offset=10,
                        shadow="md",
                        openDelay=300,
                        closeDelay=200,
                        children=[
                            dmc.HoverCardTarget(
                                dmc.Carousel(
                                    children=carousel_slides,
                                    withIndicators=True,
                                    withControls=True,
                                    height=210,
                                    style={"borderRadius": "8px 8px 0 0", "cursor": "pointer"},
                                )
                            ),
                            dmc.HoverCardDropdown(
                                dmc.Carousel(
                                    children=large_carousel_slides,
                                    withIndicators=True,
                                    withControls=True,
                                    height=400,
                                    style={
                                        "width": "600px",
                                        "borderRadius": "8px",
                                    },
                                ),
                                style={"padding": 0},
                            ),
                        ],
                    ),
                    withBorder=True,
                )

            # Define the output folder where screenshots are saved
            output_folder = "/app/depictio/dash/static/screenshots"
            dashboard_id_str = dashboard["dashboard_id"]  # Use dashboard_id to match URL identifier

            # Check for theme-specific screenshots (use dashboard_id for URL consistency)
            light_filename = f"{dashboard_id_str}_light.png"
            dark_filename = f"{dashboard_id_str}_dark.png"
            legacy_filename = f"{dashboard_id_str}.png"

            light_path = os.path.join(output_folder, light_filename)
            dark_path = os.path.join(output_folder, dark_filename)
            legacy_path = os.path.join(output_folder, legacy_filename)

            # Determine URLs for both themes
            light_url = (
                f"/static/screenshots/{light_filename}" if os.path.exists(light_path) else None
            )
            dark_url = f"/static/screenshots/{dark_filename}" if os.path.exists(dark_path) else None

            # Fallback logic
            if not light_url and not dark_url:
                # Try legacy single screenshot
                if os.path.exists(legacy_path):
                    light_url = dark_url = f"/static/screenshots/{legacy_filename}"
                else:
                    # Use default placeholder
                    default_url = dash.get_asset_url("images/backgrounds/default_thumbnail.png")
                    light_url = dark_url = default_url

            # Use light theme as default initial display
            thumbnail_url = light_url

            # Check if we have a valid thumbnail (not default placeholder)
            has_thumbnail = (
                os.path.exists(light_path)
                or os.path.exists(dark_path)
                or os.path.exists(legacy_path)
            )

            if not has_thumbnail:
                logger.warning(
                    f"Thumbnail not found for dashboard {dashboard_id_str} "
                    f"(checked: {light_filename}, {dark_filename}, {legacy_filename})"
                )
                default_thumbnail_url = light_url  # Already set to default in fallback logic

                thumbnail = html.Div(
                    [
                        html.A(
                            dmc.CardSection(
                                html.Div(
                                    [
                                        dmc.Image(
                                            src=default_thumbnail_url,
                                            style={
                                                "width": "180px",
                                                "height": "180px",
                                                "objectFit": "contain",
                                            },
                                            alt="Default dashboard thumbnail",
                                        ),
                                        dmc.Text(
                                            "No thumbnail available",
                                            size="sm",
                                            ta="center",
                                            c="gray",
                                            style={"marginTop": "12px", "fontSize": "13px"},
                                        ),
                                    ],
                                    style={
                                        "width": "100%",
                                        "height": "210px",  # Adjusted for 4-column layout (maintains 16:9 proportions)
                                        "display": "flex",
                                        "flexDirection": "column",
                                        "alignItems": "center",
                                        "justifyContent": "center",
                                        "borderRadius": "8px 8px 0 0",
                                    },
                                ),
                                withBorder=True,
                            ),
                            href=f"/dashboard/{dashboard['dashboard_id']}",
                            style={"textDecoration": "none"},
                        ),
                    ]
                )
            else:
                # Theme-aware thumbnail display with data attributes for clientside theme switching
                thumbnail = html.A(
                    dmc.CardSection(
                        html.Div(
                            dmc.Image(
                                src=thumbnail_url,
                                style={
                                    "width": "100%",
                                    "height": "210px",
                                    "objectFit": "cover",
                                    "objectPosition": "center center",
                                    "borderRadius": "8px 8px 0 0",
                                    "display": "block",
                                },
                                alt=f"Thumbnail for {dashboard['title']}",
                            ),
                            **{
                                "data-dashboard-id": dashboard_id_str,
                                "data-light-src": light_url,
                                "data-dark-src": dark_url,
                            },
                        ),
                        withBorder=True,
                    ),
                    href=f"/dashboard/{dashboard['dashboard_id']}",
                    style={"textDecoration": "none"},
                )

            return thumbnail

        def loop_over_dashboards(user_id, dashboards, token, current_user):
            """
            Generate a list of dashboard card components.

            Iterates over all provided dashboards and creates a complete
            card component for each, assembling the thumbnail, header,
            action buttons (in an accordion), and modal dialogs for
            delete confirmation and name editing.

            Args:
                user_id: Current user's ID for permission checks and
                    ownership display.
                dashboards: List of dashboard dictionaries to render.
                token: Authentication token for API calls during rendering.
                current_user: User object for anonymous user detection
                    and permission validation.

            Returns:
                list: List of dmc.Card components, each containing:
                    - Clickable thumbnail image linking to dashboard
                    - Header with icon, title, subtitle, and badges
                    - Collapsible accordion with action buttons
                    - Delete confirmation modal
                    - Edit name modal
                    Cards are styled with borders, shadows, and flex layout.
            """
            view = list()
            for dashboard in dashboards:
                # delete_modal = modal_delete_dashboard(dashboard)
                delete_modal, delete_modal_id = create_delete_confirmation_modal(
                    id_prefix="dashboard",
                    item_id=dashboard["dashboard_id"],
                    title=f"Delete dashboard : {dashboard['title']}",
                )
                edit_modal = modal_edit_dashboard(dashboard)
                buttons = create_buttons(dashboard, user_id, current_user)
                dashboard_header = create_dashboad_view_header(dashboard, user_id, token)

                # Get tab info for thumbnail carousel
                tabs_info = get_child_tabs_info(str(dashboard["dashboard_id"]), token)
                child_tab_count = tabs_info["count"]
                child_tabs = tabs_info["tabs"]
                total_tab_count = 1 + child_tab_count

                buttons = dmc.Accordion(
                    [
                        dmc.AccordionItem(
                            value="actions",
                            children=[
                                dmc.AccordionControl(
                                    dmc.Group(
                                        [
                                            DashIconify(
                                                icon="mdi:cog-outline",
                                                width=12,  # Even smaller icon
                                                color="#6c757d",  # Subtle gray
                                            ),
                                            dmc.Text(
                                                "Actions",
                                                style={
                                                    "fontSize": "12px",  # Even smaller font
                                                    "fontWeight": "400",
                                                    "color": "#6c757d",
                                                },
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    # style={
                                    #     "minHeight": "24px",  # Very compact height
                                    #     "padding": "2px 6px",  # Minimal padding
                                    # },
                                ),
                                dmc.AccordionPanel(
                                    buttons,
                                    # style={
                                    #     "padding": "4px 6px",  # Very compact padding
                                    # },
                                ),
                            ],
                        ),
                    ],
                    variant="default",
                    # radius="sm",
                    # style={
                    #     "width": "100%",
                    #     "margin": "2px 0",  # Minimal margin
                    #     "border": "1px solid #e9ecef",  # Subtle border only
                    #     # Remove backgroundColor completely
                    # },
                    # chevronPosition="right",
                )

                thumbnail = return_thumbnail(user_id, dashboard, total_tab_count, child_tabs)
                view.append(
                    dmc.Card(
                        withBorder=True,
                        shadow="sm",
                        radius="md",
                        # style={"width": 480},
                        # Remove fixed width to allow flexibility
                        style={
                            "width": "100%",
                            "height": "100%",
                            "display": "flex",
                            "flexDirection": "column",
                        },
                        children=[
                            thumbnail,
                            dmc.Space(h=15),  # Add space between image and title
                            dashboard_header,
                            buttons,
                            delete_modal,
                            edit_modal,
                        ],
                    )
                )
            return view

        def create_empty_state_card(icon: str, title: str, description: str) -> list[dmc.Center]:
            """
            Create an empty state card similar to projects.py.

            Args:
                icon: Iconify icon name
                title: Main title text
                description: Description text

            Returns:
                List containing a centered empty state card
            """
            return [
                dmc.Center(
                    dmc.Paper(
                        children=[
                            dmc.Stack(
                                children=[
                                    dmc.Center(
                                        DashIconify(
                                            icon=icon,
                                            width=64,
                                            height=64,
                                            color="#6c757d",
                                        )
                                    ),
                                    dmc.Text(
                                        title,
                                        ta="center",
                                        fw="bold",
                                        size="xl",
                                    ),
                                    dmc.Text(
                                        description,
                                        ta="center",
                                        c="gray",
                                        size="sm",
                                    ),
                                ],
                                align="center",
                                gap="sm",
                            )
                        ],
                        shadow="sm",
                        radius="md",
                        p="xl",
                        withBorder=True,
                        style={"width": "100%", "maxWidth": "500px"},
                    ),
                    style={"minHeight": "300px", "height": "auto"},
                )
            ]

        # Categorize dashboards with precedence: Example > Public > Accessed > Owned
        # Example dashboards are ONLY those explicitly marked OR owned by example/demo users
        # If current user owns a dashboard, it goes to Owned (not Example) unless explicitly marked

        # Check if current user is anonymous
        is_anonymous = hasattr(current_user, "is_anonymous") and current_user.is_anonymous

        # Example dashboards: explicitly marked by ID OR owned by example/demo users (but NOT current user)
        # Order: ampliseq, penguins, iris
        example_dashboard_ids = [
            "646b0f3c1e4a2d7f8e5b8ca2",  # nf-core/ampliseq
            "6824cb3b89d2b72169309738",  # Penguins Species Analysis
            "6824cb3b89d2b72169309737",  # Iris Species Comparison
        ]
        example_dashboards = [
            d
            for d in dashboards
            if (
                # Explicitly marked as example by ID
                str(d.get("dashboard_id", "")) in example_dashboard_ids
                # OR owned by example/demo user (but not by current user - duplicates go to Owned)
                or (
                    str(user_id) not in [str(owner["_id"]) for owner in d["permissions"]["owners"]]
                    and (
                        any(
                            "example" in owner.get("email", "").lower()
                            or "demo" in owner.get("email", "").lower()
                            for owner in d["permissions"]["owners"]
                        )
                        or d.get("title", "").lower().startswith("example:")
                    )
                )
            )
        ]

        # Sort example dashboards by the order defined in example_dashboard_ids
        example_dashboards.sort(
            key=lambda d: (
                example_dashboard_ids.index(str(d.get("dashboard_id", "")))
                if str(d.get("dashboard_id", "")) in example_dashboard_ids
                else len(example_dashboard_ids)
            )
        )

        example_ids = {str(d.get("dashboard_id", "")) for d in example_dashboards}

        # Public dashboards: public but not in examples
        public_dashboards = [
            d
            for d in dashboards
            if d.get("is_public", False)
            and str(d.get("dashboard_id", "")) not in example_ids
            and str(user_id) not in [str(owner["_id"]) for owner in d["permissions"]["owners"]]
        ]

        # Accessed dashboards: shared with user but not owned, not public, not examples
        accessed_dashboards = [
            d
            for d in dashboards
            if str(user_id) not in [str(owner["_id"]) for owner in d["permissions"]["owners"]]
            and not d.get("is_public", False)
            and str(d.get("dashboard_id", "")) not in example_ids
            and (not is_anonymous or d.get("is_public", False))
        ]

        # Owned dashboards: owned by user but not in examples (lowest precedence)
        owned_dashboards = [
            d
            for d in dashboards
            if str(user_id) in [str(owner["_id"]) for owner in d["permissions"]["owners"]]
            and str(d.get("dashboard_id", "")) not in example_ids
        ]

        # Create views for each category (using same icons as accordion headers)
        owned_dashboards_content = (
            loop_over_dashboards(user_id, owned_dashboards, token, current_user)
            if owned_dashboards
            else create_empty_state_card(
                icon="mdi:account-check",
                title="No owned dashboards",
                description="Create your first dashboard to get started.",
            )
        )

        accessed_dashboards_content = (
            loop_over_dashboards(user_id, accessed_dashboards, token, current_user)
            if accessed_dashboards
            else create_empty_state_card(
                icon="material-symbols:share-outline",
                title="No accessed dashboards",
                description="Dashboards shared with you will appear here.",
            )
        )

        public_dashboards_content = (
            loop_over_dashboards(user_id, public_dashboards, token, current_user)
            if public_dashboards
            else create_empty_state_card(
                icon="mdi:earth",
                title="No public dashboards",
                description="Public dashboards will appear here.",
            )
        )

        example_dashboards_content = (
            loop_over_dashboards(user_id, example_dashboards, token, current_user)
            if example_dashboards
            else create_empty_state_card(
                icon="mdi:school-outline",
                title="No example dashboards",
                description="Example and demo dashboards will appear here.",
            )
        )

        owned_dashboards_view = dmc.SimpleGrid(
            owned_dashboards_content,
            cols={
                "base": 1,
                "sm": 2,
                "lg": 4,
            },
            spacing="xl",
            verticalSpacing="xl",
            style={"width": "100%"},
        )

        accessed_dashboards_view = dmc.SimpleGrid(
            accessed_dashboards_content,
            cols={
                "base": 1,
                "sm": 2,
                "lg": 4,
            },
            spacing="xl",
            verticalSpacing="xl",
            style={"width": "100%"},
        )

        public_dashboards_view = dmc.SimpleGrid(
            public_dashboards_content,
            cols={
                "base": 1,
                "sm": 2,
                "lg": 4,
            },
            spacing="xl",
            verticalSpacing="xl",
            style={"width": "100%"},
        )

        example_dashboards_view = dmc.SimpleGrid(
            example_dashboards_content,
            cols={
                "base": 1,
                "sm": 2,
                "lg": 4,
            },
            spacing="xl",
            verticalSpacing="xl",
            style={"width": "100%"},
        )

        # Determine which sections to expand based on content
        # All non-empty sections should be opened
        default_expanded = []
        if owned_dashboards:
            default_expanded.append("owned")
        if accessed_dashboards:
            default_expanded.append("accessed")
        if public_dashboards:
            default_expanded.append("public")
        if example_dashboards:
            default_expanded.append("example")

        # Collapsible sections using Accordion
        # Order of appearance: Owned / Accessed / Public / Example
        return html.Div(
            [
                dmc.Accordion(
                    multiple=True,
                    value=default_expanded,
                    variant="default",
                    chevronPosition="left",
                    chevronSize=30,
                    children=[
                        # Owned Dashboards Section
                        dmc.AccordionItem(
                            [
                                dmc.AccordionControl(
                                    dmc.Group(
                                        [
                                            DashIconify(
                                                icon="mdi:account-check", width=18, color="#1c7ed6"
                                            ),
                                            dmc.Text(
                                                f"Owned Dashboards ({len(owned_dashboards)})",
                                                size="lg",
                                                fw="bold",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                ),
                                dmc.AccordionPanel(
                                    [
                                        dmc.Space(h=10),
                                        owned_dashboards_view,
                                    ]
                                ),
                            ],
                            value="owned",
                        ),
                        # Accessed Dashboards Section
                        dmc.AccordionItem(
                            [
                                dmc.AccordionControl(
                                    dmc.Group(
                                        [
                                            DashIconify(
                                                icon="material-symbols:share-outline",
                                                width=18,
                                                color="#54ca74",
                                            ),
                                            dmc.Text(
                                                f"Accessed Dashboards ({len(accessed_dashboards)})",
                                                size="lg",
                                                fw="bold",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                ),
                                dmc.AccordionPanel(
                                    [
                                        dmc.Space(h=10),
                                        accessed_dashboards_view,
                                    ]
                                ),
                            ],
                            value="accessed",
                        ),
                        # Public Dashboards Section
                        dmc.AccordionItem(
                            [
                                dmc.AccordionControl(
                                    dmc.Group(
                                        [
                                            DashIconify(
                                                icon="mdi:earth", width=18, color="#20c997"
                                            ),
                                            dmc.Text(
                                                f"Public Dashboards ({len(public_dashboards)})",
                                                size="lg",
                                                fw="bold",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                ),
                                dmc.AccordionPanel(
                                    [
                                        dmc.Space(h=10),
                                        public_dashboards_view,
                                    ]
                                ),
                            ],
                            value="public",
                        ),
                        # Example Dashboards Section
                        dmc.AccordionItem(
                            [
                                dmc.AccordionControl(
                                    dmc.Group(
                                        [
                                            DashIconify(
                                                icon="mdi:school-outline", width=18, color="#fd7e14"
                                            ),
                                            dmc.Text(
                                                f"Example Dashboards ({len(example_dashboards)})",
                                                size="lg",
                                                fw="bold",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                ),
                                dmc.AccordionPanel(
                                    [
                                        dmc.Space(h=10),
                                        example_dashboards_view,
                                    ]
                                ),
                            ],
                            value="example",
                        ),
                    ],
                ),
            ],
            style={"width": "100%"},
        )

    @app.callback(
        Output("dashboard-projects", "data"),
        Input("dashboard-modal", "opened"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def load_projects(modal_opened, user_data):
        """
        Load available projects when dashboard creation modal is opened.

        Fetches all projects accessible to the user from the API and formats
        them for display in a select dropdown.

        Args:
            modal_opened: Whether the dashboard creation modal is open.
            user_data: User session data containing access token.

        Returns:
            list: List of project options with label and value keys.
        """
        # Only load projects when modal is opened
        if not modal_opened:
            return []

        # Check if user data is valid
        if not user_data or "access_token" not in user_data:
            logger.warning("No valid user data or access token")
            return []

        try:
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/projects/get/all",
                headers={"Authorization": f"Bearer {user_data['access_token']}"},
                timeout=settings.performance.api_request_timeout,
            )

            if response.status_code == 200:
                projects = response.json()
                projects_multiselect_options = [
                    {
                        "label": f"{project['name']} ({str(project['id'])})",
                        "value": project["id"],
                    }
                    for project in projects
                ]
                return projects_multiselect_options
            else:
                logger.error(f"API Error: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            logger.error(f"Exception in load_projects: {e}")
            return []

    def build_icon_preview(
        icon_name: str | None, icon_color: str | None, workflow_system: str | None
    ) -> tuple:
        """
        Build icon preview component based on icon settings.

        When a workflow system is selected (not "none"), automatically uses the
        workflow-specific logo image and color. Otherwise uses custom icon settings.

        Args:
            icon_name: Icon identifier from Iconify (e.g., "mdi:chart-line") or image path.
            icon_color: Color name for the icon (e.g., "orange", "blue").
            workflow_system: Selected workflow system (e.g., "nextflow", "snakemake", "none").

        Returns:
            Tuple of (preview component, resolved icon name, resolved color, color_disabled).
        """
        allowed_colors = ("blue", "teal", "orange", "red", "purple", "pink", "green", "gray")
        workflow_icons = get_workflow_icon_mapping()
        workflow_colors = get_workflow_icon_color()

        # Workflow system overrides custom icon settings
        if workflow_system and workflow_system != "none":
            icon_name = workflow_icons.get(workflow_system, "mdi:view-dashboard")
            icon_color = workflow_colors.get(workflow_system, "orange")
            color_disabled = True
        else:
            # Apply defaults for custom icon mode
            if not icon_name or not icon_name.strip():
                icon_name = "mdi:view-dashboard"
            if icon_color not in allowed_colors:
                icon_color = "orange"
            color_disabled = False

        # Build preview component based on icon type
        if icon_name and icon_name.startswith("/assets/"):
            preview = html.Img(
                src=icon_name,
                style={"width": "32px", "height": "32px", "objectFit": "contain"},
            )
        else:
            preview = dmc.ActionIcon(
                DashIconify(icon=icon_name, width=24, height=24),
                color=icon_color,
                radius="xl",
                size="lg",
                variant="filled",
                disabled=color_disabled,
            )

        return preview, icon_name, icon_color, color_disabled

    @app.callback(
        [
            Output("dashboard-icon-preview", "children"),
            Output("dashboard-icon-input", "value"),
            Output("dashboard-icon-color-select", "value"),
            Output("dashboard-icon-color-select", "disabled"),
        ],
        [
            Input("dashboard-icon-input", "value"),
            Input("dashboard-icon-color-select", "value"),
            Input("dashboard-workflow-system-select", "value"),
        ],
        prevent_initial_call=True,
    )
    def update_icon_preview(icon_name, icon_color, workflow_system):
        """Update the dashboard creation modal icon preview."""
        return build_icon_preview(icon_name, icon_color, workflow_system)

    @app.callback(
        [
            Output({"type": "edit-dashboard-icon-preview", "index": MATCH}, "children"),
            Output({"type": "edit-dashboard-icon", "index": MATCH}, "value"),
            Output({"type": "edit-dashboard-icon-color", "index": MATCH}, "value"),
            Output({"type": "edit-dashboard-icon-color", "index": MATCH}, "disabled"),
        ],
        [
            Input({"type": "edit-dashboard-icon", "index": MATCH}, "value"),
            Input({"type": "edit-dashboard-icon-color", "index": MATCH}, "value"),
            Input({"type": "edit-dashboard-workflow", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def update_edit_icon_preview(icon_name, icon_color, workflow_system):
        """Update the dashboard edit modal icon preview."""
        return build_icon_preview(icon_name, icon_color, workflow_system)

    @app.callback(
        Output({"type": "dashboard-list", "index": ALL}, "children"),
        # [Output({"type": "dashboard-list", "index": ALL}, "children"), Output({"type": "dashboard-index-store", "index": ALL}, "data")],
        [
            # Input({"type": "cancel-dashboard-delete-button", "index": ALL}, "n_clicks"),
            Input({"type": "confirm-dashboard-delete-button", "index": ALL}, "n_clicks"),
            Input({"type": "save-edit-dashboard", "index": ALL}, "n_clicks"),
            Input({"type": "duplicate-dashboard-button", "index": ALL}, "n_clicks"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "n_clicks"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "children"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "id"),
        ],
        [
            State({"type": "create-dashboard-button", "index": ALL}, "id"),
            # State({"type": "dashboard-index-store", "index": ALL}, "data"),
            State({"type": "confirm-dashboard-delete-button", "index": ALL}, "index"),
            # Edit dashboard states
            State({"type": "edit-dashboard-title", "index": ALL}, "value"),
            State({"type": "edit-dashboard-title", "index": ALL}, "id"),
            State({"type": "edit-dashboard-subtitle", "index": ALL}, "value"),
            State({"type": "edit-dashboard-subtitle", "index": ALL}, "id"),
            State({"type": "edit-dashboard-icon", "index": ALL}, "value"),
            State({"type": "edit-dashboard-icon", "index": ALL}, "id"),
            State({"type": "edit-dashboard-icon-color", "index": ALL}, "value"),
            State({"type": "edit-dashboard-icon-color", "index": ALL}, "id"),
            State({"type": "edit-dashboard-workflow", "index": ALL}, "value"),
            State({"type": "edit-dashboard-workflow", "index": ALL}, "id"),
            State("local-store", "data"),
            Input("dashboard-modal-store", "data"),
        ],
    )
    def update_dashboards(
        # cancel_n_clicks_list,
        delete_n_clicks_list,
        edit_n_clicks_list,
        duplicate_n_clicks_list,
        make_public_n_clicks_list,
        make_public_children_list,
        make_public_id_list,
        # create_ids_list,
        store_data_list,
        delete_ids_list,
        # Edit dashboard values
        edit_title_values,
        edit_title_ids,
        edit_subtitle_values,
        edit_subtitle_ids,
        edit_icon_values,
        edit_icon_ids,
        edit_icon_color_values,
        edit_icon_color_ids,
        edit_workflow_values,
        edit_workflow_ids,
        user_data,
        modal_data,
    ):
        """
        Main callback for dashboard list updates.

        Handles all dashboard actions: creation, deletion, duplication, editing,
        and public/private status toggling. Routes to appropriate handler based on
        which button triggered the callback.

        Args:
            delete_n_clicks_list: Click counts for delete confirmation buttons.
            edit_n_clicks_list: Click counts for save edit buttons.
            duplicate_n_clicks_list: Click counts for duplicate buttons.
            make_public_n_clicks_list: Click counts for public/private toggle buttons.
            make_public_children_list: Button text for public/private buttons.
            make_public_id_list: IDs for public/private buttons.
            store_data_list: Dashboard store data list.
            delete_ids_list: IDs of dashboards to delete.
            edit_title_values: Edit dashboard title values.
            edit_title_ids: IDs for title input fields.
            edit_subtitle_values: Edit dashboard subtitle values.
            edit_subtitle_ids: IDs for subtitle input fields.
            edit_icon_values: Edit dashboard icon values.
            edit_icon_ids: IDs for icon input fields.
            edit_icon_color_values: Edit dashboard icon color values.
            edit_icon_color_ids: IDs for icon color select fields.
            edit_workflow_values: Edit dashboard workflow values.
            edit_workflow_ids: IDs for workflow select fields.
            user_data: User session data with access token.
            modal_data: Dashboard creation modal data.

        Returns:
            list: Updated dashboard view components for each dashboard-list output.
        """
        # log_context_info()

        # Fetch user data using cached API call
        from depictio.models.models.users import UserContext

        current_user_api = api_call_fetch_user_from_token(user_data["access_token"])
        if not current_user_api:
            logger.warning("User not found in dashboards management.")
            # Return empty list for each dashboard-list component
            # Ensure we always return a list, even if store_data_list is empty
            list_length = max(len(store_data_list), 1)
            return [html.Div("User not found. Please login again.")] * list_length

        # Create UserContext from API response
        current_user = UserContext(
            id=str(current_user_api.id),
            email=current_user_api.email,
            is_admin=current_user_api.is_admin,
            is_anonymous=getattr(current_user_api, "is_anonymous", False),
        )
        # current_userbase = UserBase(
        #     convert_model_to_dict(current_user, exclude_none=True).dict(
        #         exclude={
        #             "tokens",
        #             "is_active",
        #             "is_verified",
        #             "last_login",
        #             "registration_date",
        #             "password",
        #         }
        #     )
        # )
        current_userbase = current_user.turn_to_userbase()

        index_data = load_dashboards_from_db(user_data["access_token"])
        dashboards = [
            DashboardData.from_mongo(dashboard) for dashboard in index_data.get("dashboards", [])
        ]
        # next_index = index_data.get("next_index", 1)

        if not ctx.triggered_id:
            return handle_no_trigger(dashboards, store_data_list, current_userbase, user_data)
            # return handle_no_trigger(dashboards, next_index, store_data_list, current_userbase)

        if "type" not in ctx.triggered_id:
            if ctx.triggered_id == "dashboard-modal-store":
                return handle_dashboard_creation(
                    dashboards, modal_data, user_data, current_userbase, store_data_list
                )
                # return handle_dashboard_creation(dashboards, next_index, modal_data, user_data, current_userbase, store_data_list)

        if ctx.triggered_id.get("type") == "confirm-dashboard-delete-button":
            return handle_dashboard_deletion(
                dashboards,
                delete_ids_list,
                user_data,
                store_data_list,
                current_userbase,
            )

        if ctx.triggered_id.get("type") == "duplicate-dashboard-button":
            return handle_dashboard_duplication(
                dashboards, user_data, store_data_list, current_userbase
            )

        if ctx.triggered_id.get("type") == "make-public-dashboard-button":
            logger.info(f"Make public dashboard button clicked with ID: {ctx.triggered_id}")
            public_current_status = [
                child
                for child, id in zip(make_public_children_list, make_public_id_list)
                if str(id["index"]) == str(ctx.triggered_id["index"])
            ][0]
            public_current_status = False if public_current_status == "Make public" else True

            return handle_dashboard_make_public(
                dashboards,
                user_data,
                store_data_list,
                current_userbase,
                public_current_status,
            )

        if ctx.triggered_id.get("type") == "save-edit-dashboard":
            index = ctx.triggered_id["index"]

            # Build lookup dict: field_name -> (values_list, ids_list)
            field_inputs = {
                "title": (edit_title_values, edit_title_ids),
                "subtitle": (edit_subtitle_values, edit_subtitle_ids),
                "icon": (edit_icon_values, edit_icon_ids),
                "icon_color": (edit_icon_color_values, edit_icon_color_ids),
                "workflow_system": (edit_workflow_values, edit_workflow_ids),
            }

            # Extract values by matching index and filter out None values
            updates = {}
            for field_name, (values, ids) in field_inputs.items():
                for value, id_dict in zip(values, ids):
                    if str(id_dict["index"]) == str(index):
                        if value is not None:
                            updates[field_name] = value
                        break

            return handle_dashboard_edit_full(
                index, updates, dashboards, user_data, store_data_list, current_userbase
            )

        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_no_trigger(dashboards, store_data_list, current_userbase, user_data):
        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_dashboard_creation(
        dashboards, modal_data, user_data, current_userbase, store_data_list
    ):
        if modal_data.get("title"):
            logger.debug("Creating new dashboard")

            dashboard_id = PyObjectId()
            # dashboard_id = generate_unique_index()

            new_dashboard = DashboardData(
                id=dashboard_id,
                title=modal_data["title"],
                subtitle=modal_data.get("subtitle", ""),
                icon=modal_data.get("icon", "mdi:view-dashboard"),
                icon_color=modal_data.get("icon_color", "orange"),
                icon_variant="filled",
                workflow_system=modal_data.get("workflow_system", "none"),
                last_saved_ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                permissions=Permission(owners=[current_userbase]),
                # permissions={"owners": [current_userbase], "viewers": []},
                dashboard_id=dashboard_id,
                project_id=PyObjectId(modal_data["project_id"]),
            )
            logger.debug(f"New dashboard: {format_pydantic(new_dashboard)}")
            dashboards.append(new_dashboard)
            insert_dashboard(dashboard_id, new_dashboard.mongo(), user_data["access_token"])
            # next_index += 1

        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_dashboard_deletion(
        dashboards, delete_ids_list, user_data, store_data_list, current_userbase
    ):
        ctx_triggered_dict = ctx.triggered[0]
        index_confirm_delete = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        delete_dashboard(index_confirm_delete, user_data["access_token"])

        dashboards = [
            dashboard
            for dashboard in dashboards
            if str(dashboard.dashboard_id) != str(index_confirm_delete)
        ]
        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(dashboards, len(dashboards) + 1, store_data_list, current_userbase)

    def handle_dashboard_make_public(
        dashboards, user_data, store_data_list, current_userbase, public_current_status
    ):
        logger.info("Make public dashboard button clicked")
        ctx_triggered_dict = ctx.triggered[0]
        index_make_public = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        new_status = not public_current_status

        for dashboard in dashboards:
            if str(dashboard.dashboard_id) == str(index_make_public):
                response = httpx.post(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/toggle_public_status/{index_make_public}",
                    headers={"Authorization": f"Bearer {user_data['access_token']}"},
                    json={"is_public": new_status},
                )
                if response.status_code != 200:
                    raise ValueError(f"Failed to update dashboard status. Error: {response.text}")
                dashboard.is_public = response.json()["is_public"]
                logger.debug(f"Successfully made dashboard '{new_status}': {dashboard}")
                break

        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )

    def handle_dashboard_duplication(dashboards, user_data, store_data_list, current_userbase):
        """
        Handle the duplication of an existing dashboard.

        Creates a complete copy of a dashboard including all its data
        and components. The duplicated dashboard is assigned a new ID,
        ownership is transferred to the current user, and it is set to
        private by default. The dashboard thumbnail is also copied.

        This function:
        1. Identifies the dashboard to duplicate from callback context
        2. Fetches the full dashboard data from the API
        3. Creates a deep copy with new ID and "(copy)" title suffix
        4. Transfers ownership to the current user
        5. Sets the duplicate to private visibility
        6. Saves the new dashboard to the database
        7. Copies the thumbnail screenshot if it exists

        Args:
            dashboards: List of current DashboardData objects.
            user_data: User session data containing access_token for API calls.
            store_data_list: List of store data for generating view response.
            current_userbase: UserBase object representing the current user,
                used to set ownership on the duplicated dashboard.

        Returns:
            list: Updated dashboard view components reflecting the addition
                of the duplicated dashboard.

        Raises:
            ValueError: If fetching the original dashboard data fails.
        """
        logger.info("Duplicate dashboard button clicked")
        ctx_triggered_dict = ctx.triggered[0]
        index_duplicate = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]

        updated_dashboards = list()
        for dashboard in dashboards:
            updated_dashboards.append(dashboard)
            if str(dashboard.dashboard_id) == str(index_duplicate):
                logger.debug(f"Found dashboard to duplicate: {dashboard}")

                # Load full dashboard data from the database
                dashboard_data_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{index_duplicate}",
                    headers={"Authorization": f"Bearer {user_data['access_token']}"},
                )
                if dashboard_data_response.status_code != 200:
                    raise ValueError(
                        f"Failed to load dashboard data from the database. Error: {dashboard_data_response.text}"
                    )
                else:
                    dashboard_data_response = dashboard_data_response.json()

                # deep copy the dashboard object
                new_dashboard = DashboardData.from_mongo(dashboard_data_response)
                new_dashboard.id = ObjectId()
                new_dashboard.title = f"{dashboard.title} (copy)"
                new_dashboard.dashboard_id = str(new_dashboard.id)
                new_dashboard.permissions.owners = [current_userbase]
                new_dashboard.permissions.viewers = []
                new_dashboard.is_public = False  # Always make duplicated dashboards private
                logger.info(f"New dashboard: {format_pydantic(new_dashboard)}")
                # new_dashboard.dashboard_id = generate_unique_index()
                # new_dashboard.dashboard_id = str(len(dashboards) + 1)
                updated_dashboards.append(new_dashboard)
                insert_dashboard(
                    new_dashboard.dashboard_id,
                    new_dashboard.mongo(),
                    user_data["access_token"],
                )

                # Copy thumbnail
                thumbnail_filename = f"{str(dashboard.id)}.png"
                # thumbnail_filename = f"{str(current_userbase.id)}_{str(dashboard.id)}.png"
                thumbnail_fs_path = f"/app/depictio/dash/static/screenshots/{thumbnail_filename}"

                if not os.path.exists(thumbnail_fs_path):
                    logger.warning(f"Thumbnail not found at path: {thumbnail_fs_path}")
                else:
                    # Copy the thumbnail to the new dashboard ID
                    new_thumbnail_fs_path = (
                        f"/app/depictio/dash/static/screenshots/{str(new_dashboard.id)}.png"
                    )
                    shutil.copy(thumbnail_fs_path, new_thumbnail_fs_path)

        return generate_dashboard_view_response(
            updated_dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(updated_dashboards, len(updated_dashboards) + 1, store_data_list, current_userbase)

    def handle_dashboard_edit_full(
        dashboard_id, updates, dashboards, user_data, store_data_list, current_userbase
    ):
        """
        Handle editing a dashboard with all fields (title, subtitle, icon, icon_color, workflow_system).

        Args:
            dashboard_id: The dashboard ID to edit.
            updates: Dictionary of fields to update.
            dashboards: List of current dashboard objects.
            user_data: User session data with access token.
            store_data_list: Dashboard store data list.
            current_userbase: Current user base object.

        Returns:
            list: Updated dashboard view components.
        """
        logger.info(f"Edit dashboard button clicked for dashboard: {dashboard_id}")
        logger.debug(f"Updates: {updates}")

        updated_dashboards = edit_dashboard(
            dashboard_id, updates, dashboards, user_data["access_token"]
        )

        return generate_dashboard_view_response(
            updated_dashboards, store_data_list, current_userbase, user_data
        )

    def generate_dashboard_view_response(dashboards, store_data_list, current_userbase, user_data):
        dashboards = [convert_objectid_to_str(dashboard.mongo()) for dashboard in dashboards]
        current_user = api_call_fetch_user_from_token(user_data["access_token"])
        dashboards_view = create_homepage_view(
            dashboards, current_userbase.id, user_data["access_token"], current_user
        )
        return [dashboards_view] * len(store_data_list)

    @app.callback(
        Output({"type": "edit-dashboard-modal", "index": MATCH}, "opened"),
        [
            Input({"type": "edit-dashboard-button", "index": MATCH}, "n_clicks"),
            Input({"type": "cancel-edit-dashboard", "index": MATCH}, "n_clicks"),
            Input({"type": "save-edit-dashboard", "index": MATCH}, "n_clicks"),
        ],
        [State({"type": "edit-dashboard-modal", "index": MATCH}, "opened")],
        prevent_initial_call=True,
    )
    def handle_edit_dashboard_modal(edit_clicks, cancel_clicks, save_clicks, opened):
        """
        Handle the edit dashboard modal open/close state.

        Opens modal when edit button clicked, closes when cancel or save clicked.

        Args:
            edit_clicks: Click count for edit button.
            cancel_clicks: Click count for cancel button.
            save_clicks: Click count for save button.
            opened: Current modal open state.

        Returns:
            bool: New modal open state.
        """
        # Check which button was clicked
        ctx = dash.callback_context
        if not ctx.triggered:
            return opened

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # If edit button was clicked, toggle modal
        if "edit-dashboard-button" in triggered_id:
            return not opened
        # If cancel or save button was clicked, close modal
        elif "cancel-edit-dashboard" in triggered_id or "save-edit-dashboard" in triggered_id:
            return False

        return opened

    @app.callback(
        [
            Output("dashboard-modal-store", "data"),
            Output("dashboard-modal", "opened"),
            Output("init-create-dashboard-button", "data"),
            Output("unique-title-warning", "style"),
            Output("unique-title-warning", "children"),
            Output("url", "pathname", allow_duplicate=True),
        ],
        [
            Input({"type": "create-dashboard-button", "index": ALL}, "n_clicks"),
            Input("create-dashboard-submit", "n_clicks"),
            Input("cancel-dashboard-button", "n_clicks"),
        ],
        [
            State("dashboard-title-input", "value"),
            State("dashboard-subtitle-input", "value"),
            State("dashboard-icon-input", "value"),
            State("dashboard-icon-color-select", "value"),
            State("dashboard-workflow-system-select", "value"),
            State("dashboard-modal", "opened"),
            State("local-store", "data"),
            State("init-create-dashboard-button", "data"),
            State("dashboard-projects", "value"),
        ],
        prevent_initial_call=True,
    )
    def handle_create_dashboard_and_toggle_modal(
        n_clicks_create,
        n_clicks_submit,
        n_clicks_cancel,
        title,
        subtitle,
        icon,
        icon_color,
        workflow_system,
        opened,
        user_data,
        init_create_dashboard_button,
        project,
    ):
        """
        Handle dashboard creation modal interactions.

        Manages modal open/close state, validates inputs (unique title, project selection),
        and submits dashboard creation data. Redirects anonymous users to profile page.

        Args:
            n_clicks_create: Click counts for create dashboard buttons.
            n_clicks_submit: Click count for submit button.
            n_clicks_cancel: Click count for cancel button.
            title: Dashboard title input value.
            subtitle: Dashboard subtitle input value.
            icon: Selected icon identifier.
            icon_color: Selected icon color.
            workflow_system: Selected workflow system.
            opened: Current modal open state.
            user_data: User session data with access token.
            init_create_dashboard_button: Initialization flag for create button.
            project: Selected project ID.

        Returns:
            Tuple of (modal_data, modal_opened, init_flag, warning_style, warning_children, url_pathname)
        """
        data = {
            "title": "",
            "subtitle": "",
            "icon": "mdi:view-dashboard",
            "icon_color": "orange",
            "icon_variant": "filled",
            "project_id": "",
            "workflow_system": "none",
        }

        if not init_create_dashboard_button:
            return data, opened, True, dash.no_update, dash.no_update, dash.no_update

        if "type" in ctx.triggered_id:
            triggered_id = ctx.triggered_id["type"]
        else:
            triggered_id = ctx.triggered_id

        if triggered_id == "create-dashboard-button":
            # Check if user is anonymous and redirect to profile page
            from depictio.models.models.users import UserContext

            # Fetch user data using cached API call
            current_user_api = api_call_fetch_user_from_token(user_data["access_token"])
            if not current_user_api:
                logger.warning("User not found in dashboard creation.")
                return data, opened, True, dash.no_update, dash.no_update, dash.no_update

            # Create UserContext from API response
            current_user = UserContext(
                id=str(current_user_api.id),
                email=current_user_api.email,
                is_admin=current_user_api.is_admin,
                is_anonymous=getattr(current_user_api, "is_anonymous", False),
            )
            if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
                logger.info(
                    "Anonymous user clicked 'Login to Create Dashboards' - redirecting to profile"
                )
                return (
                    dash.no_update,
                    False,  # Keep modal closed
                    dash.no_update,
                    {"display": "none"},  # Hide any warning messages
                    dash.no_update,
                    "/profile",  # Redirect to profile page
                )

            # Toggle the modal when the create button is clicked (for authenticated users)
            return (
                dash.no_update,
                True,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        if triggered_id == "cancel-dashboard-button":
            logger.info("Create button clicked")
            # Toggle the modal when the create button is clicked
            return (
                dash.no_update,
                False,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        if triggered_id == "create-dashboard-submit":
            logger.info("Submit button clicked")
            dashboards = load_dashboards_from_db(user_data["access_token"])["dashboards"]
            if len(dashboards) > 0:
                existing_titles = [dashboard["title"] for dashboard in dashboards]

                if title in existing_titles:
                    logger.warning(f"Dashboard with title '{title}' already exists.")
                    return (
                        dash.no_update,
                        True,
                        dash.no_update,
                        {"display": "block"},
                        dmc.Badge(
                            children="Title already exists",
                            color="red",
                            # size="xl",
                            id="unique-title-warning-badge",
                        ),
                        dash.no_update,
                    )

                if not title:
                    logger.warning("Title is empty")
                    return (
                        dash.no_update,
                        True,
                        dash.no_update,
                        {"display": "block"},
                        dmc.Badge(
                            children="Title cannot be empty",
                            color="red",
                            # size="xl",
                            id="unique-title-warning-badge",
                        ),
                        dash.no_update,
                    )
            if not project:
                logger.warning("Project not selected")
                return (
                    dash.no_update,
                    True,
                    dash.no_update,
                    {"display": "block"},
                    dmc.Badge(
                        children="Project not selected",
                        color="red",
                        # size="xl",
                        id="unique-title-warning-badge",
                    ),
                    dash.no_update,
                )

            # Set the title and keep the modal open (or toggle it based on your preference)
            data["title"] = title
            data["subtitle"] = subtitle if subtitle else ""
            data["icon"] = icon if icon else "mdi:view-dashboard"
            data["icon_color"] = icon_color if icon_color else "orange"
            data["icon_variant"] = "filled"
            data["project_id"] = project
            data["workflow_system"] = workflow_system if workflow_system else "none"
            return data, False, False, {"display": "none"}, dash.no_update, dash.no_update

        logger.debug("No relevant clicks")
        # Return default values if no relevant clicks happened
        return data, opened, False, dash.no_update, dash.no_update, dash.no_update

    @app.callback(
        Output({"type": "dashboard-delete-confirmation-modal", "index": MATCH}, "opened"),
        [
            Input({"type": "delete-dashboard-button", "index": MATCH}, "n_clicks"),
            Input({"type": "confirm-dashboard-delete-button", "index": MATCH}, "n_clicks"),
            Input({"type": "cancel-dashboard-delete-button", "index": MATCH}, "n_clicks"),
        ],
        [
            State(
                {"type": "dashboard-delete-confirmation-modal", "index": MATCH},
                "opened",
            )
        ],
        prevent_initial_call=True,
    )
    def open_delete_modal(n1, n2, n3, opened):
        """
        Toggle the delete confirmation modal open/close state.

        Any of the three buttons (delete, confirm, cancel) will toggle the modal.

        Args:
            n1: Click count for delete button.
            n2: Click count for confirm button.
            n3: Click count for cancel button.
            opened: Current modal open state.

        Returns:
            bool: New modal open state (toggled).
        """
        return not opened

    @app.callback(
        Output("landing-page", "children"),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
        ],
    )
    def update_landing_page(
        pathname,
        data,
    ):
        """
        Update the landing page content based on URL and user data.

        Renders the dashboard list section when user navigates to /dashboards
        or when user session data changes.

        Args:
            pathname: Current URL pathname.
            data: User session data containing access token.

        Returns:
            Component: Landing page content with dashboard list, or no_update.

        Raises:
            dash.exceptions.PreventUpdate: When no trigger is present.
        """
        # Use consolidated user cache instead of individual API call

        # Fetch user data using cached API call
        user = api_call_fetch_user_from_token(data["access_token"])

        def render_landing_page(data):
            return html.Div(
                [
                    # dcc.Store(id={"type": "dashboard-index-store", "index": user.email}, storage_type="session", data={"next_index": 1}),  # Store for dashboard index management
                    # render_welcome_section(user.email),
                    render_dashboard_list_section(user.email),
                    # Dummy output for clientside thumbnail theme swap callback
                    html.Div(id="thumbnail-theme-swap-dummy", style={"display": "none"}),
                ]
            )

        # Check which input triggered the callback
        if not ctx.triggered:
            # return dash.no_update
            raise dash.exceptions.PreventUpdate
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # Respond to URL changes
        if trigger_id == "url":
            if pathname == "/dashboards":
                # if pathname.startswith("/dashboard/"):
                # dashboard_id = pathname.split("/")[-1]
                # Fetch dashboard data based on dashboard_id and return the appropriate layout
                # return html.Div([f"Displaying Dashboard {dashboard_id}", dbc.Button("Go back", href="/", color="black", external_link=True)])
                # return dash.no_update
                # elif pathname
                return render_landing_page(data)

        # Respond to modal-store data changes
        elif trigger_id == "local-store":
            if data:
                return render_landing_page(data)
            # return html.Div("Please login to view this page.")
            return dash.no_update

        return dash.no_update

    # =============================================================================
    # THEME-AWARE THUMBNAIL SWAPPING (CLIENTSIDE)
    # =============================================================================

    # Clientside callback to swap thumbnails based on theme changes
    # Listens to theme-store and updates all dashboard thumbnails to match current theme
    app.clientside_callback(
        """
        function(theme_data, url) {
            console.log('🎨 THUMBNAIL THEME SWAP: theme_data=', theme_data, 'url=', url);

            // Read theme from Dash store or fallback to localStorage directly
            let theme = theme_data;
            if (!theme) {
                // If theme-store hasn't loaded yet, read directly from localStorage
                const storedTheme = localStorage.getItem('theme-store');
                if (storedTheme) {
                    try {
                        theme = JSON.parse(storedTheme);
                    } catch (e) {
                        console.warn('Failed to parse theme from localStorage:', e);
                        theme = 'light';
                    }
                } else {
                    theme = 'light';
                }
            }
            console.log('→ Current theme:', theme);

            // Function to swap thumbnails
            const swapThumbnails = () => {
                const selector = theme === 'dark' ? 'data-dark-src' : 'data-light-src';
                console.log('→ Using selector:', selector);

                const thumbnails = document.querySelectorAll('[data-dashboard-id]');
                console.log('→ Found', thumbnails.length, 'thumbnails');

                let swapped = 0;
                thumbnails.forEach(elem => {
                    const newSrc = elem.getAttribute(selector);
                    if (newSrc) {
                        const img = elem.tagName === 'IMG' ? elem : elem.querySelector('img');
                        if (img) {
                            const currentPath = new URL(img.src, window.location.href).pathname;
                            const newPath = newSrc.startsWith('http') ? new URL(newSrc).pathname : newSrc;

                            if (currentPath !== newPath) {
                                console.log('  ✓ Swapping thumbnail:', elem.getAttribute('data-dashboard-id'), currentPath, '→', newPath);
                                const cacheBustedSrc = newSrc + '?t=' + Date.now();
                                img.src = cacheBustedSrc;
                                swapped++;
                            }
                        }
                    }
                });

                console.log('✅ Swapped', swapped, 'thumbnails for theme:', theme);
                return swapped;
            };

            // Immediate attempt
            let swapped = swapThumbnails();

            // Set up MutationObserver to watch for dynamically added thumbnails (e.g., HoverCard content)
            console.log('→ Setting up MutationObserver to watch for new thumbnails...');

            const observer = new MutationObserver((mutations) => {
                // Check if any new elements with data-dashboard-id were added
                for (let mutation of mutations) {
                    if (mutation.addedNodes.length > 0) {
                        const newThumbnails = [];
                        mutation.addedNodes.forEach(node => {
                            if (node.nodeType === 1) {  // Element node
                                // Check if the node itself has data-dashboard-id
                                if (node.hasAttribute && node.hasAttribute('data-dashboard-id')) {
                                    newThumbnails.push(node);
                                }
                                // Check if any descendants have data-dashboard-id
                                if (node.querySelectorAll) {
                                    const descendants = node.querySelectorAll('[data-dashboard-id]');
                                    newThumbnails.push(...descendants);
                                }
                            }
                        });

                        if (newThumbnails.length > 0) {
                            console.log(`→ Detected ${newThumbnails.length} new thumbnails, swapping...`);
                            swapThumbnails();  // Swap all thumbnails (including new ones)
                        }
                    }
                }
            });

            // Observe the entire document body for added nodes (catches HoverCard portals)
            observer.observe(document.body, {
                childList: true,
                subtree: true
            });

            // Keep observer alive for the session (no auto-disconnect)
            // This ensures HoverCard content gets theme-swapped when it appears

            return window.dash_clientside.no_update;
        }
        """,
        Output("thumbnail-theme-swap-dummy", "children"),
        Input("theme-store", "data"),
        Input("url", "pathname"),
        prevent_initial_call=False,  # Allow initial call to swap thumbnails on page load
    )
