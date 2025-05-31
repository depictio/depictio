import dash_mantine_components as dmc
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
    {"field": "id", "editable": False},
    {"field": "email", "editable": True},
    {
        "field": "Owner",
        "cellRenderer": "agCheckboxCellRenderer",
        "headerName": '<span style="color: #228BE6; font-weight: bold;">Owner</span>',
        "suppressHtmlEscaping": True,
    },
    {
        "field": "Editor",
        "cellRenderer": "agCheckboxCellRenderer",
        "headerName": '<span style="color: #20c997; font-weight: bold;">Editor</span>',
        "suppressHtmlEscaping": True,
    },
    {
        "field": "Viewer",
        "cellRenderer": "agCheckboxCellRenderer",
        "headerName": '<span style="color: #868e96; font-weight: bold;">Viewer</span>',
        "suppressHtmlEscaping": True,
    },
]

app.layout = html.Div(
    [
        # dmc.Badge(
        #     "Orange red",
        #     variant="gradient",
        #     gradient={"from": "orange", "to": "red"},
        # ),
        # dag.AgGrid(
        #     id="grid-cell-data-types-editors",
        #     columnDefs=columnDefs,
        #     rowData=rowData,
        #     defaultColDef={"flex": 1, "editable": True},
        #     dashGridOptions={"animateRows": False},
        # ),
        # html.Div(id="cell-update-output"),
        # dmc.Group(
        #     children=[
        #         dmc.Badge(
        #             "Indigo cyan",
        #             variant="gradient",
        #             gradient={"from": "indigo", "to": "cyan"},
        #         ),
        #         dmc.Badge(
        #             "Lime green",
        #             variant="gradient",
        #             gradient={"from": "teal", "to": "lime", "deg": 105},
        #         ),
        #         dmc.Badge(
        #             "Teal blue",
        #             variant="gradient",
        #             gradient={"from": "teal", "to": "blue", "deg": 60},
        #         ),
        #         dmc.Badge(
        #             "Orange red",
        #             variant="gradient",
        #             gradient={"from": "orange", "to": "red"},
        #         ),
        #         dmc.Badge(
        #             "Grape pink",
        #             variant="gradient",
        #             gradient={"from": "grape", "to": "pink", "deg": 35},
        #         ),
        #     ]
        # ),
        dmc.Badge(
            "You picked a Depictio template for the workflow X",
            radius="xl",
            size="xl",
            className="animated-badge",
        ),
    ]
)


# @callback(
#     Output("grid-cell-data-types-editors", "rowData"),
#     Input("grid-cell-data-types-editors", "cellValueChanged"),
#     State("grid-cell-data-types-editors", "rowData"),
# )
# def update_role_selection(cell_changed, current_rows):
#     if not cell_changed:
#         return dash.no_update

#     cell_changed = cell_changed[0]
#     changed_field = cell_changed["colId"]
#     row_index = cell_changed["rowIndex"]
#     new_value = cell_changed["value"]

#     role_columns = ["Owner", "Editor", "Viewer"]
#     if changed_field in role_columns and new_value is True:
#         updated_data = [row.copy() for row in current_rows]
#         changed_row = updated_data[row_index]

#         for role in role_columns:
#             changed_row[role] = False
#         changed_row[changed_field] = True

#         return updated_data

#     return current_rows


if __name__ == "__main__":
    app.run(debug=True, port=8051)
