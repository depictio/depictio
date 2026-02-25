"""Stepper Part Two - Component type selection step.

This module provides callbacks for the second step of the dashboard component
creation stepper. Users select which type of component they want to add
(Figure, Card, Interactive, Table, MultiQC, or Image) via a 2x3 card grid.
"""

import dash_mantine_components as dmc
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

from depictio.dash.component_metadata import get_component_metadata, is_enabled

# Component types to show in the grid (excluding disabled Text)
_GRID_COMPONENT_TYPES = ["figure", "card", "interactive", "table", "multiqc", "image", "map"]

# Colors matching depictio-docs design
_GRID_ICON_COLORS = {
    "figure": "#9966cc",
    "card": "#45b8ac",
    "interactive": "#8bc34a",
    "table": "#6495ed",
    "multiqc": "transparent",
    "image": "#e6779f",
    "map": "#7A5DC7",
}

# Display names used as button values (must match existing callback patterns)
_DISPLAY_NAMES = {
    "figure": "Figure",
    "card": "Card",
    "interactive": "Interactive",
    "table": "Table",
    "multiqc": "MultiQC",
    "image": "Image",
    "map": "Map",
}


def _create_component_card(comp_type: str, n: str) -> html.Div:
    """Create a component selection card for the grid.

    Args:
        comp_type: Internal component type key.
        n: Unique identifier for this stepper instance.

    Returns:
        A DMC Paper card with icon, title, and description.
    """
    metadata = get_component_metadata(comp_type)
    display_name = _DISPLAY_NAMES[comp_type]
    description = metadata.get("description", "")
    icon_bg = _GRID_ICON_COLORS.get(comp_type, "#999")
    disabled = not is_enabled(comp_type)

    # Icon: image for MultiQC, DashIconify for others
    if comp_type == "multiqc":
        icon_element = html.Img(
            src="/assets/images/logos/multiqc.png",
            style={"width": "44px", "height": "44px", "objectFit": "contain"},
        )
    else:
        icon_element = DashIconify(
            icon=metadata.get("icon", "mdi:help-circle"), color="white", width=24
        )

    icon_container = html.Div(
        icon_element,
        style={
            "width": "48px",
            "height": "48px",
            "borderRadius": "12px",
            "background": icon_bg,
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "margin": "0 auto 1rem auto",
        },
    )

    # Wrap Paper in clickable div (Paper doesn't accept n_clicks in DMC 2.x)
    return html.Div(
        children=dmc.Paper(
            children=[
                icon_container,
                dmc.Text(display_name, fw="bold", size="lg", ta="center"),
                dmc.Text(description, size="sm", c="gray", ta="center", mt="xs"),
            ],
            shadow="sm",
            radius="md",
            p="lg",
            withBorder=True,
            style={
                "textAlign": "center",
                "transition": "transform 0.2s ease, box-shadow 0.2s ease",
                "opacity": 0.5 if disabled else 1,
                "height": "100%",
            },
            className="component-selection-card",
        ),
        id={"type": "btn-option", "index": n, "value": display_name},
        n_clicks=0,
        style={
            "cursor": "not-allowed" if disabled else "pointer",
            "pointerEvents": "auto" if not disabled else "none",
        },
    )


def _create_stepper_stores(n: str) -> list:
    """Create all stores needed for the stepper buttons.

    Args:
        n: Unique identifier for this stepper instance.

    Returns:
        List of dcc.Store components for tracking button state.
    """
    stores = []
    for comp_type in _GRID_COMPONENT_TYPES:
        display_name = _DISPLAY_NAMES[comp_type]
        stores.append(
            dcc.Store(
                id={"type": "store-btn-option", "index": n, "value": display_name},
                data=0,
                storage_type="session",
            )
        )
    stores.append(
        dcc.Store(id={"type": "last-button", "index": n}, data="None", storage_type="session"),
    )
    return stores


def _build_component_selection_layout(n: str) -> dmc.Stack:
    """Build the component selection UI layout as a 2x3 card grid.

    Args:
        n: Unique identifier for this stepper instance.

    Returns:
        A DMC Stack containing the grid of component cards.
    """
    cards = [_create_component_card(comp_type, n) for comp_type in _GRID_COMPONENT_TYPES]

    # Center the last card when it's alone in its row (7 items in a 3-col grid)
    if len(cards) % 3 == 1:
        cards[-1].style = {**(cards[-1].style or {}), "gridColumn": "2"}

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
                cards,
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(3, 1fr)",
                    "gap": "1.5rem",
                    "maxWidth": "900px",
                    "margin": "2rem auto",
                    "padding": "0 1rem",
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
        """Update the component type selection cards when stepper is triggered.

        Args:
            stored_add_button: Data from the add-button store containing the stepper ID.

        Returns:
            Tuple of (cards layout, store components list).

        Raises:
            PreventUpdate: If store is not yet initialized.
        """
        if not stored_add_button or "_id" not in stored_add_button:
            raise PreventUpdate

        n = stored_add_button["_id"]
        stores = _create_stepper_stores(n)
        layout = _build_component_selection_layout(n)

        return layout, stores

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
