import dash
from dash import ALL, MATCH, Input, Output, State, html

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite

# Depictio components imports - design step
from depictio.dash.modules.card_component.frontend import design_card
from depictio.dash.modules.figure_component.frontend import design_figure
from depictio.dash.modules.interactive_component.frontend import design_interactive

# Depictio utils imports
from depictio.dash.modules.table_component.frontend import design_table


def return_design_component(component_selected, id, df, btn_component):
    if component_selected == "Figure":
        return design_figure(id), btn_component
    elif component_selected == "Card":
        return design_card(id, df), btn_component
    elif component_selected == "Interactive":
        return design_interactive(id, df), btn_component
    elif component_selected == "Table":
        return design_table(id), btn_component
    elif component_selected == "JBrowse2":
        return dash.no_update, btn_component
        # return design_jbrowse(id), btn_component
    # TODO: implement the following components
    elif component_selected == "Graph":
        return dash.no_update, btn_component
    elif component_selected == "Map":
        return dash.no_update, btn_component
    else:
        return html.Div("Not implemented yet"), btn_component


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
            "JBrowse2",
            "Graph",
            "Map",
        ]

        # Ensure workflow_selection and data_collection_selection are not None
        if workflow_selection is None or data_collection_selection is None:
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
                    if last_button in ["Figure", "Card", "Interactive", "Table"]:
                        last_button_index = components_list.index(last_button)
                        component_to_render = last_button
                        component_id = ids[last_button_index]
                        logger.info(f"id: {component_id}")
                    else:
                        return html.Div("Not implemented yet"), btn_component

            # Load data once for whichever component needs to be rendered
            if component_to_render and component_id:
                df = load_deltatable_lite(wf_id, dc_id, TOKEN=TOKEN)
                logger.debug(
                    f"Stepper: Loaded delta table for {wf_id}:{dc_id} (shape: {df.shape}) for {component_to_render}"
                )
                return return_design_component(component_to_render, component_id, df, btn_component)

        return dash.no_update, btn_component if btn_component else dash.no_update
