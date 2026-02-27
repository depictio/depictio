"""
Sidebar panel for managing active global (cross-tab) filters.

Provides:
- create_global_filters_panel(): Static layout with container divs
- register_global_filters_panel_callbacks(): Callbacks to render filter list and handle removal

The panel is displayed in the dashboard sidebar below the tab list.
"""

from typing import Any

import dash
import dash_mantine_components as dmc
import httpx
from dash import Input, Output, State, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger


def create_global_filters_panel() -> html.Div:
    """Create the sidebar section showing active global filters.

    Returns:
        Div containing the global filters panel with header and filter list container.
    """
    return html.Div(
        id="global-filters-panel",
        children=[
            dmc.Divider(variant="dashed", my="xs"),
            dmc.Group(
                [
                    DashIconify(icon="mdi:filter-variant", width=16, color="blue"),
                    dmc.Text("Global Filters", size="sm", fw=500),
                    dmc.Badge(
                        id="global-filter-count",
                        size="xs",
                        variant="filled",
                        color="blue",
                        children="0",
                    ),
                ],
                gap="xs",
                align="center",
                px="md",
                py="xs",
            ),
            html.Div(id="global-filters-list", style={"padding": "0 12px"}),
        ],
        style={"display": "none"},  # Hidden when no global filters
    )


def register_global_filters_panel_callbacks(app: dash.Dash) -> None:
    """Register callbacks for the global filters sidebar panel.

    Two callbacks:
    1. Render the filter list and badge count from global-filters-store
    2. Handle filter removal when close button is clicked

    Args:
        app: Dash application instance.
    """

    @app.callback(
        Output("global-filters-list", "children"),
        Output("global-filter-count", "children"),
        Output("global-filters-panel", "style"),
        Input("global-filters-store", "data"),
    )
    def render_global_filters_list(
        global_filters: dict[str, Any] | None,
    ) -> tuple[list[Any], str, dict[str, str]]:
        """Render active global filters as removable badges.

        Args:
            global_filters: Current global filter state.

        Returns:
            Tuple of (filter_badges, count_text, panel_style).
        """
        if not global_filters:
            return [], "0", {"display": "none"}

        badges: list[Any] = []
        for filter_key, filter_data in global_filters.items():
            if not isinstance(filter_data, dict):
                continue

            column_name = filter_data.get("column_name", filter_key)
            values = filter_data.get("values")

            # Build human-readable label
            if isinstance(values, list) and len(values) <= 3:
                value_str = ", ".join(str(v) for v in values)
            elif isinstance(values, list):
                value_str = f"{len(values)} values"
            elif values is not None:
                value_str = str(values)
            else:
                value_str = "all"

            label = f"{column_name}: {value_str}"

            badge = dmc.Badge(
                label,
                id={"type": "global-filter-remove", "index": filter_key},
                size="sm",
                variant="outline",
                color="blue",
                rightSection=DashIconify(icon="mdi:close", width=12),
                style={"cursor": "pointer", "maxWidth": "100%"},
                fullWidth=True,
            )
            badges.append(dmc.Stack([badge], gap="4px", mb="4px"))

        count = str(len(badges))
        style = {"display": "block"} if badges else {"display": "none"}
        return badges, count, style

    @app.callback(
        Output("global-filters-store", "data", allow_duplicate=True),
        Input({"type": "global-filter-remove", "index": dash.ALL}, "n_clicks"),
        State("global-filters-store", "data"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def remove_global_filter(
        n_clicks_list: list[int | None],
        global_filters: dict[str, Any] | None,
        local_data: dict[str, Any] | None,
        pathname: str | None,
    ) -> dict[str, Any]:
        """Remove a global filter when its close button is clicked.

        Args:
            n_clicks_list: Click counts for all remove buttons.
            global_filters: Current global filter state.
            local_data: User auth data.
            pathname: Current URL.

        Returns:
            Updated global filters with the clicked filter removed.
        """
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        triggered_id = ctx.triggered_id
        if not isinstance(triggered_id, dict) or triggered_id.get("type") != "global-filter-remove":
            raise dash.exceptions.PreventUpdate

        filter_key = triggered_id.get("index")
        if not filter_key or not global_filters:
            raise dash.exceptions.PreventUpdate

        global_filters = dict(global_filters)
        if filter_key in global_filters:
            del global_filters[filter_key]
            logger.info(f"Global filter removed: {filter_key}")

        # Persist to MongoDB
        access_token = local_data.get("access_token") if local_data else None
        dashboard_id = ""
        if pathname:
            parts = pathname.strip("/").split("/")
            if len(parts) >= 2:
                dashboard_id = parts[-1].replace("/edit", "")

        if access_token and dashboard_id:
            try:
                from depictio.dash.api_calls import API_BASE_URL

                httpx.put(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/global-filters/{dashboard_id}",
                    json=global_filters,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5.0,
                )
            except Exception as e:
                logger.debug(f"Could not persist global filter removal: {e}")

        return global_filters
