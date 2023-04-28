data = {
    "BAB3114iTRUE5E81": {
        "raw_total_sequences": 452566,
        "filtered_sequences": 0,
        "sequences": 452566,
        "is_sorted": 1,
        "1st_fragments": 226283,
        "last_fragments": 226283,
        "reads_mapped": 444492,
        "cell_type": "neuron",
        "organism": "mouse",
    },
    "GHT5763uSILV3R19": {
        "raw_total_sequences": 315980,
        "filtered_sequences": 1000,
        "sequences": 314980,
        "is_sorted": 0,
        "1st_fragments": 157490,
        "last_fragments": 157490,
        "reads_mapped": 305872,
        "cell_type": "astrocyte",
        "organism": "rat",
    },
    "JKL9182rGOLD2B57": {
        "raw_total_sequences": 568201,
        "filtered_sequences": 3000,
        "sequences": 565201,
        "is_sorted": 1,
        "1st_fragments": 282600,
        "last_fragments": 282601,
        "reads_mapped": 550897,
        "cell_type": "microglia",
        "organism": "human",
    },
}

import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        dcc.Dropdown(
            id="visualization-type",
            options=[
                {"label": "Scatter Plot", "value": "scatter"},
                {"label": "Bar Chart", "value": "bar"},
                {"label": "Line Chart", "value": "line"},
            ],
            value="scatter",
        ),
        dcc.Dropdown(id="x-axis", options=[...], value="..."),  # Add options for x-axis
        dcc.Dropdown(id="y-axis", options=[...], value="..."),  # Add options for y-axis
        dcc.Dropdown(id="color", options=[...], value=None),  # Add options for color
        dcc.Dropdown(
            id="hover_data", options=[...], value=None  # Add options for hover_data
        ),
        dcc.Dropdown(id="marker", options=[...], value=None),  # Add options for marker
        html.Div(id="graph-container"),
    ]
)


@app.callback(
    Output("graph-container", "children"),
    [
        Input("visualization-type", "value"),
        Input("x-axis", "value"),
        Input("y-axis", "value"),
        Input("color", "value"),
        Input("hover_data", "value"),
        Input("marker", "value"),
    ],
)
def update_graph(visualization_type, x_axis, y_axis, color, hover_data, marker):
    # Process inputs and generate the appropriate graph
    graph = ...
    return graph


if __name__ == "__main__":
    app.run_server(debug=True)
