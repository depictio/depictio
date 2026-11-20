"""Resolve Iconify icon ids to inline SVG markup.

Depictio stores icons as Iconify ids (``mdi:counter``, ``mdi:chart-donut``...)
everywhere a card, section or component picks one; the SPA draws them from an
icon subset bundled at build time (``viewer/scripts/generate-icon-subset.mjs``,
which scans the sources and every shipped dashboard). A notebook export has no
browser, so it reads the same subset, written as JSON next to the API
(``viewer/dist-icons/icon-subset.json``): the icons the viewer can draw are
exactly the ones the export can draw, with no network.

Only an id the subset lacks (a dashboard imported with an icon no shipped
dashboard uses, which the viewer itself shows blank) is asked of Iconify's
public API: all such ids at once, under one short time budget, and only
successes are remembered, so a network blip costs one export an icon rather
than blanking it until the process restarts. An air-gapped instance simply
gets no icon for those.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, wait
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import httpx

from depictio.api.v1.configs.logging_init import logger

ICONIFY_API = "https://api.iconify.design"

#: The viewer's icon subset as JSON, ``{"prefix:name": {body, width, height}}``.
SUBSET_PATH = Path(__file__).resolve().parents[3] / "viewer" / "dist-icons" / "icon-subset.json"

#: Total wall-clock budget for the Iconify fallback of one call, in seconds.
FALLBACK_BUDGET_S = 3.0
_FALLBACK_WORKERS = 8

# Successful network fetches only: a failure is never cached.
_fetched: dict[str, str] = {}


def _svg(body: str, width: object = 24, height: object = 24) -> str:
    # currentColor + no fixed size: the caller colours and sizes it with CSS
    # (icon_color, a font-size-matched em box), the same way @iconify/react
    # renders it in the SPA.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="1em" height="1em" fill="currentColor">{body}</svg>'
    )


@lru_cache(maxsize=4)
def _load_subset(path: str) -> dict[str, dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.info(
            f"icons: no bundled icon subset at {path} (build the viewer, or `pnpm --filter "
            "depictio-viewer icons`); falling back to the Iconify API"
        )
        return {}
    except Exception as exc:  # a corrupt file is not worth failing an export over
        logger.warning(f"icons: unreadable icon subset at {path}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def bundled_icon(icon_id: str) -> str | None:
    """One icon from the bundled subset, as SVG, or ``None`` when it is not there."""
    icon = _load_subset(str(SUBSET_PATH)).get(icon_id)
    if not isinstance(icon, dict) or "body" not in icon:
        return None
    return _svg(icon["body"], icon.get("width", 24), icon.get("height", 24))


def _fetch_icon_svg(icon_id: str) -> str | None:
    """One icon from the Iconify API, or ``None``. Successes are remembered."""
    if icon_id in _fetched:
        return _fetched[icon_id]
    if ":" not in icon_id:
        return None
    prefix, name = icon_id.split(":", 1)
    try:
        resp = httpx.get(f"{ICONIFY_API}/{prefix}.json", params={"icons": name}, timeout=2.5)
        resp.raise_for_status()
        icon = (resp.json().get("icons") or {}).get(name)
    except Exception as exc:  # network down, icon set unknown, rate-limited...
        logger.debug(f"icon resolve failed for {icon_id!r}: {exc}")
        return None
    if not icon or "body" not in icon:
        return None
    svg = _svg(icon["body"], icon.get("width", 24), icon.get("height", 24))
    _fetched[icon_id] = svg
    return svg


def resolve_icons(icon_ids: Iterable[str | None], *, network: bool = True) -> dict[str, str]:
    """``{icon_id: svg}`` for every resolvable id in ``icon_ids``.

    The bundled subset first; the misses from Iconify in parallel within
    ``FALLBACK_BUDGET_S`` when ``network``. Unresolvable ids are omitted rather
    than raising: a missing icon degrades to no icon, never a broken export.
    """
    out: dict[str, str] = {}
    misses: list[str] = []
    for icon_id in {i for i in icon_ids if i}:
        svg = bundled_icon(icon_id) or _fetched.get(icon_id)
        if svg:
            out[icon_id] = svg
        elif ":" in icon_id:
            misses.append(icon_id)
    if not misses or not network:
        return out
    pool = ThreadPoolExecutor(max_workers=min(_FALLBACK_WORKERS, len(misses)))
    try:
        futures = {pool.submit(_fetch_icon_svg, i): i for i in misses}
        done, _ = wait(futures, timeout=FALLBACK_BUDGET_S)
        for future in done:
            svg = future.result()
            if svg:
                out[futures[future]] = svg
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out
