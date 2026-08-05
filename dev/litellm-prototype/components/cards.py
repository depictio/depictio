"""Metric stat card components."""

from __future__ import annotations

import dash_mantine_components as dmc
from dash_iconify import DashIconify


def create_stat_card(
    title: str,
    value: str | int | float,
    icon: str = "mdi:chart-line",
    color: str | None = None,
) -> dmc.Card:
    """Create a metric card matching depictio's card style.

    Args:
        title: Card title text.
        value: The metric value to display.
        icon: Material Design Icon name.
        color: Optional accent color.
    """
    icon_style = {"color": color} if color else {}

    card_content = dmc.Stack(
        [
            dmc.Group(
                [
                    DashIconify(icon=icon, width=24, style=icon_style),
                    dmc.Text(title, size="sm", fw=500, c="dimmed"),
                ],
                gap="xs",
                align="center",
            ),
            dmc.Text(
                str(value),
                size="xl",
                fw=700,
            ),
        ],
        gap="xs",
    )

    return dmc.Card(
        dmc.CardSection(
            card_content,
            p="md",
            style={
                "height": "100%",
                "display": "flex",
                "flexDirection": "column",
                "justifyContent": "center",
            },
        ),
        withBorder=True,
        shadow="sm",
        radius="md",
        style={"height": "100%", "minHeight": "120px"},
    )
