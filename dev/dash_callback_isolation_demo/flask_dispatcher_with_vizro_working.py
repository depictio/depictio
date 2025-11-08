"""
Flask dispatcher with properly working Vizro integration.

Uses Flask multi-app pattern with all apps on the same server.
"""
import dash_mantine_components as dmc
from dash import Dash, Input, Output, dcc, html
from flask import Flask
from pages import dashboard_dynamic, dashboard_edit
import vizro_standalone

# Create main Flask server
server = Flask(__name__)

# Create home page Dash app
app_home = Dash(
    __name__,
    server=server,
    url_base_pathname='/',
    suppress_callback_exceptions=True,
)

# Create dynamic dashboard app
app_dashboards = Dash(
    __name__,
    server=server,
    url_base_pathname='/dashboard/',
    suppress_callback_exceptions=True,
)

# Create edit app
app_edit = Dash(
    __name__,
    server=server,
    url_base_pathname='/dashboard-edit/',
    suppress_callback_exceptions=True,
)

# Create Vizro app on the same Flask server with url_base_pathname='/vizro/'
app_vizro = vizro_standalone.create_standalone_vizro_app(server=server)

# Home page layout (same as before, with Vizro link)
app_home.layout = dmc.MantineProvider(
    [
        dcc.Store(id='shared-token-store', storage_type='local'),
        dmc.Container(
            [
                dmc.Stack(
                    [
                        dmc.Group(
                            [
                                dmc.ThemeIcon(
                                    html.Span("🏠", style={"fontSize": "24px"}),
                                    size="xl",
                                    radius="md",
                                    variant="light",
                                ),
                                dmc.Title("Dash Multi-App Demo with Vizro", order=1, c="blue"),
                            ],
                            gap="md",
                        ),
                        dmc.Text(
                            "Single Flask server with multiple isolated Dash apps including Vizro",
                            size="lg",
                            c="dimmed",
                        ),
                        # Vizro card
                        dmc.Title("Vizro Dashboard", order=3, mt="xl", mb="md"),
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
                                                dmc.Title("Vizro Interactive Dashboard", order=4),
                                                dmc.Text(
                                                    "Full Vizro dashboard with interactive filters and multiple pages",
                                                    size="xs",
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
                                        "Open Vizro Dashboard",
                                        fullWidth=True,
                                        variant="gradient",
                                        gradient={"from": "violet", "to": "grape"},
                                        rightSection=html.Span("→"),
                                    ),
                                    href="/vizro/",
                                ),
                            ],
                            shadow="md",
                            padding="lg",
                            radius="md",
                            withBorder=True,
                        ),
                        # Regular dashboards
                        dmc.Title("Demo Dashboards", order=3, mt="xl", mb="md"),
                        dmc.SimpleGrid(
                            cols=3,
                            spacing="lg",
                            children=[
                                dmc.Card(
                                    [
                                        dmc.Text(dashboard["name"]),
                                        dmc.Anchor(
                                            dmc.Button("Open"),
                                            href=f"/dashboard/{dashboard['id']}/",
                                            refresh=True,
                                        ),
                                    ],
                                    shadow="sm",
                                    padding="lg",
                                )
                                for dashboard in dashboard_dynamic.get_all_dashboards()
                            ],
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

# Set layouts for other apps
app_dashboards.layout = dashboard_dynamic.layout
app_edit.layout = dashboard_edit.layout

# Register callbacks
dashboard_dynamic.register_callbacks(app_dashboards)
dashboard_edit.register_callbacks(app_edit)

# Home page callbacks
@app_home.callback(
    Output('shared-token-store', 'data'),
    Input('generate-token-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def generate_token(n_clicks):
    import uuid
    return str(uuid.uuid4())

if __name__ == "__main__":
    print("=" * 80)
    print("🚀 Flask Multi-App Server with Vizro!")
    print("=" * 80)
    print("📊 Home:           http://localhost:8050/")
    print("📈 Dashboards:     http://localhost:8050/dashboard/<id>/")
    print("✏️  Editor:         http://localhost:8050/dashboard-edit/<id>/")
    print("📊 Vizro:          http://localhost:8050/vizro/")
    print("=" * 80)

    # Use Flask's built-in dev server (all apps on same server)
    server.run(debug=True, port=8050, host='localhost')
