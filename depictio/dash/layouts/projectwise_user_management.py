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
import dash_mantine_components as dmc
import httpx
from dash import Input, Output, State, ctx, dcc, html

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.api_utils import (
    fetch_all_users,
    fetch_all_users_detailed,
    fetch_project_permissions,
    get_current_user_info,
    toggle_project_visibility_api,
    update_project_permissions_api,
)
from depictio.dash.layouts.layouts_toolbox import create_add_with_input_modal
from depictio.models.models.base import convert_objectid_to_str

# Initialize empty structures - will be populated by callback
# GROUPS_DATA = {}  # Disabled for user-only permissions
# GROUP_OPTIONS = []  # Disabled for user-only permissions


# DISABLED: Group management removed for user-only permissions
# def fetch_groups_data(token):
#     """
#     Fetch groups data from API and format it for use in the UI.
#
#     Args:
#         token (str): Authentication token for API access.
#
#     Returns:
#         tuple: (groups_dict, group_options)
#             - groups_dict: Dictionary of group data with ID as key.
#             - group_options: List of group options for dropdown selection.
#     """
#     try:
#         response = requests.get(
#             f"{API_BASE_URL}/depictio/api/v1/auth/get_all_groups_including_users",
#             headers={"Authorization": f"Bearer {token}"},
#         )
#         groups_list = response.json()
#         groups_dict = {group["id"]: group for group in groups_list}
#         group_options = [
#             {"value": group["id"], "label": group["name"]}
#             for group in groups_list
#             if group["name"] not in ["admin", "users"]
#         ]
#         return groups_dict, group_options
#     except Exception as e:
#         logger.info(f"Error fetching groups data: {e}")
#         return {}, []


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
    can_edit = is_admin or is_owner

    return [
        {"field": "id", "hide": True},
        {"field": "email", "headerName": "Email", "minWidth": 200, "editable": False},
        {"field": "groups", "headerName": "Groups", "minWidth": 150, "editable": False},
        {
            "field": "Owner",
            "cellRenderer": "agCheckboxCellRenderer",
            "cellStyle": {
                "textAlign": "center",
                "pointerEvents": "none" if not can_edit else "auto",
            },
            "editable": can_edit,
            "suppressKeyboardEvent": not can_edit,
            "suppressClickEdit": not can_edit,
            "suppressMenu": True,
        },
        {
            "field": "Editor",
            "cellRenderer": "agCheckboxCellRenderer",
            "cellStyle": {
                "textAlign": "center",
                "pointerEvents": "none" if not can_edit else "auto",
            },
            "editable": can_edit,
            "suppressKeyboardEvent": not can_edit,
            "suppressClickEdit": not can_edit,
            "suppressMenu": True,
        },
        {
            "field": "Viewer",
            "cellRenderer": "agCheckboxCellRenderer",
            "cellStyle": {
                "textAlign": "center",
                "pointerEvents": "none" if not can_edit else "auto",
            },
            "editable": can_edit,
            "suppressKeyboardEvent": not can_edit,
            "suppressClickEdit": not can_edit,
            "suppressMenu": True,
        },
        {
            "field": "actions",
            "headerName": "Actions",
            "cellRenderer": "Button" if can_edit else None,
            "cellRendererParams": ({"className": "btn", "value": "🗑️"} if can_edit else {}),
            "editable": False,
            "suppressMenu": True,
        },
        {"field": "is_admin", "hide": True},
        {"field": "groups_with_metadata", "hide": True},
    ]


def create_project_header(project_name, project_id, is_public, is_admin=False, is_owner=False):
    """
    Create the project header component with title and visibility toggle.

    Args:
        project_name (str): Name of the project.
        project_id (str): Project identifier.
        is_public (bool): Current project visibility.
        is_admin (bool): Whether the current user is an admin.
        is_owner (bool): Whether the current user is a project owner.

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
        disabled=not (is_admin or is_owner),  # Only allow admins/owners to change visibility
    )
    title_button = dmc.Group([title, make_public_button], justify="space-between")
    details = dmc.Text(
        f"Project ID: {project_id}",
        size="sm",
        c="gray",
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

cannot_change_last_owner_modal, cannot_change_last_owner_modal_id = create_add_with_input_modal(
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

# Store for user permissions to avoid repeated API calls
user_permissions_store = dcc.Store(
    id="permissions-manager-user-permissions", data=None, storage_type="memory"
)

text_table_header = dmc.Text("Project Permissions", size="xl", fw="bold", c="black")

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
        user_permissions_store,
        # Project header and permissions grid
        html.Div(id="permissions-manager-project-header"),
        text_table_header,
        dcc.Store(id="permissions-manager-grid-store", storage_type="memory"),
        dag.AgGrid(
            id="permissions-manager-grid",
            columnDefs=create_column_defs(
                is_admin=False, is_owner=False
            ),  # Default to no permissions, will be updated by callback
            defaultColDef={
                "flex": 1,
                "editable": False,  # Default to non-editable, will be controlled by column definitions
                "resizable": True,
                "sortable": True,
            },
            dashGridOptions={
                "animateRows": True,
                "pagination": True,
                "paginationAutoPageSize": True,
                "getRowId": "params.data.id",
                "suppressClickEdit": True,  # Disable all click editing by default
                "readOnlyEdit": True,  # Make grid read-only by default
                "suppressCellSelection": True,  # Disable cell selection
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
                        dmc.GridCol(
                            [
                                html.Div(
                                    [
                                        dmc.Text("Permissions", fw="bold", size="sm"),
                                        dmc.Group(
                                            [
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
                                            gap="md",
                                        ),
                                    ]
                                )
                            ],
                            span=12,
                        ),
                        # DISABLED: Group management section removed for user-only permissions
                        # dmc.Col(
                        #     [
                        #         dmc.Group(
                        #             [
                        #                 dmc.Select(
                        #                     id="permissions-manager-input-group",
                        #                     label="Group",
                        #                     placeholder="Select group",
                        #                     data=[],  # Updated via callback
                        #                     searchable=True,
                        #                     clearable=True,
                        #                     nothingFound="No group found",
                        #                     style={"width": "300px"},
                        #                 ),
                        #                 dmc.Button(
                        #                     "Add Group",
                        #                     id="permissions-manager-btn-add-group",
                        #                     color="green",
                        #                     disabled=True,
                        #                 ),
                        #             ],
                        #             position="left",
                        #             align="flex-end",
                        #             style={"width": "100%"},
                        #         ),
                        #     ],
                        #     span=12,
                        # ),
                        dmc.GridCol(
                            [
                                dmc.Group(
                                    [
                                        dmc.MultiSelect(
                                            id="permissions-manager-input-email",
                                            label="Select Users",
                                            placeholder="Select users by email",
                                            data=[],  # Updated via callback
                                            searchable=True,
                                            clearable=True,
                                            nothingFoundMessage="No users found",
                                            style={"width": "400px"},
                                        ),
                                        dmc.Button(
                                            "Add Users",
                                            id="permissions-manager-btn-add-user",
                                            color="blue",
                                            disabled=True,
                                        ),
                                    ],
                                    justify="flex-start",
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
    Update project permissions via the API using centralized api_utils.

    Args:
        rows (list): Updated permissions rows.
        project_id (str): Project ID.
        token (str): Access token.

    Returns:
        bool: True if successful, False otherwise.
    """
    result = update_project_permissions_api(project_id, rows, token)
    return result["success"]


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
        Output("permissions-manager-input-email", "data"),
        Output("permissions-manager-grid", "rowData"),
        Output("permissions-manager-grid-store", "data"),
        Output("permissions-manager-project-header", "children"),
        Output("permissions-manager-grid", "columnDefs"),
        Output("permissions-manager-grid", "dashGridOptions"),
        Output("permissions-manager-user-permissions", "data"),  # Store user permissions
        Input("permissions-manager-project-header", "children"),
        State("local-store", "data"),
        State("url", "pathname"),
    )
    def initialize_data(_, local_store_data, pathname):
        """
        Initialize UI components with data fetched from the API when the page loads.
        """
        project_id = pathname.split("/")[-1]

        # Fetch all users for the MultiSelect
        user_options = fetch_all_users(token=local_store_data["access_token"])
        logger.info(f"User options: {user_options}")

        # Fetch project data.
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
            params={"project_id": project_id},
            headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
        )
        if response.status_code != 200:
            logger.error(f"Error fetching project data: {response.text}")
            return user_options, [], [], [], create_column_defs(), {}, {}

        project_data = response.json()
        project_name = project_data.get("name", "Project")

        # Get current user info and determine permissions.
        current_user = get_current_user_info(local_store_data["access_token"])
        is_admin = current_user.get("is_admin", False) if current_user else False
        is_owner = False
        if (
            "permissions" in project_data
            and "owners" in project_data["permissions"]
            and current_user
        ):
            current_user_id = current_user.get("id")
            project_owners = project_data["permissions"].get("owners", [])
            logger.info(f"Current user ID: {current_user_id}")
            logger.info(f"Current user data: {current_user}")
            logger.info(f"Project owners raw: {project_owners}")
            logger.info(
                f"Project owners _id: {[str(owner.get('_id')) for owner in project_owners]}"
            )
            logger.info(f"Project owners id: {[str(owner.get('id')) for owner in project_owners]}")
            # Only check ownership if we have a valid current user ID
            if current_user_id:
                # Try both _id and id fields to be safe
                is_owner = any(
                    str(owner.get("_id")) == str(current_user_id)
                    or str(owner.get("id")) == str(current_user_id)
                    for owner in project_owners
                )

        logger.info(
            f"Permission check - User: {current_user.get('email') if current_user else 'None'}, is_admin: {is_admin}, is_owner: {is_owner}"
        )

        column_defs = create_column_defs(is_admin=is_admin, is_owner=is_owner)
        project_header = create_project_header(
            project_name,
            project_id,
            project_data.get("is_public", False),
            is_admin=is_admin,
            is_owner=is_owner,
        )

        # Create grid options based on permissions
        can_edit = is_admin or is_owner
        grid_options = {
            "animateRows": True,
            "pagination": True,
            "paginationAutoPageSize": True,
            "getRowId": "params.data.id",
            "suppressClickEdit": not can_edit,  # Disable click editing for non-owners
            "readOnlyEdit": not can_edit,  # Make grid read-only for non-owners
            "suppressCellSelection": not can_edit,  # Disable cell selection for non-owners
        }

        current_permissions = fetch_project_permissions(
            project_id=project_id, token=local_store_data["access_token"]
        )
        logger.info(f"Current permissions: {current_permissions}")
        logger.info(f"User can edit: {can_edit}, is_admin: {is_admin}, is_owner: {is_owner}")

        # Filter out users who are already in the permissions table
        existing_user_ids = {user["id"] for user in current_permissions}
        filtered_user_options = [
            option for option in user_options if option["value"] not in existing_user_ids
        ]
        logger.info(
            f"Filtered user options: {len(filtered_user_options)} of {len(user_options)} available"
        )

        return (
            filtered_user_options,
            current_permissions,
            current_permissions,
            [project_header],
            column_defs,
            grid_options,
            {"is_admin": is_admin, "is_owner": is_owner},  # Store user permissions
        )

    # DISABLED: Email options callback removed - now using direct text input
    # @app.callback(
    #     Output("permissions-manager-input-email", "data"),
    #     Output("permissions-manager-input-email", "disabled"),
    #     Input("permissions-manager-input-group", "value"),
    # )
    # def update_email_options(selected_group_id):
    #     """
    #     Populate the email dropdown based on the selected group.
    #     """
    #     logger.info(f"Selected group ID: {selected_group_id}")
    #     logger.info(f"Groups data: {GROUPS_DATA}")
    #     if selected_group_id and selected_group_id in GROUPS_DATA:
    #         email_options = [
    #             {"value": user["id"], "label": user["email"]}
    #             for user in GROUPS_DATA[selected_group_id]["users"]
    #         ]
    #         return email_options, False
    #     return [], True

    @app.callback(
        Output("permissions-manager-btn-add-user", "disabled"),
        Output("permissions-manager-checkbox-owner", "disabled"),
        Output("permissions-manager-checkbox-editor", "disabled"),
        Output("permissions-manager-checkbox-viewer", "disabled"),
        Output("permissions-manager-input-email", "disabled"),
        Input("permissions-manager-input-email", "value"),
        Input("permissions-manager-checkbox-owner", "checked"),
        Input("permissions-manager-checkbox-editor", "checked"),
        Input("permissions-manager-checkbox-viewer", "checked"),
        State("permissions-manager-user-permissions", "data"),
        prevent_initial_call=False,  # Allow initial call to set proper state
    )
    def toggle_add_buttons(
        selected_users, owner_checked, editor_checked, viewer_checked, user_permissions_data
    ):
        """
        Enable or disable Add buttons and checkboxes based on current user and selections.
        """
        # Handle None values from initial callback
        if selected_users is None:
            selected_users = []
        if owner_checked is None:
            owner_checked = False
        if editor_checked is None:
            editor_checked = False
        if viewer_checked is None:
            viewer_checked = False

        # If user permissions data not available, keep controls enabled during initial load
        # This prevents the "flash of disabled state" during page loading
        if not user_permissions_data:
            # During initial load, enable checkboxes but disable add button until data loads
            return True, False, False, False, False

        # Get user permissions from stored data (set during initialization)
        is_admin = user_permissions_data.get("is_admin", False)
        is_owner = user_permissions_data.get("is_owner", False)

        # User must be either admin or project owner to manage permissions
        if not (is_admin or is_owner):
            return True, True, True, True, True  # Disable everything including multiselect

        # Check if users are selected and exactly one permission is selected
        users_selected = len(selected_users) > 0 if selected_users else False
        permissions_checked = [owner_checked, editor_checked, viewer_checked]
        exactly_one_permission = sum(permissions_checked) == 1

        # Debug logging to understand what's happening
        logger.info(f"Toggle buttons - user_permissions_data: {user_permissions_data}")
        logger.info(
            f"Toggle buttons - users_selected: {users_selected}, selected_users: {selected_users}"
        )
        logger.info(
            f"Toggle buttons - owner_checked: {owner_checked}, editor_checked: {editor_checked}, viewer_checked: {viewer_checked}"
        )
        logger.info(
            f"Toggle buttons - exactly_one_permission: {exactly_one_permission}, permissions_checked: {permissions_checked}"
        )
        logger.info(f"Toggle buttons - is_admin: {is_admin}, is_owner: {is_owner}")

        add_user_disabled = not (users_selected and exactly_one_permission)

        logger.info(f"Toggle buttons - add_user_disabled: {add_user_disabled}")

        # Enable checkboxes and multiselect for authorized users
        return add_user_disabled, False, False, False, False

    @app.callback(
        Output("permissions-manager-grid", "rowData", allow_duplicate=True),
        Output("permissions-manager-grid", "defaultColDef"),
        Output("permissions-manager-input-email", "value"),
        Output("permissions-manager-checkbox-owner", "checked"),
        Output("permissions-manager-checkbox-editor", "checked"),
        Output("permissions-manager-checkbox-viewer", "checked"),
        Output("permissions-manager-input-email", "data", allow_duplicate=True),
        Input("permissions-manager-btn-add-user", "n_clicks"),
        State("permissions-manager-input-email", "value"),
        State("permissions-manager-input-email", "data"),
        State("permissions-manager-checkbox-owner", "checked"),
        State("permissions-manager-checkbox-editor", "checked"),
        State("permissions-manager-checkbox-viewer", "checked"),
        State("permissions-manager-grid", "rowData"),
        State("permissions-manager-grid", "defaultColDef"),
        Input("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def add_users(
        user_clicks,
        selected_user_ids,
        dropdown_data,
        owner_checked,
        editor_checked,
        viewer_checked,
        current_rows,
        grid_options,
        local_store_data,
        pathname,
    ):
        """
        Add selected users to the project with specified permissions.
        """
        triggered_id = ctx.triggered_id

        # Convert individual checkbox states to permissions list
        permissions = []
        logger.info(
            f"Checkbox states - owner_checked: {owner_checked}, editor_checked: {editor_checked}, viewer_checked: {viewer_checked}"
        )

        if owner_checked:
            permissions.append("Owner")
        if editor_checked:
            permissions.append("Editor")
        if viewer_checked:
            permissions.append("Viewer")

        logger.info(
            f"Triggered ID: {triggered_id}, selected_user_ids: {selected_user_ids}, Permissions: {permissions}"
        )
        logger.info(f"Current rows: {current_rows}")

        if local_store_data is None:
            return current_rows, grid_options, [], False, False, False, dropdown_data

        current_user = get_current_user_info(local_store_data["access_token"])
        if not current_user:
            return current_rows, grid_options, [], False, False, False, dropdown_data

        # Check if user has permission to add users (admin or project owner)
        is_admin = current_user.get("is_admin", False)
        project_id = pathname.split("/")[-1]

        # Get project data to check ownership
        project_response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
            params={"project_id": project_id},
            headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
        )

        is_owner = False
        if project_response.status_code == 200:
            project_data = project_response.json()
            if "permissions" in project_data and "owners" in project_data["permissions"]:
                current_user_id = current_user.get("id")
                if current_user_id:  # Only check if we have a valid user ID
                    is_owner = any(
                        str(owner.get("_id")) == str(current_user_id)
                        for owner in project_data["permissions"].get("owners", [])
                    )

        # Only allow admins or project owners to add users
        if not (is_admin or is_owner):
            logger.warning(
                f"User {current_user.get('email')} attempted to add users without authorization"
            )
            grid_options["editable"] = False
            return current_rows, grid_options, [], False, False, False, dropdown_data

        # Return unchanged if missing required data.
        if not selected_user_ids or not permissions:
            return current_rows, grid_options, [], False, False, False, dropdown_data

        new_users = []
        project_id = pathname.split("/")[-1]

        # Add selected users to the project.
        if triggered_id == "permissions-manager-btn-add-user" and selected_user_ids:
            # Get detailed user data for the selected users
            users_lookup = fetch_all_users_detailed(local_store_data["access_token"])

            for user_id in selected_user_ids:
                # Get user data from the detailed lookup
                user_data = users_lookup.get(user_id)
                if not user_data:
                    logger.error(f"User data not found for user_id: {user_id}")
                    continue

                user_email = user_data["email"]

                # Skip if user already exists in the project
                if any(row["id"] == user_id for row in current_rows):
                    logger.info(f"User {user_email} already exists in project, skipping")
                    continue

                logger.info(f"Adding user: {user_email} with permissions: {permissions}")
                new_users.append(
                    {
                        "id": user_id,
                        "email": user_email,
                        "groups": "",  # Groups info not needed for basic functionality
                        "Owner": "Owner" in permissions,
                        "Editor": "Editor" in permissions,
                        "Viewer": "Viewer" in permissions,
                        "is_admin": user_data["is_admin"],
                        "groups_with_metadata": [],  # Empty since not critical
                    }
                )

        updated_rows = current_rows + new_users
        update_permissions_api(updated_rows, project_id, local_store_data["access_token"])

        # Update dropdown options by removing newly added users
        updated_dropdown_data = [
            option for option in dropdown_data if option["value"] not in selected_user_ids
        ]

        return updated_rows, grid_options, [], False, False, False, updated_dropdown_data

    @app.callback(
        Output("permissions-manager-input-email", "data", allow_duplicate=True),
        Input("permissions-manager-grid", "rowData"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_dropdown_on_grid_change(current_rows, local_store_data):
        """
        Update dropdown options when grid data changes (users added/removed).
        """
        if not local_store_data or not current_rows:
            return []

        # Fetch all users
        all_user_options = fetch_all_users(token=local_store_data["access_token"])

        # Filter out users who are already in the permissions table
        # Add defensive check for None users
        existing_user_ids = {
            user["id"] for user in current_rows if user is not None and "id" in user
        }
        filtered_user_options = [
            option
            for option in all_user_options
            if option and option.get("value") not in existing_user_ids
        ]

        logger.info(
            f"Updated dropdown: {len(filtered_user_options)} of {len(all_user_options)} users available"
        )
        return filtered_user_options

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

        # Use current_rows_store if current_rows is None
        working_rows = current_rows if current_rows is not None else current_rows_store
        logger.info(f"Working with rows: {working_rows}")

        updated_rows = []

        # Close modal if confirm/cancel clicked.
        if triggered_id in [
            "confirm-cannot-change-last-owner-add-button.n_clicks",
            "cancel-cannot-change-last-owner-add-button.n_clicks",
        ]:
            return working_rows, current_rows_store, False

        # Handle delete action via button click.
        if triggered_id == "permissions-manager-grid.cellClicked" and clicked_data:
            column = clicked_data.get("colId")
            row_id = clicked_data.get("rowId")
            if column == "actions":
                logger.info(f"Delete action triggered for row ID: {row_id}")
                current_user = get_current_user_info(local_store_data["access_token"])
                if not current_user:
                    logger.warning("No current user found - blocking delete")
                    return working_rows, current_rows_store, False

                # Check if user has permission to delete users
                is_admin = current_user.get("is_admin", False)
                project_id = pathname.split("/")[-1]

                # Get project data to check ownership
                project_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
                    params={"project_id": project_id},
                    headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
                )

                is_owner = False
                if project_response.status_code == 200:
                    project_data = project_response.json()
                    if "permissions" in project_data and "owners" in project_data["permissions"]:
                        current_user_id = current_user.get("id")
                        if current_user_id:  # Only check if we have a valid user ID
                            # Try both _id and id fields to be safe
                            is_owner = any(
                                str(owner.get("_id")) == str(current_user_id)
                                or str(owner.get("id")) == str(current_user_id)
                                for owner in project_data["permissions"].get("owners", [])
                            )

                # Only allow admins or project owners to delete users
                if not (is_admin or is_owner):
                    logger.warning(
                        f"User {current_user.get('email')} attempted to delete user without authorization"
                    )
                    # Return the original rows to prevent unauthorized deletion
                    return (
                        working_rows,
                        current_rows_store,
                        False,
                    )
                target_row = next(
                    (row for row in working_rows if str(row["id"]) == str(row_id)), None
                )
                if target_row and target_row["Owner"]:
                    # Check if the user is the last owner
                    owner_count = sum(1 for row in working_rows if row["Owner"])
                    if owner_count <= 1:
                        return working_rows, current_rows_store, True
                updated_rows = [row for row in working_rows if str(row["id"]) != str(row_id)]
                logger.info(
                    f"User {row_id} deleted successfully. Remaining users: {len(updated_rows)}"
                )

        # Handle checkbox changes for permissions.
        if triggered_id == "permissions-manager-grid.cellValueChanged" and value_changed_data:
            cell_data = value_changed_data[0]
            column = cell_data.get("colId")
            row_id = cell_data.get("rowId")
            logger.warning(
                f"CELL VALUE CHANGE DETECTED - Column: {column}, Row: {row_id}, Data: {cell_data}"
            )

            if column in ["Owner", "Editor", "Viewer"]:
                current_user = get_current_user_info(local_store_data["access_token"])
                if not current_user:
                    logger.warning("No current user found - blocking change")
                    return working_rows, current_rows_store, False

                # Check if user has permission to modify permissions
                is_admin = current_user.get("is_admin", False)
                project_id = pathname.split("/")[-1]

                # Get project data to check ownership
                project_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
                    params={"project_id": project_id},
                    headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
                )

                is_owner = False
                if project_response.status_code == 200:
                    project_data = project_response.json()
                    if "permissions" in project_data and "owners" in project_data["permissions"]:
                        current_user_id = current_user.get("id")
                        project_owners = project_data["permissions"].get("owners", [])
                        logger.info(f"Permission check in cell change - User ID: {current_user_id}")
                        logger.info(f"Project owners raw data: {project_owners}")
                        logger.info(
                            f"Project owners _id: {[str(owner.get('_id')) for owner in project_owners]}"
                        )
                        logger.info(
                            f"Project owners id: {[str(owner.get('id')) for owner in project_owners]}"
                        )
                        if current_user_id:  # Only check if we have a valid user ID
                            # Try both _id and id fields to be safe
                            is_owner = any(
                                str(owner.get("_id")) == str(current_user_id)
                                or str(owner.get("id")) == str(current_user_id)
                                for owner in project_owners
                            )

                logger.warning(
                    f"Permission check in cell change - is_admin: {is_admin}, is_owner: {is_owner}"
                )

                # Only allow admins or project owners to modify permissions
                logger.info(
                    f"Permission check: is_admin={is_admin}, is_owner={is_owner}, allowed={(is_admin or is_owner)}"
                )
                if not (is_admin or is_owner):
                    logger.warning(
                        f"User {current_user.get('email')} attempted to modify permissions without authorization - BLOCKING CHANGE"
                    )
                    # Return the original rows to revert any unauthorized changes
                    return (
                        working_rows,
                        current_rows_store,
                        False,
                    )

                current_user_id = current_user.get("id")
                owner_count = sum(1 for row in working_rows if row["Owner"])
                target_row = next(
                    (row for row in working_rows if str(row["id"]) == str(row_id)), None
                )
                # Check if the user is the last owner
                if (
                    owner_count <= 1
                    and target_row
                    and target_row["Owner"]
                    and str(target_row["id"]) == str(current_user_id)
                    and column != "Owner"
                ):
                    return working_rows, current_rows_store, True
                updated_rows = working_rows.copy()
                # Reset roles for the row and set the new role.
                for row in updated_rows:
                    if str(row["id"]) == str(row_id):
                        for role in ["Owner", "Editor", "Viewer"]:
                            row[role] = False
                        row[column] = True
                        break

        if not updated_rows:
            return working_rows, current_rows_store, False

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
        add_clicks, confirm_clicks, cancel_clicks, selected_users, current_rows
    ):
        """
        Toggle the modal warning if any of the selected users already exists.
        """
        triggered_id = ctx.triggered_id
        if triggered_id in [
            "confirm-user-exists-add-button",
            "cancel-user-exists-add-button",
        ]:
            return False
        if triggered_id == "permissions-manager-btn-add-user":
            if not add_clicks or not selected_users:
                return False
            # Check if any selected user already exists
            # Add defensive check for None rows
            current_user_ids = {
                row["id"] for row in current_rows if row is not None and "id" in row
            }
            return any(user_id in current_user_ids for user_id in selected_users)
        return False

    @app.callback(
        Output(cannot_delete_owner_modal_id, "opened"),
        Input("permissions-manager-grid", "cellClicked"),
        Input("confirm-cannot-delete-owner-add-button", "n_clicks"),
        Input("cancel-cannot-delete-owner-add-button", "n_clicks"),
        State("permissions-manager-grid", "rowData"),
        prevent_initial_call=True,
    )
    def toggle_cannot_delete_owner_modal(clicked_data, confirm_clicks, cancel_clicks, current_rows):
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
        Helper function to toggle project public/private status via API using centralized api_utils.
        """
        return toggle_project_visibility_api(project_id, is_public, token)

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
                is_public=value == "True",
            )
            if response["success"]:
                return False, value, value
            else:
                return False, dash.no_update, dash.no_update
