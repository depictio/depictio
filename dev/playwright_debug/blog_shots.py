#!/usr/bin/env python3
"""Capture the blog's landing-page screenshots at high resolution.

Standalone on purpose: dev/playwright_debug/docs_screenshots.py imports the API
settings chain (pydantic -> colorlog -> ...), which needs the full app env. This
only needs playwright + pyyaml, so it runs in a throwaway venv against any
running stack.

    python dev/playwright_debug/blog_shots.py \
        --viewer-url http://localhost:5601 \
        --admin-config depictio/.depictio/admin_config.yaml \
        --out /tmp/shots --scale 2

Shots: /dashboards and /projects, the two landing pages the 1.0 blog post uses.
The docs copies under images/react/ are 1440x900 at 1x, which looks soft in a
blog body; --scale 2 renders the same layout at twice the pixel density.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

# Mirrors build_localstorage_init_script() in
# depictio/api/v1/services/screenshot_helpers.py. Kept in sync by hand; the
# shape matters (theme-store must be {"colorScheme": ...}, not a bare string,
# or MantineProvider silently falls back to light).
INIT_TEMPLATE = (
    "localStorage.setItem('local-store', {token});"
    "localStorage.setItem('theme-store', {theme});"
)

TOKEN_FIELDS = (
    "_id",
    "user_id",
    "expire_datetime",
    "created_at",
    "refresh_expire_datetime",
    "access_token",
    "refresh_token",
    "name",
    "token_lifetime",
    "token_type",
)


def token_payload(admin_config: Path) -> str:
    config = yaml.safe_load(admin_config.read_text())
    info = config.get("user", {}).get("token", {})
    payload: dict[str, object] = {"logged_in": True}
    for key in TOKEN_FIELDS:
        # admin_config stores the two id fields unprefixed.
        value = info.get({"_id": "id"}.get(key, key))
        if value is not None:
            payload[key] = str(value) if key in ("_id", "user_id") else value
    if "access_token" not in payload:
        raise SystemExit(f"no access_token in {admin_config}")
    return json.dumps(payload)


async def capture(
    viewer: str, token: str, out: Path, scale: float, wait_ms: int, width: int, height: int
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    init = INIT_TEMPLATE.format(
        token=json.dumps(token), theme=json.dumps(json.dumps({"colorScheme": "light"}))
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": width, "height": height}, device_scale_factor=scale
        )
        await context.add_init_script(init)
        page = await context.new_page()
        for route, name in (("/dashboards", "page_dashboards"), ("/projects", "page_projects")):
            await page.goto(f"{viewer}{route}", wait_until="domcontentloaded")
            await page.wait_for_timeout(wait_ms)
            await _strip_toasts(page)
            target = out / f"{name}.png"
            await page.screenshot(path=str(target))
            print(f"  -> {target}")
        await browser.close()


async def _strip_toasts(page) -> None:
    """Endpoints that reject the anonymous token raise red toasts; drop them."""
    await page.evaluate(
        "document.querySelectorAll('.mantine-Notification-root').forEach(n => n.remove())"
    )


async def capture_dashboard_scroll(
    viewer: str,
    token: str,
    out: Path,
    dashboard_id: str,
    prefix: str,
    scale: float,
    wait_ms: int,
    width: int,
    height: int,
    steps: int,
    overlap: float,
) -> None:
    """Walk one dashboard top to bottom, one viewport-sized frame per step.

    A dashboard tab is much taller than any sensible blog image, and a single
    full-page capture of it scales down to unreadable. Instead this emits a
    sequence of viewport frames with a little overlap, which can be shown as a
    strip or assembled into a gif.
    """
    out.mkdir(parents=True, exist_ok=True)
    init = INIT_TEMPLATE.format(
        token=json.dumps(token), theme=json.dumps(json.dumps({"colorScheme": "light"}))
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": width, "height": height}, device_scale_factor=scale
        )
        await context.add_init_script(init)
        page = await context.new_page()
        await page.goto(f"{viewer}/dashboard/{dashboard_id}", wait_until="domcontentloaded")
        # Charts stream in well after DOMContentLoaded; the grid must settle
        # before the first frame or the top of the page is still skeletons.
        await page.wait_for_timeout(wait_ms)
        await _strip_toasts(page)
        # The dashboard body scrolls inside an AppShell div, not on <body>, so
        # window.scrollTo is a no-op here. Find the tallest scrollable container
        # that is not an ag-grid viewport (those scroll their own rows).
        handle = await page.evaluate_handle(
            """() => {
              let best = null;
              document.querySelectorAll('div').forEach(el => {
                if (el.className && el.className.toString().includes('ag-')) return;
                if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 200) {
                  if (!best || el.scrollHeight > best.scrollHeight) best = el;
                }
              });
              return best || document.scrollingElement;
            }"""
        )
        metrics = await handle.evaluate("el => ({sh: el.scrollHeight, ch: el.clientHeight})")
        total, view = metrics["sh"], metrics["ch"]
        step_px = int(view * (1 - overlap))
        print(f"  scroller {total}px tall, viewport {view}px, stepping {step_px}px x {steps}")
        for i in range(steps):
            y = min(i * step_px, max(total - view, 0))
            await handle.evaluate(f"el => el.scrollTo(0, {y})")
            # Let lazy panels below the fold render before capturing.
            await page.wait_for_timeout(2_500)
            await _strip_toasts(page)
            target = out / f"{prefix}_{i + 1}.png"
            await page.screenshot(path=str(target))
            print(f"  -> {target} (y={y})")
            if y >= total - view:
                break
        await browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewer-url", default="http://localhost:5601")
    ap.add_argument("--admin-config", type=Path, default=Path("depictio/.depictio/admin_config.yaml"))
    ap.add_argument("--out", type=Path, default=Path("/tmp/shots"))
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--wait-ms", type=int, default=3500)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument(
        "--height",
        type=int,
        default=1100,
        help="Taller than the docs default of 900 so the dashboard cards fit "
        "without being clipped mid-card.",
    )
    ap.add_argument(
        "--dashboard-id",
        help="Capture this dashboard by scrolling instead of the landing pages.",
    )
    ap.add_argument("--prefix", default="dashboard", help="Filename prefix for scroll frames.")
    ap.add_argument("--steps", type=int, default=4, help="Max scroll frames.")
    ap.add_argument(
        "--overlap",
        type=float,
        default=0.12,
        help="Fraction of viewport repeated between frames, so nothing is cut at a seam.",
    )
    args = ap.parse_args()
    token = token_payload(args.admin_config)
    print(f"capturing from {args.viewer_url} at {args.scale}x")
    if args.dashboard_id:
        asyncio.run(
            capture_dashboard_scroll(
                args.viewer_url,
                token,
                args.out,
                args.dashboard_id,
                args.prefix,
                args.scale,
                args.wait_ms,
                args.width,
                args.height,
                args.steps,
                args.overlap,
            )
        )
    else:
        asyncio.run(
            capture(
                args.viewer_url,
                token,
                args.out,
                args.scale,
                args.wait_ms,
                args.width,
                args.height,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
