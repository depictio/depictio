import inspect
import re

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import plotly.express as px
import polars as pl
from bson import ObjectId
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite


def build_figure_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "figure-body",
                    "index": index,
                },
                style={
                    "padding": "5px",  # Reduce padding inside the card body
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                    "height": "100%",  # Make sure it fills the parent container
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Optional: Remove shadow for a cleaner look
                # "border": "1px solid #ddd",  # Optional: Add a light border
                # "borderRadius": "4px",  # Optional: Slightly round the corners
                "border": "0px",  # Optional: Remove border
            },
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
                style={
                    "padding": "5px",  # Reduce padding inside the card body
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                    "height": "100%",  # Make sure it fills the parent container
                },
            ),
            style={
                "overflowX": "hidden",
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Optional: Remove shadow for a cleaner look
                # "border": "1px solid #ddd",  # Optional: Add a light border
                # "borderRadius": "4px",  # Optional: Slightly round the corners
                "border": "0px",  # Optional: Remove border
            },
            id={
                "type": "figure-component",
                "index": index,
            },
        )


# Cache for sampled data to avoid re-sampling large datasets
_sampling_cache = {}


def render_figure(dict_kwargs, visu_type, df, cutoff=100000, selected_point=None):
    if dict_kwargs and visu_type.lower() in plotly_vizu_dict and df is not None:
        if df.height > cutoff:
            # Use caching for sampled data to improve performance
            cache_key = f"{id(df)}_{cutoff}_{hash(str(dict_kwargs))}"
            if cache_key not in _sampling_cache:
                _sampling_cache[cache_key] = df.sample(n=cutoff, seed=0).to_pandas()
                logger.debug(
                    f"Figure: Cached sampled data for large dataset (cache_key: {cache_key})"
                )
            else:
                logger.debug(f"Figure: Using cached sampled data (cache_key: {cache_key})")

            figure = plotly_vizu_dict[visu_type.lower()](_sampling_cache[cache_key], **dict_kwargs)
        else:
            figure = plotly_vizu_dict[visu_type.lower()](df.to_pandas(), **dict_kwargs)
    else:
        figure = px.scatter()

    if selected_point:
        selected_x = selected_point["x"]
        selected_y = selected_point["y"]

        # Optimized: Single vectorized operation instead of multiple list comprehensions
        x_col = df[dict_kwargs["x"]]
        y_col = df[dict_kwargs["y"]]

        # Create boolean mask for selected points
        is_selected = (x_col == selected_x) & (y_col == selected_y)

        # Use vectorized operations for better performance
        colors = ["red" if sel else "blue" for sel in is_selected]
        opacities = [1.0 if sel else 0.3 for sel in is_selected]

        # Update marker colors with optimized data
        figure.update_traces(
            marker=dict(
                color=colors,
                opacity=opacities,
            )
        )

    return figure


def build_figure(**kwargs):
    index = kwargs.get("index")
    dict_kwargs = kwargs.get("dict_kwargs", {})
    visu_type = kwargs.get("visu_type", "scatter")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    build_frame = kwargs.get("build_frame", False)
    parent_index = kwargs.get("parent_index", None)
    df = kwargs.get("df", pl.DataFrame())
    TOKEN = kwargs.get("access_token")
    filter_applied = kwargs.get("filter_applied", False)

    # selected_point = kwargs.get("selected_point")  # New parameter for selected point

    logger.info(f"Building figure with index {index}")
    # logger.info(f"Dict kwargs: {dict_kwargs}")
    # logger.info(f"Visu type: {visu_type}")
    # logger.info(f"WF ID: {wf_id}")
    # logger.info(f"DC ID: {dc_id}")
    # logger.info(f"DC config: {dc_config}")
    # logger.info(f"Build frame: {build_frame}")
    # logger.info(f"Selected Point: {selected_point}")

    store_index = index.replace("-tmp", "") if index else "unknown"

    store_component_data = {
        "index": str(store_index),
        "component_type": "figure",
        "dict_kwargs": dict_kwargs,
        "visu_type": visu_type,
        "wf_id": wf_id,
        "dc_id": dc_id,
        "dc_config": dc_config,
        "parent_index": parent_index,
        "filter_applied": filter_applied,
    }

    dict_kwargs = {k: v for k, v in dict_kwargs.items() if v is not None}

    # wf_id, dc_id = return_mongoid(workflow_id=wf_id, data_collection_id=dc_id)
    if df.is_empty():
        # Check if we're in a refresh context where we should load new data
        if kwargs.get("refresh", True):
            logger.info(
                f"Figure component {index}: Loading delta table for {wf_id}:{dc_id} (no pre-loaded df)"
            )
            # Validate that we have valid IDs before calling load_deltatable_lite
            if not wf_id or not dc_id:
                logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
                df = pl.DataFrame()  # Return empty DataFrame if IDs are missing
            else:
                df = load_deltatable_lite(ObjectId(wf_id), ObjectId(dc_id), TOKEN=TOKEN)
        else:
            # If refresh=False and df is empty, this means filters resulted in no data
            # Keep the empty DataFrame to properly reflect the filtered state
            logger.info(
                f"Figure component {index}: Using empty DataFrame from filters (shape: {df.shape}) - filters exclude all data"
            )
    else:
        logger.debug(f"Figure component {index}: Using pre-loaded DataFrame (shape: {df.shape})")

    # figure = render_figure(dict_kwargs, visu_type, df)

    # selected_point = df.sample(n=1).to_dicts()[0]
    # logger.info(f"Selected point: {selected_point}")
    # logger.info(f"Dict kwargs: {dict_kwargs}")
    # selected_point = {"x": selected_point[dict_kwargs["x"]], "y": selected_point[dict_kwargs["y"]]}

    figure = render_figure(dict_kwargs, visu_type, df)

    style_partial_data_displayed = {"display": "none"}
    cutoff = 100000
    if build_frame:
        if visu_type.lower() == "scatter" and df.shape[0] > cutoff:
            style_partial_data_displayed = {"display": "block"}

    partial_data_badge = dmc.Tooltip(
        children=dmc.Badge(
            "Partial data displayed",
            id={"type": "graph-partial-data-displayed", "index": index},
            style=style_partial_data_displayed,
            leftSection=DashIconify(
                icon="mdi:alert-circle",
                width=20,
            ),
            # sx={"paddingLeft": 0},
            size="lg",
            radius="xl",
            color="red",
            fullWidth=False,
        ),
        label=f"Scatter plots are only displayed with a maximum of {cutoff} points.",
        position="top",
        openDelay=500,
    )
    # dc_config["filter_applied"] = True
    filter_badge_style = {"display": "none"}
    if filter_applied:
        if visu_type.lower() == "scatter":
            filter_badge_style = {"display": "block"}
    logger.debug(f"Filter applied: {filter_applied}")
    logger.debug(f"Filter badge style: {filter_badge_style}")

    filter_badge = dmc.Tooltip(
        children=dmc.Badge(
            "Filter applied",
            id={"type": "graph-filter-badge", "index": index},
            style=filter_badge_style,
            leftSection=DashIconify(
                icon="mdi:filter",
                width=20,
            ),
            size="lg",
            radius="xl",
            color="orange",
            fullWidth=False,
        ),
        label="Data displayed in the plot was filtered.",
        position="top",
        openDelay=500,
    )

    row_badges = html.Div()
    if build_frame:
        row_badges = dbc.Row(
            dmc.Group(
                [partial_data_badge, filter_badge],
                grow=False,
                gap="xl",
                style={"margin-left": "12px"},
            )
        )

    figure_div = html.Div(
        [
            row_badges,
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


# Cache for parameter information to avoid re-processing docstrings
_param_info_cache = {}


def get_param_info(plotly_vizu_list):
    # Use caching to avoid re-processing docstrings on every call
    cache_key = tuple(func.__name__ for func in plotly_vizu_list)

    if cache_key in _param_info_cache:
        logger.debug("Figure: Using cached parameter info")
        return _param_info_cache[cache_key]

    logger.debug("Figure: Processing parameter info from docstrings")
    param_info = {}
    for func in plotly_vizu_list:
        param_info[func.__name__] = extract_info_from_docstring(func.__doc__)
        param_info[func.__name__] = process_json_from_docstring(param_info[func.__name__])

    _param_info_cache[cache_key] = param_info
    return param_info


# FIXME: find another way than inspect.signature to get the parameters, not stable enough for long term support
# TODO: export this to a separate file in order to be used in the frontend


def get_common_params(plotly_vizu_list):
    """
    Get the common parameters between a list of Plotly visualizations
    """
    # Iterate over the list of visualizations and get the parameters, then get the common ones
    if not plotly_vizu_list:
        return set(), []

    param_sets = [set(inspect.signature(func).parameters.keys()) for func in plotly_vizu_list]
    common_params = param_sets[0].intersection(*param_sets[1:]) if param_sets else set()
    # Sort the common parameters based on the order of the first visualization
    common_param_names = [p for p in list(common_params)]
    common_param_names.sort(
        key=lambda x: list(inspect.signature(plotly_vizu_list[0]).parameters).index(x)
    )
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
        common_params_tmp = (
            common_params.intersection(func_params.keys())
            if common_params
            else set(func_params.keys())
        )
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
