from dash import html, Input, Output, State, ALL, MATCH, ctx
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx

# Depictio imports
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN, logger


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
    )
    def set_workflow_options(n_clicks):
        logger.info(f"CTX Triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX triggered: {ctx.triggered}")

        if isinstance(ctx.triggered_id, dict):
            if ctx.triggered_id["type"] == "btn-option":
                component_selected = ctx.triggered_id["value"]

        else:
            component_selected = "None"

        all_wf_dc = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()

        mapping_component_data_collection = {
            "Table": ["Figure", "Card", "Interactive", "Table"],
            "JBrowse2": ["JBrowse2"],
        }

        logger.info(f"Component selected: {component_selected}")
        valid_wfs = sorted(
            {wf["workflow_tag"] for wf in all_wf_dc for dc in wf["data_collections"] if component_selected in mapping_component_data_collection[dc["config"]["type"]]}
        )
        logger.info(f"valid_wfs: {valid_wfs}")

        # Return the data and the first value if the data is not empty
        if valid_wfs:
            return valid_wfs, valid_wfs[0]
        else:
            return dash.no_update, dash.no_update

    @app.callback(
        Output({"type": "datacollection-selection-label", "index": MATCH}, "data"),
        Output({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "id"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        # prevent_initial_call=True,
    )
    def set_datacollection_options(selected_workflow, id, n_clicks):
        logger.info(f"CTX Triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX triggered: {ctx.triggered}")

        if isinstance(ctx.triggered_id, dict):
            if ctx.triggered_id["type"] == "btn-option":
                component_selected = ctx.triggered_id["value"]

        else:
            component_selected = "None"

        all_wf_dc = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()
        selected_wf_data = [wf for wf in all_wf_dc if wf["workflow_tag"] == selected_workflow][0]

        mapping_component_data_collection = {
            "Table": ["Figure", "Card", "Interactive", "Table"],
            "JBrowse2": ["JBrowse2"],
        }

        logger.info(f"Component selected: {component_selected}")
        valid_dcs = sorted(
            {dc["data_collection_tag"] for dc in selected_wf_data["data_collections"] if component_selected in mapping_component_data_collection[dc["config"]["type"]]}
        )
        logger.info(f"valid_dcs: {valid_dcs}")

        logger.info("ID: {}".format(id))
        if not selected_workflow:
            raise dash.exceptions.PreventUpdate

        # tmp_data = list_data_collections_for_dropdown(selected_workflow)

        # Return the data and the first value if the data is not empty
        if valid_dcs:
            return valid_dcs, valid_dcs[0]
        else:
            raise dash.exceptions.PreventUpdate

    @app.callback(
        [Output({"type": "stepper-basic-usage", "index": MATCH}, "active"), Output({"type": "next-basic-usage", "index": MATCH}, "disabled")],
        [
            Input({"type": "back-basic-usage", "index": MATCH}, "n_clicks"),
            Input({"type": "next-basic-usage", "index": MATCH}, "n_clicks"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        ],
        [State({"type": "stepper-basic-usage", "index": MATCH}, "active")],
    )
    def update_stepper(back_clicks, next_clicks, workflow_selection, data_selection, btn_option_clicks, current_step):
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

        next_step = current_step  # Default to the current step if no actions require a change

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
            next_step = min(3, current_step + 1)  # Move to the next step, max out at step 3
        elif "back-basic-usage" in triggered_input:
            next_step = max(0, current_step - 1)  # Move to the previous step, minimum is step 0

        return next_step, disable_next

    # @app.callback(
    #     Output({"type": "stepper-basic-usage", "index": MATCH}, "active"),
    #     Output({"type": "next-basic-usage", "index": MATCH}, "disabled"),
    #     Input({"type": "back-basic-usage", "index": MATCH}, "n_clicks"),
    #     Input({"type": "next-basic-usage", "index": MATCH}, "n_clicks"),
    #     Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
    #     State({"type": "stepper-basic-usage", "index": MATCH}, "active"),
    #     prevent_initial_call=True,
    # )
    # def update(back, next_, btn_component, current):
    #     if back is None and next_ is None:
    #         if btn_component is not None:
    #             disable_next = False
    #         else:
    #             disable_next = True

    #         return current, disable_next
    #     else:
    #         button_id = ctx.triggered_id
    #         step = current if current is not None else active

    #         if button_id["type"] == "back-basic-usage":
    #             step = step - 1 if step > min_step else step
    #             return step, False

    #         else:
    #             step = step + 1 if step < max_step else step
    #             return step, False


def create_stepper_output(n, active):
    logger.info(f"Creating stepper output for index {n}")
    logger.info(f"Active step: {active}")

    stepper_dropdowns = html.Div(
        [
            html.Hr(),
            dbc.Row(
                [
                    dbc.Col(dmc.Title("Component selected:", order=3, align="left", weight=500), width=4),
                    dbc.Col(dmc.Text("None", id={"type": "component-selected", "index": n}, size="xl", align="left", weight=500), width=8),
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

    # index = n
    # new_element = html.Div(
    #     [
    #         dbc.Button("Done", id={"type": "btn-done", "index": index}),
    #         html.Div(
    #             html.Div(
    #                 [
    #                     f"TEST-{index}",
    #                     # html.Div("TOTOTOTO"),
    #                     buttons_list
    #                     # stepper_dropdowns
    #                 ],
    #                 id={"type": "TEST", "index": index},
    #             ),
    #             id={"type": "component-container", "index": index},
    #         ),
    #     ]
    # )
    # logger.info(f"New element: {new_element}")

    stepper = dmc.Stepper(
        id={"type": "stepper-basic-usage", "index": n},
        active=active,
        # color="green",
        breakpoint="sm",
        children=[
            dmc.StepperStep(
                label="Component selection",
                description="Select your component type",
                children=buttons_list,
                id={"type": "stepper-step-2", "index": n},
                # icon=DashIconify(icon="icon-park-outline:puzzle", width=30, color="white"),
                # progressIcon=DashIconify(icon="icon-park-outline:puzzle", width=30, color="white"),
                # completedIcon=DashIconify(icon="icon-park-solid:puzzle", width=30, color="white"),
            ),
            dmc.StepperStep(
                label="Data selection",
                description="Select your workflow and data collection",
                children=stepper_dropdowns,
                # loading=True,
                id={"type": "stepper-step-1", "index": n},
            ),
            dmc.StepperStep(
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
            ),
            dmc.StepperCompleted(
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
                                leftIcon=DashIconify(icon="bi:check-circle", width=30, color="white"),
                            ),
                        ]
                    ),
                ],
            ),
        ],
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

    return modal
