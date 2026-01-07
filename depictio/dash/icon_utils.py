"""Icon utilities for Dash dashboard components."""

from dash_iconify import DashIconify


def DashboardIcon(icon: str, color: str = "blue", width: int = 20) -> DashIconify:
    """
    Create a dashboard icon component using DashIconify.

    This is a convenience wrapper around DashIconify that provides consistent
    default styling for dashboard icons throughout the application.

    Args:
        icon: Icon name from iconify library (e.g., "mdi:view-dashboard", "mdi:chart-line")
        color: Icon color, can be any CSS color value (default: "blue")
        width: Icon width in pixels (default: 20)

    Returns:
        DashIconify component configured with the specified parameters

    Example:
        >>> from depictio.dash.icon_utils import DashboardIcon
        >>> icon = DashboardIcon("mdi:view-dashboard", color="orange", width=24)
    """
    return DashIconify(icon=icon, color=color, width=width)
