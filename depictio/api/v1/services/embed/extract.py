"""Extract a component's Plotly figure from the real React renderer.

Same machinery as the dashboard screenshots (``screenshot_service``): the
worker's Playwright drives the viewer, with a token of the requester's own
rather than the admin's, but instead of capturing pixels it reads
``gd.data`` / ``gd.layout`` off the Plotly graph div. Same renderer, same
numbers, no reimplementation.

A renderer that is not Plotly (SVG, canvas, WebGL, plain HTML) has no figure
to read, so for those the same pass takes a PNG of the tile once the
renderer reports itself drawn (``data-embed-status`` on the embed page): a
static snapshot, which the notebook labels as one. ``expect`` says which of
the two the caller knows it wants; a tile expected to be Plotly that turns
out not to be still gets its snapshot rather than an error.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Literal
from urllib.parse import quote

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# A trace read straight off a live Plotly.js graph div can carry 8-digit hex
# colours (``#RRGGBBAA``, an alpha channel) — valid Plotly.js, not valid
# Python plotly (used below to round-trip the figure through go.Figure).
# Same fix as depictio.notebook.components._normalize_colors; duplicated
# rather than imported so this server module and the standalone notebook
# client keep their separate dependency footprints.
_HEX8_RE = re.compile(r"^#([0-9a-fA-F]{2}){4}$")


def _hex8_to_rgba(color: str) -> str:
    r, g, b, a = (int(color[i : i + 2], 16) for i in (1, 3, 5, 7))
    return f"rgba({r}, {g}, {b}, {a / 255:.3f})"


def _normalize_colors(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _normalize_colors(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_colors(v) for v in obj]
    if isinstance(obj, str) and _HEX8_RE.match(obj):
        return _hex8_to_rgba(obj)
    return obj


# JS evaluated in the embed page once the component reports ready. Typed
# arrays (plotly.js keeps large columns as Float64Array) are not JSON, so the
# replacer turns them into plain arrays.
_READ_FIGURE_JS = """
() => {
  const root = document.querySelector('[data-embed-status]');
  const status = root ? root.getAttribute('data-embed-status') : 'missing';
  const reason = root ? root.getAttribute('data-embed-reason') : null;
  const gd = document.querySelector('.js-plotly-plot');
  if (!gd || !gd.data) {
    return JSON.stringify({
      status: status === 'ready' ? 'unsupported' : status,
      figure: null,
      reason,
    });
  }
  const replacer = (_k, v) => (ArrayBuffer.isView(v) ? Array.from(v) : v);
  return JSON.stringify({ status: 'ready', figure: { data: gd.data, layout: gd.layout } }, replacer);
}
"""

# Wait until the embed has decided (the renderer reported itself drawn, and for
# a Plotly tile its graph div exists, or a terminal status) — polling the DOM is
# cheap and exits early on errors.
_SETTLED_JS = """
(expect) => {
  const root = document.querySelector('[data-embed-status]');
  if (!root) return false;
  const status = root.getAttribute('data-embed-status');
  if (status === 'error' || status === 'unsupported') return true;
  if (status !== 'ready') return false;
  if (expect === 'image') return true;
  const gd = document.querySelector('.js-plotly-plot');
  if (!gd) return false;
  return Boolean(gd.querySelector('.plot-container')) && Boolean(gd.data);
}
"""

_STATUS_JS = """
() => {
  const root = document.querySelector('[data-embed-status]');
  return root ? root.getAttribute('data-embed-status') : 'missing';
}
"""

Expect = Literal["plotly", "image"]

# WebGL renderers (3Dmol, GenomeSpy, deck.gl) need a software GL in a headless
# browser with no GPU; recent Chromium no longer falls back to SwiftShader on
# its own.
_LAUNCH_ARGS = ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]

# The tile's own frame on the embed page (ComponentFrameApp); the screenshot
# system targets the same class on the dashboard.
_TILE_SELECTOR = ".react-grid-item"
_SNAPSHOT_VIEWPORT = {"width": 1200, "height": 720}
_FIGURE_VIEWPORT = {"width": 1400, "height": 900}


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
        # leftovers or private keys never reach the client. go.Figure()
        # normalises (and, on a validation error, has been seen to pop
        # trace keys such as ``type`` off its input dict before raising) —
        # feed it a normalised copy, never the dict we fall back to below.
        try:
            import plotly.graph_objects as go

            normalized = _normalize_colors(json.loads(json.dumps(figure)))
            figure = json.loads(go.Figure(normalized, skip_invalid=True).to_json())
        except Exception as exc:  # keep the original raw dict rather than fail the whole job
            logger.debug(f"embed extract: plotly normalisation skipped: {exc}")
        return {"status": "ready", "figure": figure, "source": "extracted"}
    if status == "unsupported":
        return {
            "status": "unsupported",
            "figure": None,
            "reason": "this component does not draw a Plotly figure",
        }
    reason = payload.get("reason")
    return {
        "status": "error",
        "figure": None,
        "reason": f"the component reported an error: {reason}"
        if reason
        else f"embed page reported {status!r}",
    }


def snapshot_result(png: bytes) -> dict[str, Any]:
    """A ``ComponentFigureResponse`` dict carrying a PNG of the tile."""
    return {
        "status": "ready",
        "figure": None,
        "image": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
        "source": "snapshot",
    }


async def _snapshot(page: Any) -> bytes:
    """A PNG of the tile, once what it fetched has landed and it has painted."""
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:  # a renderer that keeps a connection open is still drawn
        pass
    # One more frame budget for canvas/WebGL renderers, which paint after their
    # data arrives rather than with it.
    await page.wait_for_timeout(800)
    tile = page.locator(_TILE_SELECTOR).first
    return await tile.screenshot(type="png", timeout=15000, animations="disabled")


async def extract_component_figure(
    dashboard_id: str,
    component_id: str,
    state: dict[str, Any],
    theme: str = "light",
    timeout_s: int | None = None,
    expect: Expect = "plotly",
    *,
    token_payload: dict[str, Any],
) -> dict[str, Any]:
    """Load the embed page headlessly and read its Plotly figure, or snapshot it.

    ``token_payload`` is the session the page runs with: the requester's own,
    minted for this pass (``task_tokens.browser_token_payload``), so the page
    shows what they may see and runs with no more rights than theirs.
    """
    from playwright.async_api import async_playwright

    from depictio.api.v1.services.screenshot_helpers import (
        HOST_UNREACHABLE_MARKERS,
        apply_init_script,
    )

    timeout_s = timeout_s or settings.notebook_export.extract_timeout_s
    url = embed_url(settings.viewer.url, dashboard_id, component_id, state, theme)
    token_data = token_payload
    logger.info(f"embed extract: {dashboard_id}/{component_id} via {url.split('#')[0]}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        try:
            viewport = _SNAPSHOT_VIEWPORT if expect == "image" else _FIGURE_VIEWPORT
            context = await browser.new_context(viewport=viewport)
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
                await page.wait_for_function(_SETTLED_JS, arg=expect, timeout=timeout_s * 1000)
            except Exception:
                # Drawn, but no Plotly div after all: the renderer is not Plotly
                # (or not on this view), and its picture is still worth having.
                if await page.evaluate(_STATUS_JS) == "ready":
                    return snapshot_result(await _snapshot(page))
                return {
                    "status": "error",
                    "figure": None,
                    "reason": f"the component did not render within {timeout_s}s",
                }
            raw = await page.evaluate(_READ_FIGURE_JS)
            result = parse_extracted(raw)
            if result["status"] == "unsupported" or (
                expect == "image" and result["status"] == "ready"
            ):
                return snapshot_result(await _snapshot(page))
            return result
        finally:
            await browser.close()
