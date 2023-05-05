from dash import dcc, html
from dash.dependencies import Input, Output, State
import ast
import dash
import dash_bootstrap_components as dbc
import json
import os, json
import pandas as pd
import plotly.express as px
import time

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

json_data = {
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
    "QWE1234rBLUE9X01": {
        "raw_total_sequences": 375000,
        "filtered_sequences": 2500,
        "sequences": 372500,
        "is_sorted": 0,
        "1st_fragments": 186250,
        "last_fragments": 186250,
        "reads_mapped": 365000,
        "cell_type": "endothelial",
        "organism": "zebrafish",
    },
    "ASD5678eGREEN2M03": {
        "raw_total_sequences": 480000,
        "filtered_sequences": 8000,
        "sequences": 472000,
        "is_sorted": 1,
        "1st_fragments": 236000,
        "last_fragments": 236000,
        "reads_mapped": 455000,
        "cell_type": "oligodendrocyte",
        "organism": "chicken",
    },
    "ZXC9012tORANGE4H05": {
        "raw_total_sequences": 520000,
        "filtered_sequences": 20000,
        "sequences": 500000,
        "is_sorted": 0,
        "1st_fragments": 250000,
        "last_fragments": 250000,
        "reads_mapped": 485000,
        "cell_type": "fibroblast",
        "organism": "cow",
    },
    "TYU1357yYELLOW5L07": {
        "raw_total_sequences": 410000,
        "filtered_sequences": 10000,
        "sequences": 400000,
        "is_sorted": 1,
        "1st_fragments": 200000,
        "last_fragments": 200000,
        "reads_mapped": 390000,
        "cell_type": "keratinocyte",
        "organism": "dog",
    },
    "GHJ2468uRED6N09": {
        "raw_total_sequences": 600000,
        "filtered_sequences": 30000,
        "sequences": 570000,
        "is_sorted": 0,
        "1st_fragments": 285000,
        "last_fragments": 285000,
        "reads_mapped": 540000,
        "cell_type": "hepatocyte",
        "organism": "frog",
    },
    "BNM3579iINDIGO7Y11": {
        "raw_total_sequences": 330000,
        "filtered_sequences": 1500,
        "sequences": 328500,
        "is_sorted": 1,
        "1st_fragments": 164250,
        "last_fragments": 164250,
        "reads_mapped": 320000,
        "cell_type": "cardiomyocyte",
        "organism": "monkey",
    },
    "POI4680oVIOLET8U13": {
        "raw_total_sequences": 450000,
        "filtered_sequences": 5000,
        "sequences": 445000,
        "is_sorted": 0,
        "1st_fragments": 222500,
        "last_fragments": 222500,
        "reads_mapped": 430000,
        "cell_type": "lymphocyte",
        "organism": "horse",
    },
}

df = pd.read_csv(
    # "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
    "https://raw.githubusercontent.com/plotly/datasets/master/titanic.csv"
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
            # "animation_frame": "year",
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
        "material-icons": "candlestick_chart",
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
            # "title": "Population by Continent",
        },
    },
}

import inspect

plotly_vizu_list = [px.scatter, px.line, px.bar, px.histogram, px.box]

plotly_vizu_dict = {}
for vizu_func in plotly_vizu_list:
    plotly_vizu_dict[vizu_func.__name__] = vizu_func


common_params = set.intersection(
    *[set(inspect.signature(func).parameters.keys()) for func in plotly_vizu_list]
)
common_param_names = [p for p in list(common_params)]
common_param_names.sort(
    key=lambda x: list(inspect.signature(plotly_vizu_list[0]).parameters).index(x)
)

specific_params = {}

for vizu_func in plotly_vizu_list:
    func_params = inspect.signature(vizu_func).parameters
    param_names = list(func_params.keys())

    common_params_tmp = (
        common_params.intersection(func_params.keys())
        if common_params
        else set(func_params.keys())
    )

    specific_params[vizu_func] = [p for p in param_names if p not in common_params_tmp]

print("Common parameters:", common_param_names)
for vizu_func, params in specific_params.items():
    print(f"Specific parameters for {vizu_func.__name__}: {params}")


# Create a DataFrame from the JSON data for plotting
# df = pd.DataFrame.from_dict(json_data, orient="index")
# print(df)

# Generate dropdown options based on DataFrame columns
dropdown_options = [{"label": col, "value": col} for col in df.columns]


dropdown_elements = [
    "x-axis",
    "y-axis",
    "color",
]


import inspect

# Define the available visualizations
plotly_vizu_list = [px.scatter, px.line, px.bar, px.histogram, px.box]

common_params = set.intersection(
    *[set(inspect.signature(func).parameters.keys()) for func in plotly_vizu_list]
)
common_param_names = [p for p in list(common_params)]
common_param_names.sort(
    key=lambda x: list(inspect.signature(plotly_vizu_list[0]).parameters).index(x)
)

specific_params = {}

for vizu_func in plotly_vizu_list:
    func_params = inspect.signature(vizu_func).parameters
    param_names = list(func_params.keys())

    common_params_tmp = (
        common_params.intersection(func_params.keys())
        if common_params
        else set(func_params.keys())
    )

    specific_params[vizu_func.__name__] = [
        p for p in param_names if p not in common_params_tmp
    ]

print(specific_params)


def load_data():
    if os.path.exists("data_prepare.json"):
        with open("data_prepare.json", "r") as file:
            data = json.load(file)
        return data
    return None


# data = load_data()

init_children = list()


app.layout = dbc.Container(
    [
        dcc.Interval(
            id="interval",
            interval=2000,  # Save slider value every 1 second
            n_intervals=0,
        ),
        html.H1(
            "Prepare your visualization",
            className="text-center mb-4",
        ),
        html.Hr(),
        dbc.Row(
            [
                dbc.Col(html.H2("Visualization type"), width=2),
                dbc.Col(
                    dcc.Dropdown(
                        id="visualization-type",
                        options=[
                            {"label": func.__name__, "value": func.__name__}
                            for func in plotly_vizu_list
                        ],
                        value=plotly_vizu_list[0].__name__,
                    ),
                    width=4,
                ),
                html.Hr(),
                dbc.Row(
                    [
                        dbc.Col(html.H3("X-axis"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="x-axis",
                                options=dropdown_options,
                                value=list(df.columns)[0],
                            ),
                            width=2,
                        ),
                        dbc.Col(html.H3("Y-axis"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="y-axis",
                                options=dropdown_options,
                                value=list(df.columns)[1],
                            ),
                            width=2,
                        ),
                        dbc.Col(html.H3("color"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="color",
                                options=dropdown_options,
                                # value=list(df.columns)[2],
                                value=list(df.columns)[2],
                            ),
                            width=2,
                        ),
                    ],
                    justify="center",
                ),
                html.Hr(),
                dbc.Col(
                    [
                        dbc.Button(
                            "Edit",
                            id="edit-button",
                            color="primary",
                            size="lg",
                            style={"font-size": "22px"},
                        ),
                        dbc.Modal(
                            [
                                dbc.ModalHeader(
                                    html.H1(
                                        "Success!",
                                        className="text-success",
                                    )
                                ),
                                dbc.ModalBody(
                                    html.H5(
                                        "Your amazing dashboard was successfully saved!",
                                        className="text-success",
                                    ),
                                    style={"background-color": "#F0FFF0"},
                                ),
                                dbc.ModalFooter(
                                    dbc.Button(
                                        "Close",
                                        id="modal-close-button",
                                        className="ml-auto",
                                        color="success",
                                    )
                                ),
                            ],
                            id="success-modal",
                            centered=True,
                        ),
                        dbc.Button(
                            "Save",
                            id="save-button",
                            color="success",
                            style={"margin-left": "10px", "font-size": "22px"},
                            size="lg",
                            n_clicks=0,
                        ),
                    ],
                    className="d-flex justify-content-center align-items-center",
                ),
                html.Hr(),
                dbc.Row(
                    [
                        dbc.Col(
                            dcc.Graph(id="graph-container", config={"editable": True}),
                        ),
                    ],
                    className="mt-3",
                ),
            ],
            className="text-center mt-3",
            justify="center",
        ),
        html.Hr(),
        dbc.Row(
            [
                dbc.Offcanvas(
                    [
                        html.Div(id="specific-params-container"),
                    ],
                    id="modal",
                    title="Edit Menu",
                    scrollable=True,
                    # size="xl",
                    backdrop=False,
                ),
            ],
            justify="center",
        ),
        html.Hr(),
    ],
    fluid=True,
)


# define the callback to show/hide the modal
@app.callback(
    Output("modal", "is_open"),
    [Input("edit-button", "n_clicks"), Input("modal-close-button", "n_clicks")],
    [State("modal", "is_open")],
)
def toggle_modal(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    return is_open


def generate_callback(element_id):
    @app.callback(
        Output(f"stored-{element_id}", "data"),
        Input("interval", "n_intervals"),
        State(element_id, "value"),
    )
    def save_value(n_intervals, value):
        if n_intervals == 0:
            raise dash.exceptions.PreventUpdate
        return value

    @app.callback(
        Output(element_id, "value"),
        Input(f"stored-{element_id}", "data"),
    )
    def update_value(data):
        if data is None:
            raise dash.exceptions.PreventUpdate
        return data

    return save_value, update_value


for element_id in dropdown_elements:
    # print(element_id)
    # Create dcc.Store for each dropdown element
    app.layout.children.insert(
        0, dcc.Store(id=f"stored-{element_id}", storage_type="session", data="")
    )

    # Register the save and update callbacks for each element
    save_value_callback, update_value_callback = generate_callback(element_id)
    # print(save_value_callback)
    # print(update_value_callback)
app.layout.children.insert(
    0,
    dcc.Store(id=f"stored-visualization-type", storage_type="session", data="scatter"),
)
save_value_callback, update_value_callback = generate_callback("visualization-type")

# app.layout.children.insert(
#     0,
#     dcc.Store(id=f"stored-accordion", storage_type="session"),
# )
# save_value_callback, update_value_callback = generate_callback("accordion")


# Define the callback to update the specific parameters dropdowns
@app.callback(
    Output("specific-params-container", "children"),
    Input("visualization-type", "value"),
)
def update_specific_params(value):
    if value is not None:
        specific_params_options = [
            {"label": param_name, "value": param_name}
            for param_name in specific_params[value]
        ]
        specific_params_dropdowns = [
            dbc.AccordionItem(
                [
                    dbc.Row(
                        [
                            dcc.Dropdown(
                                id=f"{value}-{param_name}",
                                options=list(df.columns),
                                value=None,
                            ),
                        ]
                    ),
                ],
                className="my-2",
                title=param_name,
            )
            for param_name in specific_params[value]
        ]
        return [html.H5(f"{value.capitalize()} specific parameters")] + [
            dbc.Accordion(
                specific_params_dropdowns,
                flush=True,
                always_open=True,
                persistence_type="session",
                id="accordion",
            ),
            # dcc.Store(id="accordion-state"),
        ]
    else:
        return html.Div()


@app.callback(
    Output("save-button", "n_clicks"),
    Input("save-button", "n_clicks"),
    [State(f"stored-{element}", "data") for element in dropdown_elements]
    + [State(element, "value") for element in dropdown_elements],
)
def save_data(
    n_clicks,
    *element_data,
):
    if n_clicks > 0:
        print("\n")

        # print(element_data)
        # Store values of dropdown elements in a dictionary
        element_values = {}
        for i, element_id in enumerate(dropdown_elements):
            print(i, element_id)
            stored_data = element_data[i + 1]
            print(stored_data)
            # value = element_data[i + len(dropdown_elements)]
            element_values[element_id] = {
                "stored_data": stored_data,
                # "value": value,
            }

        print(element_values)

        with open("data_prepare.json", "w") as file:
            json.dump(element_values, file)

        return n_clicks

    return n_clicks


@app.callback(
    Output("graph-container", "figure"),
    [
        Input("visualization-type", "value"),
        Input("x-axis", "value"),
        Input("y-axis", "value"),
        Input("color", "value"),
    ],
)
def update_graph(visualization_type, x_axis, y_axis, color):
    print(visualization_type)
    # Process inputs and generate the appropriate graph
    plot_func = plotly_vizu_dict[visualization_type]
    plot_kwargs = {}

    plot_kwargs["x"] = x_axis
    plot_kwargs["y"] = y_axis
    if color:
        plot_kwargs["color"] = color

    figure = plot_func(data_frame=df, **plot_kwargs)
    return figure


if __name__ == "__main__":
    app.run_server(debug=True)
