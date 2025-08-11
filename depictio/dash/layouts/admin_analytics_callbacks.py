"""
Callbacks for Admin Analytics Dashboard.
"""

import dash_mantine_components as dmc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go  # type: ignore
import requests

from dash import Input, Output, State, dash_table, html
from dash.exceptions import PreventUpdate
from depictio.api.v1.configs.config import settings
from depictio.dash.api_calls import api_call_fetch_user_from_token
from depictio.dash.layouts.admin_analytics import (
    create_analytics_dashboard_404,
    create_analytics_dashboard_layout,
)


def register_admin_analytics_callbacks(app):
    """Register all analytics dashboard callbacks."""

    @app.callback(
        Output("analytics-dashboard-content", "children"),
        Input("analytics-dashboard-trigger", "id"),
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def render_analytics_dashboard(trigger, local_data):
        """Render analytics dashboard if user has admin privileges."""
        if not local_data or not local_data.get("access_token"):
            return create_analytics_dashboard_404()

        # Check if user is admin
        try:
            user = api_call_fetch_user_from_token(local_data["access_token"])
            if not user or not user.is_admin:
                return create_analytics_dashboard_404()
        except Exception:
            return create_analytics_dashboard_404()

        # Check if analytics is enabled
        if not settings.analytics.enabled:
            return create_analytics_dashboard_404()

        return create_analytics_dashboard_layout()

    @app.callback(
        [
            Output("metric-active-users", "children"),
            Output("metric-sessions-today", "children"),
            Output("metric-pageviews-hour", "children"),
            Output("metric-avg-response", "children"),
            Output("realtime-metrics-store", "data"),
        ],
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-all-analytics", "n_clicks"),
        ],
        [State("auto-refresh-toggle", "checked"), State("local-store", "data")],
        prevent_initial_call=False,
    )
    def update_realtime_metrics(n_intervals, refresh_clicks, auto_refresh, local_data):
        """Update real-time metrics display."""
        if not local_data or not local_data.get("access_token"):
            raise PreventUpdate

        # Skip auto-refresh if disabled (but allow manual refresh)
        if n_intervals > 0 and not auto_refresh:
            raise PreventUpdate

        try:
            # Call analytics API
            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/realtime-metrics",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]
                return (
                    str(data.get("active_sessions", 0)),
                    str(data.get("sessions_today", 0)),
                    str(data.get("page_views_today", 0)),
                    f"{data.get('avg_response_time_ms', 0):.0f}ms",
                    data,
                )
            else:
                return "Error", "Error", "Error", "Error", {}

        except Exception as e:
            print(f"Failed to fetch realtime metrics: {e}")
            return "N/A", "N/A", "N/A", "N/A", {}

    @app.callback(
        Output("daily-activity-chart", "figure"),
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-activity-chart", "n_clicks"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_daily_activity_chart(n_intervals, refresh_clicks, local_data):
        """Update daily activity trends chart."""
        if not local_data or not local_data.get("access_token"):
            return go.Figure()  # type: ignore

        try:
            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/daily-activity-chart",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]

                if not data:
                    # Return empty chart with message
                    fig = go.Figure()  # type: ignore
                    fig.add_annotation(
                        text="No activity data available yet",
                        xref="paper",
                        yref="paper",
                        x=0.5,
                        y=0.5,
                        xanchor="center",
                        yanchor="middle",
                        showarrow=False,
                        font_size=16,
                        font_color="gray",
                    )
                    fig.update_layout(
                        title="Daily Activity Trends",
                        xaxis_title="Date",
                        yaxis_title="Total Activities",
                        height=350,
                        showlegend=False,
                    )
                    return fig

                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["date"])

                fig = px.line(
                    df, x="date", y="total_activities", title="Daily Activity Trends", markers=True
                )

                fig.update_layout(
                    height=350,
                    xaxis_title="Date",
                    yaxis_title="Total Activities",
                    showlegend=False,
                    margin=dict(l=0, r=0, t=40, b=0),
                )

                return fig
            else:
                return go.Figure()  # type: ignore

        except Exception as e:
            print(f"Failed to fetch daily activity data: {e}")
            return go.Figure()  # type: ignore

    @app.callback(
        Output("user-types-chart", "figure"),
        [Input("analytics-auto-refresh", "n_intervals"), Input("refresh-user-types", "n_clicks")],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_user_types_chart(n_intervals, refresh_clicks, local_data):
        """Update user types distribution pie chart."""
        if not local_data or not local_data.get("access_token"):
            return go.Figure()  # type: ignore

        try:
            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/user-types-distribution",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]

                if not data:
                    fig = go.Figure()  # type: ignore
                    fig.add_annotation(
                        text="No user data available yet",
                        xref="paper",
                        yref="paper",
                        x=0.5,
                        y=0.5,
                        xanchor="center",
                        yanchor="middle",
                        showarrow=False,
                        font_size=14,
                        font_color="gray",
                    )
                    fig.update_layout(height=300, showlegend=False)
                    return fig

                df = pd.DataFrame(data)

                fig = px.pie(
                    df,
                    values="count",
                    names="user_type",
                    title="User Type Distribution",
                    color_discrete_map={"Anonymous": "#ff7f0e", "Authenticated": "#1f77b4"},
                )

                fig.update_layout(
                    height=300,
                    margin=dict(l=0, r=0, t=40, b=0),
                    showlegend=True,
                    legend=dict(orientation="v", yanchor="middle", y=0.5),
                )

                return fig
            else:
                return go.Figure()  # type: ignore

        except Exception as e:
            print(f"Failed to fetch user types data: {e}")
            return go.Figure()  # type: ignore

    @app.callback(
        Output("top-users-table", "children"),
        [Input("analytics-auto-refresh", "n_intervals"), Input("refresh-top-users", "n_clicks")],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_top_users_table(n_intervals, refresh_clicks, local_data):
        """Update top users table."""
        if not local_data or not local_data.get("access_token"):
            return html.Div("No data available")

        try:
            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/top-users?limit=10",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]

                if not data:
                    return dmc.Text("No user data available yet", c="gray", ta="center", mt="xl")

                # Format the data for display
                formatted_data = []
                for user in data:
                    formatted_data.append(
                        {
                            "User": user.get("user_email", "Unknown"),
                            "Sessions": user.get("total_sessions", 0),
                            "Page Views": user.get("total_page_views", 0),
                            "Time (min)": f"{user.get('total_time_minutes', 0):.0f}",
                            "Admin": "✓" if user.get("user_is_admin") else "",
                        }
                    )

                return dash_table.DataTable(
                    data=formatted_data,
                    columns=[{"name": col, "id": col} for col in formatted_data[0].keys()],
                    style_cell={
                        "textAlign": "left",
                        "fontSize": "14px",
                        "fontFamily": "Arial",
                        "backgroundColor": "var(--app-surface-color, #ffffff)",
                        "color": "var(--app-text-color, #000000)",
                    },
                    style_header={
                        "backgroundColor": "var(--app-border-color, #e0e0e0)",
                        "fontWeight": "bold",
                    },
                    style_data_conditional=[
                        {
                            "if": {"column_id": "Admin", "filter_query": "{Admin} = ✓"},
                            "color": "green",
                            "fontWeight": "bold",
                        }
                    ],
                    page_size=10,
                    sort_action="native",
                )
            else:
                return dmc.Text("Error loading user data", c="red")

        except Exception as e:
            print(f"Failed to fetch top users data: {e}")
            return dmc.Text("Failed to load data", c="red")

    @app.callback(
        Output("activity-overview-content", "children"),
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-activity-overview", "n_clicks"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_activity_overview(n_intervals, refresh_clicks, local_data):
        """Update activity overview content."""
        if not local_data or not local_data.get("access_token"):
            return html.Div("No data available")

        try:
            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/activity-trends",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]

                if not data:
                    return dmc.Text(
                        "No activity data available yet", c="gray", ta="center", mt="xl"
                    )

                df = pd.DataFrame(data)

                # Calculate summary statistics
                total_activities = df["activity_count"].sum()
                avg_response_time = df["avg_response_time_ms"].mean()

                # Activity type breakdown
                activity_breakdown = (
                    df.groupby("activity_type")["activity_count"].sum().reset_index()
                )

                return dmc.Stack(
                    [
                        dmc.Group(
                            [
                                dmc.Stack(
                                    [
                                        dmc.Text("Total Activities", size="sm", c="gray"),
                                        dmc.Text(
                                            f"{total_activities:,}", size="xl", fw="bold", c="blue"
                                        ),
                                    ],
                                    gap="xs",
                                    align="center",
                                ),
                                dmc.Stack(
                                    [
                                        dmc.Text("Avg Response Time", size="sm", c="gray"),
                                        dmc.Text(
                                            f"{avg_response_time:.0f}ms",
                                            size="xl",
                                            fw="bold",
                                            c="orange",
                                        ),
                                    ],
                                    gap="xs",
                                    align="center",
                                ),
                            ],
                            justify="space-around",
                        ),
                        dmc.Divider(),
                        dmc.Title("Activity Breakdown", order=6, c="dark"),
                        dmc.Stack(
                            [
                                dmc.Group(
                                    [
                                        dmc.Text(
                                            row.activity_type.replace("_", " ").title(), fw="bold"
                                        ),
                                        dmc.Badge(
                                            f"{row.activity_count:,}", color="blue", variant="light"
                                        ),
                                    ],
                                    justify="space-between",
                                )
                                for _, row in activity_breakdown.iterrows()
                            ],
                            gap="xs",
                        ),
                    ],
                    gap="md",
                )
            else:
                return dmc.Text("Error loading activity data", c="red")

        except Exception as e:
            print(f"Failed to fetch activity overview data: {e}")
            return dmc.Text("Failed to load data", c="red")

    @app.callback(
        Output("analytics-loading-output", "children"),
        Input("refresh-all-analytics", "n_clicks"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def refresh_all_analytics_data(n_clicks, local_data):
        """Trigger ETL refresh for all analytics data."""
        if not n_clicks or not local_data or not local_data.get("access_token"):
            raise PreventUpdate

        try:
            response = requests.post(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/etl/refresh",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                timeout=30,
            )

            if response.status_code == 200:
                return "Data refreshed successfully"
            else:
                return "Refresh failed"

        except Exception as e:
            print(f"Failed to refresh analytics data: {e}")
            return "Refresh failed"
