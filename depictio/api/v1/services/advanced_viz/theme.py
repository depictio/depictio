"""Python port of ``advanced_viz/plotlyTheme.ts``.

Kept a faithful mirror of the TypeScript so a Python-built figure and the
client-rendered one are visually identical and the golden-JSON parity tests in
``depictio/tests/api/v1/services/advanced_viz/`` can compare them directly. When
the TS file changes, this one must change with it.

Builders take an explicit :class:`PlotlyThemeColors` rather than a theme name, so
they stay pure functions — that is what makes them cheap to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Mantine's default gray scale. The viewer does not override `colors.gray`
# (checked in depictio/viewer/src/theme.ts), so `theme.colors.gray[N]` in
# plotlyTheme.ts resolves to these. Pinned as literals because the Python side
# has no Mantine theme object to read from.
_MANTINE_GRAY_2 = "#e9ecef"
_MANTINE_GRAY_8 = "#343a40"


@dataclass(frozen=True)
class PlotlyThemeColors:
    """Mirror of the ``PlotlyThemeColors`` interface in plotlyTheme.ts."""

    text_color: str
    grid_color: str
    zero_line_color: str
    bg_color: str


def plotly_theme_colors(is_dark: bool) -> PlotlyThemeColors:
    """Resolve the four theme colours for a light or dark render."""
    return PlotlyThemeColors(
        text_color=_MANTINE_GRAY_2 if is_dark else _MANTINE_GRAY_8,
        grid_color="rgba(255,255,255,0.08)" if is_dark else "rgba(0,0,0,0.08)",
        zero_line_color="rgba(255,255,255,0.35)" if is_dark else "rgba(0,0,0,0.35)",
        bg_color="rgba(0,0,0,0)",
    )


def colors_for_theme(theme: str) -> PlotlyThemeColors:
    """Convenience wrapper taking the wire value ``"light"`` / ``"dark"``."""
    return plotly_theme_colors(theme == "dark")


def _retint_title(title: Any, color: str) -> Any:
    """Normalise a title (string or dict) and force its font colour."""
    if title is None:
        return None
    if isinstance(title, str):
        return {"text": title, "font": {"color": color}}
    if isinstance(title, dict):
        font = {**(title.get("font") or {}), "color": color}
        return {**title, "font": font}
    return title


def _retint_axis(axis: Any, c: PlotlyThemeColors) -> dict[str, Any]:
    a = dict(axis or {})
    a["color"] = c.text_color
    a["gridcolor"] = c.grid_color
    a["zerolinecolor"] = c.zero_line_color
    a["linecolor"] = c.grid_color
    a["tickfont"] = {**(a.get("tickfont") or {}), "color": c.text_color}
    if a.get("title") is not None:
        a["title"] = _retint_title(a["title"], c.text_color)
    return a


def _retint_colorbar(holder: dict[str, Any], c: PlotlyThemeColors) -> dict[str, Any]:
    cb = dict(holder.get("colorbar") or {})
    cb["tickfont"] = {**(cb.get("tickfont") or {}), "color": c.text_color}
    if cb.get("title") is not None:
        cb["title"] = _retint_title(cb["title"], c.text_color)
    return {**holder, "colorbar": cb}


def apply_layout_theme(layout: dict[str, Any] | None, c: PlotlyThemeColors) -> dict[str, Any]:
    """Retint every axis, scene, legend, annotation and colorbar in a layout.

    Explicit rather than relying on Plotly's template-vs-layout precedence, which
    is unreliable. Idempotent, so it is safe on an already-themed layout.
    """
    out: dict[str, Any] = dict(layout or {})

    for key in list(out.keys()):
        value = out[key]
        if key.startswith(("xaxis", "yaxis", "zaxis")):
            out[key] = _retint_axis(value, c)
        elif key.startswith("scene"):
            scene = dict(value or {})
            for sub in ("xaxis", "yaxis", "zaxis"):
                if scene.get(sub) is not None:
                    scene[sub] = _retint_axis(scene[sub], c)
            scene["bgcolor"] = c.bg_color
            out[key] = scene
        elif key == "coloraxis" and isinstance(value, dict):
            out[key] = _retint_colorbar(value, c)
        elif key == "annotations" and isinstance(value, list):
            # Only retint annotations with no explicit colour — colour-coded ones
            # (tier badges, signed-effect labels) carry meaning and must survive.
            out[key] = [
                a
                if not isinstance(a, dict) or (a.get("font") or {}).get("color") is not None
                else {**a, "font": {**(a.get("font") or {}), "color": c.text_color}}
                for a in value
            ]
        elif key == "legend" and isinstance(value, dict):
            legend = dict(value)
            legend["font"] = {**(legend.get("font") or {}), "color": c.text_color}
            legend["bgcolor"] = c.bg_color
            if legend.get("title") is not None:
                legend["title"] = _retint_title(legend["title"], c.text_color)
            out[key] = legend
        elif key == "title" and isinstance(value, dict):
            out[key] = _retint_title(value, c.text_color)

    # Theme-level values go last so they win over anything baked into the input.
    return {
        **out,
        "template": "plotly_dark" if c.text_color == _MANTINE_GRAY_2 else "plotly_white",
        "plot_bgcolor": c.bg_color,
        "paper_bgcolor": c.bg_color,
        "font": {**(out.get("font") or {}), "color": c.text_color},
    }


def apply_data_theme(data: list[Any] | None, c: PlotlyThemeColors) -> list[Any]:
    """Retint per-trace colorbars and text fonts.

    Trace ``textfont`` is only retinted when the trace did not pick a colour
    itself, preserving tier-coloured labels (volcano UP/DN, manhattan HIT/MISS).
    """
    out: list[Any] = []
    for trace in data or []:
        if not isinstance(trace, dict):
            out.append(trace)
            continue
        t = dict(trace)
        if t.get("colorbar") is not None:
            t["colorbar"] = _retint_colorbar({"colorbar": t["colorbar"]}, c)["colorbar"]
        if isinstance(t.get("marker"), dict):
            marker = dict(t["marker"])
            if marker.get("colorbar") is not None:
                marker["colorbar"] = _retint_colorbar({"colorbar": marker["colorbar"]}, c)[
                    "colorbar"
                ]
            t["marker"] = marker
        if isinstance(t.get("textfont"), dict) and t["textfont"].get("color") is None:
            t["textfont"] = {**t["textfont"], "color": c.text_color}
        out.append(t)
    return out


def apply_theme(spec: dict[str, Any], theme: str) -> dict[str, Any]:
    """Apply both passes to a ``{data, layout}`` spec."""
    c = colors_for_theme(theme)
    return {
        "data": apply_data_theme(spec.get("data"), c),
        "layout": apply_layout_theme(spec.get("layout"), c),
    }
