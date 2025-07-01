import dash
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.dash.colors import colors  # Import our color palette

# Create a Stack to vertically arrange all elements with proper spacing
layout = dmc.Container(
    dmc.Stack(
        gap="xl",  # Extra large spacing between stack items
        children=[
            # First section: Main cards (GitHub and Documentation)
            dmc.Paper(
                p="xl",  # Extra large padding
                radius="md",  # Medium border radius
                withBorder=False,  # Border around the section
                shadow=None,  # No shadow
                mt="xl",  # Margin top
                children=[
                    # Title for Repository & Documentation section
                    dmc.Text(
                        "Resources",
                        size="xl",
                        fw="bold",
                        ta="center",
                        mb="md",
                    ),
                    # Main cards in a 2-column grid
                    dmc.SimpleGrid(
                        # cols=2,  # Number of columns in the grid
                        spacing="xl",  # Space between the cards
                        cols={
                            "base": 1,
                            "sm": 2,
                            "lg": 2,
                            # "xl": 4,  # Back to original responsive sizing
                        },  # Responsive columns: 1 on mobile, 2 on small, 3 on large, 4 on xl
                        children=[
                            # Github Repository Card
                            dmc.Card(
                                withBorder=True,  # Adds a border to the card
                                shadow="md",  # Medium shadow for depth
                                radius="md",  # Medium border radius for rounded corners
                                p="lg",  # Padding inside the card
                                style={
                                    "textAlign": "center",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "minHeight": "300px",  # Use minHeight instead of fixed height
                                },  # Center-align text and elements
                                children=[
                                    # Card content wrapper
                                    html.Div(
                                        style={
                                            "flex": "1",  # Takes up available space
                                            "display": "flex",
                                            "flexDirection": "column",
                                        },
                                        children=[
                                            # Icon and Title
                                            dmc.Group(
                                                justify="center",
                                                gap="sm",
                                                children=[
                                                    DashIconify(
                                                        icon="mdi:github",
                                                        width=40,
                                                        color="#333",
                                                    ),
                                                    dmc.Text(
                                                        "GitHub Repository",
                                                        size="xl",
                                                        fw="bold",  # Bold text
                                                    ),
                                                ],
                                            ),
                                            # Description
                                            dmc.Text(
                                                "Explore the source code of Depictio on GitHub.",
                                                size="md",
                                                c="gray",
                                                mt="sm",  # Margin top for spacing
                                                style={"flex": "1"},  # Fill available space
                                            ),
                                        ],
                                    ),
                                    # GitHub Button with Link (placed at bottom)
                                    dmc.Anchor(
                                        href="https://github.com/depictio/depictio",  # Replace with your GitHub repo URL
                                        target="_blank",  # Opens the link in a new tab
                                        children=dmc.Button(
                                            "GitHub",
                                            variant="filled",
                                            size="md",
                                            radius="md",
                                            mt="md",  # Margin top for spacing
                                            leftSection=DashIconify(
                                                icon="mdi:github-circle",
                                                width=20,
                                            ),
                                            styles={
                                                "root": {
                                                    "backgroundColor": "#333333",  # GitHub dark color
                                                    "&:hover": {"backgroundColor": "#444444"},
                                                }
                                            },
                                        ),
                                        style={"marginTop": "auto"},  # Pushes button to bottom
                                    ),
                                ],
                            ),
                            # Documentation Card
                            dmc.Card(
                                withBorder=True,
                                shadow="md",
                                radius="md",
                                p="lg",  # Padding inside the card
                                style={
                                    "textAlign": "center",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "minHeight": "300px",  # Use minHeight instead of fixed height
                                },
                                children=[
                                    # Card content wrapper
                                    html.Div(
                                        style={
                                            "flex": "1",  # Takes up available space
                                            "display": "flex",
                                            "flexDirection": "column",
                                        },
                                        children=[
                                            # Icon and Title
                                            dmc.Group(
                                                justify="center",
                                                gap="sm",
                                                children=[
                                                    DashIconify(
                                                        icon="mdi:file-document",
                                                        width=40,
                                                        color="#333",
                                                    ),
                                                    dmc.Text(
                                                        "Documentation",
                                                        size="xl",
                                                        fw="bold",
                                                    ),
                                                ],
                                            ),
                                            # Description
                                            dmc.Text(
                                                "Learn how to use Depictio with our comprehensive documentation.",
                                                size="md",
                                                c="gray",
                                                mt="sm",
                                                style={"flex": "1"},  # Fill available space
                                            ),
                                        ],
                                    ),
                                    # Documentation Button with Link
                                    dmc.Anchor(
                                        href="https://depictio.github.io/depictio-docs/",  # Replace with your documentation URL
                                        target="_blank",
                                        children=dmc.Button(
                                            "Documentation",
                                            variant="filled",
                                            size="md",
                                            radius="md",
                                            mt="md",
                                            leftSection=DashIconify(
                                                icon="mdi:file-document-box",
                                                width=20,
                                            ),
                                            styles={
                                                "root": {
                                                    "backgroundColor": "#333333",  # Dark color to match
                                                    "&:hover": {"backgroundColor": "#444444"},
                                                }
                                            },
                                        ),
                                        style={"marginTop": "auto"},  # Pushes button to bottom
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            # Second section: Funding & Partners
            dmc.Paper(
                p="xl",  # Extra large padding
                radius="md",  # Medium border radius
                withBorder=False,  # Border around the section
                shadow=None,  # No shadow
                mt="xl",  # Margin top
                children=[
                    # Title for Funding & Partners section
                    dmc.Text(
                        "Funding",
                        size="xl",
                        fw="bold",
                        ta="center",
                        mb="xl",  # Margin bottom (increased spacing)
                    ),
                    # Funding & Partners cards in a 3-column grid
                    dmc.SimpleGrid(
                        # cols=3,  # Three columns for the three partner cards
                        cols={
                            "base": 1,
                            "sm": 2,
                            "lg": 3,
                            # "xl": 4,  # Back to original responsive sizing
                        },  # Responsive columns: 1 on mobile, 2 on small, 3 on large, 4 on xl
                        spacing="xl",  # Space between cards
                        # breakpoints=[
                        #     {"maxWidth": 1200, "cols": 3, "spacing": "md"},
                        #     {"maxWidth": 980, "cols": 2, "spacing": "md"},
                        #     {"maxWidth": 755, "cols": 1, "spacing": "md"},
                        # ],  # Responsive design
                        children=[
                            # Marie Skłodowska-Curie grant Card
                            dmc.Card(
                                withBorder=True,
                                shadow="md",
                                radius="md",
                                p="lg",  # Padding inside the card
                                style={
                                    "textAlign": "center",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "minHeight": "350px",  # Use minHeight instead of fixed height
                                },
                                children=[
                                    # Card content wrapper
                                    html.Div(
                                        style={
                                            "flex": "1",  # Takes up available space
                                            "display": "flex",
                                            "flexDirection": "column",
                                        },
                                        children=[
                                            # Logo Image
                                            html.Img(
                                                src=dash.get_asset_url(
                                                    "EN_fundedbyEU_VERTICAL_RGB_POS.png"
                                                ),
                                                style={
                                                    "height": "100px",
                                                    "objectFit": "contain",
                                                    "marginBottom": "10px",
                                                },
                                            ),
                                            # Title
                                            dmc.Text(
                                                "Marie Skłodowska-Curie Grant",
                                                size="lg",
                                                fw="bold",
                                            ),
                                            # Description
                                            dmc.Text(
                                                "This project has received funding from the European Union's Horizon 2020 research and innovation programme under the Marie Skłodowska-Curie grant agreement No 945405",
                                                size="sm",
                                                c="gray",
                                                mt="sm",
                                                style={"flex": "1"},  # Fill available space
                                            ),
                                        ],
                                    ),
                                    # Link Button
                                    dmc.Anchor(
                                        href="https://marie-sklodowska-curie-actions.ec.europa.eu/",
                                        target="_blank",
                                        children=dmc.Button(
                                            "Learn More",
                                            variant="outline",
                                            size="sm",
                                            radius="md",
                                            mt="md",
                                            styles={
                                                "root": {
                                                    "borderColor": "#333333",
                                                    "color": "#333333",
                                                }
                                            },
                                        ),
                                        style={"marginTop": "auto"},  # Pushes button to bottom
                                    ),
                                ],
                            ),
                            # ARISE Programme Card
                            dmc.Card(
                                withBorder=True,
                                shadow="md",
                                radius="md",
                                p="lg",  # Padding inside the card
                                style={
                                    "textAlign": "center",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "minHeight": "350px",  # Use minHeight instead of fixed height
                                },
                                children=[
                                    # Card content wrapper
                                    html.Div(
                                        style={
                                            "flex": "1",  # Takes up available space
                                            "display": "flex",
                                            "flexDirection": "column",
                                        },
                                        children=[
                                            # Logo Image
                                            html.Img(
                                                src=dash.get_asset_url("AriseLogo300dpi.png"),
                                                style={
                                                    "height": "100px",
                                                    "objectFit": "contain",
                                                    "marginBottom": "10px",
                                                },
                                            ),
                                            # Title
                                            dmc.Text(
                                                "ARISE Programme",
                                                size="lg",
                                                fw="bold",
                                            ),
                                            # Description
                                            dmc.Text(
                                                "ARISE is a postdoctoral research programme for technology developers, hosted at EMBL.",
                                                size="sm",
                                                c="gray",
                                                mt="sm",
                                                style={"flex": "1"},  # Fill available space
                                            ),
                                        ],
                                    ),
                                    # Link Button
                                    dmc.Anchor(
                                        href="https://www.embl.org/about/info/arise/",
                                        target="_blank",
                                        children=dmc.Button(
                                            "Learn More",
                                            variant="outline",
                                            size="sm",
                                            radius="md",
                                            mt="md",
                                            styles={
                                                "root": {
                                                    "borderColor": "#333333",
                                                    "color": "#333333",
                                                }
                                            },
                                        ),
                                        style={"marginTop": "auto"},  # Pushes button to bottom
                                    ),
                                ],
                            ),
                            # EMBL Card
                            dmc.Card(
                                withBorder=True,
                                shadow="md",
                                radius="md",
                                p="lg",  # Padding inside the card
                                style={
                                    "textAlign": "center",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "minHeight": "350px",  # Use minHeight instead of fixed height
                                },
                                children=[
                                    # Card content wrapper
                                    html.Div(
                                        style={
                                            "flex": "1",  # Takes up available space
                                            "display": "flex",
                                            "flexDirection": "column",
                                        },
                                        children=[
                                            # Logo Image
                                            html.Img(
                                                src=dash.get_asset_url(
                                                    "EMBL_logo_colour_DIGITAL.png"
                                                ),
                                                style={
                                                    "height": "100px",
                                                    "objectFit": "contain",
                                                    "marginBottom": "10px",
                                                },
                                            ),
                                            # Title
                                            dmc.Text(
                                                "EMBL",
                                                size="lg",
                                                fw="bold",
                                            ),
                                            # Description
                                            dmc.Text(
                                                "The European Molecular Biology Laboratory is Europe's flagship laboratory for the life sciences.",
                                                size="sm",
                                                c="gray",
                                                mt="sm",
                                                style={"flex": "1"},  # Fill available space
                                            ),
                                        ],
                                    ),
                                    # Link Button
                                    dmc.Anchor(
                                        href="https://www.embl.org/",
                                        target="_blank",
                                        children=dmc.Button(
                                            "Learn More",
                                            variant="outline",
                                            size="sm",
                                            radius="md",
                                            mt="md",
                                            styles={
                                                "root": {
                                                    "borderColor": "#333333",
                                                    "color": "#333333",
                                                }
                                            },
                                        ),
                                        style={"marginTop": "auto"},  # Pushes button to bottom
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            # NEW SECTION: Academic Partners
            dmc.Paper(
                p="xl",
                radius="md",
                withBorder=False,
                shadow=None,
                mt="xl",
                children=[
                    # Title for Academic Partners section
                    dmc.Text(
                        "Academic Partners",
                        size="xl",
                        fw="bold",
                        ta="center",
                        mb="xl",
                    ),
                    # Academic Partners card centered
                    dmc.Center(
                        dmc.Card(
                            withBorder=True,
                            shadow="md",
                            radius="md",
                            p="lg",
                            style={
                                "textAlign": "center",
                                "maxWidth": "500px",
                                "width": "100%",
                                "display": "flex",
                                "flexDirection": "column",
                                "minHeight": "300px",  # Use minHeight instead of fixed height
                            },
                            children=[
                                # Card content wrapper
                                html.Div(
                                    style={
                                        "flex": "1",  # Takes up available space
                                        "display": "flex",
                                        "flexDirection": "column",
                                    },
                                    children=[
                                        # Logo Image
                                        html.Img(
                                            src=dash.get_asset_url(
                                                "scilifelab_logo.png"  # You'll need to add this to your assets
                                            ),
                                            style={
                                                "height": "60px",
                                                "objectFit": "contain",
                                                "marginBottom": "10px",
                                            },
                                        ),
                                        # Title
                                        dmc.Text(
                                            "SciLifeLab Data Centre",
                                            size="lg",
                                            fw="bold",
                                            # style={"color": colors["blue"]},
                                        ),
                                        # Description
                                        dmc.Text(
                                            "SciLifeLab Data Centre provides data-driven life science research infrastructure and expertise to accelerate open science in Sweden and beyond.",
                                            size="md",
                                            c="gray",
                                            mt="sm",
                                            style={"flex": "1"},  # Fill available space
                                        ),
                                    ],
                                ),
                                # Link Button
                                dmc.Anchor(
                                    href="https://www.scilifelab.se/data/",
                                    target="_blank",
                                    children=dmc.Button(
                                        "Learn More",
                                        variant="outline",
                                        size="sm",
                                        radius="md",
                                        mt="md",
                                        styles={
                                            "root": {
                                                "borderColor": "#333333",
                                                "color": "#333333",
                                            }
                                        },
                                    ),
                                    style={"marginTop": "auto"},  # Pushes button to bottom
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            # Additional Resources Section
            dmc.Paper(
                p="xl",
                radius="md",
                withBorder=False,
                shadow=None,
                mt="xl",
                children=[
                    # Title for Additional Resources section
                    dmc.Text(
                        "Additional Resources",
                        size="xl",
                        fw="bold",
                        ta="center",
                        mb="xl",
                    ),
                    # Color Palette Card centered
                    dmc.Center(
                        dmc.Card(
                            withBorder=True,
                            shadow="md",
                            radius="md",
                            p="lg",
                            style={
                                "textAlign": "center",
                                "maxWidth": "500px",
                                "width": "100%",
                                "display": "flex",
                                "flexDirection": "column",
                                "minHeight": "400px",  # Use minHeight instead of fixed height
                            },
                            children=[
                                # Card content wrapper
                                html.Div(
                                    style={
                                        "flex": "1",  # Takes up available space
                                        "display": "flex",
                                        "flexDirection": "column",
                                    },
                                    children=[
                                        # Icon and Title
                                        dmc.Group(
                                            justify="center",
                                            gap="sm",
                                            children=[
                                                DashIconify(
                                                    icon="mdi:palette",
                                                    width=40,
                                                    style={"color": colors["purple"]},
                                                ),
                                                dmc.Text(
                                                    "Depictio Color Palette",
                                                    size="xl",
                                                    fw="bold",
                                                    style={"color": colors["purple"]},
                                                ),
                                            ],
                                        ),
                                        # Description
                                        dmc.Text(
                                            "Explore Depictio's brand colors for consistent design across your applications.",
                                            size="md",
                                            c="gray",
                                            mt="sm",
                                        ),
                                        # Color preview strip
                                        dmc.Group(
                                            [
                                                html.Div(
                                                    style={
                                                        "backgroundColor": color,
                                                        "height": "30px",
                                                        "flex": "1",
                                                    }
                                                )
                                                for color in [
                                                    colors["purple"],
                                                    colors["blue"],
                                                    colors["teal"],
                                                    colors["green"],
                                                    colors["yellow"],
                                                    colors["orange"],
                                                    colors["red"],
                                                ]
                                            ],
                                            grow=True,
                                            gap=0,
                                            style={
                                                "borderRadius": "8px",
                                                "overflow": "hidden",
                                                "marginTop": "20px",
                                                "marginBottom": "20px",
                                                "boxShadow": "0 2px 8px rgba(0, 0, 0, 0.1)",
                                            },
                                        ),
                                    ],
                                ),
                                # Color Palette Button with Link
                                dcc.Link(
                                    children=dmc.Button(
                                        "View Color Palette",
                                        variant="filled",
                                        size="md",
                                        radius="md",
                                        leftSection=DashIconify(
                                            icon="mdi:palette-outline",
                                            width=20,
                                        ),
                                        styles={
                                            "root": {
                                                "backgroundColor": colors["purple"],
                                                "&:hover": {
                                                    "backgroundColor": colors["purple"] + "cc"
                                                },
                                            }
                                        },
                                    ),
                                    href="/palette",  # Link to your color palette page
                                    style={"marginTop": "auto"},  # Pushes button to bottom
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            # Copyright notice
            dmc.Text(
                "© 2025 Depictio. Developed by Thomas Weber. All rights reserved.",
                size="xs",
                c="gray",
                ta="center",
                mt="xl",
                mb="xl",  # Add margin bottom to ensure space at page end
            ),
        ],
    ),
    size="xl",  # Extra large container for content
    py="xl",  # Padding top and bottom
)
