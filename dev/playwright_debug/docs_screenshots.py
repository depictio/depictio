#!/usr/bin/env python3
"""Capture documentation screenshots via Playwright against the React (Beta) viewer.

Prerequisites:
    - Dev stack running: `docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up`
    - Vite dev server up on http://localhost:5173 (`pnpm -C depictio/viewer dev`)
    - depictio/.depictio/admin_config.yaml present (created on first stack boot)

Usage:
    python dev/playwright_debug/docs_screenshots.py list
    python dev/playwright_debug/docs_screenshots.py run \\
        --project-id 646b0f3c1e4a2d7f8e5b8c9a \\
        --shot link_create_modal --shot manage_dc_modal --shot create_dc_modal_table

    # realtime shots need a dashboard in a `realtime.enabled` project, and a
    # journal export to populate the event log (see --journal)
    python dev/playwright_debug/docs_screenshots.py run \\
        --viewer-url http://localhost:5600 --no-seed-auth \\
        --project-id 750a1b2c3d4e5f6a7b8c9d0e --dashboard-id 6a5e584b269ea7d0acdc7ffa \\
        --journal /tmp/journal.json --theme dark --shot realtime_live_menu

Shots register themselves in REGISTRY; future releases add new shots in this file
and select them via repeated --shot flags. Output lands in <output-root>/react/,
which is what the docs site reads; --version inserts an extra subdirectory for
one-off captures that shouldn't overwrite the published set.
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


def _rel(path: Path) -> str:
    """Workspace-relative path for logging, falling back to the absolute path
    when the output root sits outside the workspace (e.g. a scratch dir)."""
    try:
        return str(path.relative_to(REPO_ROOT.parent))
    except ValueError:
        return str(path)


async def _shot(ctx: ShotContext, selector: str, name: str) -> None:
    locator = ctx.page.locator(selector).first
    await locator.wait_for(state="visible", timeout=15_000)
    # Brief settle for fonts / icons rendering inside the modal.
    await ctx.page.wait_for_timeout(400)
    target = ctx.output_dir / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    await locator.screenshot(path=str(target))
    typer.echo(f"  → {_rel(target)}")


async def _page_shot_current(ctx: ShotContext, name: str) -> None:
    """Full-viewport capture of the page as it currently stands (no navigation).

    For shots that first click through in-page UI (tabs, segmented controls,
    accordions) — the caller has already navigated and settled.
    """
    target = ctx.output_dir / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    await ctx.page.screenshot(path=str(target), full_page=False)
    typer.echo(f"  → {_rel(target)}")


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
    typer.echo(f"  → {_rel(target)}")


@register("admin_monitoring_ingestion_detail")
async def _mon_ingestion_detail(ctx: ShotContext) -> None:
    """Ingestion detail: CLI command, local paths, per-DC breakdown + step list."""
    await _mon_expand_shot(ctx, None, _rb(f"admin_monitoring_ingestion_detail_{ctx.theme}"))


@register("admin_monitoring_ingestion_live")
async def _mon_ingestion_live(ctx: ShotContext) -> None:
    """Ingestion detail for an in-flight run (running status + current-step highlight)."""
    await _mon_expand_shot(ctx, "Viralrecon", _rb(f"admin_monitoring_ingestion_live_{ctx.theme}"))


# ---- Real-time events shots -----------------------------------------------
# Driven against a dashboard in a project with `realtime.enabled: true`. The
# event log lives in localStorage (`depictio.realtime.journal`), so a fresh
# browser context starts empty — pass `--journal <file.json>` with a journal
# exported from a browser that watched a real stream to capture the log,
# hover-card and highlight states without re-running the acquisition.

REALTIME_JOURNAL_KEY = "depictio.realtime.journal"

# The footer Box carries no test id, so find it structurally: walk up from the
# last component chrome to the ancestor that owns the 1px top border — that Box
# *is* the pinned footer. Returns the element, or null before it mounts.
_FOOTER_JS = """() => {
    const chrome = [...document.querySelectorAll('.depictio-component-chrome')].pop();
    if (!chrome) return null;
    let n = chrome;
    while (n && n !== document.body) {
        const bw = parseFloat(getComputedStyle(n).borderTopWidth || '0');
        if (bw > 0 && n.getBoundingClientRect().width > window.innerWidth * 0.7) return n;
        n = n.parentElement;
    }
    return null;
}"""


async def _open_realtime_dashboard(ctx: ShotContext) -> None:
    """Navigate to the dashboard and wait until the timeline footer has settled.

    The footer mounts well after the grid and then renders "Loading timeline…"
    until its data collection resolves. Both stages have to pass — polling only
    the text would succeed instantly, before the footer even exists.
    """
    await ctx.page.goto(
        f"{ctx.viewer_url}/dashboard/{ctx.dashboard_id}", wait_until="domcontentloaded"
    )
    await wait_for_theme_applied(ctx.page, ctx.theme)
    try:
        await ctx.page.wait_for_function(
            f"() => {{ const f = ({_FOOTER_JS})();"
            f" return !!f && !f.innerText.includes('Loading timeline'); }}",
            timeout=30_000,
        )
    except Exception:
        typer.echo("  ! no settled timeline footer — capturing anyway", err=True)
    await ctx.page.wait_for_timeout(2_000)
    await dismiss_notifications(ctx.page)


async def _clip_shot(ctx: ShotContext, box: dict, name: str) -> None:
    """Viewport screenshot cropped to `box` ({x, y, width, height})."""
    target = ctx.output_dir / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    await ctx.page.screenshot(path=str(target), clip=box)
    typer.echo(f"  → {_rel(target)}")


async def _open_realtime_menu(ctx: ShotContext) -> None:
    await ctx.page.locator('[aria-label="Real-time updates"]').click()
    await ctx.page.locator(".mantine-Menu-dropdown").first.wait_for(state="visible", timeout=10_000)
    await ctx.page.wait_for_timeout(500)


@register("realtime_dashboard")
async def _realtime_dashboard(ctx: ShotContext) -> None:
    """Live dashboard: status pill top-right, pinned acquisition-window footer."""
    await _open_realtime_dashboard(ctx)
    await _page_shot_current(ctx, _rb(f"realtime_dashboard_{ctx.theme}"))


@register("realtime_indicator")
async def _realtime_indicator(ctx: ShotContext) -> None:
    """Header strip cropped to the real-time status pill."""
    await _open_realtime_dashboard(ctx)
    box = await ctx.page.locator('[aria-label="Real-time updates"]').bounding_box()
    if not box:
        raise RuntimeError("real-time indicator not found — is `realtime` enabled?")
    # Widen leftwards so the neighbouring header controls give the pill context,
    # and run to the viewport edge so the pill itself isn't shaved.
    left = max(0.0, box["x"] - 380)
    width = await ctx.page.evaluate("() => window.innerWidth")
    await _clip_shot(
        ctx,
        {"x": left, "y": 0, "width": width - left, "height": 50},
        _rb(f"realtime_indicator_{ctx.theme}"),
    )


@register("realtime_timeline_footer")
async def _realtime_timeline_footer(ctx: ShotContext) -> None:
    """The full-width acquisition-window scrubber pinned below the columns."""
    await _open_realtime_dashboard(ctx)
    box = await ctx.page.evaluate(
        f"() => {{ const f = ({_FOOTER_JS})(); if (!f) return null;"
        f" const r = f.getBoundingClientRect();"
        f" return {{ x: r.x, y: r.y, width: r.width, height: r.height }}; }}"
    )
    if not box:
        raise RuntimeError("timeline footer not found — no top-placement component?")
    await _clip_shot(ctx, box, _rb(f"realtime_timeline_footer_{ctx.theme}"))


@register("realtime_live_menu")
async def _realtime_live_menu(ctx: ShotContext) -> None:
    """Live updates dropdown: mode/pause switches over the captured event log."""
    await _open_realtime_dashboard(ctx)
    await _open_realtime_menu(ctx)
    await _shot(ctx, ".mantine-Menu-dropdown", _rb(f"realtime_live_menu_{ctx.theme}"))


@register("realtime_event_detail")
async def _realtime_event_detail(ctx: ShotContext) -> None:
    """Hover-card on an event-log row — row delta, versions, new ids, payload."""
    await _open_realtime_dashboard(ctx)
    await _open_realtime_menu(ctx)
    await ctx.page.locator(".mantine-Menu-dropdown [style*='border-left']").first.hover()
    await ctx.page.locator(".mantine-HoverCard-dropdown").first.wait_for(
        state="visible", timeout=10_000
    )
    await ctx.page.wait_for_timeout(600)
    await _page_shot_current(ctx, _rb(f"realtime_event_detail_{ctx.theme}"))


@register("realtime_highlight")
async def _realtime_highlight(ctx: ShotContext) -> None:
    """A past batch pinned via the highlight button — row stays marked, and a
    Clear highlight link appears in the log header."""
    await _open_realtime_dashboard(ctx)
    await _open_realtime_menu(ctx)
    await ctx.page.locator('[aria-label="Highlight this batch"]').first.click()
    # Park the cursor off the dropdown: leaving it on the button keeps both the
    # "Highlighted" tooltip and the row hover-card up, hiding the Clear
    # highlight link and the highlighted points behind them. Aim for the filter
    # panel — parking over the grid pops a Plotly modebar into the shot.
    await ctx.page.mouse.move(150, 620)
    await ctx.page.wait_for_timeout(1_200)
    await _page_shot_current(ctx, _rb(f"realtime_highlight_{ctx.theme}"))


# ---- Cross-DC link inspection shots ---------------------------------------
# Driven against a project that owns at least one MultiQC `sample_mapping`
# link (the nf-core reference projects do). The links section is collapsed by
# default, so every shot here expands it first.


async def _open_links_section(ctx: ShotContext) -> None:
    """Open the project page and expand the Cross-DC links section."""
    await ctx.page.goto(
        f"{ctx.viewer_url}/projects/{ctx.project_id}", wait_until="domcontentloaded"
    )
    await ctx.page.wait_for_timeout(1_500)
    await dismiss_notifications(ctx.page)
    toggle = ctx.page.get_by_test_id("links-section-toggle")
    await toggle.wait_for(state="visible", timeout=15_000)
    await toggle.click()
    # Wait for a row rather than a fixed delay: the list is fetched on mount.
    await ctx.page.locator('[data-testid="inspect-link-btn"]').first.wait_for(
        state="visible", timeout=15_000
    )
    await ctx.page.wait_for_timeout(400)


@register("link_inspect_action")
async def _link_inspect_action(ctx: ShotContext) -> None:
    """Cross-DC links table with the per-row inspect (magnifier) action."""
    await _open_links_section(ctx)
    await _shot(ctx, '[data-testid="links-section"]', _rb("link_inspect_action"))


@register("link_mapping_modal")
async def _link_mapping_modal(ctx: ShotContext) -> None:
    """Standalone mapping inspector, opened from a sample_mapping link's magnifier."""
    await _open_links_section(ctx)
    row = ctx.page.locator("tr", has_text="sample_mapping").first
    await row.get_by_test_id("inspect-link-btn").click()
    # The preview resolves every distinct source value server-side; wait for
    # the grid to hold rows so the shot isn't the loading state.
    await ctx.page.locator('[data-testid="mapping-inspector-grid"] .ag-row').first.wait_for(
        state="visible", timeout=60_000
    )
    await ctx.page.wait_for_timeout(600)
    await _shot(ctx, '[data-testid="link-mapping-modal"]', _rb("link_mapping_modal"))


# ---- Funnel filtering shots ------------------------------------------------
# Driven against a dashboard with categorical (MultiSelect) filters. Funnel
# filtering is an author-level dashboard flag; these shots flip it with the
# panel's own toggle, which is per-page-view and writes nothing.

FUNNEL_PICKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("species", ("Adelie",)),
    ("island", ("Torgersen", "Biscoe")),
    ("sex", ("male",)),
)


async def _filter_panel(ctx: ShotContext):
    """The filter panel Paper — located from the funnel toggle it contains."""
    return ctx.page.get_by_test_id("funnel-toggle").locator(
        "xpath=ancestor::*[contains(@class,'mantine-Paper-root')][1]"
    )


async def _open_funnel_panel(ctx: ShotContext) -> None:
    """Open the dashboard, reveal the filter panel and switch funnelling on."""
    await ctx.page.goto(
        f"{ctx.viewer_url}/dashboard/{ctx.dashboard_id}", wait_until="domcontentloaded"
    )
    await ctx.page.wait_for_timeout(6_000)
    await dismiss_notifications(ctx.page)
    rail = ctx.page.locator('[aria-label="Show filters"]')
    if await rail.count() and await rail.first.is_visible():
        await rail.first.click()
        await ctx.page.wait_for_timeout(800)
    toggle = ctx.page.get_by_test_id("funnel-toggle")
    await toggle.wait_for(state="visible", timeout=20_000)
    # The overview button is mounted-but-disabled while funnelling is off —
    # that is the state check, since the toggle itself only varies by variant.
    overview = ctx.page.get_by_test_id("funnel-view-button")
    if await overview.is_disabled():
        await toggle.click()
        await ctx.page.wait_for_timeout(1_500)


async def _apply_funnel_filters(ctx: ShotContext) -> None:
    """Select the categorical values the funnel captions describe."""
    for column, values in FUNNEL_PICKS:
        field = ctx.page.get_by_placeholder(f"Select {column}…")
        await field.wait_for(state="visible", timeout=15_000)
        await field.click()
        for value in values:
            await ctx.page.get_by_role("option", name=value, exact=True).first.click()
        await ctx.page.keyboard.press("Escape")
        # Each change debounces, refetches the availability sets and re-renders.
        await ctx.page.wait_for_timeout(2_500)


@register("funnel_panel_header")
async def _funnel_panel_header(ctx: ShotContext) -> None:
    """Panel header: title, attached funnel pair, overflow menu, Reset."""
    await _open_funnel_panel(ctx)
    await _apply_funnel_filters(ctx)
    box = await (await _filter_panel(ctx)).bounding_box()
    if not box:
        raise RuntimeError("filter panel not found")
    await _clip_shot(
        ctx,
        {"x": box["x"], "y": box["y"], "width": box["width"], "height": min(box["height"], 150)},
        _rb("funnel_panel_header"),
    )


@register("funnel_panel_highlighting")
async def _funnel_panel_highlighting(ctx: ShotContext) -> None:
    """Whole panel with funnelling on: per-value markers and n/N badges."""
    await _open_funnel_panel(ctx)
    await _apply_funnel_filters(ctx)
    panel = await _filter_panel(ctx)
    target = ctx.output_dir / f"{_rb('funnel_panel_highlighting')}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    await panel.screenshot(path=str(target))
    typer.echo(f"  → {_rel(target)}")


async def _open_funnel_overview(ctx: ShotContext):
    await ctx.page.get_by_test_id("funnel-view-button").click()
    modal = ctx.page.locator(".mantine-Modal-content").first
    await modal.wait_for(state="visible", timeout=20_000)
    # Plotly draws after the funnel counts land; wait for the trace itself.
    await ctx.page.locator(".mantine-Modal-content .js-plotly-plot").first.wait_for(
        state="visible", timeout=60_000
    )
    await ctx.page.wait_for_timeout(1_500)
    return modal


@register("funnel_overview")
async def _funnel_overview(ctx: ShotContext) -> None:
    """Funnel overview modal: cascading row counts + the stage list."""
    await _open_funnel_panel(ctx)
    await _apply_funnel_filters(ctx)
    await _open_funnel_overview(ctx)
    await _shot(ctx, ".mantine-Modal-content", _rb("funnel_overview"))


@register("funnel_overview_reordered")
async def _funnel_overview_reordered(ctx: ShotContext) -> None:
    """Same funnel with the last stage moved up — intermediate counts change,
    the final count does not."""
    await _open_funnel_panel(ctx)
    await _apply_funnel_filters(ctx)
    await _open_funnel_overview(ctx)
    await ctx.page.locator('[aria-label^="Move "][aria-label$=" earlier"]').last.click()
    await ctx.page.wait_for_timeout(3_000)
    await _shot(ctx, ".mantine-Modal-content", _rb("funnel_overview_reordered"))


# ---- CLI ------------------------------------------------------------------


@app.command(name="list")
def list_shots() -> None:
    """List available shot names."""
    for name in sorted(REGISTRY):
        typer.echo(name)


@app.command()
def run(
    version: str = typer.Option(
        "",
        "--version",
        help="Optional release tag used as an output subdirectory. Omit to write "
        "straight into <output-root>/react/, which is where the docs site now "
        "reads its images from.",
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
    theme: str = typer.Option(
        "light",
        "--theme",
        help="Colour scheme to seed (light|dark). Theme-aware shots suffix the "
        "filename with _<theme>; run once per theme for the docs light/dark pair.",
    ),
    journal: Path = typer.Option(
        None,
        "--journal",
        help="JSON file seeded into localStorage as the realtime event log "
        "(depictio.realtime.journal). Needed by the realtime_* shots, whose log, "
        "hover-card and highlight states only exist once events have been seen.",
    ),
    seed_auth: bool = typer.Option(
        True,
        "--seed-auth/--no-seed-auth",
        help="Seed the local admin token into localStorage. Disable when driving "
        "an instance in unauthenticated mode that the local token doesn't belong to.",
    ),
    viewport_width: int = typer.Option(1440, "--viewport-width"),
    viewport_height: int = typer.Option(900, "--viewport-height"),
    headless: bool = typer.Option(True, "--headless/--headed"),
) -> None:
    """Capture one or more named shots into <output-root>/<version>/."""
    if theme not in ("light", "dark"):
        raise typer.BadParameter(f"--theme must be 'light' or 'dark', got {theme!r}.")
    if journal is not None and not journal.exists():
        raise typer.BadParameter(f"--journal file not found: {journal}")
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
            journal,
            seed_auth,
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
    journal: Path | None = None,
    seed_auth: bool = True,
) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": vw, "height": vh})
        # Seed auth + theme in localStorage via init script so they are present
        # BEFORE any page script runs — early API calls (listProjectLinks,
        # listChildTabs) and the SPA's readInitialColorScheme both fire on first
        # paint, so a post-navigation setItem is too late.
        if seed_auth:
            init_script = build_localstorage_init_script(_load_token_payload(), theme)
        else:
            # Theme only — writing an empty `local-store` would look like a
            # broken session rather than no session at all.
            init_script = (
                f"localStorage.setItem('theme-store',"
                f" {json.dumps(json.dumps({'colorScheme': theme}))});"
            )
        await context.add_init_script(init_script)
        if journal is not None:
            # Same reasoning: the RealtimeIndicator reads the journal in a
            # useState initialiser, i.e. on first render.
            await context.add_init_script(
                f"localStorage.setItem({json.dumps(REALTIME_JOURNAL_KEY)},"
                f" {json.dumps(journal.read_text())});"
            )
        page = await context.new_page()
        ctx = ShotContext(
            page=page,
            viewer_url=viewer_url,
            project_id=project_id,
            dashboard_id=dashboard_id,
            output_dir=output_dir,
            theme=theme,
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
