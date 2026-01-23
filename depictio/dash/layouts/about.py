"""About page layout for Depictio.

This module defines the about page layout featuring:
- Resources section with GitHub and Documentation links
- Funding information (EU Marie Sklodowska-Curie, ARISE, EMBL)
- Academic partners section (SciLifeLab)
- Copyright notice
"""

import dash
import dash_mantine_components as dmc
from dash import html
from dash_iconify import DashIconify


def _create_resource_card(
    icon: str,
    title: str,
    description: str,
    button_label: str,
    button_icon: str,
    href: str,
) -> dmc.Card:
    """Create a resource card with icon, title, description, and link button.

    Args:
        icon: DashIconify icon identifier.
        title: Card title text.
        description: Card description text.
        button_label: Button text.
        button_icon: DashIconify icon for button.
        href: Link URL.

    Returns:
        A DMC Card component.
    """
    return dmc.Card(
        withBorder=True,
        shadow="md",
        radius="md",
        p="lg",
        style={
            "textAlign": "center",
            "display": "flex",
            "flexDirection": "column",
            "minHeight": "300px",
        },
        children=[
            html.Div(
                style={"flex": "1", "display": "flex", "flexDirection": "column"},
                children=[
                    dmc.Group(
                        justify="center",
                        gap="sm",
                        children=[
                            DashIconify(icon=icon, width=40),
                            dmc.Text(title, size="xl", fw="bold"),
                        ],
                    ),
                    dmc.Text(
                        description,
                        size="md",
                        c="gray",
                        mt="sm",
                        style={"flex": "1"},
                    ),
                ],
            ),
            dmc.Anchor(
                href=href,
                target="_blank",
                children=dmc.Button(
                    button_label,
                    variant="filled",
                    size="md",
                    radius="md",
                    mt="md",
                    leftSection=DashIconify(icon=button_icon, width=20),
                    styles={
                        "root": {
                            "backgroundColor": "#333333",
                            "&:hover": {"backgroundColor": "#444444"},
                        }
                    },
                ),
                style={"marginTop": "auto"},
            ),
        ],
    )


def _create_funding_card(
    image_path: str,
    title: str,
    description: str,
    href: str,
) -> dmc.Card:
    """Create a funding/partner card with logo, title, description, and link.

    Args:
        image_path: Path to logo image via dash.get_asset_url.
        title: Card title text.
        description: Card description text.
        href: Link URL.

    Returns:
        A DMC Card component.
    """
    return dmc.Card(
        withBorder=True,
        shadow="md",
        radius="md",
        p="lg",
        style={
            "textAlign": "center",
            "display": "flex",
            "flexDirection": "column",
            "minHeight": "350px",
        },
        children=[
            html.Div(
                style={"flex": "1", "display": "flex", "flexDirection": "column"},
                children=[
                    html.Img(
                        src=dash.get_asset_url(image_path),
                        style={
                            "height": "100px",
                            "objectFit": "contain",
                            "marginBottom": "10px",
                        },
                    ),
                    dmc.Text(title, size="lg", fw="bold"),
                    dmc.Text(
                        description,
                        size="sm",
                        c="gray",
                        mt="sm",
                        style={"flex": "1"},
                    ),
                ],
            ),
            dmc.Anchor(
                href=href,
                target="_blank",
                children=dmc.Button(
                    "Learn More",
                    variant="outline",
                    size="sm",
                    radius="md",
                    mt="md",
                    styles={"root": {"borderColor": "#333333", "color": "#333333"}},
                ),
                style={"marginTop": "auto"},
            ),
        ],
    )


def _create_partner_card(
    image_path: str,
    title: str,
    description: str,
    href: str,
    logo_height: str = "100px",
    text_size: str = "sm",
) -> dmc.Card:
    """Create a partner/academic card with customizable logo height.

    Args:
        image_path: Path to logo image via dash.get_asset_url.
        title: Card title text.
        description: Card description text.
        href: Link URL.
        logo_height: Height of the logo image.
        text_size: Size of the description text.

    Returns:
        A DMC Card component.
    """
    return dmc.Card(
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
            "minHeight": "300px",
        },
        children=[
            html.Div(
                style={"flex": "1", "display": "flex", "flexDirection": "column"},
                children=[
                    html.Img(
                        src=dash.get_asset_url(image_path),
                        style={
                            "height": logo_height,
                            "objectFit": "contain",
                            "marginBottom": "10px",
                        },
                    ),
                    dmc.Text(title, size="lg", fw="bold"),
                    dmc.Text(
                        description,
                        size=text_size,
                        c="gray",
                        mt="sm",
                        style={"flex": "1"},
                    ),
                ],
            ),
            dmc.Anchor(
                href=href,
                target="_blank",
                children=dmc.Button(
                    "Learn More",
                    variant="outline",
                    size="sm",
                    radius="md",
                    mt="md",
                    styles={"root": {"borderColor": "#333333", "color": "#333333"}},
                ),
                style={"marginTop": "auto"},
            ),
        ],
    )


# Layout construction
layout = dmc.Container(
    dmc.Stack(
        gap="xl",
        children=[
            # Resources section
            dmc.Paper(
                p="xl",
                radius="md",
                withBorder=False,
                shadow=None,
                mt="xl",
                children=[
                    dmc.Text("Resources", size="xl", fw="bold", ta="center", mb="md"),
                    dmc.SimpleGrid(
                        spacing="xl",
                        cols={"base": 1, "sm": 2, "lg": 2},
                        children=[
                            _create_resource_card(
                                icon="mdi:github",
                                title="GitHub Repository",
                                description="Explore the source code of Depictio on GitHub.",
                                button_label="GitHub",
                                button_icon="mdi:github-circle",
                                href="https://github.com/depictio/depictio",
                            ),
                            _create_resource_card(
                                icon="mdi:file-document",
                                title="Documentation",
                                description="Learn how to use Depictio with our comprehensive documentation.",
                                button_label="Documentation",
                                button_icon="mdi:file-document-box",
                                href="https://depictio.github.io/depictio-docs/",
                            ),
                        ],
                    ),
                ],
            ),
            # Funding section
            dmc.Paper(
                p="xl",
                radius="md",
                withBorder=False,
                shadow=None,
                mt="xl",
                children=[
                    dmc.Text("Funding", size="xl", fw="bold", ta="center", mb="xl"),
                    dmc.SimpleGrid(
                        cols={"base": 1, "sm": 2, "lg": 3},
                        spacing="xl",
                        children=[
                            _create_funding_card(
                                image_path="images/logos/EN_fundedbyEU_VERTICAL_RGB_POS.png",
                                title="Marie Sklodowska-Curie Grant",
                                description=(
                                    "This project has received funding from the European Union's "
                                    "Horizon 2020 research and innovation programme under the "
                                    "Marie Sklodowska-Curie grant agreement No 945405"
                                ),
                                href="https://marie-sklodowska-curie-actions.ec.europa.eu/",
                            ),
                            _create_funding_card(
                                image_path="images/logos/AriseLogo300dpi.png",
                                title="ARISE Programme",
                                description=(
                                    "ARISE is a postdoctoral research programme for technology "
                                    "developers, hosted at EMBL."
                                ),
                                href="https://www.embl.org/about/info/arise/",
                            ),
                            _create_funding_card(
                                image_path="images/logos/EMBL_logo_colour_DIGITAL.png",
                                title="EMBL",
                                description=(
                                    "The European Molecular Biology Laboratory is Europe's "
                                    "flagship laboratory for the life sciences."
                                ),
                                href="https://www.embl.org/",
                            ),
                        ],
                    ),
                ],
            ),
            # Academic Partners section
            dmc.Paper(
                p="xl",
                radius="md",
                withBorder=False,
                shadow=None,
                mt="xl",
                children=[
                    dmc.Text("Academic Partners", size="xl", fw="bold", ta="center", mb="xl"),
                    dmc.Center(
                        _create_partner_card(
                            image_path="images/logos/scilifelab_logo.png",
                            title="SciLifeLab Data Centre",
                            description=(
                                "SciLifeLab Data Centre provides data-driven life science "
                                "research infrastructure and expertise to accelerate open "
                                "science in Sweden and beyond."
                            ),
                            href="https://www.scilifelab.se/data/",
                            logo_height="60px",
                            text_size="md",
                        ),
                    ),
                ],
            ),
            # Copyright notice
            dmc.Text(
                "2025 Depictio. Developed by Thomas Weber. All rights reserved.",
                size="xs",
                c="gray",
                ta="center",
                mt="xl",
                mb="xl",
            ),
        ],
    ),
    size="xl",
    py="xl",
)
