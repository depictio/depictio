import uuid

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import Dash, Input, Output, State, callback, ctx

app = Dash(__name__)

# Group composition mapping
GROUP_COMPOSITION = {
    "Engineering": ["alice@company.org", "bob@startup.net", "charlie@enterprise.com"],
    "Marketing": ["diana@research.edu", "eve@marketing.com"],
    "Sales": ["frank@sales.org", "grace@enterprise.com"],
    "Research": ["henry@research.edu", "ivy@innovation.com"],
    "Customer Support": ["jack@support.net", "kate@helpdesk.com"],
}

# Flatten email options from group composition
EMAIL_OPTIONS = [email for group_emails in GROUP_COMPOSITION.values() for email in group_emails]
GROUP_OPTIONS = list(GROUP_COMPOSITION.keys())

# Initial row data
rowData = [
    {
        "id": 1,
        "email": "alice@company.org",
        "group": "Engineering",
        "Owner": True,
        "Editor": False,
        "Viewer": False,
    }
]

columnDefs = [
    {
        "field": "id",
        "hide": True,
    },
    {"field": "email", "headerName": "Email", "minWidth": 200},
    {"field": "group", "headerName": "Group", "minWidth": 150},
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
            "style": {
                "fontSize": "14px",
                "padding": "6px 12px",
                "margin": "4px",
                "boxShadow": "0 2px 5px rgba(0,0,0,0.2)",
            },
            "value": "🗑️",
        },
    },
]

# Layout with form to add new users
app.layout = dmc.Container(
    [
        dmc.Title("User Permissions Manager", order=1, mb=20),
        dmc.Card(
            [
                dmc.Grid(
                    [
                        dmc.Col(
                            [
                                dmc.Select(
                                    id="input-group",
                                    label="Group",
                                    placeholder="Select group",
                                    data=GROUP_OPTIONS,
                                    searchable=True,
                                    clearable=True,
                                    nothingFound="No group found",
                                    style={
                                        # "height": "100%",
                                        "overflow": "visible",
                                        "position": "relative",
                                        # "overflowY": "auto",
                                    },
                                )
                            ],
                            span=4,
                        ),
                        dmc.Col(
                            [
                                dmc.Select(
                                    id="input-email",
                                    label="Email",
                                    placeholder="Select email",
                                    data=[],  # Will be dynamically populated
                                    searchable=True,
                                    clearable=True,
                                    nothingFound="No email found",
                                    disabled=True,
                                    style={"minHeight": "80px"},
                                )
                            ],
                            span=4,
                        ),
                        dmc.Col(
                            [
                                dmc.Text("Permissions", fw="medium", mb=10),
                                dmc.CheckboxGroup(
                                    id="input-permissions",
                                    orientation="horizontal",
                                    children=[
                                        dmc.Checkbox(label="Owner", value="Owner"),
                                        dmc.Checkbox(label="Editor", value="Editor"),
                                        dmc.Checkbox(label="Viewer", value="Viewer"),
                                    ],
                                    style={"minHeight": "80px"},
                                ),
                            ],
                            span=6,
                        ),
                        dmc.Col(
                            [
                                dmc.Button(
                                    "Add User",
                                    id="btn-add-user",
                                    color="blue",
                                    mt=25,
                                    disabled=True,
                                ),
                                dmc.Button(
                                    "Add Group",
                                    id="btn-add-group",
                                    color="green",
                                    mt=25,
                                    ml=10,
                                    disabled=True,
                                ),
                            ],
                            span=6,
                        ),
                    ],
                )
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            mb=20,
            style={
                "minHeight": "200px",
                "display": "flex",
                "flexWrap": "wrap",
                "overflow": "visible",
                "position": "relative",
            },
        ),
        dag.AgGrid(
            id="permission-grid",
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
            style={"height": "500px"},
            columnSize="sizeToFit",
        ),
    ]
)


# Callback to dynamically populate email dropdown based on selected group
@callback(
    Output("input-email", "data"),
    Output("input-email", "disabled"),
    Input("input-group", "value"),
)
def update_email_options(selected_group):
    if selected_group:
        return GROUP_COMPOSITION[selected_group], False
    return [], True


# Merged callback to enable/disable Add User and Add Group buttons
@callback(
    Output("btn-add-user", "disabled"),
    Output("btn-add-group", "disabled"),
    Input("input-email", "value"),
    Input("input-group", "value"),
    Input("input-permissions", "value"),
    prevent_initial_call=True,
)
def toggle_add_buttons(email, group, permissions):
    if not permissions:
        permissions = []

    # Add User button is enabled when email and permissions are selected
    add_user_disabled = not (email and len(permissions) > 0)

    # Add Group button is enabled when group and permissions are selected
    add_group_disabled = not (group and not email and len(permissions) > 0)

    print(f"Email: {email}, Group: {group}, Permissions: {permissions}")
    print(f"Add User disabled: {add_user_disabled}, Add Group disabled: {add_group_disabled}")

    return add_user_disabled, add_group_disabled


# Combined callback for adding users and groups
@callback(
    Output("permission-grid", "rowData", allow_duplicate=True),
    Output("input-email", "value"),
    Output("input-group", "value"),
    Output("input-permissions", "value"),
    Input("btn-add-user", "n_clicks"),
    Input("btn-add-group", "n_clicks"),
    State("input-email", "value"),
    State("input-group", "value"),
    State("input-permissions", "value"),
    State("permission-grid", "rowData"),
    prevent_initial_call=True,
)
def add_user_or_group(user_clicks, group_clicks, email, group, permissions, current_rows):
    # Determine which button was clicked
    triggered_id = ctx.triggered_id

    if not group or not permissions:
        return current_rows, "", "", []

    # Create new users
    new_users = []

    # For individual user addition
    if triggered_id == "btn-add-user" and email:
        new_users.append(
            {
                "id": str(uuid.uuid4()),
                "email": email,
                "group": group,
                "Owner": "Owner" in permissions,
                "Editor": "Editor" in permissions,
                "Viewer": "Viewer" in permissions,
            }
        )

    # For group addition
    elif triggered_id == "btn-add-group":
        for email in GROUP_COMPOSITION[group]:
            # Check if email already exists in current rows
            if not any(row["email"] == email for row in current_rows):
                new_users.append(
                    {
                        "id": str(uuid.uuid4()),
                        "email": email,
                        "group": group,
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
@callback(
    Output("permission-grid", "rowData", allow_duplicate=True),
    Input("permission-grid", "cellValueChanged"),
    State("permission-grid", "rowData"),
    prevent_initial_call=True,
)
def handle_cell_click_and_delete(cell_data, current_rows):
    if not cell_data:
        return current_rows

    print(f"Cell clicked: {cell_data}")
    print(f"Current rows: {current_rows}")

    cell_data = cell_data[0]
    print(f"Cell data: {cell_data}")

    column = cell_data.get("colId")
    row_id = cell_data.get("rowId")

    print(f"Column: {column}")
    print(f"Row ID: {row_id}")

    # Handle checkbox columns
    role_columns = ["Owner", "Editor", "Viewer"]
    if column in role_columns:
        print("Processing role selection")
        updated_rows = current_rows.copy()

        # Find the row that was clicked
        for row in updated_rows:
            if str(row["id"]) == str(row_id):
                print(f"Found row: {row}")

                # Set all role columns to False first
                for role in role_columns:
                    print(f"Setting {role} to False")
                    row[role] = False

                # Then set the clicked column to True
                print(f"Setting {column} to True")
                row[column] = True
                break

        return updated_rows

    # Handle delete button
    elif column == "actions":
        print(f"Deleting row with ID: {row_id}")
        updated_rows = [row for row in current_rows if str(row["id"]) != str(row_id)]
        return updated_rows

    return current_rows


if __name__ == "__main__":
    app.run(debug=True)
