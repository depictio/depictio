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
                group_name = ", ".join(
                    [group["name"] for group in user_api.get("groups", [])]
                )
                permissions_data.append(
                    {
                        "id": user["_id"],
                        "email": user["email"],
                        "groups": group_name,
                        "Owner": True,
                        "Editor": False,
                        "Viewer": False,
                    }
                )

            # Process editors
            for user in project_data["permissions"].get("editors", []):
                group_name = ", ".join(
                    [group["name"] for group in user_api.get("groups", [])]
                )
                permissions_data.append(
                    {
                        "id": user["_id"],
                        "email": user["email"],
                        "groups": group_name,
                        "Owner": False,
                        "Editor": True,
                        "Viewer": False,
                    }
                )

            # Process viewers
            for user in project_data["permissions"].get("viewers", []):
                group_name = ", ".join(
                    [group["name"] for group in user_api.get("groups", [])]
                )
                permissions_data.append(
                    {
                        "id": user["_id"],
                        "email": user["email"],
                        "groups": group_name,
                        "Owner": False,
                        "Editor": False,
                        "Viewer": True,
                    }
                )

        return permissions_data
    except Exception as e:
        logger.info(f"Error fetching project permissions: {e}")
        return []


columnDefs = [
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
        "cellRenderer": "Button",
        "cellRendererParams": {
            "className": "btn",
            "value": "🗑️",
        },
    },
]

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
    title="Make Project Public",
    title_color="green",
    message="Are you sure you want to change visibility of the project?",
    confirm_button_text="Yes",
    confirm_button_color="green",
    cancel_button_text="No",
    icon="mdi:jira",
    opened=False,
)

store_make_project_public_modal = dcc.Store(id="store-make-project-public", data=None, storage_type="memory")

layout = dmc.Container(
    [
        user_exists_modal,
        cannot_delete_owner_modal,
        make_project_public_modal,
        store_make_project_public_modal,
        html.Div(id="permissions-manager-project-header"),
        # Grid first for better visibility
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
            style={"height": "400px"},
            columnSize="sizeToFit",
        ),
        # Controls in a more compact layout below
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
                                        dmc.Checkbox(label="Owner", value="Owner"),
                                        dmc.Checkbox(label="Editor", value="Editor"),
                                        dmc.Checkbox(label="Viewer", value="Viewer"),
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
                                            id="permissions-managerinput-group",
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
    # Callback to initialize data when page loads
    @app.callback(
        Output("permissions-managerinput-group", "data"),
        Output("permissions-manager-grid", "rowData"),
        Output("permissions-manager-project-header", "children"),
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
            return [], []
        project_data = response.json()
        project_name = project_data.get("name", "Project")

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

        current_permissions = fetch_project_permissions(
            project_id=project_id, token=local_store_data["access_token"]
        )
        logger.info(f"Current permissions: {current_permissions}")
        return (
            GROUP_OPTIONS,
            current_permissions,
            [title_button, details],
        )

    # Callback to dynamically populate email dropdown based on selected group
    @app.callback(
        Output("permissions-manager-input-email", "data"),
        Output("permissions-manager-input-email", "disabled"),
        Input("permissions-managerinput-group", "value"),
    )
    def update_email_options(selected_group_id):
        if selected_group_id and selected_group_id in GROUPS_DATA:
            # Convert users to email options
            email_options = [
                {"value": user["email"], "label": user["email"]}
                for user in GROUPS_DATA[selected_group_id]["users"]
            ]
            return email_options, False
        return [], True

    # Merged callback to enable/disable Add User and Add Group buttons
    @app.callback(
        Output("permissions-manager-btn-add-user", "disabled"),
        Output("permissions-manager-btn-add-group", "disabled"),
        Input("permissions-manager-input-email", "value"),
        Input("permissions-managerinput-group", "value"),
        Input("permissions-manager-checkboxes", "value"),
        prevent_initial_call=True,
    )
    def toggle_add_buttons(email, group, permissions):
        if not permissions:
            permissions = []

        # Add User button is enabled when email and permissions are selected
        add_user_disabled = not (email and len(permissions) > 0 and group == "Public")

        # Add Group button is enabled when group and permissions are selected
        add_group_disabled = not (group and not email and len(permissions) > 0)

        return add_user_disabled, add_group_disabled

    # Combined callback for adding users and groups
    @app.callback(
        Output("permissions-manager-grid", "rowData", allow_duplicate=True),
        Output("permissions-manager-input-email", "value"),
        Output("permissions-managerinput-group", "value"),
        Output("permissions-manager-checkboxes", "value"),
        Input("permissions-manager-btn-add-user", "n_clicks"),
        Input("permissions-manager-btn-add-group", "n_clicks"),
        State("permissions-manager-input-email", "value"),
        State("permissions-managerinput-group", "value"),
        State("permissions-manager-checkboxes", "value"),
        State("permissions-manager-grid", "rowData"),
        prevent_initial_call=True,
    )
    def add_user_or_group(
        user_clicks, group_clicks, email, group_id, permissions, current_rows
    ):
        # Determine which button was clicked
        triggered_id = ctx.triggered_id

        if not group_id or not permissions or group_id not in GROUPS_DATA:
            return current_rows, "", "", []

        group_name = GROUPS_DATA[group_id]["name"]
        new_users = []

        # For individual user addition
        if triggered_id == "permissions-manager-btn-add-user" and email:
            # Check if user already exists in current rows
            if any(row["email"] == email for row in current_rows):
                # Return current state without changes to trigger modal
                return current_rows, email, group_id, permissions

            # Find user in the group data to get their ID
            user_data = next(
                (
                    user
                    for user in GROUPS_DATA[group_id]["users"]
                    if user["email"] == email
                ),
                None,
            )
            if user_data:
                new_users.append(
                    {
                        "id": user_data["id"],  # Use existing user ID
                        "email": email,
                        "groups": group_name,
                        "Owner": "Owner" in permissions,
                        "Editor": "Editor" in permissions,
                        "Viewer": "Viewer" in permissions,
                    }
                )

        # For group addition
        elif triggered_id == "permissions-manager-btn-add-group":
            for user in GROUPS_DATA[group_id]["users"]:
                # Check if email already exists in current rows
                if not any(row["email"] == user["email"] for row in current_rows):
                    new_users.append(
                        {
                            "id": user["id"],  # Use existing user ID
                            "email": user["email"],
                            "groups": group_name,
                            "Owner": "Owner" in permissions,
                            "Editor": "Editor" in permissions,
                            "Viewer": "Viewer" in permissions,
                        }
                    )

        # Add to current rows
        updated_rows = current_rows + new_users

        # Return updated rows and reset form
        return updated_rows, "", "", []

    # Callback to handle cell clicks and delete actions
    @app.callback(
        Output("permissions-manager-grid", "rowData", allow_duplicate=True),
        Input("permissions-manager-grid", "cellClicked"),
        Input("permissions-manager-grid", "cellValueChanged"),
        State("permissions-manager-grid", "rowData"),
        prevent_initial_call=True,
    )
    def handle_cell_click_and_delete(clicked_data, value_changed_data, current_rows):
        triggered_id = ctx.triggered[0]["prop_id"]
        logger.info(f"Triggered ID: {triggered_id}")
        logger.info(f"Clicked data: {clicked_data}")
        logger.info(f"Value changed data: {value_changed_data}")
        logger.info(f"Current rows: {current_rows}")

        # Handle button clicks (delete action)
        if "permissions-manager-grid.cellClicked" == triggered_id and clicked_data:
            column = clicked_data.get("colId")
            row_id = clicked_data.get("rowId")

            logger.info(f"Column: {column}")
            logger.info(f"Row ID: {row_id}")

            if column == "actions":
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
                return updated_rows

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

                return updated_rows

        return current_rows

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

    @app.callback(
        Output(make_project_public_modal_id, "opened"),
        Output("make-project-public-button", "value"),
        Output("store-make-project-public", "data"),
        Input("make-project-public-button", "value"),
        Input("confirm-make-project-public-add-button", "n_clicks"),
        Input("cancel-make-project-public-add-button", "n_clicks"),
        State("store-make-project-public", "data"),
        prevent_initial_call=True,
    )
    def toggle_make_project_public_modal(
        value, confirm_clicks, cancel_clicks, store_data
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
            return False, value, value
