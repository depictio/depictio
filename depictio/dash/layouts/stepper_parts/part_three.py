import dash
import dash_mantine_components as dmc
import httpx
from dash import ALL, MATCH, Input, Output, State, html

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite

# Depictio components imports - design step
from depictio.dash.modules.card_component.frontend import design_card
from depictio.dash.modules.figure_component.frontend import design_figure
from depictio.dash.modules.interactive_component.frontend import design_interactive
from depictio.dash.modules.multiqc_component.frontend import design_multiqc

# Depictio utils imports
from depictio.dash.modules.table_component.frontend import design_table


def return_design_component(
    component_selected, id, df, btn_component, wf_id=None, dc_id=None, local_data=None
):
    # Check if DC is MultiQC type and override component selection
    # MultiQC data collections should use standalone MultiQC component, not Figure
    if component_selected == "Figure" and dc_id and local_data:
        try:
            TOKEN = local_data.get("access_token")
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/{dc_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            if response.status_code == 200:
                dc_type = response.json().get("config", {}).get("type", "").lower()
                if dc_type == "multiqc":
                    logger.info(
                        "🔄 ROUTING: MultiQC DC detected - routing to MultiQC component instead of Figure"
                    )
                    component_selected = "MultiQC"  # Override to MultiQC
        except Exception as e:
            logger.warning(f"Failed to detect DC type for routing: {e}")

    # Wrap all components in full-width container, but give Figure extra width treatment
    if component_selected == "Figure":
        component_content = design_figure(
            id, workflow_id=wf_id, data_collection_id=dc_id, local_data=local_data
        )
        return html.Div(
            component_content, style={"width": "100%", "maxWidth": "none"}
        ), btn_component
    elif component_selected == "Card":
        component_content = design_card(id, df)
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "Interactive":
        component_content = design_interactive(id, df)
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "Table":
        component_content = design_table(id)
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "Text":
        from depictio.dash.modules.text_component.frontend import design_text

        component_content = design_text(id)

        # Extract the preview from component_content (it's the last item)
        left_content = component_content.children[:-1]  # All items except the preview
        preview_content = component_content.children[-1]  # The preview section

        # Create layout with left and right sections for text component using DMC
        text_layout = dmc.Paper(
            [
                # Left section - Instructions/Help (without preview)
                dmc.Paper(
                    dmc.Stack(left_content),
                    w="45%",
                    p="xl",
                    style={
                        "borderRight": "1px solid var(--mantine-color-gray-4)",
                    },
                ),
                # Right section - Move the good preview here
                dmc.Paper(
                    preview_content,
                    w="45%",
                    p="xl",
                ),
            ],
            w="100%",
            mih=300,
            withBorder=True,
            radius="md",
            p="xs",
            style={
                "display": "flex",
                "flexDirection": "row",
                "gap": "10px",
            },
        )

        return text_layout, btn_component
    elif component_selected == "MultiQC":
        component_content = design_multiqc(
            id, workflow_id=wf_id, data_collection_id=dc_id, local_data=local_data
        )
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "JBrowse2":
        return dash.no_update, btn_component
        # return design_jbrowse(id), btn_component
    # TODO: implement the following components
    elif component_selected == "Graph":
        return dash.no_update, btn_component
    elif component_selected == "Map":
        return dash.no_update, btn_component
    else:
        return html.Div("Not implemented yet", style={"width": "100%"}), btn_component


def register_callbacks_stepper_part_three(app):
    @app.callback(
        Output({"type": "output-stepper-step-3", "index": MATCH}, "children"),
        Output({"type": "store-btn-option", "index": MATCH, "value": ALL}, "data"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        Input({"type": "store-btn-option", "index": MATCH, "value": ALL}, "data"),
        State({"type": "btn-option", "index": MATCH, "value": ALL}, "id"),
        State({"type": "last-button", "index": MATCH}, "data"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_step_3(
        workflow_selection,
        data_collection_selection,
        btn_component,
        store_btn_component,
        ids,
        last_button,
        local_data,
    ):
        wf_id = workflow_selection
        dc_id = data_collection_selection

        if not local_data:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_data["access_token"]

        logger.info(f"workflow_selection: {workflow_selection}")
        logger.info(f"data_collection_selection: {data_collection_selection}")
        logger.info(f"btn_component: {btn_component}")
        logger.info(f"store_btn_component: {store_btn_component}")
        logger.info(f"ids: {ids}")
        logger.info(f"STEP 3 last_button: {last_button}")

        components_list = [
            "Figure",
            "Card",
            "Interactive",
            "Table",
            "Text",
            "MultiQC",
            "JBrowse2",
            "Graph",
            "Map",
        ]

        # Ensure workflow_selection and data_collection_selection are not None
        # Allow Text and MultiQC components to proceed without workflow/data collection selection
        if last_button not in ["Text", "MultiQC"] and (
            workflow_selection is None or data_collection_selection is None
        ):
            raise dash.exceptions.PreventUpdate

        # Retrieve wf_id and dc_id
        # wf_id, dc_id = return_mongoid(workflow_tag=workflow_selection, data_collection_tag=data_collection_selection, TOKEN=TOKEN)

        # Check if any button has been clicked more than stored
        # button_clicked = False
        if btn_component is not None and store_btn_component is not None:
            btn_index = [
                i for i, (x, y) in enumerate(zip(btn_component, store_btn_component)) if x > y
            ]
            # OPTIMIZATION: Load data once for both code paths to avoid duplicate loading
            df = None
            component_to_render = None
            component_id = None

            if btn_index:
                # button_clicked = True
                component_selected = components_list[btn_index[0]]
                if component_selected in [
                    "Figure",
                    "Card",
                    "Interactive",
                    "Table",
                    "Text",
                    "MultiQC",
                ]:
                    component_to_render = component_selected
                    component_id = ids[btn_index[0]]
                else:
                    return html.Div("Not implemented yet"), btn_component
            else:
                logger.info("No button clicked")
                logger.info(f"wf_id: {wf_id}")
                logger.info(f"workflow_selection: {workflow_selection}")
                logger.info(f"dc_id: {dc_id}")
                logger.info(f"data_collection_selection: {data_collection_selection}")
                logger.info(f"last_button: {last_button}")

                # Get id using components_list index, last_button and store_btn_component
                if last_button != "None":
                    if last_button in ["Figure", "Card", "Interactive", "Table", "Text", "MultiQC"]:
                        last_button_index = components_list.index(last_button)
                        component_to_render = last_button
                        component_id = ids[last_button_index]
                        logger.info(f"id: {component_id}")
                    else:
                        return html.Div("Not implemented yet"), btn_component

            # Load data once for whichever component needs to be rendered
            if component_to_render and component_id:
                if component_to_render in ["Text", "MultiQC"]:
                    # Text and MultiQC components don't need delta table data
                    df = None
                else:
                    # Check data collection type to determine if we need to load delta table
                    try:
                        # Get data collection info to check type
                        response = httpx.get(
                            f"{API_BASE_URL}/depictio/api/v1/datacollections/{dc_id}",
                            headers={"Authorization": f"Bearer {TOKEN}"},
                        )

                        if response.status_code == 200:
                            dc_info = response.json()
                            dc_type = dc_info.get("config", {}).get("type", "").lower()

                            if dc_type == "multiqc":
                                # MultiQC data collections don't have traditional tabular data for preview
                                logger.info(
                                    f"Skipping data preview for MultiQC data collection: {dc_id}"
                                )
                                df = None
                            else:
                                df = load_deltatable_lite(wf_id, dc_id, TOKEN=TOKEN)
                        else:
                            logger.warning(
                                f"Failed to get data collection info: {response.status_code}"
                            )
                            # Don't fallback immediately - try to load data but handle errors gracefully
                            try:
                                df = load_deltatable_lite(wf_id, dc_id, TOKEN=TOKEN)
                            except Exception as load_error:
                                logger.warning(
                                    f"Failed to load delta table (possibly MultiQC): {load_error}"
                                )
                                df = None
                    except Exception as e:
                        logger.warning(f"Error checking data collection type: {e}")
                        # Try to load data but handle errors gracefully
                        try:
                            df = load_deltatable_lite(wf_id, dc_id, TOKEN=TOKEN)
                        except Exception as load_error:
                            logger.warning(
                                f"Failed to load delta table (possibly MultiQC): {load_error}"
                            )
                            df = None
                if df is not None:
                    logger.debug(
                        f"Stepper: Loaded delta table for {wf_id}:{dc_id} (shape: {df.shape}) for {component_to_render}"
                    )
                else:
                    logger.debug(f"Stepper: No data required for {component_to_render} component")
                return return_design_component(
                    component_to_render, component_id, df, btn_component, wf_id, dc_id, local_data
                )

        return dash.no_update, btn_component if btn_component else dash.no_update
