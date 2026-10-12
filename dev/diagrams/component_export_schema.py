#!/usr/bin/env python3
"""Render the component-export schemas as hand-drawn SVGs (+ PNGs).

Two diagrams:

* *component_export* — what a caller gets from the export endpoint: one
  component, one URL, two formats whose coverage differs on purpose, and the
  revision that tells a host when to fetch again.
* *component_export_ui* — the way in from the dashboard: the tile's
  "Export / embed" action, the dialog that picks the mode, and the two pages
  the link ends up on.

Generated rather than drawn so a change in the flow shows up as a diff. The
primitives and glyphs are the shared ones in ``sketch.py`` (Excalidraw's look,
Virgil inlined into the PNG, a fixed seed so re-running is byte-identical).

Usage:
    python dev/diagrams/component_export_schema.py --out docs/images/v0.12/react/schema
    # writes <out>_component_export.{svg,png} and <out>_component_export_ui.{svg,png}
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    BLUE_INK,
    DIM,
    GREEN,
    GREY,
    LIGHT_GREY,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    write,
)

app = typer.Typer(add_completion=False)

W, H = 1240, 640


def _elbow(s: Sketch, points: list[tuple[float, float]]) -> None:
    """A right-angled connector whose last leg carries the arrowhead."""
    s.curve(points[:-1], colour="#1e1e1e")
    (x1, y1), (x2, y2) = points[-2], points[-1]
    s.arrow(x1, y1, x2, y2)


def _scatter(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """A tiny plot: axes and a handful of points, the figure a spec draws."""
    s.line(x, y, x, y + h, amount=0.8, width=1.3, passes=1)
    s.line(x, y + h, x + w, y + h, amount=0.8, width=1.3, passes=1)
    for fx, fy in ((0.15, 0.7), (0.3, 0.45), (0.42, 0.55), (0.55, 0.3), (0.7, 0.35), (0.85, 0.15)):
        s.dot(x + fx * w, y + fy * h, 3.5, fill=BLUE_INK, width=1)


def formats_schema() -> Sketch:
    s = Sketch(W, H, seed=11)
    s.heading(
        46,
        52,
        "One component, two ways out",
        "the same URL returns a Plotly spec, or a page that needs nothing to render",
    )

    component = Box(
        46,
        250,
        250,
        104,
        BLUE,
        "A dashboard component",
        ("figure · table · card · map", "multiqc · advanced viz", "image · text · interactive"),
    )
    endpoint = Box(
        356,
        250,
        286,
        104,
        YELLOW,
        "GET /export/…/{cid}",
        (
            "`?format=json|html`",
            "`&theme= &filters= &controls=`",
            "anonymous: public projects only",
        ),
    )
    spec = Box(
        706,
        104,
        232,
        92,
        GREEN,
        "format=json",
        ("the viewer's own render path", "`{data, layout, config, meta}`"),
    )
    page_box = Box(
        706,
        408,
        232,
        92,
        VIOLET,
        "format=html",
        ("the real React renderer,", "inlined into one file"),
    )
    for b in (component, endpoint, spec, page_box):
        s.box(b)

    # The two consumers, drawn as pages rather than named.
    host = browser(s, 986, 92, 208, 120)
    _scatter(s, host.x + 22, host.y + 42, host.w - 52, host.h - 58)
    s.text(host.cx, host.y - 12, "your page, your plotly.js", size=14, colour=DIM)
    framed = browser(s, 986, 396, 208, 120)
    s.frame(framed.x + 16, framed.y + 38, framed.w - 32, framed.h - 50, dashed=True, fill=VIOLET)
    s.text(framed.cx, framed.y + 84, "`<iframe>`", size=14)
    s.text(framed.cx, framed.y - 12, "any allow-listed site", size=14, colour=DIM)

    s.arrow(component.right + 8, component.cy, endpoint.x - 10, endpoint.cy)
    fork_x = endpoint.right + 34
    _elbow(
        s,
        [
            (endpoint.right + 8, endpoint.cy),
            (fork_x, endpoint.cy),
            (fork_x, spec.cy),
            (spec.x - 10, spec.cy),
        ],
    )
    _elbow(
        s,
        [
            (endpoint.right + 8, endpoint.cy),
            (fork_x, endpoint.cy),
            (fork_x, page_box.cy),
            (page_box.x - 10, page_box.cy),
        ],
    )
    s.arrow(spec.right + 8, spec.cy, host.x - 10, spec.cy)
    s.arrow(page_box.right + 8, page_box.cy, framed.x - 10, page_box.cy)

    # Coverage, under each format: what works, and in red what does not yet.
    s.text(
        706, 228, "figure · map · multiqc · 12 of 35 advanced-viz kinds", size=13, anchor="start"
    )
    s.text(
        706,
        248,
        "the other 23 build in the browser → 501 + html_url",
        size=13,
        colour=RED,
        anchor="start",
    )
    s.text(706, 532, "every type but jbrowse · zero network calls", size=13, anchor="start")
    s.text(
        706,
        552,
        "no page: genome view, contact map, group compare",
        size=13,
        colour=RED,
        anchor="start",
    )

    # Discovery and freshness, below the endpoint, clear of the fork's leg.
    s.text(
        endpoint.x,
        endpoint.bottom + 40,
        "ask …/components first: it lists",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        endpoint.x,
        endpoint.bottom + 60,
        "the formats each one has, and why not",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.frame(endpoint.x, endpoint.bottom + 84, 286, 112, fill=LIGHT_GREY)
    s.text(
        endpoint.x + 14,
        endpoint.bottom + 108,
        "revision = definition + data",
        size=15,
        anchor="start",
        weight="bold",
    )
    s.text(
        endpoint.x + 14,
        endpoint.bottom + 130,
        "version ledger `content_hash`",
        size=13,
        colour=DIM,
        anchor="start",
    )
    s.text(
        endpoint.x + 14,
        endpoint.bottom + 150,
        "+ each collection's aggregation hash",
        size=13,
        colour=DIM,
        anchor="start",
    )
    s.text(
        endpoint.x + 14,
        endpoint.bottom + 176,
        "`ETag` → 304 · `?expect_revision=` → 409",
        size=13,
        anchor="start",
    )

    s.text(
        W - 46,
        H - 22,
        "off by default: DEPICTIO_FASTAPI_EMBED_ENABLED",
        size=14,
        colour=DIM,
        anchor="end",
    )
    return s


def _tile_row(s: Sketch, x: float, y: float, *, export_on: bool) -> float:
    """The hover row of a tile: a few plain icons, then the export one. Returns its x."""
    for i in range(3):
        s.dot(x + i * 20, y, 6, fill=WHITE, colour=GREY)
    ex = x + 3 * 20 + 6
    if export_on:
        s.frame(ex - 11, y - 11, 22, 22, fill=BLUE)
        s.text(ex, y + 5, "`{}`", size=12)
    return ex


def ui_schema() -> Sketch:
    s = Sketch(W, H, seed=23)
    s.heading(
        46,
        52,
        "Export from the tile",
        "the action builds the URL in the mode you pick; the export API serves it",
    )

    # -- the dashboard, a tile hovered ------------------------------------------
    dash = browser(s, 46, 112, 360, 300)
    tiles = (
        (dash.x + 16, dash.y + 44, 150, 110, GREEN),
        (dash.x + 182, dash.y + 44, 162, 110, BLUE),
        (dash.x + 16, dash.y + 170, 328, 112, YELLOW),
    )
    for tx, ty, tw, th, fill in tiles:
        s.frame(tx, ty, tw, th, fill=fill)
    hovered = tiles[1]
    _scatter(s, hovered[0] + 18, hovered[1] + 34, hovered[2] - 40, hovered[3] - 46)
    export_x = _tile_row(s, hovered[0] + 66, hovered[1] + 16, export_on=True)
    s.text(dash.cx, dash.bottom + 26, "every tile, while the API is on", size=14, colour=DIM)
    s.text(dash.cx, dash.bottom + 46, "(`embed_enabled` on /auth/me/optional)", size=13, colour=DIM)

    # -- the dialog -------------------------------------------------------------
    modal = Box(470, 100, 392, 398, WHITE, "")
    s.rect(modal)
    s.text(modal.x + 18, modal.y + 32, "Export / embed", size=18, anchor="start", weight="bold")
    s.text(modal.x + 18, modal.y + 64, "Mode", size=13, anchor="start", colour=DIM)
    json_seg = Box(modal.x + 18, modal.y + 74, 178, 32, GREEN, "")
    html_seg = Box(json_seg.right, modal.y + 74, 178, 32, WHITE, "")
    s.rect(json_seg)
    s.rect(html_seg)
    s.text(json_seg.cx, json_seg.y + 21, "Plotly spec (JSON)", size=13, weight="bold")
    s.text(html_seg.cx, html_seg.y + 21, "Embeddable page (HTML)", size=13)
    s.text(
        modal.x + 18,
        modal.y + 128,
        "a mode the component lacks is greyed, with the reason",
        size=12,
        anchor="start",
        colour=DIM,
    )

    s.text(modal.x + 18, modal.y + 160, "Theme  light | dark", size=13, anchor="start")
    toggle = Box(modal.x + 200, modal.y + 146, 34, 18, BLUE_INK, "")
    s.rect(toggle)
    s.dot(toggle.right - 9, toggle.cy, 6, fill=WHITE)
    s.text(toggle.right + 10, modal.y + 160, "current filters (2)", size=13, anchor="start")

    s.text(
        modal.x + 18,
        modal.y + 198,
        "URL   curl   plotly.js   <iframe>",
        size=13,
        anchor="start",
        weight="bold",
    )
    s.line(
        modal.x + 18, modal.y + 206, modal.x + 48, modal.y + 206, width=2.4, passes=1, amount=0.5
    )
    code = Box(modal.x + 18, modal.y + 218, 356, 88, LIGHT_GREY, "")
    s.rect(code, colour=GREY)
    s.text(code.x + 12, code.y + 26, "`https://…/depictio/api/v1/export/`", size=12, anchor="start")
    s.text(
        code.x + 12, code.y + 46, "`  dashboards/{id}/components/{cid}`", size=12, anchor="start"
    )
    s.text(
        code.x + 12, code.y + 66, "`  ?format=json&theme=light&filters=…`", size=12, anchor="start"
    )
    copy = Box(modal.right - 112, modal.y + 326, 94, 30, BLUE, "")
    opener = Box(modal.right - 214, modal.y + 326, 90, 30, WHITE, "")
    s.rect(copy)
    s.rect(opener)
    s.text(copy.cx, copy.y + 20, "Copy", size=13, weight="bold")
    s.text(opener.cx, opener.y + 20, "Open", size=13)
    s.text(
        modal.x + 18,
        modal.y + 384,
        "private project → `Bearer $DEPICTIO_TOKEN`",
        size=12,
        anchor="start",
        colour=DIM,
    )

    s.arrow(export_x + 14, hovered[1] + 16, modal.x - 10, json_seg.cy)

    # -- where the link ends up ---------------------------------------------------
    host = browser(s, 930, 112, 264, 150)
    _scatter(s, host.x + 26, host.y + 46, host.w - 60, host.h - 64)
    s.text(host.cx, host.bottom + 22, "JSON: drawn by the host's plotly.js", size=14, colour=DIM)
    framed = browser(s, 930, 340, 264, 150)
    s.frame(framed.x + 18, framed.y + 40, framed.w - 36, framed.h - 54, dashed=True, fill=VIOLET)
    _scatter(s, framed.x + 40, framed.y + 54, framed.w - 84, framed.h - 86)
    s.text(framed.cx, framed.bottom + 22, "HTML: an `<iframe>`, or a file", size=14, colour=DIM)
    s.text(framed.cx, framed.bottom + 42, "framing needs the site in", size=13, colour=DIM)
    s.text(
        framed.cx,
        framed.bottom + 60,
        "`DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS`",
        size=12,
        colour=DIM,
    )

    s.arrow(modal.right + 8, json_seg.cy, host.x - 10, host.cy)
    s.arrow(modal.right + 8, code.cy + 40, framed.x - 10, framed.cy)

    # What the action deliberately is not offered on, and what it exports instead.
    s.dot(32, H - 66, 4, fill=GREY, colour=GREY)
    s.text(
        46,
        H - 62,
        "not on a JBrowse tile, nor while a past version is shown: the API serves the live one",
        size=13,
        colour=DIM,
        anchor="start",
    )
    s.dot(32, H - 44, 4, fill=GREY, colour=GREY)
    s.text(
        46,
        H - 40,
        "a highlight or a cross-tab section exports the component it shows, from its own tab",
        size=13,
        colour=DIM,
        anchor="start",
    )
    s.text(
        W - 46,
        H - 40,
        "off by default: DEPICTIO_FASTAPI_EMBED_ENABLED",
        size=13,
        colour=DIM,
        anchor="end",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/react/schema"), "--out", help="Output path stem"
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also render a PNG"),
) -> None:
    write(formats_schema(), out, "component_export", png=png)
    write(ui_schema(), out, "component_export_ui", png=png)


if __name__ == "__main__":
    app()
