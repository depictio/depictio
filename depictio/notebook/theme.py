"""The report's look: Depictio's Paper chrome, or the classic Mantine defaults.

Paper is the live app's default chrome (id ``glass``, name "Paper":
``viewer/src/chrome/variants/glass/``). This module is its Python side, so a
figure in an exported document looks like the same figure in the dashboard:

* :func:`paper_layout` is ``glassPlotly('light')`` (``plotly.ts``): Inter in
  three steps of ink, transparent paper and plot, a faint horizontal grid
  only, no axis lines and no ticks, a small hover card, boxless legends;
* :func:`paper_defaults` is ``glassPlotlyDefaults('light', layout)``: tight
  margins, the legend in one row at the top left when the figure has not
  placed it, and the colorway led by the instance's primary;
* :func:`apply_theme` merges both into a figure the way the app's
  ``applyChromePlotly`` does (``plotlyPatch.ts``): the defaults fill what the
  figure leaves unset, then the patch overrides.

:func:`use_theme` turns it on for the whole document (the export's setup cell
calls it): it registers the ``depictio_paper`` Plotly template, makes every
figure the document displays pass through :func:`apply_theme`, and returns the
``<style>`` that embeds Inter, so a self-contained report needs no font
request. Plotly cannot read CSS variables, so every colour here is the
concrete value Mantine resolves the app's variable to.
"""

from __future__ import annotations

import base64
import copy
import re
from functools import lru_cache
from importlib import resources
from typing import Any

# Mantine 7's default palette, the shades the Paper chrome reads
# (``--mantine-color-<name>-<shade>``). Light scheme only: a report is a page.
GRAY = {
    0: "#f8f9fa",
    1: "#f1f3f5",
    2: "#e9ecef",
    3: "#dee2e6",
    4: "#ced4da",
    5: "#adb5bd",
    6: "#868e96",
    7: "#495057",
    8: "#343a40",
    9: "#212529",
}
WHITE = "#ffffff"

# Shades 6 (filled, light scheme) and 7 (the accent's ink, ``--gl-accent-fg``)
# of every Mantine palette a brand's ``primary`` may name.
MANTINE_SHADES: dict[str, tuple[str, str]] = {
    "dark": ("#2e2e2e", "#242424"),
    "gray": ("#868e96", "#495057"),
    "red": ("#fa5252", "#f03e3e"),
    "pink": ("#e64980", "#d6336c"),
    "grape": ("#be4bdb", "#ae3ec9"),
    "violet": ("#7950f2", "#7048e8"),
    "indigo": ("#4c6ef5", "#4263eb"),
    "blue": ("#228be6", "#1c7ed6"),
    "cyan": ("#15aabf", "#1098ad"),
    "teal": ("#12b886", "#0ca678"),
    "green": ("#40c057", "#37b24d"),
    "lime": ("#82c91e", "#74b816"),
    "yellow": ("#fab005", "#f59f00"),
    "orange": ("#fd7e14", "#f76707"),
}

# An unbranded instance's primary: Mantine's blue (``buildDepictioTheme``).
DEFAULT_PRIMARY = "#228be6"

# ``GLASS_HUES``: Paper's series hues after the instance's primary, at shade 6.
GLASS_HUES = ("teal", "orange", "grape", "cyan", "pink", "lime", "indigo", "yellow", "red")

# The app's UI stack (``brandTheme.ts`` ``DEFAULT_FONT_FAMILY``), which Paper
# puts Inter in front of.
SYSTEM_SANS = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif'
)
MONO = 'Menlo, Monaco, Consolas, "Courier New", monospace'

THEMES = ("paper", "classic")
TEMPLATE_NAME = "depictio_paper"

_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")


def _alpha(color: str, a: float) -> str:
    """``#rrggbb`` at an alpha, as Plotly's ``rgba()`` (``plotly.ts`` ``alpha``)."""
    if not _HEX6.match(color):
        return color
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {a})"


def resolve_primary(primary: str | None) -> tuple[str, str]:
    """A brand's ``primary`` as ``(shade 6, shade 7)`` hex.

    A Mantine palette name resolves against Mantine's own shades; a hex goes
    through the same 10-shade ladder the app builds for it
    (``branding.derive_palette``), so the report's accent ink is the app's.
    """
    if not primary:
        return MANTINE_SHADES["blue"]
    name = primary.split(".")[0].strip().lower()
    if name in MANTINE_SHADES:
        return MANTINE_SHADES[name]
    if _HEX6.match(primary):
        try:
            from depictio.models.models.branding import derive_palette

            shades = derive_palette(primary)
        except Exception:  # noqa: BLE001 - the accent ink is cosmetic
            shades = []
        return (primary.lower(), shades[7] if len(shades) > 7 else primary.lower())
    return MANTINE_SHADES["blue"]


def sans_stack(font_family: str | None = None) -> str:
    """``'Inter Variable', Inter, <the app's UI stack>`` (``plotly.ts`` ``sans``)."""
    return f"'Inter Variable', Inter, {font_family or SYSTEM_SANS}"


def paper_layout(font_family: str | None = None) -> dict[str, Any]:
    """``glassPlotly('light')``: the patch that overrides a figure's own layout."""
    sans = sans_stack(font_family)
    ink, dimmed, faint, line = GRAY[9], GRAY[7], GRAY[6], GRAY[9]
    axis = {
        "showline": False,
        "zerolinecolor": _alpha(line, 0.16),
        "zerolinewidth": 1,
        "gridcolor": _alpha(line, 0.07),
        "gridwidth": 1,
        "ticks": "",
        "tickfont": {"family": sans, "color": faint},
        "title": {"font": {"family": sans, "color": dimmed}, "standoff": 8},
        "automargin": True,
    }
    return {
        "font": {"family": sans, "color": ink},
        "title": {
            "font": {"family": sans, "color": ink},
            "x": 0,
            "xanchor": "left",
            "xref": "paper",
        },
        "paper_bgcolor": "rgba(0, 0, 0, 0)",
        "plot_bgcolor": "rgba(0, 0, 0, 0)",
        "xaxis": {**copy.deepcopy(axis), "showgrid": False},
        "yaxis": {**copy.deepcopy(axis), "showgrid": True},
        "hoverlabel": {
            "bgcolor": WHITE,
            "bordercolor": _alpha(line, 0.12),
            "font": {"family": sans, "color": ink},
            "align": "left",
        },
        "legend": {
            "bgcolor": "rgba(0, 0, 0, 0)",
            "borderwidth": 0,
            "font": {"family": sans, "color": dimmed},
            "title": {"font": {"family": sans, "color": ink}},
            "itemsizing": "constant",
            "itemwidth": 30,
        },
        "coloraxis": {
            "colorbar": {
                "outlinewidth": 0,
                "thickness": 12,
                "ticks": "",
                "tickfont": {"family": sans, "color": faint},
            }
        },
        "modebar": {"bgcolor": "rgba(0, 0, 0, 0)", "color": faint, "activecolor": ink},
        "bargap": 0.3,
    }


# The keys that place a legend (``plotly.ts`` ``LEGEND_PLACEMENT``).
LEGEND_PLACEMENT = ("orientation", "x", "y", "xanchor", "yanchor", "xref", "yref")


def paper_colorway(primary: str | None = None) -> list[str]:
    """Paper's colorway: the instance's primary, then ``GLASS_HUES`` at shade 6."""
    first, _ = resolve_primary(primary)
    hues = [MANTINE_SHADES[h][0] for h in GLASS_HUES]
    return hues if first in hues else [first, *hues]


def paper_defaults(
    primary: str | None = None, layout: dict[str, Any] | None = None
) -> dict[str, Any]:
    """``glassPlotlyDefaults('light', layout)``: what fills a figure's unset keys."""
    out: dict[str, Any] = {
        "margin": {"l": 4, "r": 8, "t": 8, "b": 4, "pad": 0},
        "colorway": paper_colorway(primary),
    }
    own = (layout or {}).get("legend") or {}
    if layout is not None and not any(own.get(k) is not None for k in LEGEND_PLACEMENT):
        # A titled figure keeps its title at the top left, so the legend row
        # goes to the bottom left instead of printing over it.
        top = not has_title(layout)
        out["legend"] = {
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "xref": "container",
            "y": 1 if top else 0,
            "yanchor": "top" if top else "bottom",
            "yref": "container",
        }
    return out


def has_title(layout: dict[str, Any]) -> bool:
    """Whether the figure draws a title of its own (``plotly.ts`` ``hasTitle``)."""
    title = layout.get("title")
    text = title.get("text") if isinstance(title, dict) else title
    return isinstance(text, str) and bool(text.strip())


def _deep_merge(base: Any, patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base) if isinstance(base, dict) else {}
    for k, v in patch.items():
        out[k] = (
            _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        )
    return out


def _axis_keys(layout: dict[str, Any], axis: str) -> list[str]:
    keys = [k for k in layout if k == axis or (k.startswith(axis) and k[len(axis) :].isdigit())]
    return keys if axis in keys else [axis, *keys]


def merge_layout(layout: dict[str, Any], patch: dict[str, Any], *, over: bool) -> dict[str, Any]:
    """``plotlyPatch.ts`` ``mergeLayout``: ``over`` picks who wins a key both set.

    A patch's ``xaxis`` / ``yaxis`` reach every x / y axis of the figure
    (facets included), as in the app.
    """
    out = dict(layout)

    def merge(cur: Any, v: Any) -> Any:
        if not isinstance(v, dict) or not isinstance(cur, dict):
            return v if over or cur is None else cur
        return _deep_merge(cur, v) if over else _deep_merge(v, cur)

    for k, v in patch.items():
        if k in ("xaxis", "yaxis") and isinstance(v, dict):
            for key in _axis_keys(out, k):
                out[key] = merge(out.get(key), v)
        else:
            out[k] = merge(out.get(k), v)
    return out


# What ``use_theme`` turned on for the document.
_STATE: dict[str, Any] = {"name": "classic", "primary": None, "font_family": None}


def active_theme() -> str:
    return str(_STATE["name"])


def apply_theme(fig_dict: dict[str, Any], theme: str | None = None) -> dict[str, Any]:
    """A figure (as Plotly's dict) in the document's look; unchanged under classic.

    ``applyChromePlotly``: Paper's defaults fill what the layout leaves unset,
    then its patch overrides. The input is not modified.
    """
    if (theme or _STATE["name"]) != "paper" or not isinstance(fig_dict, dict):
        return fig_dict
    layout = fig_dict.get("layout") if isinstance(fig_dict.get("layout"), dict) else {}
    layout = dict(layout or {})
    # A figure built in this kernel carries Plotly's whole template; the app
    # never sees one, so it is the template's look that the patch replaces and
    # the figure's own choices that it keeps.
    layout = merge_layout(layout, paper_defaults(_STATE["primary"], layout), over=False)
    layout = merge_layout(layout, paper_layout(_STATE["font_family"]), over=True)
    return {**fig_dict, "layout": layout}


def apply_to_figure(fig: Any) -> Any:
    """A ``plotly.graph_objects.Figure`` in the document's look (a new figure)."""
    if _STATE["name"] != "paper":
        return fig
    import plotly.graph_objects as go

    return go.Figure(apply_theme(fig.to_plotly_json()), skip_invalid=True)


def paper_template(primary: str | None = None, font_family: str | None = None):
    """Paper as a Plotly template, for figures built in the document (``px.*``).

    The template holds both halves (defaults, then the patch over them), so a
    figure built here starts in Paper's look; :func:`apply_theme` still runs
    on display, which is what keeps a server-built figure's own template from
    winning.
    """
    import plotly.graph_objects as go

    layout = merge_layout(paper_defaults(primary), paper_layout(font_family), over=True)
    return go.layout.Template(layout=layout)


_FONT_FACES = (
    # (file, unicode-range) as ``@fontsource-variable/inter`` declares them.
    (
        "inter-latin-wght-normal.woff2",
        "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,"
        "U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
    ),
    (
        "inter-latin-ext-wght-normal.woff2",
        "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,"
        "U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,"
        "U+2C60-2C7F,U+A720-A7FF",
    ),
    (
        "inter-greek-wght-normal.woff2",
        "U+0370-0377,U+037A-037F,U+0384-038A,U+038C,U+038E-03A1,U+03A3-03FF",
    ),
)


@lru_cache(maxsize=1)
def font_face_css() -> str:
    """Inter (the variable font the app self-hosts) as ``@font-face`` data URIs.

    Latin, Latin Extended and Greek: what dashboard labels, sample names and
    units (µ, α, Δ) are written in. Empty when the font files are missing
    from the install, which falls back to the system stack behind it.
    """
    rules = []
    base = resources.files("depictio.notebook") / "assets" / "fonts"
    for name, ranges in _FONT_FACES:
        try:
            data = (base / name).read_bytes()
        except (FileNotFoundError, OSError):
            continue
        uri = "data:font/woff2;base64," + base64.b64encode(data).decode("ascii")
        rules.append(
            "@font-face{font-family:'Inter Variable';font-style:normal;font-display:swap;"
            f"font-weight:100 900;src:url({uri}) format('woff2-variations');"
            f"unicode-range:{ranges};}}"
        )
    return "".join(rules)


def use_theme(
    name: str = "paper", *, primary: str | None = None, font_family: str | None = None
) -> str:
    """Turn the document's look on; returns the markup the report needs for it.

    ``paper``: registers the ``depictio_paper`` Plotly template (and makes it
    the default on top of ``plotly_white``), makes every figure the document
    displays wear Paper (:func:`apply_theme`), and returns a ``<style>`` that
    embeds Inter. ``classic`` leaves Plotly's defaults alone and returns ``""``.
    Print the result from an ``output: asis`` cell.
    """
    if name not in THEMES:
        raise ValueError(f"unknown theme {name!r}; one of {', '.join(THEMES)}")
    _STATE.update(name=name, primary=primary, font_family=font_family)
    if name != "paper":
        return ""
    try:
        import plotly.io as pio

        pio.templates[TEMPLATE_NAME] = paper_template(primary, font_family)
        pio.templates.default = f"plotly_white+{TEMPLATE_NAME}"
    except Exception:  # noqa: BLE001 - figures keep plotly's look; the page still is Paper
        pass
    faces = font_face_css()
    return f"<style>{faces}</style>" if faces else ""
