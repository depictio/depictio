import dash_mantine_components as dmc
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import is_enabled
from depictio.dash.modules.card_component.frontend import create_stepper_card_button

# Depictio components imports - button step
from depictio.dash.modules.figure_component.frontend import create_stepper_figure_button
from depictio.dash.modules.interactive_component.frontend import create_stepper_interactive_button
from depictio.dash.modules.multiqc_component.frontend import create_stepper_multiqc_button
from depictio.dash.modules.table_component.frontend import create_stepper_table_button
from depictio.dash.modules.text_component.frontend import create_stepper_text_button


def register_callbacks_stepper_part_two(app):
    @app.callback(
        [
            Output({"type": "buttons-list", "index": MATCH}, "children"),
            Output({"type": "store-list", "index": MATCH}, "children"),
        ],
        Input("stored-add-button", "data"),
        prevent_initial_call=True,
    )
    def update_button_list(stored_add_button):
        # Guard: Skip if Store not yet initialized
        if not stored_add_button or "_id" not in stored_add_button:
            raise PreventUpdate

        n = stored_add_button["_id"]

        # Removed graph_stepper_button and map_stepper_button as they are no longer needed

        figure_stepper_button, figure_stepper_button_store = create_stepper_figure_button(
            n, disabled=not is_enabled("figure")
        )
        card_stepper_button, card_stepper_button_store = create_stepper_card_button(
            n, disabled=not is_enabled("card")
        )
        (
            interactive_stepper_button,
            interactive_stepper_button_store,
        ) = create_stepper_interactive_button(n, disabled=not is_enabled("interactive"))
        table_stepper_button, table_stepper_button_store = create_stepper_table_button(
            n, disabled=not is_enabled("table")
        )
        # Removed jbrowse_stepper_button creation as it's no longer displayed
        text_stepper_button, text_stepper_button_store = create_stepper_text_button(
            n, disabled=not is_enabled("text")
        )
        multiqc_stepper_button, multiqc_stepper_button_store = create_stepper_multiqc_button(
            n, disabled=not is_enabled("multiqc")
        )

        standard_components = [
            figure_stepper_button,
            card_stepper_button,
            interactive_stepper_button,
            table_stepper_button,
            text_stepper_button,
            multiqc_stepper_button,
        ]
        # Hide special components (JBrowse, Graph, Map) as requested
        # special_components = [jbrowse_stepper_button]
        # special_components += [graph_stepper_button, map_stepper_button]

        buttons_list = dmc.Stack(
            [
                dmc.Stack(
                    [
                        dmc.Title(
                            "Select Component Type",
                            order=3,
                            ta="center",
                            fw="bold",
                            mb="xs",
                        ),
                        dmc.Text(
                            "Choose the type of component you want to add to your dashboard",
                            size="sm",
                            c="gray",
                            ta="center",
                            mb="lg",
                        ),
                    ],
                    gap="xs",
                ),
                dmc.Divider(variant="solid"),
                # macOS dock-style component selection
                html.Div(
                    [
                        html.Div(
                            standard_components,
                            id="component-dock-container",
                            style={
                                "display": "flex",
                                "flexDirection": "column",
                                "alignItems": "flex-start",
                                "justifyContent": "center",
                                "gap": "16px",
                                "padding": "24px 0",
                                "marginLeft": "10%",  # Centered but slightly left
                                "minHeight": "60vh",  # Ensure vertical centering
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "center",
                        "alignItems": "center",
                        "minHeight": "60vh",
                    },
                ),
            ],
            gap="md",
            justify="center",
            align="center",
        )
        # logger.info(f"Buttons list: {buttons_list}")

        store_list = [
            figure_stepper_button_store,
            card_stepper_button_store,
            interactive_stepper_button_store,
            table_stepper_button_store,
            text_stepper_button_store,
            multiqc_stepper_button_store,
            dcc.Store(
                id={"type": "last-button", "index": n},
                data="None",
                storage_type="session",
            ),
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
