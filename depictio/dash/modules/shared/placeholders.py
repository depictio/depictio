"""Shared placeholder components for unavailable data collections.

When a dashboard component's DC has no data (missing pipeline output, skipped
processing, etc.), these utilities produce styled informational placeholders
instead of red error messages.

Components are styled with a ``data-unavailable`` CSS class so the drawer
toggle can show/hide them all at once.
"""

import dash_mantine_components as dmc
import plotly.express as px
import plotly.graph_objects as go
from dash import html
from dash_iconify import DashIconify


def create_data_unavailable_box(
    dc_tag: str,
    description: str = "",
) -> html.Div:
    """Styled info box for components with missing DC data.

    Returns a gray, non-alarming box showing the DC tag and description.
    Wrapped in a div with ``className="data-unavailable"`` and
    ``style={"display": "none"}`` (hidden by default).

    Args:
        dc_tag: Data collection tag (e.g. ``alpha_diversity``).
        description: Optional human-readable description.
    """
    children = [
        dmc.Group(
            [
                dmc.ThemeIcon(
                    DashIconify(icon="tabler:database-off", width=20),
                    variant="light",
                    color="gray",
                    size="lg",
                ),
                dmc.Text("Data unavailable", fw=500, c="dimmed", size="sm"),
            ],
            gap="xs",
        ),
        dmc.Text(dc_tag, ff="monospace", size="xs", c="dimmed"),
    ]
    if description:
        children.append(dmc.Text(description, size="xs", c="dimmed"))

    return html.Div(
        dmc.Center(
            dmc.Stack(children, align="center", gap=4),
            h="100%",
        ),
        className="data-unavailable",
        style={"display": "none", "height": "100%"},
    )


def create_data_unavailable_figure(
    dc_tag: str,
    description: str = "",
    theme: str = "light",
) -> go.Figure:
    """Plotly figure annotation for components with missing DC data.

    Figure callbacks must return Plotly figure objects, not DMC components.
    This creates a gray (non-alarming) annotation, distinct from the red
    error annotations used for real errors.

    The figure is wrapped with a layout class ``data-unavailable-figure``
    that the toggle can target.

    Args:
        dc_tag: Data collection tag.
        description: Optional description.
        theme: ``"light"`` or ``"dark"``.
    """
    text = f"Data unavailable: {dc_tag}"
    if description:
        text += f"<br><span style='font-size:12px'>{description}</span>"

    template = "plotly_dark" if theme == "dark" else "plotly_white"

    fig = px.scatter(template=template, title="")
    fig.add_annotation(
        text=text,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        xanchor="center",
        yanchor="middle",
        showarrow=False,
        font={"size": 14, "color": "gray"},
        bgcolor="rgba(245,245,245,0.8)" if theme == "light" else "rgba(40,40,40,0.8)",
        bordercolor="lightgray",
        borderwidth=1,
        borderpad=10,
    )

    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
    )

    return fig
