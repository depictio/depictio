#!/usr/bin/env python3
"""
Debug AG Grid App - Minimal reproduction to test AG Grid loading issues

This app reproduces the exact AG Grid setup that's causing crashes in
projectwise_user_management.py to help identify what's wrong.
"""

import dash
import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import Input, Output, State, callback, dcc, html

# Initialize the Dash app
app = dash.Dash(__name__)

# Sample data that mimics the permissions structure
SAMPLE_PERMISSIONS = [
    {
        "id": "user1",
        "email": "user1@example.com",
        "groups": "admin, users",
        "Owner": True,
        "Editor": False,
        "Viewer": False,
    },
    {
        "id": "user2",
        "email": "user2@example.com",
        "groups": "users",
        "Owner": False,
        "Editor": True,
        "Viewer": False,
    },
    {
        "id": "user3",
        "email": "user3@example.com",
        "groups": "users",
        "Owner": False,
        "Editor": False,
        "Viewer": True,
    },
]


def create_column_defs(is_admin=False, is_owner=False):
    """
    Create column definitions for the permissions grid based on user roles.
    This matches the function from projectwise_user_management.py
    """
    can_edit = is_admin or is_owner
    print(
        f"🔧 Creating column defs - can_edit: {can_edit}, is_admin: {is_admin}, is_owner: {is_owner}"
    )

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
            "suppressMenu": True,
            "width": 100,
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
            "suppressMenu": True,
            "width": 100,
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
            "suppressMenu": True,
            "width": 100,
        },
        {
            "field": "actions",
            "headerName": "Actions",
            "cellRenderer": "DashIconify",
            "cellRendererParams": {
                "icon": "mdi:delete",
                "color": "red",
                "width": 20,
            },
            "width": 100,
            "editable": False,
            "suppressMenu": True,
        }
        if can_edit
        else None,
    ]


# Layout of the app
app.layout = dmc.MantineProvider(
    [
        dmc.Container(
            [
                dmc.Title("🔍 AG Grid Debug App", order=1),
                dmc.Text("Testing AG Grid initialization and loading states", size="lg"),
                html.Hr(),
                # Control buttons to test different states
                dmc.Group(
                    [
                        dmc.Button("Test as Admin", id="btn-admin", color="red"),
                        dmc.Button("Test as Owner", id="btn-owner", color="blue"),
                        dmc.Button("Test as Viewer", id="btn-viewer", color="gray"),
                        dmc.Button("Test Empty Grid", id="btn-empty", color="orange"),
                    ]
                ),
                html.Hr(),
                # Debug info
                dcc.Store(id="debug-store", data={"is_admin": False, "is_owner": False}),
                html.Div(id="debug-info"),
                html.Hr(),
                # The AG Grid that's causing issues - EXACT copy from projectwise_user_management.py
                dmc.Text("🏗️ AG Grid Component:", fw="bold"),
                dag.AgGrid(
                    id="debug-permissions-grid",
                    rowData=[],  # Start empty, will be populated by callback
                    columnDefs=create_column_defs(is_admin=False, is_owner=False),
                    defaultColDef={
                        "flex": 1,
                        "editable": False,
                        "resizable": True,
                        "sortable": True,
                    },
                    dashGridOptions={
                        "animateRows": True,
                        "pagination": True,
                        "paginationAutoPageSize": True,
                        "getRowId": "params.data.id",
                        "suppressClickEdit": True,
                        "readOnlyEdit": True,
                        "suppressCellSelection": True,
                    },
                    className="ag-theme-alpine",
                    style={"height": "400px"},
                    columnSize="sizeToFit",
                ),
                html.Hr(),
                # Raw data display for comparison
                dmc.Text("📋 Raw Data for Reference:", fw="bold"),
                html.Pre(id="raw-data-display"),
            ],
            size="lg",
        )
    ]
)


@callback(
    Output("debug-permissions-grid", "rowData"),
    Output("debug-permissions-grid", "columnDefs"),
    Output("debug-permissions-grid", "dashGridOptions"),
    Output("debug-info", "children"),
    Output("raw-data-display", "children"),
    Output("debug-store", "data"),
    Input("btn-admin", "n_clicks"),
    Input("btn-owner", "n_clicks"),
    Input("btn-viewer", "n_clicks"),
    Input("btn-empty", "n_clicks"),
    State("debug-store", "data"),
    prevent_initial_call=False,
)
def update_grid_state(admin_clicks, owner_clicks, viewer_clicks, empty_clicks, store_data):
    """
    Update the grid based on button clicks to test different permission states.
    """
    print(f"\n🔄 Callback triggered!")
    print(f"   admin_clicks: {admin_clicks}")
    print(f"   owner_clicks: {owner_clicks}")
    print(f"   viewer_clicks: {viewer_clicks}")
    print(f"   empty_clicks: {empty_clicks}")

    # Determine which button was clicked
    ctx = dash.callback_context
    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None
    print(f"   triggered_id: {triggered_id}")

    # Set permissions based on clicked button
    is_admin = False
    is_owner = False
    test_data = SAMPLE_PERMISSIONS.copy()

    if triggered_id == "btn-admin":
        is_admin = True
        status = "🔴 ADMIN MODE"
        print("   → Setting admin mode")
    elif triggered_id == "btn-owner":
        is_owner = True
        status = "🔵 OWNER MODE"
        print("   → Setting owner mode")
    elif triggered_id == "btn-viewer":
        status = "⚪ VIEWER MODE"
        print("   → Setting viewer mode")
    elif triggered_id == "btn-empty":
        test_data = []
        status = "🟠 EMPTY GRID MODE"
        print("   → Setting empty grid mode")
    else:
        status = "🟢 INITIAL LOAD"
        print("   → Initial load")

    # Create column definitions and grid options
    column_defs = create_column_defs(is_admin=is_admin, is_owner=is_owner)
    print(f"   → Created {len(column_defs)} column definitions")

    can_edit = is_admin or is_owner
    grid_options = {
        "animateRows": True,
        "pagination": True,
        "paginationAutoPageSize": True,
        "getRowId": "params.data.id",
        "suppressClickEdit": not can_edit,
        "readOnlyEdit": not can_edit,
        "suppressCellSelection": not can_edit,
    }
    print(f"   → Created grid options, can_edit: {can_edit}")

    # Debug info display
    debug_info = dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Badge(status, size="lg"),
                    dmc.Text(f"is_admin: {is_admin}"),
                    dmc.Text(f"is_owner: {is_owner}"),
                    dmc.Text(f"can_edit: {can_edit}"),
                ]
            ),
            dmc.Text(f"Data rows: {len(test_data)}"),
            dmc.Text(f"Column defs: {len(column_defs)}"),
            dmc.Text(f"Grid options: {list(grid_options.keys())}"),
        ],
        withBorder=True,
        p="md",
    )

    # Raw data for inspection
    raw_data = f"SAMPLE_PERMISSIONS = {test_data}"

    store_update = {"is_admin": is_admin, "is_owner": is_owner}

    print(f"   → Returning data with {len(test_data)} rows")
    print(f"   → Column definitions: {[col['field'] for col in column_defs]}")
    print(f"✅ Callback complete\n")

    return test_data, column_defs, grid_options, debug_info, raw_data, store_update


@callback(
    Output("debug-permissions-grid", "cellValueChanged"),
    Input("debug-permissions-grid", "cellValueChanged"),
    State("debug-store", "data"),
    prevent_initial_call=True,
)
def handle_cell_value_changed(cell_changed, store_data):
    """
    Handle cell value changes - this callback mimics the problematic one in the main app.
    """
    print(f"\n📝 Cell value changed!")
    print(f"   cell_changed: {cell_changed}")
    print(f"   store_data: {store_data}")

    if not cell_changed:
        print("   → No change data, preventing update")
        return dash.no_update

    changed_data = cell_changed[0] if isinstance(cell_changed, list) else cell_changed
    print(f"   → Changed: {changed_data}")

    # Just log for now, don't do anything that could cause loops
    return dash.no_update


if __name__ == "__main__":
    print("🚀 Starting AG Grid Debug App...")
    print("📍 Open http://localhost:8052 to test")
    print("🔍 Check console for detailed logging")

    app.run(
        debug=True,
        host="0.0.0.0",
        port=8053,
        dev_tools_hot_reload=True,
        dev_tools_ui=True,
    )
