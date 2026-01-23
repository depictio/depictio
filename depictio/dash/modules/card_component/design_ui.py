"""
Card Component - Design UI Creation Functions

This module contains functions that create the design/edit interface for cards.
These functions are lazy-loaded only when entering edit mode or stepper.

Functions:
- design_card: Creates the card design UI (edit form + preview)
- create_stepper_card_button: Creates the card button for component type selection
"""

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.dash.colors import colors
from depictio.dash.component_metadata import get_component_color, get_dmc_button_color, is_enabled
from depictio.dash.modules.card_component.utils import build_card_frame
from depictio.dash.utils import UNSELECTED_STYLE

# Icon options for card component icon selector
CARD_ICON_OPTIONS = [
    {"label": "Chart Line", "value": "mdi:chart-line"},
    {"label": "Thermometer", "value": "mdi:thermometer"},
    {"label": "Water", "value": "mdi:water"},
    {"label": "Flask", "value": "mdi:flask"},
    {"label": "Air Filter", "value": "mdi:air-filter"},
    {"label": "Flash", "value": "mdi:flash"},
    {"label": "Gauge", "value": "mdi:gauge"},
    {"label": "Water Percent", "value": "mdi:water-percent"},
    {"label": "Ruler", "value": "mdi:ruler"},
    {"label": "Blur", "value": "mdi:blur"},
    {"label": "Leaf", "value": "mdi:leaf"},
    {"label": "Check Circle", "value": "mdi:check-circle"},
    {"label": "Target", "value": "mdi:target"},
    {"label": "Bullseye Arrow", "value": "mdi:bullseye-arrow"},
    {"label": "Flask Empty", "value": "mdi:flask-empty"},
    {"label": "Shield Check", "value": "mdi:shield-check"},
    {"label": "Chart Bell Curve", "value": "mdi:chart-bell-curve"},
    {"label": "Scatter Plot", "value": "mdi:scatter-plot"},
    {"label": "Alert Circle", "value": "mdi:alert-circle"},
    {"label": "Counter", "value": "mdi:counter"},
    {"label": "Sine Wave", "value": "mdi:sine-wave"},
    {"label": "Beaker", "value": "mdi:beaker"},
    {"label": "Speedometer", "value": "mdi:speedometer"},
    {"label": "Flash Outline", "value": "mdi:flash-outline"},
    {"label": "Trending Up", "value": "mdi:trending-up"},
    {"label": "DNA", "value": "mdi:dna"},
    {"label": "Map Marker Path", "value": "mdi:map-marker-path"},
    {"label": "Content Copy", "value": "mdi:content-copy"},
]

# Font size options for card title
FONT_SIZE_OPTIONS = [
    {"label": "Extra Small", "value": "xs"},
    {"label": "Small", "value": "sm"},
    {"label": "Medium", "value": "md"},
    {"label": "Large", "value": "lg"},
    {"label": "Extra Large", "value": "xl"},
]

# Default color swatches for card styling
COLOR_SWATCHES = [
    colors["purple"],
    colors["blue"],
    colors["teal"],
    colors["green"],
    colors["yellow"],
    colors["orange"],
    colors["pink"],
    colors["red"],
    colors["grey"],
]


def _create_card_edit_form(index: str, df) -> dmc.Card:
    """
    Create the card edit form with all input controls.

    Args:
        index: Component index for pattern-matching.
        df: DataFrame for column selection options.

    Returns:
        dmc.Card containing all edit form controls.
    """
    return dmc.Card(
        dmc.CardSection(
            dmc.Stack(
                [
                    dmc.TextInput(
                        label="Card title",
                        id={"type": "card-input", "index": index},
                        value="",
                    ),
                    dmc.Select(
                        label="Select your column",
                        id={"type": "card-dropdown-column", "index": index},
                        data=[{"label": e, "value": e} for e in df.columns],
                        value=None,
                    ),
                    dmc.Select(
                        label="Select your aggregation method",
                        id={"type": "card-dropdown-aggregation", "index": index},
                        value=None,
                    ),
                    dmc.Stack(
                        [
                            dmc.Text("Card Styling", size="sm", fw="bold"),
                            dmc.ColorInput(
                                label="Background Color",
                                description="Card background color (leave empty for auto theme)",
                                id={"type": "card-color-background", "index": index},
                                value="",
                                format="hex",
                                placeholder="Auto (follows theme)",
                                swatches=COLOR_SWATCHES,
                            ),
                            dmc.ColorInput(
                                label="Title Color",
                                description="Card title and value text color (leave empty for auto theme)",
                                id={"type": "card-color-title", "index": index},
                                value="",
                                format="hex",
                                placeholder="Auto (follows theme)",
                                swatches=COLOR_SWATCHES + [colors["black"]],
                            ),
                            dmc.Select(
                                label="Icon",
                                description="Select an icon for your card",
                                id={"type": "card-icon-selector", "index": index},
                                data=CARD_ICON_OPTIONS,
                                value="mdi:chart-line",
                                searchable=True,
                                clearable=False,
                            ),
                            dmc.Select(
                                label="Title Font Size",
                                description="Font size for card title",
                                id={"type": "card-title-font-size", "index": index},
                                data=FONT_SIZE_OPTIONS,
                                value="md",
                                clearable=False,
                            ),
                        ],
                        gap="sm",
                    ),
                    html.Div(id={"type": "aggregation-description", "index": index}),
                ],
                gap="sm",
            ),
            id={"type": "card", "index": index},
            style={"padding": "1rem"},
        ),
        withBorder=True,
        shadow="sm",
        style={"width": "100%"},
    )


def design_card(id, df):
    """
    Create the card design UI with edit controls and live preview.

    Args:
        id: Component ID dict (pattern-matching).
        df: DataFrame for column selection.

    Returns:
        List containing the complete card design interface.
    """
    index = id["index"]

    left_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Card edit menu", order=5, style={"textAlign": "center"}),
                _create_card_edit_form(index, df),
            ],
            align="flex-end",
            justify="center",
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end"},
    )
    right_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Resulting card", order=5, style={"textAlign": "center"}),
                dmc.Paper(
                    html.Div(
                        build_card_frame(index=index, show_border=False),
                        id={"type": "component-container", "index": index},
                    ),
                    withBorder=True,
                    radius="md",
                    p="md",
                    style={"width": "100%"},
                ),
            ],
            align="flex-start",
            justify="center",
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={"display": "flex", "alignItems": "center", "justifyContent": "flex-start"},
    )

    arrow_column = dmc.GridCol(
        dmc.Stack(
            [
                html.Div(style={"height": "50px"}),
                dmc.Center(DashIconify(icon="mdi:arrow-right-bold", width=40, height=40)),
            ],
            align="start",
            justify="start",
            style={"height": "100%"},
        ),
        span="content",
        style={"display": "flex", "alignItems": "center", "justifyContent": "center"},
    )

    main_layout = dmc.Grid(
        [left_column, arrow_column, right_column],
        justify="center",
        align="center",
        gutter="md",
        style={"height": "100%", "minHeight": "300px"},
    )

    bottom_section = dmc.Stack(
        [
            dmc.Title("Data Collection - Columns description", order=5, ta="center"),
            html.Div(id={"type": "card-columns-description", "index": index}),
        ],
        gap="md",
        style={"marginTop": "2rem"},
    )

    return [dmc.Stack([main_layout, html.Hr(), bottom_section], gap="lg")]


def create_stepper_card_button(n, disabled=None):
    """
    Create the stepper card button for component type selection.

    Args:
        n: Button index for pattern matching
        disabled (bool, optional): Override enabled state. If None, uses metadata.

    Returns:
        tuple: (button component, store component)
    """

    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("card")

    color = get_dmc_button_color("card")
    hex_color = get_component_color("card")

    # Create the card button
    button = dmc.Button(
        "Card",
        id={
            "type": "btn-option",
            "index": n,
            "value": "Card",
        },
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=color,
        leftSection=DashIconify(icon="formkit:number", color=hex_color),
        disabled=disabled,
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Card",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
