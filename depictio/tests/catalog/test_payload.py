"""Tests for the Dash-free catalog-preview payload computer.

``build_payload`` turns a catalog output + its fixture into the
``window.__CATALOG_PREVIEW__`` blob the standalone viewer bundle consumes
(StoredMetadata per render + per-render data in the api.ts response shapes).
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.catalog.payload import (
    CatalogPayloadError,
    _aggregate,
    _table_payload,
    build_payload,
)
from depictio.models.components.advanced_viz.catalog import load_catalog_entries

FLAGSHIP = "qiime2_alpha_diversity"


def _get_output(output_id: str):
    return next(o for e in load_catalog_entries() for o in e.outputs if o.id == output_id)


@pytest.fixture
def df() -> pl.DataFrame:
    return pl.DataFrame({"group": ["a", "a", "b"], "value": [1.0, 3.0, 5.0]})


def test_aggregate_average(df: pl.DataFrame) -> None:
    assert _aggregate(df, "value", "average") == pytest.approx(3.0)


def test_aggregate_unknown_column(df: pl.DataFrame) -> None:
    with pytest.raises(CatalogPayloadError, match="absent"):
        _aggregate(df, "missing", "average")


def test_table_payload_shape(df: pl.DataFrame) -> None:
    t = _table_payload(df)
    assert {c["field"] for c in t["columns"]} == {"group", "value"}
    # numeric column typed for ag-grid's number filter / right-align
    assert next(c for c in t["columns"] if c["field"] == "value")["type"] == "numericColumn"
    assert t["total"] == 3
    assert len(t["rows"]) == 3


def test_flagship_payload_has_all_renders() -> None:
    output = _get_output(FLAGSHIP)
    payload = build_payload(output, "light")

    assert payload["output"]["id"] == FLAGSHIP
    assert payload["theme"] == "light"
    types = [m["component_type"] for m in payload["renders"]]
    # The flagship renders at least a figure, several metric cards and a table
    # (its exact shape evolves with the catalog, so assert the core kinds, not
    # an exact list).
    assert types[0] == "figure"
    assert types.count("card") >= 4
    assert "table" in types
    # No render is left unsupported — every declared kind is wired.
    assert not any(m.get("_unsupported") or m.get("_error") for m in payload["renders"])

    data = payload["data"]
    # figure → Plotly JSON (2×2 facet box plot = a trace per habitat)
    fig = next(iter(data["figures"].values()))
    assert "data" in fig["figure"] and len(fig["figure"]["data"]) >= 1
    # metric cards → numeric values
    assert len(data["cards"]["values"]) >= 4
    assert all(isinstance(v, (int, float)) for v in data["cards"]["values"].values())
    # 1 table with rows
    table = next(iter(data["tables"].values()))
    assert table["total"] > 0
    # every render carries a unique synthetic dc_id (interactive/advanced-viz keying)
    dc_ids = [m["dc_id"] for m in payload["renders"]]
    assert len(set(dc_ids)) == len(dc_ids)


def test_interactive_payload_wired() -> None:
    # sintax → two MultiSelect filters (Kingdom/Phylum) + a table. The
    # interactive renders must be wired (no _unsupported) and carry their
    # distinct-value options keyed by `<dc_id>::<column>` for the viewer's
    # interactive renderers (fetchUniqueValues).
    payload = build_payload(_get_output("sintax_rel_abundance"), "light")
    interactives = [m for m in payload["renders"] if m["component_type"] == "interactive"]
    assert interactives, "expected interactive renders in sintax_rel_abundance"
    for m in interactives:
        assert not m.get("_unsupported") and not m.get("_error")
        assert m.get("render_id")  # render's own id is exposed
        assert m["interactive_component_type"] == "MultiSelect"
        key = f"{m['dc_id']}::{m['column_name']}"
        assert key in payload["data"]["unique"]
        assert payload["data"]["unique"][key]  # non-empty distinct values


def test_interactive_range_payload_wired() -> None:
    # artic_variants_long has a RangeSlider on a numeric column (AF) → min/max
    # keyed by `<dc_id>::<column>` for fetchColumnRange.
    payload = build_payload(_get_output("artic_variants_long"), "light")
    sliders = [
        m
        for m in payload["renders"]
        if m["component_type"] == "interactive"
        and m.get("interactive_component_type") == "RangeSlider"
    ]
    assert sliders, "expected a RangeSlider render in artic_variants_long"
    for m in sliders:
        assert not m.get("_unsupported") and not m.get("_error")
        key = f"{m['dc_id']}::{m['column_name']}"
        rng = payload["data"]["ranges"][key]
        assert isinstance(rng["min"], float) and isinstance(rng["max"], float)
        assert rng["min"] <= rng["max"]


def test_render_id_exposed() -> None:
    # Every render's own `id` (when declared) is surfaced as `render_id`.
    payload = build_payload(_get_output("artic_variants_long"), "light")
    render_ids = [m.get("render_id") for m in payload["renders"]]
    assert "af_slider" in render_ids
    assert "table" in render_ids


def test_payload_is_json_serialisable() -> None:
    import json

    payload = build_payload(_get_output(FLAGSHIP), "light")
    json.dumps(payload, default=str)  # must not raise


def test_advanced_viz_client_side_payload() -> None:
    # ivar_variants_long → manhattan / lollipop / oncoplot (fetchAdvancedVizData kinds)
    payload = build_payload(_get_output("ivar_variants_long"), "light")
    kinds = {m.get("viz_kind") for m in payload["renders"] if m["component_type"] == "advanced_viz"}
    assert {"manhattan", "lollipop", "oncoplot"} <= kinds

    for m in payload["renders"]:
        if m["component_type"] != "advanced_viz":
            continue
        assert m["config"]["viz_kind"] == m["viz_kind"]
        av = payload["data"]["advancedVizData"][m["dc_id"]]
        assert av["row_count"] > 0
        # each declared <role>_col is projected into the row columns
        role_cols = [v for k, v in m["config"].items() if k.endswith("_col")]
        assert role_cols and all(c in av["rows"] for c in role_cols)


def test_coverage_track_compute_payload() -> None:
    # mosdepth_genome_coverage → coverage_track (server-computed kind, done as a
    # pure projection into the dispatch 'result' shape).
    payload = build_payload(_get_output("mosdepth_genome_coverage"), "light")
    [m] = [r for r in payload["renders"] if r["component_type"] == "advanced_viz"]
    assert m["viz_kind"] == "coverage_track"
    assert m["config"]["chromosome_col"] and m["config"]["value_col"]
    result = payload["data"]["compute"][m["dc_id"]]
    assert result["row_count"] > 0
    assert result["columns"]["value"] in result["rows"]
    assert isinstance(result["summary"]["mean_value"], float)


def test_box_plot_card_payload() -> None:
    payload = build_payload(_get_output(FLAGSHIP), "light")
    card = next(m for m in payload["renders"] if m["component_type"] == "card")
    assert card["secondary_layout"] == "box_plot"
    assert card["aggregations"] == ["box_plot_stats"]
    stats = payload["data"]["cards"]["secondary"][card["index"]]["box_plot_stats"]
    assert {"q1", "q3", "median", "lower_whisker", "upper_whisker", "outliers"} <= set(stats)
    assert stats["q1"] <= stats["median"] <= stats["q3"]
