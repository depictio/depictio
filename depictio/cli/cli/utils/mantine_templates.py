"""Native Plotly ``mantine_light`` / ``mantine_dark`` templates + theme helper.

Single source of truth for the two server-rendered figure templates and the
``theme -> template name`` mapping. Lives in ``depictio.cli.cli.utils`` (a
package shipped with the CLI) so that **both** the API render path *and* the CLI
offline figure prerender build byte-identical figures — the CLI cannot import
``depictio.api.v1.services.*`` (not shipped in a CLI-only install), so this
shared render asset has to live on the CLI side, mirroring the existing
``sample_mapping`` helper the API already imports from here.

The API modules ``figure/mantine_templates.py`` and ``multiqc/themes.py`` are
thin re-export shims over this module, so every existing
``ensure_mantine_templates`` / ``get_theme_template`` import keeps working
unchanged.

Replaces the former ``dash_mantine_components.add_figure_templates()`` call,
dropped when Dash was removed in the React migration. We don't want to pull
Dash back into the API/worker images just to register two Plotly templates, so
this rebuilds them from the standard Mantine default palette — the same hex
values dmc used — keeping server-rendered figures visually identical.

Mantine palette reference (shade index): accent colors use [6] (light) / [8]
(dark); ``dark[7]`` is the dark paper background.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# Mantine default fontFamily.
_FONT_FAMILY = (
    "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, "
    'sans-serif, "Apple Color Emoji", "Segoe UI Emoji"'
)

# Categorical colorway — Mantine [blue, red, green, violet, orange, cyan, pink,
# yellow] at shade 6 (light) and shade 8 (dark).
_LIGHT_COLORWAY = [
    "#228be6",
    "#fa5252",
    "#40c057",
    "#7950f2",
    "#fd7e14",
    "#15aabf",
    "#e64980",
    "#fab005",
]
_DARK_COLORWAY = [
    "#1971c2",
    "#e03131",
    "#2f9e44",
    "#6741d9",
    "#e8590c",
    "#0c8599",
    "#c2255c",
    "#f08c00",
]

# Sequential colorscale shared by both templates (dmc's gradient).
_SEQUENTIAL_COLORS = [
    "#1864ab",
    "#7065b9",
    "#af61b7",
    "#e35ea5",
    "#ff6587",
    "#ff7c63",
    "#ff9e3d",
    "#fcc419",
]
_SEQUENTIAL = [[i / (len(_SEQUENTIAL_COLORS) - 1), c] for i, c in enumerate(_SEQUENTIAL_COLORS)]


def _build(colorway: list[str], bg: str, grid: str) -> go.layout.Template:
    axis = dict(gridcolor=grid, gridwidth=0.5, zerolinecolor=grid)
    return go.layout.Template(
        layout=dict(
            colorway=colorway,
            paper_bgcolor=bg,
            plot_bgcolor=bg,
            font=dict(family=_FONT_FAMILY),
            xaxis=axis,
            yaxis=axis,
            geo=dict(bgcolor=bg),
            colorscale=dict(sequential=_SEQUENTIAL),
        )
    )


def ensure_mantine_templates() -> None:
    """Register ``mantine_light``/``mantine_dark`` in ``plotly.io.templates``.

    Idempotent and self-guarding — safe to call on every figure-build entry
    point (mirrors the old dmc guard). Replaces ``dmc.add_figure_templates()``.
    """
    if "mantine_light" not in pio.templates:
        pio.templates["mantine_light"] = _build(_LIGHT_COLORWAY, "#ffffff", "#dee2e6")
    if "mantine_dark" not in pio.templates:
        pio.templates["mantine_dark"] = _build(_DARK_COLORWAY, "#1a1b1e", "#343a40")


def get_theme_template(theme: str) -> str:
    """Return the Plotly template name for the given UI theme.

    Registers the templates as a side effect: a bare name is only usable if it
    resolves in ``pio.templates``, and every caller asking for one is about to
    hand it to Plotly. Leaving registration to the figure *build* meant any path
    that skipped the build — a warm figure cache returning ``go.Figure(dict)``,
    then re-templated for the other theme — got a name Plotly rejects.

    Args:
        theme: theme name (e.g. "light", "dark"); empty / falsy values fall back to light.

    Returns:
        "mantine_dark" or "mantine_light".
    """
    ensure_mantine_templates()
    if not theme or theme == {} or theme == "{}":
        theme = "light"
    return "mantine_dark" if theme == "dark" else "mantine_light"
