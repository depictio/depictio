"""Dynamic dashboard module that handles all dashboard UUIDs."""

import uuid

import dash
import dash_mantine_components as dmc
from dash import Input, Output, dcc, html

# Mock dashboard database - in real app, this would be MongoDB
MOCK_DASHBOARDS = {
    "abc-123-dashboard": {
        "id": "abc-123-dashboard",
        "name": "Sales Dashboard",
        "description": "Q4 2024 Sales Analytics",
        "color": "blue",
        "icon": "📊",
        "components": [
            {"type": "metric", "title": "Total Revenue", "value": "$1.2M", "delta": "+12%"},
            {"type": "metric", "title": "New Customers", "value": "342", "delta": "+8%"},
            {"type": "chart", "title": "Revenue Trend", "chart_type": "line"},
        ],
    },
    "def-456-dashboard": {
        "id": "def-456-dashboard",
        "name": "Marketing Dashboard",
        "description": "Campaign Performance Metrics",
        "color": "green",
        "icon": "📈",
        "components": [
            {"type": "metric", "title": "Impressions", "value": "2.5M", "delta": "+23%"},
            {"type": "metric", "title": "Click Rate", "value": "3.2%", "delta": "+0.5%"},
            {"type": "chart", "title": "Campaign Performance", "chart_type": "bar"},
        ],
    },
    "ghi-789-dashboard": {
        "id": "ghi-789-dashboard",
        "name": "Operations Dashboard",
        "description": "Real-time Operations Monitoring",
        "color": "red",
        "icon": "⚙️",
        "components": [
            {"type": "metric", "title": "Active Tasks", "value": "127", "delta": "-5"},
            {"type": "metric", "title": "Completion Rate", "value": "94%", "delta": "+2%"},
            {"type": "chart", "title": "Task Distribution", "chart_type": "pie"},
        ],
    },
}


def get_dashboard_config(dashboard_id):
    """Fetch dashboard config from mock database."""
    return MOCK_DASHBOARDS.get(dashboard_id)


def get_all_dashboards():
    """Get all available dashboards."""
    return list(MOCK_DASHBOARDS.values())


def build_dashboard_content(config):
    """Build dashboard VIEW layout from config."""
    print(f"DEBUG: build_dashboard_content called with config: {config}")

    if not config:
        # Show available dashboard IDs for debugging
        available_ids = list(MOCK_DASHBOARDS.keys())
        return dmc.Stack(
            [
                dmc.Alert(
                    "Dashboard not found",
                    title="404 Error",
                    color="red",
                    variant="filled",
                ),
                dmc.Card(
                    [
                        dmc.Title("Debug Info", order=4, mb="sm"),
                        dmc.Text(f"Available dashboard IDs:", fw=500),
                        dmc.List([dmc.ListItem(id) for id in available_ids]),
                        dmc.Anchor(
                            dmc.Button("← Back to Home", variant="light"),
                            href="/",
                            refresh=True,
                        ),
                    ],
                    shadow="sm",
                    padding="lg",
                    radius="md",
                    withBorder=True,
                ),
            ],
            gap="md",
        )

    components = []

    # Token display (shared across apps via localStorage)
    components.append(html.Div(id="dashboard-token-display", style={"marginBottom": "20px"}))

    # Header with Edit button
    components.append(
        dmc.Group(
            [
                html.A(
                    "← Back to Home",
                    href="/",
                    style={
                        "textDecoration": "none",
                        "color": f"var(--mantine-color-{config['color']}-6)",
                        "fontSize": "14px",
                        "fontWeight": "500",
                    },
                    target="_self",
                ),
                dmc.Anchor(
                    dmc.Button(
                        "Edit Dashboard",
                        variant="light",
                        color=config["color"],
                        leftSection=html.Span("✏️"),
                        size="sm",
                    ),
                    href=f"/dashboard-edit/{config['id']}/",
                    refresh=True,
                    style={"marginLeft": "auto"},
                ),
            ],
            mb="lg",
            style={"display": "flex", "justifyContent": "space-between", "width": "100%"},
        )
    )

    # Dashboard title
    components.append(
        dmc.Group(
            [
                dmc.ThemeIcon(
                    html.Span(config["icon"], style={"fontSize": "32px"}),
                    size=60,
                    radius="md",
                    variant="light",
                    color=config["color"],
                ),
                dmc.Stack(
                    [
                        dmc.Title(config["name"], order=2),
                        dmc.Text(config["description"], c="dimmed", size="sm"),
                    ],
                    gap=5,
                ),
            ],
            mb="xl",
        )
    )

    # Interactive counter (demonstrates isolated callbacks)
    components.append(
        dmc.Card(
            [
                dmc.Title("Isolated Callback Demo", order=4, mb="md"),
                dmc.Text(
                    "This counter is isolated to this dashboard instance. Click to test:",
                    size="sm",
                    c="dimmed",
                    mb="md",
                ),
                dmc.Group(
                    [
                        dmc.Button(
                            "Increment Counter",
                            id={"type": "counter-btn", "dashboard": config["id"]},
                            color=config["color"],
                        ),
                        dmc.Badge(
                            "0",
                            id={"type": "counter-display", "dashboard": config["id"]},
                            size="xl",
                            variant="filled",
                            color=config["color"],
                        ),
                    ],
                    gap="md",
                ),
            ],
            shadow="sm",
            padding="lg",
            radius="md",
            withBorder=True,
            mb="lg",
        )
    )

    # Build components grid
    metrics = []
    charts = []

    for component in config.get("components", []):
        if component["type"] == "metric":
            metrics.append(
                dmc.Card(
                    [
                        dmc.Text(component["title"], size="sm", c="dimmed", mb=5),
                        dmc.Title(component["value"], order=3, mb=5),
                        dmc.Badge(
                            component["delta"],
                            color="green" if "+" in component["delta"] else "red",
                            variant="light",
                        ),
                    ],
                    shadow="sm",
                    padding="lg",
                    radius="md",
                    withBorder=True,
                )
            )
        elif component["type"] == "chart":
            charts.append(
                dmc.Card(
                    [
                        dmc.Title(component["title"], order=4, mb="md"),
                        dmc.Text(
                            f"Chart Type: {component['chart_type']}",
                            size="sm",
                            c="dimmed",
                        ),
                        html.Div(
                            style={
                                "height": "200px",
                                "background": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                                "borderRadius": "8px",
                                "display": "flex",
                                "alignItems": "center",
                                "justifyContent": "center",
                                "marginTop": "10px",
                            },
                            children=[
                                dmc.Text(
                                    f"{component['chart_type'].title()} Chart Placeholder",
                                    c="white",
                                    fw=500,
                                )
                            ],
                        ),
                    ],
                    shadow="sm",
                    padding="lg",
                    radius="md",
                    withBorder=True,
                )
            )

    if metrics:
        components.append(dmc.SimpleGrid(cols=3, spacing="lg", mb="lg", children=metrics))

    if charts:
        components.append(dmc.SimpleGrid(cols=2, spacing="lg", children=charts))

    return dmc.Stack(components, gap="md")


# Layout for the dynamic dashboard app (VIEW mode only)
layout = dmc.MantineProvider(
    [
        dcc.Location(id="dashboard-url", refresh=False),
        dcc.Store(id="dashboard-config-store"),
        dcc.Store(id='shared-token-store', storage_type='local'),  # Shared token storage
        dmc.Container(
            [html.Div(id="dashboard-content-dynamic")],
            size="lg",
            py=30,
        ),
    ]
)


def register_callbacks(app):
    """Register callbacks for dynamic dashboard VIEW app."""

    print("DEBUG: Registering VIEW app callbacks (isolated registry)")

    @app.callback(
        Output("dashboard-config-store", "data"),
        Input("dashboard-url", "pathname"),
    )
    def load_dashboard_config(pathname):
        """Extract dashboard ID from URL and load config."""
        print(f"DEBUG [VIEW APP]: Received pathname: '{pathname}'")
        print(f"DEBUG [VIEW APP]: Available dashboards: {list(MOCK_DASHBOARDS.keys())}")

        if not pathname or pathname == "/":
            print("DEBUG [VIEW APP]: Pathname is empty or root, returning None")
            return None

        # Clean up pathname - remove leading/trailing slashes
        clean_path = pathname.strip("/")
        print(f"DEBUG [VIEW APP]: Cleaned pathname: '{clean_path}'")

        # Extract dashboard_id from pathname
        # pathname comes as '/dashboard/abc-123-dashboard/'
        parts = [p for p in clean_path.split("/") if p]

        print(f"DEBUG [VIEW APP]: Split parts: {parts}")

        # Since url_base_pathname='/dashboard/', the pathname includes 'dashboard' as first part
        # parts[1] is the dashboard ID
        if len(parts) >= 2:
            dashboard_id = parts[1]  # Second part is the dashboard ID

            print(f"DEBUG [VIEW APP]: Extracted dashboard_id: '{dashboard_id}'")
            config = get_dashboard_config(dashboard_id)
            print(f"DEBUG [VIEW APP]: Config lookup result: {config is not None}")
            if config:
                print(f"DEBUG [VIEW APP]: Found dashboard: {config['name']}")
            return config

        print(f"DEBUG [VIEW APP]: Not enough parts (need 2, got {len(parts)}), returning None")
        return None

    @app.callback(
        Output("dashboard-content-dynamic", "children"),
        Input("dashboard-config-store", "data"),
    )
    def render_dashboard(config):
        """Render dashboard VIEW content from config."""
        print(f"DEBUG [VIEW APP]: Rendering view page with config: {config is not None}")
        return build_dashboard_content(config)

    # Token display callback (reads from localStorage)
    @app.callback(
        Output("dashboard-token-display", "children"),
        Input('shared-token-store', 'data'),
    )
    def display_dashboard_token(token):
        """Display shared token in dashboard view."""
        print(f"DEBUG [VIEW APP]: Token from localStorage: {token}")
        if token:
            return dmc.Alert(
                [
                    html.Strong("🔑 Token (from Home): "),
                    html.Code(token[:8] + "..."),
                ],
                color="green",
                variant="light",
            )
        return None

    # View mode counter callback (ISOLATED to VIEW app only!)
    @app.callback(
        Output({"type": "counter-display", "dashboard": dash.dependencies.MATCH}, "children"),
        Input({"type": "counter-btn", "dashboard": dash.dependencies.MATCH}, "n_clicks"),
        prevent_initial_call=True,
    )
    def update_counter(n_clicks):
        """Update isolated counter for this dashboard (VIEW mode only)."""
        print(f"DEBUG [VIEW APP]: Counter clicked {n_clicks} times")
        return str(n_clicks or 0)
