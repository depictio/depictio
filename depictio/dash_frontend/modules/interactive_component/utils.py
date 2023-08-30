import sys

sys.path.append("/Users/tweber/Gits/depictio")

from dash import dcc
import dash_mantine_components as dmc


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
    },
}
