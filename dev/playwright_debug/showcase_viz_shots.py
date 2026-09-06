#!/usr/bin/env python3
"""Capture one high-resolution screenshot per tab of the advanced-viz showcase.

`template_dashboard_shots.py` is the twin of this script for the nf-core templates,
where one dashboard holds every tab and the tabs are clicked. The showcase is built
the other way round: each tab is its own dashboard document, linked to its siblings by
`parent_dashboard_tag`, so a tab is reachable directly at `/dashboard/<dashboard_id>`
and nothing has to be clicked. That is the whole reason this is a separate script.

Shots are taken at `device_scale_factor=2`, so a 1680 CSS-pixel viewport writes a
3360-pixel-wide PNG. They are not quantised: these are meant to be looked at closely.

Prerequisites:
    - the stack is running and the showcase project has been reseeded since the
      dashboards' YAML last changed, or the server still serves the previous tabs
    - the API has been restarted since any new advanced-viz kind was added, or the
      tile renders as "Unknown advanced viz kind"

Usage:
    python dev/playwright_debug/showcase_viz_shots.py --out /tmp/shots \\
        --viewer-url http://localhost:5601 --api-url http://localhost:8101

    # only the tabs added with the life-science kinds
    python dev/playwright_debug/showcase_viz_shots.py --tab profile --tab sashimi ...

    # also open each tile's Settings popover and shoot it on its own
    python dev/playwright_debug/showcase_viz_shots.py --out /tmp/shots --settings
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from pathlib import Path

import typer
import yaml
from playwright.async_api import Page, async_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from depictio.api.v1.services.screenshot_helpers import (  # noqa: E402
    build_localstorage_init_script,
    dismiss_notifications,
    wait_for_dashboard_content,
    wait_for_plotly_drawn,
)

SHOWCASE_DIR = REPO_ROOT / "depictio" / "projects" / "init" / "advanced_viz_showcase"
ADMIN_CONFIG_PATH = REPO_ROOT / "depictio" / ".depictio" / "admin_config.yaml"

app = typer.Typer(add_completion=False)


def token_payload() -> str:
    """The JSON blob the SPA expects in localStorage, straight from admin_config."""
    if not ADMIN_CONFIG_PATH.exists():
        raise typer.BadParameter(f"admin_config.yaml not found at {ADMIN_CONFIG_PATH}")
    cfg = yaml.safe_load(ADMIN_CONFIG_PATH.read_text())
    return json.dumps(cfg["user"]["token"] if "user" in cfg else cfg)


def tabs_from_yaml(wanted: list[str]) -> list[tuple[str, str, str]]:
    """`(slug, dashboard_id, title)` per showcase tab, read from the shipped YAML.

    The YAML is the source of truth for the id, not the server: a tab whose id the
    server does not know about is exactly the failure this script should surface,
    and resolving through the API would hide it behind a silent skip.
    """
    out: list[tuple[str, str, str]] = []
    for path in sorted((SHOWCASE_DIR / "dashboards").glob("*.yaml")):
        slug = path.stem
        if wanted and slug not in wanted:
            continue
        doc = yaml.safe_load(path.read_text())
        out.append((slug, str(doc["dashboard_id"]), str(doc.get("title") or slug)))
    missing = sorted(set(wanted) - {slug for slug, _, _ in out})
    if missing:
        raise typer.BadParameter(f"no dashboard YAML for: {', '.join(missing)}")
    return out


def api_get(api_url: str, path: str, token: str):
    req = urllib.request.Request(
        f"{api_url}/depictio/api/v1{path}", headers={"Authorization": f"Bearer {token}"}
    )
    return json.load(urllib.request.urlopen(req))


def server_knows(api_url: str, dashboard_id: str, token: str) -> bool:
    """Whether `/dashboard/<id>` will resolve, probed one id at a time.

    `/dashboards/list` is not the check to make: it answers with main dashboards
    only, so every showcase tab but `volcano` is absent from it by design, and a
    listing-based guard rejects the whole run. `/get/<id>` is what the viewer
    itself calls, so a 200 here is exactly the condition the shot needs.
    """
    try:
        api_get(api_url, f"/dashboards/get/{dashboard_id}", token)
        return True
    except urllib.error.HTTPError:
        return False


async def grow_to_fit(page: Page, width: int, max_height: int) -> None:
    """Expand the viewport until the dashboard scroller has nothing left to reveal.

    The page itself never scrolls: `[data-testid="dashboard-content"]` is the scroller,
    so `document.body.scrollHeight` is always one viewport tall and a `full_page`
    capture would silently show only the top of the tab. Growing the viewport by the
    container's hidden overflow is what puts the whole tab in one shot.
    """
    for _ in range(3):
        over = await page.evaluate(
            "() => { const e = document.querySelector('[data-testid=\"dashboard-content\"]');"
            " return e ? e.scrollHeight - e.clientHeight : 0; }"
        )
        if over <= 4:
            return
        size = page.viewport_size or {"width": width, "height": 1200}
        grown = min(size["height"] + over, max_height)
        if grown <= size["height"]:
            return
        await page.set_viewport_size({"width": width, "height": grown})
        await page.wait_for_timeout(1_200)


async def shoot_settings(page: Page, dest: Path) -> str | None:
    """Open the first tile's Settings popover and screenshot the dropdown alone.

    The dropdown is a portalled Mantine `Popover.Dropdown`, so it is not inside
    the tile and a tile-scoped clip would cut it off. Shooting the element gives
    the controls at full pixel density with no dashboard around them, which is
    what makes the panel legible at all: at tile scale it is a 380px sliver.
    """
    button = page.locator('[aria-label="Viz settings"]').first
    if await button.count() == 0:
        return None
    # Dispatched rather than clicked: the frame header sits above the Plotly
    # canvas, and Plotly's `svg-container` claims pointer events over the whole
    # tile, so an actual-pointer click is intercepted and retries forever.
    await button.evaluate("el => el.click()")
    # Scoped by the panel's own header, not by `.first`: every Mantine Select and
    # MultiSelect *inside* the panel is itself a Popover.Dropdown, mounted hidden
    # from the moment the panel opens, and those sort ahead of it in the DOM.
    dropdown = (
        page.locator(".mantine-Popover-dropdown")
        .filter(has=page.get_by_text("Viz controls", exact=True))
        .first
    )
    try:
        await dropdown.wait_for(state="visible", timeout=5_000)
    except Exception:
        return None
    # Selects inside the panel animate open/closed; let the layout settle so the
    # capture is not taken mid-transition.
    await page.wait_for_timeout(500)
    await dropdown.screenshot(path=str(dest))
    await page.keyboard.press("Escape")
    return str(dest)


@app.command()
def main(
    out: Path = typer.Option(..., help="Directory to write the PNGs into"),
    viewer_url: str = typer.Option("http://localhost:5601"),
    api_url: str = typer.Option("http://localhost:8101"),
    tab: list[str] = typer.Option([], help="Tab slug (repeatable); default is every tab"),
    width: int = typer.Option(1680, help="Viewport width in CSS pixels"),
    height: int = typer.Option(1200, help="Initial viewport height in CSS pixels"),
    max_height: int = typer.Option(4200, help="Cap on the grown viewport height"),
    scale: int = typer.Option(2, help="device_scale_factor; 2 doubles the pixel count"),
    theme: str = typer.Option("light"),
    settings: bool = typer.Option(
        False, help="Also shoot each tab's Settings popover as <slug>-settings.png"
    ),
) -> None:
    asyncio.run(
        _run(
            out, viewer_url, api_url, list(tab), width, height, max_height, scale, theme, settings
        )
    )


async def _run(
    out: Path,
    viewer_url: str,
    api_url: str,
    wanted: list[str],
    width: int,
    height: int,
    max_height: int,
    scale: int,
    theme: str,
    settings: bool,
) -> None:
    tabs = tabs_from_yaml(wanted)
    payload = token_payload()
    token = json.loads(payload)["access_token"]

    # Fail loudly and early rather than writing a directory of login screens.
    unknown = [(s, i) for s, i, _ in tabs if not server_knows(api_url, i, token)]
    if unknown:
        raise typer.BadParameter(
            "the server does not know these dashboards, reseed the showcase first: "
            + ", ".join(f"{s} ({i})" for s, i in unknown)
        )

    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(
            viewport={"width": width, "height": height}, device_scale_factor=scale
        )
        await context.add_init_script(build_localstorage_init_script(payload, theme))
        page = await context.new_page()
        for slug, dash_id, title in tabs:
            await page.set_viewport_size({"width": width, "height": height})
            await page.goto(f"{viewer_url}/dashboard/{dash_id}", wait_until="networkidle")
            await wait_for_dashboard_content(page)
            await wait_for_plotly_drawn(page, timeout_ms=20_000)
            await dismiss_notifications(page)
            await grow_to_fit(page, width, max_height)
            # One more settle: growing the viewport re-lays-out react-grid-layout and
            # Plotly resizes asynchronously behind it.
            await wait_for_plotly_drawn(page, timeout_ms=10_000)
            await page.wait_for_timeout(800)
            dest = out / f"{slug}.png"
            await page.screenshot(path=str(dest))
            kb = dest.stat().st_size // 1024
            print(f"{slug:22s} {title:34s} {kb:>6} KB  {dest}")
            if settings:
                panel = out / f"{slug}-settings.png"
                if await shoot_settings(page, panel):
                    print(f"{'':22s} {'settings popover':34s} "
                          f"{panel.stat().st_size // 1024:>6} KB  {panel}")
                else:
                    print(f"{'':22s} {'settings popover':34s} {'':>6}     no Settings button")
        await browser.close()


if __name__ == "__main__":
    app()
