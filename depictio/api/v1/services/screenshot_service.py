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

from playwright.async_api import Page, async_playwright

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.users import TokenBeanie, UserBeanie


class ScreenshotResult(TypedDict):
    """Result of dual-theme screenshot generation."""

    status: str  # "success" or "error"
    dashboard_id: str
    light_screenshot: str | None
    dark_screenshot: str | None
    error: str | None


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
    dashboard_id: str, output_folder: str = "/app/depictio/dash/static/screenshots"
) -> ScreenshotResult:
    """
    Generate both light and dark mode screenshots in single browser call.

    This function creates dual-theme screenshots ({dashboard_id}_light.png and
    {dashboard_id}_dark.png) in a single Playwright session, reusing the browser
    context for efficiency (~40% time savings vs. two separate calls).

    Strategy:
    1. Launch browser and authenticate with admin token
    2. Navigate to dashboard in light mode, hide UI chrome, screenshot
    3. Reload with dark mode theme, hide UI chrome, screenshot
    4. Both screenshots saved to output_folder

    Args:
        dashboard_id: Dashboard ID to screenshot
        output_folder: Directory to save screenshots (default: /app/depictio/dash/static/screenshots)

    Returns:
        ScreenshotResult: Dict with status, dashboard_id, screenshot paths, and optional error
    """
    Path(output_folder).mkdir(parents=True, exist_ok=True)

    light_path = f"{output_folder}/{dashboard_id}_light.png"
    dark_path = f"{output_folder}/{dashboard_id}_dark.png"

    try:
        # Get admin authentication token
        token_data = await get_admin_auth_token()
        token_data_json = json.dumps(token_data)
        dashboard_url = f"{settings.dash.internal_url}/dashboard/{dashboard_id}"

        logger.info(f"📸 Starting dual-theme screenshot for dashboard: {dashboard_id}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})

            # Set authentication token before navigation
            await page.goto(settings.dash.internal_url)
            await page.evaluate(f"localStorage.setItem('local-store', '{token_data_json}')")

            # --- LIGHT MODE SCREENSHOT ---
            logger.info("📸 Phase 1: Capturing light mode screenshot...")
            # Navigate to dashboard first
            await page.goto(dashboard_url, timeout=30000)  # wait_until defaults to "load"

            # Set theme AFTER navigation - JSON serialized to match dcc.Store format
            await page.evaluate("localStorage.setItem('theme-store', JSON.stringify('light'))")
            # Reload to apply theme
            await page.reload(timeout=30000)

            # Wait for MantineProvider to apply light theme
            try:
                await page.wait_for_selector('[data-mantine-color-scheme="light"]', timeout=10000)
                logger.info("✅ Light theme applied (data-mantine-color-scheme='light')")
                # Wait for CSS transitions to complete (200ms transitions + buffer)
                await page.wait_for_timeout(500)
                # Verify theme applied
                theme_value = await page.evaluate(
                    """
                    () => document.querySelector('[data-mantine-color-scheme]')?.getAttribute('data-mantine-color-scheme')
                """
                )
                logger.info(f"✅ Verified light theme attribute: {theme_value}")
            except Exception as e:
                logger.warning(f"⚠️ Timeout waiting for light theme attribute: {e}")
                # Fallback: wait for timeout
                await page.wait_for_timeout(7000)
            try:
                await wait_for_dashboard_content(page)
                logger.info("✅ Dashboard components rendered (light mode)")
            except Exception as e:
                logger.warning(f"⚠️ Timeout waiting for components (light mode): {e}")

            # Hide UI chrome and take screenshot
            await hide_ui_chrome(page)
            main_element = await page.query_selector(".mantine-AppShell-main")
            if main_element:
                await main_element.screenshot(path=light_path)
                logger.info(f"✅ Light mode screenshot saved: {light_path}")
            else:
                await page.screenshot(path=light_path, full_page=True)
                logger.info(f"✅ Light mode screenshot saved (fallback): {light_path}")

            # --- DARK MODE SCREENSHOT ---
            logger.info("📸 Phase 2: Capturing dark mode screenshot...")
            # Set theme - JSON serialized to match dcc.Store format
            await page.evaluate("localStorage.setItem('theme-store', JSON.stringify('dark'))")
            # Reload to apply theme
            await page.reload(timeout=30000)

            # Wait for MantineProvider to apply dark theme
            try:
                await page.wait_for_selector('[data-mantine-color-scheme="dark"]', timeout=10000)
                logger.info("✅ Dark theme applied (data-mantine-color-scheme='dark')")
                # Wait for CSS transitions to complete (200ms transitions + buffer)
                await page.wait_for_timeout(500)
                # Verify theme applied
                theme_value = await page.evaluate(
                    """
                    () => document.querySelector('[data-mantine-color-scheme]')?.getAttribute('data-mantine-color-scheme')
                """
                )
                logger.info(f"✅ Verified dark theme attribute: {theme_value}")
            except Exception as e:
                logger.warning(f"⚠️ Timeout waiting for dark theme attribute: {e}")
                # Fallback: wait for timeout
                await page.wait_for_timeout(7000)
            try:
                await wait_for_dashboard_content(page)
                logger.info("✅ Dashboard components rendered (dark mode)")
            except Exception as e:
                logger.warning(f"⚠️ Timeout waiting for components (dark mode): {e}")

            # Hide UI chrome and take screenshot
            await hide_ui_chrome(page)
            main_element = await page.query_selector(".mantine-AppShell-main")
            if main_element:
                await main_element.screenshot(path=dark_path)
                logger.info(f"✅ Dark mode screenshot saved: {dark_path}")
            else:
                await page.screenshot(path=dark_path, full_page=True)
                logger.info(f"✅ Dark mode screenshot saved (fallback): {dark_path}")

            await browser.close()
            logger.info(f"📸 Dual-theme screenshot completed for dashboard: {dashboard_id}")

        result: ScreenshotResult = {
            "status": "success",
            "light_screenshot": light_path,
            "dark_screenshot": dark_path,
            "dashboard_id": dashboard_id,
            "error": None,
        }
        return result

    except Exception as e:
        logger.error(f"❌ Dual-theme screenshot error for {dashboard_id}: {str(e)}")
        error_result: ScreenshotResult = {
            "status": "error",
            "dashboard_id": dashboard_id,
            "light_screenshot": None,
            "dark_screenshot": None,
            "error": str(e),
        }
        return error_result
