"""The report host of the static runtime (``depictio/serverless/report.py``).

A rendered report embeds producer A's manifest, once, beside the report
runtime. These tests hold it to that: the manifest a report carries IS the one
a static export of the same dashboard bundles (same producer, same body, same
permission rule), with only ``initial_filters`` added; a state the runtime
cannot reproduce is refused; and the endpoints only clear an owner.

They run on the offline producer-A stack of ``test_serverless_export.py``
(fake Mongo collections and endpoint bodies), so no infrastructure is needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bson import ObjectId

from depictio.models.models.analysis_state import AnalysisState, NotebookExportRequest
from depictio.notebook.report_runtime import CONFIG_ID, MANIFEST_ID, RUNTIME_MARK
from depictio.serverless import report
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
# The block: runtime + manifest, once
# ---------------------------------------------------------------------------


@pytest.fixture
def built_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / report.RUNTIME_JS).write_text("window.__ran=1;/*</script>*/")
    (tmp_path / report.RUNTIME_CSS).write_text(".depictio-report-root{color:red}")
    monkeypatch.setenv(report.RUNTIME_DIR_ENV, str(tmp_path))
    return tmp_path


@pytest.mark.usefixtures("offline_stack")
def test_the_block_inlines_runtime_and_manifest_once(built_runtime):
    manifest = report.build_report_manifest(str(DASHBOARD_OID), ADMIN, _state())
    html = report.report_runtime_html(manifest, config={"brand": {"primary": "#123456"}})
    assert html.count(f'id="{MANIFEST_ID}"') == 1
    assert html.count(f'id="{CONFIG_ID}"') == 1
    assert html.count(f'{RUNTIME_MARK}="js"') == 1
    assert html.count(f'{RUNTIME_MARK}="css"') == 1
    # Nothing inside can close the element it is in.
    assert html.count("</script>") == 3  # config, manifest, runtime
    assert "#123456" in html
    # The manifest goes before the script that reads it.
    assert html.index(MANIFEST_ID) < html.index(f'{RUNTIME_MARK}="js"')


def test_runtime_missing_is_a_named_error(tmp_path, monkeypatch):
    monkeypatch.setenv(report.RUNTIME_DIR_ENV, str(tmp_path))
    assert not report.runtime_available()
    with pytest.raises(report.ReportRuntimeUnavailable, match="build:static"):
        report.runtime_assets()


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


def test_the_worker_writes_an_empty_block_when_it_cannot_build(monkeypatch, tmp_path):
    """A failed manifest build must not make the document ask the API instead."""
    from depictio.api import celery_app as worker

    def boom(*a, **kw):
        raise ProducerAError("permission denied")

    monkeypatch.setattr(report, "build_report_runtime", boom)
    path = worker._report_runtime_file(
        "job1",
        {
            "dashboard_id": str(DASHBOARD_OID),
            "state": _state().model_dump(mode="json"),
            "user": {"id": str(ObjectId()), "email": "", "is_admin": False, "is_anonymous": False},
            "config": None,
        },
    )
    try:
        assert Path(path).read_text() == ""
    finally:
        Path(path).unlink()
