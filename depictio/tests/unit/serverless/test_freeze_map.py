"""A map is frozen with the server's own ``render_map``, not omitted.

``_freeze_map`` passed ``active_selection_values``, a keyword ``render_map``
no longer takes, so every map in an export raised and was dropped while the
preflight still promised a frozen tile.
"""

from __future__ import annotations

from types import SimpleNamespace

import polars as pl

from depictio.serverless import producer_a

COMP = {
    "index": "map-1",
    "component_type": "map",
    "dc_id": "64b000000000000000000001",
    "wf_id": "64b000000000000000000002",
    "map_type": "scatter_map",
    "lat_column": "lat",
    "lon_column": "lon",
    "color_column": "site",
    "map_style": "carto-positron",
}


def test_freeze_map_renders_offline_with_family_colours(monkeypatch) -> None:
    df = pl.DataFrame({"lat": [48.5, 49.0], "lon": [7.7, 8.4], "site": ["A", "B"]})
    monkeypatch.setattr(producer_a, "_dc_init_entry", lambda comp: {"delta_location": "x"})
    monkeypatch.setattr(
        producer_a, "_dtu", lambda: SimpleNamespace(load_deltatable_lite=lambda **_: df)
    )
    out = producer_a._freeze_map(COMP, user=None, category_colors={"site": {"A": "#ff0000"}})

    layout = out["figure"]["layout"]
    assert layout["map"]["style"] == "white-bg"  # no tile server in a bundle
    assert out["metadata"]["map_type"] == "scatter_map"
    assert out["metadata"]["displayed_count"] == 2
    colours = {t.get("name"): t.get("marker", {}).get("color") for t in out["figure"]["data"]}
    assert colours.get("A") == "#ff0000"
