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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import typer
import yaml
from playwright.async_api import Page, async_playwright

# Repo-rooted import so the script runs from anywhere (e.g. via `python
# dev/playwright_debug/docs_screenshots.py ...`) without a packaged install.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depictio.api.v1.services.screenshot_helpers import (  # noqa: E402
    build_localstorage_init_script,
    dismiss_notifications,
    wait_for_theme_applied,
)

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
    theme: str = "light"
    #: Project name used to pick the ingestion row of a watcher-driven cycle.
    watch_project_name: str = "Watcher Demo"


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


async def _page_shot_current(ctx: ShotContext, name: str) -> None:
    """Full-viewport capture of the page as it currently stands (no navigation).

    For shots that first click through in-page UI (tabs, segmented controls,
    accordions) — the caller has already navigated and settled.
    """
    target = ctx.output_dir / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    await ctx.page.screenshot(path=str(target), full_page=False)
    typer.echo(f"  → {target.relative_to(REPO_ROOT.parent)}")


async def _page_shot(ctx: ShotContext, route: str, name: str, wait_ms: int = 1200) -> None:
    """Full-viewport capture of a React Beta page after navigation + settle.

    Uses `domcontentloaded` (not `networkidle`) because dashboard pages keep a
    realtime websocket open — networkidle never resolves there. wait_ms covers
    the time between DOMContentLoaded and grid/chart settle.
    """
    await ctx.page.goto(f"{ctx.viewer_url}{route}", wait_until="domcontentloaded")
    await ctx.page.wait_for_timeout(wait_ms)
    # Strip toasts — some endpoints (e.g. /links/{project_id}) reject the
    # single-user-mode anonymous token and surface red error toasts that
    # would otherwise sit on top of the shot.
    await dismiss_notifications(ctx.page)
    await _page_shot_current(ctx, name)


# ---- Shot registry --------------------------------------------------------


@register("link_create_modal")
async def _link_create(ctx: ShotContext) -> None:
    """Cross-DC link Create/Edit modal with resolver picker."""
    await ctx.page.goto(f"{ctx.viewer_url}/projects/{ctx.project_id}")
    await ctx.page.get_by_test_id("add-link-btn").click()
    await _shot(ctx, '[data-testid="link-edit-modal"]', "link_create_modal")


@register("manage_dc_modal")
async def _manage_dc(ctx: ShotContext) -> None:
    """Manage Data Collection modal (Modify / Clear tabs)."""
    await ctx.page.goto(f"{ctx.viewer_url}/projects/{ctx.project_id}")
    await ctx.page.get_by_test_id("manage-dc-btn").first.click()
    await _shot(ctx, '[data-testid="manage-dc-modal"]', "manage_dc_modal")


@register("create_dc_modal_table")
async def _create_dc_table(ctx: ShotContext) -> None:
    """Create DC modal on the Table tab (where coordinates lat/lon detection lives)."""
    await ctx.page.goto(f"{ctx.viewer_url}/projects/{ctx.project_id}")
    await ctx.page.get_by_test_id("create-dc-btn").click()
    # Tab is selected by default; click is a no-op safety in case order shifts.
    await ctx.page.get_by_role("tab", name="Table (CSV / TSV / Parquet)").click()
    await _shot(ctx, '[data-testid="create-dc-modal"]', "create_dc_modal_table")


# ---- Full-page React (Beta) page shots ------------------------------------
# Output to <version>/react/ so they don't clash with legacy Dash images
# until the prose is rewritten to reference them.


def _rb(name: str) -> str:
    """Place page-level shots under a react/ subdir within --version."""
    return f"react/{name}"


@register("page_dashboards")
async def _page_dashboards(ctx: ShotContext) -> None:
    """React Beta /dashboards landing — dashboard list."""
    await _page_shot(ctx, "/dashboards", _rb("page_dashboards"))


@register("page_projects")
async def _page_projects(ctx: ShotContext) -> None:
    """React Beta /projects — projects list."""
    await _page_shot(ctx, "/projects", _rb("page_projects"))


@register("page_project_detail")
async def _page_project_detail(ctx: ShotContext) -> None:
    """React Beta /projects/{id} — DC list + cross-DC links + joins graph."""
    await _page_shot(ctx, f"/projects/{ctx.project_id}", _rb("page_project_detail"))


@register("page_profile")
async def _page_profile(ctx: ShotContext) -> None:
    """React Beta /profile — user profile."""
    await _page_shot(ctx, "/profile", _rb("page_profile"))


@register("page_about")
async def _page_about(ctx: ShotContext) -> None:
    """React Beta /about — about page."""
    await _page_shot(ctx, "/about", _rb("page_about"))


@register("page_admin")
async def _page_admin(ctx: ShotContext) -> None:
    """React Beta /admin — admin users page (admin role required)."""
    await _page_shot(ctx, "/admin", _rb("page_admin"))


@register("page_cli_agents")
async def _page_cli_agents(ctx: ShotContext) -> None:
    """React Beta /cli-agents — CLI tokens / agents."""
    await _page_shot(ctx, "/cli-agents", _rb("page_cli_agents"))


@register("page_dashboard_viewer")
async def _page_dashboard_viewer(ctx: ShotContext) -> None:
    """React Beta /dashboard/{id} — read-only dashboard view, settles after grid render."""
    await _page_shot(
        ctx, f"/dashboard/{ctx.dashboard_id}", _rb("page_dashboard_viewer"), wait_ms=9_000
    )


@register("page_dashboard_editor")
async def _page_dashboard_editor(ctx: ShotContext) -> None:
    """React Beta /dashboard-edit/{id} — design-mode editor."""
    await _page_shot(
        ctx,
        f"/dashboard-edit/{ctx.dashboard_id}",
        _rb("page_dashboard_editor"),
        wait_ms=4_000,
    )


# ---- Workflow shots (click a trigger, screenshot the resulting modal) -----


@register("cli_config_create_modal")
async def _cli_config_create(ctx: ShotContext) -> None:
    """Add New CLI Configuration modal opened on /cli-agents."""
    await ctx.page.goto(f"{ctx.viewer_url}/cli-agents", wait_until="domcontentloaded")
    await ctx.page.wait_for_timeout(800)
    await ctx.page.get_by_test_id("add-cli-config-btn").click()
    await _shot(ctx, '[data-testid="create-cli-token-modal"]', _rb("cli_config_create_modal"))


@register("new_dashboard_modal")
async def _new_dashboard(ctx: ShotContext) -> None:
    """+ New Dashboard modal opened on /dashboards (project picker)."""
    await ctx.page.goto(f"{ctx.viewer_url}/dashboards", wait_until="domcontentloaded")
    await ctx.page.wait_for_timeout(800)
    await ctx.page.get_by_test_id("new-dashboard-btn").click()
    await _shot(ctx, '[data-testid="create-dashboard-modal"]', _rb("new_dashboard_modal"))


# ---- Admin "Log & Task" monitoring shots ----------------------------------
# Navigate to /admin, open the "Log & Task" tab, select a pane, and capture the
# full viewport (tab bar + segmented control give docs context). Filenames carry
# a _<theme> suffix so a light and a dark run produce the #only-light/#only-dark
# pair the docs site expects.


async def _open_monitoring(ctx: ShotContext, pane_label: str | None) -> None:
    """Open Admin → Log & Task and select `pane_label` (None keeps the default
    Tasks pane). Waits for the colour scheme + a pane row/empty-state to settle."""
    await ctx.page.goto(f"{ctx.viewer_url}/admin", wait_until="domcontentloaded")
    await ctx.page.wait_for_timeout(800)
    await wait_for_theme_applied(ctx.page, ctx.theme)
    # The admin page is a Mantine Tabs; the monitoring tab is labelled "Log & Task".
    await ctx.page.get_by_role("tab", name="Log & Task").click()
    await ctx.page.wait_for_timeout(600)
    if pane_label:
        # SegmentedControl labels are plain text buttons inside the panel.
        await ctx.page.get_by_text(pane_label, exact=True).click()
    # Give the pane's first poll time to resolve so the shot isn't a bare loader.
    await ctx.page.wait_for_timeout(1500)
    await dismiss_notifications(ctx.page)


@register("admin_monitoring_tasks")
async def _mon_tasks(ctx: ShotContext) -> None:
    """Log & Task → Tasks pane (Celery task ledger)."""
    await _open_monitoring(ctx, None)
    await _page_shot_current(ctx, _rb(f"admin_monitoring_tasks_{ctx.theme}"))


@register("admin_monitoring_ingestion")
async def _mon_ingestion(ctx: ShotContext) -> None:
    """Log & Task → Ingestion pane (CLI/UI ingestion runs)."""
    await _open_monitoring(ctx, "Ingestion")
    await _page_shot_current(ctx, _rb(f"admin_monitoring_ingestion_{ctx.theme}"))


@register("admin_monitoring_logs")
async def _mon_logs(ctx: ShotContext) -> None:
    """Log & Task → Logs pane (capped application-log collection)."""
    await _open_monitoring(ctx, "Logs")
    await _page_shot_current(ctx, _rb(f"admin_monitoring_logs_{ctx.theme}"))


@register("admin_monitoring_health")
async def _mon_health(ctx: ShotContext) -> None:
    """Log & Task → Health pane (Celery worker/broker health)."""
    await _open_monitoring(ctx, "Health")
    # Worker-inspect (Celery ping) lags the generic pane settle; wait for the
    # metric cards so the shot isn't a bare loader.
    try:
        await ctx.page.get_by_text("Workers", exact=True).wait_for(state="visible", timeout=10_000)
        await ctx.page.wait_for_timeout(600)
    except Exception:
        pass
    await _page_shot_current(ctx, _rb(f"admin_monitoring_health_{ctx.theme}"))


@register("admin_monitoring_task_detail")
async def _mon_task_detail(ctx: ShotContext) -> None:
    """Log & Task → Tasks pane with the first row expanded (id/worker/args/logs)."""
    await _open_monitoring(ctx, None)
    control = ctx.page.locator("button.mantine-Accordion-control").first
    await control.wait_for(state="visible", timeout=10_000)
    await control.click()
    await ctx.page.wait_for_timeout(600)
    await _page_shot_current(ctx, _rb(f"admin_monitoring_task_detail_{ctx.theme}"))


async def _mon_expand_shot(ctx: ShotContext, has_text: str | None, out_name: str) -> None:
    """Open Ingestion, expand the row matching `has_text` (or the first), and
    element-screenshot the whole expanded item so a tall detail isn't clipped."""
    await _open_monitoring(ctx, "Ingestion")
    controls = ctx.page.locator("button.mantine-Accordion-control")
    control = controls.filter(has_text=has_text).first if has_text else controls.first
    await control.wait_for(state="visible", timeout=10_000)
    await control.click()
    await ctx.page.wait_for_timeout(700)
    item = control.locator("xpath=ancestor::*[contains(@class,'mantine-Accordion-item')]").first
    target = ctx.output_dir / f"{out_name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    await item.screenshot(path=str(target))
    typer.echo(f"  → {target.relative_to(REPO_ROOT.parent)}")


@register("admin_monitoring_ingestion_detail")
async def _mon_ingestion_detail(ctx: ShotContext) -> None:
    """Ingestion detail: CLI command, local paths, per-DC breakdown + step list."""
    await _mon_expand_shot(ctx, None, _rb(f"admin_monitoring_ingestion_detail_{ctx.theme}"))


@register("admin_monitoring_ingestion_live")
async def _mon_ingestion_live(ctx: ShotContext) -> None:
    """Ingestion detail for an in-flight run (running status + current-step highlight)."""
    await _mon_expand_shot(ctx, "Viralrecon", _rb(f"admin_monitoring_ingestion_live_{ctx.theme}"))


@register("admin_monitoring_agents")
async def _mon_agents(ctx: ShotContext) -> None:
    """Agents pane with the first watcher expanded: fields, "Run now", watched paths.

    Needs a live `depictio watch` registered against the stack — an empty
    registry produces an empty-state shot rather than a failure.
    """
    await _open_monitoring(ctx, "Agents")
    control = ctx.page.locator("button.mantine-Accordion-control").first
    await control.wait_for(state="visible", timeout=10_000)
    await control.click()
    await ctx.page.wait_for_timeout(600)
    await _page_shot_current(ctx, _rb(f"admin_monitoring_agents_{ctx.theme}"))


@register("admin_monitoring_ingestion_watch")
async def _mon_ingestion_watch(ctx: ShotContext) -> None:
    """Ingestion detail for a watcher cycle: trigger badge/reason + per-phase steps.

    Matches on the project name of the watched project, so a stack where that
    project has never been watched will pick the wrong row — pass
    `--watch-project-name` to point it at whichever project has watch runs.
    """
    await _mon_expand_shot(
        ctx, ctx.watch_project_name, _rb(f"admin_monitoring_ingestion_watch_{ctx.theme}")
    )


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
    watch_project_name: str = typer.Option(
        "Watcher Demo",
        "--watch-project-name",
        help="Project name whose watcher-driven ingestion run should be captured.",
    ),
    theme: str = typer.Option(
        "light",
        "--theme",
        help="Colour scheme to seed (light|dark). Theme-aware shots suffix the "
        "filename with _<theme>; run once per theme for the docs light/dark pair.",
    ),
    viewport_width: int = typer.Option(1440, "--viewport-width"),
    viewport_height: int = typer.Option(900, "--viewport-height"),
    headless: bool = typer.Option(True, "--headless/--headed"),
) -> None:
    """Capture one or more named shots into <output-root>/<version>/."""
    if theme not in ("light", "dark"):
        raise typer.BadParameter(f"--theme must be 'light' or 'dark', got {theme!r}.")
    output_dir = output_root / version
    output_dir.mkdir(parents=True, exist_ok=True)
    names = shot or sorted(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise typer.BadParameter(f"Unknown shot(s): {unknown}. Run `list` to see available names.")
    typer.echo(f"📸 Capturing {len(names)} shot(s) [{theme}] into {output_dir}")
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
            theme,
            watch_project_name,
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
    theme: str,
    watch_project_name: str,
) -> None:
    token_payload = _load_token_payload()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": vw, "height": vh})
        # Seed auth + theme in localStorage via init script so they are present
        # BEFORE any page script runs — early API calls (listProjectLinks,
        # listChildTabs) and the SPA's readInitialColorScheme both fire on first
        # paint, so a post-navigation setItem is too late.
        await context.add_init_script(build_localstorage_init_script(token_payload, theme))
        page = await context.new_page()
        ctx = ShotContext(
            page=page,
            viewer_url=viewer_url,
            project_id=project_id,
            dashboard_id=dashboard_id,
            output_dir=output_dir,
            theme=theme,
            watch_project_name=watch_project_name,
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
