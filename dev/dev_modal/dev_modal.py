import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.layout = html.Div(
    [
        html.H1("Add Plots Dynamically"),
        html.Br(),
        dbc.Button("Add Plot", id="add-plot-button", color="primary"),
        html.Br(),
        html.Div(id="plot-container"),
        dbc.Modal(
            [
                dbc.ModalHeader(html.H3("Select a plot type")),
                dbc.ModalBody(
                    [
                        dbc.Table(
                            [
                                html.Thead(
                                    [
                                        html.Tr(
                                            [
                                                html.Th(html.H5("Plot Type")),
                                                html.Th(html.H5("Description")),
                                                html.Th(
                                                    html.H5(
                                                        "Property",
                                                        style={"text-align": "left"},
                                                    ),
                                                ),
                                                html.Th(),
                                            ]
                                        )
                                    ]
                                ),
                                html.Tbody(
                                    [
                                        html.Tr(
                                            [
                                                html.Td("Line plot"),
                                                html.Td("This is a line plot"),
                                                html.Td("Line plot property A"),
                                                dbc.Button(
                                                    "Select",
                                                    id="line-plot-option",
                                                    color="light",
                                                    style={
                                                        "cursor": "pointer",
                                                        "width": "100%",
                                                    },
                                                ),
                                            ],
                                            id="line-plot-row",
                                            style={"width": "100%"},
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Scatter plot"),
                                                html.Td("This is a scatter plot"),
                                                html.Td("Scatter plot property B"),
                                                dbc.Button(
                                                    "Select",
                                                    id="scatter-plot-option",
                                                    color="light",
                                                    style={
                                                        "cursor": "pointer",
                                                        "width": "100%",
                                                    },
                                                ),
                                            ],
                                            id="scatter-plot-row",
                                            style={"width": "100%"},
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Bar plot"),
                                                html.Td("This is a bar plot"),
                                                html.Td("Bar plot property C"),
                                                dbc.Button(
                                                    "Select",
                                                    id="bar-plot-option",
                                                    color="light",
                                                    style={
                                                        "cursor": "pointer",
                                                        "width": "100%",
                                                    },
                                                ),
                                            ],
                                            id="bar-plot-row",
                                            style={"width": "100%"},
                                        ),
                                    ]
                                ),
                            ],
                            bordered=True,
                            hover=True,
                            responsive=True,
                            striped=True,
                            size="sm",
                            style={"width": "100%"},
                        ),
                    ]
                ),
                dbc.ModalFooter(
                    dbc.Button("Close", id="modal-close-button", color="secondary")
                ),
            ],
            id="modal",
            centered=True,
            size="lg",
        ),
    ],
)


# define the callback to show/hide the modal
@app.callback(
    Output("modal", "is_open"),
    [Input("add-plot-button", "n_clicks"), Input("modal-close-button", "n_clicks")],
    [State("modal", "is_open")],
)
def toggle_modal(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    return is_open


# @app.callback(
#     Output("plot-container", "children"),
#     [
#         Input("line-plot-option", "n_clicks"),
#         Input("bar-plot-option", "n_clicks"),
#         Input("scatter-plot-option", "n_clicks"),
#     ],
#     [State("plot-container", "children")],
# )


def create_new_plot(button_id, index):
    new_plot = dbc.Card(
        [
            dbc.CardHeader(
                html.Button(
                    "×",
                    className="close",
                    id={"type": "plot-close-button", "index": index},
                ),
            ),
            dbc.CardBody(
                dcc.Graph(
                    id={"type": "plot", "index": index},
                    figure={"data": [{"x": [1, 2, 3], "y": [4, 1, 2]}]},
                )
            ),
        ],
        style={"width": "100%", "margin-bottom": "10px"},
    )

    if button_id == "line-plot-option":
        new_plot.children[1].children.figure["data"][0]["type"] = "line"
    elif button_id == "bar-plot-option":
        new_plot.children[1].children.figure["data"][0]["type"] = "bar"
    elif button_id == "scatter-plot-option":
        new_plot.children[1].children.figure["data"][0]["type"] = "scatter"
        new_plot.children[1].children.figure["data"][0]["mode"] = "markers"

    return new_plot


@app.callback(
    Output("plot-container", "children"),
    [
        Input("line-plot-option", "n_clicks"),
        Input("bar-plot-option", "n_clicks"),
        Input("scatter-plot-option", "n_clicks"),
        Input(
            {"type": "plot-close-button", "index": dash.dependencies.ALL}, "n_clicks"
        ),
    ],
    [State("plot-container", "children")],
    prevent_initial_call=True,
)
def update_plots(
    line_n_clicks, bar_n_clicks, scatter_n_clicks, close_clicks, existing_children
):
    if not existing_children:
        existing_children = list()
    ctx = dash.callback_context
    if not ctx.triggered:
        return existing_children

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id in ["line-plot-option", "bar-plot-option", "scatter-plot-option"]:
        new_plot = create_new_plot(button_id, len(existing_children))
        return existing_children + [new_plot]

    elif "plot-close-button" in button_id:
        index_to_remove = int(button_id.split("}")[-2].split(":")[-1].strip())
        existing_children.pop(index_to_remove)
        return existing_children

    else:
        return existing_children


if __name__ == "__main__":
    app.run_server(debug=True)
