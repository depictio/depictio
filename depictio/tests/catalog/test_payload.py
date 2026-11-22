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
    _inject,
    _table_payload,
    advanced_viz_persist_config,
    build_payload,
    export_site_data,
    inline_logos,
    json_safe,
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


def test_code_figures_preview_with_the_grouping_names_bound() -> None:
    """A code figure may spread the grouping names a dashboard render binds.

    The preview has no saved groups, so it binds them ungrouped, the same
    values a dashboard render hands over before anyone has made a group. Every
    bundled code figure that names them must therefore build without error.
    """
    from depictio.api.v1.services.figure.groups import CODE_GROUP_BY, CODE_GROUP_KWARGS

    uses_grouping = [
        o
        for e in load_catalog_entries()
        for o in e.outputs
        if any(
            r.code and (CODE_GROUP_BY in r.code or CODE_GROUP_KWARGS in r.code)
            for r in o.renders_as
        )
    ]
    assert uses_grouping, "no bundled code figure names the grouping kwargs"
    for output in uses_grouping:
        errors = [r["_error"] for r in build_payload(output, "light")["renders"] if r.get("_error")]
        assert errors == [], f"{output.id}: {errors}"


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


def test_an_embedding_ships_the_columns_its_colour_menu_offers() -> None:
    """The preview answers the render-time column menu, offline.

    On a dashboard the embedding's "Colour by" and "Hover columns" menus are
    filled from ``GET /datacollections/polars_schema`` and the picked column is
    fetched on demand. The offline bundle can do neither, so the payload has to
    carry the unbound fixture columns and advertise them as the DC schema —
    otherwise the menu is empty and the plot is stuck on dim_1/dim_2.
    """
    payload = build_payload(_get_output("ampcombi_embedding"), "light")
    render = next(m for m in payload["renders"] if m.get("viz_kind") == "embedding")
    dc_id = render["dc_id"]

    schema = payload["data"]["schemas"][dc_id]
    rows = payload["data"]["advancedVizData"][dc_id]["rows"]
    # The annotations the recipe emits precisely so the plane can be re-coloured.
    for column in ("sample", "prob_max", "charge_class", "aa_length"):
        assert column in schema, f"{column} missing from the advertised schema"
        assert column in rows, f"{column} advertised but its values were not shipped"
    # Nothing may be offered that the payload cannot colour by.
    assert set(schema) <= set(rows)


def test_a_kind_without_a_column_menu_stays_on_its_roles() -> None:
    """The extra columns are for the menus, not a blanket fixture dump.

    A manhattan has no column menu, so shipping its whole fixture would only
    grow the bundle every reader downloads.
    """
    payload = build_payload(_get_output("ivar_variants_long"), "light")
    render = next(m for m in payload["renders"] if m.get("viz_kind") == "manhattan")
    dc_id = render["dc_id"]

    assert dc_id not in payload["data"]["schemas"]
    bound = {v for k, v in render["config"].items() if k.endswith("_col")}
    assert set(payload["data"]["advancedVizData"][dc_id]["rows"]) == bound


def test_the_payload_is_injected_once(tmp_path, monkeypatch) -> None:
    """A second copy of the sentinel (a comment quoting it) must not get the payload:
    the template once named it in a comment, and every gallery shipped it twice."""
    template = tmp_path / "catalog-preview.html"
    template.write_text(
        "<!-- replaces __CATALOG_PAYLOAD__ -->"
        '<script id="catalog-payload" type="application/json">__CATALOG_PAYLOAD__</script>'
    )
    monkeypatch.setattr("depictio.catalog.payload.TEMPLATE_PATH", template)

    html = _inject({"marker": "only-once"})

    assert html.count("only-once") == 1


def _flagship_entry():
    return next(e for e in load_catalog_entries() if any(o.id == FLAGSHIP for o in e.outputs))


def test_the_site_index_lists_every_output_without_its_data(tmp_path) -> None:
    import json

    entry = _flagship_entry()
    stats = export_site_data([entry], tmp_path, "9.9.9")

    index = json.loads((tmp_path / "index.json").read_text())
    assert index["version"] == "9.9.9"
    assert index["initialOutputId"] is None
    [tool] = index["tools"]
    assert tool["id"] == entry.id
    assert [o["output"]["id"] for o in tool["outputs"]] == [o.id for o in entry.outputs]
    assert all(o["fixturePreview"] is None for o in tool["outputs"])
    assert not index["data"]["figures"] and not index["data"]["tables"]
    assert stats["tools"] == 1
    assert stats["outputs"] == len(entry.outputs)


def test_the_site_index_carries_the_module_version(tmp_path) -> None:
    import json

    entry = _flagship_entry()
    export_site_data([entry], tmp_path, "9.9.9")

    [tool] = json.loads((tmp_path / "index.json").read_text())["tools"]
    assert tool["version"] == entry.version


def test_each_site_output_file_holds_what_the_gallery_embeds(tmp_path) -> None:
    """Same fixture and data as the one-page gallery: only the download moves."""
    import json

    entry = _flagship_entry()
    export_site_data([entry], tmp_path, "dev")

    expected = json_safe(build_payload(_get_output(FLAGSHIP), "light", entry))
    written = json.loads((tmp_path / "outputs" / f"{FLAGSHIP}.json").read_text())
    roundtrip = json.loads(json.dumps(expected, default=str))
    assert written["fixturePreview"] == roundtrip["fixturePreview"]
    assert written["data"] == roundtrip["data"]
    # Browser JSON.parse rejects NaN / Infinity tokens.
    text = (tmp_path / "outputs" / f"{FLAGSHIP}.json").read_text()
    assert "NaN" not in text and "Infinity" not in text


def test_an_output_without_a_preview_is_listed_but_gets_no_file(tmp_path, monkeypatch) -> None:
    import json

    def broken(output, tool, theme):
        return {
            "output": {"id": output.id},
            "fixturePreview": None,
            "renders": [],
            "ok": False,
            "error": "boom",
        }, {}

    monkeypatch.setattr("depictio.catalog.payload._output_entry", broken)
    entry = _flagship_entry()
    stats = export_site_data([entry], tmp_path, "dev")

    index = json.loads((tmp_path / "index.json").read_text())
    assert all(o["ok"] is False for o in index["tools"][0]["outputs"])
    assert stats["failed"] == len(entry.outputs)
    assert not list((tmp_path / "outputs").iterdir())


def test_a_reused_output_id_stops_the_site_export(tmp_path) -> None:
    entry = _flagship_entry()
    with pytest.raises(CatalogPayloadError, match="more than one tool"):
        export_site_data([entry, entry], tmp_path, "dev")


def test_multiqc_logo_paths_become_data_uris() -> None:
    """A static page has no /dashboard/logos/ to serve them from."""
    text = 'src="/dashboard/logos/multiqc_icon_dark.svg" b="/dashboard-beta/logos/multiqc_icon_white.svg"'
    out = inline_logos(text)
    assert "/dashboard" not in out
    assert out.count("data:image/svg+xml;base64,") == 2


def test_a_coverage_track_lists_chromosomes_and_samples_in_file_order() -> None:
    """Hash-ordered lists change between runs, and the catalog site stores an
    output's data once per content: every export would look like a new version."""
    from depictio.catalog.payload import _load_fixture_df

    output = _get_output("macs2_peaks")
    [summary] = [
        v["summary"]
        for v in build_payload(output, "light")["data"]["compute"].values()
        if "summary" in v
    ]
    df = _load_fixture_df(output)

    def first_seen(values: list[str]) -> list[str]:
        column = next(c for c in df.columns if set(df[c].cast(str).to_list()) == set(values))
        return list(dict.fromkeys(df[column].cast(str).to_list()))

    assert summary["chromosomes"] == first_seen(summary["chromosomes"])
    assert summary["samples"] == first_seen(summary["samples"])


def _output_of_kind(kind: str):
    for entry in load_catalog_entries():
        for output in entry.outputs:
            if any(r.component == "advanced_viz" and r.kind == kind for r in output.renders_as):
                return entry, output
    raise AssertionError(f"no catalog output renders a {kind}")


@pytest.mark.parametrize("kind", ["sankey", "upset_plot"])
def test_a_computed_render_is_reproducible_and_has_no_error(kind) -> None:
    """The kernels live in the Celery module, which refuses an unconfigured server on
    import: a failure there is swallowed into a per-render `_error` (and no data), so
    the two payloads would compare equal while both being empty."""
    import json

    entry, output = _output_of_kind(kind)

    first = build_payload(output, "light", entry)
    second = build_payload(output, "light", entry)

    wanted = [r for r in first["renders"] if r.get("viz_kind") in ("sankey", "upset_plot", "upset")]
    assert wanted
    assert not [r["_error"] for r in first["renders"] if "_error" in r]
    assert not [r["_error"] for r in second["renders"] if "_error" in r]
    computed = [first["data"]["compute"][r["dc_id"]] for r in wanted]
    assert all(c.get("figure") for c in computed)
    assert all(c["compute_ms"] == 0 for c in computed)
    assert json.dumps(json_safe(first), sort_keys=False, default=str) == json.dumps(
        json_safe(second), sort_keys=False, default=str
    )


def test_the_export_counts_the_renders_that_failed(tmp_path, monkeypatch) -> None:
    def failing(output, tool, theme):
        renders = [{"index": f"r{i}", "_error": "boom"} for i in range(3)]
        return {
            "output": {"id": output.id},
            "fixturePreview": None,
            "renders": renders,
            "ok": True,
        }, {}

    monkeypatch.setattr("depictio.catalog.payload._output_entry", failing)
    entry = _flagship_entry()
    stats = export_site_data([entry], tmp_path, "dev")

    assert stats["failed"] == 0
    assert stats["render_errors"] == 3 * len(entry.outputs)
    ids = stats["render_error_ids"]
    assert ids[:3] == [f"{entry.outputs[0].id}:r{i}" for i in range(3)]
    assert len(ids) == min(20, stats["render_errors"])


def test_a_clean_export_reports_no_render_error(tmp_path) -> None:
    stats = export_site_data([_flagship_entry()], tmp_path, "dev")

    assert stats["render_errors"] == 0
    assert stats["render_error_ids"] == []


def test_a_tied_card_mode_is_the_smallest_value_as_on_the_server() -> None:
    """Polars gives tied modes in hash order; pandas (the dashboard's card) sorts
    them. A card listing `mode` beside a strip made the export differ between runs."""
    from depictio.catalog.payload import _aggregate

    df = pl.DataFrame({"g": ["novel", "known", "novel", "known", None, None, None]})
    assert {_aggregate(df, "g", "mode") for _ in range(20)} == {"known"}
    assert df["g"].to_pandas().mode().iloc[0] == "known"


def test_a_marked_figure_ships_the_patch_that_takes_its_marks_off() -> None:
    """The preview's "Automatic marks" switch: the figure keeps its marks, and
    `marks_off` names what to drop. A figure without marks carries none."""
    payload = build_payload(_get_output("bclconvert_lane_summary"), "light")
    figures = payload["data"]["figures"].values()
    marked = [f for f in figures if "marks_off" in f]
    assert marked, "no figure of this output carries marks"
    for f in marked:
        assert f["marks_off"]["data"] or f["marks_off"]["layout"]
