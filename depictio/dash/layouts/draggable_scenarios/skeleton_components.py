"""
Skeleton component utilities for progressive loading in Depictio dashboards.
This module provides skeleton placeholders that match the structure of actual components.
"""

import dash_mantine_components as dmc
from dash import html


def create_skeleton_edit_buttons(component_type="figure", component_uuid=None):
    """Create skeleton edit buttons that match the actual edit button structure."""
    buttons = [
        dmc.Skeleton(height=32, width=32, radius="sm"),  # Remove button
        dmc.Skeleton(height=32, width=32, radius="sm"),  # Edit button
        dmc.Skeleton(height=32, width=32, radius="sm"),  # Duplicate button
    ]

    # Add reset button for scatter plots
    if component_type == "figure":
        buttons.append(dmc.Skeleton(height=32, width=32, radius="sm"))  # Reset button

    return dmc.Group(buttons, grow=False, gap="xs", style={"margin-left": "12px"})


def create_skeleton_figure(component_uuid, component_metadata=None):
    """Create skeleton placeholder for figure components."""
    visu_type = component_metadata.get("visu_type", "scatter") if component_metadata else "scatter"

    return html.Div(
        [
            # Skeleton edit buttons
            create_skeleton_edit_buttons("figure", component_uuid),
            # Skeleton for the figure content
            dmc.Stack(
                [
                    # Title skeleton
                    dmc.Skeleton(height=24, width="50%", radius="sm"),
                    # Graph area skeleton - varies by visualization type
                    html.Div(
                        [
                            # Main graph skeleton
                            dmc.Skeleton(
                                height=350,
                                width="100%",
                                radius="md",
                                style={"border": "1px solid #e0e0e0"},
                            ),
                            # Loading indicator
                            html.Div(
                                [
                                    dmc.Loader(size="md", color="blue"),
                                    dmc.Text(
                                        f"Loading {visu_type} visualization...",
                                        size="sm",
                                        c="gray",
                                        style={"marginLeft": "10px"},
                                    ),
                                ],
                                style={
                                    "position": "absolute",
                                    "top": "50%",
                                    "left": "50%",
                                    "transform": "translate(-50%, -50%)",
                                    "display": "flex",
                                    "alignItems": "center",
                                    "backgroundColor": "rgba(255, 255, 255, 0.9)",
                                    "padding": "10px",
                                    "borderRadius": "5px",
                                    "boxShadow": "0 2px 8px rgba(0,0,0,0.1)",
                                },
                            ),
                        ],
                        style={"position": "relative"},
                    ),
                    # Badges skeleton (for partial data, filter applied, etc.)
                    dmc.Group(
                        [
                            dmc.Skeleton(height=24, width=80, radius="xl"),
                            dmc.Skeleton(height=24, width=90, radius="xl"),
                        ],
                        gap="md",
                        style={"marginTop": "8px"},
                    ),
                ],
                gap="md",
            ),
        ],
        style={
            "width": "100%",
            "height": "100%",
            "minHeight": "400px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "5px",
            "padding": "10px",
        },
    )


def create_skeleton_table(component_uuid, component_metadata=None):
    """Create skeleton placeholder for table components."""
    return html.Div(
        [
            # Skeleton edit buttons
            create_skeleton_edit_buttons("table", component_uuid),
            # Skeleton for the table content
            dmc.Stack(
                [
                    # Table controls skeleton
                    dmc.Group(
                        [
                            dmc.Skeleton(height=32, width=120, radius="sm"),  # Filter input
                            dmc.Skeleton(height=32, width=80, radius="sm"),  # Page size selector
                            dmc.Skeleton(height=32, width=100, radius="sm"),  # Export button
                        ],
                        gap="md",
                        style={"marginBottom": "10px"},
                    ),
                    # Table header skeleton
                    html.Div(
                        [
                            dmc.Group(
                                [
                                    dmc.Skeleton(height=20, width=80, radius="sm"),
                                    dmc.Skeleton(height=20, width=100, radius="sm"),
                                    dmc.Skeleton(height=20, width=90, radius="sm"),
                                    dmc.Skeleton(height=20, width=110, radius="sm"),
                                    dmc.Skeleton(height=20, width=85, radius="sm"),
                                ],
                                gap="md",
                                style={"padding": "8px", "backgroundColor": "#f8f9fa"},
                            ),
                        ],
                        style={"border": "1px solid #e0e0e0", "borderRadius": "4px 4px 0 0"},
                    ),
                    # Table rows skeleton
                    html.Div(
                        [
                            *[
                                dmc.Group(
                                    [
                                        dmc.Skeleton(height=16, width=80, radius="sm"),
                                        dmc.Skeleton(height=16, width=100, radius="sm"),
                                        dmc.Skeleton(height=16, width=90, radius="sm"),
                                        dmc.Skeleton(height=16, width=110, radius="sm"),
                                        dmc.Skeleton(height=16, width=85, radius="sm"),
                                    ],
                                    gap="md",
                                    style={"padding": "8px", "borderBottom": "1px solid #f0f0f0"},
                                )
                                for _ in range(8)
                            ],  # Show 8 skeleton rows
                        ],
                        style={
                            "border": "1px solid #e0e0e0",
                            "borderTop": "none",
                            "borderRadius": "0 0 4px 4px",
                        },
                    ),
                    # Pagination skeleton
                    dmc.Group(
                        [
                            dmc.Skeleton(height=32, width=60, radius="sm"),  # Previous button
                            dmc.Skeleton(height=32, width=30, radius="sm"),  # Page number
                            dmc.Skeleton(height=32, width=30, radius="sm"),  # Page number
                            dmc.Skeleton(height=32, width=30, radius="sm"),  # Page number
                            dmc.Skeleton(height=32, width=60, radius="sm"),  # Next button
                        ],
                        gap="xs",
                        style={"marginTop": "10px", "justifyContent": "center"},
                    ),
                    # Loading indicator
                    html.Div(
                        [
                            dmc.Loader(size="md", color="orange"),
                            dmc.Text(
                                "Loading table data...",
                                size="sm",
                                c="gray",
                                style={"marginLeft": "10px"},
                            ),
                        ],
                        style={
                            "position": "absolute",
                            "top": "50%",
                            "left": "50%",
                            "transform": "translate(-50%, -50%)",
                            "display": "flex",
                            "alignItems": "center",
                            "backgroundColor": "rgba(255, 255, 255, 0.9)",
                            "padding": "10px",
                            "borderRadius": "5px",
                            "boxShadow": "0 2px 8px rgba(0,0,0,0.1)",
                        },
                    ),
                ],
                gap="md",
                style={"position": "relative"},
            ),
        ],
        style={
            "width": "100%",
            "height": "100%",
            "minHeight": "400px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "5px",
            "padding": "10px",
        },
    )


def create_skeleton_interactive(component_uuid, component_metadata=None):
    """Create skeleton placeholder for interactive components."""
    return html.Div(
        [
            # Skeleton edit buttons
            create_skeleton_edit_buttons("interactive", component_uuid),
            # Skeleton for the interactive content
            dmc.Stack(
                [
                    # Component title skeleton
                    dmc.Skeleton(height=24, width="40%", radius="sm"),
                    # Interactive controls skeleton
                    dmc.Stack(
                        [
                            # Input controls
                            dmc.Group(
                                [
                                    dmc.Stack(
                                        [
                                            dmc.Skeleton(height=16, width=80, radius="sm"),  # Label
                                            dmc.Skeleton(
                                                height=36, width="100%", radius="sm"
                                            ),  # Input field
                                        ],
                                        gap="xs",
                                    ),
                                    dmc.Stack(
                                        [
                                            dmc.Skeleton(height=16, width=70, radius="sm"),  # Label
                                            dmc.Skeleton(
                                                height=36, width="100%", radius="sm"
                                            ),  # Select field
                                        ],
                                        gap="xs",
                                    ),
                                ],
                                gap="md",
                                style={"width": "100%"},
                            ),
                            # Buttons skeleton
                            dmc.Group(
                                [
                                    dmc.Skeleton(height=36, width=80, radius="sm"),  # Apply button
                                    dmc.Skeleton(height=36, width=60, radius="sm"),  # Reset button
                                ],
                                gap="md",
                                style={"marginTop": "10px"},
                            ),
                            # Output area skeleton
                            dmc.Card(
                                [
                                    dmc.Stack(
                                        [
                                            dmc.Skeleton(
                                                height=20, width="30%", radius="sm"
                                            ),  # Output title
                                            dmc.Skeleton(
                                                height=100, width="100%", radius="sm"
                                            ),  # Output content
                                        ],
                                        gap="md",
                                    ),
                                ],
                                withBorder=True,
                                shadow="sm",
                                radius="md",
                                style={"marginTop": "15px", "padding": "15px"},
                            ),
                        ],
                        gap="md",
                    ),
                    # Loading indicator
                    html.Div(
                        [
                            dmc.Loader(size="md", color="violet"),
                            dmc.Text(
                                "Loading interactive component...",
                                size="sm",
                                c="gray",
                                style={"marginLeft": "10px"},
                            ),
                        ],
                        style={
                            "position": "absolute",
                            "top": "50%",
                            "left": "50%",
                            "transform": "translate(-50%, -50%)",
                            "display": "flex",
                            "alignItems": "center",
                            "backgroundColor": "rgba(255, 255, 255, 0.9)",
                            "padding": "10px",
                            "borderRadius": "5px",
                            "boxShadow": "0 2px 8px rgba(0,0,0,0.1)",
                        },
                    ),
                ],
                gap="md",
                style={"position": "relative"},
            ),
        ],
        style={
            "width": "100%",
            "height": "100%",
            "minHeight": "300px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "5px",
            "padding": "10px",
        },
    )


def create_skeleton_card(component_uuid, component_metadata=None):
    """Create skeleton placeholder for card components."""
    return html.Div(
        [
            # Skeleton edit buttons
            create_skeleton_edit_buttons("card", component_uuid),
            # Skeleton for the card content
            dmc.Card(
                [
                    dmc.Stack(
                        [
                            # Card header skeleton
                            dmc.Group(
                                [
                                    dmc.Skeleton(height=20, width="60%", radius="sm"),  # Title
                                    dmc.Skeleton(height=16, width="30%", radius="sm"),  # Subtitle
                                ],
                                gap="xs",
                            ),
                            # Card body skeleton
                            dmc.Stack(
                                [
                                    dmc.Skeleton(
                                        height=16, width="80%", radius="sm"
                                    ),  # Content line 1
                                    dmc.Skeleton(
                                        height=16, width="90%", radius="sm"
                                    ),  # Content line 2
                                    dmc.Skeleton(
                                        height=16, width="70%", radius="sm"
                                    ),  # Content line 3
                                ],
                                gap="xs",
                                style={"marginTop": "10px"},
                            ),
                            # Card metrics skeleton
                            dmc.Group(
                                [
                                    dmc.Stack(
                                        [
                                            dmc.Skeleton(
                                                height=32, width=60, radius="sm"
                                            ),  # Big number
                                            dmc.Skeleton(height=14, width=80, radius="sm"),  # Label
                                        ],
                                        gap="xs",
                                        style={"alignItems": "center"},
                                    ),
                                    dmc.Stack(
                                        [
                                            dmc.Skeleton(
                                                height=32, width=60, radius="sm"
                                            ),  # Big number
                                            dmc.Skeleton(height=14, width=80, radius="sm"),  # Label
                                        ],
                                        gap="xs",
                                        style={"alignItems": "center"},
                                    ),
                                ],
                                gap="xl",
                                style={"marginTop": "15px"},
                            ),
                            # Loading indicator
                            html.Div(
                                [
                                    dmc.Loader(size="sm", color="green"),
                                    dmc.Text(
                                        "Loading card...",
                                        size="sm",
                                        c="gray",
                                        style={"marginLeft": "10px"},
                                    ),
                                ],
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "marginTop": "10px",
                                },
                            ),
                        ],
                        gap="md",
                    ),
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                style={"height": "100%", "padding": "15px"},
            ),
        ],
        style={
            "width": "100%",
            "height": "100%",
            "minHeight": "200px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "5px",
            "padding": "10px",
        },
    )


def create_skeleton_jbrowse(component_uuid, component_metadata=None):
    """Create skeleton placeholder for JBrowse components."""
    return html.Div(
        [
            # Skeleton edit buttons (JBrowse typically only has remove and duplicate)
            dmc.Group(
                [
                    dmc.Skeleton(height=32, width=32, radius="sm"),  # Remove button
                    dmc.Skeleton(height=32, width=32, radius="sm"),  # Duplicate button
                ],
                grow=False,
                gap="xs",
                style={"margin-left": "12px"},
            ),
            # Skeleton for the JBrowse content
            dmc.Stack(
                [
                    # JBrowse toolbar skeleton
                    dmc.Group(
                        [
                            dmc.Skeleton(height=32, width=100, radius="sm"),  # Navigation controls
                            dmc.Skeleton(height=32, width=80, radius="sm"),  # Zoom controls
                            dmc.Skeleton(height=32, width=120, radius="sm"),  # Track selector
                            dmc.Skeleton(height=32, width=90, radius="sm"),  # Settings
                        ],
                        gap="md",
                        style={"marginBottom": "10px"},
                    ),
                    # JBrowse viewer skeleton
                    html.Div(
                        [
                            # Genome browser skeleton
                            dmc.Skeleton(
                                height=400,
                                width="100%",
                                radius="md",
                                style={"border": "1px solid #e0e0e0"},
                            ),
                            # Loading indicator
                            html.Div(
                                [
                                    dmc.Loader(size="md", color="teal"),
                                    dmc.Text(
                                        "Loading genome browser...",
                                        size="sm",
                                        c="gray",
                                        style={"marginLeft": "10px"},
                                    ),
                                ],
                                style={
                                    "position": "absolute",
                                    "top": "50%",
                                    "left": "50%",
                                    "transform": "translate(-50%, -50%)",
                                    "display": "flex",
                                    "alignItems": "center",
                                    "backgroundColor": "rgba(255, 255, 255, 0.9)",
                                    "padding": "10px",
                                    "borderRadius": "5px",
                                    "boxShadow": "0 2px 8px rgba(0,0,0,0.1)",
                                },
                            ),
                        ],
                        style={"position": "relative"},
                    ),
                    # Track information skeleton
                    dmc.Group(
                        [
                            dmc.Skeleton(height=16, width=150, radius="sm"),  # Track info
                            dmc.Skeleton(height=16, width=100, radius="sm"),  # Coordinates
                        ],
                        gap="md",
                        style={"marginTop": "10px"},
                    ),
                ],
                gap="md",
            ),
        ],
        style={
            "width": "100%",
            "height": "100%",
            "minHeight": "500px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "5px",
            "padding": "10px",
        },
    )


# Skeleton component factory
skeleton_build_functions = {
    "figure": create_skeleton_figure,
    "table": create_skeleton_table,
    "interactive": create_skeleton_interactive,
    "card": create_skeleton_card,
    "jbrowse": create_skeleton_jbrowse,
}


def create_skeleton_component(component_type, component_uuid, component_metadata=None):
    """Create a skeleton component of the specified type."""
    if component_type not in skeleton_build_functions:
        # Default skeleton for unknown types
        return html.Div(
            [
                dmc.Skeleton(height=32, width=32, radius="sm"),
                dmc.Stack(
                    [
                        dmc.Skeleton(height=24, width="50%", radius="sm"),
                        dmc.Skeleton(height=200, width="100%", radius="md"),
                    ],
                    gap="md",
                ),
                html.Div(
                    [
                        dmc.Loader(size="md", color="blue"),
                        dmc.Text(f"Loading {component_type}...", size="sm", c="gray"),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "justifyContent": "center",
                        "marginTop": "10px",
                    },
                ),
            ],
            style={
                "width": "100%",
                "height": "100%",
                "minHeight": "200px",
                "backgroundColor": "var(--app-surface-color, #ffffff)",
                "border": "1px solid var(--app-border-color, #ddd)",
                "borderRadius": "5px",
                "padding": "10px",
            },
        )

    skeleton_function = skeleton_build_functions[component_type]
    return skeleton_function(component_uuid, component_metadata)
