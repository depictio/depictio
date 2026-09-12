#!/usr/bin/env python3
"""Capture one screenshot per tab of a shipped template dashboard.

The nf-core templates each ship `docs/dashboards.md`, a walkthrough that reads far
better next to a picture of the tab it describes. This drives the React viewer over a
locally ingested template project and writes `docs/screenshots/<tab-slug>.png` beside
that walkthrough.

Prerequisites:
    - the stack that ingested the template is running, and the API has been restarted
      since the last catalog tool was added (`load_catalog_entries` is lru_cached, so a
      tool added while the API ran leaves `viz_kind` null and the tile renders as
      "Unknown advanced viz kind")
    - the dashboards on the server are up to date with the YAML (`depictio dashboard
      import <base.yaml> --overwrite`)

Usage:
    python dev/playwright_debug/template_dashboard_shots.py \\
        --template nf-core/atacseq/1.2.2 \\
        --viewer-url http://localhost:5601 --api-url http://localhost:8101

    # every template that has a docs/ directory
    python dev/playwright_debug/template_dashboard_shots.py --all ...
"""

from __future__ import annotations

import asyncio
import json
import re
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

PROJECTS_DIR = REPO_ROOT / "depictio" / "projects"
ADMIN_CONFIG_PATH = REPO_ROOT / "depictio" / ".depictio" / "admin_config.yaml"

app = typer.Typer(add_completion=False)


def slugify(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def token_payload() -> str:
    """The JSON blob the SPA expects in localStorage, straight from admin_config."""
    if not ADMIN_CONFIG_PATH.exists():
        raise typer.BadParameter(f"admin_config.yaml not found at {ADMIN_CONFIG_PATH}")
    cfg = yaml.safe_load(ADMIN_CONFIG_PATH.read_text())
    return json.dumps(cfg["user"]["token"] if "user" in cfg else cfg)


def api_get(api_url: str, path: str, token: str):
    req = urllib.request.Request(
        f"{api_url}/depictio/api/v1{path}", headers={"Authorization": f"Bearer {token}"}
    )
    return json.load(urllib.request.urlopen(req))


def resolve_dashboard(api_url: str, token: str, project_tag: str) -> str:
    """The dashboard id for a template, matched on the project name its YAML declares."""
    projects = api_get(api_url, "/projects/get/all", token)
    by_name = {p.get("name"): (p.get("_id") or p.get("id")) for p in projects}
    if project_tag not in by_name:
        raise typer.BadParameter(
            f"no project named {project_tag!r} on {api_url}; ingest the template first"
        )
    pid = by_name[project_tag]
    dashboards = [
        d for d in api_get(api_url, "/dashboards/list", token) if d.get("project_id") == pid
    ]
    if not dashboards:
        raise typer.BadParameter(f"project {project_tag!r} has no dashboard")
    return dashboards[0]["dashboard_id"]


def templates_with_docs() -> list[str]:
    out = []
    for docs in sorted(PROJECTS_DIR.glob("nf-core/*/*/docs")):
        version_dir = docs.parent
        if (version_dir / "dashboards" / "base.yaml").exists():
            out.append(str(version_dir.relative_to(PROJECTS_DIR)))
    return out


def shrink_png(path: Path) -> None:
    """Quantise a capture to a 256-colour palette.

    A full tab at 1680 px wide runs to a megabyte of truecolour PNG, and these live in
    the repo next to the walkthrough that embeds them. Flat UI screenshots quantise
    without a visible difference, which is worth roughly a two-thirds saving.
    """
    try:
        from PIL import Image
    except ImportError:  # optimisation only, never a reason to lose the capture
        return
    with Image.open(path) as im:
        im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(
            path, optimize=True
        )


async def shoot_tabs(
    page: Page, out_dir: Path, width: int, height_hint: int, max_height: int, settle_ms: int
) -> list[Path]:
    """One capture per tab, in the order the tab bar shows them."""
    written: list[Path] = []
    labels = [t.strip() for t in await page.locator('[role="tab"]').all_inner_texts()]
    labels = [t for t in labels if t]
    typer.echo(f"    tabs: {labels}")
    for i, label in enumerate(labels):
        if i:
            # The tab bar sits in a sticky header, so a click attempted from a
            # scrolled position reports "element is outside of the viewport" and
            # retries until it times out. Go back to the top first, and fall back to
            # a dispatched event if the strip is still mid-animation.
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(400)
            tab = page.locator('[role="tab"]', has_text=re.compile(rf"^{re.escape(label)}$")).first
            await tab.scroll_into_view_if_needed()
            try:
                await tab.click(timeout=10_000)
            except Exception:
                await tab.dispatch_event("click")
            await page.wait_for_timeout(settle_ms)
        await wait_for_dashboard_content(page)
        await wait_for_plotly_drawn(page, timeout_ms=8_000)
        await dismiss_notifications(page)
        # The page itself never scrolls: `[data-testid="dashboard-content"]` is the
        # scroller, so `document.body.scrollHeight` is always one viewport and a
        # full_page capture would silently show only the top of the tab. Grow the
        # viewport by the container's hidden overflow instead, which is what makes
        # the whole tab paint, then clip to the ceiling the caller asked for.
        for _ in range(3):
            over = await page.evaluate(
                "() => { const e = document.querySelector('[data-testid=\"dashboard-content\"]');"
                " return e ? e.scrollHeight - e.clientHeight : 0; }"
            )
            if over <= 4:
                break
            size = page.viewport_size or {"width": width, "height": height_hint}
            grown = min(size["height"] + over, max_height)
            if grown <= size["height"]:
                break
            await page.set_viewport_size({"width": width, "height": grown})
            await page.wait_for_timeout(1_200)
        await wait_for_plotly_drawn(page, timeout_ms=6_000)
        await page.evaluate(
            "() => { const e = document.querySelector('[data-testid=\"dashboard-content\"]');"
            " if (e) e.scrollTop = 0; window.scrollTo(0, 0); }"
        )
        await page.wait_for_timeout(600)
        path = out_dir / f"{slugify(label)}.png"
        await page.screenshot(path=str(path))
        shrink_png(path)
        shot_h = (page.viewport_size or {}).get("height")
        await page.set_viewport_size({"width": width, "height": height_hint})
        await page.wait_for_timeout(700)
        written.append(path)
        typer.echo(f"    ✓ {path.name} ({shot_h}px)")
    return written


async def run_one(
    template: str,
    viewer_url: str,
    api_url: str,
    theme: str,
    width: int,
    height: int,
    max_height: int,
    settle_ms: int,
    headless: bool,
) -> None:
    version_dir = PROJECTS_DIR / template
    base = version_dir / "dashboards" / "base.yaml"
    doc = yaml.safe_load(base.read_text())
    project_tag = doc["main_dashboard"]["project_tag"]
    payload = token_payload()
    token = json.loads(payload).get("access_token")
    dashboard_id = resolve_dashboard(api_url, token, project_tag)
    out_dir = version_dir / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"  {template} -> {project_tag} / {dashboard_id}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": width, "height": height})
        # Seed auth and theme before first paint: the SPA reads both in initialisers.
        await context.add_init_script(build_localstorage_init_script(payload, theme))
        page = await context.new_page()
        await page.goto(f"{viewer_url}/dashboard/{dashboard_id}", wait_until="domcontentloaded")
        await page.wait_for_timeout(settle_ms * 2)
        await shoot_tabs(page, out_dir, width, height, max_height, settle_ms)
        await browser.close()


@app.command()
def main(
    template: list[str] = typer.Option([], "--template", help="nf-core/<pipeline>/<version>"),
    every: bool = typer.Option(False, "--all", help="every template that ships a docs/ dir"),
    viewer_url: str = typer.Option("http://localhost:5601"),
    api_url: str = typer.Option("http://localhost:8101"),
    theme: str = typer.Option("light"),
    width: int = typer.Option(1680),
    height: int = typer.Option(1250),
    max_height: int = typer.Option(3200, help="clip taller tabs to this many pixels"),
    settle_ms: int = typer.Option(3500, help="pause after navigation and each tab click"),
    headless: bool = typer.Option(True, "--headless/--headed"),
) -> None:
    names = templates_with_docs() if every else list(template)
    if not names:
        raise typer.BadParameter("pass --template <id> at least once, or --all")
    typer.echo(f"capturing {len(names)} template dashboards")
    for name in names:
        try:
            asyncio.run(
                run_one(
                    name, viewer_url, api_url, theme, width, height, max_height, settle_ms, headless
                )
            )
        except Exception as exc:  # one bad template must not sink the batch
            typer.echo(f"  ✗ {name}: {exc}", err=True)


if __name__ == "__main__":
    app()
