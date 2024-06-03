
from dash import dcc, html
import dash_mantine_components as dmc
import dash_bootstrap_components as dbc

from depictio.api.v1.deltatables_utils import load_deltatable_lite


def build_interactive_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "input-body",
                    "index": index,
                }
            ),
            style={"width": "100%"},
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
            ),
            style={"width": "100%"},
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
    build_frame = kwargs.get("build_frame", False)

    func_name = agg_functions[column_type]["input_methods"][interactive_component_type]["component"]

    # Common Store Component
    store_component = dcc.Store(
        id={"type": "stored-metadata-component", "index": str(index)},
        data={
            "component_type": "interactive",
            "interactive_component_type": interactive_component_type,
            "index": str(index),
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
            "column_name": column_name,
            "column_type": column_type,
            "cols_json": cols_json,
            "value": value,
        },
        storage_type="memory",
    )

    # Load the delta table & get the specs
    df = load_deltatable_lite(wf_id, dc_id)

    # Handling different aggregation values

    ## Categorical data

    # If the aggregation value is Select, MultiSelect or SegmentedControl
    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        data = sorted(df[column_name].drop_nans().unique())

        interactive_component = func_name(data=data, id={"type": "interactive-component-value", "index": str(index), "persistence_type": "local"})

        # If the aggregation value is MultiSelect, make the component searchable and clearable
        if interactive_component_type == "MultiSelect":

            kwargs = {"searchable": True, "clearable": True, "clearSearchOnChange": False, "persistence_type": "local"}
            if not value:
                value = []
            kwargs.update({"value": value})
            interactive_component = func_name(
                data=data,
                id={"type": "interactive-component-value", "index": str(index)},
                **kwargs,
            )

    # If the aggregation value is TextInput
    elif interactive_component_type == "TextInput":
        kwargs = ({"persistence_type": "local"},)
        if not value:
            value = ""
        kwargs.update({"value": value})
        interactive_component = func_name(
            placeholder="Your selected value",
            id={"type": "interactive-component-value", "index": str(index)},
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
            "id": {"type": "interactive-component-value", "index": str(index)},
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
            marks = {str(elem): str(elem) for elem in df[column_name].unique()} if df[column_name].nunique() < 30 else {}
            kwargs.update({"marks": marks, "step": None, "included": False})
        interactive_component = func_name(**kwargs)

    # If no title is provided, use the aggregation value on the selected column
    if not title:
        card_title = html.H5(f"{interactive_component_type} on {column_name}")
    else:
        card_title = html.H5(f"{title}")

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
                "description": "Single value slider",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
                "description": "Two values slider",
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
    },
}
