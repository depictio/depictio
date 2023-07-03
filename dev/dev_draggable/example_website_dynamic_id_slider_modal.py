import dash
from dash.dependencies import Input, Output, State
from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd
import dash_draggable
import dash_table

external_stylesheets = [
    dbc.themes.BOOTSTRAP,
    # "https://codepen.io/chriddyp/pen/bWLwgP.css",
    # {
    #     "href": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css",
    #     "rel": "stylesheet",
    # },
    {
        "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
        "rel": "stylesheet",
    },
]

app = dash.Dash(
    __name__,
    external_stylesheets=external_stylesheets,
    # suppress_callback_exceptions=True,
)

df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
)

AVAILABLE_PLOT_TYPES = {
    "scatter-plot": {
        "type": "Scatter plot",
        "description": "Scatter plot of GDP per Capita vs. Life Expectancy",
        "property": "Property A",
        "material-icons": "scatter_plot",
        "function": px.scatter,
        "kwargs": {
            "x": "gdpPercap",
            "y": "lifeExp",
            "size": "pop",
            "color": "continent",
            "hover_name": "country",
            "log_x": True,
            "size_max": 55,
            "animation_frame": "year",
        },
    },
    "bar-plot": {
        "type": "Bar plot",
        "description": "Bar plot of Total GDP per Year",
        "property": "Property B",
        "material-icons": "bar_chart",
        "function": px.bar,
        "kwargs": {
            "x": "year",
            "y": "gdpPercap",
            "color": "continent",
            "hover_name": "country",
            "facet_col": "continent",
            "facet_col_wrap": 3,
            "height": 700,
        },
    },
    "line-plot": {
        "type": "Line plot",
        "description": "Line plot of GDP per Capita over Time",
        "property": "Property C",
        "material-icons": "show_chart",
        "function": px.line,
        "kwargs": {
            "x": "year",
            "y": "gdpPercap",
            "color": "continent",
            "hover_name": "country",
            "line_group": "country",
            "line_shape": "spline",
            "render_mode": "svg",
        },
    },
    "box-plot": {
        "type": "Box plot",
        "description": "Box plot of Life Expectancy by Continent",
        "property": "Property D",
        "material-icons": "analytics",
        "function": px.box,
        "kwargs": {
            "x": "continent",
            "y": "lifeExp",
            "color": "continent",
            "hover_name": "country",
            "points": "all",
            "notched": True,
        },
    },
    "pie-chart": {
        "type": "Pie chart",
        "description": "Pie chart of Population by Continent",
        "property": "Property E",
        "material-icons": "pie_chart",
        "function": px.pie,
        "kwargs": {
            "names": "continent",
            "values": "pop",
            "hover_name": "continent",
            "hole": 0.4,
            # "animation_frame": "year",
            "title": "Population by Continent",
        },
    },
}

AVAILABLE_PLOT_TYPES = dict(sorted(AVAILABLE_PLOT_TYPES.items()))


def create_initial_figure(selected_year, plot_type):
    filtered_df = df[df.year == selected_year]

    fig = AVAILABLE_PLOT_TYPES[plot_type]["function"](
        filtered_df, **AVAILABLE_PLOT_TYPES[plot_type]["kwargs"]
    )

    fig.update_layout(transition_duration=500)

    return fig


app.layout = html.Div(
    [
        html.H1("Dash Draggable"),
        html.B("Description:"),
        html.Ul(
            [
                html.Li("The charts are draggable and resizeable."),
                html.Li("Click the 'Add Plot' button to add a new plot."),
            ]
        ),
        # dash_draggable.ResponsiveGridLayout(
        #     children=[
        #     ]
        # ),
        dbc.Button("Add Plot", id="add-plot-button", color="primary"),
        dcc.Slider(
            id="year-slider",
            min=df["year"].min(),
            max=df["year"].max(),
            value=df["year"].min(),
            marks={str(year): str(year) for year in df["year"].unique()},
            step=None,
        ),
        # html.Div(
        #     [
        #         # Add a button for each available plot type
        #         html.Button(
        #             f"Add {plot_type}",
        #             id=f"add-plot-button-{plot_type.lower().replace(' ', '-')}",
        #             n_clicks=0,
        #         )
        #         for plot_type in AVAILABLE_PLOT_TYPES.keys()
        #     ],
        #     style={"display": "inline-block"},
        # ),
        dcc.Store(id="stored-year", storage_type="session"),
        dcc.Interval(
            id="save-slider-value-interval",
            interval=2000,  # Save slider value every 1 second
            n_intervals=0,
        ),
        dcc.Store(id="stored-children", storage_type="session"),
        dcc.Store(id="stored-layout", storage_type="session"),
        dash_draggable.ResponsiveGridLayout(
            id="draggable",
            clearSavedLayout=True,
            layouts=dict(),
            children=[
                # Remove the initial graph and slider, as they won't be needed
            ],
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
                                                html.Th(html.H5("")),
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
                                                html.Td(
                                                    html.I(
                                                        className="material-icons",
                                                        children=AVAILABLE_PLOT_TYPES[
                                                            plot_type
                                                        ]["material-icons"],
                                                    )
                                                ),
                                                html.Td(
                                                    AVAILABLE_PLOT_TYPES[plot_type][
                                                        "type"
                                                    ]
                                                ),
                                                html.Td(
                                                    AVAILABLE_PLOT_TYPES[plot_type][
                                                        "description"
                                                    ]
                                                ),
                                                html.Td(
                                                    AVAILABLE_PLOT_TYPES[plot_type][
                                                        "property"
                                                    ]
                                                ),
                                                html.Td(
                                                    dbc.Button(
                                                        "Select",
                                                        id=f"add-plot-button-{plot_type.lower().replace(' ', '-')}",
                                                        color="light",
                                                        n_clicks=0,
                                                        style={
                                                            "cursor": "pointer",
                                                            # "width": "100%",
                                                        },
                                                    ),
                                                    style={"text-align": "center"},
                                                ),
                                            ],
                                            id=f"{AVAILABLE_PLOT_TYPES[plot_type]['type'].lower().replace(' ', '-')}-row",
                                            style={"width": "100%"},
                                        )
                                        for plot_type in AVAILABLE_PLOT_TYPES
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
    ]
)


@app.callback(
    Output("stored-year", "data"),
    Input("save-slider-value-interval", "n_intervals"),
    State("year-slider", "value"),
)
def save_slider_value(n_intervals, value):
    if n_intervals == 0:
        raise dash.exceptions.PreventUpdate
    return value


@app.callback(
    Output("year-slider", "value"),
    Input("stored-year", "data"),
)
def update_slider_value(data):
    if data is None:
        raise dash.exceptions.PreventUpdate
    return data


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


@app.callback(
    [
        Output("draggable", "children"),
        Output("draggable", "layouts"),
        Output("stored-layout", "data"),
        Output("stored-children", "data"),
    ],
    [
        Input(f"add-plot-button-{plot_type.lower().replace(' ', '-')}", "n_clicks")
        for plot_type in AVAILABLE_PLOT_TYPES.keys()
    ]
    + [
        Input("stored-layout", "data"),
        Input("stored-children", "data"),
        Input("draggable", "layouts"),
        Input({"type": "remove-button", "index": dash.dependencies.ALL}, "n_clicks"),
        Input("year-slider", "value"),
    ],
    [
        State("draggable", "children"),
        State("draggable", "layouts"),
        State("stored-layout", "data"),
        State("stored-children", "data"),
    ],
)
def update_draggable_children(
    # n_clicks, selected_year, current_draggable_children, current_layouts, stored_figures
    *args,
):
    ctx = dash.callback_context
    triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
    print(triggered_input)
    print(ctx.triggered)
    stored_layout_data = args[-9]
    stored_children_data = args[-8]
    new_layouts = args[-7]
    # remove-button -6
    selected_year = args[-5]
    current_draggable_children = args[-4]
    current_layouts = args[-3]
    stored_layout = args[-2]
    stored_figures = args[-1]

    # if current_draggable_children is None:
    #     current_draggable_children = []
    # if current_layouts is None:
    #     current_layouts = dict()

    if triggered_input.startswith("add-plot-button-"):
        plot_type = triggered_input.replace("add-plot-button-", "")

        n_clicks = ctx.triggered[0]["value"]

        new_plot_id = f"graph-{n_clicks}-{plot_type.lower().replace(' ', '-')}"
        new_plot_type = plot_type

        new_plot = dcc.Graph(
            id=new_plot_id,
            figure=create_initial_figure(selected_year, new_plot_type),
            responsive=True,
            style={
                "width": "100%",
                "height": "100%",
            },
        )
        # print(new_plot)

        new_draggable_child = html.Div(
            [
                dbc.Button(
                    "Remove",
                    id={"type": "remove-button", "index": new_plot_id},
                    color="danger",
                ),
                new_plot,
            ],
            id=f"draggable-{new_plot_id}",
        )
        # print(current_draggable_children)
        # print(len(current_draggable_children))

        updated_draggable_children = current_draggable_children + [new_draggable_child]

        # Define the default size and position for the new plot
        new_layout_item = {
            "i": f"draggable-{new_plot_id}",
            "x": 10 * ((len(updated_draggable_children) + 1) % 2),
            "y": n_clicks * 10,
            "w": 6,
            "h": 14,
        }

        # Update the layouts property for both 'lg' and 'sm' sizes
        updated_layouts = {}
        for size in ["lg", "sm"]:
            if size not in current_layouts:
                current_layouts[size] = []
            updated_layouts[size] = current_layouts[size] + [new_layout_item]

        # Store the newly created figure in stored_figures
        # stored_figures[new_plot_id] = new_plot

        return (
            updated_draggable_children,
            updated_layouts,
            # selected_year,
            updated_layouts,
            updated_draggable_children,
            # selected_year,
        )

    elif triggered_input == "year-slider":
        updated_draggable_children = []

        for child in current_draggable_children:
            # try:
            graph = child["props"]["children"][1]
            # Extract the figure type and its corresponding function
            figure_type = "-".join(graph["props"]["id"].split("-")[2:])
            graph_id = graph["props"]["id"]
            updated_fig = create_initial_figure(selected_year, figure_type)
            # stored_figures[graph_id] = updated_fig
            graph["props"]["figure"] = updated_fig
            updated_child = html.Div(
                [
                    dbc.Button(
                        "Remove",
                        id={"type": "remove-button", "index": child["props"]["id"]},
                        color="danger",
                    ),
                    graph,
                ],
                id=child["props"]["id"],
            )

            updated_draggable_children.append(updated_child)
            # except:
            #     # If any exception occurs, just append the current child without modifications
            #     updated_draggable_children.append(child)

        # return updated_draggable_children, current_layouts, stored_figures

        return (
            updated_draggable_children,
            current_layouts,
            # selected_year,
            current_layouts,
            updated_draggable_children,
            # selected_year,
        )

    # if the remove button was clicked, return an empty list to remove all the plots

    elif "remove-button" in triggered_input:
        # print(triggered_input)
        # extract the UUID from the button_id
        # try:
        import ast

        button_id = ast.literal_eval(triggered_input)
        # except:
        #     pass
        # print(button_id, type(button_id))
        button_uuid = button_id["index"]
        print("\n")
        print(button_uuid)

        # find the child div with the corresponding id
        for child in current_draggable_children:
            print(child)
            print("\n")
            if child["props"]["id"] == button_uuid:
                current_draggable_children.remove(child)
        return (
            current_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            current_draggable_children,
            # selected_year,
        )
    elif (
        triggered_input == "stored-layout"
        or triggered_input == "stored-children"
        # or triggered_input == "stored-year"
    ):
        if stored_layout_data and stored_children_data:
            return (
                stored_children_data,
                stored_layout_data,
                # selected_year,
                stored_layout_data,
                stored_children_data,
                # selected_year,
            )
        else:
            return (
                current_draggable_children,
                {},
                # selected_year,
                stored_layout,
                stored_figures,
                # selected_year,
            )

    elif triggered_input == "draggable":
        return (
            current_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            current_draggable_children,
            # selected_year,
        )

    # Add an else condition to return the current layout when there's no triggering input
    else:
        raise dash.exceptions.PreventUpdate

    # Remove the initial call prevention from the clientside_callback
    app.clientside_callback(
        "dash_draggable.update_layout",
        Output("draggable", "layouts"),
        [
            Input(f"add-plot-button-{plot_type.lower().replace(' ', '-')}", "n_clicks")
            for plot_type in AVAILABLE_PLOT_TYPES.keys()
        ],
    )


if __name__ == "__main__":
    app.run_server(debug=True, port="8052")
