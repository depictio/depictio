"""
Shared screenshot service for dashboard dual-theme screenshot generation.

This module provides centralized Playwright-based screenshot logic that can be
used by both the API endpoint (for testing/debugging) and the Celery task
(for production async screenshot generation).

Eliminates HTTP indirection and centralizes screenshot logic in one place.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from bson import ObjectId
from playwright.async_api import Page, async_playwright

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.models.models.users import TokenBeanie, UserBeanie


class ScreenshotResult(TypedDict):
    """Result of dual-theme screenshot generation."""

    status: str  # "success", "skipped", "forbidden", or "error"
    dashboard_id: str
    light_screenshot: str | None
    dark_screenshot: str | None
    error: str | None


# Playwright error substrings that mean "the Dash frontend host isn't reachable"
# (typically: this worktree didn't start the depictio-frontend container).
# Treat them as "skip screenshot" rather than "task failed".
_HOST_UNREACHABLE_MARKERS = (
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT",
)


def check_dashboard_owner_permission_sync(dashboard_id: str, user_id: str) -> bool:
    """
    Check if user is the owner of a dashboard (via project ownership).

    Uses synchronous MongoDB operations (pymongo). Safe to call from both
    sync contexts (Dash callbacks) and async contexts (via the async wrapper).

    Args:
        dashboard_id: Dashboard ObjectId as string
        user_id: User ObjectId as string

    Returns:
        True if user owns dashboard, False otherwise
    """
    try:
        # Convert dashboard_id string to ObjectId for MongoDB query
        dashboard_oid = ObjectId(dashboard_id)
        dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_oid})
        if not dashboard:
            logger.warning(f"Dashboard not found: {dashboard_id}")
            return False

        project_id = dashboard.get("project_id")
        if not project_id:
            logger.warning(f"Dashboard {dashboard_id} has no project_id")
            return False

        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project:
            logger.warning(f"Project not found: {project_id}")
            return False

        owners = project.get("permissions", {}).get("owners", [])
        user_obj_id = ObjectId(user_id)
        return any(owner.get("_id") == user_obj_id for owner in owners)

    except Exception as e:
        logger.error(f"Error checking dashboard ownership: {e}")
        return False


async def check_dashboard_owner_permission(dashboard_id: str, user_id: str) -> bool:
    """
    Async wrapper around check_dashboard_owner_permission_sync.

    Both functions use synchronous pymongo under the hood. This wrapper
    exists for API compatibility in async contexts.
    """
    return check_dashboard_owner_permission_sync(dashboard_id, user_id)


async def wait_for_dashboard_content(page: Page) -> None:
    """Wait for react-grid-item components to render with proper dimensions."""
    await page.wait_for_function(
        """() => {
            const components = document.querySelectorAll('.react-grid-item');
            if (components.length === 0) return false;
            for (let component of components) {
                const rect = component.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) return true;
            }
            return false;
        }""",
        timeout=settings.performance.screenshot_content_wait,
    )


async def hide_ui_chrome(page: Page) -> None:
    """Hide navbar, header, debug menu, and adjust page styling for clean screenshot."""
    await page.evaluate(
        """() => {
        const navbar = document.querySelector('.mantine-AppShell-navbar');
        if (navbar) navbar.style.display = 'none';

        const header = document.querySelector('.mantine-AppShell-header');
        if (header) header.style.display = 'none';

        const debugMenu = document.querySelector('.dash-debug-menu__outer');
        if (debugMenu) debugMenu.style.display = 'none';

        const pageContent = document.querySelector('#page-content');
        if (pageContent) {
            pageContent.style.padding = '0';
            pageContent.style.margin = '0';
        }

        const main = document.querySelector('.mantine-AppShell-main');
        if (main) {
            main.style.padding = '0';
            main.style.paddingLeft = '0';
            main.style.margin = '0';
        }
    }"""
    )


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
    output_folder: str = "/app/depictio/dash/static/screenshots",
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
        output_folder: Directory to save screenshots (default: /app/depictio/dash/static/screenshots)
        user_id: Optional user ID for permission validation (recommended for security)

    Returns:
        ScreenshotResult: Dict with status, dashboard_id, screenshot paths, and optional error
                         Returns forbidden status if user_id provided but user is not owner
    """
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
        dashboard_url = f"{settings.dash.internal_url}/dashboard/{dashboard_id}"

        logger.info(f"Starting dual-theme screenshot for dashboard {dashboard_id}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})

            # Set authentication token before navigation. The very first goto
            # is also our probe: if the Dash frontend container isn't running
            # in this compose project, Playwright surfaces ERR_NAME_NOT_RESOLVED
            # (or ERR_CONNECTION_*) — skip rather than failing the Celery task.
            try:
                await page.goto(settings.dash.internal_url)
            except Exception as nav_err:
                msg = str(nav_err)
                if any(m in msg for m in _HOST_UNREACHABLE_MARKERS):
                    logger.warning(
                        f"Dash frontend ({settings.dash.internal_url}) is unreachable "
                        f"from this worker — skipping screenshot for {dashboard_id}. "
                        "Start the depictio-frontend container or set "
                        "DEPICTIO_DASH_SERVICE_NAME to a reachable host."
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


async def generate_react_dual_theme_screenshots(
    dashboard_id: str,
    output_folder: str = "/app/depictio/dash/static/screenshots",
    user_id: str | None = None,
    open_settings: bool = False,
    filename_prefix: str = "react",
) -> ScreenshotResult:
    """Generate light + dark screenshots of the React beta viewer.

    Sibling of `generate_dual_theme_screenshots` (which targets the Dash app at
    `settings.dash.url`). This one drives the SPA bundle that FastAPI itself
    serves at `{settings.fastapi.url}/dashboard-beta/{id}`.

    Differences vs the Dash variant:
      • Origin / dashboard URL come from `settings.fastapi.*` (not `settings.dash`).
      • `theme-store` localStorage payload is `{"colorScheme": "<theme>"}` — the
        SPA's `readInitialColorScheme()` reads `parsed.colorScheme`, so the
        Dash-style bare string `"light"` would silently fall back to light.
      • Optional `open_settings=True` clicks the first `aria-label="Viz settings"`
        ActionIcon so the popover shows in the capture. Falls back to a normal
        shot if no popover exists. The Mantine popover is portaled to body, so
        we full-page capture in that case instead of cropping to AppShell.Main.

    Output filenames are `{filename_prefix}_{dashboard_id}_{theme}.png` (default
    prefix keeps them out of the way of the Dash auto-screenshot job which uses
    `{dashboard_id}_{theme}.png`).
    """
    if user_id:
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
    light_path = f"{output_folder}/{filename_prefix}_{dashboard_id}_light.png"
    dark_path = f"{output_folder}/{filename_prefix}_{dashboard_id}_dark.png"

    # The React SPA is served by the FastAPI process itself. Use `.url` so the
    # property picks internal vs external based on DEPICTIO_CONTEXT — inside
    # the API container this resolves to the docker DNS hostname, on a host
    # invocation it falls back to the external port.
    origin = settings.fastapi.url
    dashboard_url = f"{origin}/dashboard-beta/{dashboard_id}"

    try:
        token_data = await get_admin_auth_token()
        token_data_json = json.dumps(token_data)

        logger.info(f"React dual-theme screenshot: dashboard {dashboard_id} via {dashboard_url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})

            for theme, output_path in [("light", light_path), ("dark", dark_path)]:
                # SPA's readInitialColorScheme reads parsed.colorScheme — a bare
                # string like '"light"' parses to a string with no .colorScheme
                # property and silently falls back to light. Inject both
                # localStorage values via init script BEFORE any navigation:
                # hitting the bare origin would trigger the SPA's `isBareRoot`
                # redirect to /dashboards-beta and kill any page.evaluate
                # before it lands, so we can't set storage after the fact.
                theme_payload = json.dumps({"colorScheme": theme})
                init_script = (
                    f"localStorage.setItem('local-store', {json.dumps(token_data_json)});"
                    f"localStorage.setItem('theme-store', {json.dumps(theme_payload)});"
                )
                # Drop any prior init script (light pass) before adding the
                # dark-pass one, so the two themes don't stack.
                await context.clear_cookies()
                page = await context.new_page()
                await page.add_init_script(init_script)

                try:
                    await page.goto(
                        dashboard_url,
                        timeout=settings.performance.screenshot_navigation_timeout,
                    )
                except Exception as nav_err:
                    msg = str(nav_err)
                    if any(m in msg for m in _HOST_UNREACHABLE_MARKERS):
                        logger.warning(
                            f"FastAPI host ({origin}) unreachable — skipping React "
                            f"screenshot for {dashboard_id}."
                        )
                        await browser.close()
                        return {
                            "status": "skipped",
                            "light_screenshot": None,
                            "dark_screenshot": None,
                            "dashboard_id": dashboard_id,
                            "error": None,
                        }
                    raise

                # Wait for Mantine to apply the colour scheme before the viz
                # mounts — otherwise the first render flashes in the wrong
                # theme and the screenshot may catch the flash.
                try:
                    await page.wait_for_selector(
                        f'[data-mantine-color-scheme="{theme}"]',
                        timeout=settings.performance.screenshot_content_wait,
                    )
                except Exception:
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

                # Extra settling time for plotly to finish drawing.
                await page.wait_for_timeout(settings.performance.screenshot_stabilization_wait)

                await hide_ui_chrome(page)

                popover_open = False
                if open_settings:
                    popover_open = await _try_open_viz_settings(page)

                if popover_open:
                    # Mantine popovers portal to document.body, so they sit
                    # outside the AppShell.Main DOM bbox — element.screenshot()
                    # would clip them off. Fall back to a viewport capture.
                    await page.screenshot(path=output_path, full_page=False)
                else:
                    main_element = await page.query_selector(".mantine-AppShell-main")
                    if main_element:
                        await main_element.screenshot(path=output_path)
                    else:
                        await page.screenshot(path=output_path, full_page=False)

                # Fresh page per theme so the init-script (which sets the
                # theme key) re-runs cleanly on the next iteration.
                await page.close()

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
