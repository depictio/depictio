#!/usr/bin/env python3
"""Capture documentation screenshots via Playwright against the React (Beta) viewer.

Prerequisites:
    - Dev stack running: `docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up`
    - Vite dev server up on http://localhost:5173 (`pnpm -C depictio/viewer dev`)
    - depictio/.depictio/admin_config.yaml present (created on first stack boot)

Usage:
    python dev/playwright_debug/docs_screenshots.py list
    python dev/playwright_debug/docs_screenshots.py run --version v0.12 \\
        --project-id 646b0f3c1e4a2d7f8e5b8c9a \\
        --shot link_create_modal --shot manage_dc_modal --shot create_dc_modal_table

Shots register themselves in REGISTRY; future releases add new shots in this file
and select them via repeated --shot flags. No release version is hardcoded outside
that single --version flag.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import typer
import yaml
from playwright.async_api import Page, async_playwright

app = typer.Typer(add_completion=False, no_args_is_help=True)

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_CONFIG_PATH = REPO_ROOT / "depictio" / ".depictio" / "admin_config.yaml"
DEFAULT_DOCS_IMAGE_ROOT = REPO_ROOT.parent / "depictio-docs" / "docs" / "images"


@dataclass(frozen=True)
class ShotContext:
    page: Page
    viewer_url: str
    project_id: str
    dashboard_id: str
    output_dir: Path


ShotFn = Callable[[ShotContext], Awaitable[None]]
REGISTRY: dict[str, ShotFn] = {}


def register(name: str) -> Callable[[ShotFn], ShotFn]:
    def deco(fn: ShotFn) -> ShotFn:
        REGISTRY[name] = fn
        return fn

    return deco


def _load_token_payload() -> str:
    """Read admin_config.yaml and emit the JSON string the SPA expects in
    localStorage['local-store']. Mirrors the structure produced by
    `_get_admin_token_localstorage_payload()` in the API codebase.
    """
    if not ADMIN_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"admin_config.yaml not found at {ADMIN_CONFIG_PATH}. "
            "Boot the dev stack at least once to generate it."
        )
    with open(ADMIN_CONFIG_PATH) as fh:
        config = yaml.safe_load(fh)
    token_info = config.get("user", {}).get("token", {})
    payload = {
        "_id": str(token_info.get("id")),
        "user_id": str(token_info.get("user_id")),
        "logged_in": True,
        "expire_datetime": token_info.get("expire_datetime"),
        "created_at": token_info.get("created_at"),
        "refresh_expire_datetime": token_info.get("refresh_expire_datetime"),
        "access_token": token_info.get("access_token"),
        "refresh_token": token_info.get("refresh_token"),
        "name": token_info.get("name"),
        "token_lifetime": token_info.get("token_lifetime"),
        "token_type": token_info.get("token_type"),
    }
    return json.dumps({k: v for k, v in payload.items() if v is not None})


async def _shot(ctx: ShotContext, selector: str, name: str) -> None:
    locator = ctx.page.locator(selector).first
    await locator.wait_for(state="visible", timeout=15_000)
    # Brief settle for fonts / icons rendering inside the modal.
    await ctx.page.wait_for_timeout(400)
    target = ctx.output_dir / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    await locator.screenshot(path=str(target))
    typer.echo(f"  → {target.relative_to(REPO_ROOT.parent)}")


async def _page_shot(ctx: ShotContext, route: str, name: str, wait_ms: int = 1200) -> None:
    """Full-viewport capture of a React Beta page after navigation + settle.

    Uses `domcontentloaded` (not `networkidle`) because dashboard pages keep a
    realtime websocket open — networkidle never resolves there. wait_ms covers
    the time between DOMContentLoaded and grid/chart settle.

    Also dismisses any visible Mantine notifications before screenshotting —
    some endpoints (e.g. /links/{project_id}) reject the single-user-mode
    anonymous token and surface red error toasts that would otherwise clutter
    the shot.
    """
    await ctx.page.goto(f"{ctx.viewer_url}{route}", wait_until="domcontentloaded")
    await ctx.page.wait_for_timeout(wait_ms)
    await ctx.page.evaluate(
        """() => {
            document.querySelectorAll(
                '[data-mantine-notification-root], .mantine-Notifications-notification, .mantine-Notification-root'
            ).forEach(n => n.remove());
        }"""
    )
    target = ctx.output_dir / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    await ctx.page.screenshot(path=str(target), full_page=False)
    typer.echo(f"  → {target.relative_to(REPO_ROOT.parent)}")


# ---- Shot registry --------------------------------------------------------


@register("link_create_modal")
async def _link_create(ctx: ShotContext) -> None:
    """Cross-DC link Create/Edit modal with resolver picker."""
    await ctx.page.goto(f"{ctx.viewer_url}/projects-beta/{ctx.project_id}")
    await ctx.page.get_by_test_id("add-link-btn").click()
    await _shot(ctx, '[data-testid="link-edit-modal"]', "link_create_modal")


@register("manage_dc_modal")
async def _manage_dc(ctx: ShotContext) -> None:
    """Manage Data Collection modal (Modify / Clear tabs)."""
    await ctx.page.goto(f"{ctx.viewer_url}/projects-beta/{ctx.project_id}")
    await ctx.page.get_by_test_id("manage-dc-btn").first.click()
    await _shot(ctx, '[data-testid="manage-dc-modal"]', "manage_dc_modal")


@register("create_dc_modal_table")
async def _create_dc_table(ctx: ShotContext) -> None:
    """Create DC modal on the Table tab (where coordinates lat/lon detection lives)."""
    await ctx.page.goto(f"{ctx.viewer_url}/projects-beta/{ctx.project_id}")
    await ctx.page.get_by_test_id("create-dc-btn").click()
    # Tab is selected by default; click is a no-op safety in case order shifts.
    await ctx.page.get_by_role("tab", name="Table (CSV / TSV / Parquet)").click()
    await _shot(ctx, '[data-testid="create-dc-modal"]', "create_dc_modal_table")


# ---- Full-page React (Beta) page shots ------------------------------------
# Output to <version>/react-beta/ so they don't clash with legacy Dash images
# until the prose is rewritten to reference them.


def _rb(name: str) -> str:
    """Place page-level shots under a react-beta/ subdir within --version."""
    return f"react-beta/{name}"


@register("page_dashboards")
async def _page_dashboards(ctx: ShotContext) -> None:
    """React Beta /dashboards-beta landing — dashboard list."""
    await _page_shot(ctx, "/dashboards-beta", _rb("page_dashboards"))


@register("page_projects")
async def _page_projects(ctx: ShotContext) -> None:
    """React Beta /projects-beta — projects list."""
    await _page_shot(ctx, "/projects-beta", _rb("page_projects"))


@register("page_project_detail")
async def _page_project_detail(ctx: ShotContext) -> None:
    """React Beta /projects-beta/{id} — DC list + cross-DC links + joins graph."""
    await _page_shot(ctx, f"/projects-beta/{ctx.project_id}", _rb("page_project_detail"))


@register("page_profile")
async def _page_profile(ctx: ShotContext) -> None:
    """React Beta /profile-beta — user profile."""
    await _page_shot(ctx, "/profile-beta", _rb("page_profile"))


@register("page_about")
async def _page_about(ctx: ShotContext) -> None:
    """React Beta /about-beta — about page."""
    await _page_shot(ctx, "/about-beta", _rb("page_about"))


@register("page_admin")
async def _page_admin(ctx: ShotContext) -> None:
    """React Beta /admin-beta — admin users page (admin role required)."""
    await _page_shot(ctx, "/admin-beta", _rb("page_admin"))


@register("page_cli_agents")
async def _page_cli_agents(ctx: ShotContext) -> None:
    """React Beta /cli-agents-beta — CLI tokens / agents."""
    await _page_shot(ctx, "/cli-agents-beta", _rb("page_cli_agents"))


@register("page_dashboard_viewer")
async def _page_dashboard_viewer(ctx: ShotContext) -> None:
    """React Beta /dashboard-beta/{id} — read-only dashboard view, settles after grid render."""
    await _page_shot(
        ctx, f"/dashboard-beta/{ctx.dashboard_id}", _rb("page_dashboard_viewer"), wait_ms=9_000
    )


@register("page_dashboard_editor")
async def _page_dashboard_editor(ctx: ShotContext) -> None:
    """React Beta /dashboard-beta-edit/{id} — design-mode editor."""
    await _page_shot(
        ctx,
        f"/dashboard-beta-edit/{ctx.dashboard_id}",
        _rb("page_dashboard_editor"),
        wait_ms=4_000,
    )


# ---- Workflow shots (click a trigger, screenshot the resulting modal) -----


@register("cli_config_create_modal")
async def _cli_config_create(ctx: ShotContext) -> None:
    """Add New CLI Configuration modal opened on /cli-agents-beta."""
    await ctx.page.goto(f"{ctx.viewer_url}/cli-agents-beta", wait_until="domcontentloaded")
    await ctx.page.wait_for_timeout(800)
    await ctx.page.get_by_test_id("add-cli-config-btn").click()
    await _shot(ctx, '[data-testid="create-cli-token-modal"]', _rb("cli_config_create_modal"))


@register("new_dashboard_modal")
async def _new_dashboard(ctx: ShotContext) -> None:
    """+ New Dashboard modal opened on /dashboards-beta (project picker)."""
    await ctx.page.goto(f"{ctx.viewer_url}/dashboards-beta", wait_until="domcontentloaded")
    await ctx.page.wait_for_timeout(800)
    await ctx.page.get_by_test_id("new-dashboard-btn").click()
    await _shot(ctx, '[data-testid="create-dashboard-modal"]', _rb("new_dashboard_modal"))


# ---- CLI ------------------------------------------------------------------


@app.command(name="list")
def list_shots() -> None:
    """List available shot names."""
    for name in sorted(REGISTRY):
        typer.echo(name)


@app.command()
def run(
    version: str = typer.Option(
        ...,
        "--version",
        help="Release tag; used as output subdirectory (e.g. v0.12).",
    ),
    shot: list[str] = typer.Option(
        None,
        "--shot",
        help="Shot name(s) to capture; omit to run all.",
    ),
    viewer_url: str = typer.Option(
        "http://localhost:5173", "--viewer-url", help="React (Beta) Vite dev URL."
    ),
    project_id: str = typer.Option(
        ..., "--project-id", help="Project to drive (must contain MultiQC + table DCs)."
    ),
    dashboard_id: str = typer.Option(
        "6824cb3b89d2b72169309737",
        "--dashboard-id",
        help="Dashboard ID used by future dashboard-page shots.",
    ),
    output_root: Path = typer.Option(
        DEFAULT_DOCS_IMAGE_ROOT,
        "--output-root",
        help="Parent dir for <version>/ subfolders.",
    ),
    viewport_width: int = typer.Option(1440, "--viewport-width"),
    viewport_height: int = typer.Option(900, "--viewport-height"),
    headless: bool = typer.Option(True, "--headless/--headed"),
) -> None:
    """Capture one or more named shots into <output-root>/<version>/."""
    output_dir = output_root / version
    output_dir.mkdir(parents=True, exist_ok=True)
    names = shot or sorted(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise typer.BadParameter(
            f"Unknown shot(s): {unknown}. Run `list` to see available names."
        )
    typer.echo(f"📸 Capturing {len(names)} shot(s) into {output_dir}")
    asyncio.run(
        _run(
            names,
            viewer_url,
            project_id,
            dashboard_id,
            output_dir,
            viewport_width,
            viewport_height,
            headless,
        )
    )


async def _run(
    names: list[str],
    viewer_url: str,
    project_id: str,
    dashboard_id: str,
    output_dir: Path,
    vw: int,
    vh: int,
    headless: bool,
) -> None:
    token_payload = _load_token_payload()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": vw, "height": vh})
        # Inject the localStorage token via init script so it is present BEFORE
        # any page script runs — previously some early API calls (listProjectLinks,
        # listChildTabs) fired before our setItem and surfaced "401 invalid token"
        # toasts in the screenshot.
        await context.add_init_script(
            f"window.localStorage.setItem('local-store', {json.dumps(token_payload)});"
        )
        page = await context.new_page()
        ctx = ShotContext(
            page=page,
            viewer_url=viewer_url,
            project_id=project_id,
            dashboard_id=dashboard_id,
            output_dir=output_dir,
        )
        for name in names:
            typer.echo(f"• {name}")
            try:
                await REGISTRY[name](ctx)
            except Exception as exc:
                typer.echo(f"  ✗ {exc}", err=True)
        await browser.close()


if __name__ == "__main__":
    app()
