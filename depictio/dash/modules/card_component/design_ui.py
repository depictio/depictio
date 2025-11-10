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


def design_card(id, df):
    """
    Create the card design UI with edit controls and live preview.

    Args:
        id: Component ID dict (pattern-matching)
        df: DataFrame for column selection

    Returns:
        List containing the complete card design interface
    """
    left_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Card edit menu", order=5, style={"textAlign": "center"}),
                dmc.Card(
                    dmc.CardSection(
                        dmc.Stack(
                            [
                                # Input for the card title
                                dmc.TextInput(
                                    label="Card title",
                                    id={
                                        "type": "card-input",
                                        "index": id["index"],
                                    },
                                    value="",
                                ),
                                # Dropdown for the column selection
                                dmc.Select(
                                    label="Select your column",
                                    id={
                                        "type": "card-dropdown-column",
                                        "index": id["index"],
                                    },
                                    data=[{"label": e, "value": e} for e in df.columns],
                                    value=None,
                                ),
                                # Dropdown for the aggregation method selection
                                dmc.Select(
                                    label="Select your aggregation method",
                                    id={
                                        "type": "card-dropdown-aggregation",
                                        "index": id["index"],
                                    },
                                    value=None,
                                ),
                                # Individual style controls
                                dmc.Stack(
                                    [
                                        dmc.Text("Card Styling", size="sm", fw="bold"),
                                        dmc.ColorInput(
                                            label="Background Color",
                                            description="Card background color (leave empty for auto theme)",
                                            id={
                                                "type": "card-color-background",
                                                "index": id["index"],
                                            },
                                            value="",
                                            format="hex",
                                            placeholder="Auto (follows theme)",
                                            swatches=[
                                                colors["purple"],
                                                colors["blue"],
                                                colors["teal"],
                                                colors["green"],
                                                colors["yellow"],
                                                colors["orange"],
                                                colors["pink"],
                                                colors["red"],
                                                colors["grey"],
                                            ],
                                        ),
                                        dmc.ColorInput(
                                            label="Title Color",
                                            description="Card title and value text color (leave empty for auto theme)",
                                            id={
                                                "type": "card-color-title",
                                                "index": id["index"],
                                            },
                                            value="",
                                            format="hex",
                                            placeholder="Auto (follows theme)",
                                            swatches=[
                                                colors["purple"],
                                                colors["blue"],
                                                colors["teal"],
                                                colors["green"],
                                                colors["yellow"],
                                                colors["orange"],
                                                colors["pink"],
                                                colors["red"],
                                                colors["grey"],
                                                colors["black"],
                                            ],
                                        ),
                                        dmc.Select(
                                            label="Icon",
                                            description="Select an icon for your card",
                                            id={
                                                "type": "card-icon-selector",
                                                "index": id["index"],
                                            },
                                            data=[
                                                {
                                                    "label": "📊 Chart Line",
                                                    "value": "mdi:chart-line",
                                                },
                                                {
                                                    "label": "🌡️ Thermometer",
                                                    "value": "mdi:thermometer",
                                                },
                                                {"label": "💧 Water", "value": "mdi:water"},
                                                {"label": "🧪 Flask", "value": "mdi:flask"},
                                                {
                                                    "label": "💨 Air Filter",
                                                    "value": "mdi:air-filter",
                                                },
                                                {"label": "⚡ Flash", "value": "mdi:flash"},
                                                {"label": "📊 Gauge", "value": "mdi:gauge"},
                                                {
                                                    "label": "💦 Water Percent",
                                                    "value": "mdi:water-percent",
                                                },
                                                {"label": "📏 Ruler", "value": "mdi:ruler"},
                                                {"label": "🌫️ Blur", "value": "mdi:blur"},
                                                {"label": "🌿 Leaf", "value": "mdi:leaf"},
                                                {
                                                    "label": "✅ Check Circle",
                                                    "value": "mdi:check-circle",
                                                },
                                                {"label": "🎯 Target", "value": "mdi:target"},
                                                {
                                                    "label": "🎪 Bullseye Arrow",
                                                    "value": "mdi:bullseye-arrow",
                                                },
                                                {
                                                    "label": "⚗️ Flask Empty",
                                                    "value": "mdi:flask-empty",
                                                },
                                                {
                                                    "label": "🛡️ Shield Check",
                                                    "value": "mdi:shield-check",
                                                },
                                                {
                                                    "label": "📈 Chart Bell Curve",
                                                    "value": "mdi:chart-bell-curve",
                                                },
                                                {
                                                    "label": "🔗 Scatter Plot",
                                                    "value": "mdi:scatter-plot",
                                                },
                                                {
                                                    "label": "⚠️ Alert Circle",
                                                    "value": "mdi:alert-circle",
                                                },
                                                {"label": "🔢 Counter", "value": "mdi:counter"},
                                                {"label": "📡 Sine Wave", "value": "mdi:sine-wave"},
                                                {"label": "🧬 Beaker", "value": "mdi:beaker"},
                                                {
                                                    "label": "⚙️ Speedometer",
                                                    "value": "mdi:speedometer",
                                                },
                                                {
                                                    "label": "⚡ Flash Outline",
                                                    "value": "mdi:flash-outline",
                                                },
                                                {
                                                    "label": "📊 Trending Up",
                                                    "value": "mdi:trending-up",
                                                },
                                                {"label": "🧬 DNA", "value": "mdi:dna"},
                                                {
                                                    "label": "🗺️ Map Marker Path",
                                                    "value": "mdi:map-marker-path",
                                                },
                                                {
                                                    "label": "📋 Content Copy",
                                                    "value": "mdi:content-copy",
                                                },
                                            ],
                                            value="mdi:chart-line",
                                            searchable=True,
                                            clearable=False,
                                        ),
                                        dmc.Select(
                                            label="Title Font Size",
                                            description="Font size for card title",
                                            id={
                                                "type": "card-title-font-size",
                                                "index": id["index"],
                                            },
                                            data=[
                                                {"label": "Extra Small", "value": "xs"},
                                                {"label": "Small", "value": "sm"},
                                                {"label": "Medium", "value": "md"},
                                                {"label": "Large", "value": "lg"},
                                                {"label": "Extra Large", "value": "xl"},
                                            ],
                                            value="md",
                                            clearable=False,
                                        ),
                                    ],
                                    gap="sm",
                                ),
                                html.Div(
                                    id={
                                        "type": "aggregation-description",
                                        "index": id["index"],
                                    },
                                ),
                            ],
                            gap="sm",
                        ),
                        id={
                            "type": "card",
                            "index": id["index"],
                        },
                        style={"padding": "1rem"},
                    ),
                    withBorder=True,
                    shadow="sm",
                    style={"width": "100%"},
                ),
            ],
            align="flex-end",  # Align to right (horizontal)
            justify="center",  # Center vertically
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "flex-end",
        },  # Align to right
    )
    right_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Resulting card", order=5, style={"textAlign": "center"}),
                # Add a Paper wrapper just for visual preview in stepper mode
                dmc.Paper(
                    html.Div(
                        build_card_frame(
                            index=id["index"], show_border=False
                        ),  # No border on actual component
                        id={
                            "type": "component-container",
                            "index": id["index"],
                        },
                    ),
                    withBorder=True,  # Show border on preview container
                    radius="md",
                    p="md",  # Add some padding for the preview
                    style={"width": "100%"},
                ),
            ],
            align="flex-start",  # Align to left (horizontal)
            justify="center",  # Center vertically
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "flex-start",
        },  # Align to left
    )
    # Arrow between columns
    arrow_column = dmc.GridCol(
        dmc.Stack(
            [
                html.Div(style={"height": "50px"}),  # Spacer to align with content
                dmc.Center(
                    DashIconify(
                        icon="mdi:arrow-right-bold",
                        width=40,
                        height=40,
                    ),
                ),
            ],
            align="start",
            justify="start",
            style={"height": "100%"},
        ),
        span="content",
        style={"display": "flex", "alignItems": "center", "justifyContent": "center"},
    )

    # Main layout with components
    main_layout = dmc.Grid(
        [left_column, arrow_column, right_column],
        justify="center",
        align="center",
        gutter="md",
        style={"height": "100%", "minHeight": "300px"},
    )

    # Bottom section with column descriptions
    bottom_section = dmc.Stack(
        [
            dmc.Title("Data Collection - Columns description", order=5, ta="center"),
            html.Div(
                id={
                    "type": "card-columns-description",
                    "index": id["index"],
                }
            ),
        ],
        gap="md",
        style={"marginTop": "2rem"},
    )

    card_row = [
        dmc.Stack(
            [main_layout, html.Hr(), bottom_section],
            gap="lg",
        ),
    ]
    return card_row


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
