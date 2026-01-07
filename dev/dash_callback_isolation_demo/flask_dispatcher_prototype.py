import dash_mantine_components as dmc
from dash import Dash, html
from flask import Flask

from pages import page1, page2

server = Flask(__name__)

# Create home page Dash app
app_home = Dash(
    __name__,
    server=server,
    url_base_pathname='/',
    suppress_callback_exceptions=True,
)

# Create independent Dash apps with URL base paths and debug mode
app1 = Dash(
    __name__,
    server=server,
    url_base_pathname='/page1/',
    suppress_callback_exceptions=True,
)
app2 = Dash(
    __name__,
    server=server,
    url_base_pathname='/page2/',
    suppress_callback_exceptions=True,
)

# Home page layout with Mantine UI
app_home.layout = dmc.MantineProvider(
    [
        dmc.Container(
            [
                dmc.Stack(
                    [
                        # Header
                        dmc.Group(
                            [
                                dmc.ThemeIcon(
                                    html.Span("🏠", style={"fontSize": "24px"}),
                                    size="xl",
                                    radius="md",
                                    variant="light",
                                ),
                                dmc.Title("Dash Multi-App Demo", order=1, c="blue"),
                            ],
                            gap="md",
                        ),
                        # Description
                        dmc.Text(
                            "This demonstrates true callback isolation using Flask to host multiple independent Dash applications.",
                            size="lg",
                            c="dimmed",
                        ),
                        # Navigation cards
                        dmc.SimpleGrid(
                            cols=2,
                            spacing="lg",
                            children=[
                                dmc.Card(
                                    [
                                        dmc.Group(
                                            [
                                                dmc.ThemeIcon(
                                                    html.Span("📊", style={"fontSize": "32px"}),
                                                    size=60,
                                                    radius="md",
                                                    variant="light",
                                                    color="blue",
                                                ),
                                                dmc.Stack(
                                                    [
                                                        dmc.Title("Page 1", order=3),
                                                        dmc.Text(
                                                            "Independent Dash app with isolated callbacks",
                                                            size="sm",
                                                            c="dimmed",
                                                        ),
                                                    ],
                                                    gap=5,
                                                ),
                                            ],
                                            mb="md",
                                        ),
                                        dmc.Anchor(
                                            dmc.Button(
                                                "Go to Page 1",
                                                fullWidth=True,
                                                variant="light",
                                                color="blue",
                                                rightSection=html.Span("→"),
                                            ),
                                            href="/page1/",
                                            refresh=True,
                                        ),
                                    ],
                                    shadow="sm",
                                    padding="lg",
                                    radius="md",
                                    withBorder=True,
                                ),
                                dmc.Card(
                                    [
                                        dmc.Group(
                                            [
                                                dmc.ThemeIcon(
                                                    html.Span("📈", style={"fontSize": "32px"}),
                                                    size=60,
                                                    radius="md",
                                                    variant="light",
                                                    color="red",
                                                ),
                                                dmc.Stack(
                                                    [
                                                        dmc.Title("Page 2", order=3),
                                                        dmc.Text(
                                                            "Independent Dash app with isolated callbacks",
                                                            size="sm",
                                                            c="dimmed",
                                                        ),
                                                    ],
                                                    gap=5,
                                                ),
                                            ],
                                            mb="md",
                                        ),
                                        dmc.Anchor(
                                            dmc.Button(
                                                "Go to Page 2",
                                                fullWidth=True,
                                                variant="light",
                                                color="red",
                                                rightSection=html.Span("→"),
                                            ),
                                            href="/page2/",
                                            refresh=True,
                                        ),
                                    ],
                                    shadow="sm",
                                    padding="lg",
                                    radius="md",
                                    withBorder=True,
                                ),
                            ],
                        ),
                        # Architecture info
                        dmc.Alert(
                            [
                                dmc.Title("Architecture", order=4, mb="sm"),
                                dmc.List(
                                    [
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("Flask Server: "),
                                                        "Routes requests to different Dash apps",
                                                    ]
                                                )
                                            ]
                                        ),
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("Page 1 (/page1/): "),
                                                        "Independent Dash app with its own callbacks",
                                                    ]
                                                )
                                            ]
                                        ),
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("Page 2 (/page2/): "),
                                                        "Independent Dash app with its own callbacks",
                                                    ]
                                                )
                                            ]
                                        ),
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("Isolation: "),
                                                        "Each app has separate callback registry - no conflicts!",
                                                    ]
                                                )
                                            ]
                                        ),
                                    ],
                                    spacing="sm",
                                ),
                            ],
                            title="",
                            color="blue",
                            variant="light",
                            radius="md",
                        ),
                    ],
                    gap="xl",
                )
            ],
            size="md",
            py=50,
        )
    ]
)

# Set layouts for each Dash app
app1.layout = page1.layout
app2.layout = page2.layout

# Register callbacks for each app (ISOLATED!)
page1.register_callbacks(app1)
page2.register_callbacks(app2)

if __name__ == "__main__":
    # Enable Dash dev tools for all apps
    app_home.enable_dev_tools(debug=True, dev_tools_ui=True, dev_tools_props_check=True)
    app1.enable_dev_tools(debug=True, dev_tools_ui=True, dev_tools_props_check=True)
    app2.enable_dev_tools(debug=True, dev_tools_ui=True, dev_tools_props_check=True)

    # Run Flask server with debug mode
    server.run(debug=True, port=8050)
