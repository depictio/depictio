import dash
import dash_ag_grid as dag
from dash import Dash, html, dcc, Input, Output, State, callback, ctx
import dash_mantine_components as dmc
import json
from depictio.dash.layouts.layouts_toolbox import create_add_with_input_modal


import httpx
import requests
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging import logger
from depictio_models.models.base import convert_objectid_to_str


def fetch_groups_data(token):
    """Fetch groups data from API and format it for use in the UI"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/get_all_groups_including_users",
            headers={"Authorization": f"Bearer {token}"},
        )
        groups_list = response.json()

        # Convert list to dictionary with id as key for easier lookup
        groups_dict = {group["id"]: group for group in groups_list}

        # Create mapping of group names to options for dropdown
        group_options = [
            {"value": group["id"], "label": group["name"]}
            for group in groups_list
            if group["name"] not in ["admin", "users"]
        ]

        # rename users group label to "public"
        # group_options.append({"value": "users", "label": "Public"})

        return groups_dict, group_options
    except Exception as e:
        logger.info(f"Error fetching groups data: {e}")
        return {}, []


# Initialize empty structures - will be populated by callback
GROUPS_DATA = {}
GROUP_OPTIONS = []


# Initial row data - will be populated from project permissions
rowData = []


def fetch_project_permissions(project_id, token):
    """Fetch project permissions from API"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id/{project_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        project_data = response.json()

        permissions_data = []
        if "permissions" in project_data:
            # Process owners
            for user in project_data["permissions"].get("owners", []):
                user_api = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id/{str(user['_id'])}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if user_api.status_code != 200:
                    logger.error(f"Error fetching user data: {user_api.text}")
                    continue
                user_api = user_api.json()
                logger.info(f"User API: {user_api}")
                group_name = ", ".join(
                    [
                        group["name"]
                        for group in user_api.get("groups", [])
                        if group["name"] not in ["admin", "users"]
                    ]
                )
                permissions_data.append(
                    {
                        "id": user["_id"],
                        "email": user["email"],
                        "groups": group_name,
                        "Owner": True,
                        "Editor": False,
                        "Viewer": False,
                        "is_admin": user_api.get("is_admin", False),
                        "groups_with_metadata": convert_objectid_to_str(
                            user_api.get("groups", [])
                        ),
                    }
                )

            # Process editors
            for user in project_data["permissions"].get("editors", []):
                user_api = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id/{str(user['_id'])}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if user_api.status_code != 200:
                    logger.error(f"Error fetching user data: {user_api.text}")
                    continue
                user_api = user_api.json()
                logger.info(f"User API: {user_api}")

                group_name = ", ".join(
                    [
                        group["name"]
                        for group in user_api.get("groups", [])
                        if group["name"] not in ["admin", "users"]
                    ]
                )
                permissions_data.append(
                    {
                        "id": user["_id"],
                        "email": user["email"],
                        "groups": group_name,
                        "Owner": False,
                        "Editor": True,
                        "Viewer": False,
                        "is_admin": user_api.get("is_admin", False),
                        "groups_with_metadata": convert_objectid_to_str(
                            user_api.get("groups", [])
                        ),
                    }
                )

            # Process viewers
            for user in project_data["permissions"].get("viewers", []):
                user_api = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id/{str(user['_id'])}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if user_api.status_code != 200:
                    logger.error(f"Error fetching user data: {user_api.text}")
                    continue
                user_api = user_api.json()
                logger.info(f"User API: {user_api}")
                group_name = ", ".join(
                    [
                        group["name"]
                        for group in user_api.get("groups", [])
                        if group["name"] not in ["admin", "users"]
                    ]
                )
                permissions_data.append(
                    {
                        "id": user["_id"],
                        "email": user["email"],
                        "groups": group_name,
                        "Owner": False,
                        "Editor": False,
                        "Viewer": True,
                        "is_admin": user_api.get("is_admin", False),
                        "groups_with_metadata": convert_objectid_to_str(
                            user_api.get("groups", [])
                        ),
                    }
                )

        return permissions_data
    except Exception as e:
        logger.info(f"Error fetching project permissions: {e}")
        return []


# Define a custom cell renderer function for the actions column
# This will be used to conditionally show/hide the delete button
def create_column_defs(is_admin=False, is_owner=False):
    """Create column definitions based on user permissions"""
    return [
        {
            "field": "id",
            "hide": True,
        },
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
            "cellRendererParams": {
                "className": "btn",
                "value": "🗑️",
            }
            if (is_admin or is_owner)
            else {},
        },
        {
            "field": "is_admin",
            "hide": True,
        },
        {
            "field": "groups_with_metadata",
            "hide": True,
        },
    ]


# Initialize with default column definitions (no permissions)
columnDefs = create_column_defs()

# Layout with form to add new users
# Create modal for user already exists warning
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
    "Project Permissions",
    size="xl",
    weight="bold",
    color="black",
)

layout = dmc.Container(
    [
        user_exists_modal,
        cannot_delete_owner_modal,
        make_project_public_modal,
        store_make_project_public_modal,
        html.Div(id="permissions-manager-project-header"),
        # html.Hr(style={"margin": "15px 0"}),
        # Grid first for better visibility
        text_table_header,
        dag.AgGrid(
            id="permissions-manager-grid",
            columnDefs=columnDefs,
            rowData=rowData,
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
            # height to fit the content
            # style={"height": "100%"},
            style={"height": "400px"},
            columnSize="sizeToFit",
        ),
        # Controls in a more compact layout below
        html.Hr(),
        dmc.Card(
            [
                dmc.Grid(
                    [
                        # Permissions row
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
                                ),
                            ],
                            span=12,
                        ),
                        # First row: Group selector + Add Group button
                        dmc.Col(
                            [
                                dmc.Group(
                                    [
                                        dmc.Select(
                                            id="permissions-manager-input-group",
                                            label="Group",
                                            placeholder="Select group",
                                            data=GROUP_OPTIONS,
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
                        # Second row: Email selector + Add User button
                        dmc.Col(
                            [
                                dmc.Group(
                                    [
                                        dmc.Select(
                                            id="permissions-manager-input-email",
                                            label="Email",
                                            placeholder="Select email",
                                            data=[],
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


def register_projectwise_user_management_callbacks(app):
    @callback(
        Output("make-project-public-button", "color"),
        Input("make-project-public-button", "value"),
        Input("url", "pathname"),
    )
    def update_status(value, pathname):
        logger.info(f"value : {value}")
        if value.lower() == "true":
            return "green"
        else:
            return "violet"

    # Callback to initialize data when page loads
    @app.callback(
        Output("permissions-manager-input-group", "data"),
        Output("permissions-manager-grid", "rowData"),
        Output("permissions-manager-project-header", "children"),
        Output("permissions-manager-grid", "columnDefs"),
        Input("permissions-manager-project-header", "children"),
        State("local-store", "data"),
        State("url", "pathname"),
    )
    def initialize_data(_, local_store_data, pathname):
        global GROUPS_DATA, GROUP_OPTIONS
        GROUPS_DATA, GROUP_OPTIONS = fetch_groups_data(
            token=local_store_data["access_token"]
        )
        logger.info(f"Groups data: {GROUPS_DATA}")
        logger.info(f"Group options: {GROUP_OPTIONS}")
        project_id = pathname.split("/")[-1]

        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id/{project_id}",
            headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
        )
        if response.status_code != 200:
            logger.error(f"Error fetching project data: {response.text}")
            return [], [], [], create_column_defs()
        project_data = response.json()
        project_name = project_data.get("name", "Project")

        # Get current user info to determine permissions
        response_current_user = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
            params={"token": local_store_data["access_token"]},
            headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
        )

        is_admin = False
        is_owner = False

        if response_current_user.status_code == 200:
            current_user = response_current_user.json()
            is_admin = current_user.get("is_admin", False)

            # Check if user is an owner of this project
            current_user_id = current_user.get("id")
            if (
                "permissions" in project_data
                and "owners" in project_data["permissions"]
            ):
                is_owner = any(
                    str(owner.get("_id")) == str(current_user_id)
                    for owner in project_data["permissions"].get("owners", [])
                )
                # Create column definitions based on user permissions
                column_defs = create_column_defs(is_admin=is_admin, is_owner=is_owner)

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
                    value="True" if project_data.get("is_public") else "False",
                    radius="xl",
                )

                title_button = dmc.Group(
                    [title, make_public_button],
                    position="apart",
                )
                details = dmc.Text(
                    f"Project ID: {project_id}",
                    size="sm",
                    color="gray",
                    id="permissions-manager-project-details",
                )

                # Wrap content in Paper to differentiate it from rest of UI
                project_header_paper = dmc.Paper(
                    [
                        title_button,
                        details,
                    ],
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

                current_permissions = fetch_project_permissions(
                    project_id=project_id, token=local_store_data["access_token"]
                )
                logger.info(f"Current permissions: {current_permissions}")
                return (
                    GROUP_OPTIONS,
                    current_permissions,
                    [project_header_paper],
                    column_defs,
                )

    # Callback to dynamically populate email dropdown based on selected group
    @app.callback(
        Output("permissions-manager-input-email", "data"),
        Output("permissions-manager-input-email", "disabled"),
        Input("permissions-manager-input-group", "value"),
    )
    def update_email_options(selected_group_id):
        logger.info(f"Selected group ID: {selected_group_id}")
        logger.info(f"Groups data: {GROUPS_DATA}")

        if selected_group_id and selected_group_id in GROUPS_DATA:
            # Convert users to email options
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
        Input(
            "permissions-manager-project-header", "children"
        ),  # Add this to ensure the layout is loaded
        prevent_initial_call=True,
    )
    def toggle_add_buttons(email, group, permissions, local_store_data, project_header):
        # Check if the project header is loaded, which means the layout is ready
        if not project_header:
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        if not permissions:
            permissions = []

        if local_store_data is None:
            # Disable checkboxes if local_store data is missing
            return True, True, True, True, True, True, True

        response_current_user = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
            params={"token": local_store_data["access_token"]},
            headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
        )

        if response_current_user.status_code != 200:
            logger.error(
                f"Error fetching current user data: {response_current_user.text}"
            )
            # It might be better to update checkboxes even in error case, or use no_update.
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        current_user = response_current_user.json()
        logger.info(f"Current user : {current_user}")

        if not current_user.get("is_admin", False):
            # Disable checkboxes if the user is not admin
            return True, True, True, True, True, True, True

        # Enable Add User button when an email is provided and exactly one permission is selected.
        add_user_disabled = not (email and len(permissions) == 1)

        # Enable Add Group button when a group is provided, email is empty, and exactly one permission is selected.
        add_group_disabled = not (group and not email and len(permissions) == 1)

        return add_user_disabled, add_group_disabled, False, False, False, False, False

    # Combined callback for adding users and groups
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
        # Determine which button was clicked
        triggered_id = ctx.triggered_id

        email = next(
            (item["label"] for item in dropdown_data if item["value"] == user_id), None
        )

        logger.info(f"Triggered ID: {triggered_id}")
        logger.info(f"user_id: {user_id}")
        logger.info(f"Email: {email}")
        logger.info(f"Group ID: {group_id}")
        logger.info(f"Permissions: {permissions}")
        logger.info(f"Current rows: {current_rows}")

        logger.info(f"GROUPS_DATA: {GROUPS_DATA}")

        if local_store_data is None:
            return current_rows, grid_options, "", "", []

        response_current_user = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
            params={"token": local_store_data["access_token"]},
            headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
        )

        if response_current_user.status_code != 200:
            logger.error(
                f"Error fetching current user data: {response_current_user.text}"
            )
            return current_rows, grid_options, "", "", []
        current_user = response_current_user.json()
        logger.info(f"Current user : {current_user}")

        if current_user["is_admin"] is False:
            grid_options["editable"] = False
            logger.info("User is not admin")
            logger.info(f"Grid options: {grid_options}")
            return current_rows, grid_options, "", "", []

        if not group_id or not permissions or group_id not in GROUPS_DATA:
            return current_rows, grid_options, "", "", []

        new_users = []

        # For individual user addition
        if triggered_id == "permissions-manager-btn-add-user" and email:
            retrieve_user = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id/{user_id}",
                headers={"Authorization": f"Bearer {local_store_data['access_token']}"},
            )

            if retrieve_user.status_code != 200:
                logger.error(f"Error fetching user data: {retrieve_user.text}")
                return current_rows, grid_options, "", "", []

            retrieve_user = retrieve_user.json()
            logger.info(f"Retrieved user: {retrieve_user}")

            groups = ", ".join(
                [
                    group["name"]
                    for group in retrieve_user.get("groups", [])
                    if group["name"] not in ["admin", "users"]
                ]
            )

            # Check if user already exists in current rows
            if any(row["email"] == email for row in current_rows):
                # Return current state without changes to trigger modal
                return current_rows, grid_options, email, group_id, permissions

            logger.info(
                f"Adding user: {email} with group: {groups} and permissions: {permissions}"
            )

            new_users.append(
                {
                    "id": user_id,
                    "email": email,
                    "groups": groups,
                    "Owner": "Owner" in permissions,
                    "Editor": "Editor" in permissions,
                    "Viewer": "Viewer" in permissions,
                    "is_admin": retrieve_user.get("is_admin", False),
                    "groups_with_metadata": convert_objectid_to_str(
                        retrieve_user.get("groups", [])
                    ),
                }
            )

        # For group addition
        elif triggered_id == "permissions-manager-btn-add-group":
            for user in GROUPS_DATA[group_id]["users"]:
                retrieve_user_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id/{str(user['id'])}",
                    headers={
                        "Authorization": f"Bearer {local_store_data['access_token']}"
                    },
                )

                if retrieve_user_response.status_code != 200:
                    logger.error(
                        f"Error fetching user data: {retrieve_user_response.text}"
                    )
                    continue
                retrieve_user = retrieve_user_response.json()

                groups = ", ".join(
                    [
                        group["name"]
                        for group in retrieve_user.get("groups", [])
                        if group["name"] not in ["admin", "users"]
                    ]
                )
                # Check if email already exists in current rows
                if not any(row["email"] == user["email"] for row in current_rows):
                    new_users.append(
                        {
                            "id": user["id"],  # Use existing user ID
                            "email": user["email"],
                            "groups": groups,
                            "Owner": "Owner" in permissions,
                            "Editor": "Editor" in permissions,
                            "Viewer": "Viewer" in permissions,
                            "is_admin": user["is_admin"],
                            "groups_with_metadata": convert_objectid_to_str(
                                retrieve_user.get("groups", [])
                            ),
                        }
                    )

        # Add to current rows
        updated_rows = current_rows + new_users

        logger.info(f"Updated rows: {updated_rows}")

        permissions_payload = {
            "owners": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                    "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                }
                for user in updated_rows
                if user["Owner"]
            ],
            "editors": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                    "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                }
                for user in updated_rows
                if user["Editor"]
            ],
            "viewers": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                    "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                }
                for user in updated_rows
                if user["Viewer"]
            ],
        }
        logger.info(f"Permissions payload: {permissions_payload}")
        from depictio_models.models.users import Permission

        permissions_payload_pydantic = Permission(**permissions_payload)
        logger.info(f"Permissions payload pydantic: {permissions_payload_pydantic}")
        # logger.info(f"Permissions payload: {permissions_payload}")

        project_id = pathname.split("/")[-1]
        response_project_permissions_update = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/update_project_permissions",
            headers={
                "Authorization": f"Bearer {local_store_data['access_token']}",
                "Content-Type": "application/json",
            },
            json={
                "project_id": project_id,
                "permissions": convert_objectid_to_str(permissions_payload),
            },
        )
        if response_project_permissions_update.status_code != 200:
            logger.error(
                f"Error updating project permissions: {response_project_permissions_update.text}"
            )
            return current_rows, grid_options, "", "", []

        logger.info(
            f"Updated permissions in API: {response_project_permissions_update.json()}"
        )

        # Return updated rows and reset form
        return updated_rows, grid_options, "", "", []

    # Callback to handle cell clicks and delete actions
    @app.callback(
        Output("permissions-manager-grid", "rowData", allow_duplicate=True),
        Input("permissions-manager-grid", "cellClicked"),
        Input("permissions-manager-grid", "cellValueChanged"),
        State("permissions-manager-grid", "rowData"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def handle_cell_click_and_delete(
        clicked_data, value_changed_data, current_rows, local_store_data, pathname
    ):
        triggered_id = ctx.triggered[0]["prop_id"]
        logger.info(f"Triggered ID: {triggered_id}")
        logger.info(f"Clicked data: {clicked_data}")
        logger.info(f"Value changed data: {value_changed_data}")
        logger.info(f"Current rows: {current_rows}")
        current_owners_ids = set([row["id"] for row in current_rows if row["Owner"]])

        updated_rows = list()

        # Handle button clicks (delete action)
        if "permissions-manager-grid.cellClicked" == triggered_id and clicked_data:
            column = clicked_data.get("colId")
            row_id = clicked_data.get("rowId")

            logger.info(f"Column: {column}")
            logger.info(f"Row ID: {row_id}")

            if column == "actions":
                response_current_user = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
                    params={"token": local_store_data["access_token"]},
                    headers={
                        "Authorization": f"Bearer {local_store_data['access_token']}"
                    },
                )

                if response_current_user.status_code != 200:
                    logger.error(
                        f"Error fetching current user data: {response_current_user.text}"
                    )
                    return current_rows

                current_user = response_current_user.json()
                logger.info(f"Current user: {current_user}")

                if (current_user["is_admin"] is False) or (
                    current_user["id"] not in current_owners_ids
                ):
                    return current_rows

                logger.info(f"Delete button clicked for row ID: {row_id}")
                # Check if trying to delete the last owner
                target_row = next(
                    (row for row in current_rows if str(row["id"]) == str(row_id)), None
                )
                if target_row and target_row["Owner"]:
                    owner_count = sum(1 for row in current_rows if row["Owner"])
                    if owner_count <= 1:
                        return current_rows

                updated_rows = [
                    row for row in current_rows if str(row["id"]) != str(row_id)
                ]

        # Handle checkbox changes
        if (
            triggered_id == "permissions-manager-grid.cellValueChanged"
            and value_changed_data
        ):
            cell_data = value_changed_data[0]
            column = cell_data.get("colId")
            row_id = cell_data.get("rowId")

            # Handle checkbox columns
            role_columns = ["Owner", "Editor", "Viewer"]
            if column in role_columns:
                logger.info("Processing role selection")
                updated_rows = current_rows.copy()

                # Find the row that was clicked
                for row in updated_rows:
                    if str(row["id"]) == str(row_id):
                        logger.info(f"Found row: {row}")

                        # Set all role columns to False first
                        for role in role_columns:
                            logger.info(f"Setting {role} to False")
                            row[role] = False

                        # Then set the clicked column to True
                        logger.info(f"Setting {column} to True")
                        row[column] = True
                        break

                logger.info(f"Updated rows: {updated_rows}")

        if not updated_rows:
            return current_rows

        else:
            permissions_payload = {
                "owners": [
                    {
                        "_id": user["id"],
                        "email": user["email"],
                        "is_admin": user["is_admin"],
                        "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                    }
                    for user in updated_rows
                    if user["Owner"]
                ],
                "editors": [
                    {
                        "_id": user["id"],
                        "email": user["email"],
                        "is_admin": user["is_admin"],
                        "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                    }
                    for user in updated_rows
                    if user["Editor"]
                ],
                "viewers": [
                    {
                        "_id": user["id"],
                        "email": user["email"],
                        "is_admin": user["is_admin"],
                        "groups": convert_objectid_to_str(user["groups_with_metadata"]),
                    }
                    for user in updated_rows
                    if user["Viewer"]
                ],
            }
        logger.info(f"Permissions payload: {permissions_payload}")
        from depictio_models.models.users import Permission

        permissions_payload_pydantic = Permission(**permissions_payload)
        logger.info(f"Permissions payload pydantic: {permissions_payload_pydantic}")
        # logger.info(f"Permissions payload: {permissions_payload}")

        project_id = pathname.split("/")[-1]

        response_project_permissions_update = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/update_project_permissions",
            headers={
                "Authorization": f"Bearer {local_store_data['access_token']}",
                "Content-Type": "application/json",
            },
            json={
                "project_id": project_id,
                "permissions": convert_objectid_to_str(permissions_payload),
            },
        )
        if response_project_permissions_update.status_code != 200:
            logger.error(
                f"Error updating project permissions: {response_project_permissions_update.text}"
            )
            return current_rows

        logger.info(
            f"Updated permissions in API: {response_project_permissions_update.json()}"
        )

        return updated_rows

    # Callback to handle user exists modal
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
        triggered_id = ctx.triggered_id

        # Close modal on confirm or cancel
        if triggered_id in [
            "confirm-user-exists-add-button",
            "cancel-user-exists-add-button",
        ]:
            return False

        # Show modal when adding existing user
        if triggered_id == "permissions-manager-btn-add-user":
            if not add_clicks or not email:
                return False
            user_exists = any(row["email"] == email for row in current_rows)
            return user_exists

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
        logger.info(f"Clicked data: {clicked_data}")
        triggered_id = ctx.triggered[0]["prop_id"]
        logger.info(f"Triggered ID: {triggered_id}")
        # Close modal on confirm or cancel
        if triggered_id in [
            "confirm-cannot-delete-owner-button",
            "cancel-cannot-delete-owner-button",
        ]:
            return False

        # Show modal when deleting last owner
        if "permissions-manager-grid.cellClicked" == triggered_id and clicked_data:
            logger.info(f"Clicked data: {clicked_data}")
            logger.info(f"Current rows: {current_rows}")
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
        triggered_id = ctx.triggered_id
        logger.info(f"Triggered ID: {triggered_id}")
        logger.info(f"Value: {value}")

        if triggered_id == "make-project-public-button":
            if store_data:
                if value != store_data:
                    return True, dash.no_update, dash.no_update
                else:
                    return dash.no_update, dash.no_update, dash.no_update
            else:
                return False, dash.no_update, value
        elif triggered_id in [
            "cancel-make-project-public-add-button",
        ]:
            return False, store_data, dash.no_update
        elif triggered_id in [
            "confirm-make-project-public-add-button",
        ]:
            project_id = pathname.split("/")[-1]

            logger.info(f"Value in modal: {value}")

            response = api_toggle_project_public_private(
                project_id=str(project_id),
                token=local_store["access_token"],
                is_public=value,
            )
            if response["success"]:
                return False, value, value
            else:
                return False, dash.no_update, dash.no_update
