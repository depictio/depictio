import json
from dash import html, Input, Output, State, ALL, MATCH, ctx
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx
import yaml


# Depictio components imports - design step
from depictio.dash.modules.card_component.frontend import design_card
from depictio.dash.modules.interactive_component.frontend import design_interactive
from depictio.dash.modules.figure_component.frontend import design_figure
from depictio.dash.modules.jbrowse_component.frontend import design_jbrowse

# Depictio utils imports
from depictio.dash.modules.table_component.frontend import design_table
from depictio.dash.utils import join_deltatables, load_deltatable_lite, return_mongoid
from depictio.api.v1.configs.config import logger


def register_callbacks_stepper_part_three(app):

    @app.callback(
        Output({"type": "output-stepper-step-3", "index": MATCH}, "children"),
        Output({"type": "store-btn-option", "index": MATCH, "value": ALL}, "data"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        Input({"type": "store-btn-option", "index": MATCH, "value": ALL}, "data"),
        State({"type": "btn-option", "index": MATCH, "value": ALL}, "id"),
        # prevent_initial_call=True,
    )
    def update_step_3(
        workflow_selection,
        data_collection_selection,
        btn_component,
        store_btn_component,
        ids,
    ):

        logger.info(f"workflow_selection: {workflow_selection}")
        logger.info(f"data_collection_selection: {data_collection_selection}")
        logger.info(f"btn_component: {btn_component}")
        logger.info(f"store_btn_component: {store_btn_component}")
        logger.info(f"ids: {ids}")


        components_list = [
            "Figure",
            "Card",
            "Interactive",
            "Table", 
            "JBrowse2",
            "Graph",
            "Map",
        ]

        if workflow_selection is not None and data_collection_selection is not None and btn_component is not None:
            # print("update_step_2")
            # retrieve value in btn_component that is higher than the previous value in store_btn_component at the same index
            btn_index = [i for i, (x, y) in enumerate(zip(btn_component, store_btn_component)) if x > y]
            if btn_index:
                component_selected = components_list[btn_index[0]]
                id = ids[btn_index[0]]

                if component_selected not in ["JBrowse2", "Graph", "Map"]:
                    
                    # Retrive wf id and dc id
                    wf_id, dc_id = return_mongoid(workflow_tag=workflow_selection, data_collection_tag=data_collection_selection)
                    df = load_deltatable_lite(wf_id, dc_id)

                if component_selected == "Figure":
                    return design_figure(id), btn_component
                elif component_selected == "Card":
                    return design_card(id, df), btn_component
                elif component_selected == "Interactive":
                    return design_interactive(id, df), btn_component
                elif component_selected == "JBrowse2":
                    return design_jbrowse(id), btn_component
                elif component_selected == "Table":
                    return design_table(id), btn_component
                # TODO: implement the following components
                elif component_selected == "Graph":
                    return dash.no_update, dash.no_update
                elif component_selected == "Map":
                    return dash.no_update, dash.no_update
                else:
                    return html.Div("Not implemented yet"), dash.no_update

            else:
                raise dash.exceptions.PreventUpdate

        else:
            raise dash.exceptions.PreventUpdate
