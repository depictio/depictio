import json
import os

import dash
import dash_bootstrap_components as dbc
import dash_draggable
import plotly.express as px
from dash import dcc, html
from dash.dependencies import Input, Output, State


def load_layout():
    if os.path.isfile("layout.json"):
        with open("layout.json", "r") as f:
            initial_layout = json.load(f)
    else:
        initial_layout = dict()
    return initial_layout


def load_children():
    if os.path.isfile("children.json"):
        with open("children.json", "r") as c:
            children = json.load(c)
    else:
        children = list()
    return children


app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.layout = html.Div(
    [
        # dcc.Interval(id="interval-component", interval=1e9, n_intervals=0),
        html.H1("Add Plots Dynamically"),
        html.Br(),
        dbc.Button("Add Plot", id="add-plot-button", color="primary"),
        dbc.Button(
            "Save Layout and Children",
            id="save-button",
            color="success",
            n_clicks=0,
        ),
        dcc.Store(id="layout-store", storage_type="local"),
        dcc.Store(id="children-store", storage_type="local"),
        html.Br(),
        # html.Div(id="plot-container"),
        dash_draggable.ResponsiveGridLayout(
            # id="drag-1",
            id="plot-container",
            clearSavedLayout=False,
            # layouts=load_layout(),
            children=load_children(),
            # margin={"x": 10, "y": 10},
            # compactType="vertical",
            # preventCollision=True,
            # useCSSTransforms=True,
        ),
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
                dbc.ModalFooter(dbc.Button("Close", id="modal-close-button", color="secondary")),
            ],
            id="modal",
            centered=True,
            size="lg",
        ),
    ],
)


# # Define the callback
# @app.callback(
#     Output("scatter-plot", "figure"), Input("interval-component", "n_intervals")
# )
# def update_figure(interval):
#     # Generate random data
#     x = np.random.rand(100)
#     y = np.random.rand(100)

#     # Create the scatter plot
#     fig = px.scatter(x=x, y=y, title="Life expectancy over the years")
#     return fig


@app.callback(
    [Output("layout-store", "data"), Output("children-store", "data")],
    [Input("save-button", "n_clicks")],
    [
        State("plot-container", "layouts"),
        State("plot-container", "children"),
    ],
    prevent_initial_call=True,
)
def save_layout_and_children(n_clicks, layout, children):
    if n_clicks > 0:
        with open("layout.json", "w") as f:
            f.write(json.dumps(layout))
        with open("children.json", "w") as c:
            c.write(json.dumps(children))
    return layout, children


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
        Input("layout-store", "data"),
        Input("children-store", "data"),
    ],
    [State("plot-container", "children")],
)
def add_plot(
    line_n_clicks,
    bar_n_clicks,
    scatter_n_clicks,
    layout_store,
    children_store,
    existing_children,
):
    if not existing_children:
        existing_children = list()
    #     layout = {
    #         "lg": [
    #             {**default_item_layout, "i": str(uuid.uuid4())},
    #         ]
    #     }
    # else:
    #     layout = None
    ctx = dash.callback_context
    if not ctx.triggered:
        return existing_children
    else:
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    if button_id == "line-plot-option":
        fig = px.line(x=[1, 2, 3], y=[4, 1, 2])
    elif button_id == "bar-plot-option":
        fig = px.bar(x=[1, 2, 3], y=[4, 1, 2])
    elif button_id == "scatter-plot-option":
        fig = px.scatter(x=[1, 2, 3], y=[4, 1, 2])
    else:
        return existing_children
    new_child = dcc.Graph(
        # id={
        #     "type": "dynamic-graph",
        #     # "index": len(existing_children),
        # },
        figure=fig,
        style={"height": "100%", "width": "100%"},
        config={"staticPlot": False, "editable": True},
    )
    existing_children.append(new_child)
    # if layout is None:
    #     layout = dash_draggable.generate_layout(existing_children)

    return existing_children


if __name__ == "__main__":
    app.run_server(debug=True, port=8051)
