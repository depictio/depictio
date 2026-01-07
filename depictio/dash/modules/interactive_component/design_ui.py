"""
Interactive Component - Design UI Creation Functions

This module contains functions that create the design/edit interface for interactive components.
These functions are lazy-loaded only when entering edit mode or stepper.

Functions:
- design_interactive: Creates the interactive component design UI (edit form + preview)
- create_stepper_interactive_button: Creates the interactive button for component type selection
"""

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.dash.colors import colors
from depictio.dash.component_metadata import get_component_color, get_dmc_button_color, is_enabled
from depictio.dash.modules.interactive_component.utils import build_interactive_frame
from depictio.dash.utils import UNSELECTED_STYLE


def design_interactive(id, df):
    """
    Create the interactive component design UI with edit controls and live preview.

    Args:
        id: Component ID dict (pattern-matching)
        df: DataFrame for column selection

    Returns:
        List containing the complete interactive design interface
    """
    left_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Interactive edit menu", order=5, style={"textAlign": "center"}),
                dmc.Card(
                    dmc.CardSection(
                        dmc.Stack(
                            [
                                dmc.TextInput(
                                    label="Interactive component title",
                                    id={
                                        "type": "input-title",
                                        "index": id["index"],
                                    },
                                ),
                                dmc.Select(
                                    label="Select your column",
                                    id={
                                        "type": "input-dropdown-column",
                                        "index": id["index"],
                                    },
                                    data=[{"label": e, "value": e} for e in df.columns],
                                    value=None,
                                ),
                                dmc.Select(
                                    label="Select your interactive component",
                                    id={
                                        "type": "input-dropdown-method",
                                        "index": id["index"],
                                    },
                                    value=None,
                                ),
                                dmc.Select(
                                    label="Scale type (for numerical sliders)",
                                    description="Choose between linear or logarithmic scale for slider components",
                                    id={
                                        "type": "input-dropdown-scale",
                                        "index": id["index"],
                                    },
                                    data=[
                                        {"label": "Linear", "value": "linear"},
                                        {"label": "Logarithmic (Log10)", "value": "log10"},
                                    ],
                                    value="linear",
                                    clearable=False,
                                    style={"display": "none"},  # Initially hidden
                                ),
                                dmc.ColorInput(
                                    label="Color",
                                    description="Component color (leave empty for auto theme)",
                                    id={
                                        "type": "input-color-picker",
                                        "index": id["index"],
                                    },
                                    value="",  # Empty string for DMC compliance
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
                                        colors["violet"],
                                        colors["black"],
                                    ],
                                ),
                                dmc.Select(
                                    label="Icon",
                                    description="Select an icon for your component",
                                    id={
                                        "type": "input-icon-selector",
                                        "index": id["index"],
                                    },
                                    data=[
                                        {"label": "🎚️ Slider Alt", "value": "bx:slider-alt"},
                                        {"label": "📊 Chart Line", "value": "mdi:chart-line"},
                                        {"label": "🔢 Counter", "value": "mdi:counter"},
                                        {"label": "🌡️ Thermometer", "value": "mdi:thermometer"},
                                        {"label": "💧 Water", "value": "mdi:water"},
                                        {"label": "🧪 Flask", "value": "mdi:flask"},
                                        {"label": "💨 Air Filter", "value": "mdi:air-filter"},
                                        {"label": "⚡ Flash", "value": "mdi:flash"},
                                        {"label": "📊 Gauge", "value": "mdi:gauge"},
                                        {"label": "💦 Water Percent", "value": "mdi:water-percent"},
                                        {"label": "📏 Ruler", "value": "mdi:ruler"},
                                        {"label": "🌫️ Blur", "value": "mdi:blur"},
                                        {"label": "🌿 Leaf", "value": "mdi:leaf"},
                                        {"label": "✅ Check Circle", "value": "mdi:check-circle"},
                                        {"label": "🎯 Target", "value": "mdi:target"},
                                        {
                                            "label": "🎪 Bullseye Arrow",
                                            "value": "mdi:bullseye-arrow",
                                        },
                                        {"label": "⚗️ Flask Empty", "value": "mdi:flask-empty"},
                                        {"label": "🛡️ Shield Check", "value": "mdi:shield-check"},
                                        {
                                            "label": "📈 Chart Bell Curve",
                                            "value": "mdi:chart-bell-curve",
                                        },
                                        {"label": "🔗 Scatter Plot", "value": "mdi:scatter-plot"},
                                        {"label": "⚠️ Alert Circle", "value": "mdi:alert-circle"},
                                        {"label": "📡 Sine Wave", "value": "mdi:sine-wave"},
                                        {"label": "🧬 Beaker", "value": "mdi:beaker"},
                                        {"label": "⚙️ Speedometer", "value": "mdi:speedometer"},
                                        {"label": "⚡ Flash Outline", "value": "mdi:flash-outline"},
                                        {"label": "📊 Trending Up", "value": "mdi:trending-up"},
                                        {"label": "🧬 DNA", "value": "mdi:dna"},
                                        {
                                            "label": "🗺️ Map Marker Path",
                                            "value": "mdi:map-marker-path",
                                        },
                                        {"label": "📋 Content Copy", "value": "mdi:content-copy"},
                                        {"label": "🔽 Select", "value": "mdi:form-select"},
                                        {"label": "🔘 Radio", "value": "mdi:radiobox-marked"},
                                        {"label": "☑️ Checkbox", "value": "mdi:checkbox-marked"},
                                        {"label": "🔀 Switch", "value": "mdi:toggle-switch"},
                                        {"label": "📅 Calendar", "value": "mdi:calendar-range"},
                                    ],
                                    value="bx:slider-alt",
                                    searchable=True,
                                    clearable=False,
                                ),
                                dmc.Select(
                                    label="Title Size",
                                    description="Choose the size of the component title",
                                    id={
                                        "type": "input-title-size",
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
                                dmc.NumberInput(
                                    label="Number of marks (for sliders)",
                                    description="Choose how many marks to display on the slider",
                                    id={
                                        "type": "input-number-marks",
                                        "index": id["index"],
                                    },
                                    value=2,
                                    min=2,
                                    max=10,
                                    step=1,
                                    style={"display": "none"},  # Initially hidden
                                ),
                                html.Div(
                                    id={
                                        "type": "interactive-description",
                                        "index": id["index"],
                                    },
                                ),
                            ],
                            gap="sm",
                        ),
                        id={
                            "type": "input",
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
        style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end"},
    )
    right_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title(
                    "Resulting interactive component", order=5, style={"textAlign": "center"}
                ),
                # Add a Paper wrapper just for visual preview in stepper mode
                dmc.Paper(
                    html.Div(
                        build_interactive_frame(
                            index=id["index"], show_border=False
                        ),  # No border on the actual component
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
        style={"display": "flex", "alignItems": "center", "justifyContent": "flex-start"},
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
                        color="#666",
                    ),
                ),
            ],
            align="center",
            justify="center",
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
                    "type": "interactive-columns-description",
                    "index": id["index"],
                }
            ),
        ],
        gap="md",
        style={"marginTop": "2rem"},
    )

    interactive_row = [
        dmc.Stack(
            [main_layout, html.Hr(), bottom_section],
            gap="lg",
        ),
    ]
    return interactive_row


def create_stepper_interactive_button(n, disabled=None):
    """
    Create the stepper interactive button for component type selection.

    Args:
        n: Button index for pattern matching
        disabled (bool, optional): Override enabled state. If None, uses metadata.

    Returns:
        tuple: (button component, store component)
    """

    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("interactive")

    color = get_dmc_button_color("interactive")
    hex_color = get_component_color("interactive")

    button = dmc.Button(
        "Interactive",
        id={
            "type": "btn-option",
            "index": n,
            "value": "Interactive",
        },
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=color,
        leftSection=DashIconify(icon="bx:slider-alt", color=hex_color),
        disabled=disabled,
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Interactive",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
