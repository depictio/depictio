"""Notebook export against the funnel harness — the row-count oracle.

Reuses ``test_funnel_values``'s setup (mongomock, patched permission and link
resolution, a fake Delta load over an inline frame). The generated notebook
is executed offline against the same frame written as Parquet, and every
stage's ``df.height`` must equal what ``funnel_values`` reports for that
stage. Reordering stages changes the intermediate counts, never the last.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from unittest.mock import patch

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as nbx
from depictio.api.v1.endpoints.dashboards_endpoints.routes import funnel_values_endpoint
from depictio.api.v1.services.notebook_export.ipynb import ipynb_available
from depictio.models.models.analysis_state import AnalysisState, NotebookExportRequest

DC1 = str(ObjectId())
PROJECT_ID = ObjectId()
WF_ID = str(ObjectId())
DASHBOARD_ID = str(ObjectId())
CHILD_ID = str(ObjectId())

BASE_DF = pl.DataFrame(
    {
        "habitat": ["Groundwater", "Groundwater", "Riverwater", "Riverwater", "Seawater"],
        "depth": ["1", "2", "3", "4", "5"],
        "temp": [4.0, 6.0, 12.0, 15.0, 18.0],
    }
)


def _component(index, ctype, **extra):
    return {
        "index": index,
        "component_type": ctype,
        "dc_id": DC1,
        "wf_id": WF_ID,
        "dc_config": {"delta_location": f"memory://{DC1}", "type": "table"},
        **extra,
    }


def _dashboard_doc() -> dict:
    return {
        "dashboard_id": DASHBOARD_ID,
        "project_id": PROJECT_ID,
        "title": "Wells & Rivers",
        "subtitle": "Where the samples came from",
        "is_main_tab": True,
        "tab_order": 0,
        "grid_sections": [{"name": "Overview"}],
        "stored_metadata": [
            {
                "index": "txt-1",
                "component_type": "text",
                "title": "Sampling",
                "body": "Five samples.",
                "section": "Overview",
            },
            _component(
                "comp-habitat",
                "interactive",
                interactive_component_type="MultiSelect",
                column_name="habitat",
                title="Habitat",
                placement="left",
            ),
            _component(
                "comp-depth",
                "interactive",
                interactive_component_type="MultiSelect",
                column_name="depth",
                title="Depth",
                placement="left",
            ),
            _component(
                "comp-temp",
                "interactive",
                interactive_component_type="RangeSlider",
                column_name="temp",
                title="Temperature",
                placement="left",
            ),
            _component(
                "card-1",
                "card",
                title="Samples",
                aggregation="count",
                column_name="depth",
                section="Overview",
            ),
            _component(
                "card-2",
                "card",
                title="Mean temperature",
                aggregation="average",
                column_name="temp",
                section="Overview",
            ),
            _component(
                "fig-1",
                "figure",
                title="Temperature by habitat",
                mode="ui",
                visu_type="bar",
                dict_kwargs={
                    "x": "habitat",
                    "y": "temp",
                    "color": None,
                    "labels": '{"temp": "Temperature"}',
                },
                section="Overview",
            ),
            _component(
                "fig-2",
                "figure",
                title="Custom",
                mode="code",
                visu_type="scatter",
                code_content="fig = px.scatter(df.to_pandas(), x='depth', y='temp')",
                section="Overview",
            ),
            _component("tbl-1", "table", title="Rows", page_size=50, columns=["habitat", "temp"]),
        ],
    }


def _child_doc() -> dict:
    return {
        "dashboard_id": CHILD_ID,
        "parent_dashboard_id": DASHBOARD_ID,
        "project_id": PROJECT_ID,
        "title": "Details",
        "is_main_tab": False,
        "tab_order": 1,
        "stored_metadata": [
            _component("viz-1", "advanced_viz", title="Embedding", viz_kind="embedding"),
        ],
    }


def _fake_load(workflow_id, data_collection_id, metadata=None, init_data=None, **kwargs):
    df = BASE_DF
    for f in metadata or []:
        column = f.get("column_name")
        value = f.get("value")
        itype = f.get("interactive_component_type")
        if column not in df.columns:
            continue
        if itype == "RangeSlider":
            df = df.filter((pl.col(column) >= value[0]) & (pl.col(column) <= value[1]))
        else:
            values = value if isinstance(value, list) else [value]
            df = df.filter(pl.col(column).cast(pl.Utf8).is_in([str(v) for v in values]))
    return df


def _filter(index, column, value, itype="MultiSelect"):
    return {
        "index": index,
        "value": value,
        "column_name": column,
        "interactive_component_type": itype,
        "metadata": {"dc_id": DC1, "column_name": column},
    }


@pytest.fixture
def patched_env():
    client = mongomock.MongoClient()
    db = client.test_db
    db.dashboards.insert_one(_dashboard_doc())
    db.dashboards.insert_one(_child_doc())
    db.projects.insert_one(
        {
            "_id": PROJECT_ID,
            "name": "Wells",
            "workflows": [
                {
                    "workflow_tag": "sampling",
                    "data_collections": [{"_id": ObjectId(DC1), "data_collection_tag": "samples"}],
                }
            ],
            "template_origin": {
                "run_provenance": [
                    {
                        "source": "params.json",
                        "group": "Parameters",
                        "key": "min_depth",
                        "value": "1",
                        "highlight": True,
                    }
                ]
            },
        }
    )
    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    with (
        patch(f"{routes_mod}.dashboards_collection", db.dashboards),
        patch(f"{routes_mod}.projects_collection", db.projects),
        patch(f"{routes_mod}.check_project_permission", lambda *a, **k: True),
        patch(f"{routes_mod}._resolve_link_filters_cached", lambda **kw: list(kw["filters"])),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", _fake_load),
        patch.object(nbx, "_dtypes_for", lambda *a, **k: None),
    ):
        yield
        client.close()


class _User:
    email = "t.weber@example.org"


def _state(filters, stage_order=()):
    return AnalysisState.model_validate(
        {
            "filters": filters,
            "funnel": {"stage_order": list(stage_order)},
            "context": {"dashboard_id": DASHBOARD_ID},
        }
    )


def _export(state, fmt="marimo"):
    return nbx.notebook_export(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        request=NotebookExportRequest(state=state, format=fmt),
        current_user=_User(),
        access_token=None,
    )


def _preflight(state):
    return nbx.notebook_export_preflight(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        request=NotebookExportRequest(state=state),
        current_user=_User(),
        access_token=None,
    )


def _funnel(filters):
    return funnel_values_endpoint(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        request={"filters": filters, "target_indexes": [], "include_stages": True},
        current_user=object(),
        access_token=None,
    )


def _run_notebook(source: str, tmp_path, monkeypatch):
    BASE_DF.write_parquet(tmp_path / f"{DC1}.parquet")
    monkeypatch.setenv("DEPICTIO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEPICTIO_API_URL", raising=False)
    monkeypatch.delenv("DEPICTIO_API_TOKEN", raising=False)
    path = tmp_path / "export.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(f"export_{tmp_path.name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The child tab's advanced viz re-renders through the API, which this
    # offline run has no access to: stub the client call so the rest runs.
    with patch(
        "depictio.notebook.client.DepictioClient.component", lambda *a, **k: "rendered by Depictio"
    ):
        _outputs, defs = module.app.run()
    return defs


FILTERS = [
    _filter("comp-habitat", "habitat", ["Groundwater", "Riverwater"]),
    _filter("comp-temp", "temp", [5.0, 20.0], itype="RangeSlider"),
    _filter("comp-depth", "depth", ["2", "3", "5"]),
]


@pytest.mark.parametrize(
    "stage_order",
    [
        (),
        ("comp-depth", "comp-temp", "comp-habitat"),
        ("comp-temp",),
    ],
)
def test_stage_row_counts_match_funnel_values(patched_env, tmp_path, monkeypatch, stage_order):
    state = _state(FILTERS, stage_order)
    ordered = nbx._order_active_filters(list(FILTERS), list(stage_order))
    oracle = _funnel(ordered)
    resp = _export(state)
    source = resp.body.decode()
    defs = _run_notebook(source, tmp_path, monkeypatch)
    assert defs["df_samples"].height == oracle["initial_rows_by_dc"][DC1] == BASE_DF.height
    for k, stage in enumerate(oracle["stages"], start=1):
        assert defs[f"stage_{k}_samples"].height == stage["rows_by_dc"][DC1], (k, stage_order)
    assert defs["final_samples"].height == oracle["stages"][-1]["rows_by_dc"][DC1]
    # Tiles computed over the final frame.
    assert defs["card_samples"] == defs["final_samples"].height
    assert defs["card_mean_temperature"] == pytest.approx(defs["final_samples"]["temp"].mean())
    assert defs["table_rows"].columns == ["habitat", "temp"]
    # UI-built, so it renders through client.component(...) like the child
    # tab's advanced viz (api-mode names get the "viz_" prefix, not "fig_");
    # the offline stub stands in for the real API.
    assert defs["viz_temperature_by_habitat"] == "rendered by Depictio"
    assert defs["fig_custom"].data[0].type == "scatter"


def test_reordering_changes_intermediate_counts_but_not_the_final_one(patched_env):
    a = _funnel(nbx._order_active_filters(list(FILTERS), []))
    b = _funnel(
        nbx._order_active_filters(list(FILTERS), ["comp-depth", "comp-temp", "comp-habitat"])
    )
    assert a["stages"][0]["rows_by_dc"] != b["stages"][0]["rows_by_dc"]
    assert a["stages"][-1]["rows_by_dc"] == b["stages"][-1]["rows_by_dc"]


def test_export_headers_and_content(patched_env):
    resp = _export(_state(FILTERS))
    assert resp.media_type.startswith("text/x-python")
    assert resp.headers["Content-Disposition"] == 'attachment; filename="wells_rivers.py"'
    src = resp.body.decode()
    assert "# Wells & Rivers" in src and "Where the samples came from" in src
    assert "min_depth" in src  # run provenance in the header
    assert "t.weber@example.org" in src
    assert "Groundwater" in src and "Riverwater" in src
    assert "client.component(" in src and "'viz-1'" in src  # the child tab's advanced viz
    # The child tab's own heading: an h3 like every other tab, under the
    # results h2, carrying the marker the export's fold/rail script keys on.
    assert re.search(r"^\s*### <span data-dpx-accent=.*Details", src, re.M)
    assert "'fig-1'" in src  # the UI-built figure, rendered through the API too


def test_preflight_verdicts(patched_env):
    pre = _preflight(_state(FILTERS))
    by_index = {c.index: c for c in pre.components}
    # fig-1 is UI-built, so it goes through the API like fig-2 would if it
    # were not the author's own code; fig-2 is mode="code" and stays inlined.
    assert by_index["fig-1"].status == "api" and by_index["fig-2"].status == "code"
    assert by_index["viz-1"].status == "api" and by_index["viz-1"].kind == "embedding"
    assert by_index["card-1"].name == "card_samples"
    assert [s.index for s in pre.stages] == ["comp-habitat", "comp-temp", "comp-depth"]
    assert pre.dcs[0].tag == "samples" and pre.dcs[0].rows == BASE_DF.height
    assert pre.counts["code"] == 5 and pre.counts["api"] == 2
    assert pre.ipynb_available == ipynb_available()


def test_inactive_filters_are_not_stages(patched_env):
    pre = _preflight(_state([_filter("comp-habitat", "habitat", []), *FILTERS[1:]]))
    assert [s.index for s in pre.stages] == ["comp-temp", "comp-depth"]


def test_unknown_dashboard_is_404(patched_env):
    with pytest.raises(HTTPException) as exc:
        nbx.notebook_export(
            dashboard_id=str(ObjectId()),  # type: ignore[arg-type]
            request=NotebookExportRequest(state=_state([])),
            current_user=_User(),
            access_token=None,
        )
    assert exc.value.status_code == 404


def test_permission_denied_is_403(patched_env):
    with patch(
        "depictio.api.v1.endpoints.dashboards_endpoints.routes.check_project_permission",
        lambda *a, **k: False,
    ):
        with pytest.raises(HTTPException) as exc:
            _export(_state([]))
    assert exc.value.status_code == 403


def test_feature_flag_off_is_404(patched_env):
    with patch.object(nbx.settings.notebook_export, "enabled", False):
        with pytest.raises(HTTPException) as exc:
            _export(_state([]))
    assert exc.value.status_code == 404


@pytest.mark.skipif(not ipynb_available(), reason="marimo/nbformat not installed")
def test_ipynb_and_quarto_variants(patched_env):
    marimo_src = _export(_state(FILTERS)).body.decode()
    ipynb = _export(_state(FILTERS), fmt="ipynb")
    assert ipynb.media_type == "application/x-ipynb+json"
    assert ipynb.headers["Content-Disposition"].endswith('.ipynb"')
    nb = json.loads(ipynb.body)
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code_cells) == marimo_src.count("@app.cell") - marimo_src.count("mo.md(")
    assert all(c["outputs"] == [] for c in code_cells)
    quarto = _export(_state(FILTERS), fmt="quarto")
    assert quarto.headers["Content-Disposition"].endswith('.quarto.ipynb"')
    qnb = json.loads(quarto.body)
    assert qnb["cells"][0]["cell_type"] == "raw"
    assert "title: Wells & Rivers" in "".join(qnb["cells"][0]["source"])
    assert qnb["cells"][1:] == nb["cells"]


def test_ipynb_unavailable_is_501(patched_env):
    with patch.object(nbx, "to_ipynb", side_effect=nbx.IpynbExportUnavailable("no marimo")):
        with pytest.raises(HTTPException) as exc:
            _export(_state([]), fmt="ipynb")
    assert exc.value.status_code == 501


# ── The rendered report ───────────────────────────────────────────────────────


class _RenderUser:
    email = "t.weber@example.org"
    id = ObjectId()


def _render(state):
    return asyncio.run(
        nbx.notebook_export_render(
            dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
            request=NotebookExportRequest(state=state, format="quarto"),
            current_user=_RenderUser(),  # type: ignore[arg-type]
            access_token=None,
        )
    )


def test_render_off_by_default_is_501(patched_env):
    with pytest.raises(HTTPException) as exc:
        _render(_state([]))
    assert exc.value.status_code == 501


@pytest.mark.skipif(not ipynb_available(), reason="marimo/nbformat not installed")
def test_render_stages_the_notebook_and_queues_the_job(patched_env):
    """The notebook goes to S3 under the caller's prefix; the broker gets its key."""
    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}

    class _Token:
        id = ObjectId()

    async def _fake_add_token(token_data):
        assert token_data.token_lifetime == "short-lived"
        return _Token()

    with (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch(
            "depictio.api.v1.services.screenshot_service.check_dashboard_owner_permission_sync",
            lambda *a: True,
        ),
        patch(
            "depictio.api.v1.services.notebook_export.store.put",
            lambda key, body, content_type: staged.__setitem__(key, body),
        ),
        patch(
            "depictio.api.v1.endpoints.user_endpoints.core_functions._add_token", _fake_add_token
        ),
        patch(
            "depictio.api.celery_app.render_notebook_report.apply_async",
            lambda **kw: queued.update(kw),
        ),
    ):
        status = _render(_state(FILTERS))

    assert status.status == "queued" and status.filename.endswith(".html")
    key = next(iter(staged))
    assert key.startswith(f"notebook_reports/{_RenderUser.id}/{status.job_id}/")
    assert key.endswith(".quarto.ipynb")
    # What was staged is the Quarto notebook, front matter and all.
    assert json.loads(staged[key])["cells"][0]["cell_type"] == "raw"
    # The job is addressed by the id the caller was handed, and carries the
    # token by id rather than the token itself.
    assert queued["task_id"] == status.job_id
    assert queued["kwargs"]["notebook_key"] == key
    assert queued["kwargs"]["token_id"] == str(_Token.id)
    assert "access_token" not in queued["kwargs"]


def test_a_render_job_of_another_user_is_not_found(patched_env):
    class _Result:
        state = "SUCCESS"
        result = {"user_id": str(ObjectId()), "key": "k", "filename": "r.html"}

    with (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch("celery.result.AsyncResult", lambda *a, **k: _Result()),
    ):
        with pytest.raises(HTTPException) as exc:
            nbx.notebook_export_render_status(job_id="someone-elses", current_user=_RenderUser())  # type: ignore[arg-type]
    assert exc.value.status_code == 404


def test_a_non_owner_cannot_render_author_written_code(patched_env):
    """A code-mode figure is the author's Python, and the render is what runs it."""
    with (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch.object(type(nbx.settings.auth), "is_single_user_mode", False),
        patch(
            "depictio.api.v1.services.screenshot_service.check_dashboard_owner_permission_sync",
            lambda *a: False,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            _render(_state(FILTERS))
    assert exc.value.status_code == 403
    assert "code-mode" in exc.value.detail
