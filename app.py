# Import necessary libraries
import numpy as np
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash
import dash_bootstrap_components as dbc
import dash_draggable
import dash_mantine_components as dmc
import inspect
import pandas as pd
import plotly.express as px
import re
from dash_iconify import DashIconify
import ast

from config import external_stylesheets

app = dash.Dash(
    __name__,
    external_stylesheets=external_stylesheets,
    suppress_callback_exceptions=True,
)


from utils import (
    get_common_params,
    get_specific_params,
    extract_info_from_docstring,
    process_json_from_docstring,
    get_param_info,
)
from utils import (
    plotly_vizu_list,
    plotly_vizu_dict,
    common_params,
    common_params_names,
    specific_params,
    param_info,
    base_elements,
    allowed_types,
    plotly_bootstrap_mapping,
    secondary_common_params,
    secondary_common_params_lite,
)

from utils import agg_functions

from utils import create_initial_figure, load_data

# Data

df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
)
# print(df)


backend_components = html.Div(
    [
        dcc.Interval(
            id="interval",
            interval=2000,  # Save input value every 1 second
            n_intervals=0,
        ),
        # dcc.Store(id="stored-year", storage_type="memory", data=init_year),
        # dcc.Store(id="stored-children", storage_type="memory", data=init_children),
        # dcc.Store(id="stored-layout", storage_type="memory", data=init_layout),
        dcc.Store(id="stored-children", storage_type="memory"),
        dcc.Store(id="stored-layout", storage_type="memory"),
    ]
)

header = html.Div(
    [
        html.H1("Depictio"),
        dmc.Button(
            "Add new component",
            id="add-button",
            size="lg",
            radius="xl",
            variant="gradient",
            n_clicks=0,
        ),
        dbc.Checklist(
            id="edit-dashboard-mode-button",
            # color="secondary",
            style={"margin-left": "20px", "font-size": "22px"},
            # size="lg",
            # n_clicks=0,
            options=[
                {"label": "Edit dashboard", "value": 0},
            ],
            value=[0],
            switch=True,
        ),
        dcc.Store(
            id="stored-edit-dashboard-mode-button",
            storage_type="memory",
            data={"count": 0},
        ),
    ],
)


init_layout = dict()
init_children = list()
app.layout = dbc.Container(
    [
        html.Div(
            [
                backend_components,
                header,
                dash_draggable.ResponsiveGridLayout(
                    id="draggable",
                    clearSavedLayout=True,
                    layouts=init_layout,
                    children=init_children,
                    isDraggable=True,
                    isResizable=True,
                ),
            ],
        ),
    ],
    fluid=False,
)


@app.callback(
    Output("collapse", "is_open"),
    [Input("collapse-button", "n_clicks")],
    [State("collapse", "is_open")],
)
def toggle_collapse(n, is_open):
    if n:
        return not is_open
    return is_open


@app.callback(
    Output({"type": "modal", "index": MATCH}, "is_open"),
    [Input({"type": "btn-done", "index": MATCH}, "n_clicks")],
    prevent_initial_call=True,
)
def close_modal(n_clicks):
    if n_clicks > 0:
        return False
    return True


# @app.callback(
#     [Output("draggable", "children"), Output("draggable", "layouts")],
#     [Input("add-button", "n_clicks")],
#     [State("draggable", "children"), State("draggable", "layouts")],
#     prevent_initial_call=True,
# )
# def add_new_div(n, children, layouts):

#     print("add_new_div")
#     # print(app._callback_list)

#     print("index: {}".format(n))
#     new_plot_id = f"graph-{n}"
#     print(new_plot_id)

#     new_element = html.Div(
#         [
#             html.Div(id={"type": "add-content", "index": n}),
#             dbc.Modal(
#                 id={"type": "modal", "index": n},
#                 children=[
#                     dbc.ModalHeader(html.H5("Design your new dashboard component")),
#                     dbc.ModalBody(
#                         [
#                             dbc.Row(
#                                 [
#                                     dbc.Col(
#                                         dmc.Button(
#                                             "Figure",
#                                             id={
#                                                 "type": "btn-option",
#                                                 "index": n,
#                                                 "value": "Figure",
#                                             },
#                                             n_clicks=0,
#                                             style={
#                                                 "display": "inline-block",
#                                                 "width": "250px",
#                                                 "height": "100px",
#                                             },
#                                             size="xl",
#                                             color="grape",
#                                             leftIcon=DashIconify(icon="mdi:graph-box"),
#                                         )
#                                     ),
#                                     dbc.Col(
#                                         dmc.Button(
#                                             "Card",
#                                             id={
#                                                 "type": "btn-option",
#                                                 "index": n,
#                                                 "value": "Card",
#                                             },
#                                             n_clicks=0,
#                                             style={
#                                                 "display": "inline-block",
#                                                 "width": "250px",
#                                                 "height": "100px",
#                                             },
#                                             size="xl",
#                                             color="violet",
#                                             leftIcon=DashIconify(
#                                                 icon="formkit:number", color="white"
#                                             ),
#                                         )
#                                     ),
#                                     dbc.Col(
#                                         dmc.Button(
#                                             "Interactive",
#                                             id={
#                                                 "type": "btn-option",
#                                                 "index": n,
#                                                 "value": "Interactive",
#                                             },
#                                             n_clicks=0,
#                                             style={
#                                                 "display": "inline-block",
#                                                 "width": "250px",
#                                                 "height": "100px",
#                                             },
#                                             size="xl",
#                                             color="indigo",
#                                             leftIcon=DashIconify(
#                                                 icon="bx:slider-alt", color="white"
#                                             ),
#                                         )
#                                     ),
#                                 ]
#                             ),
#                         ],
#                         id={"type": "modal-body", "index": n},
#                         style={
#                             "display": "flex",
#                             "justify-content": "center",
#                             "align-items": "center",
#                             "flex-direction": "column",
#                             "height": "100%",
#                             "width": "100%",
#                         },
#                     ),
#                 ],
#                 is_open=True,
#                 size="xl",
#                 backdrop=False,
#                 style={
#                     "height": "100%",
#                     "width": "100%",
#                     # "display": "flex",
#                     # "flex-direction": "column",
#                     # "flex-grow": "0",
#                 },
#             ),
#         ],
#         id=new_plot_id,
#     )

#     children.append(new_element)
#     new_layout_item = {
#         "i": f"{new_plot_id}",
#         "x": 10 * ((len(children) + 1) % 2),
#         "y": n * 10,
#         "w": 6,
#         "h": 5,
#     }

#     # Update the layouts property for both 'lg' and 'sm' sizes
#     updated_layouts = {}
#     for size in ["lg", "sm"]:
#         if size not in layouts:
#             layouts[size] = []
#         updated_layouts[size] = layouts[size] + [new_layout_item]
#     return children, updated_layouts


# Define the callback to update the specific parameters dropdowns
@dash.callback(
    [
        Output({"type": "collapse", "index": MATCH}, "children"),
    ],
    [
        Input({"type": "edit-button", "index": MATCH}, "n_clicks"),
        Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
    ],
    [State({"type": "edit-button", "index": MATCH}, "id")],
    # prevent_initial_call=True,
)
def update_specific_params(n_clicks, visu_type, edit_button_id):
    # print("update_specific_params")
    # print(app._callback_list)

    # print(n_clicks, edit_button_id)

    value = visu_type.lower()
    # value = "scatter"
    if value is not None:
        specific_params_options = [
            {"label": param_name, "value": param_name}
            for param_name in specific_params[value]
        ]

        specific_params_dropdowns = list()
        for e in specific_params[value]:
            processed_type_tmp = param_info[value][e]["processed_type"]
            allowed_types = ["str", "int", "float", "column"]
            if processed_type_tmp in allowed_types:
                input_fct = plotly_bootstrap_mapping[processed_type_tmp]
                tmp_options = dict()

                if processed_type_tmp == "column":
                    tmp_options = {
                        "options": list(df.columns),
                        "value": None,
                        "persistence": True,
                        "id": {
                            "type": f"tmp-{e}",
                            "index": edit_button_id["index"],
                        },
                    }
                if processed_type_tmp == "str":
                    tmp_options = {
                        "placeholder": e,
                        "type": "text",
                        "persistence": True,
                        "id": {
                            "type": f"tmp-{e}",
                            "index": edit_button_id["index"],
                        },
                        "value": None,
                    }
                if processed_type_tmp in ["int", "float"]:
                    tmp_options = {
                        "placeholder": e,
                        "type": "number",
                        "persistence": True,
                        "id": {
                            "type": f"tmp-{e}",
                            "index": edit_button_id["index"],
                        },
                        "value": None,
                    }
                input_fct_with_params = input_fct(**tmp_options)
                accordion_item = dbc.AccordionItem(
                    [dbc.Row(input_fct_with_params)],
                    className="my-2",
                    title=e,
                )
                specific_params_dropdowns.append(accordion_item)

        secondary_common_params_dropdowns = list()
        primary_common_params_dropdowns = list()
        for e in secondary_common_params:
            # print(e)
            processed_type_tmp = param_info[value][e]["processed_type"]
            # allowed_types = ["str", "int", "float", "column", "list"]
            allowed_types = ["str", "int", "float", "column"]
            if processed_type_tmp in allowed_types:
                input_fct = plotly_bootstrap_mapping[processed_type_tmp]
                tmp_options = dict()

                if processed_type_tmp == "column":
                    tmp_options = {
                        "options": list(df.columns),
                        "value": None,
                        "persistence": True,
                        "style": {"width": "100%"},
                        "id": {
                            "type": f"tmp-{e}",
                            "index": edit_button_id["index"],
                        },
                    }
                if processed_type_tmp == "str":
                    tmp_options = {
                        "placeholder": e,
                        "type": "text",
                        "persistence": True,
                        "id": {
                            "type": f"tmp-{e}",
                            "index": edit_button_id["index"],
                        },
                        "value": None,
                    }
                if processed_type_tmp in ["int", "float"]:
                    tmp_options = {
                        "placeholder": e,
                        "type": "number",
                        "persistence": True,
                        "id": {
                            "type": f"tmp-{e}",
                            "index": edit_button_id["index"],
                        },
                        "value": None,
                    }

                # if processed_type_tmp is "list":
                #     tmp_options = {
                #         # "options": list(df.columns),
                #         # "value": None,
                #         "persistence": True,
                #         "id": {
                #             "type": f"tmp-{e}",
                #             "index": edit_button_id["index"],
                #         },
                #     }

                input_fct_with_params = input_fct(**tmp_options)

                # input_fct_with_params = dmc.Tooltip(
                #     children=[input_fct(**tmp_options)], label="TEST"
                # )
                accordion_item = dbc.AccordionItem(
                    [dbc.Row(input_fct_with_params, style={"width": "100%"})],
                    className="my-2",
                    title=e,
                )
                if e not in base_elements:
                    secondary_common_params_dropdowns.append(accordion_item)
                else:
                    primary_common_params_dropdowns.append(accordion_item)

        # print(secondary_common_params_dropdowns)

        primary_common_params_layout = [
            dbc.Accordion(
                dbc.AccordionItem(
                    [
                        dbc.Accordion(
                            primary_common_params_dropdowns,
                            flush=True,
                            always_open=True,
                            persistence_type="session",
                            persistence=True,
                            id="accordion-sec-common",
                        ),
                    ],
                    title="Base parameters",
                ),
                start_collapsed=True,
            )
        ]

        secondary_common_params_layout = [
            dbc.Accordion(
                dbc.AccordionItem(
                    [
                        dbc.Accordion(
                            secondary_common_params_dropdowns,
                            flush=True,
                            always_open=True,
                            persistence_type="session",
                            persistence=True,
                            id="accordion-sec-common",
                        ),
                    ],
                    title="Generic parameters",
                ),
                start_collapsed=True,
            )
        ]
        dynamic_specific_params_layout = [
            dbc.Accordion(
                dbc.AccordionItem(
                    [
                        dbc.Accordion(
                            specific_params_dropdowns,
                            flush=True,
                            always_open=True,
                            persistence_type="session",
                            persistence=True,
                            id="accordion",
                        ),
                    ],
                    title=f"{value.capitalize()} specific parameters",
                ),
                start_collapsed=True,
            )
        ]
        return [
            primary_common_params_layout
            + secondary_common_params_layout
            + dynamic_specific_params_layout
        ]
    else:
        return html.Div()


def generate_dropdown_ids(value):
    specific_param_ids = [
        f"{value}-{param_name}" for param_name in specific_params[value]
    ]
    secondary_param_ids = [f"{value}-{e}" for e in secondary_common_params]

    return secondary_param_ids + specific_param_ids


@app.callback(
    Output(
        {
            "type": "collapse",
            "index": MATCH,
        },
        "is_open",
    ),
    [
        Input(
            {
                "type": "edit-button",
                "index": MATCH,
            },
            "n_clicks",
        )
    ],
    [
        State(
            {
                "type": "collapse",
                "index": MATCH,
            },
            "is_open",
        )
    ],
    prevent_initial_call=True,
)
def toggle_collapse(n, is_open):
    # print(n, is_open, n % 2 == 0)
    if n % 2 == 0:
        return False
    else:
        return True


@app.callback(
    Output({"type": "dict_kwargs", "index": MATCH}, "value"),
    [
        Input({"type": "collapse", "index": MATCH}, "children"),
        Input("interval", "n_intervals"),
    ],
    [State({"type": "dict_kwargs", "index": MATCH}, "data")],
    # prevent_initial_call=True,
)
def get_values_to_generate_kwargs(*args):
    # print("get_values_to_generate_kwargs")
    # print(args)
    # print("\n")

    children = args[0]
    # print(children)
    # visu_type = args[1]
    # print(children)
    existing_kwargs = args[-1]

    accordion_primary_common_params_args = dict()
    accordion_secondary_common_params_args = dict()
    specific_params_args = dict()
    # print(existing_kwargs)
    # print(children)

    # l[0]["props"]["children"]["props"]["children"][0]["props"]["children"][0]

    if children:
        # accordion_secondary_common_params = children[0]["props"]["children"]["props"]["children"]
        accordion_primary_common_params = children[0]["props"]["children"]["props"][
            "children"
        ][0]["props"]["children"]

        # accordion_secondary_common_params = children[1]["props"]["children"]
        if accordion_primary_common_params:
            # print("TOTO")
            accordion_primary_common_params = [
                param["props"]["children"][0]["props"]["children"]
                for param in accordion_primary_common_params
            ]

            accordion_primary_common_params_args = {
                elem["props"]["id"]["type"].replace("tmp-", ""): elem["props"]["value"]
                for elem in accordion_primary_common_params
            }

            # print(accordion_primary_common_params_args)
            # print(accordion_primary_common_params)

            # print(accordion_secondary_common_params)
            # return accordion_secondary_common_params_args
        accordion_secondary_common_params = children[1]["props"]["children"]["props"][
            "children"
        ][0]["props"]["children"]

        # accordion_secondary_common_params = children[1]["props"]["children"]
        if accordion_secondary_common_params:
            # print("TOTO")
            accordion_secondary_common_params = [
                param["props"]["children"][0]["props"]["children"]
                for param in accordion_secondary_common_params
            ]

            accordion_secondary_common_params_args = {
                elem["props"]["id"]["type"].replace("tmp-", ""): elem["props"]["value"]
                for elem in accordion_secondary_common_params
            }
            # print(accordion_secondary_common_params_args)
            # if not {
            #     k: v
            #     for k, v in accordion_secondary_common_params_args.items()
            #     if v is not None
            # }:
            #     accordion_secondary_common_params_args = {
            #         **accordion_secondary_common_params_args,
            #         **existing_kwargs,
            #     }
            # print(accordion_secondary_common_params_args)
            # print(accordion_secondary_common_params)
            # return accordion_secondary_common_params_args
        specific_params = children[2]["props"]["children"]["props"]["children"][0][
            "props"
        ]["children"]

        # accordion_secondary_common_params = children[1]["props"]["children"]
        if specific_params:
            # print("specific_params")
            specific_params = [
                param["props"]["children"][0]["props"]["children"]
                for param in specific_params
            ]

            specific_params_args = {
                elem["props"]["id"]["type"].replace("tmp-", ""): elem["props"]["value"]
                for elem in specific_params
            }
            # print(specific_params_args)

        return_dict = dict(
            **specific_params_args,
            **accordion_secondary_common_params_args,
            **accordion_primary_common_params_args,
        )
        return_dict = {k: v for k, v in return_dict.items() if v is not None}

        if not return_dict:
            return_dict = {
                **return_dict,
                **existing_kwargs,
            }
            # print("BLANK DICT, ROLLBACK TO EXISTING KWARGS")
            # print(return_dict)

        if return_dict:
            # print("RETURNING DICT")
            # print(return_dict)
            # print(accordion_secondary_common_params)
            return return_dict
        else:
            # print("EXISTING KWARGS")
            return existing_kwargs

        # else:
        #     return existing_kwargs
    else:
        return existing_kwargs

        # accordion_specific_params = args[0][3]


@app.callback(
    Output({"type": "graph", "index": MATCH}, "figure"),
    [
        Input({"type": "dict_kwargs", "index": MATCH}, "value"),
        Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        [
            Input({"type": f"tmp-{e}", "index": MATCH}, "children")
            for e in secondary_common_params_lite
        ],
        Input("interval", "n_intervals"),
    ],
    # prevent_initial_call=True,
)
def update_figure(*args):
    dict_kwargs = args[0]
    visu_type = args[1]
    # print("update figure")
    # print(dict_kwargs)
    # print(visu_type)
    # # print(app._callback_list)

    # print(dict_kwargs)
    dict_kwargs = {k: v for k, v in dict_kwargs.items() if v is not None}
    # print(dict_kwargs)
    if dict_kwargs:
        figure = plotly_vizu_dict[visu_type.lower()](df, **dict_kwargs)
        # figure = px.scatter(df, **dict_kwargs)
        # print(figure)
        # figure.update_layout(uirevision=1)

        return figure
    # print("\n")

    # accordion_specific_params = args[0][3]


@app.callback(
    Output({"type": "modal-body", "index": MATCH}, "children"),
    [Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks")],
    [
        State({"type": "btn-option", "index": MATCH, "value": ALL}, "id"),
    ],
    prevent_initial_call=True,
)
def update_modal(n_clicks, ids):
    # print("update_modal")
    # print(n_clicks, ids)
    # print("\n")

    import plotly.graph_objects as go

    # visualization_type = "scatter"
    for n, id in zip(n_clicks, ids):
        # print(n, id)
        if n > 0:
            if id["value"] == "Figure":
                # plot_func = plotly_vizu_dict[visualization_type]
                plot_kwargs = dict(x="lifeExp", y="pop", color="continent")
                # plot_kwargs = dict(
                #     x=df.columns[0], y=df.columns[1], color=df.columns[2]
                # )
                # plot_kwargs = dict()

                figure = go.Figure()

                # figure = plot_func(
                #     df,
                #     **plot_kwargs,
                # )

                return [
                    dbc.Row(
                        [
                            dbc.Col(
                                dmc.Select(
                                    label=html.H4(
                                        [
                                            DashIconify(
                                                icon="flat-color-icons:workflow"
                                            ),
                                            "Workflow selection",
                                        ]
                                    ),
                                    data=["Test1", "Test2"],
                                )
                            ),
                            dbc.Col(
                                dmc.Select(
                                    label=html.H4(
                                        [
                                            DashIconify(icon="bxs:data"),
                                            "Data collection selection",
                                        ]
                                    ),
                                    data=["Test3", "Test4"],
                                )
                            ),
                        ],
                        style={"width": "80%"},
                    ),
                    html.Br(),
                    # html.Hr(),
                    dbc.Row(
                        [
                            html.H5("Select your visualisation type"),
                            dmc.SegmentedControl(
                                data=[
                                    e.capitalize()
                                    for e in sorted(plotly_vizu_dict.keys())
                                ],
                                orientation="horizontal",
                                size="lg",
                                radius="lg",
                                id={
                                    "type": "segmented-control-visu-graph",
                                    "index": id["index"],
                                },
                                persistence=True,
                                persistence_type="session",
                                value=[
                                    e.capitalize()
                                    for e in sorted(plotly_vizu_dict.keys())
                                ][-1],
                            ),
                        ],
                        style={"height": "5%"},
                    ),
                    html.Br(),
                    dbc.Row(
                        [
                            dbc.Col(
                                dcc.Graph(
                                    # figure=figure,
                                    id={"type": "graph", "index": id["index"]},
                                    config={"editable": True},
                                ),
                                width="auto",
                            ),
                            # dbc.Col(width=0.5),
                            dbc.Col(
                                [
                                    html.Br(),
                                    html.Div(
                                        children=[
                                            dmc.Button(
                                                "Edit figure",
                                                id={
                                                    "type": "edit-button",
                                                    "index": id["index"],
                                                },
                                                n_clicks=0,
                                                # size="lg",
                                                style={"align": "center"},
                                            ),
                                            html.Hr(),
                                            dbc.Collapse(
                                                id={
                                                    "type": "collapse",
                                                    "index": id["index"],
                                                },
                                                is_open=False,
                                            ),
                                        ]
                                    ),
                                ],
                                width="auto",
                                style={"align": "center"},
                            ),
                        ]
                    ),
                    html.Br(),
                    dmc.Button(
                        "Done",
                        id={"type": "btn-done", "index": id["index"]},
                        n_clicks=0,
                        style={"display": "block"},
                    ),
                    dcc.Store(
                        id={"type": "dict_kwargs", "index": id["index"]},
                        data=plot_kwargs,
                        storage_type="memory",
                    ),
                ]
            elif id["value"] == "Card":
                # print("Card")
                return [
                    dbc.Row(
                        [
                            dbc.Col(
                                dmc.Select(
                                    label=html.H4(
                                        [
                                            DashIconify(
                                                icon="flat-color-icons:workflow"
                                            ),
                                            "Workflow selection",
                                        ]
                                    ),
                                    data=["Test1", "Test2"],
                                )
                            ),
                            dbc.Col(
                                dmc.Select(
                                    label=html.H4(
                                        [
                                            DashIconify(icon="bxs:data"),
                                            "Data collection selection",
                                        ]
                                    ),
                                    data=["Test3", "Test4"],
                                )
                            ),
                        ],
                        style={"width": "80%"},
                    ),
                    html.Br(),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.H5("Card edit menu"),
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                dmc.TextInput(
                                                    label="Card title",
                                                    id={
                                                        "type": "card-input",
                                                        "index": id["index"],
                                                    },
                                                ),
                                                dmc.Select(
                                                    label="Select your column",
                                                    id={
                                                        "type": "card-dropdown-column",
                                                        "index": id["index"],
                                                    },
                                                    data=[
                                                        {"label": e, "value": e}
                                                        for e in df.columns
                                                    ],
                                                    value=None,
                                                ),
                                                dmc.Select(
                                                    label="Select your aggregation method",
                                                    id={
                                                        "type": "card-dropdown-aggregation",
                                                        "index": id["index"],
                                                    },
                                                    value=None,
                                                ),
                                                html.Div(
                                                    id={
                                                        # "type": "debug-print",
                                                        "index": id["index"],
                                                    },
                                                ),
                                            ],
                                        ),
                                        id={
                                            "type": "card",
                                            "index": id["index"],
                                        },
                                        style={"width": "100%"},
                                    ),
                                ],
                                width="auto",
                            ),
                            dbc.Col(
                                [
                                    html.H5("Resulting card"),
                                    dbc.Card(
                                        dbc.CardBody(
                                            id={
                                                "type": "card-body",
                                                "index": id["index"],
                                            }
                                        ),
                                        style={"width": "100%"},
                                    ),
                                ],
                                width="auto",
                            ),
                        ]
                    ),
                    html.Hr(),
                    dbc.Row(
                        dmc.Button(
                            "Done",
                            id={"type": "btn-done", "index": id["index"]},
                            n_clicks=0,
                            style={"display": "block"},
                        )
                    ),
                ]
            elif id["value"] == "Interactive":
                # print("Interactive")
                return [
                    dbc.Row(
                        [
                            dbc.Col(
                                dmc.Select(
                                    label=html.H4(
                                        [
                                            DashIconify(
                                                icon="flat-color-icons:workflow"
                                            ),
                                            "Workflow selection",
                                        ]
                                    ),
                                    data=["Test1", "Test2"],
                                )
                            ),
                            dbc.Col(
                                dmc.Select(
                                    label=html.H4(
                                        [
                                            DashIconify(icon="bxs:data"),
                                            "Data collection selection",
                                        ]
                                    ),
                                    data=["Test3", "Test4"],
                                )
                            ),
                        ],
                        style={"width": "80%"},
                    ),
                    html.Br(),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.H5("Card edit menu"),
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                dmc.TextInput(
                                                    label="Card title",
                                                    id={
                                                        "type": "input-title",
                                                        "index": id["index"],
                                                    },
                                                ),
                                                dmc.Select(
                                                    label="Select your column",
                                                    id={
                                                        "type": "input-dropdown-column",
                                                        "index": id["index"],
                                                    },
                                                    data=[
                                                        {"label": e, "value": e}
                                                        for e in df.columns
                                                    ],
                                                    value=None,
                                                ),
                                                dmc.Select(
                                                    label="Select your interactive component",
                                                    id={
                                                        "type": "input-dropdown-method",
                                                        "index": id["index"],
                                                    },
                                                    value=None,
                                                ),
                                            ],
                                        ),
                                        id={
                                            "type": "input",
                                            "index": id["index"],
                                        },
                                    ),
                                ],
                                width="auto",
                            ),
                            dbc.Col(
                                [
                                    html.H5("Resulting card"),
                                    dbc.Card(
                                        dbc.CardBody(
                                            id={
                                                "type": "input-body",
                                                "index": id["index"],
                                            },
                                            style={"width": "100%"},
                                        ),
                                        style={"width": "600px"},
                                    ),
                                ],
                                width="auto",
                            ),
                        ]
                    ),
                    html.Hr(),
                    dbc.Row(
                        dmc.Button(
                            "Done",
                            id={"type": "btn-done", "index": id["index"]},
                            n_clicks=0,
                            style={"display": "block"},
                        )
                    ),
                ]
    return []


# Callback to update aggregation dropdown options based on the selected column
@app.callback(
    Output({"type": "input-dropdown-method", "index": MATCH}, "data"),
    Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
    prevent_initial_call=True,
)
def update_aggregation_options(column_value):
    if column_value is None:
        return []

    # Get the type of the selected column
    column_type = df[column_value].dtype
    # print(column_value, column_type, type(column_type))

    if column_type in ["object", "category"]:
        nb_unique = df[column_value].nunique()
    else:
        nb_unique = 0

    # Get the aggregation functions available for the selected column type
    agg_functions_tmp_methods = agg_functions[str(column_type)]["input_methods"]
    # print(agg_functions_tmp_methods)

    # Create a list of options for the dropdown
    options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]
    # print(options)

    if nb_unique > 5:
        options = [e for e in options if e["label"] != "SegmentedControl"]

    return options


# Callback to reset aggregation dropdown value based on the selected column
@app.callback(
    Output({"type": "input-dropdown-method", "index": MATCH}, "value"),
    Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
    prevent_initial_call=True,
)
def reset_aggregation_value(column_value):
    return None


# Callback to update card body based on the selected column and aggregation
@app.callback(
    Output({"type": "input-body", "index": MATCH}, "children"),
    [
        Input({"type": "input-title", "index": MATCH}, "value"),
        Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
        Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
        # Input("interval", "n_intervals"),
    ],
    prevent_initial_call=True,
)
def update_card_body(input_value, column_value, aggregation_value):
    if input_value is None or column_value is None or aggregation_value is None:
        return []

    # Get the type of the selected column
    column_type = str(df[column_value].dtype)

    # Get the pandas function for the selected aggregation
    func_name = agg_functions[column_type]["input_methods"][aggregation_value][
        "component"
    ]
    # print(func_name)

    # if callable(func_name):
    #     # If the function is a lambda function
    #     v = func_name(df[column_value])
    # else:
    #     # If the function is a pandas function
    #     v = getattr(df[column_value], func_name)()
    #     print(v, type(v))
    #     if type(v) is pd.core.series.Series and func_name != "mode":
    #         v = v.iloc[0]
    #     elif type(v) is pd.core.series.Series and func_name == "mode":
    #         if v.shape[0] == df[column_value].nunique():
    #             v = "All values are represented equally"
    #         else:
    #             v = v.iloc[0]

    # if type(v) is np.float64:
    #     v = round(v, 2)
    # v = "{:,.2f}".format(round(v, 2))
    # v = "{:,.2f}".format(round(v, 2)).replace(",", " ")

    card_title = html.H5(f"{input_value}")

    if aggregation_value in ["Select", "MultiSelect", "SegmentedControl"]:
        data = df[column_value].unique()

        new_card_body = [card_title, func_name(data=data)]
        # print(new_card_body)

        return new_card_body
    elif aggregation_value in ["TextInput"]:
        new_card_body = [
            card_title,
            func_name(placeholder="Your selected value"),
        ]
        # print(new_card_body)

        return new_card_body

    elif aggregation_value in ["Slider", "RangeSlider"]:
        min_value = df[column_value].min()
        max_value = df[column_value].max()
        kwargs = dict()
        if aggregation_value == "Slider":
            marks = dict()
            if df[column_value].nunique() < 30:
                marks = {str(elem): str(elem) for elem in df[column_value].unique()}
            step = None
            included = False
            kwargs = dict(marks=marks, step=step, included=included)

        new_card_body = [card_title, func_name(min=min_value, max=max_value, **kwargs)]
        # print(new_card_body)
        return new_card_body


# Callback to update aggregation dropdown options based on the selected column
@app.callback(
    Output({"type": "card-dropdown-aggregation", "index": MATCH}, "data"),
    Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
    prevent_initial_call=True,
)
def update_aggregation_options(column_value):
    if column_value is None:
        return []

    # Get the type of the selected column
    column_type = df[column_value].dtype
    # print(column_value, column_type, type(column_type))

    # Get the aggregation functions available for the selected column type
    agg_functions_tmp_methods = agg_functions[str(column_type)]["card_methods"]
    # print(agg_functions_tmp_methods)

    # Create a list of options for the dropdown
    options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]
    # print(options)

    return options


# Callback to reset aggregation dropdown value based on the selected column
@app.callback(
    Output({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
    Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
    prevent_initial_call=True,
)
def reset_aggregation_value(column_value):
    return None


# Callback to update card body based on the selected column and aggregation
@app.callback(
    Output({"type": "card-body", "index": MATCH}, "children"),
    [
        Input({"type": "card-input", "index": MATCH}, "value"),
        Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
        Input({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
        # Input("interval", "n_intervals"),
    ],
    prevent_initial_call=True,
)
def update_card_body(input_value, column_value, aggregation_value):
    if input_value is None or column_value is None or aggregation_value is None:
        return []

    # Get the type of the selected column
    column_type = str(df[column_value].dtype)

    # Get the pandas function for the selected aggregation
    func_name = agg_functions[column_type]["card_methods"][aggregation_value]["pandas"]

    if callable(func_name):
        # If the function is a lambda function
        v = func_name(df[column_value])
    else:
        # If the function is a pandas function
        v = getattr(df[column_value], func_name)()
        # print(v, type(v))
        if type(v) is pd.core.series.Series and func_name != "mode":
            v = v.iloc[0]
        elif type(v) is pd.core.series.Series and func_name == "mode":
            if v.shape[0] == df[column_value].nunique():
                v = "All values are represented equally"
            else:
                v = v.iloc[0]

    if type(v) is np.float64:
        v = round(v, 2)
        # v = "{:,.2f}".format(round(v, 2))
        # v = "{:,.2f}".format(round(v, 2)).replace(",", " ")

    new_card_body = [html.H5(f"{input_value}"), html.P(f"{v}")]

    return new_card_body


def find_ids_recursive(dash_component):
    """
    Recursively search for ids in the properties of a Dash component.
    :param dash_component: The Dash component to search in
    :return: A list of all ids found
    """
    if isinstance(dash_component, dict) and "props" in dash_component:
        # print(f"Inspecting {dash_component.get('type')}")
        if "id" in dash_component["props"]:
            id = dash_component["props"]["id"]
            # print(f"Found id: {id}")
            yield id
        if "children" in dash_component["props"]:
            children = dash_component["props"]["children"]
            if isinstance(children, list):
                for child in children:
                    yield from find_ids_recursive(child)
            elif isinstance(children, dict):
                yield from find_ids_recursive(children)


@app.callback(
    Output({"type": "add-content", "index": MATCH}, "children"),
    [
        Input({"type": "btn-done", "index": MATCH}, "n_clicks"),
    ],
    [
        State({"type": "modal-body", "index": MATCH}, "children"),
        State({"type": "btn-done", "index": MATCH}, "id"),
    ],
    # prevent_initial_call=True,
)
def update_button(n_clicks, children, btn_id):
    # print("update_button")
    # children = [children[4]]
    # print(children)

    btn_index = btn_id["index"]
    # print(n_clicks, btn_id)
    # print([sub_e for e in children for sub_e in list(find_ids_recursive(e))])
    # print("\n")

    # print(f"Inspecting children:")
    box_type = [sub_e for e in children for sub_e in list(find_ids_recursive(e))][0][
        "type"
    ]
    # print(children)
    # print(box_type)
    # print(f"Found ids: {all_ids}")

    div_index = 0 if box_type == "segmented-control-visu-graph" else 2
    if box_type:
        if box_type == "segmented-control-visu-graph":
            children = [children[4]]
            child = children[div_index]["props"]["children"][0]["props"][
                "children"
            ]  # Figure
            child["props"]["id"]["type"] = (
                "updated-" + child["props"]["id"]["type"]
            )  # Figure

            # print(child)
            # print("OK")
        elif box_type == "card":
            # print(children)
            child = children[div_index]["props"]["children"][1]["props"]["children"][
                1
            ]  # Card
            # print(child)
            child["props"]["children"]["props"]["id"]["type"] = (
                "updated-" + child["props"]["children"]["props"]["id"]["type"]
            )  # Figure
        elif box_type == "input":
            # print(children)
            child = children[div_index]["props"]["children"][1]["props"]["children"][
                1
            ]  # Card
            # print(child)
            child["props"]["children"]["props"]["id"]["type"] = (
                "updated-" + child["props"]["children"]["props"]["id"]["type"]
            )  # Figure
        # elif box_type == "input":
        #     child = children[0]["props"]["children"][1]["props"]["children"] # Card
        #     print(child)
        #     child["props"]["children"]["props"]["id"]["type"] = "updated-" + child["props"]["children"]["props"]["id"]["type"] # Figure

        # edit_button = dbc.Button(
        #     "Edit",
        #     id={
        #         "type": "edit-button",
        #         "index": f"edit-{btn_id}",
        #     },
        #     color="secondary",
        #     style={"margin-left": "10px"},
        #     # size="lg",
        # )

        edit_button = dmc.Button(
            "Edit",
            id={
                "type": "edit-button",
                "index": f"edit-{btn_index}",
            },
            color="gray",
            variant="filled",
            leftIcon=DashIconify(icon="basil:edit-solid", color="white"),
        )

        remove_button = dmc.Button(
            "Remove",
            id={"type": "remove-button", "index": f"remove-{btn_index}"},
            color="red",
            variant="filled",
            leftIcon=DashIconify(icon="jam:trash", color="white"),
        )

        new_draggable_child = html.Div(
            [
                remove_button,
                edit_button,
                child,
            ],
            id=f"draggable-{btn_index}",
        )

        return new_draggable_child

    else:
        return html.Div()

    # print("\nEND")

    # if n_clicks > 0:
    #     # print(children)
    #     # figure = children[0]["props"]["children"][0]["props"]["children"]["props"]["figure"]
    #     # print(children)
    #     # print(list(child["props"].keys()))
    #     # print(child_id)
    #     # child = children[0]["props"]["children"][0]["props"]["children"]["props"]["children"]
    #     # print(child)
    #     # if child["props"]["type"] is not "Card":
    #     # else:
    #     #     child["props"]["children"]["type"] = (
    #     #         "updated-" + child["props"]["id"]["type"]
    #     #     )

    #     # print(child)
    #     # # print(figure)
    #     # return dcc.Graph(
    #     #     figure=figure, id={"type": "graph", "index": btn_id["index"]}
    #     # )


# Add a callback to update the isDraggable property
@app.callback(
    [
        Output("draggable", "isDraggable"),
        Output("draggable", "isResizable"),
        Output("add-button", "disabled"),
    ],
    [Input("edit-dashboard-mode-button", "value")],
)
def freeze_layout(value):
    # switch based on button's value
    switch_state = True if len(value) > 0 else False
    if switch_state is False:
        return False, False, True
    else:
        return True, True, False


@app.callback(
    [
        Output("draggable", "children"),
        Output("draggable", "layouts"),
        Output("stored-layout", "data"),
        Output("stored-children", "data"),
        Output("stored-edit-dashboard-mode-button", "data"),
    ],
    # [
    #     Input(f"add-plot-button-{plot_type.lower().replace(' ', '-')}", "n_clicks")
    #     for plot_type in AVAILABLE_PLOT_TYPES.keys()
    # ]
    # +
    [
        Input("add-button", "n_clicks"),
        Input("edit-dashboard-mode-button", "value"),
        Input({"type": "remove-button", "index": dash.dependencies.ALL}, "n_clicks"),
        Input({"type": "input-component", "index": dash.dependencies.ALL}, "value"),
        # Input("time-input", "value"),
        Input("stored-layout", "data"),
        Input("stored-children", "data"),
        Input("draggable", "layouts"),
    ],
    [
        State("draggable", "children"),
        State("draggable", "layouts"),
        State("stored-layout", "data"),
        State("stored-children", "data"),
        State("stored-edit-dashboard-mode-button", "data"),
    ],
    prevent_initial_call=True,
)
def update_draggable_children(
    # n_clicks, selected_year, current_draggable_children, current_layouts, stored_figures
    *args,
):
    # for arg in [*args]:
    #     print("\n")
    #     print(arg)
    # print("______________________")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    ctx = dash.callback_context
    ctx_triggered = ctx.triggered
    print(f"CTX triggered: {ctx.triggered}")

    triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
    print(triggered_input)
    print(f"REMOVE BUTTON ARGS {args[-10]}")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    print("\n")
    stored_layout_data = args[-8]
    stored_children_data = args[-7]
    new_layouts = args[-6]
    # print(args[-10])

    # remove-button -7
    # selected_year = args[-6]

    current_draggable_children = args[-5]
    current_layouts = args[-4]
    stored_layout = args[-3]
    stored_figures = args[-2]
    stored_edit_dashboard = args[-1]

    switch_state = True if len(args[-11]) > 0 else False
    switch_state_index = -1 if switch_state is True else -1
    # print(f"Switch state: {switch_state}")
    # print(f"Switch state value: {stored_edit_dashboard}")

    filter_dict = {}

    # Enumerate through all the children
    for j, child in enumerate(current_draggable_children):
        # print(f"TOTO-{j}")
        # print(child["props"]["id"])
        # print(child["props"]["children"][switch_state_index]["props"])

        # Filter out those children that are not input components
        if (
            "-input" in child["props"]["id"]
            and "value"
            in child["props"]["children"][switch_state_index]["props"]["children"][-1][
                "props"
            ]
        ):
            # Extract the id and the value of the input component
            # print(f"TATA-{j}")

            id_components = child["props"]["children"][switch_state_index]["props"][
                "children"
            ][-1]["props"]["id"]["index"].split("-")[2:]
            value = child["props"]["children"][switch_state_index]["props"]["children"][
                -1
            ]["props"]["value"]

            # Construct the key for the dictionary
            key = "-".join(id_components)

            # Add the key-value pair to the dictionary
            filter_dict[key] = value

    # if current_draggable_children is None:
    #     current_draggable_children = []
    # if current_layouts is None:
    #     current_layouts = dict()

    if "add-button" in triggered_input:
        # print(ctx.triggered[0])
        # print(ctx.triggered[0]["value"])
        n = ctx.triggered[0]["value"]
        # print("add_new_div")
        # print(n)
        # print(app._callback_list)

        # print("index: {}".format(n))
        new_plot_id = f"graph-{n}"
        # print(new_plot_id)

        new_element = html.Div(
            [
                html.Div(id={"type": "add-content", "index": n}),
                dbc.Modal(
                    id={"type": "modal", "index": n},
                    children=[
                        dbc.ModalHeader(html.H5("Design your new dashboard component")),
                        dbc.ModalBody(
                            [
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            dmc.Button(
                                                "Figure",
                                                id={
                                                    "type": "btn-option",
                                                    "index": n,
                                                    "value": "Figure",
                                                },
                                                n_clicks=0,
                                                style={
                                                    "display": "inline-block",
                                                    "width": "250px",
                                                    "height": "100px",
                                                },
                                                size="xl",
                                                color="grape",
                                                leftIcon=DashIconify(
                                                    icon="mdi:graph-box"
                                                ),
                                            )
                                        ),
                                        dbc.Col(
                                            dmc.Button(
                                                "Card",
                                                id={
                                                    "type": "btn-option",
                                                    "index": n,
                                                    "value": "Card",
                                                },
                                                n_clicks=0,
                                                style={
                                                    "display": "inline-block",
                                                    "width": "250px",
                                                    "height": "100px",
                                                },
                                                size="xl",
                                                color="violet",
                                                leftIcon=DashIconify(
                                                    icon="formkit:number", color="white"
                                                ),
                                            )
                                        ),
                                        dbc.Col(
                                            dmc.Button(
                                                "Interaction",
                                                id={
                                                    "type": "btn-option",
                                                    "index": n,
                                                    "value": "Interactive",
                                                },
                                                n_clicks=0,
                                                style={
                                                    "display": "inline-block",
                                                    "width": "250px",
                                                    "height": "100px",
                                                },
                                                size="xl",
                                                color="indigo",
                                                leftIcon=DashIconify(
                                                    icon="bx:slider-alt", color="white"
                                                ),
                                            )
                                        ),
                                    ]
                                ),
                            ],
                            id={"type": "modal-body", "index": n},
                            style={
                                "display": "flex",
                                "justify-content": "center",
                                "align-items": "center",
                                "flex-direction": "column",
                                "height": "100%",
                                "width": "100%",
                            },
                        ),
                    ],
                    is_open=True,
                    size="xl",
                    backdrop=False,
                    style={
                        "height": "100%",
                        "width": "100%",
                        # "display": "flex",
                        # "flex-direction": "column",
                        # "flex-grow": "0",
                    },
                ),
            ],
            id=new_plot_id,
        )

        current_draggable_children.append(new_element)
        new_layout_item = {
            "i": f"{new_plot_id}",
            "x": 10 * ((len(current_draggable_children) + 1) % 2),
            "y": n * 10,
            "w": 6,
            "h": 5,
        }

        # Update the layouts property for both 'lg' and 'sm' sizes
        updated_layouts = {}
        for size in ["lg", "sm"]:
            if size not in current_layouts:
                current_layouts[size] = []
            current_layouts[size] = current_layouts[size] + [new_layout_item]
        return (
            current_draggable_children,
            current_layouts,
            current_layouts,
            current_draggable_children,
            stored_edit_dashboard,
        )

    #     return (
    #         updated_draggable_children,
    #         updated_layouts,
    #         # selected_year,
    #         updated_layouts,
    #         updated_draggable_children,
    #         # selected_year,
    #     )

    # if triggered_input.startswith("add-plot-button-"):
    #     plot_type = triggered_input.replace("add-plot-button-", "")

    #     n_clicks = ctx.triggered[0]["value"]
    #     print(n_clicks)

    #     new_plot_id = f"graph-{n_clicks}-{plot_type.lower().replace(' ', '-')}"
    #     new_plot_type = plot_type
    #     print(new_plot_type)

    #     if "-card" in new_plot_type:
    #         new_plot = html.Div(
    #             create_initial_figure(df, new_plot_type), id=new_plot_id
    #         )
    #     elif "-input" in new_plot_type:
    #         print(new_plot_id)
    #         # input_id = f"{plot_type.lower().replace(' ', '-')}"

    #         new_plot = create_initial_figure(df, new_plot_type, id=new_plot_id)
    #     else:
    #         new_plot = dcc.Graph(
    #             id=new_plot_id,
    #             figure=create_initial_figure(df, new_plot_type),
    #             responsive=True,
    #             style={
    #                 "width": "100%",
    #                 "height": "100%",
    #             },
    #             # config={"staticPlot": False, "editable": True},
    #         )
    #     # print(new_plot)

    #     # new_draggable_child = new_plot
    #     edit_button = dbc.Button(
    #         "Edit",
    #         id={
    #             "type": "edit-button",
    #             "index": f"edit-{new_plot_id}",
    #         },
    #         color="secondary",
    #         style={"margin-left": "10px"},
    #         # size="lg",
    #     )
    #     new_draggable_child = html.Div(
    #         [
    #             dbc.Button(
    #                 "Remove",
    #                 id={"type": "remove-button", "index": f"remove-{new_plot_id}"},
    #                 color="danger",
    #             ),
    #             edit_button,
    #             new_plot,
    #         ],
    #         id=f"draggable-{new_plot_id}",
    #     )
    #     # print(current_draggable_children)
    #     # print(len(current_draggable_children))

    #     updated_draggable_children = current_draggable_children + [new_draggable_child]

    #     # Define the default size and position for the new plot
    #     if "-card" not in new_plot_type:
    #         new_layout_item = {
    #             "i": f"draggable-{new_plot_id}",
    #             "x": 10 * ((len(updated_draggable_children) + 1) % 2),
    #             "y": n_clicks * 10,
    #             "w": 6,
    #             "h": 14,
    #         }
    #     else:
    #         new_layout_item = {
    #             "i": f"draggable-{new_plot_id}",
    #             "x": 10 * ((len(updated_draggable_children) + 1) % 2),
    #             "y": n_clicks * 10,
    #             "w": 4,
    #             "h": 5,
    #         }

    #     # Update the layouts property for both 'lg' and 'sm' sizes
    #     updated_layouts = {}
    #     for size in ["lg", "sm"]:
    #         if size not in current_layouts:
    #             current_layouts[size] = []
    #         updated_layouts[size] = current_layouts[size] + [new_layout_item]

    #     # Store the newly created figure in stored_figures
    #     # stored_figures[new_plot_id] = new_plot

    #     return (
    #         updated_draggable_children,
    #         updated_layouts,
    #         # selected_year,
    #         updated_layouts,
    #         updated_draggable_children,
    #         # selected_year,
    #     )

    # import ast

    # if "-input" in triggered_input and "remove-" not in triggered_input:
    #     input_id = ast.literal_eval(triggered_input)["index"]
    #     updated_draggable_children = []

    #     for j, child in enumerate(current_draggable_children):
    #         if child["props"]["id"].replace("draggable-", "") == input_id:
    #             updated_draggable_children.append(child)
    #         elif (
    #             child["props"]["id"].replace("draggable-", "") != input_id
    #             and "-input" not in child["props"]["id"]
    #         ):
    #             # print(child["props"]["id"]["index"])
    #             index = -1 if switch_state is True else 0
    #             graph = child["props"]["children"][index]
    #             if type(graph["props"]["id"]) is str:
    #                 # Extract the figure type and its corresponding function
    #                 figure_type = "-".join(graph["props"]["id"].split("-")[2:])
    #                 graph_id = graph["props"]["id"]
    #                 updated_fig = create_initial_figure(
    #                     df,
    #                     figure_type,
    #                     input_id="-".join(input_id.split("-")[2:]),
    #                     filter=filter_dict,
    #                 )

    #                 if "-card" in graph_id:
    #                     graph["props"]["children"] = updated_fig

    #                 else:
    #                     graph["props"]["figure"] = updated_fig
    #                 rm_button = dbc.Button(
    #                     "Remove",
    #                     id={
    #                         "type": "remove-button",
    #                         "index": child["props"]["id"],
    #                     },
    #                     color="danger",
    #                 )
    #                 edit_button = dbc.Button(
    #                     "Edit",
    #                     id={
    #                         "type": "edit-button",
    #                         "index": child["props"]["id"],
    #                     },
    #                     color="secondary",
    #                     style={"margin-left": "10px"},
    #                 )
    #                 children = (
    #                     [rm_button, edit_button, graph]
    #                     if switch_state is True
    #                     else [graph]
    #                 )
    #                 updated_child = html.Div(
    #                     children=children,
    #                     id=child["props"]["id"],
    #                 )

    #                 updated_draggable_children.append(updated_child)
    #         else:
    #             updated_draggable_children.append(child)

    #     return (
    #         updated_draggable_children,
    #         current_layouts,
    #         current_layouts,
    #         updated_draggable_children,
    #     )

    # if the remove button was clicked, return an empty list to remove all the plots

    elif "remove-" in triggered_input and [e for e in args[-10] if e]:
        print("\nREMOVE")
        print(triggered_input, type(triggered_input))
        # print(current_draggable_children)
        input_id = ast.literal_eval(triggered_input)["index"]
        # print(input_id)

        # new_filter_dict = filter_dict
        # print(new_filter_dict)
        for child in current_draggable_children:
            # print("-".join(child["props"]["id"].split("-")[1:]))
            # print("-".join(input_id.split("-")[1:]))
            if "-".join(child["props"]["id"].split("-")[1:]) == "-".join(
                input_id.split("-")[1:]
            ):
                current_draggable_children.remove(child)
        #         input_id = "-".join(input_id.split("-")[2:])

        #         # Remove the corresponding entry from filter dictionary
        #         tmp_input_id = "-".join(input_id.split("-")[1:])
        #         if "-".join(input_id.split("-")[1:]) in new_filter_dict:
        #             del new_filter_dict[tmp_input_id]
        #         print(new_filter_dict)

        # updated_draggable_children = []

        # for j, child in enumerate(current_draggable_children):
        #     if child["props"]["id"].replace("draggable-", "") == input_id:
        #         updated_draggable_children.append(child)
        #     elif (
        #         child["props"]["id"].replace("draggable-", "") != input_id
        #         and "-input" not in child["props"]["id"]
        #     ):
        #         # print(child["props"]["id"]["index"])
        #         index = -1 if switch_state is True else 0
        #         graph = child["props"]["children"][index]
        #         if type(graph["props"]["id"]) is str:
        #             print("TEST")
        #             # Extract the figure type and its corresponding function
        #             figure_type = "-".join(graph["props"]["id"].split("-")[2:])
        #             graph_id = graph["props"]["id"]
        #             updated_fig = create_initial_figure(
        #                 df,
        #                 figure_type,
        #                 input_id="-".join(input_id.split("-")[2:]),
        #                 filter=new_filter_dict,
        #             )

        #             if "-card" in graph_id:
        #                 graph["props"]["children"] = updated_fig

        #             else:
        #                 graph["props"]["figure"] = updated_fig
        #             rm_button = dbc.Button(
        #                 "Remove",
        #                 id={
        #                     "type": "remove-button",
        #                     "index": child["props"]["id"],
        #                 },
        #                 color="danger",
        #             )
        #             edit_button = dbc.Button(
        #                 "Edit",
        #                 id={
        #                     "type": "edit-button",
        #                     "index": child["props"]["id"],
        #                 },
        #                 color="secondary",
        #                 style={"margin-left": "10px"},
        #             )
        #             children = (
        #                 [rm_button, edit_button, graph]
        #                 if switch_state is True
        #                 else [graph]
        #             )
        #             updated_child = html.Div(
        #                 children=children,
        #                 id=child["props"]["id"],
        #             )

        #             updated_draggable_children.append(updated_child)
        #     else:
        #         updated_draggable_children.append(child)

        return (
            current_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            current_draggable_children,
            stored_edit_dashboard
            # selected_year,
        )
        # return (
        #     updated_draggable_children,
        #     current_layouts,
        #     current_layouts,
        #     updated_draggable_children,
        # )

    # elif triggered_input == "stored-layout" or triggered_input == "stored-children":
    #     if stored_layout_data and stored_children_data:
    #         return (
    #             stored_children_data,
    #             stored_layout_data,
    #             stored_layout_data,
    #             stored_children_data,
    #         )
    #     else:
    #         # Load data from the file if it exists
    #         loaded_data = load_data()
    #         if loaded_data:
    #             return (
    #                 loaded_data["stored_children_data"],
    #                 loaded_data["stored_layout_data"],
    #                 loaded_data["stored_layout_data"],
    #                 loaded_data["stored_children_data"],
    #             )
    #         else:
    #             return (
    #                 current_draggable_children,
    #                 {},
    #                 stored_layout,
    #                 stored_figures,
    #             )

    elif triggered_input == "draggable":
        return (
            current_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            current_draggable_children,
            stored_edit_dashboard
            # selected_year,
        )

    # div_index = 4 if box_type == "segmented-control-visu-graph" else 2
    # if box_type:
    #     if box_type == "segmented-control-visu-graph":
    #         child = children[div_index]["props"]["children"][0]["props"][
    #             "children"
    #         ]  # Figure
    #         child["props"]["id"]["type"] = (
    #             "updated-" + child["props"]["id"]["type"]
    #         )  # Figure

    #         # print(child)
    #         print("OK")
    #     elif box_type == "card":
    #         # print(children)
    #         child = children[div_index]["props"]["children"][1]["props"]["children"][
    #             1
    #         ]  # Card
    #         print(child)
    #         child["props"]["children"]["props"]["id"]["type"] = (
    #             "updated-" + child["props"]["children"]["props"]["id"]["type"]
    #         )  # Figure
    #     elif box_type == "input":
    #         # print(children)
    #         child = children[div_index]["props"]["children"][1]["props"]["children"][
    #             1
    #         ]  # Card
    #         print(child)
    #         child["props"]["children"]["props"]["id"]["type"] = (
    #             "updated-" + child["props"]["children"]["props"]["id"]["type"]

    # edit_button = dmc.Button(
    #     "Edit",
    #     id={
    #         "type": "edit-button",
    #         "index": f"edit-{btn_index}",
    #     },
    #     color="gray",
    #     variant="filled",
    #     leftIcon=DashIconify(icon="basil:edit-solid", color="white"),
    # )

    # remove_button = dmc.Button(
    #     "Remove",
    #     id={"type": "remove-button", "index": f"remove-{btn_index}"},
    #     color="red",
    #     variant="filled",
    #     leftIcon=DashIconify(icon="jam:trash", color="white"),
    # )

    # new_draggable_child = html.Div(
    #     [
    #         html.Div([remove_button, edit_button]),
    #         child,
    #     ],
    #     id=f"draggable-{btn_id}",
    # )

    elif triggered_input == "edit-dashboard-mode-button":
        # print("\n\n")
        stored_edit_dashboard["count"] = (
            stored_edit_dashboard["count"] + 1
            if switch_state
            else stored_edit_dashboard["count"]
        )

        # switch_state = True if len(ctx.triggered[0]["value"]) > 0 else False
        # print(switch_state)
        # print(stored_edit_dashboard)
        # print(current_draggable_children)
        # assuming the switch state is added as the first argument in args
        updated_draggable_children = []
        # print(len(current_draggable_children))
        for child in current_draggable_children:
            print("\n\n")
            print(child)
            print("\n\n")


            # print(len(child))
            # print(child["props"]["id"])
            # print(len(child["props"]["children"]))
            # graph = child["props"]["children"][0]["props"]["children"][
            #     -2
            # ]  # Assuming graph is always the last child
            #     graph = child["props"]["children"][0]["props"]["children"][0]["props"]["children"]
            #     print(child["props"]["children"])
            if switch_state:  # If switch is 'on', add the remove button
                # if "graph" in child["props"]["id"]:
                graph = child["props"]["children"][0]
                # print(graph["props"]["id"])

                edit_button = dmc.Button(
                    "Edit",
                    id={
                        "type": "edit-button",
                        "index": child["props"]["id"],
                    },
                    color="gray",
                    variant="filled",
                    leftIcon=DashIconify(icon="basil:edit-solid", color="white"),
                )

                remove_button = dmc.Button(
                    "Remove",
                    id={"type": "remove-button", "index": child["props"]["id"]},
                    color="red",
                    variant="filled",
                    leftIcon=DashIconify(icon="jam:trash", color="white"),
                )

                updated_child = html.Div(
                    [
                        remove_button,
                        edit_button,
                        graph,
                    ],
                    id=child["props"]["id"],
                )

                # remove_button = dbc.Button(
                #     "Remove",
                #     id={
                #         "type": "remove-button",
                #         "index": child["props"]["id"],
                #     },
                #     color="danger",
                # )
                # edit_button = dbc.Button(
                #     "Edit",
                #     id={
                #         "type": "edit-button",
                #         "index": child["props"]["id"],
                #     },
                #     color="secondary",
                #     style={"margin-left": "10px"},
                # )

                # updated_child = html.Div(
                #     [remove_button, edit_button, graph],
                #     id=child["props"]["id"],
                # )
            elif (
                switch_state is False and stored_edit_dashboard["count"] == 0
            ):  # If switch is 'off', remove the button
                graph = child["props"]["children"][0]["props"]["children"]["props"][
                    "children"
                ][2]
                # print(graph["props"]["id"])

                updated_child = html.Div(
                    [graph],
                    id=child["props"]["id"],
                )
            else:
                graph = child["props"]["children"][-1]
                # print(child["props"]["id"])

                updated_child = html.Div(
                    [graph],
                    id=child["props"]["id"],
                )
        updated_draggable_children.append(updated_child)

        return (
            updated_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            updated_draggable_children,
            stored_edit_dashboard
            # selected_year,
        )

    # # Add an else condition to return the current layout when there's no triggering input
    else:
        raise dash.exceptions.PreventUpdate


if __name__ == "__main__":
    app.run_server(debug=True, port="5080")
