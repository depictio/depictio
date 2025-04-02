"""
Project-wise User Management Module

This module provides a Dash layout and callbacks for managing user permissions
within a project. It allows administrators and project owners to add, modify,
and remove user permissions, as well as toggle project visibility.

The module is organized into:
- API utility functions for data fetching and manipulation
- UI component definitions
- Layout definition
- Modular callback functions for handling user interactions
"""

import dash
import dash_ag_grid as dag
from dash import html, dcc, Input, Output, State, ctx
import dash_mantine_components as dmc
import httpx
import requests

from depictio.dash.layouts.layouts_toolbox import create_add_with_input_modal
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging import logger
from depictio_models.models.base import convert_objectid_to_str
from depictio_models.models.users import Permission


# Initialize empty structures - will be populated by callback
GROUPS_DATA = {}
GROUP_OPTIONS = []

# -----------------------------------------------------------------------------
# API Utility Functions
# -----------------------------------------------------------------------------


def fetch_groups_data(token):
    """
    Fetch groups data from API and format it for use in the UI.

    Args:
        token (str): Authentication token for API access.

    Returns:
        tuple: (groups_dict, group_options)
            - groups_dict: Dictionary of group data with ID as key.
            - group_options: List of group options for dropdown selection.
    """
    try:
        response = requests.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/get_all_groups_including_users",
            headers={"Authorization": f"Bearer {token}"},
        )
        groups_list = response.json()
        groups_dict = {group["id"]: group for group in groups_list}
        group_options = [
            {"value": group["id"], "label": group["name"]}
            for group in groups_list
            if group["name"] not in ["admin", "users"]
        ]
        return groups_dict, group_options
    except Exception as e:
        logger.info(f"Error fetching groups data: {e}")
        return {}, []


def fetch_project_permissions(project_id, token):
    """
    Fetch project permissions from API and format for display in the grid.

    Args:
        project_id (str): ID of the project.
        token (str): Authentication token for API access.

    Returns:
        list: List of user permission objects with formatted data.
    """
    try:
        response = requests.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id/{project_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        project_data = response.json()
        permissions_data = []
        if "permissions" in project_data:
            # Process owners, editors, and viewers
            permissions_data.extend(
                _process_permission_users(
                    project_data["permissions"].get("owners", []),
                    token,
                    permission_type="Owner",
                )
            )
            permissions_data.extend(
                _process_permission_users(
                    project_data["permissions"].get("editors", []),
                    token,
                    permission_type="Editor",
                )
            )
            permissions_data.extend(
                _process_permission_users(
                    project_data["permissions"].get("viewers", []),
                    token,
                    permission_type="Viewer",
                )
            )
        return permissions_data
    except Exception as e:
        logger.info(f"Error fetching project permissions: {e}")
        return []


def _process_permission_users(users, token, permission_type):
    """
    Process a list of users for a given permission type.

    Args:
        users (list): List of user objects.
        token (str): Authentication token.
        permission_type (str): "Owner", "Editor", or "Viewer".

    Returns:
        list: Processed user permission data.
    """
    processed_users = []
    for user in users:
        user_api = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id/{str(user['_id'])}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if user_api.status_code != 200:
            logger.error(f"Error fetching user data: {user_api.text}")
            continue
        user_api = user_api.json()
        # Exclude admin and users groups from display
        group_name = ", ".join(
            [
                group["name"]
                for group in user_api.get("groups", [])
                if group["name"] not in ["admin", "users"]
            ]
        )
        permission_flags = {
            "Owner": permission_type == "Owner",
            "Editor": permission_type == "Editor",
            "Viewer": permission_type == "Viewer",
        }
        processed_users.append(
            {
                "id": user["_id"],
                "email": user["email"],
                "groups": group_name,
                **permission_flags,
                "is_admin": user_api.get("is_admin", False),
                "groups_with_metadata": convert_objectid_to_str(
                    user_api.get("groups", [])
                ),
            }
        )
    return processed_users


def update_project_permissions(project_id, permissions_data, token):
    """
    Update project permissions via API.

    Args:
        project_id (str): ID of the project.
        permissions_data (list): List of user permission objects.
        token (str): Authentication token.

    Returns:
        dict: API response or error message.
    """
    try:
        # Organize users by permission type.
        permissions_payload = {
            "owners": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                    "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                }
                for user in permissions_data
                if user["Owner"]
            ],
            "editors": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                    "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                }
                for user in permissions_data
                if user["Editor"]
            ],
            "viewers": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                    "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                }
                for user in permissions_data
                if user["Viewer"]
            ],
        }
        # Validate with Pydantic model
        permissions_payload_pydantic = Permission(**permissions_payload)
        logger.info(f"Permissions payload pydantic: {permissions_payload_pydantic}")
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/update_project_permissions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "project_id": project_id,
                "permissions": convert_objectid_to_str(permissions_payload),
            },
        )
        if response.status_code != 200:
            logger.error(f"Error updating project permissions: {response.text}")
            return {"success": False, "message": response.text}
        return {"success": True, "data": response.json()}
    except Exception as e:
        logger.error(f"Error in update_project_permissions: {e}")
        return {"success": False, "message": str(e)}


def toggle_project_visibility(project_id, token, is_public):
    """
    Toggle project visibility between public and private.

    Args:
        project_id (str): Project ID.
        token (str): Authentication token.
        is_public (bool): Desired visibility state.

    Returns:
        dict: Result with success flag and message/data.
    """
    try:
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/toggle_public_private/{project_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"is_public": is_public},
        )
        if response.status_code != 200:
            logger.error(f"Error toggling project public/private: {response.text}")
            return {"message": response.text, "success": False}
        return {"message": response.json(), "success": True}
    except Exception as e:
        logger.error(f"Error in toggle_project_visibility: {e}")
        return {"message": str(e), "success": False}


def get_current_user(token):
    """
    Get current user information from API.

    Args:
        token (str): Authentication token.

    Returns:
        dict: User data or None if error occurs.
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
            params={"token": token},
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            logger.error(f"Error fetching current user data: {response.text}")
            return None
        return response.json()
    except Exception as e:
        logger.error(f"Error in get_current_user: {e}")
        return None


# -----------------------------------------------------------------------------
# UI Component Definitions
# -----------------------------------------------------------------------------


def create_column_defs(is_admin=False, is_owner=False):
    """
    Create column definitions for the permissions grid based on user roles.

    Args:
        is_admin (bool): Whether the current user is an admin.
        is_owner (bool): Whether the current user is an owner.

    Returns:
        list: Column definitions for the AG Grid.
    """
    return [
        {"field": "id", "hide": True},
        {"field": "email", "headerName": "Email", "minWidth": 200},
        {"field": "groups", "headerName": "Groups", "minWidth": 150},
        {
            "field": "Owner",
            "cellRenderer": "agCheckboxCellRenderer",
            "cellStyle": {"textAlign": "center"},
        },
        {
            "field": "Editor",
            "cellRenderer": "agCheckboxCellRenderer",
            "cellStyle": {"textAlign": "center"},
        },
        {
            "field": "Viewer",
            "cellRenderer": "agCheckboxCellRenderer",
            "cellStyle": {"textAlign": "center"},
        },
        {
            "field": "actions",
            "headerName": "Actions",
            "cellRenderer": "Button" if (is_admin or is_owner) else None,
            "cellRendererParams": {"className": "btn", "value": "🗑️"}
            if (is_admin or is_owner)
            else {},
        },
        {"field": "is_admin", "hide": True},
        {"field": "groups_with_metadata", "hide": True},
    ]


def create_project_header(project_name, project_id, is_public):
    """
    Create the project header component with title and visibility toggle.

    Args:
        project_name (str): Name of the project.
        project_id (str): Project identifier.
        is_public (bool): Current project visibility.

    Returns:
        dmc.Paper: Component wrapping the project header.
    """
    title = dmc.Title(
        f"Project: {project_name}",
        order=3,
        mb=20,
        id="permissions-manager-project-title",
    )
    make_public_button = dmc.SegmentedControl(
        id="make-project-public-button",
        color="green",
        size="sm",
        data=[
            {"value": "True", "label": "Public"},
            {"value": "False", "label": "Private"},
        ],
        value="True" if is_public else "False",
        radius="xl",
    )
    title_button = dmc.Group([title, make_public_button], position="apart")
    details = dmc.Text(
        f"Project ID: {project_id}",
        size="sm",
        color="gray",
        id="permissions-manager-project-details",
    )
    return dmc.Paper(
        [title_button, details],
        p="md",
        shadow="sm",
        radius="md",
        withBorder=True,
        style={
            "backgroundColor": "#f8f9fa",
            "marginBottom": "20px",
            "marginTop": "20px",
        },
    )


# -----------------------------------------------------------------------------
# Modal Definitions
# -----------------------------------------------------------------------------

user_exists_modal, user_exists_modal_id = create_add_with_input_modal(
    id_prefix="user-exists",
    input_field=None,
    title="User Already Exists",
    title_color="orange",
    message="This user already has permissions in the project. You cannot add them again but you can modify their permissions.",
    confirm_button_text="OK",
    confirm_button_color="orange",
    cancel_button_text="Cancel",
    icon="mdi:alert-circle",
    opened=False,
)

cannot_delete_owner_modal, cannot_delete_owner_modal_id = create_add_with_input_modal(
    id_prefix="cannot-delete-owner",
    input_field=None,
    title="Cannot Delete last Owner",
    title_color="red",
    message="You cannot delete the last owner of the project. Please assign ownership to another user before deleting this user.",
    confirm_button_text="OK",
    confirm_button_color="red",
    cancel_button_text="Cancel",
    icon="mdi:alert-circle",
    opened=False,
)

cannot_change_last_owner_modal, cannot_change_last_owner_modal_id = (
    create_add_with_input_modal(
        id_prefix="cannot-change-last-owner",
        input_field=None,
        title="Cannot Change Last Owner Permissions",
        title_color="red",
        message="You cannot change your permissions from Owner to Editor or Viewer as you are the last owner of the project. Please assign ownership to another user first.",
        confirm_button_text="OK",
        confirm_button_color="red",
        cancel_button_text="Cancel",
        icon="mdi:alert-circle",
        opened=False,
    )
)

make_project_public_modal, make_project_public_modal_id = create_add_with_input_modal(
    id_prefix="make-project-public",
    input_field=None,
    title="Change Project Visibility",
    title_color="green",
    message="Are you sure you want to change visibility of the project?",
    confirm_button_text="Yes",
    confirm_button_color="green",
    cancel_button_text="No",
    icon="mdi:jira",
    opened=False,
)

store_make_project_public_modal = dcc.Store(
    id="store-make-project-public", data=None, storage_type="memory"
)

text_table_header = dmc.Text(
    "Project Permissions", size="xl", weight="bold", color="black"
)

# -----------------------------------------------------------------------------
# Main Layout Definition
# -----------------------------------------------------------------------------

layout = dmc.Container(
    [
        # Modals and Store
        user_exists_modal,
        cannot_delete_owner_modal,
        make_project_public_modal,
        cannot_change_last_owner_modal,
        store_make_project_public_modal,
        # Project header and permissions grid
        html.Div(id="permissions-manager-project-header"),
        text_table_header,
        dcc.Store(id="permissions-manager-grid-store", storage_type="memory"),
        dag.AgGrid(
            id="permissions-manager-grid",
            columnDefs=create_column_defs(),
            defaultColDef={
                "flex": 1,
                "editable": True,
                "resizable": True,
                "sortable": True,
            },
            dashGridOptions={
                "animateRows": True,
                "pagination": True,
                "paginationAutoPageSize": True,
                "getRowId": "params.data.id",
                "suppressClickEdit": True,
            },
            className="ag-theme-alpine",
            style={"height": "400px"},
            columnSize="sizeToFit",
        ),
        # Controls for adding permissions
        html.Hr(),
        dmc.Card(
            [
                dmc.Grid(
                    [
                        dmc.Title("Add permissions section", order=3),
                        dmc.Col(
                            [
                                dmc.CheckboxGroup(
                                    id="permissions-manager-checkboxes",
                                    orientation="horizontal",
                                    children=[
                                        dmc.Checkbox(
                                            id="permissions-manager-checkbox-owner",
                                            label="Owner",
                                            value="Owner",
                                        ),
                                        dmc.Checkbox(
                                            id="permissions-manager-checkbox-editor",
                                            label="Editor",
                                            value="Editor",
                                        ),
                                        dmc.Checkbox(
                                            id="permissions-manager-checkbox-viewer",
                                            label="Viewer",
                                            value="Viewer",
                                        ),
                                    ],
                                    label="Permissions",
                                )
                            ],
                            span=12,
                        ),
                        dmc.Col(
                            [
                                dmc.Group(
                                    [
                                        dmc.Select(
                                            id="permissions-manager-input-group",
                                            label="Group",
                                            placeholder="Select group",
                                            data=[],  # Updated via callback
                                            searchable=True,
                                            clearable=True,
                                            nothingFound="No group found",
                                            style={"width": "300px"},
                                        ),
                                        dmc.Button(
                                            "Add Group",
                                            id="permissions-manager-btn-add-group",
                                            color="green",
                                            disabled=True,
                                        ),
                                    ],
                                    position="left",
                                    align="flex-end",
                                    style={"width": "100%"},
                                ),
                            ],
                            span=12,
                        ),
                        dmc.Col(
                            [
                                dmc.Group(
                                    [
                                        dmc.Select(
                                            id="permissions-manager-input-email",
                                            label="Email",
                                            placeholder="Select email",
                                            data=[],  # Updated via callback
                                            searchable=True,
                                            clearable=True,
                                            nothingFound="No email found",
                                            disabled=True,
                                            style={"width": "300px"},
                                        ),
                                        dmc.Button(
                                            "Add User",
                                            id="permissions-manager-btn-add-user",
                                            color="blue",
                                            disabled=True,
                                        ),
                                    ],
                                    position="left",
                                    align="flex-end",
                                    style={"width": "100%"},
                                ),
                            ],
                            span=12,
                        ),
                    ],
                    align="flex-end",
                )
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            mt=20,
            style={"overflow": "visible"},
        ),
    ]
)

# -----------------------------------------------------------------------------
# Helper Functions for Callbacks
# -----------------------------------------------------------------------------


def build_permissions_payload(rows):
    """
    Build the permissions payload from grid rows.

    Args:
        rows (list): List of user permission dictionaries.

    Returns:
        dict: Permissions payload.
    """
    return {
        "owners": [
            {
                "_id": user["id"],
                "email": user["email"],
                "is_admin": user["is_admin"],
                "groups": convert_objectid_to_str(user["groups_with_metadata"]),
            }
            for user in rows
            if user["Owner"]
        ],
        "editors": [
            {
                "_id": user["id"],
                "email": user["email"],
                "is_admin": user["is_admin"],
                "groups": convert_objectid_to_str(user["groups_with_metadata"]),
            }
            for user in rows
            if user["Editor"]
        ],
        "viewers": [
            {
                "_id": user["id"],
                "email": user["email"],
                "is_admin": user["is_admin"],
                "groups": convert_objectid_to_str(user["groups_with_metadata"]),
            }
            for user in rows
            if user["Viewer"]
        ],
    }


def update_permissions_api(rows, project_id, token):
    """
    Update project permissions via the API.

    Args:
        rows (list): Updated permissions rows.
        project_id (str): Project ID.
        token (str): Access token.

    Returns:
        bool: True if successful, False otherwise.
    """
    payload = build_permissions_payload(rows)
    logger.info(f"Permissions payload: {payload}")
    # Validate payload using Pydantic model.
    permissions_payload_pydantic = Permission(**payload)
    logger.info(f"Permissions payload pydantic: {permissions_payload_pydantic}")
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/projects/update_project_permissions",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "project_id": project_id,
            "permissions": convert_objectid_to_str(payload),
        },
    )
    if response.status_code != 200:
        logger.error(f"Error updating project permissions: {response.text}")
        return False
    logger.info(f"Updated permissions in API: {response.json()}")
    return True


# -----------------------------------------------------------------------------
# Callback Registration Function
# -----------------------------------------------------------------------------


def register_projectwise_user_management_callbacks(app):
    """
    Register all callbacks for project-wise user management.

    Args:
        app (Dash): The Dash application instance.
    """

    @app.callback(
        Output("make-project-public-button", "color"),
        Input("make-project-public-button", "value"),
        Input("url", "pathname"),
    )
    def update_visibility_button_color(value, pathname):
        """Update the color of the project visibility button based on its value."""
        logger.info(f"Visibility button value: {value}")
        return "green" if value.lower() == "true" else "violet"

    @app.callback(
        Output("permissions-manager-input-group", "data"),
        Output("permissions-manager-grid", "rowData"),
        Output("permissions-manager-grid-store", "data"),
        Output("permissions-manager-project-header", "children"),
        Output("permissions-manager-grid", "columnDefs"),
        Input("permissions-manager-project-header", "children"),
        State("local-store", "data"),
        State("url", "pathname"),
    )
    def initialize_data(_, local_store_data, pathname):
        """
        Initialize UI components with data fetched from the API when the page loads.
        """
        global GROUPS_DATA, GROUP_OPTIONS
        GROUPS_DATA, GROUP_OPTIONS = fetch_groups_data(
            token=local_store_data["access_token"]
        )
        logger.info(f"Groups data: {GROUPS_DATA}")
        logger.info(f"Group options: {GROUP_OPTIONS}")
        project_id = pathname.split("/")[-1]

        # Fetch project data.
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id/{project_id}",
            headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
        )
        if response.status_code != 200:
            logger.error(f"Error fetching project data: {response.text}")
            return [], [], [], create_column_defs(), create_column_defs()

        project_data = response.json()
        project_name = project_data.get("name", "Project")

        # Get current user info and determine permissions.
        current_user = get_current_user(local_store_data["access_token"])
        is_admin = current_user.get("is_admin", False) if current_user else False
        is_owner = False
        if "permissions" in project_data and "owners" in project_data["permissions"]:
            current_user_id = current_user.get("id") if current_user else None
            is_owner = any(
                str(owner.get("_id")) == str(current_user_id)
                for owner in project_data["permissions"].get("owners", [])
            )

        column_defs = create_column_defs(is_admin=is_admin, is_owner=is_owner)
        project_header = create_project_header(
            project_name, project_id, project_data.get("is_public", False)
        )
        current_permissions = fetch_project_permissions(
            project_id=project_id, token=local_store_data["access_token"]
        )
        logger.info(f"Current permissions: {current_permissions}")
        return (
            GROUP_OPTIONS,
            current_permissions,
            current_permissions,
            [project_header],
            column_defs,
        )

    @app.callback(
        Output("permissions-manager-input-email", "data"),
        Output("permissions-manager-input-email", "disabled"),
        Input("permissions-manager-input-group", "value"),
    )
    def update_email_options(selected_group_id):
        """
        Populate the email dropdown based on the selected group.
        """
        logger.info(f"Selected group ID: {selected_group_id}")
        logger.info(f"Groups data: {GROUPS_DATA}")
        if selected_group_id and selected_group_id in GROUPS_DATA:
            email_options = [
                {"value": user["id"], "label": user["email"]}
                for user in GROUPS_DATA[selected_group_id]["users"]
            ]
            return email_options, False
        return [], True

    @app.callback(
        Output("permissions-manager-btn-add-user", "disabled"),
        Output("permissions-manager-btn-add-group", "disabled"),
        Output("permissions-manager-input-group", "disabled"),
        Output("permissions-manager-checkbox-owner", "disabled"),
        Output("permissions-manager-checkbox-editor", "disabled"),
        Output("permissions-manager-checkbox-viewer", "disabled"),
        Output("make-project-public-button", "disabled", allow_duplicate=True),
        Input("permissions-manager-input-email", "value"),
        Input("permissions-manager-input-group", "value"),
        Input("permissions-manager-checkboxes", "value"),
        Input("local-store", "data"),
        Input("permissions-manager-project-header", "children"),
        prevent_initial_call=True,
    )
    def toggle_add_buttons(email, group, permissions, local_store_data, project_header):
        """
        Enable or disable Add buttons and checkboxes based on current user and selections.
        """
        if not project_header or local_store_data is None:
            return True, True, True, True, True, True, True

        if not permissions:
            permissions = []

        current_user = get_current_user(local_store_data["access_token"])
        if not current_user or not current_user.get("is_admin", False):
            return True, True, True, True, True, True, True

        add_user_disabled = not (email and len(permissions) == 1)
        add_group_disabled = not (group and not email and len(permissions) == 1)
        return add_user_disabled, add_group_disabled, False, False, False, False, False

    @app.callback(
        Output("permissions-manager-grid", "rowData", allow_duplicate=True),
        Output("permissions-manager-grid", "defaultColDef"),
        Output("permissions-manager-input-email", "value"),
        Output("permissions-manager-input-group", "value"),
        Output("permissions-manager-checkboxes", "value"),
        Input("permissions-manager-btn-add-user", "n_clicks"),
        Input("permissions-manager-btn-add-group", "n_clicks"),
        State("permissions-manager-input-email", "value"),
        State("permissions-manager-input-email", "data"),
        State("permissions-manager-input-group", "value"),
        State("permissions-manager-checkboxes", "value"),
        State("permissions-manager-grid", "rowData"),
        State("permissions-manager-grid", "defaultColDef"),
        Input("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def add_user_or_group(
        user_clicks,
        group_clicks,
        user_id,
        dropdown_data,
        group_id,
        permissions,
        current_rows,
        grid_options,
        local_store_data,
        pathname,
    ):
        """
        Add an individual user or a group of users based on selections.
        """
        triggered_id = ctx.triggered_id
        email = next(
            (item["label"] for item in dropdown_data if item["value"] == user_id), None
        )
        logger.info(
            f"Triggered ID: {triggered_id}, user_id: {user_id}, Email: {email}, Group ID: {group_id}, Permissions: {permissions}"
        )
        logger.info(f"Current rows: {current_rows}")
        logger.info(f"GROUPS_DATA: {GROUPS_DATA}")

        if local_store_data is None:
            return current_rows, grid_options, "", "", []

        current_user = get_current_user(local_store_data["access_token"])
        if not current_user or not current_user.get("is_admin", False):
            grid_options["editable"] = False
            return current_rows, grid_options, "", "", []

        # Return unchanged if missing required data.
        if not group_id or not permissions or group_id not in GROUPS_DATA:
            return current_rows, grid_options, "", "", []

        new_users = []
        project_id = pathname.split("/")[-1]

        # Add user to the project.
        if triggered_id == "permissions-manager-btn-add-user" and email:
            retrieve_user_resp = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id/{user_id}",
                headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
            )
            if retrieve_user_resp.status_code != 200:
                logger.error(f"Error fetching user data: {retrieve_user_resp.text}")
                return current_rows, grid_options, "", "", []
            retrieve_user = retrieve_user_resp.json()
            groups_str = ", ".join(
                [
                    group["name"]
                    for group in retrieve_user.get("groups", [])
                    if group["name"] not in ["admin", "users"]
                ]
            )
            # If user already exists, return current state (modal is triggered separately)
            if any(row["email"] == email for row in current_rows):
                return current_rows, grid_options, email, group_id, permissions
            logger.info(
                f"Adding user: {email} with group: {groups_str} and permissions: {permissions}"
            )
            new_users.append(
                {
                    "id": user_id,
                    "email": email,
                    "groups": groups_str,
                    "Owner": "Owner" in permissions,
                    "Editor": "Editor" in permissions,
                    "Viewer": "Viewer" in permissions,
                    "is_admin": retrieve_user.get("is_admin", False),
                    "groups_with_metadata": convert_objectid_to_str(
                        retrieve_user.get("groups", [])
                    ),
                }
            )

        # Add group to the project
        elif triggered_id == "permissions-manager-btn-add-group":
            # Add all users in the selected group
            for user in GROUPS_DATA[group_id]["users"]:
                retrieve_user_resp = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id/{str(user['id'])}",
                    headers={
                        "Authorization": f"Bearer {local_store_data['access_token']}"
                    },
                )
                if retrieve_user_resp.status_code != 200:
                    logger.error(f"Error fetching user data: {retrieve_user_resp.text}")
                    continue
                retrieve_user = retrieve_user_resp.json()
                groups_str = ", ".join(
                    [
                        group["name"]
                        for group in retrieve_user.get("groups", [])
                        if group["name"] not in ["admin", "users"]
                    ]
                )
                # If user already exists, skip adding them
                if not any(row["email"] == user["email"] for row in current_rows):
                    new_users.append(
                        {
                            "id": user["id"],
                            "email": user["email"],
                            "groups": groups_str,
                            "Owner": "Owner" in permissions,
                            "Editor": "Editor" in permissions,
                            "Viewer": "Viewer" in permissions,
                            "is_admin": user["is_admin"],
                            "groups_with_metadata": convert_objectid_to_str(
                                retrieve_user.get("groups", [])
                            ),
                        }
                    )

        updated_rows = current_rows + new_users
        update_permissions_api(
            updated_rows, project_id, local_store_data["access_token"]
        )
        return updated_rows, grid_options, "", "", []

    @app.callback(
        Output("permissions-manager-grid", "rowData", allow_duplicate=True),
        Output("permissions-manager-grid-store", "data", allow_duplicate=True),
        Output(cannot_change_last_owner_modal_id, "opened"),
        Input("permissions-manager-grid", "cellClicked"),
        Input("permissions-manager-grid", "cellValueChanged"),
        Input("confirm-cannot-change-last-owner-add-button", "n_clicks"),
        Input("cancel-cannot-change-last-owner-add-button", "n_clicks"),
        State("permissions-manager-grid", "rowData"),
        State("local-store", "data"),
        State("permissions-manager-grid-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def handle_cell_interactions(
        clicked_data,
        value_changed_data,
        confirm_clicks,
        cancel_clicks,
        current_rows,
        local_store_data,
        current_rows_store,
        pathname,
    ):
        """
        Handle cell click events for delete actions and permission changes.
        """
        triggered_id = ctx.triggered[0]["prop_id"]
        logger.info(f"Triggered ID: {triggered_id}")
        logger.info(f"Clicked data: {clicked_data}")
        logger.info(f"Value changed data: {value_changed_data}")
        logger.info(f"Current rows: {current_rows}")
        current_owners_ids = {row["id"] for row in current_rows if row["Owner"]}
        updated_rows = []

        # Close modal if confirm/cancel clicked.
        if triggered_id in [
            "confirm-cannot-change-last-owner-add-button.n_clicks",
            "cancel-cannot-change-last-owner-add-button.n_clicks",
        ]:
            return current_rows_store, current_rows_store, False

        # Handle delete action via button click.
        if triggered_id == "permissions-manager-grid.cellClicked" and clicked_data:
            column = clicked_data.get("colId")
            row_id = clicked_data.get("rowId")
            if column == "actions":
                current_user = get_current_user(local_store_data["access_token"])
                # if user is not admin or not owner, do not allow delete
                if not current_user or (
                    not current_user.get("is_admin", False)
                    or current_user["id"] not in current_owners_ids
                ):
                    return current_rows_store, current_rows_store, False
                target_row = next(
                    (row for row in current_rows if str(row["id"]) == str(row_id)), None
                )
                if target_row and target_row["Owner"]:
                    # Check if the user is the last owner
                    owner_count = sum(1 for row in current_rows if row["Owner"])
                    if owner_count <= 1:
                        return current_rows, current_rows, True
                updated_rows = [
                    row for row in current_rows if str(row["id"]) != str(row_id)
                ]

        # Handle checkbox changes for permissions.
        if (
            triggered_id == "permissions-manager-grid.cellValueChanged"
            and value_changed_data
        ):
            cell_data = value_changed_data[0]
            column = cell_data.get("colId")
            row_id = cell_data.get("rowId")
            if column in ["Owner", "Editor", "Viewer"]:
                current_user = get_current_user(local_store_data["access_token"])
                if not current_user:
                    return current_rows_store, current_rows_store, False
                current_user_id = current_user.get("id")
                owner_count = sum(1 for row in current_rows if row["Owner"])
                target_row = next(
                    (row for row in current_rows if str(row["id"]) == str(row_id)), None
                )
                # Check if the user is the last owner
                if (
                    owner_count <= 1
                    and target_row
                    and target_row["Owner"]
                    and str(target_row["id"]) == str(current_user_id)
                    and column != "Owner"
                ):
                    return current_rows_store, current_rows_store, True
                updated_rows = current_rows.copy()
                # Reset roles for the row and set the new role.
                for row in updated_rows:
                    if str(row["id"]) == str(row_id):
                        for role in ["Owner", "Editor", "Viewer"]:
                            row[role] = False
                        row[column] = True
                        break

        if not updated_rows:
            return current_rows_store, current_rows_store, False

        update_permissions_api(
            updated_rows, pathname.split("/")[-1], local_store_data["access_token"]
        )
        return updated_rows, updated_rows, False

    @app.callback(
        Output(user_exists_modal_id, "opened"),
        Input("permissions-manager-btn-add-user", "n_clicks"),
        Input("confirm-user-exists-add-button", "n_clicks"),
        Input("cancel-user-exists-add-button", "n_clicks"),
        State("permissions-manager-input-email", "value"),
        State("permissions-manager-grid", "rowData"),
        prevent_initial_call=True,
    )
    def toggle_user_exists_modal(
        add_clicks, confirm_clicks, cancel_clicks, email, current_rows
    ):
        """
        Toggle the modal warning if the user already exists.
        """
        triggered_id = ctx.triggered_id
        if triggered_id in [
            "confirm-user-exists-add-button",
            "cancel-user-exists-add-button",
        ]:
            return False
        if triggered_id == "permissions-manager-btn-add-user":
            if not add_clicks or not email:
                return False
            return any(row["email"] == email for row in current_rows)
        return False

    @app.callback(
        Output(cannot_delete_owner_modal_id, "opened"),
        Input("permissions-manager-grid", "cellClicked"),
        Input("confirm-cannot-delete-owner-add-button", "n_clicks"),
        Input("cancel-cannot-delete-owner-add-button", "n_clicks"),
        State("permissions-manager-grid", "rowData"),
        prevent_initial_call=True,
    )
    def toggle_cannot_delete_owner_modal(
        clicked_data, confirm_clicks, cancel_clicks, current_rows
    ):
        """
        Toggle the modal warning if trying to delete the last owner.
        """
        logger.info(f"Clicked data: {clicked_data}")
        triggered_id = ctx.triggered[0]["prop_id"]
        if triggered_id in [
            "confirm-cannot-delete-owner-button",
            "cancel-cannot-delete-owner-button",
        ]:
            return False
        if triggered_id == "permissions-manager-grid.cellClicked" and clicked_data:
            column = clicked_data.get("colId")
            row_id = clicked_data.get("rowId")
            if column == "actions":
                target_row = next(
                    (row for row in current_rows if str(row["id"]) == str(row_id)), None
                )
                if target_row and target_row["Owner"]:
                    owner_count = sum(1 for row in current_rows if row["Owner"])
                    if owner_count <= 1:
                        return True
        return False

    def api_toggle_project_public_private(project_id, token, is_public):
        """
        Helper function to toggle project public/private status via API.
        """
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/toggle_public_private/{project_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"is_public": is_public},
        )
        if response.status_code != 200:
            logger.error(f"Error toggling project public/private: {response.text}")
            return {"message": response.text, "success": False}
        return {"message": response.json(), "success": True}

    @app.callback(
        Output(make_project_public_modal_id, "opened"),
        Output("make-project-public-button", "value"),
        Output("store-make-project-public", "data"),
        Input("make-project-public-button", "value"),
        Input("confirm-make-project-public-add-button", "n_clicks"),
        Input("cancel-make-project-public-add-button", "n_clicks"),
        State("store-make-project-public", "data"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def toggle_make_project_public_modal(
        value, confirm_clicks, cancel_clicks, store_data, local_store, pathname
    ):
        """
        Handle modal display and API call for toggling project visibility.
        """
        triggered_id = ctx.triggered_id
        logger.info(f"Triggered ID: {triggered_id}, Value: {value}")
        if triggered_id == "make-project-public-button":
            if store_data:
                # Check if the value has changed with the store data
                if value != store_data:
                    return True, dash.no_update, dash.no_update
                else:
                    return dash.no_update, dash.no_update, dash.no_update
            else:
                return False, dash.no_update, value
        elif triggered_id in ["cancel-make-project-public-add-button"]:
            return False, store_data, dash.no_update
        elif triggered_id in ["confirm-make-project-public-add-button"]:
            project_id = pathname.split("/")[-1]
            response = api_toggle_project_public_private(
                project_id=str(project_id),
                token=local_store["access_token"],
                is_public=value,
            )
            if response["success"]:
                return False, value, value
            else:
                return False, dash.no_update, dash.no_update
