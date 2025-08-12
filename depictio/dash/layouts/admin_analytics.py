"""
Admin Analytics Dashboard - Monitor users and system activity.
"""

from datetime import datetime, timedelta
from typing import Literal

import dash_mantine_components as dmc
from dash_iconify import DashIconify

from dash import dcc, html


def get_valid_dmc_color(
    color: str,
) -> Literal[
    "blue",
    "cyan",
    "gray",
    "green",
    "indigo",
    "lime",
    "orange",
    "pink",
    "red",
    "teal",
    "violet",
    "yellow",
    "dark",
    "grape",
]:
    """Map color strings to valid DMC colors."""
    color_mapping = {
        "blue": "blue",
        "green": "green",
        "orange": "orange",
        "red": "red",
        "purple": "violet",
        "violet": "violet",
        "cyan": "cyan",
        "teal": "teal",
        "yellow": "yellow",
        "gray": "gray",
        "grey": "gray",
        "pink": "pink",
        "lime": "lime",
        "indigo": "indigo",
        "dark": "dark",
        "grape": "grape",
    }
    return color_mapping.get(color.lower(), "blue")


def create_analytics_filters() -> dmc.Card:
    """Create filters section for analytics dashboard."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Title("Filters", order=5, c="dark"),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:filter-off", width=16),
                        id="clear-filters",
                        variant="subtle",
                        color="gray",
                        size="sm",
                    ),
                ],
                justify="space-between",
                mb="md",
            ),
            dmc.Grid(
                [
                    dmc.GridCol(
                        dmc.Stack(
                            [
                                dmc.Text("Date Range", size="sm", fw="bold", c="gray"),
                                dmc.DatePickerInput(
                                    id="date-range-picker",
                                    label="Select Date Range",
                                    placeholder="Pick dates range",
                                    type="range",
                                    value=[
                                        datetime.now().date() - timedelta(days=7),
                                        datetime.now().date(),
                                    ],
                                    maxDate=datetime.now().date(),
                                    minDate=datetime.now().date() - timedelta(days=365),
                                    clearable=True,
                                    size="sm",
                                ),
                            ],
                            gap="xs",
                        ),
                        span=4,
                    ),
                    dmc.GridCol(
                        dmc.Stack(
                            [
                                dmc.Text("User Type", size="sm", fw="bold", c="gray"),
                                dmc.Select(
                                    id="user-type-filter",
                                    label="Filter by User Type",
                                    placeholder="All Users",
                                    data=[
                                        {"value": "all", "label": "All Users"},
                                        {"value": "authenticated", "label": "Authenticated Only"},
                                        {"value": "anonymous", "label": "Anonymous Only"},
                                        {"value": "admin", "label": "Admin Users Only"},
                                    ],
                                    value="all",
                                    clearable=True,
                                    size="sm",
                                ),
                            ],
                            gap="xs",
                        ),
                        span=4,
                    ),
                    dmc.GridCol(
                        dmc.Stack(
                            [
                                dmc.Text("Specific User", size="sm", fw="bold", c="gray"),
                                dmc.Select(
                                    id="specific-user-filter",
                                    label="Select Specific User",
                                    placeholder="All Users",
                                    data=[],  # Will be populated by callback
                                    value=None,
                                    searchable=True,
                                    clearable=True,
                                    size="sm",
                                ),
                            ],
                            gap="xs",
                        ),
                        span=4,
                    ),
                ],
            ),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
        mb="lg",
    )


def create_top_pages_card() -> dmc.Card:
    """Create top pages card showing most consulted pages."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Title("Most Consulted Pages", order=4, c="dark"),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:refresh", width=16),
                        id="refresh-top-pages",
                        variant="subtle",
                        color="gray",
                        size="sm",
                    ),
                ],
                justify="space-between",
            ),
            html.Div(id="top-pages-content"),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
    )


def create_metric_card(
    title: str, value: str, metric_id: str, icon: str = "mdi:chart-line", color: str = "blue"
) -> dmc.Card:
    """Create a metric card component."""
    dmc_color = get_valid_dmc_color(color)
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon=icon, width=24),
                        size="lg",
                        variant="light",
                        color=dmc_color,
                        radius="md",
                    ),
                    dmc.Stack(
                        [
                            dmc.Text(title, size="sm", c="gray", fw="bold"),
                            dmc.Text(
                                id=metric_id, children=value, size="xl", fw="bold", c=dmc_color
                            ),
                        ],
                        gap="xs",
                    ),
                ],
                justify="flex-start",
            ),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
    )


def create_user_growth_chart() -> dmc.Card:
    """Create user growth chart component."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Title("Daily Activity Trends", order=4, c="dark"),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:refresh", width=16),
                        id="refresh-activity-chart",
                        variant="subtle",
                        color="gray",
                        size="sm",
                    ),
                ],
                justify="space-between",
            ),
            dcc.Graph(
                id="daily-activity-chart",
                config={"displayModeBar": False},
                style={"height": "350px"},
            ),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
    )


def create_user_type_distribution() -> dmc.Card:
    """Create user type distribution pie chart."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Title("User Types", order=4, c="dark"),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:refresh", width=16),
                        id="refresh-user-types",
                        variant="subtle",
                        color="gray",
                        size="sm",
                    ),
                ],
                justify="space-between",
            ),
            dcc.Graph(
                id="user-types-chart", config={"displayModeBar": False}, style={"height": "300px"}
            ),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
    )


def create_unique_connections_card() -> dmc.Card:
    """Create IP analytics card showing unique connections and IP addresses."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Group(
                        [
                            dmc.ThemeIcon(
                                DashIconify(icon="mdi:ip-network-outline", width=20),
                                size="md",
                                variant="light",
                                color="indigo",
                            ),
                            dmc.Text("Unique Connections", fw="bold", size="lg"),
                        ]
                    ),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:refresh", width=16),
                        id="refresh-unique-connections",
                        variant="subtle",
                        color="gray",
                    ),
                ],
                justify="space-between",
                mb="md",
            ),
            dcc.Loading(
                id="loading-unique-connections",
                children=[
                    html.Div(id="unique-connections-content", children="Loading IP analytics..."),
                ],
                type="dot",
                color="var(--mantine-color-indigo-6)",
            ),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
        id="unique-connections-card",
        style={"height": "350px", "overflow": "auto"},
    )


def create_users_active_today_card() -> dmc.Card:
    """Create users active today metrics card."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Title("Users Active Today", order=4, c="dark"),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:refresh", width=16),
                        id="refresh-users-active-today",
                        variant="subtle",
                        color="gray",
                        size="sm",
                    ),
                ],
                justify="space-between",
            ),
            html.Div(
                id="users-active-today-content",
                children="Loading...",
                style={
                    "minHeight": "120px",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                },
            ),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
    )


def create_recent_activity_table() -> dmc.Card:
    """Create recent activity overview."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Title("Activity Overview", order=4, c="dark"),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:refresh", width=16),
                        id="refresh-activity-overview",
                        variant="subtle",
                        color="gray",
                        size="sm",
                    ),
                ],
                justify="space-between",
            ),
            html.Div(id="activity-overview-content"),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
    )


def create_analytics_dashboard_layout() -> html.Div:
    """Create the main analytics dashboard layout."""
    return html.Div(
        [
            # Page header
            dmc.Group(
                [
                    dmc.Group(
                        [
                            dmc.ThemeIcon(
                                DashIconify(icon="mdi:chart-box-outline", width=32),
                                size="xl",
                                variant="light",
                                color="blue",
                            ),
                            dmc.Stack(
                                [
                                    dmc.Title("Analytics Dashboard", order=2, c="dark"),
                                    dmc.Text("Monitor user activity and system metrics", c="gray"),
                                ],
                                gap="xs",
                            ),
                        ]
                    ),
                    dmc.Group(
                        [
                            dmc.Button(
                                "Refresh All Data",
                                id="refresh-all-analytics",
                                leftSection=DashIconify(icon="mdi:refresh", width=16),
                                color="blue",
                                variant="light",
                            ),
                            dmc.Switch(
                                id="auto-refresh-toggle",
                                label="Auto-refresh",
                                checked=True,
                                color="green",
                            ),
                        ]
                    ),
                ],
                justify="space-between",
                mb="lg",
            ),
            # Filters section
            create_analytics_filters(),
            # Real-time metrics row
            dmc.Grid(
                [
                    dmc.GridCol(
                        create_metric_card(
                            "Active Users",
                            "0",
                            "metric-active-users",
                            "mdi:account-multiple",
                            "green",
                        ),
                        span=3,
                    ),
                    dmc.GridCol(
                        create_metric_card(
                            "Sessions Today",
                            "0",
                            "metric-sessions-today",
                            "mdi:clock-outline",
                            "blue",
                        ),
                        span=3,
                    ),
                    dmc.GridCol(
                        create_metric_card(
                            "Page Views/Hour",
                            "0",
                            "metric-pageviews-hour",
                            "mdi:eye-outline",
                            "orange",
                        ),
                        span=3,
                    ),
                    dmc.GridCol(
                        create_metric_card(
                            "Avg Response", "0ms", "metric-avg-response", "mdi:speedometer", "red"
                        ),
                        span=3,
                    ),
                ],
                mb="lg",
            ),
            # Charts row
            dmc.Grid(
                [
                    dmc.GridCol(create_user_growth_chart(), span=8),
                    dmc.GridCol(create_user_type_distribution(), span=4),
                ],
                mb="lg",
            ),
            # Cards row 1 - Analytics cards
            dmc.Grid(
                [
                    dmc.GridCol(create_users_active_today_card(), span=4),
                    dmc.GridCol(create_recent_activity_table(), span=4),
                    dmc.GridCol(create_unique_connections_card(), span=4),
                ],
                mb="md",
            ),
            # Cards row 2 - Most Consulted Pages (full width for better visibility)
            dmc.Grid(
                [
                    dmc.GridCol(create_top_pages_card(), span=12),
                ],
                mb="lg",
            ),
            # Comprehensive Analytics Summary Section
            dmc.Card(
                [
                    dmc.Group(
                        [
                            dmc.Title("Period Summary", order=4, c="dark"),
                            dmc.ActionIcon(
                                DashIconify(icon="mdi:refresh", width=16),
                                id="refresh-comprehensive-summary",
                                variant="subtle",
                                size="sm",
                                color="gray",
                            ),
                        ],
                        justify="space-between",
                    ),
                    dmc.Divider(),
                    html.Div(
                        id="comprehensive-summary-content",
                        children="Loading comprehensive summary...",
                        style={"minHeight": "200px"},
                    ),
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
                mt="xl",
            ),
            # Hidden components for data management
            dcc.Store(id="analytics-dashboard-store", storage_type="memory"),
            dcc.Store(id="realtime-metrics-store", storage_type="memory"),
            # Auto-refresh interval
            dcc.Interval(
                id="analytics-auto-refresh",
                interval=30 * 1000,  # 30 seconds
                n_intervals=0,
            ),
            # Loading overlay
            dcc.Loading(
                id="analytics-loading",
                type="cube",
                children=html.Div(id="analytics-loading-output", style={"display": "none"}),
            ),
        ],
        style={"padding": "20px"},
    )


def create_analytics_dashboard_404() -> dmc.Container:
    """Create analytics dashboard not available page."""
    return dmc.Container(
        [
            dmc.Center(
                [
                    dmc.Stack(
                        [
                            dmc.ThemeIcon(
                                DashIconify(icon="mdi:checkbox-blank-off-outline", width=64),
                                size=120,
                                variant="light",
                                color="gray",
                                radius="xl",
                            ),
                            dmc.Title("Analytics Dashboard Not Available", order=2, ta="center"),
                            dmc.Text(
                                "Analytics is not enabled or you don't have permission to view this dashboard.",
                                ta="center",
                                c="gray",
                                size="lg",
                            ),
                            # dmc.Button(
                            #     "Back to Admin",
                            #     id="back-to-admin-button",
                            #     leftSection=DashIconify(icon="mdi:arrow-left", width=16),
                            #     variant="light",
                            # ),
                        ],
                        align="center",
                        gap="lg",
                    )
                ],
                style={"height": "60vh"},
            )
        ],
        size="md",
    )


# Layout for the admin analytics page
layout = html.Div(
    [
        html.Div(id="analytics-dashboard-content"),
        html.Div(id="analytics-dashboard-trigger", style={"display": "none"}),
    ]
)
