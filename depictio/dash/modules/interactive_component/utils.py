from dash import dcc, html
import polars as pl
import dash_mantine_components as dmc
import dash_bootstrap_components as dbc

from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.api.v1.configs.logging import logger


def build_interactive_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "input-body",
                    "index": index,
                },
                # style={
                #     "padding": "5px",  # Reduce padding inside the card body
                #     "display": "flex",
                #     "flexDirection": "column",
                #     "justifyContent": "center",
                #     "height": "100%",  # Make sure it fills the parent container
                # },
            ),
            # style={
            #     "width": "100%",
            #     "height": "100%",  # Ensure the card fills the container's height
            #     "padding": "0",  # Remove default padding
            #     "margin": "0",  # Remove default margin
            #     "boxShadow": "none",  # Optional: Remove shadow for a cleaner look
            #     # "border": "1px solid #ddd",  # Optional: Add a light border
            #     # "borderRadius": "4px",  # Optional: Slightly round the corners
            #     "border": "0px",  # Optional: Remove border
            # },
            id={
                "type": "interactive-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "input-body",
                    "index": index,
                },
                style={
                    "display": "flex",
                    "flexDirection": "column",
                    "overflow": "visible",  # Allow dropdown to overflow
                    "height": "100%",
                    "position": "relative",  # Ensure positioning context
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",
                "overflow": "visible",  # Allow dropdown to overflow
                "position": "relative",  # Ensure positioning context
            },
            id={
                "type": "interactive-component",
                "index": index,
            },
        )


def build_interactive(**kwargs):
    # def build_card(index, title, wf_id, dc_id, dc_config, column_name, column_type, aggregation, v, build_frame=False):
    index = kwargs.get("index")
    title = kwargs.get("title")  # Example of default parameter
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    column_name = kwargs.get("column_name")
    column_type = kwargs.get("column_type")
    interactive_component_type = kwargs.get("interactive_component_type")
    cols_json = kwargs.get("cols_json")
    value = kwargs.get("value", None)
    df = kwargs.get("df", None)
    build_frame = kwargs.get("build_frame", False)
    TOKEN = kwargs.get("access_token")
    stepper = kwargs.get("stepper", False)
    parent_index = kwargs.get("parent_index", None)

    logger.info(f"Interactive - kwargs: {kwargs}")

    if stepper:
        value_div_type = "interactive-component-value-tmp"
    else:
        value_div_type = "interactive-component-value"

    func_name = agg_functions[column_type]["input_methods"][interactive_component_type]["component"]

    # Common Store Component
    store_index = index.replace("-tmp", "")

    store_component = dcc.Store(
        id={"type": "stored-metadata-component", "index": str(store_index)},
        data={
            "component_type": "interactive",
            "interactive_component_type": interactive_component_type,
            "index": str(store_index),
            "title": title,
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
            "column_name": column_name,
            "column_type": column_type,
            "cols_json": cols_json,
            "value": value,
            "parent_index": parent_index,
        },
        storage_type="memory",
    )

    # Load the delta table & get the specs
    # if not isinstance(df, pl.DataFrame):
    df = load_deltatable_lite(wf_id, dc_id, TOKEN=TOKEN)

    # Handling different aggregation values

    ## Categorical data

    # If the aggregation value is Select, MultiSelect or SegmentedControl
    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        data = sorted(df[column_name].drop_nulls().unique())

        # WARNING: This is a temporary solution to avoid modifying dashboard data - the -tmp suffix is added to the id and removed once clicked on the btn-done D
        interactive_component = func_name(data=data, id={"type": value_div_type, "index": str(index)})

        # If the aggregation value is MultiSelect, make the component searchable and clearable
        if interactive_component_type == "MultiSelect":
            kwargs = {
                "searchable": True,
                "clearable": True,
                "clearSearchOnChange": False,
                "persistence_type": "local",
                "dropdownPosition": "bottom",
                "zIndex": 1000,
                # "position": "relative",
            }
            if not value:
                value = []
            kwargs.update({"value": value})
            interactive_component = func_name(
                data=data,
                id={"type": value_div_type, "index": str(index)},
                **kwargs,
            )

    # If the aggregation value is TextInput
    elif interactive_component_type == "TextInput":
        logger.info("TextInput")
        logger.info(f"Value: {value}")
        logger.info(f"Value type: {type(value)}")
        kwargs = {"persistence_type": "local"}
        if not value:
            value = ""
        logger.info(f"Value: {value}")
        logger.info(f"Value type: {type(value)}")
        kwargs.update({"value": value})
        interactive_component = func_name(
            placeholder="Your selected value",
            id={"type": value_div_type, "index": str(index)},
            **kwargs,
        )

    ## Numerical data

    # If the aggregation value is Slider or RangeSlider
    elif interactive_component_type in ["Slider", "RangeSlider"]:
        min_value, max_value = (
            cols_json[column_name]["specs"]["min"],
            cols_json[column_name]["specs"]["max"],
        )
        kwargs = {
            "min": min_value,
            "max": max_value,
            "id": {"type": value_div_type, "index": str(index)},
            "persistence_type": "local",
        }
        if interactive_component_type == "RangeSlider":
            if not value:
                value = [min_value, max_value]
            kwargs.update({"value": value})
        elif interactive_component_type == "Slider":
            if not value:
                value = min_value
        kwargs.update({"value": value})
        # If the number of unique values is less than 30, use the unique values as marks
        if interactive_component_type == "Slider":
            marks = {str(elem): str(elem) for elem in df[column_name].unique()} if df[column_name].n_unique() < 30 else {}
            kwargs.update({"marks": marks, "step": None, "included": False})
        interactive_component = func_name(**kwargs)

    # If no title is provided, use the aggregation value on the selected column
    if not title:
        card_title = html.H5(f"{interactive_component_type} on {column_name}")
    else:
        card_title = html.H5(f"{title}")

    logger.info(f"Interactive - store_component: {store_component}")

    new_interactive_component = html.Div([card_title, interactive_component, store_component])

    if not build_frame:
        return new_interactive_component
    else:
        return build_interactive_frame(index=index, children=new_interactive_component)


# List of all the possible aggregation methods for each data type and their corresponding input methods
# TODO: reference in the documentation


agg_functions = {
    "int64": {
        "title": "Integer",
        "input_methods": {
            "Slider": {
                "component": dcc.Slider,
                "description": "Single value slider: will return data equal to the selected value",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
                "description": "Two values slider: will return data between the two selected values",
            },
        },
    },
    "float64": {
        "title": "Floating Point",
        "input_methods": {
            "Slider": {
                "component": dcc.Slider,
                "description": "Single value slider: will return data equal to the selected value",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
                "description": "Two values slider: will return data between the two selected values",
            },
        },
    },
    "bool": {
        "title": "Boolean",
        "description": "Boolean values",
        "input_methods": {
            "Checkbox": {
                "component": dmc.Checkbox,
                "description": "Checkbox: True or False",
            },
            "Switch": {
                "component": dmc.Switch,
                "description": "Switch",
            },
        },
    },
    "datetime": {
        "title": "Datetime",
        "description": "Date and time values",
    },
    "timedelta": {
        "title": "Timedelta",
        "description": "Differences between two datetimes",
    },
    "category": {
        "title": "Category",
        "description": "Finite list of text values",
    },
    "object": {
        "title": "Object",
        "input_methods": {
            "TextInput": {
                "component": dmc.TextInput,
                "description": "Text input: will return corresponding data to the exact text or regular expression",
            },
            "Select": {
                "component": dmc.Select,
                "description": "Select: will return corresponding data to the selected value",
            },
            "MultiSelect": {
                "component": dmc.MultiSelect,
                "description": "MultiSelect: will return corresponding data to the selected values",
            },
            "SegmentedControl": {
                "component": dmc.SegmentedControl,
                "description": "SegmentedControl: will return corresponding data to the selected value",
            },
        },
        "description": "Text or mixed numeric or non-numeric values",
    },
}
