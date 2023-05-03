import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.express as px
import pandas as pd
import dash_bootstrap_components as dbc


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

# Create a DataFrame from the JSON data for plotting
# df = pd.DataFrame.from_dict(json_data, orient="index")
# print(df)

# Generate dropdown options based on DataFrame columns
dropdown_options = [{"label": col, "value": col} for col in df.columns]

app.layout = dbc.Container(
    [
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
                            {"label": v["type"], "value": k}
                            for k, v in AVAILABLE_PLOT_TYPES.items()
                        ],
                        value="scatter-plot",
                    ),
                    width=4,
                ),
            ],
            # className="mt-3",
            justify="center",
        ),
        html.Hr(),
        dbc.Row(
            [
                dbc.Col(html.H3("X-axis"), width=1),
                dbc.Col(
                    dcc.Dropdown(
                        id="x-axis",
                        options=dropdown_options,
                        value="gdpPercap",
                    ),
                    width=2,
                ),
                dbc.Col(html.H3("Y-axis"), width=1),
                dbc.Col(
                    dcc.Dropdown(
                        id="y-axis",
                        options=dropdown_options,
                        value="lifeExp",
                    ),
                    width=2,
                ),
                dbc.Col(html.H3("Color"), width=1),
                dbc.Col(
                    dcc.Dropdown(
                        id="color",
                        options=dropdown_options,
                        value=None,
                    ),
                    width=2,
                ),
            ],
            className="text-center mt-3",
            justify="center",
        ),
        dbc.Row(
            [
                dbc.Col(html.H3("Hover data"), width=1),
                dbc.Col(
                    dcc.Dropdown(
                        id="hover_name",
                        options=dropdown_options,
                        value=None,
                    ),
                    width=2,
                ),
                dbc.Col(html.H3("Symbol"), width=1),
                dbc.Col(
                    dcc.Dropdown(
                        id="symbol",
                        options=dropdown_options,
                        value=None,
                    ),
                    width=2,
                ),
                dbc.Col(html.H3("Size"), width=1),
                dbc.Col(
                    dcc.Dropdown(
                        id="size",
                        options=dropdown_options,
                        value=None,
                    ),
                    width=2,
                ),
            ],
            className="text-center mt-3",
            justify="center",
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
    fluid=True,
)


@app.callback(
    Output("graph-container", "figure"),
    [
        Input("visualization-type", "value"),
        Input("x-axis", "value"),
        Input("y-axis", "value"),
        Input("color", "value"),
        Input("hover_name", "value"),
        Input("symbol", "value"),
        Input("size", "value"),
    ],
)
def update_graph(visualization_type, x_axis, y_axis, color, hover_name, symbol, size):
    # Process inputs and generate the appropriate graph
    plot_type = AVAILABLE_PLOT_TYPES[visualization_type]
    plot_func = plot_type["function"]
    plot_kwargs = {}

    plot_kwargs["x"] = x_axis
    plot_kwargs["y"] = y_axis
    print(size)
    if color:
        plot_kwargs["color"] = color
    if hover_name:
        plot_kwargs["hover_name"] = hover_name
    if symbol:
        plot_kwargs["symbol"] = symbol
    if size:
        print(size)
        plot_kwargs["size"] = size

    figure = plot_func(data_frame=df, **plot_kwargs)
    return figure


if __name__ == "__main__":
    app.run_server(debug=True)
