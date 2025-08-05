import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import httpx
from dash import ALL, MATCH, Input, Output, State, callback, ctx, html
from dash_iconify import DashIconify

# Depictio imports
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite

# Stepper parts imports
from depictio.dash.layouts.stepper_parts.part_one import register_callbacks_stepper_part_one
from depictio.dash.layouts.stepper_parts.part_three import register_callbacks_stepper_part_three
from depictio.dash.layouts.stepper_parts.part_two import register_callbacks_stepper_part_two
from depictio.dash.modules.card_component.frontend import design_card
from depictio.dash.modules.figure_component.frontend import design_figure
from depictio.dash.modules.interactive_component.frontend import design_interactive

min_step = 0
max_step = 3
active = 0


def register_callbacks_stepper(app):
    # Register callbacks from modular parts
    register_callbacks_stepper_part_one(app)
    register_callbacks_stepper_part_two(app)
    register_callbacks_stepper_part_three(app)

    @app.callback(
        Output({"type": "modal", "index": MATCH}, "opened"),
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
        prevent_initial_call=True,
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

        project = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{pathname.split('/')[-1]}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()
        all_wf_dc = project["workflows"]

        mapping_component_data_collection = {
            "table": ["Figure", "Card", "Interactive", "Table", "Text"],
            "jbrowse2": ["JBrowse2"],
        }

        logger.info(f"Component selected: {component_selected}")

        # Use a dictionary to track unique workflows efficiently
        valid_wfs = []
        seen_workflow_ids = set()

        for wf in all_wf_dc:
            # Check if the workflow has any matching data collection
            if (
                any(
                    component_selected in mapping_component_data_collection[dc["config"]["type"]]
                    for dc in wf["data_collections"]
                )
                and wf["id"] not in seen_workflow_ids
            ):
                seen_workflow_ids.add(wf["id"])
                valid_wfs.append(
                    {
                        "label": f"{wf['engine']['name']}/{wf['name']}",
                        "value": wf["id"],
                    }
                )

        logger.info(f"valid_wfs: {valid_wfs}")
        # Return the data and the first value if the data is not empty
        if valid_wfs:
            return valid_wfs, valid_wfs[0]["value"]
        else:
            return dash.no_update, dash.no_update

    @app.callback(
        Output({"type": "datacollection-selection-label", "index": MATCH}, "data"),
        Output({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "id"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def set_datacollection_options(selected_workflow, id, n_clicks, local_store, pathname):
        if not local_store:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_store["access_token"]

        if isinstance(ctx.triggered_id, dict):
            if ctx.triggered_id["type"] == "btn-option":
                component_selected = ctx.triggered_id["value"]
        else:
            component_selected = "None"

        project = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{pathname.split('/')[-1]}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()
        logger.info(f"Id: {id}")
        logger.info(f"Selected workflow: {selected_workflow}")
        all_wf_dc = project["workflows"]
        logger.info(f"All workflows and data collections: {all_wf_dc}")
        selected_wf_list = [wf for wf in all_wf_dc if wf["id"] == selected_workflow]
        logger.info(f"Selected workflow: {selected_wf_list}")

        if not selected_wf_list:
            logger.error(f"No workflow found with id '{selected_workflow}'")
            logger.error(f"Available workflow ids: {[wf['id'] for wf in all_wf_dc]}")
            return [], None

        selected_wf_data = selected_wf_list[0]

        mapping_component_data_collection = {
            "table": ["Figure", "Card", "Interactive", "Table", "Text"],
            "jbrowse2": ["JBrowse2"],
        }

        logger.info(f"Component selected: {component_selected}")

        # Get regular data collections
        valid_dcs = [
            {
                "label": dc["data_collection_tag"],
                "value": dc["id"],
            }
            for dc in selected_wf_data["data_collections"]
            if component_selected in mapping_component_data_collection[dc["config"]["type"]]
        ]

        # Add joined data collection options only for Figure and Table components
        # Exclude Card and Interactive components from having access to joined data collections
        allowed_components_for_joined = ["Figure", "Table"]
        if component_selected in allowed_components_for_joined:
            try:
                # Fetch available joins for this workflow
                joins_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/datacollections/get_dc_joined/{selected_workflow}",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

                if joins_response.status_code == 200:
                    joins_data = joins_response.json()
                    workflow_joins = joins_data.get(selected_workflow, {})

                    # Create a mapping from DC ID to DC tag for display names
                    dc_id_to_tag = {
                        dc["id"]: dc["data_collection_tag"]
                        for dc in selected_wf_data["data_collections"]
                    }

                    # Add joined DC options
                    for join_key, join_config in workflow_joins.items():
                        # Extract DC IDs from join key (format: "dc_id1--dc_id2")
                        dc_ids = join_key.split("--")
                        if len(dc_ids) == 2:
                            dc1_id, dc2_id = dc_ids
                            dc1_tag = dc_id_to_tag.get(dc1_id, dc1_id)
                            dc2_tag = dc_id_to_tag.get(dc2_id, dc2_id)

                            # Create display name for joined DC
                            joined_label = f"🔗 Joined: {dc1_tag} + {dc2_tag}"

                            valid_dcs.append(
                                {
                                    "label": joined_label,
                                    "value": join_key,  # Use join key as value (e.g., "dc_id1--dc_id2")
                                }
                            )

                    logger.info(f"Added {len(workflow_joins)} joined data collection options")
                else:
                    logger.warning(
                        f"Failed to fetch joins for workflow {selected_workflow}: {joins_response.status_code}"
                    )

            except Exception as e:
                logger.error(f"Error fetching joined data collections: {str(e)}")

        logger.info(f"ID: {id}")
        logger.info(f"Total valid DCs (including joins): {len(valid_dcs)}")

        if not selected_workflow:
            raise dash.exceptions.PreventUpdate

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

        next_step = current_step  # Default to the current step if no actions require a change

        # Check if any btn-option was clicked
        btn_clicks = [btn for btn in btn_option_clicks if btn > 0]
        if btn_clicks:
            # Check if Text component was selected
            if isinstance(triggered_id, dict) and triggered_id.get("type") == "btn-option":
                component_selected = triggered_id.get("value")
                logger.info(f"Component selected: {component_selected}")
                if component_selected == "Text":
                    # Text components don't need data selection, skip to design step
                    next_step = 2  # Move directly to component design step
                    logger.info(f"Text component selected, advancing to step {next_step}")
                    return next_step, False  # Return immediately to avoid further processing
                else:
                    # Other components need data selection
                    next_step = 1  # Move from button selection to data selection
            else:
                next_step = 1  # Default: move to data selection

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

    # Data preview callback for stepper
    @app.callback(
        Output({"type": "stepper-data-preview", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_stepper_data_preview(workflow_id, data_collection_id, local_data):
        """Update data preview in stepper when workflow/data collection changes."""
        if not workflow_id or not data_collection_id or not local_data:
            return html.Div()

        try:
            TOKEN = local_data["access_token"]

            # Load data preview (first 100 rows for stepper)
            df = load_deltatable_lite(
                workflow_id=workflow_id,
                data_collection_id=data_collection_id,
                TOKEN=TOKEN,
                limit_rows=100,  # Default preview size for stepper
            )

            if df is None or df.height == 0:
                return dmc.Alert(
                    "No data available for preview",
                    color="yellow",
                    title="No Data",
                )

            # Convert to pandas for AG Grid
            df_pd = df.to_pandas()

            # Handle column names with dots
            column_mapping = {}
            for col in df_pd.columns:
                if "." in col:
                    safe_col_name = col.replace(".", "_")
                    column_mapping[col] = safe_col_name
                else:
                    column_mapping[col] = col

            # Rename DataFrame columns to safe names
            df_pd = df_pd.rename(columns=column_mapping)

            # Create column definitions with improved styling
            column_defs = []
            original_columns = list(column_mapping.keys())
            for original_col in original_columns:
                safe_col = column_mapping[original_col]

                col_def = {
                    "headerName": original_col,
                    "field": safe_col,
                    "filter": True,
                    "sortable": True,
                    "resizable": True,
                    "minWidth": 120,
                }

                # Set appropriate column types
                if df_pd[safe_col].dtype in ["int64", "float64"]:
                    col_def["type"] = "numericColumn"
                elif df_pd[safe_col].dtype == "bool":
                    col_def["cellRenderer"] = "agCheckboxCellRenderer"

                column_defs.append(col_def)

            # Create enhanced AG Grid for stepper
            grid = dag.AgGrid(
                id={"type": "stepper-data-grid", "index": workflow_id},
                columnDefs=column_defs,
                rowData=df_pd.to_dict("records"),
                defaultColDef={
                    "filter": True,
                    "sortable": True,
                    "resizable": True,
                    "minWidth": 100,
                },
                dashGridOptions={
                    "pagination": True,
                    "paginationPageSize": 10,  # Smaller page size for stepper
                    "domLayout": "normal",
                    "animateRows": True,
                    "suppressMenuHide": True,
                },
                style={"height": "350px", "width": "100%"},
                className="ag-theme-alpine",
            )

            # Create summary and controls
            summary_controls = dmc.Group(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:table-eye", width=20, color="#228be6"),
                            dmc.Text("Data Preview", fw="bold", size="md"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        [
                            dmc.Text(
                                f"Showing {min(100, df.height):,} of {df.height:,} rows",
                                size="sm",
                                c="gray",
                            ),
                            dmc.Text(f"{df.width} columns", size="sm", c="gray"),
                        ],
                        gap="lg",
                    ),
                ],
                justify="space-between",
                align="center",
            )

            return dmc.Card(
                [
                    summary_controls,
                    dmc.Space(h="sm"),
                    grid,
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="md",
            )

        except Exception as e:
            logger.error(f"Error in stepper data preview: {e}")
            return dmc.Alert(
                f"Error loading data preview: {str(e)}",
                color="red",
                title="Preview Error",
            )


def create_stepper_output_edit(n, parent_id, active, component_data, TOKEN):
    # logger.info(f"Component data: {component_data}")
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

    # logger.info(f"Select row: {select_row}")

    df = load_deltatable_lite(component_data["wf_id"], component_data["dc_id"], TOKEN=TOKEN)
    # logger.info(f"DF: {df}")

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
    # logger.info(f"Card: {card}")

    # Use html.Div instead of dbc.Row to avoid Bootstrap grid constraints
    modal_body = [select_row, html.Div(card, style={"width": "100%"})]

    modal = dmc.Modal(
        id={"type": "modal-edit", "index": n},
        children=[
            html.Div(
                [
                    html.Div(
                        modal_body,
                        style=MODAL_BODY_STYLE,
                    ),
                    html.Div(
                        dmc.Group(
                            [
                                dmc.Button(
                                    "Confirm Edit",
                                    id={"type": "btn-done-edit", "index": n},
                                    n_clicks=0,
                                    size="lg",
                                    leftSection=DashIconify(icon="bi:check-circle", width=20),
                                    color="green",
                                    disabled=True,
                                ),
                            ],
                            justify="center",
                        ),
                        style=MODAL_FOOTER_STYLE,
                    ),
                ],
                style=MODAL_CONTENT_STYLE,
            )
        ],
        title=html.Div(
            [
                html.Img(
                    src=dash.get_asset_url("images/icons/favicon.ico"),
                    style={
                        "height": "34px",
                        "width": "34px",
                        "marginRight": "10px",
                        "verticalAlign": "middle",
                    },
                ),
                html.Span("Edit your dashboard component", style={"verticalAlign": "middle"}),
            ]
        ),
        opened=True,
        size=MODAL_CONFIG["size"],
        centered=True,
        withCloseButton=True,
        closeOnClickOutside=True,
        closeOnEscape=True,
        styles={
            "title": {
                "fontSize": "1.8rem",
                "fontWeight": "bold",
                "textAlign": "center",
                "width": "100%",
            },
            "header": {
                "justifyContent": "center",
                "textAlign": "center",
            },
        },
    )
    # logger.info(f"TEST MODAL: {modal}")

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
            dmc.Center(
                [
                    dmc.Title(
                        "Component selected:",
                        order=3,
                        ta="left",
                        fw="bold",
                        style={"display": "inline-block", "margin-right": "10px"},
                    ),
                    html.Div(
                        dmc.Text(
                            "None",
                            id={"type": "component-selected", "index": n},
                            size="xl",
                            ta="left",
                            fw="normal",
                        ),
                        style={"display": "inline-block"},
                    ),
                ],
                style={"align-items": "center", "display": "flex"},
            ),
            # html.Hr(),
            dmc.Space(h=20),
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
            # Data preview section
            html.Div(id={"type": "stepper-data-preview", "index": n}, style={"margin-top": "20px"}),
        ],
        # style={
        #     "height": "100%",
        #     "width": "100%",
        #     "maxWidth": "none",
        # },
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
            },
            # style={"width": "100%"},
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
                        color="green",
                        n_clicks=0,
                        size="xl",
                        style={
                            "display": "block",
                            "align": "center",
                            "height": "100px",
                        },
                        leftSection=DashIconify(icon="bi:check-circle", width=30, color="white"),
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
        # breakpoint="sm",
        children=steps,
        color="gray",
    )

    stepper_footer = dmc.Group(
        justify="center",
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
                color="gray",
            ),
        ],
    )

    modal = html.Div(
        [
            dmc.Modal(
                id={"type": "modal", "index": n},
                children=[
                    html.Div(
                        [
                            # html.H3(
                            #     "Design your new dashboard component",
                            #     style={
                            #         "marginBottom": "0",
                            #         "marginTop": "0",
                            #         "textAlign": "center",
                            #         "flexShrink": "0",
                            #         "padding": "5px 1rem 5px 1rem",
                            #         "fontSize": "1.4rem",
                            #         "backgroundColor": "#f8f9fa",
                            #         "borderBottom": "1px solid #e0e0e0",
                            #     },
                            # ),
                            html.Div(
                                stepper,
                                style=MODAL_BODY_STYLE,
                            ),
                            html.Div(
                                stepper_footer,
                                style=MODAL_FOOTER_STYLE,
                            ),
                        ],
                        style={
                            **MODAL_CONTENT_STYLE,
                            "marginTop": "-7px",  # Negative margin to move title closer to top
                        },
                    )
                ],
                title=html.Div(
                    [
                        html.Img(
                            src=dash.get_asset_url("images/icons/favicon.ico"),
                            style={
                                "height": "34px",
                                "width": "34px",
                                "marginRight": "10px",
                                "verticalAlign": "middle",
                            },
                        ),
                        html.Span(
                            "Design your new dashboard component", style={"verticalAlign": "middle"}
                        ),
                    ]
                ),
                opened=True,
                size=MODAL_CONFIG["size"],
                centered=False,  # Don't center for fullscreen
                withCloseButton=True,
                closeOnClickOutside=True,
                closeOnEscape=True,
                fullScreen=True,
                styles={
                    "title": {
                        "fontSize": "1.8rem",
                        "fontWeight": "bold",
                        "textAlign": "center",
                        "width": "100%",
                    },
                    "header": {
                        "justifyContent": "center",
                        "textAlign": "center",
                    },
                },
            ),
        ],
        id=n,
    )
    # logger.info(f"TEST MODAL: {modal}")

    return modal


# Modal configuration constants
MODAL_CONFIG = {
    "size": "90%",
    "height": "100vh",  # Full height for fullscreen
}

# Modal styles for fullscreen mode
MODAL_CONTENT_STYLE = {
    "height": "100vh",  # Full viewport height
    "minHeight": "100vh",  # Ensure full height
    "maxHeight": "100vh",  # Prevent exceeding viewport
    "overflowY": "hidden",  # Prevent content scroll - let body handle it
    "padding": "0",  # Remove padding for fullscreen
    "display": "flex",
    "flexDirection": "column",
    "boxSizing": "border-box",
}

MODAL_BODY_STYLE = {
    "flex": "1",
    "overflowY": "auto",
    "overflowX": "hidden",  # Prevent horizontal scrolling
    "padding": "0.5rem 1rem 1rem 1rem",  # Reduced top padding
    "minHeight": "0",  # Allow flex item to shrink
    "boxSizing": "border-box",
    "marginBottom": "80px",  # Space for footer
}

MODAL_FOOTER_STYLE = {
    "flexShrink": "0",
    "padding": "1rem",
    "borderTop": "1px solid var(--app-border-color, #e0e0e0)",
    "backgroundColor": "var(--app-surface-color, #f9f9f9)",
    "position": "fixed",  # Fixed to viewport
    "bottom": "0",
    "left": "0",
    "right": "0",
    "zIndex": "1000",
}


# Callback to dynamically control modal size
@callback(
    Output({"type": "modal-edit", "index": MATCH}, "size"),
    [Input({"type": "modal-edit", "index": MATCH}, "opened")],
    prevent_initial_call=True,
)
def update_modal_size(opened):
    """Update modal size when it opens."""
    return MODAL_CONFIG["size"]


@callback(
    Output({"type": "modal", "index": MATCH}, "size"),
    [Input({"type": "modal", "index": MATCH}, "opened")],
    prevent_initial_call=True,
)
def update_modal_size_regular(opened):
    """Update regular modal size when it opens."""
    return MODAL_CONFIG["size"]
