import dash_ag_grid as dag
from dash import Dash, dcc, html

app = Dash(__name__)


columnDefs = [
    {
        "field": "country",
        "editable": False,
    },
    {
        "headerName": "Select Editor",
        "field": "city",
        "cellEditor": "agSelectCellEditor",
        "cellEditorParams": {"function": "dynamicOptions(params)"},
    },
]

rowData = [
    {"country": "United States", "city": "Boston"},
    {"country": "Canada", "city": "Montreal"},
    {"country": "Canada", "city": "Vancouver"},
]


app.layout = html.Div(
    [
        dcc.Markdown(
            "This grid has dynamic options for city based on the country.  Try editing the cities."
        ),
        dag.AgGrid(
            id="cell-editor-grid-2",
            columnDefs=columnDefs,
            rowData=rowData,
            columnSize="sizeToFit",
            defaultColDef={"editable": True},
        ),
    ],
    style={"margin": 20},
)


if __name__ == "__main__":
    app.run(debug=False)
