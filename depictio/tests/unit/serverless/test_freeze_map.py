"""A map is frozen with the server's own ``render_map``, not omitted.

``_freeze_map`` passed ``active_selection_values``, a keyword ``render_map``
no longer takes, so every map in an export raised and was dropped while the
preflight still promised a frozen tile.

It keeps the dashboard's own ``map_style``: bundles used to force ``white-bg``,
which took the basemap away from every online reader (the static runtime now
draws the markers on a blank background only when the tile host is out of
reach, ``static-runtime/mapBasemap.ts``). Producer B freezes point maps the
same way, from the spec's data.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from depictio.models.models.serverless import ComponentTier, TierReason
from depictio.serverless import producer_a
from depictio.serverless.maps import MAP_FROZEN_DETAIL
from depictio.serverless.preflight import classify_component

REPO_ROOT = Path(__file__).resolve().parents[4]
MAP_SPEC = REPO_ROOT / "depictio" / "serverless" / "examples" / "map.yaml"
MAP_CSV = REPO_ROOT / "depictio" / "projects" / "test" / "map_demo" / "sampling_locations.csv"

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
    assert layout["map"]["style"] == "carto-positron"  # the dashboard's own basemap
    assert out["metadata"]["map_type"] == "scatter_map"
    assert out["metadata"]["displayed_count"] == 2
    colours = {t.get("name"): t.get("marker", {}).get("color") for t in out["figure"]["data"]}
    assert colours.get("A") == "#ff0000"


@pytest.mark.parametrize("style", ["open-street-map", "carto-voyager", "white-bg"])
def test_freeze_map_keeps_any_authored_basemap(monkeypatch, style: str) -> None:
    df = pl.DataFrame({"lat": [48.5, 49.0], "lon": [7.7, 8.4], "site": ["A", "B"]})
    monkeypatch.setattr(producer_a, "_dc_init_entry", lambda comp: {"delta_location": "x"})
    monkeypatch.setattr(
        producer_a, "_dtu", lambda: SimpleNamespace(load_deltatable_lite=lambda **_: df)
    )
    out = producer_a._freeze_map({**COMP, "map_style": style}, user=None)
    assert out["figure"]["layout"]["map"]["style"] == style


def test_planned_map_tier_no_longer_promises_a_zero_network_tile() -> None:
    plan = producer_a.classify_stored_component({"component_type": "map"})
    assert plan.tier is ComponentTier.FROZEN and plan.reason is TierReason.MAP_TILES
    assert plan.detail == MAP_FROZEN_DETAIL
    assert "white-bg" not in plan.detail and "zero-network" not in plan.detail


def test_producer_b_freezes_point_maps_and_names_why_a_choropleth_is_omitted() -> None:
    point = classify_component({"component_type": "map", "map_type": "scatter_map"})
    assert point.tier is ComponentTier.FROZEN and point.detail == MAP_FROZEN_DETAIL
    assert classify_component({"component_type": "map"}).tier is ComponentTier.FROZEN
    region = classify_component({"component_type": "map", "map_type": "choropleth_map"})
    assert region.tier is ComponentTier.OMITTED
    assert region.detail and "region geometry" in region.detail


def test_producer_b_map_bundle_keeps_the_basemap_and_family_colours(tmp_path: Path) -> None:
    from depictio.serverless.producer_b import build_manifest, load_spec

    (tmp_path / "map_demo").mkdir()
    pl.read_csv(MAP_CSV).write_parquet(tmp_path / "map_demo" / "sampling_locations.parquet")
    manifest = build_manifest(load_spec(MAP_SPEC), tmp_path).manifest

    assert manifest.tiers["sampling-map"].tier is ComponentTier.FROZEN
    frozen = manifest.frozen["sampling-map"]
    assert frozen.kind == "map"
    figure = frozen.payload["figure"]
    assert figure["layout"]["map"]["style"] == "carto-positron"
    colours = {t.get("name"): t.get("marker", {}).get("color") for t in figure["data"]}
    assert colours["urban"] == "#e8590c" and colours["marine"] == "#1c7ed6"
    assert frozen.payload["metadata"]["displayed_count"] == 24
    # The map reads its table at build time; the bundled copy is the live
    # components' (card + filter), pruned to their columns.
    (ref,) = manifest.data_refs.values()
    assert {c.name for c in ref.columns} <= {"sample_id", "biome"}


def test_producer_b_ui_figures_draw_in_the_spec_category_colours(tmp_path: Path) -> None:
    """A ui figure colouring by a column the spec pins gets the pins, as the
    render endpoint merges a dashboard's ``category_colors`` live."""
    import yaml

    from depictio.models.models.dashboards import DashboardDataLite
    from depictio.serverless.producer_b import build_manifest

    (tmp_path / "map_demo").mkdir()
    pl.read_csv(MAP_CSV).write_parquet(tmp_path / "map_demo" / "sampling_locations.parquet")
    spec = yaml.safe_load(MAP_SPEC.read_text())
    spec["components"].append(
        {
            "tag": "depth-scatter",
            "component_type": "figure",
            "workflow_tag": "map_demo",
            "data_collection_tag": "sampling_locations",
            "visu_type": "scatter",
            "dict_kwargs": {"x": "depth_m", "y": "read_count", "color": "biome"},
            "layout": {"x": 0, "y": 6, "w": 4, "h": 4},
        }
    )
    manifest = build_manifest(DashboardDataLite.model_validate(spec), tmp_path).manifest
    scaffold = manifest.bindings["depth-scatter"].scaffold
    colours = {t["name"]: t["marker"]["color"] for t in scaffold["data"]}
    assert colours == {"urban": "#e8590c", "marine": "#1c7ed6", "freshwater": "#2f9e44"}
