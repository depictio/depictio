from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import inspect
import numpy as np
import os, json
import plotly.express as px
import re


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
            "title": "Scatter plot of GDP per Capita vs. Life Expectancy",
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
    "countries-card": {
        "type": "Card",
        "description": "Countries number",
        "property": "Property X",
        "material-icons": "score",
        "function": dbc.Card,
        "column": "country",
        "operation": lambda col: col.nunique(),
        "kwargs": {},
    },
    "global-lifeexp-card": {
        "type": "Card",
        "description": "Average life expectancy",
        "property": "Property X",
        "material-icons": "score",
        "function": dbc.Card,
        "column": "lifeExp",
        "operation": lambda col: round(col.mean(), 2),
        "kwargs": {},
    },
    "time-slider-input": {
        "type": "Input",
        "description": "Year slider",
        "property": "Property Z",
        "material-icons": "tune",
        "function": dcc.Slider,
        "column": "year",
        "kwargs": {
            # "operation": lambda col: round(col.mean(), 2),
            # "min": df["year"].min(),
            # "max": df["year"].max(),
            # "value": init_year,
            # "step": None,
            "included": False,
        },
    },
    "continent-multiselect-input": {
        "type": "Input",
        "description": "Continent dropdown",
        "property": "Property I",
        "material-icons": "tune",
        "function": dcc.Dropdown,
        "column": "continent",
        "kwargs": {
            "multi": True,
            # "operation": lambda col: round(col.mean(), 2),
            # "min": df["year"].min(),
            # "max": df["year"].max(),
            # "value": init_year,
            # "step": None,
            # "included": True,
        },
    },
    "lifeexp-slider-input": {
        "type": "Input",
        "description": "LifeExp RangeSlider",
        "property": "Property J",
        "material-icons": "tune",
        "function": dcc.RangeSlider,
        "column": "lifeExp",
        "kwargs": {
            # "multi": True,
            # "operation": lambda col: round(col.mean(), 2),
            # "min": df["year"].min(),
            # "max": df["year"].max(),
            # "value": init_year,
            # "step": None,
            # "included": True,
        },
    },
    "country-input-input": {
        "type": "Input",
        "description": "Country Input",
        "property": "Property M",
        "material-icons": "search",
        "function": dcc.Input,
        "column": "country",
        "kwargs": {
            # "multi": True,
            # "operation": lambda col: round(col.mean(), 2),
            # "min": df["year"].min(),
            # "max": df["year"].max(),
            # "value": init_year,
            # "step": None,
            # "included": True,
        },
    },
}



agg_functions = {
    "int64": {
        "title": "Integer",
        "input_methods": {
            "Slider": {
                "component": dcc.Slider,
                "description": "Single value slider",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
                "description": "Two values slider",
            },
        },
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "unique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "average": {
                "pandas": "mean",
                "numpy": "mean",
                "description": "Mean of non-NA values",
            },
            "median": {
                "pandas": "median",
                "numpy": "median",
                "description": "Arithmetic median of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
            "range": {
                "pandas": lambda df: df.max() - df.min(),
                "numpy": "ptp",
                "description": "Range of non-NA values",
            },
            "variance": {
                "pandas": "var",
                "numpy": "var",
                "description": "Variance of non-NA values",
            },
            "std_dev": {
                "pandas": "std",
                "numpy": "std",
                "description": "Standard Deviation of non-NA values",
            },
            "percentile": {
                "pandas": "quantile",
                "numpy": "percentile",
                "description": "Percentiles of non-NA values",
            },
            "skewness": {
                "pandas": "skew",
                "numpy": None,
                "description": "Skewness of non-NA values",
            },
            "kurtosis": {
                "pandas": "kurt",
                "numpy": None,
                "description": "Kurtosis of non-NA values",
            },
            "cumulative_sum": {
                "pandas": "cumsum",
                "numpy": "cumsum",
                "description": "Cumulative sum of non-NA values",
            },
        },
    },
    "float64": {
        "title": "Floating Point",
        "input_methods": {
            "Slider": {
                "component": dcc.Slider,
                "description": "Single value slider",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
                "description": "Two values slider",
            },
        },
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "unique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "average": {
                "pandas": "mean",
                "numpy": "mean",
                "description": "Mean of non-NA values",
            },
            "median": {
                "pandas": "median",
                "numpy": "median",
                "description": "Arithmetic median of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
            "range": {
                "pandas": lambda df: df.max() - df.min(),
                "numpy": "ptp",
                "description": "Range of non-NA values",
            },
            "variance": {
                "pandas": "var",
                "numpy": "var",
                "description": "Variance of non-NA values",
            },
            "std_dev": {
                "pandas": "std",
                "numpy": "std",
                "description": "Standard Deviation of non-NA values",
            },
            "percentile": {
                "pandas": "quantile",
                "numpy": "percentile",
                "description": "Percentiles of non-NA values",
            },
            "skewness": {
                "pandas": "skew",
                "numpy": None,
                "description": "Skewness of non-NA values",
            },
            "kurtosis": {
                "pandas": "kurt",
                "numpy": None,
                "description": "Kurtosis of non-NA values",
            },
            "cumulative_sum": {
                "pandas": "cumsum",
                "numpy": "cumsum",
                "description": "Cumulative sum of non-NA values",
            },
        },
    },
    "bool": {
        "title": "Boolean",
        "description": "Boolean values",
        "input_methods": {
            "Checkbox": {
                "component": dmc.Checkbox,
                "description": "Checkbox",
            },
            "Switch": {
                "component": dmc.Switch,
                "description": "Switch",
            },
        },
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "datetime": {
        "title": "Datetime",
        "description": "Date and time values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "timedelta": {
        "title": "Timedelta",
        "description": "Differences between two datetimes",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "category": {
        "title": "Category",
        "description": "Finite list of text values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
        },
    },
    "object": {
        "title": "Object",
        "input_methods": {
            "TextInput": {
                "component": dmc.TextInput,
                "description": "Text input box",
            },
            "Select": {
                "component": dmc.Select,
                "description": "Select",
            },
            "MultiSelect": {
                "component": dmc.MultiSelect,
                "description": "MultiSelect",
            },
            "SegmentedControl": {
                "component": dmc.SegmentedControl,
                "description": "SegmentedControl",
            },
        },
        "description": "Text or mixed numeric or non-numeric values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
            "nunique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
        },
    },
}



# Add a new function to create a card with a number and a legend
def create_card(value, legend):
    return dbc.Card(
        [
            html.H2("{value}".format(value=value), className="card-title"),
            html.P(legend, className="card-text"),
        ],
        body=True,
        color="light",
    )


def create_input_component(df, dict_data, input_component_id):
    # print(dict_data)
    col = dict_data["column"]
    # print(col)
    # print(df)
    ComponentFunction = dict_data.get("function", dcc.Slider)  # Default to dcc.Slider

    if ComponentFunction is dcc.Slider:
        kwargs = dict(
            min=df[f"{col}"].min(),
            max=df[f"{col}"].max(),
            # value=value,
            marks={str(elem): str(elem) for elem in df[f"{col}"].unique()},
            step=None,
            included=False,
        )
    elif ComponentFunction is dcc.RangeSlider:
        kwargs = dict(
            min=df[f"{col}"].min(),
            max=df[f"{col}"].max(),
            # value=value,
            # marks={str(elem): str(elem) for elem in df[f"{col}"].unique()},
            # step=None,
            # included=True,
        )
    elif ComponentFunction is dcc.Dropdown:
        kwargs = dict(
            options=[{"label": i, "value": i} for i in df[f"{col}"].unique().tolist()],
            # value=value,
            multi=True,
        )
    elif ComponentFunction is dcc.Input:
        kwargs = dict(
            # options=[{"label": i, "value": i} for i in df[f"{col}"].unique().tolist()],
            type="text",
            placeholder="Enter a value...",
            # value=value,
            debounce=True,
        )
    # kwargs = dict(
    #     min=df[f"{col}"].min(),
    #     max=df[f"{col}"].max(),
    #     value=value,
    #     marks={str(elem): str(elem) for elem in df[f"{col}"].unique()},
    #     step=None,
    #     included=True,
    # )

    # return ComponentFunction(
    #     # id=input_component_id,
    #     # df[f"{col}"].unique().tolist(),
    #     id={"type": "input-component", "index": input_component_id},
    #     **kwargs,
    # )
    return html.Div(
        children=[
            html.H5(dict_data["description"]),
            ComponentFunction(
                # id=input_component_id,
                # df[f"{col}"].unique().tolist(),
                id={"type": "input-component", "index": input_component_id},
                **kwargs,
            ),
        ]
    )




def get_common_params(plotly_vizu_list):
    common_params = set.intersection(
        *[set(inspect.signature(func).parameters.keys()) for func in plotly_vizu_list]
    )
    common_param_names = [p for p in list(common_params)]
    common_param_names.sort(
        key=lambda x: list(inspect.signature(plotly_vizu_list[0]).parameters).index(x)
    )
    return common_params, common_param_names


def get_specific_params(plotly_vizu_list, common_params):
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
    return specific_params


def extract_info_from_docstring(docstring):
    lines = docstring.split("\n")
    # print(lines)
    parameters_section = False
    result = {}

    for line in lines:
        # print(line)
        if line.startswith("Parameters"):
            parameters_section = True
            continue
        if parameters_section:
            # if line.startswith("----------"):
            #     break
            if line.startswith("    ") is False:
                # print(line.split(': '))
                line_processed = line.split(": ")
                # print(line_processed)
                if len(line_processed) == 2:
                    parameter, type = line_processed[0], line_processed[1]
                    result[parameter] = {"type": type, "description": list()}
                else:
                    continue

            elif line.startswith("    ") is True:
                # result[-1] += " " + line.strip()
                # print(line.strip())
                result[parameter]["description"].append(line.strip())

    return result


def process_json_from_docstring(data):
    for key, value in data.items():
        # Get the type associated with the field
        field_type = value.get("type")
        # field_type = value.get('type')
        description = " ".join(value.get("description"))

        # Check if there are any options available for the field
        options = []
        # for description in value.get('description', []):
        if "One of" in description:
            # The options are usually listed after 'One of'
            option_str = description.split("One of")[-1].split(".")[0]

            options = list(set(re.findall("`'(.*?)'`", option_str)))
        elif "one of" in data[key]["type"]:
            option_str = data[key]["type"].split("one of")[-1]
            options = list(set(re.findall("`'(.*?)'`", option_str)))

        if options:
            data[key]["options"] = options

        if "Series or array-like" in field_type:
            data[key]["processed_type"] = "column"
        else:
            data[key]["processed_type"] = data[key]["type"].split(" ")[0].split(",")[0]
    return data


def get_param_info(plotly_vizu_list):
    # Code for extract_info_from_docstring and process_json_from_docstring...
    # ...
    param_info = {}
    for func in plotly_vizu_list:
        param_info[func.__name__] = extract_info_from_docstring(func.__doc__)
        param_info[func.__name__] = process_json_from_docstring(
            param_info[func.__name__]
        )
    return param_info


def get_dropdown_options(df):
    dropdown_options = [{"label": col, "value": col} for col in df.columns]
    return dropdown_options


def process_data_for_card(df, column, operation):
    value = operation(df[column])
    return value


def create_initial_figure(df, plot_type, input_id=None, filter=dict(), id=None):
    # print("TOTO")
    # print(selected_year)
    print(df)
    print(filter)
    print(plot_type)
    if filter and input_id:
        filtered_df = df
        # Apply all active filters
        for input_component_name, filter_value in filter.items():
            column_name = AVAILABLE_PLOT_TYPES[input_component_name]["column"]
            function_type = AVAILABLE_PLOT_TYPES[input_component_name]["function"]
            print(column_name, filter_value)

            if function_type is dcc.Slider:
                filtered_df = filtered_df[filtered_df[column_name] == filter_value]

            elif function_type is dcc.Dropdown:
                filtered_df = filtered_df[filtered_df[column_name].isin(filter_value)]

            elif function_type is dcc.Input:
                print(filter_value)
                filtered_df = filtered_df[
                    filtered_df[column_name].str.contains(filter_value, regex=True)
                ]

            elif function_type is dcc.RangeSlider:
                filtered_df = filtered_df[
                    (filtered_df[column_name] >= filter_value[0])
                    & (filtered_df[column_name] <= filter_value[1])
                ]

            else:
                filtered_df = filtered_df

    else:
        filtered_df = df
    # filtered_df = df
    # print(plot_type)
    if AVAILABLE_PLOT_TYPES[plot_type]["type"] is "Card":
        value = process_data_for_card(
            filtered_df,
            AVAILABLE_PLOT_TYPES[plot_type]["column"],
            AVAILABLE_PLOT_TYPES[plot_type]["operation"],
        )
        # print(value)
        fig = create_card(
            value,
            AVAILABLE_PLOT_TYPES[plot_type]["description"],
        )
    elif AVAILABLE_PLOT_TYPES[plot_type]["type"] is "Input":
        fig = create_input_component(
            df,
            AVAILABLE_PLOT_TYPES[plot_type],
            input_component_id=id
            # selected_year, df, AVAILABLE_PLOT_TYPES[plot_type], id
        )
    else:
        fig = AVAILABLE_PLOT_TYPES[plot_type]["function"](
            filtered_df, **AVAILABLE_PLOT_TYPES[plot_type]["kwargs"]
        )

        fig.update_layout(transition_duration=500)

    return fig


def load_data():
    if os.path.exists("data.json"):
        with open("data.json", "r") as file:
            data = json.load(file)
            print(data)
        return data
    return None




# TODO: utils / config

# Define the list of Plotly visualizations
plotly_vizu_list = [px.scatter, px.line, px.bar, px.histogram, px.box]

# Map visualization function names to the functions themselves
plotly_vizu_dict = {vizu_func.__name__: vizu_func for vizu_func in plotly_vizu_list}

# Get common and specific parameters for the visualizations
common_params, common_params_names = get_common_params(plotly_vizu_list)
specific_params = get_specific_params(plotly_vizu_list, common_params)

# print(common_params)
# print(common_params_names)
# print(specific_params)

# Generate parameter information and dropdown options
param_info = get_param_info(plotly_vizu_list)
# dropdown_options = get_dropdown_options(df)

# Define the elements for the dropdown menu
base_elements = ["x", "y", "color"]

# Define allowed types and the corresponding Bootstrap components
allowed_types = ["str", "int", "float", "boolean", "column"]
plotly_bootstrap_mapping = {
    "str": dbc.Input,
    "int": dbc.Input,
    "float": dbc.Input,
    "boolean": dbc.Checklist,
    "column": dcc.Dropdown,
    "list": dcc.Dropdown,
}

# Identify the parameters not in the dropdown elements
secondary_common_params = [
    e
    for e in common_params_names[1:]
    # e for e in common_params_names[1:] if e not in dropdown_elements
]
secondary_common_params_lite = [
    e
    for e in secondary_common_params
    if e
    not in [
        "category_orders",
        "color_discrete_sequence",
        "color_discrete_map",
        "log_x",
        "log_y",
        "labels",
        "range_x",
        "range_y",
    ]
]
# print(secondary_common_params)
# print("\n")