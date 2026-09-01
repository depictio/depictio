"""Extract a component's Plotly figure from the real React renderer.

Same machinery as the dashboard screenshots (``screenshot_service``): the
worker's Playwright drives the viewer with the admin token, but instead of
capturing pixels it reads ``gd.data`` / ``gd.layout`` off the Plotly graph
div. Same renderer, same numbers, no reimplementation.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# JS evaluated in the embed page once the component reports ready. Typed
# arrays (plotly.js keeps large columns as Float64Array) are not JSON, so the
# replacer turns them into plain arrays.
_READ_FIGURE_JS = """
() => {
  const root = document.querySelector('[data-embed-status]');
  const status = root ? root.getAttribute('data-embed-status') : 'missing';
  const gd = document.querySelector('.js-plotly-plot');
  if (!gd || !gd.data) {
    return JSON.stringify({ status: status === 'ready' ? 'unsupported' : status, figure: null });
  }
  const replacer = (_k, v) => (ArrayBuffer.isView(v) ? Array.from(v) : v);
  return JSON.stringify({ status: 'ready', figure: { data: gd.data, layout: gd.layout } }, replacer);
}
"""

# Wait until the embed has decided (ready with a drawn Plotly div, or a
# terminal status) — polling the DOM is cheap and exits early on errors.
_SETTLED_JS = """
() => {
  const root = document.querySelector('[data-embed-status]');
  if (!root) return false;
  const status = root.getAttribute('data-embed-status');
  if (status === 'error' || status === 'unsupported') return true;
  if (status !== 'ready') return false;
  const gd = document.querySelector('.js-plotly-plot');
  if (!gd) return false;
  return Boolean(gd.querySelector('.plot-container')) && Boolean(gd.data);
}
"""


def encode_state(state: dict[str, Any]) -> str:
    """URL-safe base64 of the state JSON, as the embed page decodes it."""
    raw = json.dumps(state, separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def embed_url(
    origin: str, dashboard_id: str, component_id: str, state: dict[str, Any], theme: str
) -> str:
    return (
        f"{origin.rstrip('/')}/embed/{quote(str(dashboard_id))}/{quote(str(component_id))}"
        f"?no-walkthrough=1#state={encode_state(state)}&theme={theme}"
    )


def parse_extracted(raw: str) -> dict[str, Any]:
    """Normalise what ``_READ_FIGURE_JS`` returned into a ``ComponentFigureResponse`` dict."""
    payload = json.loads(raw)
    status = payload.get("status")
    figure = payload.get("figure")
    if status == "ready" and figure:
        # Round-trip through plotly so the dict validates and typed-array
        # leftovers or private keys never reach the client.
        try:
            import plotly.graph_objects as go

            figure = json.loads(go.Figure(figure).to_json())
        except Exception as exc:  # keep the raw dict rather than fail the whole job
            logger.debug(f"embed extract: plotly normalisation skipped: {exc}")
        return {"status": "ready", "figure": figure, "source": "extracted"}
    if status == "unsupported":
        return {
            "status": "unsupported",
            "figure": None,
            "reason": "this component does not draw a Plotly figure",
        }
    return {"status": "error", "figure": None, "reason": f"embed page reported {status!r}"}


async def extract_component_figure(
    dashboard_id: str,
    component_id: str,
    state: dict[str, Any],
    theme: str = "light",
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Load the embed page headlessly and read its Plotly figure."""
    from playwright.async_api import async_playwright

    from depictio.api.v1.services.screenshot_helpers import (
        HOST_UNREACHABLE_MARKERS,
        apply_init_script,
    )
    from depictio.api.v1.services.screenshot_service import get_admin_auth_token

    timeout_s = timeout_s or settings.notebook_export.extract_timeout_s
    url = embed_url(settings.viewer.url, dashboard_id, component_id, state, theme)
    token_data = await get_admin_auth_token()
    logger.info(f"embed extract: {dashboard_id}/{component_id} via {url.split('#')[0]}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1400, "height": 900})
            await apply_init_script(context, json.dumps(token_data), theme)
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            except Exception as nav_err:
                if any(m in str(nav_err) for m in HOST_UNREACHABLE_MARKERS):
                    return {
                        "status": "error",
                        "figure": None,
                        "reason": f"viewer unreachable at {settings.viewer.url}",
                    }
                raise
            try:
                await page.wait_for_function(_SETTLED_JS, timeout=timeout_s * 1000)
            except Exception:
                return {
                    "status": "error",
                    "figure": None,
                    "reason": f"the component did not render within {timeout_s}s",
                }
            raw = await page.evaluate(_READ_FIGURE_JS)
            return parse_extracted(raw)
        finally:
            await browser.close()
