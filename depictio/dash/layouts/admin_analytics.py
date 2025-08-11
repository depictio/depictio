"""
Admin Analytics Dashboard - Monitor users and system activity.
"""

import dash_mantine_components as dmc
from dash_iconify import DashIconify

from dash import dcc, html


def create_metric_card(
    title: str, value: str, metric_id: str, icon: str = "mdi:chart-line", color: str = "blue"
) -> dmc.Card:
    """Create a metric card component."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon=icon, width=24),
                        size="lg",
                        variant="light",
                        color="blue",
                        radius="md",
                    ),
                    dmc.Stack(
                        [
                            dmc.Text(title, size="sm", c="gray", fw="bold"),
                            dmc.Text(id=metric_id, children=value, size="xl", fw="bold", c="blue"),
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


def create_top_users_table() -> dmc.Card:
    """Create top users table component."""
    return dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Title("Top Active Users", order=4, c="dark"),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:refresh", width=16),
                        id="refresh-top-users",
                        variant="subtle",
                        color="gray",
                        size="sm",
                    ),
                ],
                justify="space-between",
            ),
            html.Div(id="top-users-table"),
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
            # Tables row
            dmc.Grid(
                [
                    dmc.GridCol(create_top_users_table(), span=6),
                    dmc.GridCol(create_recent_activity_table(), span=6),
                ]
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
                                DashIconify(icon="mdi:chart-box-off-outline", width=64),
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
                            dmc.Button(
                                "Back to Admin",
                                id="back-to-admin-button",
                                leftSection=DashIconify(icon="mdi:arrow-left", width=16),
                                variant="light",
                            ),
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
