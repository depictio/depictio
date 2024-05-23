from dash import html, Input, Output, State, ALL, MATCH, ctx, dcc
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from depictio.dash.modules.table_component.frontend import create_stepper_table_button
from depictio.dash.utils import UNSELECTED_STYLE
from depictio.api.v1.configs.config import logger

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
        [Output({"type": "buttons-list", "index": MATCH}, "children"), Output({"type": "store-list", "index": MATCH}, "children")],
        Input("stored-add-button", "data"),
        prevent_initial_call=True,
    )
    def update_button_list(stored_add_button):
        n = stored_add_button["count"]

        graph_stepper_button = dbc.Col(
            dmc.Button(
                "Graph",
                size="xl",
                style=UNSELECTED_STYLE,
                color="orange",
                leftIcon=DashIconify(icon="ph:graph-fill", color="white"),
                disabled=False,
            )
        )

        map_stepper_button = dbc.Col(
            dmc.Button(
                "Map",
                size="xl",
                style=UNSELECTED_STYLE,
                color="red",
                leftIcon=DashIconify(icon="gridicons:globe", color="white"),
                disabled=False,
            )
        )

        figure_stepper_button, figure_stepper_button_store = create_stepper_figure_button(n, disabled=False)
        card_stepper_button, card_stepper_button_store = create_stepper_card_button(n, disabled=False)
        interactive_stepper_button, interactive_stepper_button_store = create_stepper_interactive_button(n, disabled=False)
        table_stepper_button, table_stepper_button_store = create_stepper_table_button(n, disabled=False)
        jbrowse_stepper_button, jbrowse_stepper_button_store = create_stepper_jbrowse_button(n, disabled=False)

        standard_components = [figure_stepper_button, card_stepper_button, interactive_stepper_button, table_stepper_button]
        special_components = [jbrowse_stepper_button]
        # FIXME: remove graph and map buttons
        special_components += [graph_stepper_button, map_stepper_button]

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
        logger.info(f"Buttons list: {buttons_list}")

        store_list = [
            figure_stepper_button_store,
            card_stepper_button_store,
            interactive_stepper_button_store,
            table_stepper_button_store,
            jbrowse_stepper_button_store,
            dcc.Store(id={"type": "last-button", "index": n}, data="None", storage_type="session"),
        ]

        return buttons_list, store_list

    @app.callback(
        Output({"type": "last-button", "index": MATCH}, "data"),
        Input({"type": "btn-option", "index": ALL, "value": ALL}, "n_clicks"),
        State({"type": "last-button", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_last_button_using_btn_option_value(n_clicks, last_button):
        logger.info(f"n_clicks: {n_clicks}")
        logger.info(f"last_button: {last_button}")
        if ctx.triggered_id:
            if "value" in ctx.triggered_id:
                logger.info(f"{ctx.triggered}")
                logger.info(f"ctx.triggered_id: {ctx.triggered_id}")
                id = ctx.triggered_id["value"]
                logger.info(f"Triggered id: {id}")
                logger.info(f"Last button: {last_button}")
                return id
        else:
            return last_button
        # logger.info(f"{ctx.triggered}")
        # logger.info(f"ctx.triggered_id: {ctx.triggered_id}")
        # id = ctx.triggered_id["type"]
        # logger.info(f"Triggered id: {id}")
        # logger.info(f"Last button: {last_button}")
        # return id
