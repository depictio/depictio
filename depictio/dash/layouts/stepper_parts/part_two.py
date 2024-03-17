

import json
from dash import html, Input, Output, State, ALL, MATCH, ctx
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx
import yaml

from depictio.dash.modules.table_component.frontend import create_stepper_table_button
from depictio.dash.utils import list_workflows, get_columns_from_data_collection
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN

# Depictio components imports - button step
from depictio.dash.modules.figure_component.frontend import create_stepper_figure_button
from depictio.dash.modules.card_component.frontend import create_stepper_card_button
from depictio.dash.modules.interactive_component.frontend import (
    create_stepper_interactive_button,
)
from depictio.dash.modules.jbrowse_component.frontend import (
    create_stepper_jbrowse_button,
)

def register_callbacks_stepper_part_two(app):


    @app.callback(
        Output({"type": "buttons-list", "index": MATCH}, "children"),
        Output({"type": "store-list", "index": MATCH}, "children"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input("add-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def update_button_list(workflow_selection, data_collection_selection, n):
        print("\n\n\n")
        print("update_button_list")
        print(n)
        print(workflow_selection, data_collection_selection)
        print("\n\n\n")

        workflows = list_workflows(TOKEN)

        workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_selection][0]["_id"]
        data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection_selection][0]["_id"]

        print(data_collection_selection)

        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()

        print("dc_specs")
        print(dc_specs)

        data_collection_type = dc_specs["config"]["type"]

        if data_collection_type == "Table":
            (
                figure_stepper_button,
                figure_stepper_button_store,
            ) = create_stepper_figure_button(n, disabled=False)
            card_stepper_button, card_stepper_button_store = create_stepper_card_button(n, disabled=False)

            (
                interactive_stepper_button,
                interactive_stepper_button_store,
            ) = create_stepper_interactive_button(n, disabled=False)

            (table_stepper_button, table_stepper_button_store) = create_stepper_table_button(n, disabled=False)

            (
                jbrowse_stepper_button,
                jbrowse_stepper_button_store,
            ) = create_stepper_jbrowse_button(n, disabled=True)

            standard_components = [
                figure_stepper_button,
                card_stepper_button,
                interactive_stepper_button,
                table_stepper_button
            ]
            special_components = [jbrowse_stepper_button]

        elif data_collection_type == "JBrowse2":
            (
                figure_stepper_button,
                figure_stepper_button_store,
            ) = create_stepper_figure_button(n, disabled=True)
            card_stepper_button, card_stepper_button_store = create_stepper_card_button(n, disabled=True)

            (
                interactive_stepper_button,
                interactive_stepper_button_store,
            ) = create_stepper_interactive_button(n, disabled=True)
            (table_stepper_button, table_stepper_button_store) = create_stepper_table_button(n, disabled=True)


            (
                jbrowse_stepper_button,
                jbrowse_stepper_button_store,
            ) = create_stepper_jbrowse_button(n, disabled=False)

            standard_components = [
                figure_stepper_button,
                card_stepper_button,
                interactive_stepper_button,
                table_stepper_button
            ]
            special_components = [jbrowse_stepper_button]

        buttons_list = html.Div(
            [
                html.H5("Standard components", style={"margin-top": "20px"}),
                html.Hr(),
                dmc.Center(dbc.Row(standard_components)),
                html.Br(),
                html.H5("Special components", style={"margin-top": "20px"}),
                html.Hr(),
                dmc.Center(dbc.Row(special_components)),
            ]
        )

        store_list = [
            figure_stepper_button_store,
            card_stepper_button_store,
            interactive_stepper_button_store,
            table_stepper_button_store,
            jbrowse_stepper_button_store,
        ]
        return buttons_list, store_list



    # @app.callback(
    #     [
    #         Output({"type": "btn-option", "index": MATCH, "value": "Figure"}, "style"),
    #         Output({"type": "btn-option", "index": MATCH, "value": "Card"}, "style"),
    #         Output({"type": "btn-option", "index": MATCH, "value": "Interactive"}, "style"),
    #     ],
    #     [
    #         Input({"type": "btn-option", "index": MATCH, "value": "Figure"}, "n_clicks"),
    #         Input({"type": "btn-option", "index": MATCH, "value": "Card"}, "n_clicks"),
    #         Input({"type": "btn-option", "index": MATCH, "value": "Interactive"}, "n_clicks"),
    #     ],
    #     prevent_initial_call=True,
    # )
    # def update_button_style(figure_clicks, card_clicks, interactive_clicks):
    #     ctx_triggered = dash.callback_context.triggered

    #     # Reset all buttons to unselected style
    #     figure_style = UNSELECTED_STYLE
    #     card_style = UNSELECTED_STYLE
    #     interactive_style = UNSELECTED_STYLE

    #     # Check which button was clicked and update its style
    #     if ctx_triggered:
    #         button_id = ctx_triggered[0]["prop_id"].split(".")[0]
    #         button_value = eval(button_id)["value"]

    #         if button_value == "Figure":
    #             figure_style = SELECTED_STYLE
    #         elif button_value == "Card":
    #             card_style = SELECTED_STYLE
    #         elif button_value == "Interactive":
    #             interactive_style = SELECTED_STYLE

    #     return figure_style, card_style, interactive_style
