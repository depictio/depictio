#!/usr/bin/env python3
"""Annotated screenshots of the genome browser (``jbrowse``) component.

Drives a running Depictio (``depictio local up --examples genome_tracks_examples``
is enough; the nf-core shots also need the three lot1 templates ingested with
``--var TRACKS_URI=…``), captures each scenario with Playwright, then draws
numbered callouts and a legend over the capture in the hand-drawn style of
``sketch.py`` and renders it to PNG. Scenarios that carry a ``context`` shot
also render the whole Depictio page around the browser (``*_context.png``)
before the close-up.

Usage:
    venv/bin/python dev/diagrams/jbrowse_screenshots.py --out docs/images/jbrowse
    venv/bin/python dev/diagrams/jbrowse_screenshots.py --only strandseq_filter
    # behind a TLS-intercepting proxy (CI sandboxes), let Chromium accept it:
    venv/bin/python dev/diagrams/jbrowse_screenshots.py --insecure

Each scenario returns the capture plus the page boxes to call out; the layout
of the legend and the badges is computed from those boxes, so a scenario never
hardcodes a pixel.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sketch import DIM, INK, Box, Sketch  # noqa: E402
from sketch import FONT as SKETCH_FONT  # noqa: E402

# Screenshots carry dense UI text: callouts use a plain sans instead of the
# handwriting font, which reads badly next to it.
FONT = "Inter, 'DejaVu Sans', 'Liberation Sans', Helvetica, Arial, sans-serif"

VIEWPORT = {"width": 1680, "height": 1050}
LEGEND_W = 430
BADGE_R = 17
# Callout colours: one per number, cycling. Strong enough to read over a
# screenshot, the same family as sketch.py's ink.
CALLOUT = ["#c92a2a", "#1971c2", "#2f9e44", "#e8590c", "#7048e8", "#0c8599"]


@dataclass
class Callout:
    box: tuple[float, float, float, float]  # x, y, w, h in capture pixels
    title: str
    text: str


@dataclass
class Shot:
    name: str
    title: str
    subtitle: str
    png: bytes
    callouts: list[Callout] = field(default_factory=list)
    # The same state with Depictio around it, rendered first as ``<name>``.
    context: Shot | None = None


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------


def _chromium_path() -> str | None:
    for candidate in (os.environ.get("CHROMIUM_PATH"), "/opt/pw-browsers/chromium"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


async def _open(page, base: str, dashboard_id: str) -> None:
    await page.goto(f"{base}/dashboard/{dashboard_id}", wait_until="networkidle", timeout=120_000)
    await page.wait_for_timeout(1500)
    skip = page.get_by_text("Skip tour")
    if await skip.count():
        await skip.first.click()
        await page.wait_for_timeout(300)


async def _tile(page, title: str):
    """The grid item whose genome browser carries ``title``, scrolled into view."""
    item = page.locator(".react-grid-item").filter(has_text=title).first
    await item.scroll_into_view_if_needed()
    await page.wait_for_selector('[data-jbrowse-ready="true"]', timeout=90_000)
    return item


async def _settle(page, ms: int = 6000) -> None:
    """Let JBrowse fetch and draw its blocks (it has no 'done' signal)."""
    await page.wait_for_timeout(ms)
    for _ in range(40):  # "Downloading features.." / "Loading" placeholders
        busy = page.locator("text=/Downloading|Loading\\.\\./")
        if not await busy.count():
            break
        await page.wait_for_timeout(1000)
    try:
        await page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:  # noqa: BLE001 - a long-polling socket is fine
        pass
    await page.wait_for_timeout(1500)


async def _box(locator, origin: tuple[float, float]) -> tuple[float, float, float, float]:
    b = await locator.bounding_box()
    if b is None:
        raise RuntimeError("callout target is not visible")
    return b["x"] - origin[0], b["y"] - origin[1], b["width"], b["height"]


async def _union(locator, origin: tuple[float, float]) -> tuple[float, float, float, float]:
    """Bounding box of every element ``locator`` matches."""
    boxes = [
        b for b in [await locator.nth(i).bounding_box() for i in range(await locator.count())] if b
    ]
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["width"] for b in boxes)
    y1 = max(b["y"] + b["height"] for b in boxes)
    return x0 - origin[0], y0 - origin[1], x1 - x0, y1 - y0


async def _boxes_union(locators, origin: tuple[float, float]) -> tuple[float, float, float, float]:
    """Bounding box of the first element of each locator."""
    boxes = [b for b in [await loc.first.bounding_box() for loc in locators] if b]
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["width"] for b in boxes)
    y1 = max(b["y"] + b["height"] for b in boxes)
    return x0 - origin[0], y0 - origin[1], x1 - x0, y1 - y0


async def _clip_capture(page, locators, pad: int = 16) -> tuple[bytes, tuple[float, float]]:
    """Screenshot the union of ``locators`` (plus padding); returns (png, origin)."""
    boxes = [await loc.bounding_box() for loc in locators]
    boxes = [b for b in boxes if b]
    x0 = max(min(b["x"] for b in boxes) - pad, 0)
    y0 = max(min(b["y"] for b in boxes) - pad, 0)
    x1 = max(b["x"] + b["width"] for b in boxes) + pad
    y1 = max(b["y"] + b["height"] for b in boxes) + pad
    png = await page.screenshot(clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})
    return png, (x0, y0)


async def _find_colour(
    page, x: float, y: float, w: float, h: float, colours: list[tuple[int, int, int]], tol: int = 18
):
    """Page coordinates of the middle of the longest horizontal run of ``colours``.

    Features are thin canvas strokes with no DOM node to click, so the capture is
    scanned for the widest bar drawn in one of the expected colours.
    """
    import io

    from PIL import Image

    png = await page.screenshot(clip={"x": x, "y": y, "width": w, "height": h})
    img = Image.open(io.BytesIO(png)).convert("RGB")
    sx, sy = img.width / w, img.height / h

    def hit(px: int, py: int) -> bool:
        r, g, b = img.getpixel((px, py))
        return any(
            abs(r - cr) < tol and abs(g - cg) < tol and abs(b - cb) < tol for cr, cg, cb in colours
        )

    best: tuple[int, int, int] | None = None  # (length, row, start)
    for py in range(img.height):
        run_start, run = 0, 0
        for px in range(img.width + 1):
            if px < img.width and hit(px, py):
                if run == 0:
                    run_start = px
                run += 1
            else:
                if run and (best is None or run > best[0]):
                    best = (run, py, run_start)
                run = 0
    if best is None:
        return None
    length, py, start = best
    return x + (start + length / 2) / sx, y + (py + 0.5) / sy


async def _pick_multiselect(page, placeholder: str, option: str) -> None:
    field_ = page.get_by_placeholder(placeholder).first
    await field_.click()
    await page.get_by_role("option", name=option, exact=True).first.click()
    await page.keyboard.press("Escape")


# The whole tab is captured at once: the viewport is made as tall as the
# dashboard's own scroller, within these bounds.
TAB_VIEW_MIN_H, TAB_VIEW_MAX_H = 1050, 4200

# Per component kind: legend title prefix and default note.
KIND_NOTES = {
    "jbrowse": (
        "Genome browser",
        "A tile of the grid like the others: Depictio title and action bar "
        "(metadata, fullscreen, reset, header / overview / status toggles).",
    ),
    "figure": ("Figure", "Selections on it filter the dashboard, the browser included."),
    "table": (
        "Table",
        "Row selection filters the dashboard; the browser opens the matching tracks.",
    ),
    "cards": ("Cards", "Aggregates of what the filters keep, recomputed with them."),
}


async def _filters_box(page, origin: tuple[float, float]) -> tuple[float, float, float, float]:
    """The left filter panel, down to its last filter card (the panel itself is full height)."""
    box = await page.evaluate(
        """() => {
          const title = [...document.querySelectorAll('h5')].find(e => e.textContent.trim() === 'Filters');
          const paper = title && title.closest('.mantine-Paper-root');
          if (!paper) return null;
          const r = paper.getBoundingClientRect();
          let bottom = r.top;
          paper.querySelectorAll('*').forEach(el => {
            const b = el.getBoundingClientRect();
            if (b.height > 0 && b.height < r.height * 0.6 && b.bottom <= r.bottom)
              bottom = Math.max(bottom, b.bottom);
          });
          return [r.left, r.top, r.width, bottom - r.top + 8];
        }"""
    )
    if not box:
        raise RuntimeError("filter panel not found")
    return box[0] - origin[0], box[1] - origin[1], box[2], box[3]


async def _grid_tiles(page) -> list[dict]:
    """Every tile of the tab with its kind, title and page box, in reading order."""
    return await page.evaluate(
        """() => [...document.querySelectorAll('.react-grid-item')].map(el => {
          const r = el.getBoundingClientRect();
          const kind = el.querySelector('[data-testid="jbrowse-component"]') ? 'jbrowse'
            : el.querySelector('.ag-root-wrapper, .ag-root') ? 'table'
            : el.querySelector('.js-plotly-plot, canvas, svg.main-svg') ? 'figure'
            : /\\d/.test(el.innerText) && r.height < 320 && el.innerText.length < 200 ? 'card'
            : 'text';
          const title = (el.innerText || '').split('\\n').map(t => t.trim()).find(Boolean) || '';
          return {kind, title, x: r.left, y: r.top, w: r.width, h: r.height};
        }).filter(t => t.w > 0 && t.h > 0).sort((a, b) => a.y - b.y || a.x - b.x)"""
    )


async def _context(
    page,
    name: str,
    title: str,
    subtitle: str,
    tile,
    notes: dict[str, str] | None = None,
    extra: list[tuple[object, str, str]] | None = None,
) -> Shot:
    """The whole dashboard tab around the browser, before the close-up crop.

    The dashboard scrolls inside a fixed header and filter panel, so the
    viewport is made as tall as that scroller: every component of the tab is in
    the capture, each called out by kind (``notes`` overrides the text of the
    tile whose title it names). The viewport is restored for the crop that
    follows.
    """
    height = await page.evaluate(
        "() => { const c = document.querySelector('[data-testid=dashboard-content]');"
        " return c ? c.scrollHeight + c.getBoundingClientRect().top + 16 : 0; }"
    )
    height = int(min(max(height, TAB_VIEW_MIN_H), TAB_VIEW_MAX_H))
    await page.set_viewport_size({"width": VIEWPORT["width"], "height": height})
    await page.evaluate(
        "() => { const c = document.querySelector('[data-testid=dashboard-content]');"
        " if (c) c.scrollTop = 0; }"
    )
    await page.mouse.move(2, VIEWPORT["height"] - 2)  # no hover tooltip in the shot
    await _settle(page, 6000)
    png = await page.screenshot()
    origin = (0.0, 0.0)
    callouts = [
        Callout(
            await _box(page.locator(".mantine-AppShell-header").first, origin),
            "Depictio dashboard",
            "Project / tab title, Analysis, Edit and Settings: the usual viewer.",
        ),
        Callout(
            await _box(page.locator("[role=tablist]").first, origin),
            "Dashboard tabs",
            "The genome browser is one more component of a regular tab.",
        ),
        Callout(
            await _filters_box(page, origin),
            "Dashboard filters",
            "Left-panel filters narrow every component of the tab, the browser included.",
        ),
    ]
    for loc, head, body in extra or []:
        if await loc.count():  # type: ignore[attr-defined]
            callouts.append(Callout(await _box(loc.first, origin), head, body))  # type: ignore[attr-defined]
    tiles = await _grid_tiles(page)
    cards = [t for t in tiles if t["kind"] == "card"]
    grid: list[tuple[float, float, Callout]] = []
    if cards:
        x0 = min(t["x"] for t in cards)
        y0 = min(t["y"] for t in cards)
        x1 = max(t["x"] + t["w"] for t in cards)
        y1 = max(t["y"] + t["h"] for t in cards)
        head, body = KIND_NOTES["cards"]
        names = ", ".join(t["title"] for t in cards if t["title"])
        grid.append((y0, x0, Callout((x0, y0, x1 - x0, y1 - y0), head, f"{body} ({names})")))
    for t in tiles:
        if t["kind"] not in ("jbrowse", "figure", "table"):
            continue
        prefix, body = KIND_NOTES[t["kind"]]
        note = (notes or {}).get(t["title"], body)
        # The tile's own title heads the entry; the kind leads the note.
        head = t["title"] or prefix
        body = note if head == prefix else f"{prefix}. {note}"
        grid.append((t["y"], t["x"], Callout((t["x"], t["y"], t["w"], t["h"]), head, body)))
    callouts += [c for _, _, c in sorted(grid, key=lambda g: (g[0], g[1]))]
    await page.set_viewport_size(VIEWPORT)
    await tile.scroll_into_view_if_needed()
    await _settle(page, 3000)
    return Shot(name, title, subtitle, png, callouts)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

STRANDSEQ = "946b0f3c1e4a2d7f8e5bca00"
STRANDSEQ_NOTES = {
    "Cell quality": "Lasso cells here to open their SV tracks.",
    "Cells": "Pick cells to open their SV tracks.",
    "SV calls": "Pick an SV call: the browser opens its cell and jumps to it (locus_from).",
}
# Tile titles of the nf-core Genome tracks tabs -> what they do to the browser.
NFCORE_NOTES = {
    "SEACR signal along the genome": "Click a region: its sample's tracks open on it.",
    "SEACR regions": "Pick a region: its sample's tracks open on it (locus_from).",
    "Peak significance along the genome": "Click a peak: its sample's tracks open on it.",
    "MACS2 peak calls": "Pick a peak: its sample's tracks open on it (locus_from).",
    "Library depth": "Lasso samples to open their coverage tracks.",
    "Sample PCA": "Lasso samples to open their coverage tracks.",
    "Samples": "Pick samples to open their tracks.",
    "ChIP samples": "Pick samples to open their tracks.",
}
SARSCOV2 = "946b0f3c1e4a2d7f8e5bca20"


async def strandseq_overview(page, base: str) -> Shot:
    await _open(page, base, STRANDSEQ)
    tile = await _tile(page, "SV calls per cell")
    await _settle(page)
    scatter = page.locator(".react-grid-item").filter(has_text="Cell quality").first
    context = await _context(
        page,
        "strandseq_context",
        "Strand-seq tab in Depictio",
        "Cards, a scatter, the genome browser and two tables on one tab, driven by the same filters",
        tile,
        notes=STRANDSEQ_NOTES,
    )
    await tile.hover()
    await page.wait_for_timeout(500)
    png, origin = await _clip_capture(page, [scatter, tile])
    status = tile.locator('[data-testid="jbrowse-status"]')
    toggles = tile.locator('[data-testid^="jbrowse-toggle-"]')
    first_track = tile.locator("text=SV calls").nth(1)
    return Shot(
        "strandseq_overview",
        "Strand-seq: cells next to their SV calls",
        "One genome-browser track per single cell, read by range through the API",
        png,
        [
            Callout(
                await _box(scatter, origin),
                "Cell quality scatter",
                "ASHLEYS probability against good reads. Lasso cells to open their tracks.",
            ),
            Callout(
                await _box(first_track, origin),
                "One track per cell",
                "MosaiCatcher SV calls (bgzipped BED + tabix, uploaded at ingestion), coloured "
                "by call class via the manifest's colour column.",
            ),
            Callout(
                await _union(toggles, origin),
                "Header / overview / status toggles",
                "Hide JBrowse's navigation header, the overview ruler or the status bar; the "
                "chrome also offers fullscreen and reset.",
            ),
            Callout(
                await _box(status, origin),
                "Status bar",
                "Tracks shown, tracks matching the dashboard filters, selection count.",
            ),
        ],
        context=context,
    )


async def strandseq_filter(page, base: str) -> Shot:
    await _open(page, base, STRANDSEQ)
    await _pick_multiselect(page, "Select sample…", "HG002x01")
    tile = await _tile(page, "SV calls per cell")
    await _settle(page, 8000)
    sample_filter = page.get_by_text("Sample", exact=True).first.locator("xpath=../..")
    context = await _context(
        page,
        "strandseq_filter_context",
        "A dashboard filter drives the genome browser",
        "Sample = HG002x01 in the left panel: every component narrows, the browser included",
        tile,
        notes=STRANDSEQ_NOTES,
        extra=[(sample_filter, "Sample = HG002x01", "The active filter, in the left panel.")],
    )
    png, origin = await _clip_capture(page, [sample_filter, tile], pad=20)
    status = tile.locator('[data-testid="jbrowse-status"]')
    return Shot(
        "strandseq_filter",
        "Dashboard filter → genome tracks",
        "Picking a sample in the left panel opens the SV tracks of its cells only",
        png,
        [
            Callout(
                await _box(sample_filter, origin),
                "Sample = HG002x01",
                "A regular interactive filter on the cells table.",
            ),
            Callout(
                await _box(tile.locator("text=HG002x01").first, origin),
                "Tracks follow",
                "The cells → tracks link narrows the manifest; the view swaps tracks in place "
                "(no reload, locus kept).",
            ),
            Callout(
                await _box(status, origin),
                "Matches",
                "How many tracks match the filters, and how many are shown (max_tracks).",
            ),
        ],
        context=context,
    )


async def strandseq_click(page, base: str) -> Shot:
    await _open(page, base, STRANDSEQ)
    tile = await _tile(page, "SV calls per cell")
    await _settle(page)
    # Click the 8p23.1 inversion in the first cell's track: find the call's
    # pixels (MosaiCatcher colours inversions #DDDD77 / #777711) and click them.
    track_label = tile.locator("text=SV calls").nth(1)
    tb = await track_label.bounding_box()
    assert tb
    point = await _find_colour(
        page,
        tb["x"],
        tb["y"] + tb["height"],
        700,
        60,
        [(221, 221, 119), (119, 119, 17), (170, 170, 68)],
    )
    assert point, "no SV call drawn under the first track label"
    await page.mouse.click(*point)
    await page.wait_for_timeout(1500)
    click_y = point[1]
    rb = {"x": point[0] - 30, "width": 60}
    await _settle(page, 5000)
    scatter = page.locator(".react-grid-item").filter(has_text="Cell quality").first
    png, origin = await _clip_capture(page, [scatter, tile], pad=20)
    return Shot(
        "strandseq_click",
        "Genome tracks → dashboard filter",
        "Clicking an SV call filters every component on its cell",
        png,
        [
            Callout(
                (rb["x"] - origin[0], click_y - origin[1] - 12, rb["width"], 24),
                "Click an SV call",
                "The feature's track maps back to its cell (the manifest's selection column).",
            ),
            Callout(
                await _box(scatter, origin),
                "Everything follows",
                "A jbrowse_selection filter on `cell` reaches the cells table through the "
                "tracks → cells link: the scatter (and cards, tables) now show that cell.",
            ),
            Callout(
                await _box(tile.locator('[data-testid="jbrowse-status"]'), origin),
                "Selection",
                "Click again to toggle; the chrome's reset icon clears it.",
            ),
        ],
    )


async def strandseq_compact(page, base: str) -> Shot:
    await _open(page, base, STRANDSEQ)
    tile = await _tile(page, "SV calls per cell")
    await _settle(page)
    await tile.hover()
    for key in ("header", "status"):
        await tile.locator(f'[data-testid="jbrowse-toggle-{key}"]').click()
        await page.wait_for_timeout(400)
    await tile.hover()
    fullscreen = tile.locator('[aria-label*="ullscreen"], [title*="ullscreen"]').first
    await fullscreen.click()
    await _settle(page, 4000)
    png = await page.screenshot()
    fs_toggles = page.locator('[data-testid^="jbrowse-toggle-"]').first
    b = await fs_toggles.bounding_box()
    callouts = [
        Callout(
            (0, 0, VIEWPORT["width"], 60),
            "No header, no status bar",
            "Both hidden with the chrome toggles: the tracks get the whole tile.",
        )
    ]
    if b:
        callouts.append(
            Callout(
                (b["x"], b["y"], b["width"] * 4, b["height"]),
                "Toggles stay reachable",
                "They live in Depictio's chrome, which fullscreen keeps.",
            )
        )
    return Shot(
        "strandseq_compact",
        "Compact + fullscreen",
        "Navigation header and status bar hidden, tile in native fullscreen",
        png,
        callouts,
    )


async def sarscov2_variant(page, base: str) -> Shot:
    await _open(page, base, SARSCOV2)
    tile = await _tile(page, "Variants and reads")
    await _settle(page)
    table = (
        page.locator(".react-grid-item")
        .filter(has=page.get_by_text("Variant calls", exact=True))
        .first
    )
    await table.scroll_into_view_if_needed()
    await page.wait_for_timeout(3000)  # the table fetches once in view
    # The spike's D614G (A23403G) when it is on the first page, else the first row.
    row = table.locator(".ag-row", has_text="23403").first
    if not await row.count():
        row = table.locator(".ag-row").first
    await row.locator(".ag-checkbox-input-wrapper, .ag-selection-checkbox").first.click()
    await page.wait_for_timeout(800)
    await tile.scroll_into_view_if_needed()
    await _settle(page, 9000)
    context = await _context(
        page,
        "sarscov2_context",
        "SARS-CoV-2 tab in Depictio",
        "A variant picked in the table: every component narrows, the browser jumps to it",
        tile,
        notes={
            "Coverage against variant load": "Lasso samples to open their tracks.",
            "Variant calls": "The picked row filters the dashboard; the browser jumps to "
            "the variant (locus_from).",
        },
    )
    png, origin = await _clip_capture(page, [tile])
    return Shot(
        "sarscov2_variant",
        "SARS-CoV-2: variants and reads, read in place",
        "VCF + BAM from the public nf-core megatest bucket, on a custom assembly",
        png,
        [
            Callout(
                await _box(tile.locator("input").first, origin),
                "Locus from a table row",
                "Selecting a variant filters the variants table to one row; `locus_from` "
                "jumps the view to it.",
            ),
            Callout(
                await _box(tile.locator("text=iVar variants").first, origin),
                "VCF + BAM read in place",
                "s3://nf-core-awsmegatests via the API range proxy (bucket allow-listed), "
                "signed URLs per file.",
            ),
            Callout(
                await _box(tile.locator("text=NCBI genes").first, origin),
                "Custom assembly + extra track",
                "UCSC wuhCor1 2bit aliased to MN908947.3; a gene bigBed added through "
                "config_overrides.extra_tracks.",
            ),
        ],
        context=context,
    )


async def nfcore_tab(
    page,
    base: str,
    dashboard_id: str,
    title: str,
    name: str,
    heading: str,
    subtitle: str,
    texts: list[tuple[str, str, str]],
    pick: tuple[str, str] | None = None,
    locus: str | None = None,
) -> Shot:
    await _open(page, base, dashboard_id)  # the template's Genome tracks tab
    if pick:
        await _pick_multiselect(page, *pick)
    tile = await _tile(page, title)
    if locus:
        search = tile.locator("input").first
        await search.fill(locus)
        await search.press("Enter")
    await _settle(page, 12000)
    context = await _context(
        page,
        f"{name}_context",
        f"{heading.split(':')[0]}: the Genome tracks tab",
        "Cards, the genome browser, figures and tables on one template tab, driven by the same filters",
        tile,
        notes=NFCORE_NOTES,
    )
    # Tight: the template puts a text block right above the tile.
    png, origin = await _clip_capture(page, [tile], pad=4)
    callouts = []
    for selector, head, body in texts:
        loc = tile.locator(selector).first
        if await loc.count():
            callouts.append(Callout(await _box(loc, origin), head, body))
    return Shot(name, heading, subtitle, png, callouts, context=context)


async def builder_jbrowse(page, base: str) -> Shot:
    await page.set_viewport_size({"width": 1680, "height": 2300})
    await page.goto(
        f"{base}/dashboard-edit/{SARSCOV2}/component/edit/cov-browser",
        wait_until="networkidle",
        timeout=120_000,
    )
    await page.wait_for_timeout(2000)
    skip = page.get_by_text("Skip tour")
    if await skip.count():
        await skip.first.click()
    await page.get_by_text("Custom configuration", exact=True).first.click()
    await page.get_by_text("Cross-filtering", exact=True).first.click()
    await page.wait_for_timeout(1200)
    form = page.get_by_text("Genome Browser Configuration", exact=True).first
    summary = page.get_by_text("Draft summary", exact=True).first
    overrides = page.get_by_text("Config overrides", exact=True).first
    ucsc_picker = page.locator('[data-testid="jbrowse-builder-ucsc-tracks"]').first
    loading = page.get_by_text("Data loading", exact=True).first
    # The two columns side by side (form + summary), down to the last section.
    fb = await form.bounding_box()
    bottoms = [
        b["y"] + b["height"]
        for b in [
            await overrides.locator("xpath=../..").bounding_box(),
            await page.locator(
                '[data-testid="jbrowse-builder-fetch-size-limit"]'
            ).first.bounding_box(),
        ]
        if b
    ]
    assert fb and bottoms
    x0, y0 = fb["x"] - 24, fb["y"] - 24
    clip = {
        "x": x0,
        "y": y0,
        "width": 1680 - 2 * x0,
        "height": max(bottoms) + 24 - y0,
    }
    png, origin = await page.screenshot(clip=clip), (x0, y0)
    assembly = page.get_by_text("Assembly", exact=True).first.locator("xpath=..")
    display = page.get_by_text("Display", exact=True).first.locator("xpath=..")
    cross = page.get_by_text("Cross-filtering", exact=True).first.locator("xpath=../../..")
    preset = page.get_by_text("Preset", exact=True).first.locator("xpath=..")
    return Shot(
        "builder_jbrowse",
        "Genome browser in the component builder",
        "Assembly, locus, tracks, toggles, cross-filtering and raw JBrowse config, no YAML needed",
        png,
        [
            Callout(
                await _box(assembly, origin),
                "Assembly",
                "A built-in preset (hg38, hg19, T2T, mm10, mm39, yeast, fly, worm, zebrafish, "
                "TAIR10, SARS-CoV-2) or the collection's own custom assembly.",
            ),
            Callout(
                await _box(display, origin),
                "Header / overview toggles",
                "The defaults of the chrome toggles; viewers can still flip them.",
            ),
            Callout(
                await _boxes_union(
                    [page.get_by_text("UCSC tracks", exact=True), ucsc_picker], origin
                ),
                "UCSC tracks",
                "Searchable picker over the assembly's UCSC catalogue (resolved through the "
                "UCSC API); the picked tracks open by default.",
            ),
            Callout(
                await _box(cross, origin),
                "Cross-filtering",
                "Selection column and mode: clicked feature, or every open track.",
            ),
            Callout(
                await _box(preset, origin),
                "Presets + raw overrides",
                "Named presets (built-in or the collection's) and a JSON editor deep-merged "
                "last: formats, tracks, view, configuration, extra_tracks.",
            ),
            Callout(
                await _boxes_union(
                    [loading, page.locator('[data-testid="jbrowse-builder-fetch-size-limit"]')],
                    origin,
                ),
                "Data loading",
                "Force load by default, and the per-track fetch size limit (MB).",
            ),
            Callout(
                await _box(summary.locator("xpath=../.."), origin),
                "Live summary",
                "Which tracks would show under the current filters; 'Saved view' renders "
                "the real browser.",
            ),
        ],
    )


async def _sars_browser(page, base: str, locus: str | None = None):
    """The SARS-CoV-2 tab's browser, settled, optionally moved to ``locus``."""
    await _open(page, base, SARSCOV2)
    tile = await _tile(page, "Variants and reads")
    await _settle(page)
    if locus:
        search = tile.locator("input").first
        await search.fill(locus)
        await search.press("Enter")
        await _settle(page, 8000)
    return tile


async def track_menu(page, base: str) -> Shot:
    tile = await _sars_browser(page, base)
    await tile.hover()
    await tile.locator('[data-testid="jbrowse-toggle-tracks"]').click()
    menu = page.locator('[data-testid="jbrowse-track-menu"]')
    await menu.wait_for(state="visible")
    await page.locator('[data-testid="jbrowse-track-search"]').fill("SAMPLE_41")
    await page.wait_for_timeout(600)
    await menu.locator('[data-track-id="SAMPLE_41.variants"]').click()
    await _settle(page, 7000)
    # Keep the tile's action bar (it shows on hover) in the shot.
    await tile.locator('[data-testid="jbrowse-toggle-tracks"]').hover()
    await page.wait_for_timeout(400)
    png, origin = await _clip_capture(page, [tile, menu], pad=12)
    buttons = page.locator(
        '[data-testid="jbrowse-tracks-show-all"], [data-testid="jbrowse-tracks-hide-all"], '
        '[data-testid="jbrowse-tracks-reset"]'
    )
    return Shot(
        "track_menu",
        "Tracks menu: open tracks one by one",
        "Every track matching the filters is offered (here 93), only max_tracks open",
        png,
        [
            Callout(
                await _box(tile.locator('[data-testid="jbrowse-toggle-tracks"]'), origin),
                "Tracks button",
                "In the tile's action bar, next to the header / overview / status toggles.",
            ),
            Callout(
                await _box(page.locator('[data-testid="jbrowse-track-menu-count"]'), origin),
                "Open / offered",
                "Tracks open in the view against every track the view carries.",
            ),
            Callout(
                await _box(page.locator('[data-testid="jbrowse-track-search"]'), origin),
                "Search",
                "Matches name, sample, category and format.",
            ),
            Callout(
                await _union(buttons, origin),
                "Show all / Hide all / Back to filters",
                "Show all is capped at 60 tracks; Back to filters restores the tracks the "
                "dashboard filters pick.",
            ),
            Callout(
                await _box(menu.locator('[data-track-id="SAMPLE_41.variants"]'), origin),
                "Ticked here",
                "Grouped by the manifest's category column; ticking a box opens the track.",
            ),
            Callout(
                await _box(tile.get_by_text("SAMPLE_41 iVar variants").first, origin),
                "Opened in the view",
                "Manual choices hold until the filters change.",
            ),
        ],
    )


FORCE_LOCUS = "NC_045512v2:1-29,903"


async def _hover_toolbar(tile) -> None:
    """Show the tile's action bar without a feature tooltip under the mouse."""
    await tile.hover(position={"x": 8, "y": 8})
    await tile.page.wait_for_timeout(400)


async def force_load_before(page, base: str) -> Shot:
    tile = await _sars_browser(page, base, FORCE_LOCUS)
    await _hover_toolbar(tile)
    png, origin = await _clip_capture(page, [tile])
    return Shot(
        "force_load_before",
        "Force load: JBrowse's download limit",
        "The whole genome of SARS-CoV-2 in view: the BAMs exceed the 1 MB per-track limit",
        png,
        [
            Callout(
                await _box(tile.get_by_text("Requested too much data").first, origin),
                "Limit reached",
                "JBrowse stops at fetchSizeLimit (1 MB by default) and asks to zoom in; "
                "fetch_size_limit_mb sets it per component.",
            ),
            Callout(
                await _box(tile.get_by_role("button", name="Force load", exact=True).first, origin),
                "Per-track button",
                "JBrowse's own force load, one track at a time.",
            ),
            Callout(
                await _box(tile.locator('[data-testid="jbrowse-toggle-forceload"]'), origin),
                "Force load toggle",
                "Lifts the limits of every open track at once (next shot).",
            ),
        ],
    )


async def force_load_after(page, base: str) -> Shot:
    tile = await _sars_browser(page, base, FORCE_LOCUS)
    await tile.hover()
    await tile.locator('[data-testid="jbrowse-toggle-forceload"]').click()
    await _settle(page, 20000)
    await _hover_toolbar(tile)
    png, origin = await _clip_capture(page, [tile])
    return Shot(
        "force_load_after",
        "Force load: every track, whatever its size",
        "The same view with the toggle on: the reads load, and tracks opened or zoomed out later "
        "follow",
        png,
        [
            Callout(
                await _box(tile.locator('[data-testid="jbrowse-toggle-forceload"]'), origin),
                "Force load on",
                "Remembered per viewer; force_load: true makes it the component's default.",
            ),
            Callout(
                await _box(tile.get_by_text("SAMPLE_11 primer-trimmed reads").first, origin),
                "Reads loaded",
                "65 MB of alignments read by range through the proxy.",
            ),
            Callout(
                await _box(tile.locator('[data-testid="jbrowse-status"]'), origin),
                "Status",
                "The status bar says force load is on.",
            ),
        ],
    )


async def ucsc_tracks(page, base: str) -> Shot:
    tile = await _sars_browser(page, base, "NC_045512v2:21,400-25,500")
    await _hover_toolbar(tile)
    png, origin = await _clip_capture(page, [tile])
    return Shot(
        "ucsc_tracks",
        "UCSC tracks opened by default",
        "ucsc_tracks: [artic, nextstrainClade], resolved through the UCSC API for wuhCor1",
        png,
        [
            Callout(
                await _box(tile.get_by_text("ARTIC Primers V3").first, origin),
                "ARTIC primers (UCSC)",
                "The amplicon scheme the megatest was sequenced with, from UCSC's catalogue.",
            ),
            Callout(
                await _box(tile.get_by_text("Nextstrain Clades").first, origin),
                "Nextstrain clades (UCSC)",
                "Any bigBed / bigWig / VCF track of the genome's UCSC catalogue, by name.",
            ),
            Callout(
                await _box(tile.get_by_text("SAMPLE_11 iVar variants").first, origin),
                "The collection's tracks",
                "Next to them, driven by the dashboard filters as before.",
            ),
        ],
    )


SCENARIOS: dict[str, Callable[..., Awaitable[Shot]]] = {
    "builder_jbrowse": builder_jbrowse,
    "strandseq_overview": strandseq_overview,
    "strandseq_filter": strandseq_filter,
    "strandseq_click": strandseq_click,
    "strandseq_compact": strandseq_compact,
    "sarscov2_variant": sarscov2_variant,
    "track_menu": track_menu,
    "force_load_before": force_load_before,
    "force_load_after": force_load_after,
    "ucsc_tracks": ucsc_tracks,
}


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------


def _wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        lines.append(line)
    return lines


def annotate(shot: Shot, png_size: tuple[int, int]) -> Sketch:
    """The capture on the left, numbered callouts over it, the legend on the right."""
    w, h = png_size
    top = 78
    legend_lines = sum(2 + len(_wrap(c.text, 44)) for c in shot.callouts)
    height = max(h + top + 24, top + 40 + legend_lines * 21 + 40)
    sk = Sketch(w + LEGEND_W + 48, height)
    sk.heading(24, 36, shot.title, shot.subtitle)
    data = base64.b64encode(shot.png).decode()
    sk._parts.append(
        f'<image x="24" y="{top}" width="{w}" height="{h}" href="data:image/png;base64,{data}"/>'
    )
    sk._parts.append(
        f'<rect x="24" y="{top}" width="{w}" height="{h}" fill="none" stroke="#dee2e6"/>'
    )
    lx = w + 48 + 16
    ly = top + 16
    for i, c in enumerate(shot.callouts, start=1):
        colour = CALLOUT[(i - 1) % len(CALLOUT)]
        x, y, bw, bh = c.box
        box = Box(24 + x - 4, top + y - 4, bw + 8, bh + 8, fill="none", title="")
        sk.rect(box, colour=colour)
        bx, by = box.x, box.y
        sk._parts.append(
            f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="{BADGE_R}" fill="{colour}" '
            f'stroke="#ffffff" stroke-width="2.5"/>'
        )
        sk._parts.append(
            f'<text x="{bx:.1f}" y="{by + 6:.1f}" font-family="{FONT}" font-size="18" '
            f'font-weight="bold" fill="#ffffff" text-anchor="middle">{i}</text>'
        )
        # legend entry
        sk._parts.append(
            f'<circle cx="{lx + BADGE_R:.1f}" cy="{ly + 2:.1f}" r="{BADGE_R - 3}" fill="{colour}"/>'
        )
        sk._parts.append(
            f'<text x="{lx + BADGE_R:.1f}" y="{ly + 8:.1f}" font-family="{FONT}" font-size="16" '
            f'font-weight="bold" fill="#ffffff" text-anchor="middle">{i}</text>'
        )
        sk.text(
            lx + 2 * BADGE_R + 8,
            ly + 8,
            escape(c.title),
            size=18,
            anchor="start",
            weight="bold",
            colour=INK,
        )
        ly += 30
        for line in _wrap(c.text, 44):
            sk.text(lx + 2 * BADGE_R + 8, ly, line, size=14.5, anchor="start", colour=DIM)
            ly += 21
        ly += 18
    return sk


async def _render(svg_path: Path, png_path: Path, width: float, height: float) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=_chromium_path())
        page = await browser.new_page(
            viewport={"width": int(width), "height": int(height)}, device_scale_factor=1
        )
        await page.goto(svg_path.resolve().as_uri())
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(png_path))
        await browser.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(
    base: str,
    out: Path,
    only: set[str] | None,
    insecure: bool,
    extra: dict[str, Callable[..., Awaitable[Shot]]],
) -> None:
    from PIL import Image
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    scenarios = {**SCENARIOS, **extra}
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=_chromium_path())
        for name, fn in scenarios.items():
            if only and name not in only:
                continue
            ctx = await browser.new_context(viewport=VIEWPORT, ignore_https_errors=insecure)
            page = await ctx.new_page()
            try:
                shot = await fn(page, base)
            except Exception as exc:  # noqa: BLE001 - report and go on with the rest
                print(f"✗ {name}: {exc}")
                await page.screenshot(path=str(out / f"_failed_{name}.png"))
                await ctx.close()
                continue
            await ctx.close()
            for one in [shot.context, shot] if shot.context else [shot]:
                raw = out / f"_raw_{one.name}.png"
                raw.write_bytes(one.png)
                size = Image.open(raw).size
                sk = annotate(one, size)
                svg = out / f"{one.name}.svg"
                svg.write_text(sk.svg().replace(SKETCH_FONT, FONT), encoding="utf-8")
                await _render(svg, out / f"{one.name}.png", sk.width, sk.height)
                svg.unlink()
                raw.unlink()
                print(f"✓ {out / f'{one.name}.png'}")
        await browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8058")
    ap.add_argument("--out", type=Path, default=Path("docs/images/jbrowse"))
    ap.add_argument("--only", action="append", help="scenario name (repeatable)")
    ap.add_argument("--insecure", action="store_true", help="accept TLS-intercepting proxies")
    ap.add_argument(
        "--nfcore",
        action="append",
        default=[],
        metavar="NAME=DASHBOARD_ID",
        help="nf-core template dashboards to capture (cutandrun=…, chipseq=…, rnaseq=…)",
    )
    args = ap.parse_args()

    extra: dict[str, Callable[..., Awaitable[Shot]]] = {}
    for spec in args.nfcore:
        name, _, dash = spec.partition("=")
        extra[f"nfcore_{name}"] = _nfcore_scenario(name, dash)
        if name == "cutandrun":
            extra["nfcore_cutandrun_peak"] = _cutandrun_peak_scenario(dash)
    asyncio.run(
        run(args.base_url, args.out, set(args.only) if args.only else None, args.insecure, extra)
    )


NFCORE = {
    "cutandrun": (
        "Genome browser",
        "nf-core/cutandrun: H3K4me3 at the ACTB promoter",
        "Target = h3k4me3 in the left panel; bigWig, SEACR / MACS2 peaks and BAM of the "
        "megatest, read in place (TRACKS_URI)",
        [
            (
                "text=h3k4me3_R1 signal",
                "Signal per sample",
                "bigWig coverage, coloured per target like the run's own IGV session.",
            ),
            (
                "text=h3k4me3_R1 peaks (seacr)",
                "Peak calls",
                "SEACR stringent and MACS2 narrowPeak calls of the same samples.",
            ),
            (
                "text=h3k4me3_R1 alignments",
                "Alignments",
                "The deduplicated BAM, range-read through the API proxy.",
            ),
            (
                "text=ENCODE3 cCREs",
                "UCSC track",
                "ENCODE candidate cis-regulatory elements: ucsc_tracks: [encodeCcreCombined].",
            ),
            (
                '[data-testid="jbrowse-status"]',
                "Driven by the target filter",
                "The persistent left-panel filter (samples → tracks link) picks the tracks.",
            ),
        ],
        ("Select target…", "h3k4me3"),
        "chr7:5,525,000-5,545,000",
    ),
    "chipseq": (
        "Genome browser",
        "nf-core/chipseq: FOXA1 at GREB1",
        "bigWig + narrowPeak of the hg19 megatest, read in place from S3",
        [
            ("text=FOXA1_IP_E2_R1", "IP signal", "FOXA1 bigWigs, E2 vs vehicle."),
            ("text=peaks", "MACS2 peaks", "narrowPeak calls of the same samples."),
            (
                "text=JASPAR 2022 TFBS",
                "UCSC track, too dense here",
                "JASPAR motifs (ucsc_tracks: [jaspar2022]): at 80 kb JBrowse asks to zoom in or "
                "force load; the Force load toggle lifts it for every track.",
            ),
            (
                '[data-testid="jbrowse-status"]',
                "Filtered by design",
                "Samples picked in the design table open their tracks.",
            ),
        ],
    ),
    "rnaseq": (
        "Genome browser",
        "nf-core/rnaseq: stranded coverage at the HBG locus",
        "Forward / reverse bigWigs of the GRCh37 megatest on the hg19 preset (aliased chr names)",
        [
            (
                "text=K562_REP1",
                "Stranded coverage",
                "Forward and reverse bigWigs per sample; K562 lights up the gamma-globins.",
            ),
            (
                '[data-testid="jbrowse-status"]',
                "Samplesheet-driven",
                "Rows picked in the samplesheet table open their tracks.",
            ),
        ],
    ),
}


def _nfcore_scenario(name: str, dashboard_id: str) -> Callable[..., Awaitable[Shot]]:
    title, heading, subtitle, texts, *rest = NFCORE[name]
    pick = rest[0] if rest else None
    locus = rest[1] if len(rest) > 1 else None

    async def scenario(page, base: str) -> Shot:
        return await nfcore_tab(
            page, base, dashboard_id, title, f"nfcore_{name}", heading, subtitle, texts, pick, locus
        )

    return scenario


def _cutandrun_peak_scenario(dashboard_id: str) -> Callable[..., Awaitable[Shot]]:
    """A region picked in the peak table: the browser opens its sample on it."""

    async def scenario(page, base: str) -> Shot:
        await _open(page, base, dashboard_id)
        tile = await _tile(page, "Genome browser")
        await _settle(page)
        # The peak table mounts once scrolled to (lazy tiles).
        await page.evaluate(
            "() => { const c = document.querySelector('[data-testid=dashboard-content]');"
            " if (c) c.scrollTop = c.scrollHeight; }"
        )
        await page.wait_for_timeout(4000)
        table = (
            page.locator(".react-grid-item")
            .filter(has=page.get_by_text("SEACR regions", exact=True))
            .filter(has=page.locator(".ag-root-wrapper"))
            .first
        )
        row = table.locator(".ag-row").nth(3)
        await row.locator(".ag-checkbox-input-wrapper, .ag-selection-checkbox").first.click()
        await page.wait_for_timeout(1500)
        await tile.scroll_into_view_if_needed()
        await _settle(page, 9000)
        context = await _context(
            page,
            "nfcore_cutandrun_peak_context",
            "nf-core/cutandrun: a region picked in the peak table",
            "Cards, Manhattan and tables narrow to it; the browser opens its sample on the region",
            tile,
            notes={
                **NFCORE_NOTES,
                "SEACR regions": "The picked row: a filter on peak_id, carried to the tracks "
                "through the seacr_peaks -> tracks link.",
            },
        )
        png, origin = await _clip_capture(page, [tile], pad=4)
        return Shot(
            "nfcore_cutandrun_peak",
            "nf-core/cutandrun: the browser on a picked region",
            "locus_from moves the view onto the region (± 2 kb); only its sample's tracks stay open",
            png,
            [
                Callout(
                    await _box(tile.locator("input").first, origin),
                    "Locus from the picked row",
                    "The peak table narrows seacr_peaks to one row: locus_from jumps there.",
                ),
                Callout(
                    await _box(tile.locator('[data-testid="jbrowse-status"]'), origin),
                    "Its sample only",
                    "The same filter, through the seacr_peaks -> tracks link, keeps that "
                    "sample's signal, peaks and reads.",
                ),
            ],
            context=context,
        )

    return scenario


if __name__ == "__main__":
    main()
