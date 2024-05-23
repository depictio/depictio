from dash import dcc, html
import dash_bootstrap_components as dbc
import inspect
import plotly.express as px
import re

from depictio.api.v1.deltatables_utils import load_deltatable_lite


def build_figure_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "figure-body",
                    "index": index,
                }
            ),
            style={"width": "100%"},
            id={
                "type": "figure-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "figure-body",
                    "index": index,
                },
            ),
            style={"width": "100%"},
            id={
                "type": "figure-component",
                "index": index,
            },
        )

def render_figure(dict_kwargs, visu_type, df):
    if dict_kwargs and visu_type.lower() in plotly_vizu_dict and df is not None:
        figure = plotly_vizu_dict[visu_type.lower()](df, **dict_kwargs)
        return figure
    else:
        # return empty figure
        # raise ValueError("Error in render_figure")
        return px.scatter()

def build_figure(**kwargs):
    index = kwargs.get("index")
    dict_kwargs = kwargs.get("dict_kwargs")
    visu_type = kwargs.get("visu_type")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    build_frame = kwargs.get("build_frame", False)
    import polars as pl
    df = kwargs.get("df", pl.DataFrame())



    store_component_data = {
        "index": str(index),
        "component_type": "figure",
        "dict_kwargs": dict_kwargs,
        "visu_type": visu_type,
        "wf_id": wf_id,
        "dc_id": dc_id,
        "dc_config": dc_config,
    }
    dict_kwargs = {k: v for k, v in dict_kwargs.items() if v is not None}

    # wf_id, dc_id = return_mongoid(workflow_id=wf_id, data_collection_id=dc_id)
    if df.is_empty():
        df = load_deltatable_lite(wf_id, dc_id)

    figure = render_figure(dict_kwargs, visu_type, df)

    figure_div = html.Div(
        [
            dcc.Graph(
                # figure,
                figure=figure,
                id={"type": "graph", "index": index},
                config={"editable": True, "scrollZoom": True},
            ),
            # f"TEST-GRAPH-{id['index']}",
            dcc.Store(
                data=store_component_data,
                id={
                    "type": "stored-metadata-component",
                    "index": index,
                },
            ),
        ]
    )
    if not build_frame:
        return figure_div
    else:
        return build_figure_frame(index, children=figure_div)


def extract_info_from_docstring(docstring):
    """
    Extract information from a docstring and return a dictionary with the parameters and their types
    """
    lines = docstring.split("\n")
    parameters_section = False
    result = {}

    # Iterate over the lines in the docstring
    for line in lines:
        # Check if the line starts with 'Parameters'
        if line.startswith("Parameters"):
            parameters_section = True
            continue
        # Check if the line starts with 'Returns'
        if parameters_section:
            if line.startswith("    ") is False:
                line_processed = line.split(": ")
                # Check if the line contains a parameter and a type
                if len(line_processed) == 2:
                    # Get the parameter and the type and add them to the result dictionary
                    parameter, type = line_processed[0], line_processed[1]
                    result[parameter] = {"type": type, "description": list()}
                else:
                    continue
            # If the line starts with 4 spaces, it is a description of the parameter
            elif line.startswith("    ") is True:
                result[parameter]["description"].append(line.strip())

    return result


def process_json_from_docstring(data):
    """
    Process the JSON data extracted from the docstring to add the processed type and options
    """
    for key, value in data.items():
        # Get the type associated with the field
        field_type = value.get("type")
        description = " ".join(value.get("description"))

        # Check if there are any options available for the field
        options = []
        # Check if the description contains 'One of'
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
        param_info[func.__name__] = process_json_from_docstring(param_info[func.__name__])
    return param_info


# FIXME: find another way than inspect.signature to get the parameters, not stable enough for long term support
# TODO: export this to a separate file in order to be used in the frontend


def get_common_params(plotly_vizu_list):
    """
    Get the common parameters between a list of Plotly visualizations
    """
    # Iterate over the list of visualizations and get the parameters, then get the common ones
    common_params = set.intersection(*[set(inspect.signature(func).parameters.keys()) for func in plotly_vizu_list])
    # Sort the common parameters based on the order of the first visualization
    common_param_names = [p for p in list(common_params)]
    common_param_names.sort(key=lambda x: list(inspect.signature(plotly_vizu_list[0]).parameters).index(x))
    return common_params, common_param_names


def get_specific_params(plotly_vizu_list, common_params):
    """
    Get the specific parameters for each visualization in a list of Plotly visualizations
    """
    # Iterate over the list of visualizations and get the specific parameters
    specific_params = {}
    for vizu_func in plotly_vizu_list:
        func_params = inspect.signature(vizu_func).parameters
        param_names = list(func_params.keys())
        common_params_tmp = common_params.intersection(func_params.keys()) if common_params else set(func_params.keys())
        specific_params[vizu_func.__name__] = [p for p in param_names if p not in common_params_tmp]
    return specific_params


########################################

# TODO: move this to a separate file

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

# Define the list of Plotly visualizations
plotly_vizu_list = [px.scatter, px.line, px.bar, px.histogram, px.box]

# Map visualization function names to the functions themselves
plotly_vizu_dict = {vizu_func.__name__: vizu_func for vizu_func in plotly_vizu_list}

# Get common and specific parameters for the visualizations
common_params, common_params_names = get_common_params(plotly_vizu_list)
# print("\n")
# print("common_params", common_params)
# print("\n")
specific_params = get_specific_params(plotly_vizu_list, common_params)

# print(common_params)
# print(common_params_names)
# print(specific_params)

# Generate parameter information and dropdown options
param_info = get_param_info(plotly_vizu_list)
# dropdown_options = get_dropdown_options(df)


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
