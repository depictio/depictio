"""Separate Dash app for dashboard EDIT mode - completely isolated callbacks."""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, State, dcc, html

# Import the mock database from dashboard_dynamic
from pages.dashboard_dynamic import MOCK_DASHBOARDS, get_dashboard_config


def build_edit_layout(config):
    """Build the edit page layout."""
    if not config:
        return dmc.Alert(
            "Dashboard not found",
            title="404 Error",
            color="red",
            variant="filled",
        )

    return dmc.Stack(
        [
            # Token display (shared across apps via localStorage)
            html.Div(id="edit-token-display", style={"marginBottom": "20px"}),
            # Header with navigation
            dmc.Group(
                [
                    html.A(
                        "← Back to View",
                        href=f"/dashboard/{config['id']}/",
                        style={
                            "textDecoration": "none",
                            "color": f"var(--mantine-color-{config['color']}-6)",
                            "fontSize": "14px",
                            "fontWeight": "500",
                        },
                        target="_self",
                    ),
                    html.Span("|", style={"color": "#ccc"}),
                    html.A(
                        "Home",
                        href="/",
                        style={
                            "textDecoration": "none",
                            "color": f"var(--mantine-color-{config['color']}-6)",
                            "fontSize": "14px",
                            "fontWeight": "500",
                        },
                        target="_self",
                    ),
                ],
                mb="lg",
            ),
            # Edit header
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        html.Span("✏️", style={"fontSize": "32px"}),
                        size=60,
                        radius="md",
                        variant="light",
                        color="orange",
                    ),
                    dmc.Stack(
                        [
                            dmc.Title(f"Edit: {config['name']}", order=2),
                            dmc.Text(
                                "This is a SEPARATE Dash app with isolated callbacks!",
                                c="dimmed",
                                size="sm",
                                fw=700,
                            ),
                        ],
                        gap=5,
                    ),
                ],
                mb="xl",
            ),
            # Edit form
            dmc.Card(
                [
                    dmc.Title("Dashboard Settings", order=4, mb="md"),
                    dmc.Stack(
                        [
                            # Dashboard name input
                            dmc.TextInput(
                                label="Dashboard Name",
                                placeholder="Enter dashboard name",
                                value=config["name"],
                                id="edit-name-input",
                            ),
                            # Description input
                            dmc.Textarea(
                                label="Description",
                                placeholder="Enter dashboard description",
                                value=config["description"],
                                id="edit-description-input",
                                minRows=3,
                            ),
                            # Color selector
                            dmc.Select(
                                label="Color Theme",
                                value=config["color"],
                                data=[
                                    {"label": "Blue", "value": "blue"},
                                    {"label": "Green", "value": "green"},
                                    {"label": "Red", "value": "red"},
                                    {"label": "Orange", "value": "orange"},
                                    {"label": "Purple", "value": "purple"},
                                ],
                                id="edit-color-select",
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
            ),
            # Edit-specific interactive demo (ISOLATED CALLBACKS!)
            dmc.Card(
                [
                    dmc.Title("Edit Mode Counter (Completely Isolated App!)", order=4, mb="md"),
                    dmc.Text(
                        "This counter is in a SEPARATE Dash app with its own callback registry:",
                        size="sm",
                        c="dimmed",
                        mb="md",
                    ),
                    dmc.Group(
                        [
                            dmc.Button(
                                "Increment Edit Counter",
                                id="edit-counter-btn",
                                color="orange",
                                variant="light",
                            ),
                            dmc.Badge(
                                "0",
                                id="edit-counter-display",
                                size="xl",
                                variant="filled",
                                color="orange",
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
            ),
            # Live Preview with real-time updates
            dmc.Card(
                [
                    dmc.Title("Live Preview (Real-time Callback)", order=4, mb="md"),
                    dmc.Text(
                        "This updates in real-time as you type using isolated callbacks:",
                        size="sm",
                        c="dimmed",
                        mb="md",
                    ),
                    html.Div(id="live-preview-output"),
                ],
                shadow="sm",
                padding="lg",
                radius="md",
                withBorder=True,
                mb="lg",
            ),
            # Action buttons
            dmc.Group(
                [
                    dmc.Button(
                        "Save Changes",
                        color="green",
                        leftSection=html.Span("💾"),
                        id="save-btn",
                    ),
                    dmc.Anchor(
                        dmc.Button("Cancel", variant="subtle", color="gray"),
                        href=f"/dashboard/{config['id']}/",
                        refresh=True,
                    ),
                ],
                gap="md",
            ),
            # Save notification
            html.Div(id="save-notification"),
        ],
        gap="md",
    )


# Layout for the edit app
layout = dmc.MantineProvider(
    [
        dcc.Location(id="edit-url", refresh=False),
        dcc.Store(id="edit-config-store"),
        dcc.Store(id='shared-token-store', storage_type='local'),  # Shared token storage
        dmc.Container(
            [html.Div(id="edit-content")],
            size="lg",
            py=30,
        ),
    ]
)


def register_callbacks(app):
    """Register callbacks for the EDIT app - completely isolated from view app!"""

    print("DEBUG: Registering EDIT app callbacks (isolated registry)")

    @app.callback(
        Output("edit-config-store", "data"),
        Input("edit-url", "pathname"),
    )
    def load_edit_config(pathname):
        """Load dashboard config for editing."""
        print(f"DEBUG [EDIT APP]: Received pathname: '{pathname}'")
        print(f"DEBUG [EDIT APP]: Available dashboards: {list(MOCK_DASHBOARDS.keys())}")

        if not pathname or pathname == "/":
            return None

        # Extract dashboard ID from /dashboard-edit/abc-123-dashboard/
        clean_path = pathname.strip("/")
        parts = [p for p in clean_path.split("/") if p]

        print(f"DEBUG [EDIT APP]: Split parts: {parts}")

        # Since url_base_pathname='/dashboard-edit/', pathname includes 'dashboard-edit' as first part
        # parts[1] is the actual dashboard ID
        if len(parts) >= 2:
            dashboard_id = parts[1]  # Second part is the dashboard ID
            print(f"DEBUG [EDIT APP]: Looking for dashboard_id: '{dashboard_id}'")
            config = get_dashboard_config(dashboard_id)
            print(f"DEBUG [EDIT APP]: Config found: {config is not None}")
            if config:
                print(f"DEBUG [EDIT APP]: Found dashboard: {config['name']}")
            return config

        print(f"DEBUG [EDIT APP]: Not enough parts (need 2, got {len(parts)}), returning None")
        return None

    @app.callback(
        Output("edit-content", "children"),
        Input("edit-config-store", "data"),
    )
    def render_edit_page(config):
        """Render the edit page."""
        print(f"DEBUG [EDIT APP]: Rendering edit page with config: {config is not None}")
        return build_edit_layout(config)

    # Token display callback (reads from localStorage)
    @app.callback(
        Output("edit-token-display", "children"),
        Input('shared-token-store', 'data'),
    )
    def display_edit_token(token):
        """Display shared token in edit app."""
        print(f"DEBUG [EDIT APP]: Token from localStorage: {token}")
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

    @app.callback(
        Output("edit-counter-display", "children"),
        Input("edit-counter-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def update_edit_counter(n_clicks):
        """ISOLATED callback in EDIT app - separate from view app counter!"""
        print(f"DEBUG [EDIT APP]: Edit counter clicked {n_clicks} times")
        return str(n_clicks or 0)

    @app.callback(
        Output("live-preview-output", "children"),
        [
            Input("edit-name-input", "value"),
            Input("edit-description-input", "value"),
            Input("edit-color-select", "value"),
        ],
    )
    def update_live_preview(name, description, color):
        """Real-time preview update - ISOLATED callback in EDIT app!"""
        print(f"DEBUG [EDIT APP]: Live preview updated - name={name}, color={color}")
        return dmc.Alert(
            [
                html.Strong(f"Dashboard: {name or 'Untitled'}"),
                html.Br(),
                f"Description: {description or 'No description'}",
                html.Br(),
                f"Color Theme: {color or 'Not selected'}",
            ],
            color=color or "blue",
            variant="light",
        )

    @app.callback(
        Output("save-notification", "children"),
        Input("save-btn", "n_clicks"),
        [
            State("edit-name-input", "value"),
            State("edit-description-input", "value"),
            State("edit-color-select", "value"),
        ],
        prevent_initial_call=True,
    )
    def save_changes(n_clicks, name, description, color):
        """Handle save button - ISOLATED callback in EDIT app!"""
        print(f"DEBUG [EDIT APP]: Save clicked - name={name}, color={color}")
        # In real app, save to database here
        return dmc.Alert(
            f"Saved: {name} with {color} theme! (Demo - not persisted to DB)",
            color="green",
            title="Success",
            withCloseButton=True,
            style={"marginTop": "20px"},
        )
