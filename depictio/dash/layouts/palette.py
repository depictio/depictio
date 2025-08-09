import dash_bootstrap_components as dbc
import dash_mantine_components as dmc

import dash
from dash import html
from dash.dependencies import Input, Output
from depictio.dash.colors import color_sequences, colors


def create_color_palette_page():
    """
    Creates a Dash Mantine layout for visualizing the Depictio color palette.
    Compatible with dash-mantine 0.12, using style overrides instead of color props.
    """

    # Color groups for organization
    color_groups = {
        "Logo Colors": [
            "purple",
            "violet",
            "blue",
            "teal",
            "green",
            "yellow",
            "orange",
            "pink",
        ],
        "Fitted Colors": ["red", "black"],
    }

    # Create color swatches
    color_sections = []

    for group_name, color_names in color_groups.items():
        color_cards = []

        for color_name in color_names:
            color_value = colors[color_name]

            # Create a color card using available components
            color_card = dmc.Paper(
                children=[
                    # Color swatch - using html.Div instead of Box
                    html.Div(
                        style={
                            "backgroundColor": color_value,
                            "height": "100px",
                            "width": "100%",
                            "borderRadius": "8px 8px 0 0",
                        }
                    ),
                    # Color info
                    html.Div(
                        children=[
                            dmc.Text(
                                color_name.capitalize(),
                                fw="normal",
                                size="md",
                            ),
                            dmc.Text(
                                color_value,
                                c="gray",
                                size="sm",
                                style={"fontFamily": "monospace"},
                            ),
                        ],
                        style={"padding": "16px"},
                    ),
                ],
                radius="lg",
                shadow="sm",
                withBorder=True,
                style={"overflow": "hidden"},
            )

            color_cards.append(
                dbc.Col(
                    color_card,
                    lg=3,
                    md=4,
                    sm=6,
                    xs=12,
                    className="mb-4",
                )
            )

        section = html.Div(
            [
                dmc.Title(
                    group_name,
                    order=3,
                    style={"marginBottom": "16px", "color": colors["blue"]},
                ),
                dbc.Row(color_cards),
            ],
            style={"marginBottom": "32px"},
        )

        color_sections.append(section)

    # Create color sequences visualization
    sequences = [
        {"name": "Main Sequence", "colors": color_sequences["main"]},
        {"name": "Cool Colors", "colors": color_sequences["cool"]},
        {"name": "Warm Colors", "colors": color_sequences["warm"]},
        {"name": "Alert Colors", "colors": color_sequences["alert"]},
    ]

    sequence_items = []

    for seq in sequences:
        # Create color strips using Group and html.Div
        color_boxes = []
        for color in seq["colors"]:
            color_boxes.append(
                html.Div(
                    style={
                        "backgroundColor": color,
                        "height": "50px",
                        "flex": "1",
                    }
                )
            )

        color_strip = dmc.Group(
            color_boxes,
            grow=True,
            gap=None,
            style={
                "borderRadius": "8px",
                "overflow": "hidden",
                "boxShadow": "0 2px 8px rgba(0, 0, 0, 0.1)",
            },
        )

        sequence_item = html.Div(
            [
                dmc.Text(seq["name"], fw="normal", size="md", style={"marginBottom": "8px"}),
                color_strip,
            ],
            style={"marginBottom": "24px"},
        )

        sequence_items.append(sequence_item)

    # Button examples with style override instead of color prop
    button_examples = dmc.Paper(
        children=[
            dmc.Title(
                "Button Examples",
                order=3,
                style={"marginBottom": "16px", "color": colors["blue"]},
            ),
            dmc.Group(
                [
                    # Using style override for custom colors
                    dmc.Button(
                        "Logout",
                        variant="filled",
                        radius="md",
                        styles={
                            "root": {
                                "backgroundColor": colors["red"],
                                "&:hover": {"backgroundColor": colors["red"] + "cc"},
                            }
                        },
                    ),
                    dmc.Button(
                        "Edit Password",
                        variant="filled",
                        radius="md",
                        styles={
                            "root": {
                                "backgroundColor": colors["blue"],
                                "&:hover": {"backgroundColor": colors["blue"] + "cc"},
                            }
                        },
                    ),
                    dmc.Button(
                        "CLI Agents",
                        variant="filled",
                        radius="md",
                        styles={
                            "root": {
                                "backgroundColor": colors["green"],
                                "&:hover": {"backgroundColor": colors["green"] + "cc"},
                            }
                        },
                    ),
                    dmc.Button(
                        "Warning",
                        variant="filled",
                        radius="md",
                        styles={
                            "root": {
                                "backgroundColor": colors["orange"],
                                "&:hover": {"backgroundColor": colors["orange"] + "cc"},
                            }
                        },
                    ),
                    dmc.Button(
                        "Primary Action",
                        variant="filled",
                        radius="md",
                        styles={
                            "root": {
                                "backgroundColor": colors["purple"],
                                "&:hover": {"backgroundColor": colors["purple"] + "cc"},
                            }
                        },
                    ),
                ],
                gap="md",
                # spacing="md",
            ),
            html.Div(style={"height": "20px"}),  # Spacer instead of Space
            dmc.Title(
                "Alert Examples",
                order=3,
                style={"marginBottom": "16px", "color": colors["blue"]},
            ),
            html.Div(
                [
                    # Using style override for custom colors in alerts
                    dmc.Alert(
                        "This is a success message",
                        title="Success!",
                        variant="filled",
                        style={
                            "marginBottom": "16px",
                            "backgroundColor": colors["green"],
                        },
                    ),
                    dmc.Alert(
                        "This is a warning message",
                        title="Warning!",
                        variant="filled",
                        style={
                            "marginBottom": "16px",
                            "backgroundColor": colors["orange"],
                        },
                    ),
                    dmc.Alert(
                        "This is an error message",
                        title="Error!",
                        variant="filled",
                        style={
                            "marginBottom": "16px",
                            "backgroundColor": colors["red"],
                        },
                    ),
                    dmc.Alert(
                        "This is an information message",
                        title="Information",
                        variant="filled",
                        style={
                            "marginBottom": "16px",
                            "backgroundColor": colors["blue"],
                        },
                    ),
                ],
            ),
        ],
        p="xl",
        radius="lg",
        shadow="sm",
        withBorder=True,
        style={"marginBottom": "32px"},
    )

    # Putting it all together
    color_palette_layout = dbc.Container(
        [
            dmc.Title(
                "Depictio Color Palette",
                order=1,
                style={
                    "marginBottom": "30px",
                    "marginTop": "20px",
                    "color": colors["purple"],
                },
            ),
            dmc.Text(
                "This page showcases the Depictio brand color palette for consistent use across the application.",
                size="lg",
                c="gray",
                style={"marginBottom": "32px"},
            ),
            *color_sections,
            dmc.Title(
                "Color Combinations",
                order=2,
                style={"marginBottom": "24px", "color": colors["blue"]},
            ),
            html.Div(sequence_items),
            button_examples,
        ],
        fluid=True,
        className="py-4",
    )

    return color_palette_layout


# Integration into your app: Simple iframe approach
def create_iframe_palette_page():
    """
    Creates a page that embeds a React component using an iframe.
    This is the easiest way to directly use a React component in Dash.
    """
    # Add this HTML file to your assets folder
    iframe_layout = dbc.Container(
        [
            dmc.Title(
                "Depictio Color Palette",
                order=1,
                style={
                    "marginBottom": "20px",
                    "marginTop": "20px",
                    "color": colors["purple"],
                },
            ),
            html.Iframe(
                src="/assets/color_palette.html",  # Path to the HTML file we created
                style={
                    "width": "100%",
                    "height": "800px",
                    "border": "none",
                    "borderRadius": "8px",
                    "boxShadow": "0 2px 8px rgba(0, 0, 0, 0.1)",
                },
            ),
        ],
        fluid=True,
        className="py-4",
    )

    return iframe_layout


# Sample function to register the page in your Dash app
def register_color_palette_page(app):
    """
    Registers a route for the color palette page.
    """

    @app.callback(Output("page-content", "children"), [Input("url", "pathname")])
    def display_color_palette(pathname):
        if pathname == "/palette":
            # Choose one of these approaches:
            return create_color_palette_page()  # Pure Dash Mantine approach
            # return create_iframe_palette_page()  # Iframe approach with React
        # Let other callbacks handle other routes
        return dash.no_update
