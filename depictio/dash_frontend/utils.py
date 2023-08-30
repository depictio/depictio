import collections
from io import BytesIO
import sys

sys.path.append("/Users/tweber/Gits/depictio")

from depictio.fastapi_backend.db import grid_fs, redis_cache
from depictio.fastapi_backend.configs.config import settings
from CLI_client.cli import list_workflows
import httpx
from bson import ObjectId
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import inspect
import numpy as np
import os, json
import pandas as pd
import plotly.express as px
import re

API_BASE_URL = "http://localhost:8058"


# AVAILABLE_PLOT_TYPES = {
#     "scatter-plot": {
#         "type": "Scatter plot",
#         "description": "Scatter plot of GDP per Capita vs. Life Expectancy",
#         "property": "Property A",
#         "material-icons": "scatter_plot",
#         "function": px.scatter,
#         "kwargs": {
#             "x": "gdpPercap",
#             "y": "lifeExp",
#             "size": "pop",
#             "color": "continent",
#             "hover_name": "country",
#             "log_x": True,
#             "size_max": 55,
#             "title": "Scatter plot of GDP per Capita vs. Life Expectancy",
#             # "animation_frame": "year",
#         },
#     },
#     "bar-plot": {
#         "type": "Bar plot",
#         "description": "Bar plot of Total GDP per Year",
#         "property": "Property B",
#         "material-icons": "bar_chart",
#         "function": px.bar,
#         "kwargs": {
#             "x": "year",
#             "y": "gdpPercap",
#             "color": "continent",
#             "hover_name": "country",
#             "facet_col": "continent",
#             "facet_col_wrap": 3,
#             "height": 700,
#         },
#     },
#     "line-plot": {
#         "type": "Line plot",
#         "description": "Line plot of GDP per Capita over Time",
#         "property": "Property C",
#         "material-icons": "show_chart",
#         "function": px.line,
#         "kwargs": {
#             "x": "year",
#             "y": "gdpPercap",
#             "color": "continent",
#             "hover_name": "country",
#             "line_group": "country",
#             "line_shape": "spline",
#             "render_mode": "svg",
#         },
#     },
#     "box-plot": {
#         "type": "Box plot",
#         "description": "Box plot of Life Expectancy by Continent",
#         "property": "Property D",
#         "material-icons": "candlestick_chart",
#         "function": px.box,
#         "kwargs": {
#             "x": "continent",
#             "y": "lifeExp",
#             "color": "continent",
#             "hover_name": "country",
#             "points": "all",
#             "notched": True,
#         },
#     },
#     "pie-chart": {
#         "type": "Pie chart",
#         "description": "Pie chart of Population by Continent",
#         "property": "Property E",
#         "material-icons": "pie_chart",
#         "function": px.pie,
#         "kwargs": {
#             "names": "continent",
#             "values": "pop",
#             "hover_name": "continent",
#             "hole": 0.4,
#             # "animation_frame": "year",
#             # "title": "Population by Continent",
#         },
#     },
#     "countries-card": {
#         "type": "Card",
#         "description": "Countries number",
#         "property": "Property X",
#         "material-icons": "score",
#         "function": dbc.Card,
#         "column": "country",
#         "operation": lambda col: col.nunique(),
#         "kwargs": {},
#     },
#     "global-lifeexp-card": {
#         "type": "Card",
#         "description": "Average life expectancy",
#         "property": "Property X",
#         "material-icons": "score",
#         "function": dbc.Card,
#         "column": "lifeExp",
#         "operation": lambda col: round(col.mean(), 2),
#         "kwargs": {},
#     },
#     "time-slider-input": {
#         "type": "Input",
#         "description": "Year slider",
#         "property": "Property Z",
#         "material-icons": "tune",
#         "function": dcc.Slider,
#         "column": "year",
#         "kwargs": {
#             # "operation": lambda col: round(col.mean(), 2),
#             # "min": df["year"].min(),
#             # "max": df["year"].max(),
#             # "value": init_year,
#             # "step": None,
#             "included": False,
#         },
#     },
#     "continent-multiselect-input": {
#         "type": "Input",
#         "description": "Continent dropdown",
#         "property": "Property I",
#         "material-icons": "tune",
#         "function": dcc.Dropdown,
#         "column": "continent",
#         "kwargs": {
#             "multi": True,
#             # "operation": lambda col: round(col.mean(), 2),
#             # "min": df["year"].min(),
#             # "max": df["year"].max(),
#             # "value": init_year,
#             # "step": None,
#             # "included": True,
#         },
#     },
#     "lifeexp-slider-input": {
#         "type": "Input",
#         "description": "LifeExp RangeSlider",
#         "property": "Property J",
#         "material-icons": "tune",
#         "function": dcc.RangeSlider,
#         "column": "lifeExp",
#         "kwargs": {
#             # "multi": True,
#             # "operation": lambda col: round(col.mean(), 2),
#             # "min": df["year"].min(),
#             # "max": df["year"].max(),
#             # "value": init_year,
#             # "step": None,
#             # "included": True,
#         },
#     },
#     "country-input-input": {
#         "type": "Input",
#         "description": "Country Input",
#         "property": "Property M",
#         "material-icons": "search",
#         "function": dcc.Input,
#         "column": "country",
#         "kwargs": {
#             # "multi": True,
#             # "operation": lambda col: round(col.mean(), 2),
#             # "min": df["year"].min(),
#             # "max": df["year"].max(),
#             # "value": init_year,
#             # "step": None,
#             # "included": True,
#         },
#     },
# }


# agg_functions = {
#     "int64": {
#         "title": "Integer",
#         "input_methods": {
#             "Slider": {
#                 "component": dcc.Slider,
#                 "description": "Single value slider",
#             },
#             "RangeSlider": {
#                 "component": dcc.RangeSlider,
#                 "description": "Two values slider",
#             },
#         },
#         "card_methods": {
#             "count": {
#                 "pandas": "count",
#                 "numpy": "count_nonzero",
#                 "description": "Counts the number of non-NA cells",
#             },
#             "unique": {
#                 "pandas": "nunique",
#                 "numpy": None,
#                 "description": "Number of distinct elements",
#             },
#             "sum": {
#                 "pandas": "sum",
#                 "numpy": "sum",
#                 "description": "Sum of non-NA values",
#             },
#             "average": {
#                 "pandas": "mean",
#                 "numpy": "mean",
#                 "description": "Mean of non-NA values",
#             },
#             "median": {
#                 "pandas": "median",
#                 "numpy": "median",
#                 "description": "Arithmetic median of non-NA values",
#             },
#             "min": {
#                 "pandas": "min",
#                 "numpy": "min",
#                 "description": "Minimum of non-NA values",
#             },
#             "max": {
#                 "pandas": "max",
#                 "numpy": "max",
#                 "description": "Maximum of non-NA values",
#             },
#             "range": {
#                 "pandas": lambda df: df.max() - df.min(),
#                 "numpy": "ptp",
#                 "description": "Range of non-NA values",
#             },
#             "variance": {
#                 "pandas": "var",
#                 "numpy": "var",
#                 "description": "Variance of non-NA values",
#             },
#             "std_dev": {
#                 "pandas": "std",
#                 "numpy": "std",
#                 "description": "Standard Deviation of non-NA values",
#             },
#             "percentile": {
#                 "pandas": "quantile",
#                 "numpy": "percentile",
#                 "description": "Percentiles of non-NA values",
#             },
#             "skewness": {
#                 "pandas": "skew",
#                 "numpy": None,
#                 "description": "Skewness of non-NA values",
#             },
#             "kurtosis": {
#                 "pandas": "kurt",
#                 "numpy": None,
#                 "description": "Kurtosis of non-NA values",
#             },
#             # "cumulative_sum": {
#             #     "pandas": "cumsum",
#             #     "numpy": "cumsum",
#             #     "description": "Cumulative sum of non-NA values",
#             # },
#         },
#     },
#     "float64": {
#         "title": "Floating Point",
#         "input_methods": {
#             "Slider": {
#                 "component": dcc.Slider,
#                 "description": "Single value slider",
#             },
#             "RangeSlider": {
#                 "component": dcc.RangeSlider,
#                 "description": "Two values slider",
#             },
#         },
#         "card_methods": {
#             "count": {
#                 "pandas": "count",
#                 "numpy": "count_nonzero",
#                 "description": "Counts the number of non-NA cells",
#             },
#             "unique": {
#                 "pandas": "nunique",
#                 "numpy": None,
#                 "description": "Number of distinct elements",
#             },
#             "sum": {
#                 "pandas": "sum",
#                 "numpy": "sum",
#                 "description": "Sum of non-NA values",
#             },
#             "average": {
#                 "pandas": "mean",
#                 "numpy": "mean",
#                 "description": "Mean of non-NA values",
#             },
#             "median": {
#                 "pandas": "median",
#                 "numpy": "median",
#                 "description": "Arithmetic median of non-NA values",
#             },
#             "min": {
#                 "pandas": "min",
#                 "numpy": "min",
#                 "description": "Minimum of non-NA values",
#             },
#             "max": {
#                 "pandas": "max",
#                 "numpy": "max",
#                 "description": "Maximum of non-NA values",
#             },
#             "range": {
#                 "pandas": lambda df: df.max() - df.min(),
#                 "numpy": "ptp",
#                 "description": "Range of non-NA values",
#             },
#             "variance": {
#                 "pandas": "var",
#                 "numpy": "var",
#                 "description": "Variance of non-NA values",
#             },
#             "std_dev": {
#                 "pandas": "std",
#                 "numpy": "std",
#                 "description": "Standard Deviation of non-NA values",
#             },
#             "percentile": {
#                 "pandas": "quantile",
#                 "numpy": "percentile",
#                 "description": "Percentiles of non-NA values",
#             },
#             "skewness": {
#                 "pandas": "skew",
#                 "numpy": None,
#                 "description": "Skewness of non-NA values",
#             },
#             "kurtosis": {
#                 "pandas": "kurt",
#                 "numpy": None,
#                 "description": "Kurtosis of non-NA values",
#             },
#             # "cumulative_sum": {
#             #     "pandas": "cumsum",
#             #     "numpy": "cumsum",
#             #     "description": "Cumulative sum of non-NA values",
#             # },
#         },
#     },
#     "bool": {
#         "title": "Boolean",
#         "description": "Boolean values",
#         "input_methods": {
#             "Checkbox": {
#                 "component": dmc.Checkbox,
#                 "description": "Checkbox",
#             },
#             "Switch": {
#                 "component": dmc.Switch,
#                 "description": "Switch",
#             },
#         },
#         "card_methods": {
#             "count": {
#                 "pandas": "count",
#                 "numpy": "count_nonzero",
#                 "description": "Counts the number of non-NA cells",
#             },
#             "sum": {
#                 "pandas": "sum",
#                 "numpy": "sum",
#                 "description": "Sum of non-NA values",
#             },
#             "min": {
#                 "pandas": "min",
#                 "numpy": "min",
#                 "description": "Minimum of non-NA values",
#             },
#             "max": {
#                 "pandas": "max",
#                 "numpy": "max",
#                 "description": "Maximum of non-NA values",
#             },
#         },
#     },
#     "datetime": {
#         "title": "Datetime",
#         "description": "Date and time values",
#         "card_methods": {
#             "count": {
#                 "pandas": "count",
#                 "numpy": "count_nonzero",
#                 "description": "Counts the number of non-NA cells",
#             },
#             "min": {
#                 "pandas": "min",
#                 "numpy": "min",
#                 "description": "Minimum of non-NA values",
#             },
#             "max": {
#                 "pandas": "max",
#                 "numpy": "max",
#                 "description": "Maximum of non-NA values",
#             },
#         },
#     },
#     "timedelta": {
#         "title": "Timedelta",
#         "description": "Differences between two datetimes",
#         "card_methods": {
#             "count": {
#                 "pandas": "count",
#                 "numpy": "count_nonzero",
#                 "description": "Counts the number of non-NA cells",
#             },
#             "sum": {
#                 "pandas": "sum",
#                 "numpy": "sum",
#                 "description": "Sum of non-NA values",
#             },
#             "min": {
#                 "pandas": "min",
#                 "numpy": "min",
#                 "description": "Minimum of non-NA values",
#             },
#             "max": {
#                 "pandas": "max",
#                 "numpy": "max",
#                 "description": "Maximum of non-NA values",
#             },
#         },
#     },
#     "category": {
#         "title": "Category",
#         "description": "Finite list of text values",
#         "card_methods": {
#             "count": {
#                 "pandas": "count",
#                 "numpy": "count_nonzero",
#                 "description": "Counts the number of non-NA cells",
#             },
#             "mode": {
#                 "pandas": "mode",
#                 "numpy": None,
#                 "description": "Most common value",
#             },
#         },
#     },
#     "object": {
#         "title": "Object",
#         "input_methods": {
#             "TextInput": {
#                 "component": dmc.TextInput,
#                 "description": "Text input box",
#             },
#             "Select": {
#                 "component": dmc.Select,
#                 "description": "Select",
#             },
#             "MultiSelect": {
#                 "component": dmc.MultiSelect,
#                 "description": "MultiSelect",
#             },
#             "SegmentedControl": {
#                 "component": dmc.SegmentedControl,
#                 "description": "SegmentedControl",
#             },
#         },
#         "description": "Text or mixed numeric or non-numeric values",
#         "card_methods": {
#             "count": {
#                 "pandas": "count",
#                 "numpy": "count_nonzero",
#                 "description": "Counts the number of non-NA cells",
#             },
#             "mode": {
#                 "pandas": "mode",
#                 "numpy": None,
#                 "description": "Most common value",
#             },
#             "nunique": {
#                 "pandas": "nunique",
#                 "numpy": None,
#                 "description": "Number of distinct elements",
#             },
#         },
#     },
# }


# # Add a new function to create a card with a number and a legend
# def create_card(value, legend):
#     return dbc.Card(
#         [
#             html.H2("{value}".format(value=value), className="card-title"),
#             html.P(legend, className="card-text"),
#         ],
#         body=True,
#         color="light",
#     )


# def create_input_component(df, dict_data, input_component_id):
#     # print(dict_data)
#     col = dict_data["column"]
#     # print(col)
#     # print(df)
#     ComponentFunction = dict_data.get("function", dcc.Slider)  # Default to dcc.Slider

#     if ComponentFunction is dcc.Slider:
#         kwargs = dict(
#             min=df[f"{col}"].min(),
#             max=df[f"{col}"].max(),
#             # value=value,
#             marks={str(elem): str(elem) for elem in df[f"{col}"].unique()},
#             step=None,
#             included=False,
#         )
#     elif ComponentFunction is dcc.RangeSlider:
#         kwargs = dict(
#             min=df[f"{col}"].min(),
#             max=df[f"{col}"].max(),
#             # value=value,
#             # marks={str(elem): str(elem) for elem in df[f"{col}"].unique()},
#             # step=None,
#             # included=True,
#         )
#     elif ComponentFunction is dcc.Dropdown:
#         kwargs = dict(
#             options=[{"label": i, "value": i} for i in df[f"{col}"].unique().tolist()],
#             # value=value,
#             multi=True,
#         )
#     elif ComponentFunction is dcc.Input:
#         kwargs = dict(
#             # options=[{"label": i, "value": i} for i in df[f"{col}"].unique().tolist()],
#             type="text",
#             placeholder="Enter a value...",
#             # value=value,
#             debounce=True,
#         )
#     # kwargs = dict(
#     #     min=df[f"{col}"].min(),
#     #     max=df[f"{col}"].max(),
#     #     value=value,
#     #     marks={str(elem): str(elem) for elem in df[f"{col}"].unique()},
#     #     step=None,
#     #     included=True,
#     # )

#     # return ComponentFunction(
#     #     # id=input_component_id,
#     #     # df[f"{col}"].unique().tolist(),
#     #     id={"type": "input-component", "index": input_component_id},
#     #     **kwargs,
#     # )
#     return html.Div(
#         children=[
#             html.H5(dict_data["description"]),
#             ComponentFunction(
#                 # id=input_component_id,
#                 # df[f"{col}"].unique().tolist(),
#                 id={"type": "input-component", "index": input_component_id},
#                 **kwargs,
#             ),
#         ]
#     )



# def get_dropdown_options(df):
#     dropdown_options = [{"label": col, "value": col} for col in df.columns]
#     return dropdown_options


# def process_data_for_card(df, column, operation):
#     value = operation(df[column])
#     return value


# def create_initial_figure(df, plot_type, input_id=None, filter=dict(), id=None):
#     # print("TOTO")
#     # print(selected_year)
#     print(df)
#     print(filter)
#     print(plot_type)
#     if filter and input_id:
#         filtered_df = df
#         # Apply all active filters
#         for input_component_name, filter_value in filter.items():
#             column_name = AVAILABLE_PLOT_TYPES[input_component_name]["column"]
#             function_type = AVAILABLE_PLOT_TYPES[input_component_name]["function"]
#             print(column_name, filter_value)

#             if function_type is dcc.Slider:
#                 filtered_df = filtered_df[filtered_df[column_name] == filter_value]

#             elif function_type is dcc.Dropdown:
#                 filtered_df = filtered_df[filtered_df[column_name].isin(filter_value)]

#             elif function_type is dcc.Input:
#                 print(filter_value)
#                 filtered_df = filtered_df[
#                     filtered_df[column_name].str.contains(filter_value, regex=True)
#                 ]

#             elif function_type is dcc.RangeSlider:
#                 filtered_df = filtered_df[
#                     (filtered_df[column_name] >= filter_value[0])
#                     & (filtered_df[column_name] <= filter_value[1])
#                 ]

#             else:
#                 filtered_df = filtered_df

#     else:
#         filtered_df = df
#     # filtered_df = df
#     # print(plot_type)
#     if AVAILABLE_PLOT_TYPES[plot_type]["type"] == "Card":
#         value = process_data_for_card(
#             filtered_df,
#             AVAILABLE_PLOT_TYPES[plot_type]["column"],
#             AVAILABLE_PLOT_TYPES[plot_type]["operation"],
#         )
#         # print(value)
#         fig = create_card(
#             value,
#             AVAILABLE_PLOT_TYPES[plot_type]["description"],
#         )
#     elif AVAILABLE_PLOT_TYPES[plot_type]["type"] == "Input":
#         fig = create_input_component(
#             df,
#             AVAILABLE_PLOT_TYPES[plot_type],
#             input_component_id=id
#             # selected_year, df, AVAILABLE_PLOT_TYPES[plot_type], id
#         )
#     else:
#         fig = AVAILABLE_PLOT_TYPES[plot_type]["function"](
#             filtered_df, **AVAILABLE_PLOT_TYPES[plot_type]["kwargs"]
#         )

#         fig.update_layout(transition_duration=500)

#     return fig


def load_data():
    if os.path.exists("data.json"):
        with open("data.json", "r") as file:
            data = json.load(file)
            print(data)
        return data
    return None


def load_gridfs_file(workflow_id: str, data_collection_id: str, cols: list = None):
    print(workflow_id, data_collection_id)

    if workflow_id is None or data_collection_id is None:
        response = httpx.get(f"{API_BASE_URL}/workflows/get_workflows")
        print(response)
        if response.status_code == 200:
            workflow_id = response.json()[0]["workflow_id"]
            data_collection_id = response.json()[0]["data_collection_ids"][0]
            print(response.json())

        else:
            print("No workflows found")
            return None

    print(workflow_id)

    workflow_engine = workflow_id.split("/")[0]
    workflow_name = workflow_id.split("/")[1]

    print(workflow_engine, workflow_name)
    print(data_collection_id)

    response = httpx.get(
        f"{API_BASE_URL}/datacollections/get_aggregated_file_id/{workflow_engine}/{workflow_name}/{data_collection_id}"
    )
    print(response)

    if response.status_code == 200:
        file_id = response.json()["gridfs_file_id"]

        # Get the file from GridFS

        # Check if present in redis cache otherwise load and save to redis

        if redis_cache.exists(file_id):
            print("Loading from redis cache")
            # Convert the binary data to a BytesIO stream
            data_stream = BytesIO(redis_cache.get(file_id))
            if not cols:
                df = pd.read_parquet(data_stream)
            else:
                df = pd.read_parquet(data_stream, columns=cols)

        else:
            print("Loading from gridfs")
            associated_file = grid_fs.get(ObjectId(file_id))
            if not cols:
                df = pd.read_parquet(associated_file)
            else:
                df = pd.read_parquet(associated_file, columns=cols)
            redis_cache.set(file_id, df.to_parquet())

        return df


def get_columns_from_data_collection(
    workflow_id: str,
    data_collection_id: str,
):
    print("get_columns_from_data_collection")
    print(workflow_id, data_collection_id)

    if workflow_id is not None and data_collection_id is not None:
        print("OK")
        print(workflow_id, data_collection_id)
        workflow_engine = workflow_id.split("/")[0]
        workflow_name = workflow_id.split("/")[1]
        print(workflow_engine, workflow_name)
        response = httpx.get(
            f"{API_BASE_URL}/datacollections/get_columns/{workflow_engine}/{workflow_name}/{data_collection_id}"
        )
        print(response)
        if response.status_code == 200:
            json = response.json()
            print(json)
            return json
        else:
            print("No workflows found")
            return None


def list_workflows_for_dropdown():
    workflows = [wf["workflow_id"] for wf in list_workflows()]
    workflows_dict_for_dropdown = [{"label": wf, "value": wf} for wf in workflows]
    print(workflows_dict_for_dropdown)
    return workflows_dict_for_dropdown


def list_data_collections_for_dropdown(workflow_id: str = None):
    if workflow_id is None:
        return []
    else:
        data_collections = [
            dc
            for wf in list_workflows()
            for dc in wf["data_collection_ids"]
            if wf["workflow_id"] == workflow_id
        ]
        data_collections_dict_for_dropdown = [
            {"label": dc, "value": dc} for dc in data_collections
        ]
        return data_collections_dict_for_dropdown


# TODO: utils / config

