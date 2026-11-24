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
this rebuilds them from the shared depictio plot palette
(``depictio.models.palettes``): the categorical colorway, the sequential
colorscale and the text / grid / axis tokens are the same ones the viewer's
Plotly theme reads, so a server-rendered figure matches a client-rendered one.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

from depictio.models import palettes

# The plot font stack. The minimal figure style reads it to tell a brand font
# (kept) from this default (replaced by Inter).
FONT_FAMILY = palettes.font_family()


def _sequential(mode: str) -> list[list[float | str]]:
    """The default sequential colorscale of a mode, as Plotly stops."""
    return palettes.colorscale(palettes.sequential(None, mode))


# Transparent, not a painted rectangle. Every server-rendered figure sits on a
# card the app has already painted, and the client-side advanced-viz renderers
# theme themselves that way (`plotlyTheme.ts`) — a figure that paints its own
# opaque `#1a1b1e` reads as a darker block sitting inside the card, which is
# exactly how a code-mode figure and an advanced viz stopped matching in dark
# mode. Text and grid colours come from the shared chrome tokens so both paths
# land on one appearance.
_TRANSPARENT = "rgba(0,0,0,0)"


def _build(mode: str) -> go.layout.Template:
    chrome = palettes.chrome(mode)
    text = chrome["text"]
    # `color` covers the axis line and tick labels; a template that sets only
    # `font.family` leaves Plotly's built-in `#444`, which is unreadable on a
    # dark card.
    axis = dict(
        gridcolor=chrome["grid"],
        gridwidth=0.5,
        zerolinecolor=chrome["zero"],
        linecolor=chrome["axis_line"],
        color=text,
    )
    return go.layout.Template(
        layout=dict(
            colorway=palettes.categorical(None, mode),
            paper_bgcolor=_TRANSPARENT,
            plot_bgcolor=_TRANSPARENT,
            font=dict(family=FONT_FAMILY, color=text),
            xaxis=axis,
            yaxis=axis,
            geo=dict(bgcolor=_TRANSPARENT),
            colorscale=dict(sequential=_sequential(mode)),
        )
    )


def ensure_mantine_templates() -> None:
    """Register ``mantine_light``/``mantine_dark`` in ``plotly.io.templates``.

    Idempotent and self-guarding — safe to call on every figure-build entry
    point (mirrors the old dmc guard). Replaces ``dmc.add_figure_templates()``.
    """
    if "mantine_light" not in pio.templates:
        pio.templates["mantine_light"] = _build("light")
    if "mantine_dark" not in pio.templates:
        pio.templates["mantine_dark"] = _build("dark")


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
