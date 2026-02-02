"""Stepper Part Two - Component type selection step.

This module provides callbacks for the second step of the dashboard component
creation stepper. Users select which type of component they want to add
(Figure, Card, Interactive, Table, Text, or MultiQC).
"""

import dash_mantine_components as dmc
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate

from depictio.dash.component_metadata import is_enabled
from depictio.dash.modules.card_component.frontend import create_stepper_card_button

# Depictio components imports - button step
from depictio.dash.modules.figure_component.utils import create_stepper_figure_button
from depictio.dash.modules.image_component.design_ui import create_stepper_image_button
from depictio.dash.modules.interactive_component.frontend import create_stepper_interactive_button
from depictio.dash.modules.multiqc_component.frontend import create_stepper_multiqc_button
from depictio.dash.modules.table_component.frontend import create_stepper_table_button
from depictio.dash.modules.text_component.frontend import create_stepper_text_button


def _create_stepper_buttons(n: str) -> tuple[list, list]:
    """Create all component type selection buttons and their stores.

    Args:
        n: The unique identifier for this stepper instance.

    Returns:
        A tuple containing (list of button components, list of store components).
    """
    figure_btn, figure_store = create_stepper_figure_button(n, disabled=not is_enabled("figure"))
    card_btn, card_store = create_stepper_card_button(n, disabled=not is_enabled("card"))
    interactive_btn, interactive_store = create_stepper_interactive_button(
        n, disabled=not is_enabled("interactive")
    )
    table_btn, table_store = create_stepper_table_button(n, disabled=not is_enabled("table"))
    text_btn, text_store = create_stepper_text_button(n, disabled=not is_enabled("text"))
    multiqc_btn, multiqc_store = create_stepper_multiqc_button(
        n, disabled=not is_enabled("multiqc")
    )
    image_btn, image_store = create_stepper_image_button(n, disabled=not is_enabled("image"))

    buttons = [figure_btn, card_btn, interactive_btn, table_btn, text_btn, multiqc_btn, image_btn]
    stores = [
        figure_store,
        card_store,
        interactive_store,
        table_store,
        text_store,
        multiqc_store,
        image_store,
        dcc.Store(id={"type": "last-button", "index": n}, data="None", storage_type="session"),
    ]
    return buttons, stores


def _build_component_selection_layout(buttons: list) -> dmc.Stack:
    """Build the component selection UI layout.

    Args:
        buttons: List of component type selection buttons.

    Returns:
        A DMC Stack containing the complete selection interface.
    """
    return dmc.Stack(
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
            html.Div(
                [
                    html.Div(
                        buttons,
                        id="component-dock-container",
                        style={
                            "display": "flex",
                            "flexDirection": "column",
                            "alignItems": "flex-start",
                            "justifyContent": "center",
                            "gap": "16px",
                            "padding": "24px 0",
                            "marginLeft": "10%",
                            "minHeight": "60vh",
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


def register_callbacks_stepper_part_two(app):
    """Register Dash callbacks for stepper part two.

    Args:
        app: The Dash application instance.
    """

    @app.callback(
        [
            Output({"type": "buttons-list", "index": MATCH}, "children"),
            Output({"type": "store-list", "index": MATCH}, "children"),
        ],
        Input("stored-add-button", "data"),
        prevent_initial_call=True,
    )
    def update_button_list(stored_add_button):
        """Update the component type selection buttons when stepper is triggered.

        Args:
            stored_add_button: Data from the add-button store containing the stepper ID.

        Returns:
            Tuple of (buttons layout, store components list).

        Raises:
            PreventUpdate: If store is not yet initialized.
        """
        if not stored_add_button or "_id" not in stored_add_button:
            raise PreventUpdate

        n = stored_add_button["_id"]
        buttons, stores = _create_stepper_buttons(n)
        buttons_layout = _build_component_selection_layout(buttons)

        return buttons_layout, stores

    @app.callback(
        Output({"type": "last-button", "index": MATCH}, "data"),
        Input({"type": "btn-option", "index": ALL, "value": ALL}, "n_clicks"),
        State({"type": "last-button", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_last_button_using_btn_option_value(n_clicks, last_button):
        """Track which component type button was last clicked.

        Args:
            n_clicks: Click counts from all component type buttons.
            last_button: Previously selected button value.

        Returns:
            The value of the most recently clicked button, or the previous value.
        """
        if ctx.triggered_id and "value" in ctx.triggered_id:
            button_id = ctx.triggered_id["value"]
            return button_id

        return last_button
