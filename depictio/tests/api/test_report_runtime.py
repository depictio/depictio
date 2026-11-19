"""The report host of the static runtime (``depictio/serverless/report.py``).

A rendered report embeds producer A's manifest, once, beside the static
runtime. These tests hold it to that: the manifest a report carries IS the one
a static export of the same dashboard bundles (same producer, same body, same
permission rule), with only ``initial_filters`` added; a state the runtime
cannot reproduce is refused; the endpoints only clear an owner; and a reader's
own render gets the manifest from a worker job, not from the API process.

They run on the offline producer-A stack of ``test_serverless_export.py``
(fake Mongo collections and endpoint bodies), so no infrastructure is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from bson import ObjectId

from depictio.models.models.analysis_state import AnalysisState, NotebookExportRequest
from depictio.serverless import combined, report
from depictio.serverless.producer_a import ExportUser, ProducerAError, export_manifest
from depictio.tests.api.test_serverless_export import (  # noqa: F401 (fixture)
    DASHBOARD_OID,
    DC_OID,
    PROJECT_OID,
    _dashboard_doc,
    _FakeCollection,
    offline_stack,
)

ADMIN = ExportUser(id=ObjectId(), is_admin=True)


def _state(**extra: Any) -> AnalysisState:
    return AnalysisState.model_validate(
        {
            "filters": [
                {
                    "index": "ms-1",
                    "column_name": "species",
                    "interactive_component_type": "MultiSelect",
                    "value": ["Adelie"],
                    "metadata": {"dc_id": str(DC_OID), "column_name": "species"},
                }
            ],
            "context": {"dashboard_id": str(DASHBOARD_OID)},
            **extra,
        }
    )


def _comparable(dump: dict[str, Any]) -> dict[str, Any]:
    """A manifest dump without what differs between two builds of one state."""
    out = dict(dump)
    out.pop("built_at", None)
    out.pop("initial_filters", None)
    provenance = dict(out.get("provenance") or {})
    provenance.pop("exported_at", None)
    out["provenance"] = provenance
    return out


# ---------------------------------------------------------------------------
# The manifest: producer A's own
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("offline_stack")
def test_the_report_manifest_is_producer_a_manifest():
    state = _state()
    bundled = export_manifest(str(DASHBOARD_OID), ADMIN).manifest
    reported = report.build_report_manifest(str(DASHBOARD_OID), ADMIN, state)
    assert bundled is not None
    assert _comparable(reported.model_dump(mode="json")) == _comparable(
        bundled.model_dump(mode="json")
    )
    # The one addition: the runtime opens on the exported state.
    assert bundled.initial_filters == []
    assert reported.initial_filters == state.filters_as_payload()
    # And it is still a valid manifest of the contract.
    type(reported).model_validate(reported.model_dump(mode="json"))


def test_the_report_manifest_needs_owner_like_the_static_export(monkeypatch):
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod

    monkeypatch.setattr(db_mod, "dashboards_collection", _FakeCollection([_dashboard_doc()]))
    monkeypatch.setattr(
        routes_mod,
        "projects_collection",
        _FakeCollection(
            [
                {
                    "_id": PROJECT_OID,
                    "is_public": True,
                    "permissions": {"owners": [], "editors": [], "viewers": []},
                }
            ]
        ),
    )
    viewer = ExportUser(id=ObjectId(), is_admin=False)
    with pytest.raises(ProducerAError, match="permission denied"):
        report.build_report_manifest(str(DASHBOARD_OID), viewer, _state())


def test_no_user_is_never_read_as_the_admin():
    with pytest.raises(report.ReportRuntimeRefused, match="requester"):
        report.build_report_manifest(str(DASHBOARD_OID), None, _state())


@pytest.mark.parametrize(
    "extra,needle",
    [
        ({"pins": {"as_of_version": "v1"}}, "pinned"),
        ({"pins": {"data_versions": {str(DC_OID): 2}}}, "pinned"),
        ({"color_by": {"kind": "groups"}}, "selection groups"),
        ({"split_panels": [{"name": "A", "constraints": []}]}, "selection groups"),
        (
            {
                "groups": [
                    {
                        "id": "g",
                        "name": "G",
                        "color": "#000",
                        "column_name": "species",
                        "filter_active": True,
                    }
                ]
            },
            "selection group",
        ),
    ],
)
def test_a_state_the_page_cannot_reproduce_is_refused(extra, needle):
    state = _state(**extra)
    assert needle in (report.ineligibility(state) or "")
    with pytest.raises(report.ReportRuntimeRefused):
        report.build_report_manifest(str(DASHBOARD_OID), ADMIN, state)


def test_a_plain_state_is_eligible_and_group_filters_never_ride_along():
    state = _state()
    assert report.ineligibility(state) is None
    state.filters.append(
        state.filters[0].model_copy(update={"index": "__g__", "source": "group_filter"})
    )
    assert [f["index"] for f in report.initial_filters(state)] == ["ms-1"]


# ---------------------------------------------------------------------------
# The manifest as text: serialised once
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("offline_stack")
def test_the_manifest_json_is_the_dump_serialised_once():
    manifest = report.build_report_manifest(str(DASHBOARD_OID), ADMIN, _state())
    text = report.manifest_json(manifest)
    assert json.loads(text) == json.loads(json.dumps(manifest.model_dump(mode="json")))


def test_the_manifest_json_falls_back_for_what_pydantic_cannot_write():
    class _Odd:
        def model_dump_json(self) -> str:
            raise TypeError("numpy.float32 is not JSON serializable")

        def model_dump(self, mode: str = "json") -> dict[str, Any]:
            return {"x": float("nan"), "y": object.__name__}

    assert json.loads(report.manifest_json(_Odd())) == {"x": None, "y": "object"}  # type: ignore[arg-type]


@pytest.fixture
def built_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / combined.RUNTIME_JS).write_text("window.__ran=1;/*</script>*/")
    (tmp_path / combined.RUNTIME_CSS).write_text(".depictio-report-root{color:red}")
    monkeypatch.setenv(report.RUNTIME_DIR_ENV, str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# The endpoints' gate
# ---------------------------------------------------------------------------


def _request(**kw: Any) -> NotebookExportRequest:
    return NotebookExportRequest(state=_state(), **kw)


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch, built_runtime):
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as routes_mod

    owners: set[str] = set()
    monkeypatch.setattr(
        routes_mod,
        "dashboards_collection",
        _FakeCollection([{"dashboard_id": DASHBOARD_OID, "project_id": PROJECT_OID}]),
    )
    monkeypatch.setattr(
        routes_mod,
        "check_project_permission",
        lambda project_id, user, level: level == "owner" and str(user.id) in owners,
    )
    return owners


def test_only_an_owner_gets_the_runtime(gate):
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as ep

    user = ExportUser(id=ObjectId())
    assert "owners" in (ep._runtime_refusal(DASHBOARD_OID, _state(), user) or "")
    gate.add(str(user.id))
    assert ep._runtime_refusal(DASHBOARD_OID, _state(), user) is None
    assert "pinned" in (
        ep._runtime_refusal(DASHBOARD_OID, _state(pins={"as_of_version": "v"}), user) or ""
    )


def test_a_runtime_that_is_not_built_is_a_refusal_of_its_own(gate, built_runtime):
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as ep

    owner = ExportUser(id=ObjectId())
    gate.add(str(owner.id))
    (built_runtime / combined.RUNTIME_JS).unlink()
    assert "not built" in (ep._runtime_refusal(DASHBOARD_OID, _state(), owner) or "")
    # The owner rule does not depend on it.
    assert ep._owner_refusal(DASHBOARD_OID, _state(), owner) is None


def test_render_embeds_by_default_and_the_download_does_not(gate):
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as ep

    owner = ExportUser(id=ObjectId())
    gate.add(str(owner.id))
    assert ep._embed_runtime(_request(), DASHBOARD_OID, owner, default=True) is True
    assert ep._embed_runtime(_request(), DASHBOARD_OID, owner, default=False) is False
    assert ep._embed_runtime(_request(embed_runtime=True), DASHBOARD_OID, owner, default=False)
    assert not ep._embed_runtime(_request(embed_runtime=False), DASHBOARD_OID, owner, default=True)
    # Asked for, but not an owner: the document is the plain notebook.
    stranger = ExportUser(id=ObjectId())
    assert not ep._embed_runtime(
        _request(embed_runtime=True), DASHBOARD_OID, stranger, default=True
    )


# ---------------------------------------------------------------------------
# A reader's own render: the manifest is a worker job
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, state: str, result: Any = None) -> None:
        self.state = state
        self.result = result
        self.traceback = None

    def failed(self) -> bool:
        return self.state == "FAILURE"

    def successful(self) -> bool:
        return self.state == "SUCCESS"


def _routes():
    from depictio.api.v1.endpoints.serverless_endpoints import routes

    return routes


def test_the_manifest_route_queues_a_job_for_an_owner(monkeypatch):
    routes = _routes()
    queued: dict[str, Any] = {}
    owner = ExportUser(id=ObjectId(), email="o@x")
    monkeypatch.setattr(
        routes,
        "dashboards_collection",
        _FakeCollection([{"dashboard_id": DASHBOARD_OID, "project_id": PROJECT_OID}]),
    )
    monkeypatch.setattr(
        routes,
        "check_project_permission",
        lambda project_id, user, level: level == "owner" and user is owner,
    )
    monkeypatch.setattr(
        "depictio.api.celery_app.build_report_manifest_job.apply_async",
        lambda **kw: queued.update(kw),
    )
    out = routes.post_report_manifest(str(DASHBOARD_OID), _request(), current_user=owner)
    assert out["status"] == "queued" and queued["task_id"] == out["job_id"]
    assert queued["kwargs"]["runtime"]["user"] == {
        "id": str(owner.id),
        "email": "o@x",
        "is_admin": False,
        "is_anonymous": False,
    }
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as denied:
        routes.post_report_manifest(
            str(DASHBOARD_OID), _request(), current_user=ExportUser(id=ObjectId())
        )
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as refused:
        routes.post_report_manifest(
            str(DASHBOARD_OID),
            NotebookExportRequest(state=_state(pins={"as_of_version": "v1"})),
            current_user=owner,
        )
    assert refused.value.status_code == 409


def test_the_manifest_poll_answers_the_job(monkeypatch):
    from fastapi import HTTPException

    routes = _routes()
    owner = ExportUser(id=ObjectId())
    results: dict[str, _Result] = {}
    monkeypatch.setattr(routes, "AsyncResult", lambda job_id, app=None: results[job_id])
    monkeypatch.setattr(
        "depictio.api.v1.services.notebook_export.store.get",
        lambda key: b'{"dashboard":{"id":"d"}}',
    )
    results["q"] = _Result("PENDING")
    assert routes.poll_report_manifest("q", current_user=owner)["status"] == "queued"
    results["r"] = _Result("PROGRESS", {"user_id": str(owner.id)})
    assert routes.poll_report_manifest("r", current_user=owner)["status"] == "running"
    results["ok"] = _Result("SUCCESS", {"user_id": str(owner.id), "key": "k"})
    body = json.loads(routes.poll_report_manifest("ok", current_user=owner).body)
    assert body == {"job_id": "ok", "status": "ready", "manifest": {"dashboard": {"id": "d"}}}
    # Somebody else's job is not found.
    with pytest.raises(HTTPException) as other:
        routes.poll_report_manifest("ok", current_user=ExportUser(id=ObjectId()))
    assert other.value.status_code == 404
    # A refusal answers as the route would have.
    for exc, status in (
        (report.ReportRuntimeRefused("pinned"), 409),
        (ProducerAError("permission denied"), 404),
        (RuntimeError("boom"), 500),
    ):
        results["f"] = _Result("FAILURE", exc)
        with pytest.raises(HTTPException) as failed:
            routes.poll_report_manifest("f", current_user=owner)
        assert failed.value.status_code == status


def test_the_manifest_job_stores_the_manifest_under_its_requester(monkeypatch):
    from depictio.api import celery_app as worker

    stored: dict[str, bytes] = {}
    monkeypatch.setattr(
        "depictio.api.v1.services.notebook_export.store.put",
        lambda key, body, ct: stored.__setitem__(key, body),
    )
    monkeypatch.setattr(worker.build_report_manifest_job, "update_state", lambda **k: None)

    class _M:
        def model_dump_json(self) -> str:
            return '{"ok":true}'

    seen: dict[str, Any] = {}

    def fake(runtime: dict) -> Any:
        seen["args"] = worker._runtime_args(runtime)
        return _M()

    monkeypatch.setattr(worker, "_report_manifest", fake)
    user = {"id": str(ObjectId()), "email": "", "is_admin": False, "is_anonymous": False}
    out = worker.build_report_manifest_job.run(
        job_id="j1",
        runtime={
            "dashboard_id": str(DASHBOARD_OID),
            "state": _state().model_dump(mode="json"),
            "user": user,
        },
    )
    assert out["user_id"] == user["id"] and out["key"].endswith(f"/{user['id']}/j1/manifest.json")
    assert stored[out["key"]] == b'{"ok":true}'
    dashboard_id, export_user, state = seen["args"]
    assert dashboard_id == str(DASHBOARD_OID) and export_user.id == user["id"]
    assert state.filters[0].index == "ms-1"
