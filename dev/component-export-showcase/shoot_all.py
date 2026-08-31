#!/usr/bin/env python3
"""Screenshot every showcase page, for the PR.

`shoot_site.py` sweeps the gallery's three delivery modes and `shoot_page.py`
takes one route; this takes the whole set, which is what a PR needs.

Playwright rather than headless Chrome flags, for two reasons that matter here:

* it can *scroll*, and the pages lazy-mount panels on intersection, so a
  fixed-viewport capture of a tall page photographs placeholders;
* it can wait for a real condition (`.js-plotly-plot` count settling) instead of
  a virtual-time budget, so a slow advanced-viz render is not caught half-drawn.

Captures are *stitched from viewport shots* rather than taken with
`full_page=True`. Chromium composites a full-page capture from the layout tree
and leaves cross-origin iframes blank in it, which on these pages means the
embedded Depictio control — the thing worth showing — photographs as an empty
box. A viewport shot is a real paint and contains it.

    python shoot_all.py [--port 8899] [--only qc-report gallery]
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

#: Overlap between stitched viewport captures, so a sticky header does not slice
#: a figure in half at the seam.
STITCH_OVERLAP = 60

#: A sticky or fixed element re-paints at the top of every viewport capture, so a
#: stitched page grows a copy of the site header at each seam. Demoting just those
#: elements to `static` for the duration of the capture puts each one in the image
#: exactly once, where it sits in the document.
UNSTICK = """() => {
  for (const el of document.querySelectorAll('*')) {
    const pos = getComputedStyle(el).position;
    if (pos === 'sticky' || pos === 'fixed') {
      el.dataset.shotPosition = el.style.position || '';
      el.style.position = 'static';
    }
  }
}"""

OUT_DIR = Path(__file__).resolve().parent / "screenshots"

#: (slug, route, note). Ordered as the story reads, not as the nav lists them.
PAGES = [
    ("01-landing", "/", "the three integration shapes, stated"),
    ("02-qc-report", "/qc-report", "a real report page built from JSON specs"),
    ("03-gallery", "/gallery", "one card per component type, all three modes"),
    ("04-report", "/report", "host-built controls + Depictio's own control, framed"),
    ("05-versioning", "/versioning", "ETag/304, version pinning, ?controls="),
    ("06-limited", "/example-limited", "where the JSON path stops, and why"),
    ("07-selftest", "/selftest", "every filter fetched twice and compared"),
]


def settle(page, timeout_ms: int = 45_000) -> None:
    """Scroll the page and wait for the figure count to stop changing.

    Panels mount on intersection, so a page that is never scrolled never draws
    most of itself. Waiting on a stable count beats a fixed sleep: the fast pages
    finish early and the slow ones are not truncated.
    """
    page.wait_for_timeout(2500)
    y, previous, stable = 0, -1, 0
    elapsed = 0
    while elapsed < timeout_ms:
        height = page.evaluate("() => document.body.scrollHeight")
        page.evaluate(f"() => window.scrollTo(0, {y})")
        page.wait_for_timeout(1200)
        elapsed += 1200
        y = 0 if y >= height else y + 700
        count = page.evaluate(
            "() => document.querySelectorAll('.js-plotly-plot, iframe').length"
        )
        stable = stable + 1 if count == previous else 0
        previous = count
        # Two stable samples after a full pass is enough; anything still loading
        # would have changed the count.
        if stable >= 3 and y == 0:
            break
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(2000)


def capture(page, out: Path, viewport_height: int) -> None:
    """Screenshot the whole page by stitching real viewport paints.

    `full_page=True` would be one call, but Chromium renders that capture from
    the layout tree and omits cross-origin iframe content — exactly the embedded
    Depictio control these pages exist to show. So: scroll, shoot, repeat, and
    paste the strips together.
    """
    from PIL import Image

    # Demote sticky/fixed elements first: they would otherwise appear once per
    # strip. Done after `settle()`, so nothing that depends on scroll position
    # for mounting is disturbed.
    page.evaluate(UNSTICK)
    page.wait_for_timeout(500)

    total = page.evaluate("() => document.body.scrollHeight")
    step = viewport_height - STITCH_OVERLAP
    offsets = list(range(0, max(total - viewport_height, 0) + step, step))
    # Never scroll past the bottom, or the last strip repeats content.
    offsets = sorted({min(y, max(total - viewport_height, 0)) for y in offsets})

    canvas = Image.new("RGB", (page.viewport_size["width"], total), "white")
    for y in offsets:
        page.evaluate(f"() => window.scrollTo(0, {y})")
        page.wait_for_timeout(700)
        strip = Image.open(io.BytesIO(page.screenshot()))
        canvas.paste(strip, (0, y))
    canvas.save(out)


def main() -> int:
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()

    base = f"http://localhost:{args.port}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = [p for p in PAGES if not args.only or p[0] in args.only or p[1] in args.only]

    print(f"site  {base}\nout   {OUT_DIR}\n")
    failures = 0
    viewport_height = 1000
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--enable-unsafe-swiftshader"])
        for slug, route, note in wanted:
            page = browser.new_page(viewport={"width": 1600, "height": viewport_height})
            out = OUT_DIR / f"{slug}.png"
            try:
                page.goto(base + route, wait_until="load", timeout=120_000)
                settle(page)
                capture(page, out, viewport_height)
                size = out.stat().st_size / 1024
                figures = page.evaluate("() => document.querySelectorAll('.js-plotly-plot').length")
                frames = page.evaluate("() => document.querySelectorAll('iframe').length")
                print(f"  {slug:16} {size:7.0f} KB   {figures:2d} figures, {frames} frames   {note}")
            except Exception as exc:
                print(f"  {slug:16} FAILED  {type(exc).__name__}: {exc}")
                failures += 1
            finally:
                page.close()
        browser.close()

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
