#!/usr/bin/env python3
"""Render the component-export schema as a hand-drawn SVG (+ PNG).

The diagram summarises what a caller gets from the export endpoint: one component,
one URL, and two formats whose coverage differs on purpose. It is generated rather
than drawn so it can be corrected in a diff when the flow changes.

Drawing primitives come from ``dev/diagrams/sketch.py``, the shared toolkit the
other diagrams in this directory already use. This module used to carry its own
copy, on the grounds that the shared module did not exist yet; it does now.

``embed_font=True`` inlines Virgil from the copy vendored at
``depictio/viewer/src/assets/fonts/Virgil.ttf`` as a base64 ``@font-face``.
Relying on a locally installed Virgil GS means the SVG silently renders in
whatever cursive the fallback list finds — on a machine without the font (CI, a
container) the result does not look hand-drawn at all.

Usage:
    python dev/diagrams/component_export_schema.py --out docs/images/v0.12/react/schema
    # writes <out>_component_export.svg and, unless --no-png, .png
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    ORANGE,
    RED,
    VIOLET,
    YELLOW,
    Box,
    Sketch,
)

app = typer.Typer(add_completion=False)

W, H = 1240, 620


def build() -> str:
    s = Sketch(W, H, seed=11, embed_font=True)

    s.text(46, 52, "One component, two ways out", size=25, anchor="start")
    s.text(
        46,
        78,
        "the same URL returns a Plotly spec, or a page that needs nothing to render",
        size=15,
        colour=DIM,
        anchor="start",
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
        ("?format=json | html", "&theme= &filters=", "existing viewer permission"),
    )

    spec = Box(
        706,
        104,
        232,
        92,
        GREEN,
        "format=json",
        ("Python builds the figure", "{data, layout, config, meta}"),
    )
    consumer = Box(
        986,
        104,
        208,
        92,
        GREEN,
        "your plotly.js",
        ("figure · map · multiqc", "+ 6 advanced-viz kinds"),
    )

    page = Box(
        706,
        408,
        232,
        92,
        VIOLET,
        "format=html",
        ("the real React renderer,", "inlined into one file"),
    )
    iframe = Box(
        986,
        408,
        208,
        92,
        ORANGE,
        "iframe, any site",
        ("9 of 10 types —", "all but jbrowse"),
    )

    for b in (component, endpoint, spec, consumer, page, iframe):
        s.box(b)

    s.arrow(component.right + 8, component.cy, endpoint.x - 10, endpoint.cy)

    # The fork. Sideways out of the endpoint, then up to json / down to html.
    fork_x = endpoint.right + 34
    s.elbow(
        [
            (endpoint.right + 8, endpoint.cy),
            (fork_x, endpoint.cy),
            (fork_x, spec.cy),
            (spec.x - 10, spec.cy),
        ]
    )
    s.elbow(
        [
            (endpoint.right + 8, endpoint.cy),
            (fork_x, endpoint.cy),
            (fork_x, page.cy),
            (page.x - 10, page.cy),
        ]
    )

    s.arrow(spec.right + 8, spec.cy, consumer.x - 10, consumer.cy)
    s.arrow(page.right + 8, page.cy, iframe.x - 10, iframe.cy)

    # Which format a given component supports is a question with an answer.
    # Set below the endpoint box and broken in two so it stays clear of the fork's
    # vertical leg at fork_x — one long line would run straight through it.
    s.text(
        endpoint.x,
        endpoint.bottom + 42,
        "ask …/components first —",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        endpoint.x,
        endpoint.bottom + 63,
        "it lists the formats each one supports",
        size=14,
        colour=DIM,
        anchor="start",
    )

    # The gap in the json format, in the reference's red-for-what-does-not-work.
    s.text(
        706,
        232,
        "12 advanced-viz kinds still build in the browser",
        size=14,
        colour=RED,
        anchor="start",
    )
    s.text(706, 252, "→ 501, with the html_url that does work", size=13, colour=RED, anchor="start")

    # The property that makes the html format worth having.
    s.text(
        706,
        542,
        "zero network calls — opens straight from file://",
        size=14,
        colour=DIM,
        anchor="start",
    )

    s.text(
        W - 46,
        H - 26,
        "off by default — DEPICTIO_FASTAPI_EMBED_ENABLED",
        size=14,
        colour=DIM,
        anchor="end",
    )

    return s.svg()


async def _render_png(svg_path: Path, png_path: Path, chromium_path: str | None) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        launch: dict = {"executable_path": chromium_path} if chromium_path else {}
        browser = await p.chromium.launch(**launch)
        page = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        await page.goto(svg_path.resolve().as_uri())
        await page.wait_for_timeout(400)  # let the handwriting font load
        await page.screenshot(path=str(png_path))
        await browser.close()


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/react/schema"),
        "--out",
        help="Output prefix; '_component_export.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
    chromium_path: str = typer.Option(
        None,
        "--chromium-path",
        help="Chromium binary to rasterise with. Defaults to Playwright's own lookup.",
    ),
) -> None:
    """Write the schema SVG (and PNG) under --out."""
    svg_path = out.with_name(f"{out.name}_component_export.svg")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(build(), encoding="utf-8")
    typer.echo(f"→ {svg_path}")
    if png:
        png_path = svg_path.with_suffix(".png")
        asyncio.run(_render_png(svg_path, png_path, chromium_path))
        typer.echo(f"→ {png_path}")


if __name__ == "__main__":
    app()
