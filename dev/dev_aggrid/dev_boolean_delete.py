import json
import dash_ag_grid as dag
from dash import Dash, html, dcc, Input, Output, callback
import pandas as pd
import dash_bootstrap_components as dbc



data = {
    "ticker": ["AAPL", "MSFT", "AMZN", "GOOGL"],
    "company": ["Apple", "Microsoft", "Amazon", "Alphabet"],
    "price": [154.99, 268.65, 100.47, 96.75],
    "Delete": ["Delete" for i in range(4)],
}
df = pd.DataFrame(data)

columnDefs = [
    {
        "headerName": "Stock Ticker",
        "field": "ticker",
    },
    {"headerName": "Company", "field": "company", "filter": True},
    {
        "headerName": "Last Close Price",
        "type": "rightAligned",
        "field": "price",
        "valueFormatter": {"function": """d3.format("($,.2f")(params.value)"""},
    },
    {
        "field": "Delete",
        "cellRenderer": "Button",
        "cellRendererParams": {
            "className": "btn btn-danger fw-bold",
            "style": {"fontSize": "14px", "padding": "6px 12px", "margin": "4px", "boxShadow": "0 2px 5px rgba(0,0,0,0.2)"}
        },
    },
]


grid = dag.AgGrid(
    id="custom-component-btn-grid",
    columnDefs=columnDefs,
    rowData=df.to_dict("records"),
    columnSize="autoSize",
    dashGridOptions={"rowHeight": 48},
)


app = Dash(__name__, external_stylesheets=[dbc.themes.SPACELAB])

app.layout = html.Div(
    [
        dcc.Markdown("Example of cellRenderer with custom button component"),
        grid,
        html.Div(id="custom-component-btn-value-changed"),
    ]
)


@callback(
    Output("custom-component-btn-value-changed", "children"),
    Input("custom-component-btn-grid", "cellRendererData"),
)
def showChange(n):
    return json.dumps(n)


if __name__ == "__main__":
    app.run(debug=True, port=8052)
