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


CONTEXT_VIEWPORT = {"width": 1680, "height": 1280}


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


async def _context(
    page,
    name: str,
    title: str,
    subtitle: str,
    tile,
    section: str = "Genome browser",
    extra: list[tuple[object, str, str]] | None = None,
) -> Shot:
    """The whole Depictio page around the browser, before the close-up crop.

    The dashboard scrolls inside a fixed header and filter panel, so the section
    holding the browser is brought to the top of that scroller and the viewport
    made taller; both are restored for the crop that follows.
    """
    await page.set_viewport_size(CONTEXT_VIEWPORT)
    sec = page.locator(".depictio-section-item").filter(has=page.get_by_text(section, exact=True))
    if await sec.count():
        await sec.first.evaluate("e => e.scrollIntoView({block: 'start'})")
    else:
        await tile.evaluate("e => e.scrollIntoView({block: 'center'})")
    await _settle(page, 4000)
    png = await page.screenshot()
    origin = (0.0, 0.0)
    header = page.locator(".mantine-AppShell-header").first
    callouts = [
        Callout(
            await _box(header, origin),
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
            "Interactive filters of the left panel; the browser follows them through the DC links.",
        ),
        Callout(
            await _box(tile, origin),
            "Genome browser component",
            "A tile of the grid like a figure or a table: Depictio title, action bar "
            "(metadata, fullscreen, reset, header / overview / status toggles).",
        ),
    ]
    for loc, head, body in extra or []:
        if await loc.count():  # type: ignore[attr-defined]
            callouts.append(Callout(await _box(loc.first, origin), head, body))  # type: ignore[attr-defined]
    await page.set_viewport_size(VIEWPORT)
    await tile.scroll_into_view_if_needed()
    await _settle(page, 3000)
    return Shot(name, title, subtitle, png, callouts)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

STRANDSEQ = "946b0f3c1e4a2d7f8e5bca00"
SARSCOV2 = "946b0f3c1e4a2d7f8e5bca20"


async def strandseq_overview(page, base: str) -> Shot:
    await _open(page, base, STRANDSEQ)
    tile = await _tile(page, "SV calls per cell")
    await _settle(page)
    scatter = page.locator(".react-grid-item").filter(has_text="Cell quality").first
    context = await _context(
        page,
        "strandseq_context",
        "Strand-seq showcase in Depictio",
        "The genome browser next to a scatter, cards and tables, driven by the left-panel filters",
        tile,
        extra=[(scatter, "Figure next to it", "Lasso cells here to open their SV tracks.")],
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
        "SARS-CoV-2 showcase in Depictio",
        "A variant picked in the table: the browser jumps to it (locus_from) and shows its samples",
        tile,
        extra=[
            (table, "Variant table", "Selecting a row filters the dashboard on that variant."),
        ],
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
        f"{heading.split(':')[0]} template in Depictio",
        "The Genome tracks tab of the template: its tabs, its filters and the browser tile",
        tile,
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
    await page.set_viewport_size({"width": 1680, "height": 1500})
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
    # The two columns side by side (form + summary), down to the overrides editor.
    fb = await form.bounding_box()
    ob = await overrides.locator("xpath=../..").bounding_box()
    assert fb and ob
    x0, y0 = fb["x"] - 24, fb["y"] - 24
    clip = {
        "x": x0,
        "y": y0,
        "width": 1680 - 2 * x0,
        "height": ob["y"] + ob["height"] + 24 - y0,
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
                await _box(summary.locator("xpath=../.."), origin),
                "Live summary",
                "Which tracks would show under the current filters; 'Saved view' renders "
                "the real browser.",
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


if __name__ == "__main__":
    main()
