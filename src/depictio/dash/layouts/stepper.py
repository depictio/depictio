from dash import html, Input, Output, State, ALL, MATCH, ctx, dcc
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx
import pandas as pd

# Depictio imports
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.modules.card_component.frontend import design_card
from depictio.dash.modules.figure_component.frontend import design_figure
from depictio.dash.modules.interactive_component.frontend import design_interactive
from depictio.api.v1.configs.logging import logger

# from depictio.dash.modules.table_component.frontend import design_table
from depictio.dash.utils import (
    get_component_data,
    return_dc_tag_from_id,
    return_mongoid,
    return_wf_tag_from_id,
)


min_step = 0
max_step = 3
active = 0


def register_callbacks_stepper(app):
    @app.callback(
        Output({"type": "modal", "index": MATCH}, "is_open"),
        [Input({"type": "btn-done", "index": MATCH}, "n_clicks")],
        prevent_initial_call=True,
    )
    def close_modal(n_clicks):
        if n_clicks > 0:
            return False
        return True

    @app.callback(
        Output({"type": "workflow-selection-label", "index": MATCH}, "data"),
        Output({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State("local-store", "data"),
        State("url", "pathname"),
    )
    def set_workflow_options(n_clicks, local_store, pathname):
        logger.info(f"CTX Triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX triggered: {ctx.triggered}")

        if not local_store:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_store["access_token"]

        if isinstance(ctx.triggered_id, dict):
            if ctx.triggered_id["type"] == "btn-option":
                component_selected = ctx.triggered_id["value"]

        else:
            component_selected = "None"
        # component_selected = "Card"

        project = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{pathname.split('/')[-1]}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()
        all_wf_dc = project["workflows"]
        logger.info(f"all_wf_dc: {all_wf_dc}")

        # all_wf_dc = httpx.get(
        #     f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id/{local_store['project_id']}",
        #     headers={
        #         "Authorization": f"Bearer {TOKEN}",
        #     },
        # ).json()

        mapping_component_data_collection = {
            "table": ["Figure", "Card", "Interactive", "Table"],
            "jbrowse2": ["JBrowse2"],
        }

        logger.info(f"Component selected: {component_selected}")
        # valid_wfs = sorted(
        #     {wf["workflow_tag"] for wf in all_wf_dc for dc in wf["data_collections"] if component_selected in mapping_component_data_collection[dc["config"]["type"]]}
        # )
        # logger.info(f"valid_wfs: {valid_wfs}")

        # Use a dictionary to track unique workflows efficiently
        valid_wfs = []
        seen_workflow_ids = set()

        for wf in all_wf_dc:
            # Check if the workflow has any matching data collection
            if (
                any(
                    component_selected
                    in mapping_component_data_collection[dc["config"]["type"]]
                    for dc in wf["data_collections"]
                )
                and wf["_id"] not in seen_workflow_ids
            ):
                seen_workflow_ids.add(wf["_id"])
                valid_wfs.append(
                    {
                        "label": wf["workflow_tag"],
                        "value": wf["_id"],
                    }
                )

        logger.info(f"valid_wfs: {valid_wfs}")
        # Return the data and the first value if the data is not empty
        if valid_wfs:
            return valid_wfs, valid_wfs[0]["value"]
        else:
            return dash.no_update, dash.no_update

    # @app.callback(
    #     Output({"type": "workflow-selection-label-edit", "index": MATCH}, "data"),
    #     Output({"type": "workflow-selection-label-edit", "index": MATCH}, "value"),
    #     Input({"type": "stepper-step-1-edit", "index": MATCH}, "active"),
    #     State("local-store", "data"),
    # )
    # def set_workflow_options(active_step, local_store):
    #     logger.info(f"CTX Triggered ID: {ctx.triggered_id}")
    #     logger.info(f"CTX triggered: {ctx.triggered}")

    #     if not local_store:
    #         raise dash.exceptions.PreventUpdate

    #     TOKEN = local_store["access_token"]

    #     if isinstance(ctx.triggered_id, dict):
    #         if ctx.triggered_id["type"] == "btn-option":
    #             component_selected = ctx.triggered_id["value"]

    #     else:
    #         component_selected = "None"
    #     component_selected = "Card"

    #     all_wf_dc = httpx.get(
    #         f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows",
    #         headers={
    #             "Authorization": f"Bearer {TOKEN}",
    #         },
    #     ).json()

    #     mapping_component_data_collection = {
    #         "Table": ["Figure", "Card", "Interactive", "Table"],
    #         "JBrowse2": ["JBrowse2"],
    #     }

    #     logger.info(f"Component selected: {component_selected}")
    #     valid_wfs = sorted(
    #         {wf["workflow_tag"] for wf in all_wf_dc for dc in wf["data_collections"] if component_selected in mapping_component_data_collection[dc["config"]["type"]]}
    #     )
    #     logger.info(f"valid_wfs: {valid_wfs}")

    #     # Return the data and the first value if the data is not empty
    #     if valid_wfs:
    #         return valid_wfs, valid_wfs[0]
    #     else:
    #         return dash.no_update, dash.no_update

    @app.callback(
        Output({"type": "datacollection-selection-label", "index": MATCH}, "data"),
        Output({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "id"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State("local-store", "data"),
        State("url", "pathname"),
        # prevent_initial_call=True,
    )
    def set_datacollection_options(
        selected_workflow, id, n_clicks, local_store, pathname
    ):
        logger.info(f"CTX Triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX triggered: {ctx.triggered}")

        if not local_store:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_store["access_token"]

        if isinstance(ctx.triggered_id, dict):
            if ctx.triggered_id["type"] == "btn-option":
                component_selected = ctx.triggered_id["value"]

        else:
            component_selected = "None"
        # component_selected = "Card"

        project = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{pathname.split('/')[-1]}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()
        all_wf_dc = project["workflows"]
        logger.info(f"all_wf_dc: {all_wf_dc}")

        # all_wf_dc = httpx.get(
        #     f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows",
        #     headers={
        #         "Authorization": f"Bearer {TOKEN}",
        #     },
        # ).json()
        selected_wf_data = [wf for wf in all_wf_dc if wf["_id"] == selected_workflow][0]

        mapping_component_data_collection = {
            "table": ["Figure", "Card", "Interactive", "Table"],
            "jbrowse2": ["JBrowse2"],
        }

        logger.info(f"Component selected: {component_selected}")
        valid_dcs = sorted(
            {
                dc["data_collection_tag"]
                for dc in selected_wf_data["data_collections"]
                if component_selected
                in mapping_component_data_collection[dc["config"]["type"]]
            }
        )

        valid_dcs = [
            {
                "label": dc["data_collection_tag"],
                "value": dc["_id"],
            }
            for dc in selected_wf_data["data_collections"]
            if component_selected
            in mapping_component_data_collection[dc["config"]["type"]]
        ]

        logger.info(f"valid_dcs: {valid_dcs}")

        logger.info("ID: {}".format(id))
        if not selected_workflow:
            raise dash.exceptions.PreventUpdate

        # tmp_data = list_data_collections_for_dropdown(selected_workflow)

        # Return the data and the first value if the data is not empty
        if valid_dcs:
            return valid_dcs, valid_dcs[0]["value"]
        else:
            raise dash.exceptions.PreventUpdate

    @app.callback(
        [
            Output({"type": "stepper-basic-usage", "index": MATCH}, "active"),
            Output({"type": "next-basic-usage", "index": MATCH}, "disabled"),
        ],
        [
            Input({"type": "back-basic-usage", "index": MATCH}, "n_clicks"),
            Input({"type": "next-basic-usage", "index": MATCH}, "n_clicks"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        ],
        [State({"type": "stepper-basic-usage", "index": MATCH}, "active")],
    )
    def update_stepper(
        back_clicks,
        next_clicks,
        workflow_selection,
        data_selection,
        btn_option_clicks,
        current_step,
    ):
        ctx = dash.callback_context

        if not ctx.triggered:
            # No inputs have fired yet, prevent update
            raise dash.exceptions.PreventUpdate

        triggered_id = ctx.triggered_id
        if isinstance(ctx.triggered_id, dict):
            triggered_input = ctx.triggered_id["type"]
        elif isinstance(ctx.triggered_id, str):
            triggered_input = ctx.triggered_id
        inputs_list = ctx.inputs_list

        logger.info(f"CTX triggered: {ctx.triggered}")
        logger.info(f"Triggered ID: {triggered_id}")
        logger.info(f"Inputs list: {inputs_list}")

        next_step = (
            current_step  # Default to the current step if no actions require a change
        )

        # Check if any btn-option was clicked
        btn_clicks = [btn for btn in btn_option_clicks if btn > 0]
        if btn_clicks:
            next_step = 1  # Move from button selection to data selection

        if triggered_input == "btn-option":
            if not btn_clicks:
                return current_step, True

        # Check workflow and data collection for enabling/disabling the next button
        disable_next = False
        if current_step == 1 and (not workflow_selection or not data_selection):
            disable_next = True

        # Check if the Next or Back buttons were clicked
        if "next-basic-usage" in triggered_input:
            next_step = min(
                3, current_step + 1
            )  # Move to the next step, max out at step 3
        elif "back-basic-usage" in triggered_input:
            next_step = max(
                0, current_step - 1
            )  # Move to the previous step, minimum is step 0

        return next_step, disable_next


def create_stepper_output_edit(n, parent_id, active, component_data, TOKEN):
    logger.info(f"Component data: {component_data}")
    id = {"type": f"{component_data['component_type']}-component", "index": n}

    # wf_tag = return_wf_tag_from_id(component_data["wf_id"], TOKEN=TOKEN)
    # dc_tag = return_dc_tag_from_id(
    #     # workflow_id=component_data["wf_id"],
    #     data_collection_id=component_data["dc_id"],
    #     TOKEN=TOKEN,
    # )

    select_row = dbc.Row(
        [
            dbc.Col(
                # Workflow selection dropdown
                dmc.Select(
                    id={"type": "workflow-selection-label", "index": n},
                    # value=workflow_selection,
                    value=component_data["wf_id"],
                    label=html.H4(
                        [
                            DashIconify(icon="flat-color-icons:workflow"),
                            "Workflow selection",
                        ]
                    ),
                    style={
                        "height": "100%",
                        "display": "none",
                        "width": "100%",
                    },
                )
            ),
            dbc.Col(
                # Data collection selection dropdown
                dmc.Select(
                    id={
                        "type": "datacollection-selection-label",
                        "index": n,
                    },
                    # value=datacollection_selection,
                    value=component_data["dc_id"],
                    label=html.H4(
                        [
                            DashIconify(icon="bxs:data"),
                            "Data collection selection",
                        ]
                    ),
                    style={
                        "height": "100%",
                        "width": "100%",
                        "display": "none",
                    },
                )
            ),
        ],
        style={"display": "none"},
    )

    logger.info(f"Select row: {select_row}")

    df = load_deltatable_lite(
        component_data["wf_id"], component_data["dc_id"], TOKEN=TOKEN
    )
    logger.info(f"DF: {df}")

    def return_design_component(component_selected, id, df):
        if component_selected == "Figure":
            return design_figure(id, component_data=component_data)
        elif component_selected == "Card":
            return design_card(id, df)
        elif component_selected == "Interactive":
            return design_interactive(id, df)
        # elif component_selected == "Table":
        #     return design_table(id)

    component_selected = component_data["component_type"].capitalize()
    card = return_design_component(component_selected=component_selected, id=id, df=df)
    logger.info(f"Card: {card}")

    # if component_selected != "Card":
    modal_body = [select_row, dbc.Row(card)]
    # else:
    #     modal_body = [dbc.Row(card)]

    modal = dbc.Modal(
        id={"type": "modal-edit", "index": n},
        children=[
            dbc.ModalHeader(
                html.H5("Edit your dashboard component"), close_button=False
            ),
            dbc.ModalBody(
                modal_body,
                # id={"type": "modal-body-edit", "index": n},
                style={
                    "display": "flex",
                    "justify-content": "center",
                    "align-items": "center",
                    "flex-direction": "column",
                    "height": "100%",
                    "width": "100%",
                },
            ),
            dbc.ModalFooter(
                [
                    dmc.Center(
                        dmc.Button(
                            "Confirm Edit",
                            id={"type": "btn-done-edit", "index": n},
                            # id={"type": "btn-done-edit", "index": n},
                            n_clicks=0,
                            size="xl",
                            leftIcon=DashIconify(
                                icon="bi:check-circle", width=30, color="white"
                            ),
                            disabled=True,
                        )
                    ),
                ],
                style={
                    "display": "flex",
                    "justify-content": "center",
                    "align-items": "center",
                    "width": "100%",
                    "height": "100%",  # Set height to fill available space
                    "padding": "1rem",  # Optional: adjust padding for spacing
                },
            ),
        ],
        is_open=True,
        size="xl",
        backdrop=False,
        keyboard=False,
        style={
            "height": "100%",
            "width": "100%",
        },
    )
    logger.info(f"TEST MODAL: {modal}")

    return modal


def create_stepper_output(n, active):
    logger.info(f"Creating stepper output for index {n}")
    logger.info(f"Active step: {active}")

    # # Use component_data to pre-populate stepper if editing
    # component_selected = component_data.get("component_selected", "None") if component_data else "None"
    # workflow_selection = component_data.get("workflow_selection", "")
    # datacollection_selection = component_data.get("datacollection_selection", "")

    stepper_dropdowns = html.Div(
        [
            html.Hr(),
            dbc.Row(
                [
                    dbc.Col(
                        dmc.Title(
                            "Component selected:", order=3, align="left", weight=500
                        ),
                        width=4,
                    ),
                    dbc.Col(
                        dmc.Text(
                            "None",
                            id={"type": "component-selected", "index": n},
                            size="xl",
                            align="left",
                            weight=500,
                        ),
                        width=8,
                    ),
                ],
                style={"align-items": "center"},
            ),
            html.Hr(),
            dbc.Row(
                [
                    dbc.Col(
                        # Workflow selection dropdown
                        dmc.Select(
                            id={"type": "workflow-selection-label", "index": n},
                            # value=workflow_selection,
                            label=html.H4(
                                [
                                    DashIconify(icon="flat-color-icons:workflow"),
                                    "Workflow selection",
                                ]
                            ),
                            style={
                                "height": "100%",
                                "display": "inline-block",
                                "width": "100%",
                            },
                        )
                    ),
                    dbc.Col(
                        # Data collection selection dropdown
                        dmc.Select(
                            id={
                                "type": "datacollection-selection-label",
                                "index": n,
                            },
                            # value=datacollection_selection,
                            label=html.H4(
                                [
                                    DashIconify(icon="bxs:data"),
                                    "Data collection selection",
                                ]
                            ),
                            style={
                                "height": "100%",
                                "width": "100%",
                                "display": "inline-block",
                            },
                        )
                    ),
                ],
            ),
            html.Hr(),
            dbc.Row(html.Div(id={"type": "dropdown-output", "index": n})),
        ],
        style={
            "height": "100%",
            "width": "822px",
        },
    )

    buttons_list = html.Div(
        [
            html.Div(
                id={
                    "type": "buttons-list",
                    "index": n,
                }
            ),
            html.Div(
                id={
                    "type": "store-list",
                    "index": n,
                }
            ),
        ]
    )

    step_one = dmc.StepperStep(
        label="Component selection",
        description="Select your component type",
        children=buttons_list,
        id={"type": "stepper-step-2", "index": n},
    )

    step_two = dmc.StepperStep(
        label="Data selection",
        description="Select your workflow and data collection",
        children=stepper_dropdowns,
        # loading=True,
        id={"type": "stepper-step-1", "index": n},
    )
    step_three = dmc.StepperStep(
        label="Design your component",
        description="Customize your component as you wish",
        # loading=True,
        children=html.Div(
            id={
                "type": "output-stepper-step-3",
                "index": n,
            }
        ),
        id={"type": "stepper-step-3", "index": n},
    )
    step_completed = dmc.StepperCompleted(
        children=[
            dmc.Center(
                [
                    dmc.Button(
                        "Add to dashboard",
                        id={
                            "type": "btn-done",
                            "index": n,
                        },
                        n_clicks=0,
                        size="xl",
                        style={
                            "display": "block",
                            "align": "center",
                            "height": "100px",
                        },
                        leftIcon=DashIconify(
                            icon="bi:check-circle", width=30, color="white"
                        ),
                    ),
                ]
            ),
        ],
    )

    steps = [step_one, step_two, step_three, step_completed]

    stepper = dmc.Stepper(
        id={"type": "stepper-basic-usage", "index": n},
        active=active,
        # color="green",
        breakpoint="sm",
        children=steps,
    )

    stepper_footer = dmc.Group(
        position="center",
        mt="xl",
        children=[
            dmc.Button(
                "Back",
                id={"type": "back-basic-usage", "index": n},
                variant="default",
                n_clicks=0,
            ),
            dmc.Button(
                "Next step",
                id={"type": "next-basic-usage", "index": n},
                disabled=True,
                n_clicks=0,
            ),
        ],
    )

    modal = html.Div(
        [
            dbc.Modal(
                id={"type": "modal", "index": n},
                children=[
                    dbc.ModalHeader(html.H5("Design your new dashboard component")),
                    dbc.ModalBody(
                        [stepper, stepper_footer],
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
                },
            ),
        ],
        id=n,
    )
    logger.info(f"TEST MODAL: {modal}")

    return modal
