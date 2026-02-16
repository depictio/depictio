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

    status: str  # "success" or "error"
    dashboard_id: str
    light_screenshot: str | None
    dark_screenshot: str | None
    error: str | None


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
        timeout=10000,
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

            # Set authentication token before navigation
            await page.goto(settings.dash.internal_url)
            await page.evaluate(f"localStorage.setItem('local-store', '{token_data_json}')")

            # Capture both themes in sequence
            for theme, output_path in [("light", light_path), ("dark", dark_path)]:
                if theme == "light":
                    # Navigate to dashboard first, then set theme and reload
                    await page.goto(dashboard_url, timeout=30000)

                await page.evaluate(
                    f"localStorage.setItem('theme-store', JSON.stringify('{theme}'))"
                )
                await page.reload(timeout=30000)

                # Wait for MantineProvider to apply theme
                try:
                    await page.wait_for_selector(
                        f'[data-mantine-color-scheme="{theme}"]', timeout=10000
                    )
                    await page.wait_for_timeout(500)
                except Exception:
                    logger.warning(
                        f"Timeout waiting for {theme} theme attribute, using fallback wait"
                    )
                    await page.wait_for_timeout(7000)

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
