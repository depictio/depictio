"""``depictio.notebook`` against a mocked API (``httpx.MockTransport``)."""

from __future__ import annotations

import io
import json

import httpx
import polars as pl
import pytest

from depictio.notebook import DepictioClient, DepictioClientError
from depictio.notebook.components import (
    COMPONENT_CLASSES,
    AdvancedVizComponent,
    CardComponent,
    FigureComponent,
    TableComponent,
    TextComponent,
    filters_to_metadata,
)

DASH = "6824cb3b89d2b72169309738"
DC = "646b0f3c1e4a2d7f8e5b8ca1"
TABLE = pl.DataFrame(
    {"species": ["Adelie", "Gentoo", "Adelie"], "body_mass_g": [3500.0, 5000.0, 3800.0]}
)

DASHBOARD = {
    "dashboard_id": DASH,
    "title": "Penguins",
    "stored_metadata": [
        {"index": "fig-1", "component_type": "figure", "title": "Bill shape", "dc_id": DC},
        {"index": "tbl-1", "component_type": "table", "title": "Raw data", "dc_id": DC},
        {
            "index": "card-1",
            "component_type": "card",
            "title": "Individuals",
            "aggregation": "count",
            "column_name": "species",
            "dc_id": DC,
        },
        {
            "index": "flt-1",
            "component_type": "interactive",
            "title": "Species",
            "interactive_component_type": "MultiSelect",
            "column_name": "species",
            "dc_id": DC,
        },
        {"index": "txt-1", "component_type": "text", "title": "Intro", "body": "Hello", "order": 2},
        {
            "index": "viz-1",
            "component_type": "advanced_viz",
            "title": "Embedding",
            "viz_kind": "embedding",
            "dc_id": DC,
        },
        {"index": "dup", "component_type": "figure", "title": "Twin", "dc_id": DC},
        {"index": "dup2", "component_type": "figure", "title": "Twin", "dc_id": DC},
    ],
}

FIGURE = {
    "data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}],
    "layout": {"title": {"text": "t"}},
}


class FakeApi:
    """Routes the client's requests and records what it saw."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.figure_polls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        assert request.headers.get("authorization") == "Bearer tok"
        if path.endswith(f"/dashboards/get/{DASH}"):
            return httpx.Response(200, json=DASHBOARD)
        if path.endswith(f"/deltatables/data/{DC}"):
            buf = io.BytesIO()
            df = TABLE
            cols = request.url.params.get("columns")
            if cols:
                df = df.select(cols.split(","))
            df.write_parquet(buf)
            return httpx.Response(
                200,
                content=buf.getvalue(),
                headers={"content-type": "application/vnd.apache.parquet"},
            )
        if "/render_figure/" in path:
            return httpx.Response(
                200, json={"figure": FIGURE, "metadata": {"filter_applied": bool(body["filters"])}}
            )
        if "/render_table/" in path:
            start = body["start"]
            rows = TABLE.to_dicts()[start : start + 2]
            return httpx.Response(200, json={"columns": [], "rows": rows, "total": TABLE.height})
        if "/bulk_compute_cards/" in path:
            return httpx.Response(
                200,
                json={
                    "values": {"card-1": 3},
                    "secondary_values": {},
                    "aggregations": {"card-1": ["count"]},
                    "filter_applied": False,
                },
            )
        if "/deltatables/unique_values/" in path:
            return httpx.Response(200, json={"column": "species", "values": ["Adelie", "Gentoo"]})
        if "/component_figure/jobs/" in path:
            self.figure_polls += 1
            if self.figure_polls < 2:
                return httpx.Response(200, json={"status": "pending", "job_id": "j1"})
            return httpx.Response(
                200, json={"status": "ready", "figure": FIGURE, "source": "extracted"}
            )
        if "/component_figure/" in path:
            return httpx.Response(200, json={"status": "pending", "job_id": "j1"})
        if "/advanced_viz/data" in path:
            return httpx.Response(
                200, json={"columns": ["a"], "rows": {"a": [1, 2]}, "row_count": 2}
            )
        if "/embed/" in path:
            return httpx.Response(200, text="<!doctype html><html><body>tile</body></html>")
        if path.endswith("/notebook_export/" + DASH + "/preflight"):
            return httpx.Response(200, json={"components": [], "counts": {}})
        if path.endswith("/notebook_export/" + DASH):
            if body["format"] == "marimo":
                return httpx.Response(200, text="import marimo\n")
            return httpx.Response(200, content=b'{"cells": []}')
        if path.endswith("/dashboards/get/missing"):
            return httpx.Response(404, json={"detail": "Dashboard 'missing' not found."})
        return httpx.Response(500, json={"detail": f"unexpected {path}"})


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def client(api, monkeypatch):
    monkeypatch.delenv("DEPICTIO_DATA_DIR", raising=False)
    return DepictioClient("https://depictio.test", "tok", transport=httpx.MockTransport(api))


def test_env_and_cli_config_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DEPICTIO_API_URL", raising=False)
    monkeypatch.delenv("DEPICTIO_API_TOKEN", raising=False)
    cfg = tmp_path / ".depictio"
    cfg.mkdir()
    (cfg / "CLI.yaml").write_text(
        "api_base_url: https://from-cli.test\nuser:\n  token:\n    access_token: cli-tok\n"
    )
    c = DepictioClient()
    assert c.base_url == "https://from-cli.test" and c.token == "cli-tok"
    monkeypatch.setenv("DEPICTIO_API_URL", "https://from-env.test/")
    monkeypatch.setenv("DEPICTIO_API_TOKEN", "env-tok")
    c = DepictioClient()
    assert c.base_url == "https://from-env.test" and c.token == "env-tok"
    assert DepictioClient("https://arg.test", "arg-tok").token == "arg-tok"


def test_no_api_configured_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DEPICTIO_API_URL", raising=False)
    monkeypatch.delenv("DEPICTIO_API_TOKEN", raising=False)
    with pytest.raises(DepictioClientError, match="DEPICTIO_API_URL"):
        DepictioClient().dashboard(DASH)


def test_data_reads_parquet_from_the_api(client):
    df = client.data(DC)
    assert df.equals(TABLE)
    assert client.data(DC, columns=["species"]).columns == ["species"]


def test_data_offline_mode_reads_local_parquet(tmp_path, api):
    TABLE.write_parquet(tmp_path / f"{DC}.parquet")
    c = DepictioClient(
        "https://depictio.test", "tok", transport=httpx.MockTransport(api), data_dir=str(tmp_path)
    )
    assert c.data(DC).equals(TABLE)
    assert not [call for call in api.calls if "/deltatables/data/" in call[1]]


def test_components_listing_and_lookup(client):
    listing = client.components(DASH)
    assert listing.height == len(DASHBOARD["stored_metadata"])
    assert client.metadata(DASH, "fig-1")["title"] == "Bill shape"
    assert client.metadata(DASH, "bill shape")["index"] == "fig-1"
    with pytest.raises(KeyError, match="several components"):
        client.metadata(DASH, "Twin")
    with pytest.raises(KeyError, match="no component"):
        client.metadata(DASH, "nope")


def test_filter_builds_the_wire_shape(client):
    f = client.filter(DASH, "Species", ["Adelie"])
    assert f == {
        "index": "flt-1",
        "value": ["Adelie"],
        "column_name": "species",
        "interactive_component_type": "MultiSelect",
        "metadata": {
            "dc_id": DC,
            "column_name": "species",
            "interactive_component_type": "MultiSelect",
        },
    }
    with pytest.raises(ValueError):
        client.filter(DASH, "Bill shape", 1)
    assert filters_to_metadata([f, {"index": "x", "value": []}]) == [
        {"interactive_component_type": "MultiSelect", "column_name": "species", "value": ["Adelie"]}
    ]


def test_figure_component_renders_through_the_api(client, api):
    species = client.filter(DASH, "Species", ["Adelie"])
    comp = client.component(DASH, "Bill shape", filters=[species])
    assert isinstance(comp, FigureComponent)
    fig = comp.figure
    assert fig.data[0].type == "scatter"
    sent = next(b for m, p, b in api.calls if "/render_figure/" in p)
    assert sent["filters"] == [species] and sent["theme"] == "light"
    bundle = comp._repr_mimebundle_()
    assert "application/vnd.plotly.v1+json" in bundle
    mime, payload = comp._mime_()
    assert mime == "text/html" and payload
    assert client.figure(DASH, "fig-1") is not None


def test_table_component_pages_through_all_rows(client):
    comp = client.component(DASH, "Raw data")
    assert isinstance(comp, TableComponent)
    df = comp.data
    assert df.height == TABLE.height
    assert "text/html" in comp._repr_mimebundle_()


def test_card_component_value_and_html(client):
    comp = client.component(DASH, "Individuals")
    assert isinstance(comp, CardComponent)
    assert comp.value == 3
    html = comp._repr_mimebundle_()["text/html"]
    assert "Individuals" in html and ">3<" in html


def test_text_component_is_markdown(client):
    comp = client.component(DASH, "Intro")
    assert isinstance(comp, TextComponent)
    assert comp.markdown == "## Intro\n\nHello"
    assert comp._repr_mimebundle_()["text/markdown"] == "## Intro\n\nHello"


def test_advanced_viz_polls_for_the_extracted_figure(client, api, monkeypatch):
    monkeypatch.setattr("depictio.notebook.client.time.sleep", lambda s: None)
    comp = client.component(DASH, "Embedding")
    assert isinstance(comp, AdvancedVizComponent)
    assert comp.figure.data[0].type == "scatter"
    assert api.figure_polls == 2
    assert comp.data.columns == ["a"]


def test_html_embed_and_interactive_options(client):
    comp = client.component(DASH, "Raw data")
    assert "<html" in comp.html
    flt = client.component(DASH, "Species")
    assert flt.data[flt.data.columns[0]].to_list() == ["Adelie", "Gentoo"]
    assert "Species" in flt._repr_mimebundle_()["text/html"]


def test_state_can_be_passed_explicitly(client, api):
    state = client.state(
        DASH, filters=[client.filter(DASH, "flt-1", ["Gentoo"])], stage_order=["flt-1"]
    )
    comp = client.component(DASH, "fig-1", state=state)
    comp.figure
    sent = next(b for m, p, b in api.calls if "/render_figure/" in p)
    assert sent["filters"][0]["value"] == ["Gentoo"]


def test_notebook_and_preflight(client, tmp_path):
    assert client.notebook(DASH).startswith("import marimo")
    out = tmp_path / "nb.ipynb"
    assert client.notebook(DASH, fmt="ipynb", save_to=out) == b'{"cells": []}'
    assert out.read_bytes() == b'{"cells": []}'
    assert client.preflight(DASH) == {"components": [], "counts": {}}


def test_api_errors_carry_status_and_detail(client):
    with pytest.raises(DepictioClientError) as exc:
        client.dashboard("missing")
    assert exc.value.status == 404 and "not found" in exc.value.detail


def test_every_component_class_displays_in_all_three_environments():
    for cls in COMPONENT_CLASSES.values():
        assert callable(getattr(cls, "_repr_mimebundle_"))
        assert callable(getattr(cls, "_mime_"))
        assert cls.default_display in ("figure", "data", "html", "markdown")
