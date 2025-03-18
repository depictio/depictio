import dash_ag_grid as dag
from dash import Dash, html, Input, Output, State, callback
import json
import dash

app = Dash()

rowData = [
    {
        "id": 1,
        "email": "toto",
        "Owner": True,
        "Editor": False,
        "Viewer": False,
    }
]

columnDefs = [
    # set types
    {"field": "id", "editable": False},
    {"field": "email", "editable": True},
    {
        "field": "Owner",
        "cellRenderer": "agCheckboxCellRenderer",
    },
    {
        "field": "Editor",
        "cellRenderer": "agCheckboxCellRenderer",
    },
    {
        "field": "Viewer",
        "cellRenderer": "agCheckboxCellRenderer",
    },
]

app.layout = html.Div(
    [
        dag.AgGrid(
            id="grid-cell-data-types-editors",
            columnDefs=columnDefs,
            rowData=rowData,
            defaultColDef={"flex": 1, "editable": True},
            dashGridOptions={"animateRows": False},
        ),
        html.Div(id="cell-update-output"),
    ],
)


@callback(
    Output("grid-cell-data-types-editors", "rowData"),
    Input("grid-cell-data-types-editors", "cellValueChanged"),
    State("grid-cell-data-types-editors", "rowData"),
)
def update_role_selection(cell_changed, current_rows):
    if not cell_changed:
        return dash.no_update

    print(cell_changed)
    print(current_rows)

    cell_changed = cell_changed[0]  # Assuming there's only one cell changed for now

    # Get the changed cell information
    changed_field = cell_changed["colId"]
    row_index = cell_changed["rowIndex"]
    new_value = cell_changed["value"]

    # Only handle changes to the role columns
    role_columns = ["Owner", "Editor", "Viewer"]
    if changed_field in role_columns and new_value is True:
        print("TOTO")
        # Create a deep copy of the current row data
        updated_data = []
        for row in current_rows:
            updated_data.append(row.copy())

        print(updated_data)

        # Get the row that was changed
        changed_row = updated_data[0]  # Assuming there's only one row for now
        print(f"Changed row: {changed_row}")

        # Set all role columns to False for the changed row
        for role in role_columns:
            print(f"Processing role: {role}")
            changed_row[role] = False
            print(f"After setting {role} to False: {changed_row}")

        # Set the changed column to True
        changed_row[changed_field] = True
        print(f"After setting {changed_field} to True: {changed_row}")

        return updated_data

    return current_rows


if __name__ == "__main__":
    app.run(debug=True, port=8051)
