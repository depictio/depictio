"""
Shared screenshot service for dashboard dual-theme screenshot generation.

The active code path drives the React SPA at `{fastapi.url}/dashboard-beta/{id}`
via `generate_react_dual_theme_screenshots`. Dash-targeted captures
(`generate_dual_theme_screenshots`) are kept for emergency rollback only —
they log a deprecation warning on every call and should not run in normal
operation.

Low-level Playwright primitives (init-script builder, theme/grid waits, chrome
hider, notification dismisser, unreachable-host markers) live in
`screenshot_helpers.py` so the dev `docs_screenshots.py` script can share them
without dragging the MongoDB-backed token loader along.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

from bson import ObjectId
from playwright.async_api import Page, async_playwright

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.api.v1.services.screenshot_helpers import (
    HOST_UNREACHABLE_MARKERS,
    apply_init_script,
    hide_ui_chrome,
    wait_for_dashboard_content,
    wait_for_plotly_drawn,
    wait_for_theme_applied,
)
from depictio.models.models.users import TokenBeanie, UserBeanie

__all__ = [
    "ScreenshotResult",
    "check_dashboard_owner_permission",
    "check_dashboard_owner_permission_sync",
    "generate_dual_theme_screenshots",
    "generate_react_dual_theme_screenshots",
    "get_admin_auth_token",
    # Re-exported for legacy callers; the canonical source is screenshot_helpers.
    "hide_ui_chrome",
    "wait_for_dashboard_content",
]


class ScreenshotResult(TypedDict):
    """Result of dual-theme screenshot generation."""

    status: str  # "success", "skipped", "forbidden", or "error"
    dashboard_id: str
    light_screenshot: str | None
    dark_screenshot: str | None
    error: str | None


def check_dashboard_owner_permission_sync(dashboard_id: str, user_id: str) -> bool:
    """
    Check if user is the owner of a dashboard.

    Looks at dashboard-level ``permissions.owners`` first — duplication
    assigns the new owner there while keeping ``project_id`` pointing at
    the original project, so a project-only check denies legitimate
    copies. Falls back to the parent project's owners when the dashboard
    has no per-dashboard owners (e.g. seeded dashboards).

    Uses synchronous MongoDB operations (pymongo). Safe to call from both
    sync contexts (Dash callbacks) and async contexts (via the async wrapper).
    """
    try:
        dashboard_oid = ObjectId(dashboard_id)
        dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_oid})
        if not dashboard:
            logger.warning(f"Dashboard not found: {dashboard_id}")
            return False

        user_obj_id = ObjectId(user_id)

        if _any_owner_matches(dashboard.get("permissions", {}).get("owners"), user_obj_id):
            return True

        project_id = dashboard.get("project_id")
        if not project_id:
            return False

        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project:
            logger.warning(f"Project not found: {project_id}")
            return False

        return _any_owner_matches(project.get("permissions", {}).get("owners"), user_obj_id)

    except Exception as e:
        logger.error(f"Error checking dashboard ownership: {e}")
        return False


def _any_owner_matches(owners: object, user_obj_id: ObjectId) -> bool:
    """Return True if any owner record matches ``user_obj_id``.

    Tolerates both ``ObjectId`` and string forms of the owner's ``_id``.
    """
    if not isinstance(owners, list):
        return False
    for owner_obj in owners:
        if not isinstance(owner_obj, dict):
            continue
        owner = cast(dict[str, object], owner_obj)
        raw = owner.get("_id")
        if isinstance(raw, ObjectId):
            if raw == user_obj_id:
                return True
        elif isinstance(raw, str):
            try:
                if ObjectId(raw) == user_obj_id:
                    return True
            except Exception:
                continue
    return False


async def check_dashboard_owner_permission(dashboard_id: str, user_id: str) -> bool:
    """
    Async wrapper around check_dashboard_owner_permission_sync.

    Both functions use synchronous pymongo under the hood. This wrapper
    exists for API compatibility in async contexts.
    """
    return check_dashboard_owner_permission_sync(dashboard_id, user_id)


async def get_admin_auth_token() -> dict[str, str]:
    """
    Retrieve admin authentication token from MongoDB.

    Returns:
        dict: Token data serialized for localStorage, including:
            - _id, user_id, access_token, refresh_token
            - expire_datetime, created_at (as strings)
            - logged_in: True

    Raises:
        ValueError: If admin user or valid token not found
    """
    current_user = await UserBeanie.find_one({"email": "admin@example.com"})
    if not current_user:
        raise ValueError("Admin user not found")

    token = await TokenBeanie.find_one(
        {
            "user_id": current_user.id,
            "refresh_expire_datetime": {"$gt": datetime.now()},
        }
    )
    if not token:
        raise ValueError("Valid token not found for admin user")

    # Prepare token data for localStorage
    token_data = token.model_dump(exclude_none=True)
    token_data["_id"] = str(token_data.pop("id", None))
    token_data["user_id"] = str(token_data["user_id"])
    token_data["logged_in"] = True

    # Serialize datetime fields
    if isinstance(token_data.get("expire_datetime"), datetime):
        token_data["expire_datetime"] = token_data["expire_datetime"].strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(token_data.get("created_at"), datetime):
        token_data["created_at"] = token_data["created_at"].strftime("%Y-%m-%d %H:%M:%S")

    return token_data


async def generate_dual_theme_screenshots(
    dashboard_id: str,
    output_folder: str = "/app/depictio/api/static/screenshots",
    user_id: str | None = None,
) -> ScreenshotResult:
    """
    Generate both light and dark mode screenshots in single browser call with optional permission validation.

    This function creates dual-theme screenshots ({dashboard_id}_light.png and
    {dashboard_id}_dark.png) in a single Playwright session, reusing the browser
    context for efficiency (~40% time savings vs. two separate calls).

    Strategy:
    1. Validate user ownership if user_id provided (defense in depth)
    2. Launch browser and authenticate with admin token
    3. Navigate to dashboard in light mode, hide UI chrome, screenshot
    4. Reload with dark mode theme, hide UI chrome, screenshot
    5. Both screenshots saved to output_folder

    Args:
        dashboard_id: Dashboard ID to screenshot
        output_folder: Directory to save screenshots (default: /app/depictio/api/static/screenshots)
        user_id: Optional user ID for permission validation (recommended for security)

    Returns:
        ScreenshotResult: Dict with status, dashboard_id, screenshot paths, and optional error
                         Returns forbidden status if user_id provided but user is not owner

    DEPRECATED: prefer `generate_react_dual_theme_screenshots`. Production
    screenshot capture now drives the React SPA. This function is kept for
    emergency rollback and logs a warning on every call.
    """
    logger.warning(
        "generate_dual_theme_screenshots (Dash) is deprecated — "
        "callers should use generate_react_dual_theme_screenshots."
    )
    # Validate ownership if user_id provided (defense in depth)
    if user_id:
        is_owner = await check_dashboard_owner_permission(
            dashboard_id=dashboard_id, user_id=user_id
        )

        if not is_owner:
            logger.warning(
                f"Screenshot denied: user {user_id} is not owner of dashboard {dashboard_id}"
            )
            error_result: ScreenshotResult = {
                "status": "forbidden",
                "dashboard_id": dashboard_id,
                "light_screenshot": None,
                "dark_screenshot": None,
                "error": "User is not dashboard owner",
            }
            return error_result

    Path(output_folder).mkdir(parents=True, exist_ok=True)

    light_path = f"{output_folder}/{dashboard_id}_light.png"
    dark_path = f"{output_folder}/{dashboard_id}_dark.png"

    try:
        # Get admin authentication token
        token_data = await get_admin_auth_token()
        token_data_json = json.dumps(token_data)
        # ``no-walkthrough=1`` tells the React viewer's ``WalkthroughHost`` to
        # short-circuit before mounting either tour engine. The legacy
        # ``/dashboard/{id}`` route doesn't render the React walkthrough today,
        # so this is defensive — keeps the PNG clean if/when screenshots ever
        # target ``/dashboard-beta/{id}``.
        dashboard_url = f"{settings.viewer.internal_url}/dashboard/{dashboard_id}?no-walkthrough=1"

        logger.info(f"Starting dual-theme screenshot for dashboard {dashboard_id}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})

            # Set authentication token before navigation. The very first goto
            # is also our probe: if the viewer container isn't running in
            # this compose project, Playwright surfaces ERR_NAME_NOT_RESOLVED
            # (or ERR_CONNECTION_*) — skip rather than failing the Celery task.
            try:
                await page.goto(settings.viewer.internal_url)
            except Exception as nav_err:
                msg = str(nav_err)
                if any(m in msg for m in HOST_UNREACHABLE_MARKERS):
                    logger.warning(
                        f"Viewer ({settings.viewer.internal_url}) is unreachable "
                        f"from this worker — skipping screenshot for {dashboard_id}. "
                        "Start the depictio-viewer container or set "
                        "DEPICTIO_VIEWER_SERVICE_NAME to a reachable host."
                    )
                    await browser.close()
                    skip_result: ScreenshotResult = {
                        "status": "skipped",
                        "light_screenshot": None,
                        "dark_screenshot": None,
                        "dashboard_id": dashboard_id,
                        "error": None,
                    }
                    return skip_result
                raise
            await page.evaluate(f"localStorage.setItem('local-store', '{token_data_json}')")

            # Capture both themes in sequence
            for theme, output_path in [("light", light_path), ("dark", dark_path)]:
                if theme == "light":
                    # Navigate to dashboard first, then set theme and reload
                    await page.goto(
                        dashboard_url, timeout=settings.performance.screenshot_navigation_timeout
                    )

                await page.evaluate(
                    f"localStorage.setItem('theme-store', JSON.stringify('{theme}'))"
                )
                await page.reload(timeout=settings.performance.screenshot_navigation_timeout)

                # Wait for MantineProvider to apply theme
                try:
                    await page.wait_for_selector(
                        f'[data-mantine-color-scheme="{theme}"]',
                        timeout=settings.performance.screenshot_content_wait,
                    )
                    await page.wait_for_timeout(1000)
                except Exception:
                    logger.warning(
                        f"Timeout waiting for {theme} theme attribute, using fallback wait"
                    )
                    await page.wait_for_timeout(settings.performance.screenshot_stabilization_wait)

                try:
                    await wait_for_dashboard_content(page)
                except Exception:
                    logger.warning(f"Timeout waiting for dashboard components ({theme} mode)")

                # Hide UI chrome and take screenshot
                await hide_ui_chrome(page)
                main_element = await page.query_selector(".mantine-AppShell-main")
                if main_element:
                    await main_element.screenshot(path=output_path)
                else:
                    await page.screenshot(path=output_path, full_page=True)

            await browser.close()
            logger.info(f"Dual-theme screenshots completed for dashboard {dashboard_id}")

        result: ScreenshotResult = {
            "status": "success",
            "light_screenshot": light_path,
            "dark_screenshot": dark_path,
            "dashboard_id": dashboard_id,
            "error": None,
        }
        return result

    except Exception as e:
        logger.error(f"Dual-theme screenshot error for {dashboard_id}: {e}")
        error_result: ScreenshotResult = {
            "status": "error",
            "dashboard_id": dashboard_id,
            "light_screenshot": None,
            "dark_screenshot": None,
            "error": str(e),
        }
        return error_result


async def _try_open_viz_settings(page: Page) -> bool:
    """Click the first advanced-viz settings cog so the popover shows in the shot.

    Returns True if the popover opened. Silently returns False when the viz
    being screenshotted is something other than an advanced-viz (or when the
    popover fails to mount for any reason) — the caller continues with a
    settings-closed capture in that case.
    """
    btn = await page.query_selector('[aria-label="Viz settings"]')
    if not btn:
        return False
    await btn.click()
    try:
        await page.wait_for_selector(".mantine-Popover-dropdown", timeout=2000)
        await page.wait_for_timeout(200)
        return True
    except Exception:
        return False


def _react_output_paths(
    output_folder: str, dashboard_id: str, filename_prefix: str
) -> tuple[str, str]:
    """Resolve `(light_path, dark_path)` for the React screenshot job.

    Default `filename_prefix=""` produces `{id}_{theme}.png` — same names as
    the legacy Dash job, so dashboard-card UIs that already fetch those URLs
    keep working with no frontend change. A non-empty prefix yields
    `{prefix}_{id}_{theme}.png` for parallel batches (e.g. docs captures
    flagged with `--filename-prefix=docs`) that must not clobber the
    canonical shots.
    """
    if filename_prefix:
        light = f"{output_folder}/{filename_prefix}_{dashboard_id}_light.png"
        dark = f"{output_folder}/{filename_prefix}_{dashboard_id}_dark.png"
    else:
        light = f"{output_folder}/{dashboard_id}_light.png"
        dark = f"{output_folder}/{dashboard_id}_dark.png"
    return light, dark


async def generate_react_dual_theme_screenshots(
    dashboard_id: str,
    output_folder: str = "/app/depictio/api/static/screenshots",
    user_id: str | None = None,
    open_settings: bool = False,
    filename_prefix: str = "",
) -> ScreenshotResult:
    """Generate light + dark screenshots of the React beta viewer.

    This is the canonical production path. Drives the SPA bundle FastAPI
    serves at `{settings.fastapi.url}/dashboard-beta/{id}` (port 8100 by
    default).

    Defaults to filenames `{id}_light.png` / `{id}_dark.png` for backward
    compatibility with consumers that previously read the Dash-generated
    PNGs from the same folder. Pass a non-empty `filename_prefix` to keep
    parallel batches (e.g. docs captures) from clobbering the canonical
    shots.

    `open_settings=True` clicks the first `aria-label="Viz settings"`
    ActionIcon before capture so the popover shows in the shot (advanced-
    viz docs flow); falls back to a normal shot if no popover exists.
    Because Mantine popovers portal to document.body, a popover-open
    capture switches from element.screenshot to a viewport capture.
    """
    # Single-user mode has no per-user ownership — skip the check entirely,
    # mirroring the Celery task (celery_app.py) and the HTTP screenshot route.
    # Without this, seeded/dev dashboards (owned by the seed admin, not the
    # anonymous single-user) get a spurious "not dashboard owner" rejection.
    if user_id and not settings.auth.is_single_user_mode:
        is_owner = await check_dashboard_owner_permission(
            dashboard_id=dashboard_id, user_id=user_id
        )
        if not is_owner:
            return {
                "status": "forbidden",
                "dashboard_id": dashboard_id,
                "light_screenshot": None,
                "dark_screenshot": None,
                "error": "User is not dashboard owner",
            }

    Path(output_folder).mkdir(parents=True, exist_ok=True)
    light_path, dark_path = _react_output_paths(output_folder, dashboard_id, filename_prefix)

    # The React SPA is served by the viewer (nginx) container, not the API.
    # Use the viewer's internal URL so the worker's headless browser loads
    # the bundle from nginx; the SPA's relative /depictio/api/* calls are
    # then proxied by that same nginx back to the backend. `.url` picks
    # internal vs external by DEPICTIO_CONTEXT (server → docker/k8s DNS
    # hostname; host invocation → external port).
    origin = settings.viewer.url
    # `?no-walkthrough=1` tells the React SPA's WalkthroughHost to bail
    # before mounting either tour engine, so the captured PNG never
    # contains the popover, anchor, or dim backdrop — even when the
    # seeded admin's localStorage would otherwise auto-start the
    # builder walkthrough on first visit.
    dashboard_url = f"{origin}/dashboard-beta/{dashboard_id}?no-walkthrough=1"

    try:
        token_data = await get_admin_auth_token()
        token_data_json = json.dumps(token_data)

        logger.info(f"React dual-theme screenshot: dashboard {dashboard_id} via {dashboard_url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            for theme, output_path in [("light", light_path), ("dark", dark_path)]:
                # Fresh context per theme — Playwright init scripts re-run on
                # every navigation/reload and overwrite any post-nav
                # `evaluate(localStorage.set...)`, so a reload-and-swap strategy
                # silently captures the same theme twice. The fresh context
                # is the safe choice; cost is ~+14 s vs the Dash variant on a
                # large dashboard. Acceptable because the active path
                # (`generate_dashboard_screenshot_dual` Celery task) is
                # fire-and-forget and the user doesn't wait.
                context = await browser.new_context(viewport={"width": 1920, "height": 1080})
                await apply_init_script(context, token_data_json, theme)
                page = await context.new_page()

                try:
                    # `wait_until="domcontentloaded"` rather than the default
                    # "load" — the SPA keeps lazy-loading code-split chunks
                    # for a couple seconds after first paint and we don't
                    # need them; `wait_for_dashboard_content` below gates on
                    # the actual grid-render. Also matches the dev
                    # docs_screenshots.py pattern.
                    await page.goto(
                        dashboard_url,
                        wait_until="domcontentloaded",
                        timeout=settings.performance.screenshot_navigation_timeout,
                    )
                except Exception as nav_err:
                    msg = str(nav_err)
                    if any(m in msg for m in HOST_UNREACHABLE_MARKERS):
                        logger.warning(
                            f"FastAPI host ({origin}) unreachable — skipping React "
                            f"screenshot for {dashboard_id}."
                        )
                        await context.close()
                        await browser.close()
                        return {
                            "status": "skipped",
                            "light_screenshot": None,
                            "dark_screenshot": None,
                            "dashboard_id": dashboard_id,
                            "error": None,
                        }
                    raise

                if not await wait_for_theme_applied(page, theme):
                    logger.warning(
                        f"React: timeout waiting for {theme} theme attribute "
                        f"on dashboard {dashboard_id}"
                    )

                try:
                    await wait_for_dashboard_content(page)
                except Exception:
                    logger.warning(
                        f"React: timeout waiting for grid items "
                        f"({theme}) on dashboard {dashboard_id}"
                    )

                # Probe each `.plotly-graph-div` for `.plot-container` instead
                # of paying an unconditional ~1 s sleep — exits in <200 ms on a
                # warm dashboard, exits immediately on a card-only dashboard,
                # and falls back to a "log + continue" on the (rare) 3 s
                # timeout. The Dash variant still sleeps because its plotly
                # mounts happen after server callbacks complete and aren't as
                # easy to probe from the page side.
                if not await wait_for_plotly_drawn(page):
                    logger.warning(
                        f"React: plotly draw timed out ({theme}) on dashboard "
                        f"{dashboard_id} — capturing anyway"
                    )

                await hide_ui_chrome(page)

                popover_open = False
                if open_settings:
                    popover_open = await _try_open_viz_settings(page)

                if popover_open:
                    # Mantine popovers portal to document.body, so they sit
                    # outside the AppShell.Main DOM bbox — element.screenshot()
                    # would clip them off. Fall back to a viewport capture.
                    await page.screenshot(
                        path=output_path,
                        full_page=False,
                        timeout=settings.performance.screenshot_capture_timeout,
                    )
                else:
                    main_element = await page.query_selector(".mantine-AppShell-main")
                    if main_element:
                        # Honour the configured capture timeout instead of
                        # Playwright's default 30s — phylogeny / advanced-viz
                        # heavy tabs do animated layout passes that the default
                        # "wait for stable" can't catch in time.
                        await main_element.screenshot(
                            path=output_path,
                            timeout=settings.performance.screenshot_capture_timeout,
                        )
                    else:
                        await page.screenshot(
                            path=output_path,
                            full_page=False,
                            timeout=settings.performance.screenshot_capture_timeout,
                        )

                await context.close()

            await browser.close()
            logger.info(f"React dual-theme screenshots completed for {dashboard_id}")

        return {
            "status": "success",
            "light_screenshot": light_path,
            "dark_screenshot": dark_path,
            "dashboard_id": dashboard_id,
            "error": None,
        }

    except Exception as e:
        logger.error(f"React dual-theme screenshot error for {dashboard_id}: {e}")
        return {
            "status": "error",
            "dashboard_id": dashboard_id,
            "light_screenshot": None,
            "dark_screenshot": None,
            "error": str(e),
        }
