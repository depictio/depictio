"""Notebook export against the funnel harness — the row-count oracle.

Reuses ``test_funnel_values``'s setup (mongomock, patched permission and link
resolution, a fake Delta load over an inline frame). The generated notebook
is executed offline against the same frame written as Parquet, and every
stage's ``df.height`` must equal what ``funnel_values`` reports for that
stage. Reordering stages changes the intermediate counts, never the last.
"""

from __future__ import annotations

import re
import sys
import types
from unittest.mock import patch

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as nbx
from depictio.api.v1.endpoints.dashboards_endpoints.routes import funnel_values_endpoint
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
    jobs_mod = "depictio.api.v1.services.notebook_export.jobs"
    with (
        patch(f"{jobs_mod}.jobs_collection", db.notebook_export_jobs),
        patch(f"{jobs_mod}.slots_collection", db.notebook_export_slots),
        patch(f"{routes_mod}.dashboards_collection", db.dashboards),
        patch(f"{routes_mod}.projects_collection", db.projects),
        patch(f"{routes_mod}.check_project_permission", lambda *a, **k: True),
        patch("depictio.serverless.producer_a.export_denial", lambda *a, **k: None),
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


def _export(state):
    return nbx.notebook_export(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        request=NotebookExportRequest(state=state),
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


@pytest.fixture(autouse=True)
def _restore_document_theme():
    """A document run here turns its theme on for the whole process, as a kernel's
    would: put Plotly's default template back for the tests after it."""
    import plotly.io as pio

    from depictio.notebook import theme

    default, state = pio.templates.default, dict(theme._STATE)
    yield
    pio.templates.default = default
    theme._STATE.clear()
    theme._STATE.update(state)


def _run_notebook(source: str, tmp_path, monkeypatch, parameters: dict | None = None):
    BASE_DF.write_parquet(tmp_path / f"{DC1}.parquet")
    monkeypatch.setenv("DEPICTIO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEPICTIO_API_URL", raising=False)
    monkeypatch.delenv("DEPICTIO_API_TOKEN", raising=False)
    (tmp_path / "export.qmd").write_text(source)
    # Run the document the way Quarto does: every {python} chunk, top to
    # bottom, in one namespace. The kernel Quarto drives always has IPython;
    # the test env may not, and only its HTML display wrapper is used.
    try:
        import IPython.display  # noqa: F401
    except ImportError:
        _stub_ipython_without_a_kernel(monkeypatch)
    defs: dict = {"__name__": f"export_{tmp_path.name}"}
    # The child tab's advanced viz re-renders through the API, which this
    # offline run has no access to: stub the client call so the rest runs.
    with patch(
        "depictio.notebook.client.DepictioClient.component", lambda *a, **k: "rendered by Depictio"
    ):
        for i, chunk in enumerate(_CHUNK_RE.findall(source)):
            exec(compile(chunk[1], f"<chunk {i}>", "exec"), defs)
            if parameters is not None and chunk[1].startswith("#| tags: [parameters]"):
                # What `quarto render -P` does: a cell right after the tagged one.
                defs.update(parameters)
    return defs


def _stub_ipython_without_a_kernel(monkeypatch) -> None:
    """IPython as a plain Python process sees it: importable, no kernel running.

    The document imports ``HTML`` from ``IPython.display``, and plotly asks
    ``IPython.get_ipython()`` whether it is inside a notebook; ``None`` is the
    real answer outside a kernel.
    """
    ipython = types.ModuleType("IPython")
    ipython.get_ipython = lambda: None  # type: ignore[attr-defined]
    display = types.ModuleType("IPython.display")
    display.HTML = type(  # type: ignore[attr-defined]
        "HTML",
        (),
        {
            "__init__": lambda self, data: setattr(self, "data", data),
            "_repr_html_": lambda self: self.data,
        },
    )
    ipython.display = display  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", display)


_CHUNK_RE = re.compile(r"^(`{3,})\{python\}\n(.*?)\n\1$", re.S | re.M)


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


@pytest.mark.parametrize(
    "new_filters,new_order",
    [
        # Same filters, another order: every stage follows the new order.
        (FILTERS, ("comp-depth", "comp-habitat", "comp-temp")),
        # Other values, and one filter fewer.
        (
            [
                _filter("comp-habitat", "habitat", ["Riverwater"]),
                _filter("comp-temp", "temp", [10.0, 30.0], itype="RangeSlider"),
            ],
            (),
        ),
        # A filter the export never saw: it lands in the final frame.
        ([*FILTERS, _filter("comp-extra", "depth", ["1", "3", "4"])], ()),
    ],
)
def test_a_parameterised_render_refilters_the_code_tiles(
    patched_env, tmp_path, monkeypatch, new_filters, new_order
):
    """`quarto render -P depictio_state:...` re-filters every stage, so the code
    tiles agree with the funnel endpoint for the *new* state, not the exported one."""
    source = _export(_state(FILTERS)).body.decode()
    new_state = _state(new_filters, new_order).model_dump(mode="json", exclude_none=True)
    defs = _run_notebook(source, tmp_path, monkeypatch, parameters={"depictio_state": new_state})
    ordered = nbx._order_active_filters(list(new_filters), list(new_order))
    oracle = _funnel(ordered)
    assert defs["final_samples"].height == oracle["stages"][-1]["rows_by_dc"][DC1]
    for k, stage in enumerate(oracle["stages"][: len(FILTERS)], start=1):
        assert defs[f"stage_{k}_samples"].height == stage["rows_by_dc"][DC1], k
    assert defs["card_samples"] == defs["final_samples"].height


def test_reordering_changes_intermediate_counts_but_not_the_final_one(patched_env):
    a = _funnel(nbx._order_active_filters(list(FILTERS), []))
    b = _funnel(
        nbx._order_active_filters(list(FILTERS), ["comp-depth", "comp-temp", "comp-habitat"])
    )
    assert a["stages"][0]["rows_by_dc"] != b["stages"][0]["rows_by_dc"]
    assert a["stages"][-1]["rows_by_dc"] == b["stages"][-1]["rows_by_dc"]


def test_export_headers_and_content(patched_env):
    resp = _export(_state(FILTERS))
    assert resp.media_type.startswith("text/markdown")
    assert resp.headers["Content-Disposition"] == 'attachment; filename="wells_rivers.qmd"'
    src = resp.body.decode()
    assert src.startswith("---\ntitle: Wells & Rivers\n")
    assert "\njupyter: python3\n" in src.split("\n---\n", 1)[0]
    assert "title: Wells & Rivers" in src and "subtitle: Where the samples came from" in src
    assert "# Wells & Rivers" not in src
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
    assert pre.render_available is True  # on by default; a deployment turns it off


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


def test_old_format_field_still_gets_the_quarto_document(patched_env):
    """A client from before the single format sent ``format``; it is ignored."""
    request = NotebookExportRequest.model_validate(
        {"state": _state([]).model_dump(mode="json"), "format": "ipynb"}
    )
    resp = nbx.notebook_export(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        request=request,
        current_user=_User(),
        access_token=None,
    )
    assert resp.headers["Content-Disposition"].endswith('.qmd"')


# ── The rendered report ───────────────────────────────────────────────────────


def _pinned_state(pins):
    return AnalysisState.model_validate(
        {
            **_state(FILTERS).model_dump(mode="json"),
            "pins": pins,
        }
    )


def test_a_pinned_export_reads_the_pinned_commit_and_says_what_stays_live(patched_env):
    source = _export(_pinned_state({"data_versions": {DC1: 2}})).body.decode()
    assert f"client.data({DC1!r}, version=2)" in source
    assert "read at Delta commit 2" in source
    pre = _preflight(_pinned_state({"data_versions": {DC1: 2}}))
    assert any("not versioned on the server" in w for w in pre.warnings)
    # The live export is unchanged.
    assert "version=" not in _export(_state(FILTERS)).body.decode().split("client.data(")[1][:60]


def test_a_version_that_no_longer_exists_is_a_400(patched_env):
    store = "depictio.api.v1.endpoints.dashboards_endpoints.data_versions.version_store"
    with (
        patch(f"{store}.get_version", lambda vid: None),
        patch(f"{store}.get_version_tab", lambda vid, tab: None),
    ):
        with pytest.raises(HTTPException) as exc:
            _export(_pinned_state({"as_of_version": "gone", "definition_version": "gone"}))
    assert exc.value.status_code == 400
    assert "no longer exists" in str(exc.value.detail)


class _RenderUser:
    email = "t.weber@example.org"
    id = ObjectId()
    is_anonymous = False


class _Someone(_RenderUser):
    id = ObjectId()


class _Anonymous:
    email = "anonymous@depictio.io"
    id = ObjectId()
    is_anonymous = True


def _render(state, user=None):
    return nbx.notebook_export_render(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        request=NotebookExportRequest(state=state, format="quarto"),
        current_user=user or _RenderUser(),  # type: ignore[arg-type]
        access_token=None,
    )


def _staging(staged: dict, queued: dict):
    return (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch(
            "depictio.api.v1.services.notebook_export.store.put",
            lambda key, body, content_type: staged.__setitem__(key, body),
        ),
        patch(
            "depictio.api.celery_app.render_notebook_report.apply_async",
            lambda **kw: queued.update(kw),
        ),
    )


def test_render_turned_off_is_501(patched_env):
    """On by default; a deployment whose worker has no Quarto turns it off."""
    with (
        patch.object(nbx.settings.notebook_export, "render_enabled", False),
        pytest.raises(HTTPException) as exc,
    ):
        _render(_state([]))
    assert exc.value.status_code == 501


def test_render_stages_the_notebook_and_queues_the_job(patched_env):
    """The notebook goes to S3 under the caller's prefix; the broker gets its key."""
    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}
    a, b, c = _staging(staged, queued)
    with a, b, c:
        status = _render(_state(FILTERS))

    assert status.status == "queued" and status.filename.endswith(".html")
    key = next(iter(staged))
    assert key.startswith(f"notebook_reports/{_RenderUser.id}/{status.job_id}/")
    assert key.endswith(".qmd")
    # What was staged is the Quarto document the download hands out, front matter and all.
    assert staged[key].startswith(b"---\ntitle: Wells & Rivers\n")
    # The job is addressed by the id the caller was handed, and carries no
    # token at all: the worker mints one when the render starts.
    assert queued["task_id"] == status.job_id
    assert queued["kwargs"]["notebook_key"] == key
    assert "token_id" not in queued["kwargs"] and "access_token" not in queued["kwargs"]
    # Bound to who asked, from the moment it is queued.
    from depictio.api.v1.services.notebook_export import jobs

    assert jobs.owned(status.job_id, str(_RenderUser.id), jobs.RENDER) is not None
    assert jobs.owned(status.job_id, str(ObjectId()), jobs.RENDER) is None


def test_a_render_without_a_state_hands_the_worker_the_resolved_one(patched_env):
    """A request may leave the state to the report layer (#1457): the runtime
    the worker embeds opens on the state the document was built at, never on
    a missing one."""
    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}
    a, b, c = _staging(staged, queued)
    with a, b, c, patch.object(nbx, "_embed_runtime", lambda *args, **kwargs: True):
        status = _render(None)

    assert status.status == "queued"
    runtime = queued["kwargs"]["runtime"]  # type: ignore[index]
    assert runtime["state"]["context"]["dashboard_id"] == str(DASHBOARD_ID)


def test_the_server_render_never_carries_the_author_s_code(patched_env):
    """The downloaded notebook keeps the code-mode figure's Python for its reader
    to run; the document the worker executes asks the API for that figure,
    which runs the code in the dashboard's sandbox."""
    staged: dict[str, bytes] = {}
    a, b, c = _staging(staged, {})
    with a, b, c:
        _render(_state(FILTERS))
    rendered = next(iter(staged.values())).decode()
    assert "fig = px.scatter(df.to_pandas()" not in rendered
    assert "'fig-2'" in rendered and "client.component(" in rendered
    assert "fig = px.scatter(df.to_pandas()" in _export(_state(FILTERS)).body.decode()


def test_an_anonymous_visitor_cannot_render(patched_env):
    """Every anonymous visitor is the same user: a job of theirs would be everyone's."""
    with (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch.object(type(nbx.settings.auth), "is_single_user_mode", False),
        pytest.raises(HTTPException) as exc,
    ):
        _render(_state(FILTERS), user=_Anonymous())
    assert exc.value.status_code == 401


def test_renders_are_limited_per_user(patched_env):
    staged: dict[str, bytes] = {}
    a, b, c = _staging(staged, {})
    with (
        a,
        b,
        c,
        patch.object(nbx.settings.notebook_export, "render_max_active_per_user", 2),
    ):
        user = _RenderUser()
        _render(_state([]), user=user)
        _render(_state([]), user=user)
        with pytest.raises(HTTPException) as exc:
            _render(_state([]), user=user)
    assert exc.value.status_code == 429


def test_a_failed_render_says_a_sentence_and_only_to_its_owner(patched_env):
    """A failure's own text (Quarto's log, worker paths) is the server's."""
    from depictio.api.v1.services.notebook_export import jobs

    owner = _RenderUser()
    jobs.record("failed-job", str(owner.id), jobs.RENDER)
    jobs.finish("failed-job", "failed", reason="the report ran past its time limit")

    class _Failed:
        state = "FAILURE"
        result = RuntimeError("/srv/worker/tmp/depictio-report-x: cell 4 printed SECRET")

        def successful(self):
            return False

        def failed(self):
            return True

    with (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch("celery.result.AsyncResult", lambda *a, **k: _Failed()),
    ):
        status = nbx.notebook_export_render_status(job_id="failed-job", current_user=owner)  # type: ignore[arg-type]
        assert status.status == "error"
        assert status.reason == "the report ran past its time limit"
        with pytest.raises(HTTPException) as exc:
            nbx.notebook_export_render_status(job_id="failed-job", current_user=_Someone())  # type: ignore[arg-type]
    assert exc.value.status_code == 404


def test_a_combined_render_queues_the_combined_job(patched_env):
    """The default export: the report AND the dashboard, one file, its own name."""
    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}
    a, b, c = _staging(staged, queued)
    with a, b, c, patch.object(nbx, "_combined_refusal", lambda *a: None):
        status = nbx.notebook_export_render(
            dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
            request=NotebookExportRequest(
                state=_state(FILTERS), output="combined", default_view="dashboard"
            ),
            current_user=_RenderUser(),  # type: ignore[arg-type]
            access_token=None,
        )
    assert status.filename.endswith("-report-dashboard.html")
    kwargs = queued["kwargs"]
    assert kwargs["combined"] == {"default_view": "dashboard"}
    assert kwargs["filename"] == status.filename
    # The combined file always embeds the runtime: its tiles are placeholders.
    assert kwargs["runtime"] is not None
    assert b"data-depictio-tile" in next(iter(staged.values()))


def test_the_preflight_says_whether_the_combined_file_is_on(patched_env):
    with patch.object(nbx, "_combined_refusal", lambda *a: "this server does not render reports"):
        pre = _preflight(_state(FILTERS))
    assert pre.combined_available is False
    assert pre.combined_reason == "this server does not render reports"
    with patch.object(nbx, "_combined_refusal", lambda *a: None):
        pre = _preflight(_state(FILTERS))
    assert pre.combined_available is True and pre.combined_reason is None


def test_the_preflight_says_why_a_viewer_cannot_have_the_code_figures_rendered(patched_env):
    """The render's refusal is said before the click (#1480): a viewer of a
    dashboard with code-mode figures reads it in the preflight; an editor reads
    nothing; and a server that does not render says nothing either."""
    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"

    def _preflight(state):  # as a signed-in reader
        return nbx.notebook_export_preflight(
            dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
            request=NotebookExportRequest(state=state),
            current_user=_RenderUser(),  # type: ignore[arg-type]
            access_token=None,
        )

    with (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch.object(type(nbx.settings.auth), "is_single_user_mode", False),
    ):
        with patch(
            f"{routes_mod}.check_project_permission",
            lambda project_id, user, required="viewer": required != "editor",
        ):
            pre = _preflight(_state(FILTERS))
        assert pre.render_reason and "code-mode" in pre.render_reason
        with patch(
            f"{routes_mod}.check_project_permission",
            lambda project_id, user, required="viewer": True,
        ):
            assert _preflight(_state(FILTERS)).render_reason is None
    with patch.object(nbx.settings.notebook_export, "render_enabled", False):
        assert _preflight(_state(FILTERS)).render_reason is None


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
    """A code-mode figure is the author's Python: rendering it is the project
    owners' and editors' call, not a dashboard owner's (a viewer can own a
    dashboard document)."""
    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    with (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch.object(type(nbx.settings.auth), "is_single_user_mode", False),
        patch(
            f"{routes_mod}.check_project_permission",
            lambda project_id, user, required="viewer": required != "editor",
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            _render(_state(FILTERS))
    assert exc.value.status_code == 403
    assert "code-mode" in exc.value.detail


def test_an_editor_can_render_author_written_code(patched_env):
    """An editor of the project may render it (#1457): the report layer they
    write reaches the same export as the owner's. A viewer stays refused —
    even one who owns the dashboard document (its copy is theirs, its data
    is not)."""
    from types import SimpleNamespace

    plan = SimpleNamespace(
        tabs=[
            {
                "project_id": "p1",
                "stored_metadata": [
                    {"component_type": "figure", "mode": "code", "title": "F", "index": "c1"}
                ],
            }
        ]
    )
    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    with (
        patch.object(type(nbx.settings.auth), "is_single_user_mode", False),
        patch(
            f"{routes_mod}.check_project_permission",
            lambda project_id, user, required="viewer": required in ("owner", "editor"),
        ),
    ):
        nbx._require_owner_for_authored_code(plan, _RenderUser())  # type: ignore[arg-type]
        with patch(
            f"{routes_mod}.check_project_permission",
            lambda project_id, user, required="viewer": required == "owner",
        ):
            with pytest.raises(HTTPException) as exc:
                nbx._require_owner_for_authored_code(plan, _RenderUser())  # type: ignore[arg-type]
    assert exc.value.status_code == 403


def test_a_definition_version_exports_the_components_as_that_version_defined_them():
    live = {
        "dashboard_id": DASHBOARD_ID,
        "stored_metadata": [
            {
                "index": "c1",
                "component_type": "card",
                "aggregation": "mean",
                "dc_id": DC1,
                "dc_config": {"live": True},
            },
            {"index": "c2", "component_type": "card", "aggregation": "sum", "dc_id": DC1},
        ],
    }
    stored = {
        "stored_metadata": [
            {
                "index": "c1",
                "component_type": "card",
                "aggregation": "median",
                "dc_id": DC1,
                "dc_config": {"live": False},
            },
            {"index": "c2", "component_type": "card", "aggregation": "sum", "dc_id": "other"},
        ]
    }
    warnings: list[str] = []
    with patch.object(nbx.routes, "_definition_tab", lambda tab, vid: stored):
        (tab,) = nbx._overlay_definitions([live], "v1", {DC1}, warnings)
    (card,) = tab["stored_metadata"]
    assert card["aggregation"] == "median"  # the version's definition
    assert card["dc_config"] == {"live": True}  # the live identity fields
    assert warnings and "another collection" in warnings[0]


def test_report_images_are_inlined_from_the_apps_own_assets_only(monkeypatch):
    """The dashboard's mark and a text tile's logo end up as data URIs; a path
    outside the static assets, or a non-image, is never read into the file."""
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as ep

    uri = ep._image_data_uri("/assets/images/workflows/nf-core.png")
    assert uri and uri.startswith("data:image/png;base64,")
    assert ep._image_data_uri("/assets/../../../../etc/passwd") is None
    assert ep._image_data_uri("relative/logo.png") is None
    assert ep._image_data_uri("data:image/png;base64,AAAA") == "data:image/png;base64,AAAA"

    import depictio.api.v1.remote_fetch as rf

    monkeypatch.setattr(rf, "fetch_validated_bytes", lambda url, **kw: b"<html>not an image")
    assert ep._image_data_uri("https://example.org/logo.png") is None
    monkeypatch.setattr(rf, "fetch_validated_bytes", lambda url, **kw: b"\x89PNG\r\n\x1a\nxx")
    logos = ep._resolve_text_logos(
        [
            {
                "stored_metadata": [
                    {"index": "hero", "component_type": "text", "logo": "https://e.org/l.png"},
                    {"index": "fig", "component_type": "figure", "logo": "https://e.org/l.png"},
                ]
            }
        ]
    )
    assert set(logos) == {"hero"} and logos["hero"]["light"].startswith("data:image/png")
    assert ep._depictio_mark().startswith("data:image/svg+xml;base64,")
