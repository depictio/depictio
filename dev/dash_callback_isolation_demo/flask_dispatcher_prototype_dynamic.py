import dash_mantine_components as dmc
from dash import Dash, Input, Output, dcc, html
from flask import Flask, redirect
from pages import dashboard_dynamic, dashboard_edit, vizro_flask

server = Flask(__name__)

# Create home page Dash app
app_home = Dash(
    __name__,
    server=server,
    url_base_pathname='/',
    suppress_callback_exceptions=True,
)

# Create dynamic dashboard app (handles all /dashboard/<id>/ routes)
app_dashboards = Dash(
    __name__,
    server=server,
    url_base_pathname='/dashboard/',
    suppress_callback_exceptions=True,
)

# Create SEPARATE edit app (handles all /dashboard-edit/<id>/ routes internally) - ISOLATED CALLBACKS!
app_edit = Dash(
    __name__,
    server=server,
    url_base_pathname='/dashboard-edit/',
    suppress_callback_exceptions=True,
)

# Create Vizro app (handles /vizro/ routes) - ISOLATED CALLBACKS!
# Use Flask-managed pattern like other apps
app_vizro = Dash(
    __name__,
    server=server,
    url_base_pathname='/vizro/',
    suppress_callback_exceptions=True,
)

# Home page layout with Mantine UI
app_home.layout = dmc.MantineProvider(
    [
        dcc.Store(id='shared-token-store', storage_type='local'),
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
                        # Token sharing demo
                        dmc.Alert(
                            [
                                dmc.Title("Token Sharing Test", order=4, mb="sm"),
                                dmc.Text(
                                    "Test localStorage sharing across isolated Dash apps:",
                                    size="sm",
                                    mb="md",
                                ),
                                dmc.Button(
                                    "Generate Random Token",
                                    id="generate-token-btn",
                                    color="green",
                                    leftSection=html.Span("🔑"),
                                ),
                                html.Div(id="home-token-display", style={"marginTop": "15px"}),
                            ],
                            title="",
                            color="green",
                            variant="light",
                            radius="md",
                            mb="xl",
                        ),
                        # Description
                        dmc.Text(
                            "This demonstrates dynamic dashboard routing with callback isolation. Each dashboard has a unique UUID and loads content dynamically.",
                            size="lg",
                            c="dimmed",
                        ),
                        # Available Dashboards heading
                        dmc.Title("Available Dashboards", order=3, mt="xl", mb="md"),
                        # Dashboard cards (dynamically generated)
                        dmc.SimpleGrid(
                            cols=3,
                            spacing="lg",
                            children=[
                                dmc.Card(
                                    [
                                        dmc.Group(
                                            [
                                                dmc.ThemeIcon(
                                                    html.Span(dashboard["icon"], style={"fontSize": "32px"}),
                                                    size=60,
                                                    radius="md",
                                                    variant="light",
                                                    color=dashboard["color"],
                                                ),
                                                dmc.Stack(
                                                    [
                                                        dmc.Title(dashboard["name"], order=4),
                                                        dmc.Text(
                                                            dashboard["description"],
                                                            size="xs",
                                                            c="dimmed",
                                                        ),
                                                    ],
                                                    gap=5,
                                                ),
                                            ],
                                            mb="md",
                                        ),
                                        dmc.Group(
                                            [
                                                dmc.Badge(
                                                    f"ID: {dashboard['id'][:10]}...",
                                                    size="sm",
                                                    variant="light",
                                                    color=dashboard["color"],
                                                ),
                                            ],
                                            mb="md",
                                        ),
                                        dmc.Anchor(
                                            dmc.Button(
                                                "Open Dashboard",
                                                fullWidth=True,
                                                variant="light",
                                                color=dashboard["color"],
                                                rightSection=html.Span("→"),
                                            ),
                                            href=f"/dashboard/{dashboard['id']}/",
                                            refresh=True,
                                        ),
                                    ],
                                    shadow="sm",
                                    padding="lg",
                                    radius="md",
                                    withBorder=True,
                                )
                                for dashboard in dashboard_dynamic.get_all_dashboards()
                            ],
                        ),
                        # Vizro Integration Demo
                        dmc.Title("Vizro Integration Demo", order=3, mt="xl", mb="md"),
                        dmc.Card(
                            [
                                dmc.Group(
                                    [
                                        dmc.ThemeIcon(
                                            html.Span("📊", style={"fontSize": "32px"}),
                                            size=60,
                                            radius="md",
                                            variant="light",
                                            color="violet",
                                        ),
                                        dmc.Stack(
                                            [
                                                dmc.Title("Vizro Dashboard", order=4),
                                                dmc.Text(
                                                    "Interactive Vizro-powered dashboard with filters and multiple pages",
                                                    size="xs",
                                                    c="dimmed",
                                                ),
                                            ],
                                            gap=5,
                                        ),
                                    ],
                                    mb="md",
                                ),
                                dmc.Group(
                                    [
                                        dmc.Badge(
                                            "Vizro Framework",
                                            size="sm",
                                            variant="light",
                                            color="violet",
                                        ),
                                        dmc.Badge(
                                            "Isolated Callbacks",
                                            size="sm",
                                            variant="light",
                                            color="green",
                                        ),
                                    ],
                                    mb="md",
                                ),
                                dmc.Text(
                                    [
                                        "This demonstrates Vizro running as a completely isolated Dash app. ",
                                        "Vizro has its own routing system (dcc.Location) and callback registry, ",
                                        "separate from the other apps in this demo.",
                                    ],
                                    size="sm",
                                    c="dimmed",
                                    mb="md",
                                ),
                                dmc.Group(
                                    [
                                        dmc.Anchor(
                                            dmc.Button(
                                                "Open Vizro Dashboard",
                                                variant="gradient",
                                                gradient={"from": "violet", "to": "grape"},
                                                leftSection=html.Span("📊"),
                                                rightSection=html.Span("→"),
                                            ),
                                            href="/vizro/",
                                            refresh=False,  # Use client-side navigation
                                        ),
                                    ],
                                    grow=True,
                                ),
                            ],
                            shadow="md",
                            padding="lg",
                            radius="md",
                            withBorder=True,
                            style={"maxWidth": "600px"},
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
                                                        html.Strong("Home Page (/): "),
                                                        "Static Dash app for dashboard listing",
                                                    ]
                                                )
                                            ]
                                        ),
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("Dashboard App (/dashboard/): "),
                                                        "Dash app for viewing dashboards (read-only)",
                                                    ]
                                                )
                                            ]
                                        ),
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("Edit App (/dashboard-edit/<id>/): "),
                                                        "SEPARATE Dash app for editing (isolated callbacks!)",
                                                    ]
                                                )
                                            ]
                                        ),
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("Vizro App (/vizro/): "),
                                                        "SEPARATE Vizro dashboard app (isolated callbacks!)",
                                                    ]
                                                )
                                            ]
                                        ),
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("Dynamic Routing: "),
                                                        "Uses dcc.Location to detect UUID and load content from 'database'",
                                                    ]
                                                )
                                            ]
                                        ),
                                        dmc.ListItem(
                                            [
                                                dmc.Text(
                                                    [
                                                        html.Strong("True Isolation: "),
                                                        "View and Edit are separate apps with independent callback registries!",
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

# Set layout for dynamic dashboard app (VIEW mode)
app_dashboards.layout = dashboard_dynamic.layout

# Set layout for edit app (EDIT mode - SEPARATE APP!)
app_edit.layout = dashboard_edit.layout

# Register callbacks for dynamic dashboard app (ISOLATED!)
dashboard_dynamic.register_callbacks(app_dashboards)

# Register callbacks for edit app (ISOLATED from dashboard app!)
dashboard_edit.register_callbacks(app_edit)

# Register callbacks for Vizro app (ISOLATED!)
# NOTE: vizro_flask.register_callbacks() will set the layout during registration
vizro_flask.register_callbacks(app_vizro)

# Set layout for Vizro app (after callbacks registered)
app_vizro.layout = vizro_flask.layout


# Home page callbacks for token sharing demo
@app_home.callback(
    Output('shared-token-store', 'data'),
    Input('generate-token-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def generate_token(n_clicks):
    """Generate a random token and save to localStorage."""
    import uuid

    token = str(uuid.uuid4())
    print(f"DEBUG [HOME APP]: Generated token: {token}")
    return token


@app_home.callback(
    Output('home-token-display', 'children'),
    Input('shared-token-store', 'data'),
)
def display_home_token(token):
    """Display the current token on home page."""
    print(f"DEBUG [HOME APP]: Displaying token: {token}")
    if token:
        return dmc.Alert(
            [
                html.Strong("Token: "),
                html.Code(token[:8] + "..."),
                html.Br(),
                dmc.Text("Navigate to a dashboard to verify sharing!", size="sm", c="dimmed"),
            ],
            color="green",
            variant="filled",
        )
    return dmc.Text("No token generated yet. Click the button above!", size="sm", c="dimmed")


if __name__ == "__main__":
    # Enable Dash dev tools for all apps
    app_home.enable_dev_tools(debug=True, dev_tools_ui=True, dev_tools_props_check=True)
    app_dashboards.enable_dev_tools(debug=True, dev_tools_ui=True, dev_tools_props_check=True)
    app_edit.enable_dev_tools(debug=True, dev_tools_ui=True, dev_tools_props_check=True)
    app_vizro.enable_dev_tools(debug=True, dev_tools_ui=True, dev_tools_props_check=True)

    print("=" * 80)
    print("🚀 Flask Multi-App Server Started!")
    print("=" * 80)
    print("📊 Home:           http://localhost:8050/")
    print("📈 View Dashboard: http://localhost:8050/dashboard/<id>/")
    print("✏️  Edit Dashboard: http://localhost:8050/dashboard-edit/<id>/")
    print("📊 Vizro Dashboard: http://localhost:8050/vizro/")
    print("=" * 80)
    print("🔐 Callback Isolation:")
    print("   - app_home: Home page callbacks")
    print("   - app_dashboards: View mode callbacks (separate registry)")
    print("   - app_edit: Edit mode callbacks (separate registry)")
    print("   - app_vizro: Vizro dashboard callbacks (separate registry)")
    print("=" * 80)
    print("⚠️  Note: Due to Dash architecture, separate apps require unique base paths.")
    print("   Edit URLs use /dashboard-edit/ instead of /dashboard/<id>/edit/")
    print("   This ensures true callback isolation between view and edit modes.")
    print("=" * 80)

    # Run Flask server with debug mode
    server.run(debug=True, port=8050)
