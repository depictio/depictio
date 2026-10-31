#!/usr/bin/env python3
"""Short screen recordings of the genome browser (``jbrowse``) interactions.

Companion of ``jbrowse_screenshots.py``: the same running Depictio, but each
scenario is a 10-30 s clip of one interaction (a table pick framing the browser,
a click in the browser filtering the dashboard, a GenomeSpy brush moving the
browser, UCSC tracks and the track menu, the variant stepper). A visible cursor
and a caption are drawn into the page so the clip reads without sound.

Frames come from Chrome's screencast (CDP ``Page.startScreencast``), which only
emits a frame when the page repaints; the gaps are replayed with their real
duration, capped at ``--max-still`` so a loading wait does not stall the clip.
Waits for data (``_beat``, ``_ff``) are fast-forwarded ``FAST_FORWARD`` times, so
a clip shows the interaction at its pace and the loading in a blink.

Usage:
    .venv/bin/python dev/diagrams/jbrowse_videos.py --base-url http://127.0.0.1:8140 \\
        --out /tmp/jbrowse-videos --dashboard viralrecon=<id> --dashboard chipseq=<id> ...
    .venv/bin/python dev/diagrams/jbrowse_videos.py ... --only genomespy_jbrowse

Each clip is written as ``<name>.mp4`` (H.264, faststart) with a ``<name>.webp``
poster. Needs ``ffmpeg`` on the PATH.

Interactions on a dashboard are remembered per user (filters, selections):
run it against a throwaway instance or reset the filters afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jbrowse_screenshots import _chromium_path, _settle  # noqa: E402

VIEWPORT = {"width": 1600, "height": 1000}
SCALE = 1
# How much faster the waits for data play than the interaction around them.
FAST_FORWARD = 6
# The recorder of the clip being filmed, for the waits to mark themselves.
_REC: Recorder | None = None

# A cursor and a caption drawn by the page itself, so the screencast carries them.
OVERLAY_JS = """
(() => {
  // The app reads ?no-walkthrough=1 once at load: keep it on every page an
  // in-app link opens, or the tour covers the next tab.
  const url = new URL(location.href);
  if (!url.searchParams.has('no-walkthrough')) {
    url.searchParams.set('no-walkthrough', '1');
    history.replaceState(history.state, '', url);
  }
  const install = () => {
    if (document.getElementById('__rec_cursor')) return;
    const style = document.createElement('style');
    style.textContent = `
      #__rec_cursor { position: fixed; left: 0; top: 0; width: 22px; height: 22px;
        margin: -11px 0 0 -11px; border-radius: 50%; z-index: 2147483647;
        pointer-events: none; background: rgba(230, 73, 128, .35);
        border: 2px solid rgba(230, 73, 128, .95); transition: transform .12s; }
      #__rec_cursor.down { transform: scale(.7); background: rgba(230, 73, 128, .6); }
      .__rec_ripple { position: fixed; width: 44px; height: 44px; margin: -22px 0 0 -22px;
        border-radius: 50%; border: 3px solid rgba(230, 73, 128, .9); z-index: 2147483646;
        pointer-events: none; animation: __rec_ripple .6s ease-out forwards; }
      @keyframes __rec_ripple { from { transform: scale(.3); opacity: 1 }
                                to { transform: scale(1.4); opacity: 0 } }
      #__rec_caption { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%);
        max-width: 70%; padding: 10px 18px; border-radius: 10px; z-index: 2147483645;
        pointer-events: none; font: 600 17px/1.35 Inter, system-ui, sans-serif;
        color: #fff; background: rgba(20, 22, 30, .82); box-shadow: 0 6px 24px rgba(0,0,0,.25);
        opacity: 0; transition: opacity .35s; text-align: center; }
      #__rec_caption.on { opacity: 1; }`;
    document.head.appendChild(style);
    const c = document.createElement('div'); c.id = '__rec_cursor';
    const cap = document.createElement('div'); cap.id = '__rec_caption';
    document.body.append(c, cap);
    window.addEventListener('mousemove', e => {
      c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
    }, true);
    window.addEventListener('mousedown', e => {
      c.classList.add('down');
      const r = document.createElement('div'); r.className = '__rec_ripple';
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.body.appendChild(r); setTimeout(() => r.remove(), 700);
    }, true);
    window.addEventListener('mouseup', () => c.classList.remove('down'), true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
"""


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


class Recorder:
    """Collects screencast frames with their timestamps between start() and stop()."""

    def __init__(self, page) -> None:
        self.page = page
        self.frames: list[tuple[float, bytes]] = []
        # Wall-clock spans (the screencast's timestamps) played FAST_FORWARD times faster.
        self.fast: list[tuple[float, float]] = []
        self.cdp = None

    async def start(self) -> None:
        self.cdp = await self.page.context.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        await self.cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 88,
                "maxWidth": self.page.viewport_size["width"] * SCALE,
                "maxHeight": self.page.viewport_size["height"] * SCALE,
                "everyNthFrame": 1,
            },
        )

    def _on_frame(self, event: dict) -> None:
        self.frames.append((event["metadata"]["timestamp"], base64.b64decode(event["data"])))
        asyncio.ensure_future(
            self.cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        )

    async def stop(self) -> None:
        # One last repaint so the final state has a frame of its own.
        await self.page.wait_for_timeout(1200)
        await self.cdp.send("Page.stopScreencast")

    def _in_fast(self, ts: float) -> bool:
        return any(t0 <= ts < t1 for t0, t1 in self.fast)

    def encode(
        self, out: Path, max_still: float, width: int, speed: float = 1, tail: float = 1.5
    ) -> None:
        if len(self.frames) < 2:
            raise RuntimeError("no frames recorded")
        with tempfile.TemporaryDirectory() as tmp:
            lines = []
            for i, (ts, data) in enumerate(self.frames):
                path = Path(tmp) / f"f{i:05d}.jpg"
                path.write_bytes(data)
                nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else ts + tail
                rate = speed * (FAST_FORWARD if self._in_fast(ts) else 1)
                lines += [
                    f"file '{path}'",
                    f"duration {min(max(nxt - ts, 0.02) / rate, max_still):.3f}",
                ]
            lines.append(f"file '{Path(tmp) / f'f{len(self.frames) - 1:05d}.jpg'}'")
            concat = Path(tmp) / "list.txt"
            concat.write_text("\n".join(lines))
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(concat), "-vf",
                    f"scale={width}:-2:flags=lanczos,fps=30,format=yuv420p",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "28",
                    "-movflags", "+faststart", str(out),
                ],
                check=True,
            )  # fmt: skip
            last = Path(tmp) / f"f{len(self.frames) - 1:05d}.jpg"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(last),
                    "-vf", f"scale={width}:-2:flags=lanczos", "-quality", "82",
                    str(out.with_suffix(".webp")),
                ],
                check=True,
            )  # fmt: skip


# ---------------------------------------------------------------------------
# Gestures
# ---------------------------------------------------------------------------


class Hand:
    """Mouse moves that glide (the overlay cursor follows), clicks, drags, captions."""

    def __init__(self, page) -> None:
        self.page = page
        self.x, self.y = VIEWPORT["width"] / 2, VIEWPORT["height"] / 2

    async def glide(self, x: float, y: float, speed: float = 1.4) -> None:
        dist = math.hypot(x - self.x, y - self.y)
        await self.page.mouse.move(x, y, steps=max(8, int(dist / (12 * speed))))
        self.x, self.y = x, y

    async def click_at(self, x: float, y: float, pause: int = 350) -> None:
        await self.glide(x, y)
        await self.page.wait_for_timeout(pause)
        await self.page.mouse.down()
        await self.page.wait_for_timeout(90)
        await self.page.mouse.up()

    async def click(self, locator, pause: int = 350) -> None:
        await locator.scroll_into_view_if_needed()
        box = await locator.bounding_box()
        if box is None:
            raise RuntimeError(f"not visible: {locator}")
        await self.click_at(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, pause)

    async def drag(self, x0: float, y0: float, x1: float, y1: float, steps: int = 40) -> None:
        await self.glide(x0, y0)
        await self.page.wait_for_timeout(300)
        await self.page.mouse.down()
        await self.page.mouse.move(x1, y1, steps=steps)
        self.x, self.y = x1, y1
        await self.page.wait_for_timeout(150)
        await self.page.mouse.up()

    async def type(self, locator, text: str) -> None:
        await self.click(locator)
        await locator.press("ControlOrMeta+a")
        await locator.press_sequentially(text, delay=70)
        await locator.press("Enter")

    async def zoom(self, locator, scale: float = 1.45, hold: int = 1800) -> None:
        """Zoom the page on ``locator`` for ``hold`` ms, then back: a camera move
        onto the result of a click. The app root is scaled, so nothing re-renders."""
        box = await locator.bounding_box()
        if box is None:
            return
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        await self.page.evaluate(
            """([x, y, s]) => { const r = document.getElementById('root'); if (!r) return;
                 const b = r.getBoundingClientRect();
                 r.style.transformOrigin = `${x - b.left}px ${y - b.top}px`;
                 r.style.transition = 'transform .55s cubic-bezier(.3,.7,.2,1)';
                 r.style.transform = `scale(${s})`; }""",
            [cx, cy, scale],
        )
        await self.page.wait_for_timeout(550 + hold)
        await self.page.evaluate(
            "() => { const r = document.getElementById('root'); if (r) r.style.transform = ''; }"
        )
        await self.page.wait_for_timeout(600)

    async def caption(self, text: str | None, hold: int = 1600) -> None:
        await self.page.evaluate(
            """t => { const c = document.getElementById('__rec_caption'); if (!c) return;
                      if (t) { c.textContent = t; c.classList.add('on'); }
                      else c.classList.remove('on'); }""",
            text,
        )
        await self.page.wait_for_timeout(hold if text else 400)


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


async def _open(page, base: str, dashboard_id: str) -> None:
    await page.goto(
        f"{base}/dashboard/{dashboard_id}?no-walkthrough=1",
        wait_until="networkidle",
        timeout=120_000,
    )
    await page.wait_for_timeout(1500)


async def _scroll_to(page, locator, offset: int = 90, smooth: bool = False, ms: int = 1300) -> None:
    """Scroll the dashboard so ``locator`` sits ``offset`` px below the top of the
    view; ``smooth`` eases there over ``ms``, the way a reader scrolls."""
    handle = await locator.element_handle()
    await page.evaluate(
        """([el, offset, smooth, ms]) => new Promise(done => {
          const sc = document.querySelector('[data-testid=dashboard-content]')
            || document.scrollingElement;
          const from = sc.scrollTop;
          const by = el.getBoundingClientRect().top - sc.getBoundingClientRect().top - offset;
          if (!smooth) { sc.scrollTop = from + by; return done(); }
          const t0 = performance.now();
          const step = now => {
            const t = Math.min(1, (now - t0) / ms);
            sc.scrollTop = from + by * (t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
            t < 1 ? requestAnimationFrame(step) : done();
          };
          requestAnimationFrame(step);
        })""",
        [handle, offset, smooth, ms],
    )
    await page.wait_for_timeout(300 if smooth else 500)


async def _scroll_top(page) -> None:
    await page.evaluate(
        """() => { const sc = document.querySelector('[data-testid=dashboard-content]')
                  || document.scrollingElement; sc.scrollTop = 0; }"""
    )
    await page.wait_for_timeout(400)


async def _arrive(page, rec: Recorder, target, offset: int = 10, ms: int = 1800) -> None:
    """Start filming at the top of the tab and scroll down to ``target``, the way
    a reader reaches a section. Everything on the way has loaded once already."""
    await _scroll_top(page)
    await rec.start()
    await page.wait_for_timeout(700)
    await _scroll_to(page, target, offset=offset, smooth=True, ms=ms)


async def _ff(page, awaitable):
    """Await ``awaitable`` (a load, a navigation) and fast-forward it in the clip."""
    t0 = time.time()
    try:
        return await awaitable
    finally:
        if _REC is not None and _REC.cdp is not None:
            _REC.fast.append((t0, time.time()))


def _section(page, title: str):
    return page.get_by_text(title, exact=True).first


async def _browser(page, title: str | None = None):
    """The grid tile of a genome browser (by tile text when several), ready.

    Tiles mount when scrolled to, so the tile is brought into view first."""
    tiles = page.locator(".react-grid-item").filter(
        has=page.locator('[data-testid="jbrowse-component"]')
    )
    if title:
        tiles = tiles.filter(has_text=title)
    tile = tiles.first
    await tile.wait_for(state="attached", timeout=60_000)
    await tile.scroll_into_view_if_needed()
    await tile.locator('[data-jbrowse-ready="true"]').first.wait_for(timeout=90_000)
    return tile


async def _close_filters(page) -> None:
    """Hide the left filter panel to give the canvas the full width."""
    hide = page.locator("button[aria-label='Hide filters']")
    if await hide.count():
        await hide.first.click()
        await page.wait_for_timeout(800)


async def _hide_floating(page) -> None:
    """Hide floating browsers (they follow across tabs) so they do not cover the grid."""
    for _ in range(3):
        hide = page.locator("button[aria-label='Hide genome browser panel']")
        if not await hide.count():
            return
        await hide.first.click()
        await page.wait_for_timeout(500)


async def _tile_button(page, tile, testid: str | None, label: str | None = None):
    """A button of the tile's hover bar (by test id or aria-label), shown by
    hovering the tile's top edge."""
    box = await tile.bounding_box()
    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 8)
    sel = f'[data-testid="{testid}"]' if testid else f'button[aria-label="{label}"]'
    button = tile.locator(sel).first
    await button.wait_for(state="visible", timeout=10_000)
    return button


# ---------------------------------------------------------------------------
# Scenarios. Each gets (page, hand, recorder, ids); setup runs before
# recorder.start(), so only the interaction is filmed.
# ---------------------------------------------------------------------------

Scenario = Callable[..., Awaitable[None]]


async def _warm(page, titles: tuple[str, ...], ms: int = 2500) -> None:
    """Scroll once past each section so its tiles mount and load before filming."""
    for title in titles:
        section = _section(page, title)
        if await section.count():
            await _scroll_to(page, section, offset=10)
            await _settle(page, ms)


async def _look(page, hand: Hand, locator, ms: int = 900) -> None:
    """Glide the cursor onto ``locator`` and dwell, the reader's eye on it."""
    await hand.glide(*(await _center(locator)))
    await page.wait_for_timeout(ms)


def _tile(page, text: str):
    return page.locator(".react-grid-item").filter(has_text=text).first


async def table_to_browser(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """nf-core/riboseq Locus: a row of the ORF table drives its record and the browser."""
    await _open(page, BASE, ids["riboseq"])
    await _close_filters(page)
    await _scroll_to(page, _section(page, "ORF at its locus"), offset=10)
    tile = await _browser(page)
    await _scroll_to(page, _section(page, "ORF at its locus"), offset=10)
    await _settle(page, 4000)
    table = page.locator(".react-grid-item").filter(has=page.locator(".ag-root")).first
    await table.locator(".ag-row").first.wait_for(timeout=30_000)
    rows = table.locator(".ag-center-cols-container .ag-row")
    await _arrive(page, rec, _section(page, "ORF at its locus"))
    await hand.caption("The ORF table, its record and the browser, linked on one tab", hold=900)
    for n, text in (
        (1, "Pick an ORF: its record fills in and the browser frames it"),
        (4, "Another pick: the browser follows, the ORF starred on its gene"),
    ):
        await hand.caption(text, hold=500)
        await hand.click(rows.nth(n).locator(".ag-cell").nth(2))
        await _beat(page, 2500)
        await hand.zoom(tile, scale=1.25, hold=1500)
    await hand.caption(None)


async def browser_to_dashboard(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """nf-core/viralrecon Variants: clicking a variant filters the navigator above on its sample."""
    await _open(page, BASE, ids["viralrecon"])
    tile = await _browser(page)
    await _scroll_to(page, _section(page, "Along the genome"), offset=10)
    await _settle(page, 5000)
    navigator = _tile(page, "Allele frequency along")
    variants = tile.locator(
        '[data-testid^="trackRenderingContainer"][data-testid$=".variants"]'
    ).first
    vb = await variants.bounding_box()
    assert vb, "no variant track open"
    point = await _find_saturated(page, vb["x"], vb["y"], vb["width"], min(vb["height"], 40))
    assert point, "no variant drawn on the first variant track"
    await _arrive(page, rec, _section(page, "Along the genome"))
    await hand.caption("Every call of every sample on the navigator, the reads in the browser")
    await _look(page, hand, navigator, 700)
    await hand.caption("Click a variant in the browser", hold=500)
    await hand.click_at(*point)
    await page.wait_for_timeout(900)
    # Escape would clear the selection too: close the details with their button.
    await hand.click(page.locator(".mantine-Modal-close").first)
    await hand.caption("Its sample becomes a filter: the navigator keeps that sample's calls")
    await _beat(page, 2500)
    await hand.zoom(navigator, scale=1.3, hold=1600)
    await _look(page, hand, page.get_by_text("filter active").first, 1000)
    await hand.caption(None)


async def genomespy_jbrowse(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """nf-core/nascent Genome signal: frame a gene's neighbourhood on the GenomeSpy
    lanes, brush its middle, then read the peaks in the browser below."""
    await _open(page, BASE, ids["nascent"])
    tile = await _browser(page)
    await _close_filters(page)
    lanes = (
        page.locator(".react-grid-item")
        .filter(has=page.locator('[data-testid="genome-view-interaction-mode"]'))
        .first
    )
    # The lanes on top, the browser under them: both stay in the frame.
    await _scroll_to(page, lanes, offset=10)
    await _settle(page, 5000)
    canvas = lanes.locator("canvas").first
    await _arrive(page, rec, lanes)
    # Scrolled back in, the lanes lay out again: let them, quickly.
    await _beat(page, 2500)
    await hand.caption("One lane per library, the time course from purple to yellow", hold=900)
    await hand.caption("Frame a responsive gene's neighbourhood on chr15", hold=300)
    await hand.type(lanes.get_by_label("Locus or gene"), LANES_LOCUS)
    await _beat(page, 2500)
    await hand.caption("Switch the lanes to Select and brush the middle", hold=600)
    await hand.click(lanes.locator('[data-testid="genome-view-interaction-mode"] label').nth(2))
    cb = await canvas.bounding_box()
    y = cb["y"] + cb["height"] * 0.45
    await hand.drag(
        cb["x"] + cb["width"] * BRUSH[0], y, cb["x"] + cb["width"] * BRUSH[1], y, steps=30
    )
    await hand.caption("The browser opens on the brushed window, strand by strand")
    await _beat(page, 3500)
    await _scroll_to(page, tile, offset=60, smooth=True, ms=1200)
    await hand.caption("Autoscale Local SD: each track scaled to its own peaks", hold=300)
    settings = await _tile_button(page, tile, None, "Viz settings")
    await hand.click(settings)
    autoscale = page.locator('[data-testid="jbrowse-display-autoscale"]').first
    await autoscale.wait_for(timeout=10_000)
    await hand.click(autoscale.get_by_text("Local SD", exact=True))
    await page.wait_for_timeout(500)
    await page.keyboard.press("Escape")
    await _beat(page, 2000)
    await hand.zoom(tile, scale=1.2, hold=1400)
    await hand.caption("Then read along: drag the tracks, zoom on a peak")
    track = tile.locator('[data-testid^="trackRenderingContainer"]').nth(2)
    tb = await track.bounding_box()
    ty = tb["y"] + tb["height"] / 2
    await hand.drag(tb["x"] + tb["width"] * 0.7, ty, tb["x"] + tb["width"] * 0.35, ty, steps=40)
    await _beat(page, 1500)
    zoom_in = tile.locator('[data-testid="zoom_in"]').first
    if await zoom_in.count():
        for _ in range(2):
            await hand.click(zoom_in)
            await _beat(page, 1200)
    await hand.zoom(tile, scale=1.2, hold=1600)
    await hand.caption(None)


async def _zoom_in(page, hand: Hand, tile, times: int) -> None:
    """The browser's own zoom-in button, ``times`` times, each load fast-forwarded."""
    button = tile.locator('[data-testid="zoom_in"]').first
    if not await button.count():
        return
    for _ in range(times):
        await hand.click(button, pause=200)
        await _beat(page, 1200)


async def _local_sd(page, hand: Hand, tile) -> None:
    """Autoscale every signal track to its own peaks (Viz settings, Local SD)."""
    await hand.click(await _tile_button(page, tile, None, "Viz settings"))
    autoscale = page.locator('[data-testid="jbrowse-display-autoscale"]').first
    await autoscale.wait_for(timeout=10_000)
    await hand.click(autoscale.get_by_text("Local SD", exact=True))
    await page.wait_for_timeout(500)
    await page.keyboard.press("Escape")
    await _beat(page, 1500)


async def _browser_locus(lanes) -> tuple[str, int] | None:
    """Chromosome and centre of the browser's window, read off the lanes' link chip
    ("Browser view chr14:38.014-38.019 Mb")."""
    text = await lanes.inner_text()
    m = re.search(r"Browser view\s+([^:\s]+):([\d.]+)-([\d.]+)\s*Mb", text)
    if not m:
        return None
    lo, hi = float(m.group(2)), float(m.group(3))
    return m.group(1), int((lo + hi) / 2 * 1_000_000)


async def peak_brush(page, hand: Hand, rec: Recorder, ids: dict[str, str], name: str) -> None:
    """A Locus tab of a peak pipeline: widen the lanes around the browser's best
    call, brush the peak in their middle, then read it in the browser."""
    await _open(page, BASE, ids[name])
    tile = await _browser(page)
    await _close_filters(page)
    lanes = (
        page.locator(".react-grid-item")
        .filter(has=page.locator('[data-testid="genome-view-interaction-mode"]'))
        .first
    )
    await _scroll_to(page, lanes, offset=10)
    await _settle(page, 5000)
    where = await _browser_locus(lanes)
    assert where, "no browser location"
    chrom, centre = where
    canvas = lanes.locator("canvas").first
    await _arrive(page, rec, lanes)
    await _beat(page, 2000)
    await hand.caption("One lane per library, on the browser's window: widen it", hold=600)
    field_ = lanes.get_by_label("Locus or gene")
    if await field_.count():
        span = PEAK_LANES_SPAN
        await hand.type(field_, f"{chrom}:{max(centre - span, 1):,}-{centre + span:,}")
    else:
        # No locus field: zoom the lanes on the browser's band with Ctrl + wheel.
        band = lanes.get_by_text("Browser view").last
        bb = await canvas.bounding_box()
        x = (await band.bounding_box() or bb)["x"]
        await hand.glide(x, bb["y"] + bb["height"] * 0.5)
        await page.keyboard.down("Control")
        for _ in range(8):
            await page.mouse.wheel(0, -400)
            await page.wait_for_timeout(150)
        await page.keyboard.up("Control")
    await _beat(page, 2500)
    await hand.caption("The calls around the browser's peak, lane by lane", hold=900)
    await hand.caption("Select, and brush the peak in the middle", hold=500)
    await hand.click(lanes.locator('[data-testid="genome-view-interaction-mode"] label').nth(2))
    cb = await canvas.bounding_box()
    y = cb["y"] + cb["height"] * 0.5
    await hand.drag(
        cb["x"] + cb["width"] * PEAK_BRUSH[0], y, cb["x"] + cb["width"] * PEAK_BRUSH[1], y, steps=25
    )
    await hand.caption("The browser opens on the brushed window")
    await _beat(page, 3000)
    await _scroll_to(page, tile, offset=60, smooth=True, ms=1200)
    await hand.caption("Autoscale Local SD: each signal scaled to its own peaks", hold=300)
    await _local_sd(page, hand, tile)
    await hand.zoom(tile, scale=1.2, hold=1300)
    await hand.caption("Zoom in on the peak, then along to the genes beside it", hold=300)
    await _zoom_in(page, hand, tile, 2)
    track = tile.locator('[data-testid^="trackRenderingContainer"]').nth(2)
    tb = await track.bounding_box()
    ty = tb["y"] + tb["height"] / 2
    await hand.drag(tb["x"] + tb["width"] * 0.7, ty, tb["x"] + tb["width"] * 0.4, ty, steps=40)
    await _beat(page, 1500)
    genes = tile.locator('[data-testid$="-genes"]').first
    await _look(page, hand, genes, 700)
    await hand.zoom(tile, scale=1.2, hold=1600)
    await hand.caption(None)


def _peaks(name: str) -> Scenario:
    async def scenario(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
        await peak_brush(page, hand, rec, ids, name)

    return scenario


async def ucsc_and_tracks(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """nf-core/viralrecon Variants: UCSC tracks by name, the track menu, force load."""
    await _open(page, BASE, ids["viralrecon"])
    tile = await _browser(page)
    await _close_filters(page)
    await _scroll_to(page, tile, offset=10)
    await _settle(page, 6000)
    variants = tile.locator(
        '[data-testid^="trackRenderingContainer"][data-testid$=".variants"]'
    ).first
    track_id = (await variants.get_attribute("data-testid")).rsplit("-", 1)[-1]
    sample = track_id.removesuffix(".variants")
    await _arrive(page, rec, tile)
    await hand.caption("UCSC tracks by name: the ARTIC primers and the Nextstrain clades")
    await hand.glide(*(await _center(tile.get_by_text("ARTIC Primers V3").first)))
    await page.wait_for_timeout(900)
    await hand.glide(*(await _center(tile.get_by_text("Nextstrain Clades").first)))
    await page.wait_for_timeout(900)
    await hand.caption("Next to the run's own VCF and BAM tracks, read in place")
    await hand.glide(*(await _center(tile.get_by_text(f"{sample} variants").first)))
    await page.wait_for_timeout(1200)
    await hand.caption("Every track keeps JBrowse's own menu: display mode, colours, height")
    menu_icon = variants.locator("xpath=preceding::*[@data-testid='track_menu_icon'][1]")
    await hand.click(menu_icon)
    await page.wait_for_timeout(1800)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)
    await hand.caption("The whole genome in view: the clade track exceeds its download limit")
    await hand.type(tile.locator("input").first, "NC_045512v2:1-29,903")
    await _beat(page, 2500)
    await hand.caption("Force load fetches a track past its download limit, read by range")
    clades = tile.locator('[data-testid$="-ucsc-wuhCor1-nextstrainClade"]')
    await hand.click(clades.get_by_role("button", name="Force load").first)
    await _beat(page, 4000)
    await hand.caption(None)


async def ucsc_builder(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """The component builder: pick UCSC tracks from the assembly's catalogue. Never saved."""
    await page.goto(
        f"{BASE}/dashboard-edit/{ids['viralrecon']}/component/edit/var-browser?no-walkthrough=1",
        wait_until="networkidle",
        timeout=120_000,
    )
    await page.wait_for_timeout(2500)
    picker = page.locator('[data-testid="jbrowse-builder-ucsc-tracks"]').first
    await picker.scroll_into_view_if_needed()
    await _scroll_to(page, page.get_by_text("UCSC tracks", exact=True).first, offset=200)
    await rec.start()
    await hand.caption("In the builder, UCSC tracks come from the assembly's own catalogue")
    field_ = picker
    await hand.click(field_)
    await field_.press_sequentially("gene", delay=90)
    await page.wait_for_timeout(1500)
    option = page.get_by_role("option").first
    await hand.glide(*(await _center(option)))
    await page.wait_for_timeout(600)
    await hand.click(option)
    await page.keyboard.press("Escape")
    await hand.caption("Assembly, presets, force load and fetch size sit in the same form")
    await hand.glide(
        *(await _center(page.locator('[data-testid="jbrowse-builder-force-load"]').first))
    )
    await page.wait_for_timeout(1500)
    await hand.caption(None)


async def ranked_rows(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """nf-core/raredisease Locus: a row of the ranked-variants table frames the browser."""
    await _open(page, BASE, ids["raredisease"])
    await _close_filters(page)
    await _scroll_to(page, _section(page, "Variants on one axis"), offset=10)
    tile = await _browser(page)
    await _scroll_to(page, tile, offset=10)
    await _settle(page, 5000)
    table = page.locator(".react-grid-item").filter(has_text="Ranked variants in the region").first
    await _arrive(page, rec, tile)
    await hand.caption("The best-ranked variants of the region, starred by rank in the browser")
    await page.wait_for_timeout(1500)
    await _scroll_to(page, table, offset=560, smooth=True)
    await table.locator(".ag-row").first.wait_for(timeout=30_000)
    await hand.caption(
        "Pick a row: the browser frames that variant, and the row keeps a coloured bar"
    )
    for n in (1, 2):
        await hand.click(
            table.locator(".ag-center-cols-container .ag-row").nth(n).locator(".ag-cell").nth(5)
        )
        await _beat(page, 3000)
    await hand.caption("Down to the variant: the browser zooms on it, the reads under it", hold=300)
    await _scroll_to(page, tile, offset=60, smooth=True, ms=1300)
    await _zoom_in(page, hand, tile, 3)
    ranked = tile.locator(
        '[data-testid^="trackRenderingContainer"][data-testid$="-depictio-ranked-calls"]'
    ).first
    rb = await ranked.bounding_box()
    point = None
    if rb:
        # The picked variant sits in the middle of the window: its star there.
        cx = rb["x"] + rb["width"] / 2
        point = await _find_saturated(page, cx - 80, rb["y"], 160, min(rb["height"], 60))
    if point:
        await hand.caption("Click it: its ranking, inheritance model and compound partners")
        await hand.click_at(*point)
        await page.wait_for_timeout(900)
        modal = page.locator('[role="dialog"]').first
        if await modal.count():
            await hand.zoom(modal, scale=1.3, hold=2200)
            await hand.click(page.locator(".mantine-Modal-close").first)
    await hand.caption("And the reads of each family member at that position", hold=300)
    reads = tile.locator('[data-testid$=".alignment"]').first
    await _look(page, hand, reads, 900)
    await hand.zoom(reads, scale=1.3, hold=1600)
    await hand.caption(None)


async def fusion_chord(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """nf-core/rnafusion Breakpoints: chord links, one after the other, open each call's reads."""
    await _open(page, BASE, ids["rnafusion"])
    await _close_filters(page)
    await _warm(page, ("Breakpoints at a glance", "Partner contigs", "Breakpoints and reads"))
    tile = await _browser(page)
    chord = _tile(page, "Breakpoints on the genome")
    record = _tile(page, "Call record")
    section = _section(page, "Breakpoints and reads")
    await _scroll_to(page, section, offset=10)
    await _settle(page, 5000)
    await _arrive(page, rec, section, ms=2200)
    # Links are thin strokes: click the middle of the curve, not of its box.
    points = await chord.evaluate(
        """t => [...t.querySelectorAll("svg:not(.iconify) path")]
            .filter(p => p.style.cursor === 'pointer')
            .map(p => { const m = p.getPointAtLength(p.getTotalLength() / 2)
                          .matrixTransform(p.getScreenCTM());
                        return [m.x, m.y]; })"""
    )
    assert len(points) >= 3, "too few chord links"
    picks = list(dict.fromkeys(min(i, len(points) - 1) for i in (4, len(points) // 2 + 1, 1)))
    captions = (
        "Click a link on the ring: its record opens beside it",
        "Another call: the record and both breakpoints follow",
        "One more, between two other chromosomes",
    )
    for i, text in zip(picks, captions, strict=False):
        await hand.caption(text, hold=500)
        await hand.click_at(*points[i])
        await _beat(page, 3000)
        await hand.zoom(record, scale=1.5, hold=1300)
        await hand.caption("Both sides of the breakpoint in the browser, the reads that span it")
        await hand.zoom(tile, scale=1.25, hold=1600)
    await hand.caption(None)


async def sashimi_junctions(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """nf-core/rnafusion Splice Junctions: the tab from the cards to the table, the
    sashimi's locus and zoom driving the reads below."""
    await _open(page, BASE, ids["rnafusion_splice"])
    await _close_filters(page)
    await _warm(page, ("Junctions at a glance", "Junction landscape", "Junction arcs"))
    section = _section(page, "Junction arcs")
    await _scroll_to(page, section, offset=10)
    if not await page.locator('[data-testid="jbrowse-component"]').count():
        await section.click()
    tile = await _browser(page)
    arcs = _tile(page, "Junction arcs over the busiest loci")
    await _scroll_to(page, section, offset=10)
    locus = page.get_by_label("Locus").first
    await locus.wait_for(timeout=60_000)
    # Warm every locus once (arcs, BAM index, reads), then come back to the first.
    await locus.click()
    n = await page.get_by_role("option").count()
    await page.keyboard.press("Escape")
    for i in [*range(1, min(n, 3)), 0]:
        await locus.click()
        await page.get_by_role("option").nth(i).click()
        await _settle(page, 4000)
    # The table's section opens collapsed: open it once, before filming.
    table = page.locator(".react-grid-item").filter(has=page.locator(".ag-root")).first
    await _scroll_to(page, _section(page, "Junction table"), offset=10)
    if not await table.count():
        await _section(page, "Junction table").click()
    await table.locator(".ag-row").first.wait_for(timeout=60_000)
    await _settle(page, 2000)

    await _scroll_top(page)
    await rec.start()
    await hand.caption("Junctions at a glance: scored, supported, read across", hold=700)
    cards = _tile(page, "Junctions scored")
    await _look(page, hand, cards, 600)
    await _look(page, hand, _tile(page, "Intron length"), 600)
    await hand.caption("Every junction along the genome, its support on the y axis", hold=300)
    await _scroll_to(page, _section(page, "Junction landscape"), offset=10, smooth=True, ms=1400)
    manhattan = _tile(page, "Junction support along the genome")
    mb = await manhattan.bounding_box()
    for fx in (0.2, 0.45, 0.7):
        await hand.glide(mb["x"] + mb["width"] * fx, mb["y"] + mb["height"] * 0.45)
        await page.wait_for_timeout(450)
    await hand.caption("The busiest loci as a sashimi: one lane per sample", hold=300)
    await _scroll_to(page, section, offset=10, smooth=True, ms=1400)
    cb = await arcs.locator("canvas").first.bounding_box()
    await hand.glide(cb["x"] + cb["width"] * 0.5, cb["y"] + cb["height"] * 0.25)
    await page.wait_for_timeout(700)
    await hand.caption("Arcs as wide as their reads, the exon model and the genes under them")
    await hand.glide(cb["x"] + cb["width"] * 0.5, cb["y"] + cb["height"] * 0.85)
    await page.wait_for_timeout(600)
    await hand.caption("Below, the reads: coverage, alignments and their own arcs", hold=500)
    await _look(page, hand, tile.locator('[data-testid="jbrowse-header"]'), 600)
    for i in range(1, min(n, 3)):
        await hand.caption("Pick another locus: the reads follow", hold=400)
        await hand.click(locus)
        await page.wait_for_timeout(350)
        await hand.click(page.get_by_role("option").nth(i))
        await _beat(page, 2500)
        await hand.zoom(tile, scale=1.25, hold=1500)
    await hand.caption("Zoom the sashimi: the browser keeps its window", hold=300)
    cb = await arcs.locator("canvas").first.bounding_box()
    await hand.glide(cb["x"] + cb["width"] * 0.5, cb["y"] + cb["height"] * 0.4)
    for _ in range(4):
        await page.mouse.wheel(0, -240)
        await page.wait_for_timeout(180)
    await _beat(page, 2500)
    await hand.zoom(tile, scale=1.25, hold=1500)
    await hand.caption("Every junction in the table, to sort and pick", hold=300)
    await _scroll_to(page, _section(page, "Junction table"), offset=10, smooth=True, ms=1400)
    await table.locator(".ag-row").first.wait_for(timeout=30_000)
    await _look(page, hand, table.locator(".ag-header-cell").nth(3), 700)
    await _look(page, hand, table.locator(".ag-center-cols-container .ag-row").nth(2), 900)
    await hand.caption(None)


async def cnv_profile(page, hand: Hand, rec: Recorder, ids: dict[str, str]) -> None:
    """nf-core/sarek Copy number: zoom the CNV profile on a gain, then open its reads."""
    await _open(page, BASE, ids["sarek_cnv"])
    await _close_filters(page)
    section = _section(page, "One tumour in detail")
    await _scroll_to(page, section, offset=10)
    tile = page.locator(".react-grid-item").filter(has_text="Copy-number profile of one sample")
    if not await tile.count():
        await section.click()
    tile = tile.first
    await tile.locator(".js-plotly-plot").first.wait_for(timeout=60_000)
    await _settle(page, 4000)
    chrom = tile.get_by_label("Chromosome").first
    await _arrive(page, rec, section)
    await hand.caption("Bins and CNVkit segments, gains in red and losses in blue", hold=1100)
    await hand.caption("Zoom on a chromosome from the controls", hold=400)
    await hand.click(chrom)
    await page.wait_for_timeout(350)
    await hand.click(page.get_by_role("option", name="chr8", exact=True))
    await _beat(page, 2500)
    await hand.caption("Box-zoom on a few megabases of the gain", hold=500)
    plot = tile.locator(".nsewdrag").first
    pb = await plot.bounding_box()
    y = pb["y"] + pb["height"] * 0.35
    await hand.drag(pb["x"] + pb["width"] * 0.60, y, pb["x"] + pb["width"] * 0.62, y, steps=12)
    await _beat(page, 1500)
    await hand.zoom(tile, scale=1.25, hold=1300)
    await hand.caption("Open in genome browser: the Locus tab opens on that window", hold=500)
    button = await _tile_button(page, tile, None, "Open in genome browser")
    await hand.click(button)
    browser = await _ff(page, _browser(page))
    await _scroll_to(page, browser, offset=-380)
    await hand.caption("Depth per sample on the navigator, the calls and reads in the browser")
    await _beat(page, 4000)
    await hand.zoom(browser, scale=1.25, hold=1600)
    await hand.caption(None)


async def _beat(page, ms: int = 3000) -> None:
    """A wait for data while filming, fast-forwarded in the clip: ``_settle`` can
    wait half a minute for an idle network, which a clip would show as dead time."""

    async def wait() -> None:
        await page.wait_for_timeout(ms)
        busy = page.locator("text=/Downloading|Loading\\.\\.|Processing alignments/")
        for _ in range(12):
            if not await busy.count():
                break
            await page.wait_for_timeout(1000)

    await _ff(page, wait())
    # The result, at the interaction's own pace.
    await page.wait_for_timeout(700)


async def _find_saturated(page, x: float, y: float, w: float, h: float):
    """Page coordinates of the first strongly coloured pixel run in a box: a
    variant, whatever its effect colour (the reads and labels are grey or dark)."""
    import io

    from PIL import Image

    png = await page.screenshot(clip={"x": x, "y": y, "width": w, "height": h})
    img = Image.open(io.BytesIO(png)).convert("RGB")
    sx, sy = img.width / w, img.height / h
    for py in range(img.height):
        for px in range(img.width):
            r, g, b = img.getpixel((px, py))
            if max(r, g, b) - min(r, g, b) > 90:
                return x + (px + 2) / sx, y + (py + 3) / sy
    return None


async def _center(locator) -> tuple[float, float]:
    await locator.scroll_into_view_if_needed()
    b = await locator.bounding_box()
    if b is None:
        raise RuntimeError(f"not visible: {locator}")
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


SCENARIOS: dict[str, tuple[Scenario, tuple[str, ...]]] = {
    "table_to_browser": (table_to_browser, ("riboseq",)),
    "browser_to_dashboard": (browser_to_dashboard, ("viralrecon",)),
    "genomespy_jbrowse": (genomespy_jbrowse, ("nascent",)),
    "chipseq_peaks": (_peaks("chipseq"), ("chipseq",)),
    "atacseq_peaks": (_peaks("atacseq"), ("atacseq",)),
    "cutandrun_peaks": (_peaks("cutandrun"), ("cutandrun",)),
    "ucsc_and_tracks": (ucsc_and_tracks, ("viralrecon",)),
    "ucsc_builder": (ucsc_builder, ("viralrecon",)),
    "ranked_rows": (ranked_rows, ("raredisease",)),
    "fusion_chord": (fusion_chord, ("rnafusion",)),
    "sashimi_junctions": (sashimi_junctions, ("rnafusion_splice",)),
    "cnv_profile": (cnv_profile, ("sarek_cnv",)),
}

# Per clip: a taller view, so linked tiles share the frame, and a playback speed.
CLIP_OPTIONS: dict[str, dict[str, float]] = {
    "table_to_browser": {"height": 1400},
    "browser_to_dashboard": {"height": 1400},
    "genomespy_jbrowse": {"height": 1400},
    "chipseq_peaks": {"height": 1400},
    "atacseq_peaks": {"height": 1400},
    "cutandrun_peaks": {"height": 1400},
    "ranked_rows": {"height": 1400},
    "fusion_chord": {"height": 1400, "speed": 1.25},
    "sashimi_junctions": {"height": 1400, "speed": 1.5},
    "cnv_profile": {"height": 1400},
}

BASE = "http://127.0.0.1:8058"
# The nascent lanes are framed on a responsive gene's neighbourhood (CHAC1 on
# chr15), then brushed from one fraction of their width to the other.
LANES_LOCUS = "chr15:36,000,000-46,000,000"
BRUSH = (0.35, 0.65)
# Peak pipelines: the lanes widened this far on both sides of the browser's
# best call, then brushed over this middle fraction of their width.
PEAK_LANES_SPAN = 1_500_000
PEAK_BRUSH = (0.47, 0.53)


async def run(out: Path, ids: dict[str, str], only: set[str] | None, args) -> None:
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        launch = {"headless": not args.headed}
        if path := _chromium_path():
            launch["executable_path"] = path
        browser = await p.chromium.launch(**launch)
        for name, (fn, needs) in SCENARIOS.items():
            if only and name not in only:
                continue
            missing = [n for n in needs if n not in ids]
            if missing:
                print(f"- {name}: skipped, no --dashboard {'/'.join(missing)}=<id>")
                continue
            opts = CLIP_OPTIONS.get(name, {})
            ctx = await browser.new_context(
                viewport={**VIEWPORT, "height": int(opts.get("height", VIEWPORT["height"]))},
                device_scale_factor=SCALE,
                color_scheme=args.scheme,
                ignore_https_errors=args.insecure,
            )
            await ctx.add_init_script(OVERLAY_JS)
            page = await ctx.new_page()
            rec = Recorder(page)
            global _REC
            _REC = rec
            try:
                await fn(page, Hand(page), rec, ids)
                await rec.stop()
                rec.encode(out / f"{name}.mp4", args.max_still, args.width, opts.get("speed", 1))
                size = (out / f"{name}.mp4").stat().st_size / 1e6
                print(f"✓ {out / f'{name}.mp4'} ({len(rec.frames)} frames, {size:.1f} MB)")
            except Exception as exc:  # noqa: BLE001 - report and go on with the rest
                print(f"✗ {name}: {exc}")
                await page.screenshot(path=str(out / f"_failed_{name}.png"))
            await ctx.close()
        await browser.close()


def main() -> None:
    global BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default=BASE)
    ap.add_argument("--out", type=Path, default=Path("docs/videos/jbrowse"))
    ap.add_argument(
        "--dashboard",
        action="append",
        default=[],
        metavar="NAME=DASHBOARD_ID",
        help="tab ids: viralrecon, riboseq, chipseq, atacseq, cutandrun, nascent, raredisease, rnafusion, rnafusion_splice, sarek_cnv",
    )
    ap.add_argument("--only", action="append", help="scenario name (repeatable)")
    ap.add_argument("--width", type=int, default=1600, help="output width in pixels")
    ap.add_argument("--max-still", type=float, default=1.2, help="longest frame hold (s)")
    ap.add_argument("--scheme", choices=["light", "dark"], default="light")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--insecure", action="store_true", help="accept TLS-intercepting proxies")
    args = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is required")
    BASE = args.base_url.rstrip("/")
    ids = dict(spec.partition("=")[::2] for spec in args.dashboard)
    asyncio.run(run(args.out, ids, set(args.only) if args.only else None, args))


if __name__ == "__main__":
    main()
