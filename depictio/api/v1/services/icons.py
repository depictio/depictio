"""Resolve Iconify icon ids to inline SVG markup.

Depictio stores icons as Iconify ids (``mdi:counter``, ``mdi:chart-donut``...)
everywhere a card, section or component picks one; nothing in the backend
draws them today — the SPA does, via ``@iconify/react``, choosing from
whichever npm icon sets are installed. A notebook export has no npm icon set
and no browser, so it cannot do the same. What it *can* do is ask Iconify's
public API for the one glyph it needs and bake the returned SVG in as a
literal string, once, server-side — the same "fetch once, embed the result"
shape as every other piece of this feature (figures, cards). The dashboard
author picks from thousands of possible icons, so bundling them all is not
an option; resolving on demand, cached, is.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable

import httpx

from depictio.api.v1.configs.logging_init import logger

ICONIFY_API = "https://api.iconify.design"


@lru_cache(maxsize=1024)
def _fetch_icon_svg(icon_id: str) -> str | None:
    """One icon's SVG markup, or ``None`` if it cannot be resolved.

    Process-level cache: a handful of icon ids repeat across a dashboard's
    cards and sections, and across every export/render of it, so there is no
    reason to ask Iconify twice for the same glyph in one server lifetime.
    """
    if ":" not in icon_id:
        return None
    prefix, name = icon_id.split(":", 1)
    try:
        resp = httpx.get(f"{ICONIFY_API}/{prefix}.json", params={"icons": name}, timeout=5.0)
        resp.raise_for_status()
        icon = (resp.json().get("icons") or {}).get(name)
    except Exception as exc:  # network down, icon set unknown, rate-limited...
        logger.debug(f"icon resolve failed for {icon_id!r}: {exc}")
        return None
    if not icon or "body" not in icon:
        return None
    width = icon.get("width", 24)
    height = icon.get("height", 24)
    # currentColor + no fixed size: the caller colours and sizes it with CSS
    # (icon_color, a font-size-matched em box), the same way @iconify/react
    # renders it in the SPA.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="1em" height="1em" fill="currentColor">{icon["body"]}</svg>'
    )


def resolve_icons(icon_ids: Iterable[str | None]) -> dict[str, str]:
    """``{icon_id: svg}`` for every resolvable id in ``icon_ids``.

    Unresolvable ids (network failure, unknown prefix, blank) are silently
    omitted rather than raising: a missing icon should degrade to no icon,
    not break the card or the export around it.
    """
    out: dict[str, str] = {}
    for icon_id in {i for i in icon_ids if i}:
        svg = _fetch_icon_svg(icon_id)
        if svg:
            out[icon_id] = svg
    return out
