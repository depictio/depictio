import dash
import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output, State, MATCH, ALL
import dash_bootstrap_components as dbc
import dash_draggable
import json
import os, sys
import numpy as np
import pandas as pd
import plotly.express as px
import uuid


def create_figure(fig_type):
    if fig_type == "Line plot":
        fig = px.line(
            df,
            x="year",
            y="lifeExp",
            color="continent",
            title="Line plot: Life Expectancy over Years",
        )
    elif fig_type == "Bar plot":
        fig = px.bar(
            df,
            x="year",
            y="pop",
            color="continent",
            title="Bar plot: Population over Years",
        )
    elif fig_type == "Scatter plot":
        fig = px.scatter(
            df,
            x="gdpPercap",
            y="lifeExp",
            color="continent",
            log_x=True,
            title="Scatter plot: Life Expectancy vs GDP per Capita",
        )
    elif fig_type == "Pie chart":
        year = df["year"].max()
        fig = px.pie(
            df[df["year"] == year],
            values="pop",
            names="country",
            title=f"Pie chart: Population by Country in {year}",
        )
    return fig


df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
)


plot_types = [
    {"type": "Line plot", "description": "Line plot of Life Expectancy over Years"},
    {"type": "Bar plot", "description": "Bar plot of Population over Years"},
    {
        "type": "Scatter plot",
        "description": "Scatter plot of Life Expectancy vs GDP per Capita",
    },
    {
        "type": "Pie chart",
        "description": f"Pie chart of Population by Country in {df['year'].max()}",
    },
]


def load_initial_data():
    data_file = "data.json"

    if os.path.exists(data_file):
        with open(data_file, "r") as f:
            data = json.load(f)
            initial_children = data["children"]
            initial_layouts = data["layouts"]
    else:
        initial_children = []
        initial_layouts = {}

    return initial_children, initial_layouts


initial_children, initial_layouts = load_initial_data()
print(initial_children)
print(initial_layouts)


app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    # suppress_callback_exceptions=True,
)
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
        dcc.Store(id="layout-store", storage_type="local", data=initial_layouts),
        dcc.Store(id="children-store", storage_type="local", data=initial_children),
        html.Br(),
        # html.Div(id="plot-container"),
        dash_draggable.ResponsiveGridLayout(
            # style={"--grid-item-width": "200px", "--grid-item-height": "200px"},
            # id="drag-1",
            id="plot-container",
            clearSavedLayout=True,
            # children=load_children(),
            # layouts={},
            # children=[],
            layouts=initial_layouts,
            children=initial_children,
            # margin={"x": 10, "y": 10},
            # compactType="vertical",
            # preventCollision=True,
            # useCSSTransforms=True,
            # autoSize=True,
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
                                                html.Td(plot["type"]),
                                                html.Td(plot["description"]),
                                                dbc.Button(
                                                    "Select",
                                                    id=f"{plot['type'].lower().replace(' ', '-')}-option",
                                                    color="light",
                                                    style={
                                                        "cursor": "pointer",
                                                        "width": "100%",
                                                    },
                                                ),
                                            ],
                                            id=f"{plot['type'].lower().replace(' ', '-')}-row",
                                            style={"width": "100%"},
                                        )
                                        for plot in plot_types
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
        dbc.Modal(
            [
                dbc.ModalHeader("Edit Content"),
                dbc.ModalBody(dcc.Textarea(id="edit-area", style={"width": "100%"})),
                dbc.ModalFooter(
                    [
                        dbc.Button(
                            "Save",
                            id="edit-save-button",
                        ),
                        dbc.Button("Cancel", id="cancel-button", color="secondary"),
                    ]
                ),
            ],
            id="edit-modal",
        ),
    ],
)


@app.callback(
    Output("edit-modal", "is_open"),
    [
        Input({"type": "edit-button", "index": dash.dependencies.ALL}, "n_clicks"),
        Input("edit-save-button", "n_clicks"),
        Input("cancel-button", "n_clicks"),
    ],
    [State("edit-modal", "is_open")],
)
def toggle_modal(edit_button_n_clicks, n2, n3, is_open):
    if any(edit_button_n_clicks) or n2 or n3:
        return not is_open
    return is_open


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
    print(n_clicks)
    if n_clicks > 0:
        data_file = "data.json"
        data = {"children": children, "layouts": layout}

        with open(data_file, "w") as f:
            json.dump(data, f)
    print(len(children))
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
    Output("plot-container", "children"),  # specify the output property of the callback
    [  # specify the input properties of the callback
        *[
            Input(f"{plot['type'].lower().replace(' ', '-')}-option", "n_clicks")
            for plot in plot_types
        ],
        Input({"type": "remove-button", "index": dash.dependencies.ALL}, "n_clicks"),
        Input("layout-store", "data"),
        Input("children-store", "data"),
    ],
    [
        State("plot-container", "layouts"),
        State("plot-container", "children"),
    ],  # specify the state properties of the callback
)
def add_plot(
    *input_args,
):
    plot_option_clicks = input_args[:-5]
    remove_button_n_clicks = input_args[-5]
    layout_store = input_args[-4]
    children_store = input_args[-3]
    existing_layout = input_args[-2]
    existing_children = input_args[-1]

    print(input_args)
    print(
        ["Len : {}".format(len(e)) if type(e) is list or type(e) is dict else e for e in input_args]
    )

    print(type(existing_children), len(existing_children))
    # if there are no existing children, initialize the list to an empty list
    if not existing_children or isinstance(existing_children, dict):
        existing_children = list()

    if children_store:
        existing_children = children_store
    if layout_store:
        existing_layout = layout_store

    # get the context of the callback
    ctx = dash.callback_context

    from pprint import pprint

    # pprint(existing_children)
    # if the callback is not triggered, return the existing children
    if not ctx.triggered:
        return existing_children
    else:
        # get the id of the element that triggered the callback
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # print the id of the element that triggered the callback
    print(button_id)

    selected_plot_type = None
    for plot in plot_types:
        option_id = f"{plot['type'].lower().replace(' ', '-')}-option"
        if button_id == option_id:
            selected_plot_type = plot["type"]
            break

    if selected_plot_type:
        fig = create_figure(selected_plot_type)

    # if the remove button was clicked, return an empty list to remove all the plots

    elif "remove-button" in button_id:
        print(ctx.triggered)
        # extract the UUID from the button_id
        try:
            import ast

            button_id = ast.literal_eval(button_id)
        except:
            pass
        button_uuid = button_id["index"]
        # find the child div with the corresponding id
        for child in existing_children:
            if child["props"]["id"].split("div-")[-1] == button_uuid:
                existing_children.remove(child)
        return existing_children

    # if none of the above, return the existing children
    else:
        return existing_children

    unique_id = str(uuid.uuid4())

    # create a new child div that contains the plot, edit and remove buttons
    new_child = html.Div(
        [
            dbc.Button("Edit", id={"type": "edit-button", "index": unique_id}),
            dbc.Button(
                "Remove",
                id={"type": "remove-button", "index": unique_id},
                color="danger",
            ),
            dcc.Graph(
                figure=fig,  # use the plotly figure created above
                style={"height": "100%", "width": "100%"},
                config={"staticPlot": False, "editable": True},
            ),
        ],
        id=f"div-{unique_id}",
        # style={"width": "300px", "height": "300px"},
    )

    # append the new child to the existing children list
    existing_children.append(new_child)

    # return the updated list of children
    return existing_children


if __name__ == "__main__":
    app.run_server(debug=True, port=8052)
