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
            Input("date-range-picker", "value"),
            Input("user-type-filter", "value"),
            Input("specific-user-filter", "value"),
        ],
        [State("auto-refresh-toggle", "checked"), State("local-store", "data")],
        prevent_initial_call=False,
    )
    def update_realtime_metrics(
        n_intervals, refresh_clicks, date_range, user_type, user_id, auto_refresh, local_data
    ):
        """Update real-time metrics display."""
        if not local_data or not local_data.get("access_token"):
            raise PreventUpdate

        # Skip auto-refresh if disabled (but allow manual refresh)
        if n_intervals > 0 and not auto_refresh:
            raise PreventUpdate

        try:
            # Build query parameters for filters
            params = {}
            if date_range and len(date_range) == 2:
                if date_range[0]:
                    params["start_date"] = date_range[0]
                if date_range[1]:
                    params["end_date"] = date_range[1]
            if user_type and user_type != "all":
                params["user_type"] = user_type
            if user_id:
                params["user_id"] = user_id

            # Call analytics API
            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/realtime-metrics",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                params=params,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]
                return (
                    str(data.get("active_sessions", 0)),
                    str(data.get("sessions_today", 0)),
                    str(data.get("page_views_per_hour", 0)),
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
            Input("date-range-picker", "value"),
            Input("user-type-filter", "value"),
            Input("specific-user-filter", "value"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_daily_activity_chart(
        n_intervals, refresh_clicks, date_range, user_type, user_id, local_data
    ):
        """Update daily activity trends chart."""
        if not local_data or not local_data.get("access_token"):
            return go.Figure()  # type: ignore

        try:
            # Build query parameters for filters
            params = {}
            if date_range and len(date_range) == 2:
                if date_range[0]:
                    params["start_date"] = date_range[0]
                if date_range[1]:
                    params["end_date"] = date_range[1]
            if user_type and user_type != "all":
                params["user_type"] = user_type
            if user_id:
                params["user_id"] = user_id

            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/daily-activity-chart",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                params=params,
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
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-user-types", "n_clicks"),
            Input("date-range-picker", "value"),
            Input("user-type-filter", "value"),
            Input("specific-user-filter", "value"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_user_types_chart(
        n_intervals, refresh_clicks, date_range, user_type, user_id, local_data
    ):
        """Update user types distribution pie chart."""
        if not local_data or not local_data.get("access_token"):
            return go.Figure()  # type: ignore

        try:
            # Build query parameters for filters
            params = {}
            if date_range and len(date_range) == 2:
                if date_range[0]:
                    params["start_date"] = date_range[0]
                if date_range[1]:
                    params["end_date"] = date_range[1]
            if user_type and user_type != "all":
                params["user_type"] = user_type
            if user_id:
                params["user_id"] = user_id

            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/user-types-distribution",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                params=params,
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
        Output("users-active-today-content", "children"),
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-users-active-today", "n_clicks"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_users_active_today(n_intervals, refresh_clicks, local_data):
        """Update users active today metrics."""
        try:
            # Since API works with just internal API key, try that first
            headers = {"X-Api-Key": settings.auth.internal_api_key}

            # Add authorization if available (not required for this endpoint)
            if local_data and local_data.get("access_token"):
                headers["Authorization"] = f"Bearer {local_data['access_token']}"

            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/users-active-today",
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]
                print(f"DEBUG: Successfully fetched users active today data: {data}")
            else:
                print(f"API returned status {response.status_code}: {response.text}")
                return dmc.Text(f"API Error {response.status_code}", c="red", ta="center")

        except Exception as e:
            print(f"Failed to fetch users active today: {e}")
            import traceback

            traceback.print_exc()
            return dmc.Text("Failed to load data", c="red", ta="center")

        # Render the data - simplified version for debugging
        try:
            return dmc.Stack(
                [
                    dmc.Text(
                        f"Total Active: {data.get('total_active', 0)}",
                        size="lg",
                        fw="bold",
                        c="blue",
                    ),
                    dmc.Text(
                        f"Authenticated: {data.get('authenticated_users', 0)}", size="md", c="green"
                    ),
                    dmc.Text(
                        f"Anonymous: {data.get('anonymous_sessions', 0)}", size="md", c="orange"
                    ),
                    dmc.Badge("Last 24h", color="blue", variant="light"),
                ],
                gap="sm",
                align="center",
            )
        except Exception as e:
            print(f"Error rendering users active today component: {e}")
            return dmc.Text(f"Render error: {str(e)}", c="red", ta="center")

    @app.callback(
        Output("activity-overview-content", "children"),
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-activity-overview", "n_clicks"),
            Input("date-range-picker", "value"),
            Input("user-type-filter", "value"),
            Input("specific-user-filter", "value"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_activity_overview(
        n_intervals, refresh_clicks, date_range, user_type, user_id, local_data
    ):
        """Update activity overview content."""
        if not local_data or not local_data.get("access_token"):
            return html.Div("No data available")

        try:
            # Build query parameters for filters
            params = {}
            if date_range and len(date_range) == 2:
                if date_range[0]:
                    params["start_date"] = date_range[0]
                if date_range[1]:
                    params["end_date"] = date_range[1]
            if user_type and user_type != "all":
                params["user_type"] = user_type
            if user_id:
                params["user_id"] = user_id

            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/activity-trends",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                params=params,
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

    @app.callback(
        Output("specific-user-filter", "data"),
        Input("analytics-auto-refresh", "n_intervals"),
        State("local-store", "data"),
    )
    def update_user_filter_options(n_intervals, local_data):
        """Update the user filter dropdown options."""
        if not local_data or not local_data.get("access_token"):
            return []

        try:
            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/user-list",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]
                return data
            else:
                return []

        except Exception as e:
            print(f"Failed to fetch user list: {e}")
            return []

    @app.callback(
        Output("top-pages-content", "children"),
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-top-pages", "n_clicks"),
            Input("date-range-picker", "value"),
            Input("user-type-filter", "value"),
            Input("specific-user-filter", "value"),
        ],
        State("local-store", "data"),
    )
    def update_top_pages(n_intervals, refresh_clicks, date_range, user_type, user_id, local_data):
        """Update top pages content."""
        if not local_data or not local_data.get("access_token"):
            return dmc.Text("Authentication required", c="red")

        try:
            # Build query parameters for filters
            params = {"limit": 10}
            if date_range and len(date_range) == 2:
                if date_range[0]:
                    params["start_date"] = date_range[0]
                if date_range[1]:
                    params["end_date"] = date_range[1]
            if user_type and user_type != "all":
                params["user_type"] = user_type
            if user_id:
                params["user_id"] = user_id

            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/top-pages",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                params=params,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()["data"]

                if not data:
                    return dmc.Text("No page data available yet", c="gray", ta="center", mt="xl")

                return dmc.Stack(
                    [
                        dmc.Group(
                            [
                                dmc.Text(page["path"], fw="bold", size="sm"),
                                dmc.Group(
                                    [
                                        dmc.Badge(
                                            f"{page['page_views']:,}", color="blue", variant="light"
                                        ),
                                        dmc.Text(f"{page['percentage']}%", size="xs", c="gray"),
                                    ],
                                    gap="xs",
                                ),
                            ],
                            justify="space-between",
                        )
                        for page in data
                    ],
                    gap="sm",
                )
            else:
                return dmc.Text("Error loading page data", c="red")

        except Exception as e:
            print(f"Failed to fetch top pages data: {e}")
            return dmc.Text("Failed to load data", c="red")

    @app.callback(
        [
            Output("date-range-picker", "value"),
            Output("user-type-filter", "value"),
            Output("specific-user-filter", "value"),
        ],
        Input("clear-filters", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_all_filters(n_clicks):
        """Clear all filters when clear button is clicked."""
        if n_clicks:
            from datetime import datetime, timedelta

            return [
                [datetime.now().date() - timedelta(days=7), datetime.now().date()],
                "all",
                None,
            ]
        raise PreventUpdate

    @app.callback(
        Output("comprehensive-summary-content", "children"),
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-comprehensive-summary", "n_clicks"),
            Input("date-range-picker", "value"),
            Input("user-type-filter", "value"),
            Input("specific-user-filter", "value"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_comprehensive_summary(
        n_intervals, refresh_clicks, date_range, user_type, user_id, local_data
    ):
        """Update comprehensive analytics summary."""
        if not local_data or not local_data.get("access_token"):
            return dmc.Text("Authentication required", c="red")

        try:
            # Build query parameters for filters
            params = {}
            if date_range and len(date_range) == 2:
                if date_range[0]:
                    params["start_date"] = date_range[0]
                if date_range[1]:
                    params["end_date"] = date_range[1]
            if user_type and user_type != "all":
                params["user_type"] = user_type
            if user_id:
                params["user_id"] = user_id

            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics-data/dashboard/comprehensive-summary",
                headers={
                    "Authorization": f"Bearer {local_data['access_token']}",
                    "X-Api-Key": settings.auth.internal_api_key,
                },
                params=params,
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()["data"]
                period_summary = data["period_summary"]
                user_breakdown = data["user_breakdown"]

                if not user_breakdown:
                    return dmc.Text(
                        "No data available for the selected period", c="gray", ta="center", mt="xl"
                    )

                # Create summary metrics grid
                summary_grid = dmc.Grid(
                    [
                        dmc.GridCol(
                            dmc.Stack(
                                [
                                    dmc.Text("Total Users", size="sm", c="gray", fw="bold"),
                                    dmc.Text(
                                        f"{period_summary['total_users']:,}",
                                        size="xl",
                                        fw="bold",
                                        c="blue",
                                    ),
                                ],
                                gap="xs",
                                align="center",
                            ),
                            span=2,
                        ),
                        dmc.GridCol(
                            dmc.Stack(
                                [
                                    dmc.Text("Total Sessions", size="sm", c="gray", fw="bold"),
                                    dmc.Text(
                                        f"{period_summary['total_sessions']:,}",
                                        size="xl",
                                        fw="bold",
                                        c="green",
                                    ),
                                ],
                                gap="xs",
                                align="center",
                            ),
                            span=2,
                        ),
                        dmc.GridCol(
                            dmc.Stack(
                                [
                                    dmc.Text("Page Views", size="sm", c="gray", fw="bold"),
                                    dmc.Text(
                                        f"{period_summary['total_page_views']:,}",
                                        size="xl",
                                        fw="bold",
                                        c="orange",
                                    ),
                                ],
                                gap="xs",
                                align="center",
                            ),
                            span=2,
                        ),
                        dmc.GridCol(
                            dmc.Stack(
                                [
                                    dmc.Text("API Calls", size="sm", c="gray", fw="bold"),
                                    dmc.Text(
                                        f"{period_summary['total_api_calls']:,}",
                                        size="xl",
                                        fw="bold",
                                        c="red",
                                    ),
                                ],
                                gap="xs",
                                align="center",
                            ),
                            span=2,
                        ),
                        dmc.GridCol(
                            dmc.Stack(
                                [
                                    dmc.Text("Total Time", size="sm", c="gray", fw="bold"),
                                    dmc.Text(
                                        f"{period_summary['total_time_minutes']:.0f}m",
                                        size="xl",
                                        fw="bold",
                                        c="violet",
                                    ),
                                ],
                                gap="xs",
                                align="center",
                            ),
                            span=2,
                        ),
                        dmc.GridCol(
                            dmc.Stack(
                                [
                                    dmc.Text("Avg Session", size="sm", c="gray", fw="bold"),
                                    dmc.Text(
                                        f"{period_summary['avg_session_duration']:.1f}m",
                                        size="xl",
                                        fw="bold",
                                        c="teal",
                                    ),
                                ],
                                gap="xs",
                                align="center",
                            ),
                            span=2,
                        ),
                    ],
                    gutter="md",
                )

                # Create user breakdown table
                user_table_data = []
                for user in user_breakdown[:10]:  # Top 10 users
                    user_table_data.append(
                        {
                            "User": user["user_email"]
                            if not user["is_anonymous"]
                            else f"Anonymous ({user['user_email']})",
                            "Sessions": user["sessions"],
                            "Page Views": user["page_views"],
                            "API Calls": user["api_calls"],
                            "Time (min)": f"{user['time_minutes']:.0f}",
                            "Avg Session": f"{user['avg_session_duration']:.1f}m",
                            "Type": "Admin"
                            if user["is_admin"]
                            else ("Auth" if not user["is_anonymous"] else "Anon"),
                        }
                    )

                user_table = dash_table.DataTable(
                    data=user_table_data,
                    columns=[{"name": col, "id": col} for col in user_table_data[0].keys()],
                    filter_action="native",  # Enable column filtering
                    sort_action="native",  # Enable column sorting
                    page_size=10,
                    style_cell={
                        "textAlign": "left",
                        "fontSize": "13px",
                        "fontFamily": "Arial",
                        "backgroundColor": "var(--app-surface-color, #ffffff)",
                        "color": "var(--app-text-color, #000000)",
                        "padding": "8px",
                    },
                    style_header={
                        "backgroundColor": "var(--app-border-color, #e0e0e0)",
                        "fontWeight": "bold",
                        "fontSize": "13px",
                    },
                    style_filter={
                        "backgroundColor": "var(--app-surface-color, #ffffff)",
                        "color": "var(--app-text-color, #000000)",
                        "border": "1px solid var(--app-border-color, #ddd)",
                        "fontSize": "12px",
                    },
                    style_data_conditional=[
                        {
                            "if": {"column_id": "Type", "filter_query": "{Type} = Admin"},
                            "color": "green",
                            "fontWeight": "bold",
                        },
                        {
                            "if": {"column_id": "Type", "filter_query": "{Type} = Auth"},
                            "color": "blue",
                        },
                        {
                            "if": {"column_id": "Type", "filter_query": "{Type} = Anon"},
                            "color": "gray",
                        },
                    ],
                )

                return dmc.Stack(
                    [
                        # Summary metrics
                        summary_grid,
                        dmc.Divider(),
                        # User breakdown table
                        dmc.Title("User Activity Breakdown", order=5, c="dark", mt="md"),
                        user_table,
                    ],
                    gap="md",
                )
            else:
                return dmc.Text("Error loading comprehensive summary", c="red")

        except Exception as e:
            print(f"Failed to fetch comprehensive summary: {e}")
            return dmc.Text("Failed to load comprehensive summary", c="red")

    @app.callback(
        Output("unique-connections-content", "children"),
        [
            Input("analytics-auto-refresh", "n_intervals"),
            Input("refresh-unique-connections", "n_clicks"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_unique_connections(n_intervals, refresh_clicks, local_data):
        """Update unique connections and IP address analytics."""
        try:
            headers = {"X-Api-Key": settings.auth.internal_api_key}
            if local_data and local_data.get("access_token"):
                headers["Authorization"] = f"Bearer {local_data['access_token']}"

            # Call the unique connections endpoint
            response = requests.get(
                f"{settings.fastapi.url}/depictio/api/v1/analytics/unique-connections",
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                print("DEBUG: Successfully fetched unique connections data")
            else:
                print(
                    f"Unique connections API returned status {response.status_code}: {response.text}"
                )
                return dmc.Text(f"API Error {response.status_code}", c="red", ta="center")

        except Exception as e:
            print(f"Failed to fetch unique connections: {e}")
            import traceback

            traceback.print_exc()
            return dmc.Text("Failed to load IP analytics", c="red", ta="center")

        try:
            # Extract connection summary
            conn_summary = data.get("connection_summary", {})
            top_ips = data.get("top_ip_addresses", [])

            # Create summary metrics
            summary_stack = dmc.Stack(
                [
                    dmc.Group(
                        [
                            dmc.Text("Unique IPs:", size="sm", fw="bold"),
                            dmc.Badge(
                                str(data.get("unique_ip_addresses", 0)),
                                color="indigo",
                                variant="light",
                            ),
                        ],
                        justify="space-between",
                    ),
                    dmc.Group(
                        [
                            dmc.Text("Authenticated:", size="sm"),
                            dmc.Text(
                                str(conn_summary.get("authenticated_connections", 0)), c="green"
                            ),
                        ],
                        justify="space-between",
                    ),
                    dmc.Group(
                        [
                            dmc.Text("Anonymous:", size="sm"),
                            dmc.Text(str(conn_summary.get("anonymous_connections", 0)), c="orange"),
                        ],
                        justify="space-between",
                    ),
                ],
                gap="xs",
            )

            # Create top IPs list (show top 3)
            ip_items = []
            for i, ip_data in enumerate(top_ips[:3], 1):
                ip_items.append(
                    dmc.Group(
                        [
                            dmc.Text(f"{i}. {ip_data['ip_address']}", size="xs", fw="bold"),
                            dmc.Badge(
                                f"{ip_data['total_sessions']} sessions",
                                size="xs",
                                color="cyan" if not ip_data.get("is_anonymous") else "gray",
                                variant="outline",
                            ),
                        ],
                        justify="space-between",
                        gap="xs",
                    )
                )

            return dmc.Stack(
                [
                    summary_stack,
                    dmc.Divider(size="xs"),
                    dmc.Text("Top IP Addresses", size="sm", fw="bold", c="dark"),
                    dmc.Stack(ip_items, gap="xs")
                    if ip_items
                    else dmc.Text("No data", size="sm", c="gray"),
                ],
                gap="sm",
            )

        except Exception as e:
            print(f"Error rendering unique connections: {e}")
            return dmc.Text("Error processing IP analytics", c="red", ta="center")
