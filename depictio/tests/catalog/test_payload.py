"""Tests for the Dash-free catalog-preview payload computer.

``build_payload`` turns a catalog output + its fixture into the
``window.__CATALOG_PREVIEW__`` blob the standalone viewer bundle consumes
(StoredMetadata per render + per-render data in the api.ts response shapes).
"""

from __future__ import annotations

import polars as pl
import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.catalog.payload import (
    CatalogPayloadError,
    _aggregate,
    _table_payload,
    advanced_viz_persist_config,
    build_payload,
)
from depictio.models.components.advanced_viz.catalog import load_catalog_entries
from depictio.models.components.advanced_viz.configs import VizConfig

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
    assert types == ["figure", "card", "card", "card", "card", "table"]

    data = payload["data"]
    # figure → Plotly JSON (2×2 facet box plot = a trace per habitat)
    fig = next(iter(data["figures"].values()))
    assert "data" in fig["figure"] and len(fig["figure"]["data"]) >= 1
    # 4 metric cards → numeric values
    assert len(data["cards"]["values"]) == 4
    assert all(isinstance(v, (int, float)) for v in data["cards"]["values"].values())
    # 1 table with rows
    table = next(iter(data["tables"].values()))
    assert table["total"] > 0
    # every render carries a unique synthetic dc_id (interactive/advanced-viz keying)
    dc_ids = [m["dc_id"] for m in payload["renders"]]
    assert len(set(dc_ids)) == len(dc_ids)


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


def test_top_n_card_payload_carries_the_breakdown() -> None:
    """A categorical card previews its `__breakdown__`, not a bare number.

    The picker's preview must show the strip the added component will draw,
    which for `top_n` means the shares computed by the same service the saved
    card's compute path uses.
    """
    payload = build_payload(_get_output("ivar_oncoplot_matrix"), "light")
    card = next(
        m
        for m in payload["renders"]
        if m["component_type"] == "card" and m["column_name"] == "sample_id"
    )
    assert card["secondary_layout"] == "top_n"
    assert card["breakdown_col"] == "gene"
    breakdown = payload["data"]["cards"]["secondary"][card["index"]]["__breakdown__"]
    assert breakdown["column"] == "gene"
    assert 1 <= len(breakdown["top"]) <= card["top_n_count"]
    assert 0.0 < breakdown["top_share"] <= 1.0


def test_numeric_layout_card_payload() -> None:
    """`uniqueness` (and its NUMERIC_LAYOUTS siblings) preview through the
    shared ``card_metrics`` service, keyed as ``__<layout>__``."""
    payload = build_payload(_get_output("qiime2_tree_metadata"), "light")
    card = next(
        m
        for m in payload["renders"]
        if m["component_type"] == "card" and m["column_name"] == "taxon"
    )
    assert card["secondary_layout"] == "uniqueness"
    assert "__uniqueness__" in payload["data"]["cards"]["secondary"][card["index"]]


def test_every_bundled_card_previews_its_strip() -> None:
    """Whatever a card declares, the preview computes something for it.

    Guards the layout→payload dispatch: a layout added to the catalog that the
    preview does not know how to compute would otherwise silently render as a
    hero number in the picker and as a full card on the dashboard.
    """
    missing: list[str] = []
    for entry in load_catalog_entries():
        for output in entry.outputs:
            cards = [r for r in output.renders_as if r.component == "card"]
            if not cards:
                continue
            payload = build_payload(output, "light")
            secondary = payload["data"]["cards"]["secondary"]
            for meta in payload["renders"]:
                if meta.get("component_type") != "card" or meta.get("_error"):
                    continue
                layout = meta.get("secondary_layout")
                # coverage/gauge draw from the hero value + coverage_max alone.
                if not layout or layout in ("coverage", "gauge"):
                    continue
                if not secondary.get(meta["index"]):
                    missing.append(f"{output.id}:{meta['column_name']} ({layout})")
    assert missing == [], f"cards whose strip did not compute: {missing}"


def test_every_advanced_viz_offer_persists_a_valid_config() -> None:
    """What the catalog offers must be storable, not merely renderable.

    ``advanced_viz_persist_config`` is what a catalog-added component actually
    writes into ``stored_metadata``, and every per-kind config model forbids
    unknown keys. The dashboard save path does not validate, though, so a config
    with a stray key is written happily and only fails much later: on an export,
    a re-import, or a validate. Four offers were in exactly that state (manhattan
    ``top_n_labels``, and three heatmaps emitting ``index_col`` where the model
    declares ``index_column``), so the gap is not hypothetical.
    """
    adapter = TypeAdapter(VizConfig)
    invalid: list[str] = []
    for entry in load_catalog_entries():
        for output in entry.outputs:
            for render in output.renders_as or []:
                if render.component != "advanced_viz":
                    continue
                config = advanced_viz_persist_config(output, render)
                if config is None:
                    continue  # not groundable against the fixture; nothing to store
                try:
                    adapter.validate_python(config)
                except ValidationError as exc:
                    first = exc.errors()[0]
                    invalid.append(f"{output.id} ({render.kind}): {first['loc']} {first['msg']}")
    assert invalid == [], f"catalog offers whose persisted config is invalid: {invalid}"
