"""
Real-time WebSocket component for dashboard updates.

Provides WebSocket connection to the backend events API for real-time
notifications when data collections are updated.
"""

from typing import Literal

import dash_mantine_components as dmc
from dash import html
from dash_extensions import WebSocket

# Valid color literals for DMC Badge
BadgeColor = Literal[
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
]


def create_websocket_component(component_id: str = "ws") -> WebSocket:
    """
    Create a WebSocket component for real-time updates.

    The URL is set dynamically via clientside callback to adapt to
    the current protocol (ws/wss) and host.
    """
    return WebSocket(id=component_id, url="")


def create_live_indicator(
    component_id: str = "live-indicator",
    default_text: str = "Live",
    default_color: BadgeColor = "green",
) -> dmc.Badge:
    """
    Create a live indicator badge for the dashboard header.

    Shows connection status:
    - Green "Live" when connected
    - Orange "Paused" when updates are paused
    - Red "Disconnected" when not connected
    """
    return dmc.Badge(
        default_text,
        id=component_id,
        color=default_color,
        variant="dot",
        size="sm",
    )


def create_pending_update_badge(component_id: str = "pending-badge") -> dmc.Badge:
    """
    Create a badge showing pending updates count.

    Hidden by default, shown when updates are available.
    """
    return dmc.Badge(
        "Updates available",
        id=component_id,
        color="orange",
        variant="filled",
        size="sm",
        style={"display": "none"},
    )


def create_realtime_controls() -> dmc.Group:
    """
    Create the real-time update controls for the settings drawer.

    Includes Live/Paused toggle and refresh mode selector.
    """
    return dmc.Group(
        [
            dmc.Stack(
                [
                    dmc.Text("Real-time Updates", size="sm", fw="bold"),
                    dmc.Switch(
                        id="realtime-enabled-toggle",
                        label="Enabled",
                        checked=True,
                        size="sm",
                    ),
                    dmc.Switch(
                        id="realtime-auto-refresh-toggle",
                        label="Auto-refresh (vs notifications)",
                        checked=False,
                        size="sm",
                    ),
                ],
                gap="xs",
            ),
        ],
    )


def create_websocket_layout(dashboard_id: str | None = None) -> html.Div:
    """
    Create the complete WebSocket layout for a dashboard.

    Includes the WebSocket component and hidden stores.
    Should be included in the dashboard viewer/editor layouts.
    """
    return html.Div(
        [
            create_websocket_component("ws"),
            html.Div(id="ws-dashboard-id", style={"display": "none"}, children=dashboard_id or ""),
        ],
        style={"display": "none"},
    )
