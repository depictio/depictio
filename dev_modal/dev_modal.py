import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# define a modal with clickable options
modal = dbc.Modal(
    [
        dbc.ModalHeader("Add a plot"),
        dbc.ModalBody(
            [
                html.H4("Select a plot type:"),
                dbc.ListGroup(
                    [
                        dbc.ListGroupItem(
                            "Line Plot",
                            id="line-plot-option",
                            action=True,
                            color="light",
                            style={"cursor": "pointer"},
                        ),
                        dbc.ListGroupItem(
                            "Bar Plot",
                            id="bar-plot-option",
                            action=True,
                            color="light",
                            style={"cursor": "pointer"},
                        ),
                        dbc.ListGroupItem(
                            "Scatter Plot",
                            id="scatter-plot-option",
                            action=True,
                            color="light",
                            style={"cursor": "pointer"},
                        ),
                    ],
                    flush=True,
                ),
            ]
        ),
        dbc.ModalFooter(
            dbc.Button("Close", id="modal-close-button", className="ml-auto")
        ),
    ],
    id="modal",
)

# define the layout
app.layout = html.Div(
    [
        dbc.Button("Add a plot", id="add-plot-button", color="primary"),
        html.Br(),
        html.Br(),
        html.Div(id="plot-container"),
        modal,
    ]
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


# define the callbacks to add plots based on clicked options
@app.callback(
    Output("plot-container", "children"),
    [
        Input("line-plot-option", "n_clicks"),
        Input("bar-plot-option", "n_clicks"),
        Input("scatter-plot-option", "n_clicks"),
    ],
    [State("plot-container", "children")],
)
def add_plot(line_n_clicks, bar_n_clicks, scatter_n_clicks, existing_children):
    if not existing_children:
        existing_children = list()
    ctx = dash.callback_context
    if not ctx.triggered:
        return existing_children
    else:
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    if button_id == "line-plot-option":
        return existing_children + [
            dcc.Graph(
                figure={"data": [{"x": [1, 2, 3], "y": [4, 1, 2], "type": "line"}]}
            )
        ]
    elif button_id == "bar-plot-option":
        return existing_children + [
            dcc.Graph(
                figure={"data": [{"x": [1, 2, 3], "y": [4, 1, 2], "type": "bar"}]}
            )
        ]
    elif button_id == "scatter-plot-option":
        return existing_children + [
            dcc.Graph(
                figure={
                    "data": [
                        {
                            "x": [1, 2, 3],
                            "y": [4, 1, 2],
                            "type": "scatter",
                            "mode": "markers",
                        }
                    ]
                }
            )
        ]
    else:
        return existing_children


if __name__ == "__main__":
    app.run_server(debug=True)
