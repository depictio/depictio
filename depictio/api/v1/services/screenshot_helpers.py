"""Shared Playwright primitives for screenshot capture.

Sits below `screenshot_service.py` (which holds the public dual-theme
generators) and `dev/playwright_debug/docs_screenshots.py` (which drives the
Vite dev server for documentation captures). Both call the same Mantine
AppShell / SPA, so the wait / hide / inject patterns are identical.

What lives here:
  * Atomic localStorage init-script builder (auth + theme set before any
    page script runs — the SPA's `readInitialColorScheme()` and the API
    bootstrap both read localStorage on first paint, so post-navigation
    `page.evaluate` is too late).
  * Theme-applied wait (resolves on `data-mantine-color-scheme` attribute).
  * Grid-content wait (a `.react-grid-item` exists with non-zero bbox).
  * UI chrome hider (navbar/header/debug menu/AppShell padding).
  * Mantine notification dismisser (kills toast banners that would
    otherwise clutter the shot).
  * `HOST_UNREACHABLE_MARKERS` Playwright error-substring tuple so callers
    can treat "container not running" as `status="skipped"` instead of
    failing the task.

What does NOT live here (intentional security split):
  * Token loaders. The backend service reads from MongoDB inside the API
    container; the dev script reads from `admin_config.yaml` on the host.
    They run in different trust boundaries — sharing a loader couples the
    two and forces the API process to expose a file path it shouldn't
    care about. Keep them adjacent to their callers.
"""

from __future__ import annotations

import json

from playwright.async_api import BrowserContext, Page

from depictio.api.v1.configs.config import settings

HOST_UNREACHABLE_MARKERS: tuple[str, ...] = (
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT",
)


def build_localstorage_init_script(token_payload_json: str, theme: str) -> str:
    """Return a JS snippet that seeds `local-store` + `theme-store` in
    localStorage atomically. Inject via `context.add_init_script(...)` (or
    `page.add_init_script`) BEFORE the first navigation, so the SPA's
    first render reads the correct auth + colour scheme.

    `theme-store` is written as the JSON shape `{"colorScheme": "<theme>"}`
    that `readInitialColorScheme()` parses. A bare-string value like
    `"light"` would parse to a string with no `.colorScheme` property and
    silently fall back to light mode — that's the bug we hit when the
    React variant first landed.
    """
    theme_payload = json.dumps({"colorScheme": theme})
    return (
        f"localStorage.setItem('local-store', {json.dumps(token_payload_json)});"
        f"localStorage.setItem('theme-store', {json.dumps(theme_payload)});"
    )


async def apply_init_script(context: BrowserContext, token_payload_json: str, theme: str) -> None:
    """Convenience: build + attach the init script to a fresh context."""
    await context.add_init_script(build_localstorage_init_script(token_payload_json, theme))


async def wait_for_theme_applied(page: Page, theme: str) -> bool:
    """Wait for MantineProvider to apply the colour scheme before capture.

    Returns True on success, False on timeout (caller decides whether to
    proceed with a flash risk or skip the shot). Uses the same content
    timeout as the grid-render wait so the two budgets stay aligned.
    """
    try:
        await page.wait_for_selector(
            f'[data-mantine-color-scheme="{theme}"]',
            timeout=settings.performance.screenshot_content_wait,
        )
        return True
    except Exception:
        return False


async def wait_for_dashboard_content(page: Page) -> None:
    """Wait until at least one `.react-grid-item` has non-zero dimensions.

    Both the Dash app and the React SPA wrap dashboard children in
    react-grid-layout, so the selector is the same on both stacks. Times
    out via the screenshot_content_wait setting — caller can swallow
    the exception if a partial shot is acceptable.
    """
    await page.wait_for_function(
        """() => {
            const components = document.querySelectorAll('.react-grid-item');
            if (components.length === 0) return false;
            for (const c of components) {
                const r = c.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) return true;
            }
            return false;
        }""",
        timeout=settings.performance.screenshot_content_wait,
    )


async def wait_for_plotly_drawn(page: Page, timeout_ms: int = 3000) -> bool:
    """Block until every `.plotly-graph-div` on the page has finished its
    first paint, or the timeout elapses.

    Plotly attaches a `<div class="plot-container">` child synchronously
    once the figure mounts; until then the wrapper is empty. Polling that
    structural marker is cheap, works for both Dash and the React SPA,
    and exits immediately when there are zero plotly figures on the page
    (e.g. a card-only dashboard). Caller decides how to react to a
    timeout — typically log + continue with a slightly half-drawn capture.
    """
    try:
        await page.wait_for_function(
            """() => {
                const figs = document.querySelectorAll('.plotly-graph-div');
                if (figs.length === 0) return true;
                for (const f of figs) {
                    if (!f.querySelector('.plot-container')) return false;
                }
                return true;
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


async def hide_ui_chrome(page: Page) -> None:
    """Hide navbar, header, Dash debug menu, walkthrough overlays, and zero out AppShell padding.

    The walkthrough strip is defensive: the React `WalkthroughHost` already
    honours `?no-walkthrough=1` and the screenshot pipeline appends that
    flag, but if either the gate races the mount or a stale DOM lingers,
    these selectors guarantee no popover/backdrop/anchor survives into the
    captured PNG.
    """
    await page.evaluate(
        """() => {
            const sel = (q) => document.querySelector(q);
            const navbar = sel('.mantine-AppShell-navbar');
            if (navbar) navbar.style.display = 'none';
            const header = sel('.mantine-AppShell-header');
            if (header) header.style.display = 'none';
            const debugMenu = sel('.dash-debug-menu__outer');
            if (debugMenu) debugMenu.style.display = 'none';
            document.querySelectorAll('[data-walkthrough]').forEach((el) => {
                el.style.display = 'none';
            });
            document.querySelectorAll('.depictio-walkthrough-popover').forEach((el) => {
                el.style.display = 'none';
            });
            const pageContent = sel('#page-content');
            if (pageContent) {
                pageContent.style.padding = '0';
                pageContent.style.margin = '0';
            }
            const main = sel('.mantine-AppShell-main');
            if (main) {
                main.style.padding = '0';
                main.style.paddingLeft = '0';
                main.style.margin = '0';
            }
        }"""
    )


async def dismiss_notifications(page: Page) -> None:
    """Strip any visible Mantine notifications before screenshotting.

    Some endpoints (e.g. /links/{project_id} in single-user mode) surface
    red toasts that would otherwise sit on top of the captured viewport.
    """
    await page.evaluate(
        """() => {
            document.querySelectorAll(
                '[data-mantine-notification-root],'
                + ' .mantine-Notifications-notification,'
                + ' .mantine-Notification-root'
            ).forEach(n => n.remove());
        }"""
    )
