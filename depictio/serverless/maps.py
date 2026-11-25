"""Frozen map tiles, shared by both producers.

A map ships as the server's own ``render_map`` figure at the default filter
state, with the dashboard's **own** ``map_style``: the basemap (OpenStreetMap,
Carto) loads from its tile host when the reader is online, exactly as on the
instance. A bundle used to force ``white-bg`` so that it never reached the
network, which took the basemap away from every reader to spare the offline
ones a blank background.

Offline, the static runtime (``depictio/viewer/src/static-runtime/
mapBasemap.ts``) probes the basemap host first and, when it cannot be reached,
draws the same markers on a plain background in the reader's theme instead of
handing MapLibre a style URL it can never load (which would leave the map
without its markers too). The only hosts a map tile may contact are
``BASEMAP_HOSTS``; the e2e offline specs allow exactly those.
"""

from __future__ import annotations

import json
from typing import Any

#: Every host a basemap style Depictio offers reaches (``MAP_STYLES`` in
#: ``depictio/models/components/constants.py``): Carto's style.json on the apex,
#: its glyphs/sprite/TileJSON and vector tiles on the subdomains, and the
#: OpenStreetMap raster tiles. Mirrors ``BASEMAP_CONNECT_SRC`` (the served
#: app's CSP) and ``BASEMAP_HOSTS`` in ``mapBasemap.ts``.
BASEMAP_HOSTS: tuple[str, ...] = (
    "basemaps.cartocdn.com",
    "tiles.basemaps.cartocdn.com",
    "tiles-a.basemaps.cartocdn.com",
    "tiles-b.basemaps.cartocdn.com",
    "tiles-c.basemaps.cartocdn.com",
    "tiles-d.basemaps.cartocdn.com",
    "tile.openstreetmap.org",
)

#: The tier detail every frozen map carries (producer A's planner, producer B's
#: preflight and the manifest all say the same thing).
MAP_FROZEN_DETAIL = (
    "frozen at the exported filter state with the dashboard's own basemap, which "
    "loads from its tile host when the reader is online; offline, the same "
    "markers draw on a blank background"
)

#: Map types producer B can render from the bundled table alone. A choropleth
#: also needs its region geometry, which lives in a GeoJSON data collection or
#: behind a URL the build-from-spec producer does not fetch.
TABLE_ONLY_MAP_TYPES = frozenset({"scatter_map", "density_map"})


def freeze_map_payload(
    comp: dict[str, Any], df: Any, category_colors: dict | None = None
) -> dict[str, Any]:
    """``render_map`` at the default filter state, as a frozen ``map`` payload.

    ``comp`` goes to ``render_map`` as its ``trigger_data`` unchanged, so the
    figure keeps the component's ``map_style`` (the light-theme spelling of it:
    ``render_map`` maps ``carto-darkmatter`` to ``carto-positron`` under the
    light theme it is rendered with, and the runtime swaps it back for a dark
    reader, the rule ``render_map`` applies live).
    """
    from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates
    from depictio.api.v1.services.map.render import render_map

    ensure_mantine_templates()
    fig, data_info = render_map(
        df=df,
        trigger_data=dict(comp),
        theme="light",
        existing_metadata=None,
        access_token=None,
        category_colors=category_colors,
    )
    fig_dict = json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")
    return {
        "figure": fig_dict,
        "metadata": {
            "map_type": comp.get("map_type", "scatter_map"),
            "filter_applied": False,
            "displayed_count": data_info.get("displayed_count"),
            "total_count": data_info.get("total_count"),
        },
    }
