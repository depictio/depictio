# Import necessary libraries
import collections
from dash import html, dcc, Input, Output, State, MATCH
import httpx
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from depictio.dash.utils import list_workflows
from depictio.dash.utils import (
    UNSELECTED_STYLE,
    get_columns_from_data_collection,
)

# Depictio imports
from depictio.dash.modules.figure_component.utils import (
    build_figure,
    build_figure_frame,
    specific_params,
    param_info,
    plotly_bootstrap_mapping,
    secondary_common_params,
    base_elements,
    plotly_vizu_dict,
)
from depictio.dash.utils import (
    get_columns_from_data_collection,
)
from depictio.api.v1.configs.config import API_BASE_URL

def register_callbacks_figure_component(app):
    @dash.callback(
        [
            Output({"type": "collapse", "index": MATCH}, "children"),
        ],
        [
            Input({"type": "refresh-button", "index": MATCH}, "n_clicks"),
            Input({"type": "edit-button", "index": MATCH}, "n_clicks"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        [State({"type": "edit-button", "index": MATCH}, "id"), State("local-store", "data")],
        # prevent_initial_call=True,
    )
    def update_specific_params(
        n_clicks_refresh,
        n_clicks,
        visu_type,
        workflow,
        data_collection,
        edit_button_id,
        local_data,
    ):
        """
        Compute the specific parameters dropdowns based on the selected visualisation type
        """

        if not local_data:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_data["access_token"]
        # Retrieve the columns from the selected data collection
        columns_json = get_columns_from_data_collection(workflow, data_collection, TOKEN)
        columns = list(columns_json.keys())

        # Get the value of the segmented control
        value = visu_type.lower()

        if value is None:
            return html.Div()

        elif value is not None:
            specific_params_options = [{"label": param_name, "value": param_name} for param_name in specific_params[value]]

            specific_params_dropdowns = []
            for e in specific_params[value]:
                processed_type_tmp = param_info[value][e]["processed_type"]
                allowed_types = ["str", "int", "float", "column"]
                if processed_type_tmp in allowed_types:
                    input_fct = plotly_bootstrap_mapping[processed_type_tmp]
                    tmp_options = {}

                    if processed_type_tmp == "column":
                        tmp_options = {
                            "options": columns,
                            "value": None,
                            "persistence": True,
                            "id": {
                                "type": f"tmp-{e}",
                                "index": edit_button_id["index"],
                            },
                        }
                    elif processed_type_tmp == "str":
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
                    elif processed_type_tmp in ["int", "float"]:
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
                    
                    # Retrieve the description for the tooltip
                    tooltip_label = param_info[value][e].get("description", "TEST")

                    # Create a Tooltip for the title
                    title_with_tooltip = dmc.Tooltip(
                        label=tooltip_label,
                        # position="left",
                        multiline=True,
                        transition="pop",
                        withArrow=True,
                        width=600,
                        openDelay=100,
                        closeDelay=100,
                        # transitionDuration=150,
                        zIndex=1000,
                        children=e,  # The parameter name
                    )

                    accordion_item = dbc.AccordionItem(
                        [dbc.Row(input_fct_with_params)],
                        className="my-2",
                        title=title_with_tooltip,  # Embed Tooltip in title
                    )

                    specific_params_dropdowns.append(accordion_item)

            # Repeat similar changes for secondary and primary common params
            secondary_common_params_dropdowns = []
            primary_common_params_dropdowns = []
            for e in secondary_common_params:
                processed_type_tmp = param_info[value][e]["processed_type"]
                allowed_types = ["str", "int", "float", "column"]
                if processed_type_tmp in allowed_types:
                    input_fct = plotly_bootstrap_mapping[processed_type_tmp]

                    tmp_options = {}

                    if processed_type_tmp == "column":
                        tmp_options = {
                            "options": columns,
                            "value": None,
                            "persistence": True,
                            "style": {"width": "100%"},
                            "id": {
                                "type": f"tmp-{e}",
                                "index": edit_button_id["index"],
                            },
                        }
                    elif processed_type_tmp == "str":
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
                    elif processed_type_tmp in ["int", "float"]:
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

                    # Retrieve the description for the tooltip
                    tooltip_label = param_info[value][e].get("description", "")

                    # Create a Tooltip for the title
                    title_with_tooltip = dmc.Tooltip(
                        label=tooltip_label,
                        # position="left",
                        multiline=True,
                        transition="pop",
                        withArrow=True,
                        width=600,
                        openDelay=100,
                        closeDelay=100,
                        # transitionDuration=150,
                        zIndex=1000,
                        children=e,  # The parameter name
                    )
                    accordion_item = dbc.AccordionItem(
                        [dbc.Row(input_fct_with_params, style={"width": "100%"})],
                        className="my-2",
                        title=title_with_tooltip,  # Embed Tooltip in title
                    )

                    if e not in base_elements:
                        secondary_common_params_dropdowns.append(accordion_item)
                    else:
                        primary_common_params_dropdowns.append(accordion_item)

            primary_common_params_layout = [
                dbc.Accordion(
                    dbc.AccordionItem(
                        [
                            dbc.Accordion(
                                primary_common_params_dropdowns,
                                flush=True,
                                always_open=True,
                                persistence_type="memory",
                                persistence=True,
                                id="accordion-pri-common",
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
                                persistence_type="memory",
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
                                persistence_type="memory",
                                persistence=True,
                                id="accordion",
                            ),
                        ],
                        title=f"{value.capitalize()} specific parameters",
                    ),
                    start_collapsed=True,
                )
            ]

            return [primary_common_params_layout + secondary_common_params_layout + dynamic_specific_params_layout]
        else:
            return html.Div()

    def generate_dropdown_ids(value):
        specific_param_ids = [f"{value}-{param_name}" for param_name in specific_params[value]]
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
        # prevent_initial_call=True,
    )
    def toggle_collapse(n, is_open):
        # print(n, is_open, n % 2 == 0)
        if n % 2 == 0:
            return False
        else:
            return True

    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data"),
        [
            Input({"type": "collapse", "index": MATCH}, "children"),
            # Input("interval", "n_intervals"),
        ],
        [State({"type": "dict_kwargs", "index": MATCH}, "data")],
        # prevent_initial_call=True,
    )
    def get_values_to_generate_kwargs(*args):
        children = args[0]

        existing_kwargs = args[-1]

        accordion_primary_common_params_args = dict()
        accordion_secondary_common_params_args = dict()
        specific_params_args = dict()

        if children:
            # accordion_secondary_common_params = children[0]["props"]["children"]["props"]["children"]
            accordion_primary_common_params = children[0]["props"]["children"]["props"]["children"][0]["props"]["children"]

            # accordion_secondary_common_params = children[1]["props"]["children"]
            if accordion_primary_common_params:
                accordion_primary_common_params = [param["props"]["children"][0]["props"]["children"] for param in accordion_primary_common_params]
                accordion_primary_common_params_args = {elem["props"]["id"]["type"].replace("tmp-", ""): elem["props"]["value"] for elem in accordion_primary_common_params}
            accordion_secondary_common_params = children[1]["props"]["children"]["props"]["children"][0]["props"]["children"]
            if accordion_secondary_common_params:
                accordion_secondary_common_params = [param["props"]["children"][0]["props"]["children"] for param in accordion_secondary_common_params]
                accordion_secondary_common_params_args = {elem["props"]["id"]["type"].replace("tmp-", ""): elem["props"]["value"] for elem in accordion_secondary_common_params}
            specific_params = children[2]["props"]["children"]["props"]["children"][0]["props"]["children"]
            if specific_params:
                specific_params = [param["props"]["children"][0]["props"]["children"] for param in specific_params]
                specific_params_args = {elem["props"]["id"]["type"].replace("tmp-", ""): elem["props"]["value"] for elem in specific_params}

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

            if return_dict:
                return return_dict
            else:
                return existing_kwargs

        else:
            return existing_kwargs

    @app.callback(
        Output({"type": "figure-body", "index": MATCH}, "children"),
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "segmented-control-visu-graph", "index": MATCH}, "id"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_figure(*args):
        dict_kwargs = args[0]

        visu_type = args[1]
        workflow = args[2]
        data_collection = args[3]
        id = args[4]
        local_data = args[5]

        if not local_data:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_data["access_token"]

        columns_json = get_columns_from_data_collection(workflow, data_collection, TOKEN)

        columns_specs_reformatted = collections.defaultdict(list)
        {columns_specs_reformatted[v["type"]].append(k) for k, v in columns_json.items()}

        x_col, color_col, y_col = None, None, None

        if columns_specs_reformatted["object"]:
            x_col = columns_specs_reformatted["object"][0]
            color_col = columns_specs_reformatted["object"][0]

        if columns_specs_reformatted["int64"]:
            y_col = columns_specs_reformatted["int64"][0]
        elif columns_specs_reformatted["float64"]:
            y_col = columns_specs_reformatted["float64"][0]

        # if dict_kwargs is empty, fill it with default values
        if not dict_kwargs:
            dict_kwargs = {"x": x_col, "y": y_col, "color": color_col}

        workflows = list_workflows(TOKEN)

        workflow_id = [e for e in workflows if e["workflow_tag"] == workflow][0]["_id"]
        data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection][0]["_id"]

        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()

        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        join_tables_for_wf = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/workflows/get_join_tables/{workflow_id}",
            headers=headers,
        )

        if dict_kwargs:
            figure_kwargs = {
                "index": id["index"],
                "dict_kwargs": dict_kwargs,
                "visu_type": visu_type,
                "wf_id": workflow_id,
                "dc_id": data_collection_id,
                "dc_config": dc_specs["config"],
                "visu_type": visu_type,
                "access_token": TOKEN,
            }
            return build_figure(**figure_kwargs)
        else:
            raise dash.exceptions.PreventUpdate


def design_figure(id):
    figure_row = [
        dbc.Row(
            [
                html.H5("Select your visualisation type"),
                dmc.SegmentedControl(
                    data=[e.capitalize() for e in sorted(plotly_vizu_dict.keys())],
                    orientation="horizontal",
                    size="lg",
                    radius="lg",
                    id={
                        "type": "segmented-control-visu-graph",
                        "index": id["index"],
                    },
                    persistence=True,
                    persistence_type="memory",
                    # FIXME: the default value is not the first element of the list - set to scatter plot (last element)
                    value=[e.capitalize() for e in sorted(plotly_vizu_dict.keys())][-1],
                ),
            ],
            style={"height": "5%"},
        ),
        html.Br(),
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Div(
                            build_figure_frame(index=id["index"]),
                            id={
                                "type": "component-container",
                                "index": id["index"],
                            },
                        ),
                    ],
                    width="auto",
                ),
                dbc.Col(
                    [
                        html.Br(),
                        html.Div(
                            children=[
                                dbc.Row(
                                    children=[
                                        dbc.Col(
                                            dmc.Button(
                                                "Edit figure",
                                                id={
                                                    "type": "edit-button",
                                                    "index": id["index"],
                                                },
                                                n_clicks=0,
                                                # size="lg",
                                                style={"align": "center"},
                                            )
                                        ),
                                        dbc.Col(
                                            dmc.ActionIcon(
                                                DashIconify(icon="mdi:refresh", width=30),
                                                id={
                                                    "type": "refresh-button",
                                                    "index": id["index"],
                                                },
                                                size="xl",
                                                style={"align": "center"},
                                                n_clicks=0,
                                            )
                                        ),
                                    ]
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
        dcc.Store(
            id={"type": "dict_kwargs", "index": id["index"]},
            data={},
            storage_type="memory",
        ),
    ]
    return figure_row


def create_stepper_figure_button(n, disabled=False):
    """
    Create the stepper figure button

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """

    button = dbc.Col(
        dmc.Button(
            "Figure",
            id={
                "type": "btn-option",
                "index": n,
                "value": "Figure",
            },
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="grape",
            leftIcon=DashIconify(icon="mdi:graph-box"),
            disabled=disabled,
        )
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Figure",
        },
        data=0,
        storage_type="memory",
    )
    return button, store
