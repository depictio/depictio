"""Tests for POST /projects/ingest_manifest (`_ingest_manifest_into_project`).

Same philosophy as the create_from_url tests: the full scan → remote read →
Delta pipeline is covered by the CLI unit tests; here we prove the endpoint's
contract — SSRF-gateway rejection precedes any database access, the type→tag
mapping and per-DC report are correct, the manifest scan config is persisted
on success and reverted on failure.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest, storage_config
from depictio.api.v1.remote_fetch import RemoteURLRejected
from depictio.models.models.users import UserBase

MANIFEST_JSON = """
[
  {"id": "s1", "type": "counts", "url": "https://example.org/s1.csv"},
  {"id": "s2", "type": "counts", "url": "https://example.org/s2.csv", "run": "batch1"},
  {"id": "s1", "type": "unmapped_type", "url": "https://example.org/x.csv"}
]
"""


def _user(is_admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


def _call(
    manifest_url: str = "https://example.org/manifest.json",
    project_id: str = str(ObjectId()),
    user=None,
    dry_run: bool = False,
):
    return manifest_ingest._ingest_manifest_into_project(
        project_id=project_id,
        manifest_url=manifest_url,
        current_user=user or _user(),
        dry_run=dry_run,
    )


def _project_doc(owner_id: ObjectId, tags: list[str]) -> dict:
    """A minimal project document whose workflows parse as Workflow models."""
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanURL,
    )
    from depictio.models.models.data_collections_types.table import DCTableConfig
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    data_collections = [
        DataCollection(
            data_collection_tag=tag,
            config=DataCollectionConfig(
                type="table",
                metatype="metadata",
                scan=Scan(
                    mode="url", scan_parameters=ScanURL(url=f"https://example.org/{tag}.csv")
                ),
                dc_specific_properties=DCTableConfig(format="csv"),
            ),
        )
        for tag in tags
    ]
    workflow = Workflow(
        name="wf",
        workflow_tag="wf",
        engine=WorkflowEngine(name="python", version="3.12"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(
            structure="flat", locations=["https://example.org/manifest.json"]
        ),
        data_collections=data_collections,
    )
    return {
        "_id": ObjectId(),
        "name": "manifest-project",
        "permissions": {"owners": [{"_id": owner_id}]},
        "workflows": [workflow.mongo()],
    }


def test_bad_scheme_rejected_before_db():
    # No DB patching at all: a gateway rejection must never reach Mongo.
    with pytest.raises(HTTPException) as exc:
        _call("ftp://example.org/manifest.json")
    assert exc.value.status_code == 400


def test_private_host_rejected_before_db():
    with pytest.raises(HTTPException) as exc:
        _call("https://127.0.0.1/manifest.json")
    assert exc.value.status_code == 400


def test_s3_manifest_rejected():
    with pytest.raises(HTTPException) as exc:
        _call("s3://bucket/manifest.json")
    assert exc.value.status_code == 400
    assert "s3" in exc.value.detail.lower()


@pytest.fixture()
def mock_db(monkeypatch):
    # example.org resolves publicly; allowlisting keeps the gateway green
    # without network (allowlisted hosts skip DNS resolution).
    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "example.org")
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(manifest_ingest, "projects_collection", database["projects"]),
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
        # The ingest flow resolves per-project storage credentials.
        patch.object(storage_config, "project_storage_collection", database["project_storage"]),
    ):
        yield database


@pytest.fixture()
def served_manifest():
    """Bypass the actual download, keep the gateway call visible."""

    def _fake_download(url, dest_path, max_bytes=None, timeout_s=30.0):
        with open(dest_path, "w") as fh:
            fh.write(MANIFEST_JSON)
        return len(MANIFEST_JSON)

    with patch.object(manifest_ingest, "bounded_download", side_effect=_fake_download):
        yield


def test_unknown_project_404(mock_db):
    with pytest.raises(HTTPException) as exc:
        _call()
    assert exc.value.status_code == 404


def test_no_edit_permission_403(mock_db):
    project_id = ObjectId()
    mock_db["projects"].insert_one({"_id": project_id, "permissions": {"owners": []}})
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(project_id))
    assert exc.value.status_code == 403


def test_no_matching_type_422(mock_db, served_manifest):
    user = _user()
    doc = _project_doc(user.id, tags=["something_else"])
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user, dry_run=True)
    assert exc.value.status_code == 422
    assert "counts" in exc.value.detail  # available manifest types are surfaced


def test_unparseable_manifest_422(mock_db):
    user = _user()
    doc = _project_doc(user.id, tags=["counts"])
    mock_db["projects"].insert_one(doc)

    def _bad_download(url, dest_path, max_bytes=None, timeout_s=30.0):
        with open(dest_path, "w") as fh:
            fh.write("{not json")
        return 8

    with patch.object(manifest_ingest, "bounded_download", side_effect=_bad_download):
        with pytest.raises(HTTPException) as exc:
            _call(project_id=str(doc["_id"]), user=user, dry_run=True)
    assert exc.value.status_code == 422


def test_dry_run_reports_mapping_without_touching_project(mock_db, served_manifest):
    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)

    report = _call(project_id=str(doc["_id"]), user=user, dry_run=True)

    assert report.success is True
    assert report.dry_run is True
    assert report.manifest_entries == 3
    assert [m.data_collection_tag for m in report.matched] == ["counts"]
    assert report.matched[0].status == "planned"
    assert report.matched[0].entries == 2
    assert report.unmatched_manifest_types == ["unmapped_type"]
    assert report.unmatched_dc_tags == ["annotations"]

    # Plan only: the stored scan config must be untouched.
    stored = mock_db["projects"].find_one({"_id": doc["_id"]})
    scan = stored["workflows"][0]["data_collections"][0]["config"]["scan"]
    assert scan["mode"] == "url"


def test_ingest_persists_manifest_scan_config(mock_db, served_manifest):
    user = _user()
    doc = _project_doc(user.id, tags=["counts"])
    mock_db["projects"].insert_one(doc)
    mock_db["tokens"].insert_one({"user_id": user.id, "access_token": "x"})

    with (
        patch.object(dc_utils, "_build_cli_config_for_user", return_value=object()),
        patch(
            "depictio.cli.cli.utils.helpers.process_data_collection_helper",
            return_value={"result": "success"},
        ) as helper,
    ):
        report = _call(project_id=str(doc["_id"]), user=user)

    assert report.success is True
    assert report.matched[0].status == "ingested"
    # scan then process for the single matched DC
    assert [c.kwargs.get("mode") for c in helper.call_args_list] == ["scan", "process"]

    stored = mock_db["projects"].find_one({"_id": doc["_id"]})
    scan = stored["workflows"][0]["data_collections"][0]["config"]["scan"]
    assert scan["mode"] == "manifest"
    assert scan["scan_parameters"]["manifest_url"] == "https://example.org/manifest.json"
    assert scan["scan_parameters"]["manifest_type"] == "counts"


def test_failed_ingest_reverts_scan_config(mock_db, served_manifest):
    user = _user()
    doc = _project_doc(user.id, tags=["counts"])
    mock_db["projects"].insert_one(doc)
    mock_db["tokens"].insert_one({"user_id": user.id, "access_token": "x"})

    with (
        patch.object(dc_utils, "_build_cli_config_for_user", return_value=object()),
        patch(
            "depictio.cli.cli.utils.helpers.process_data_collection_helper",
            return_value={"result": "error", "message": "boom"},
        ),
    ):
        report = _call(project_id=str(doc["_id"]), user=user)

    assert report.success is False
    assert report.matched[0].status == "failed"
    assert "boom" in (report.matched[0].message or "")

    # The failed DC's scan config must be back to its pre-ingest state.
    stored = mock_db["projects"].find_one({"_id": doc["_id"]})
    scan = stored["workflows"][0]["data_collections"][0]["config"]["scan"]
    assert scan["mode"] == "url"


# One entry on a host the gateway rejects (the other host passes).
MANIFEST_WITH_INTERNAL_ENTRY = """
[
  {"id": "s1", "type": "counts", "url": "https://example.org/s1.csv"},
  {"id": "s2", "type": "counts", "url": "https://internal.example/s2.csv"}
]
"""

INTERNAL_HOST_REASON = "Host 'internal.example' resolves to a non-public address and was rejected."


def _gate_rejecting_internal(url):
    """validate_remote_url stand-in: rejects internal.example, passes the rest."""
    if "internal.example" in url:
        raise RemoteURLRejected(INTERNAL_HOST_REASON)


def _serve(content: str):
    def _download(url, dest_path, max_bytes=None, timeout_s=30.0):
        with open(dest_path, "w") as fh:
            fh.write(content)
        return len(content)

    return patch.object(manifest_ingest, "bounded_download", side_effect=_download)


def test_rejected_entry_url_400_and_nothing_ingested(mock_db):
    # Entry URLs are gateway-checked after parsing, before any File is
    # registered: a public manifest must not be able to point the worker at an
    # internal service. The 400 lists the offending entries, and the project is
    # left exactly as it was (no scan ran, scan config untouched).
    user = _user()
    doc = _project_doc(user.id, tags=["counts"])
    mock_db["projects"].insert_one(doc)
    mock_db["tokens"].insert_one({"user_id": user.id, "access_token": "x"})

    with (
        _serve(MANIFEST_WITH_INTERNAL_ENTRY),
        patch.object(manifest_ingest, "validate_remote_url", side_effect=_gate_rejecting_internal),
        patch("depictio.cli.cli.utils.helpers.process_data_collection_helper") as helper,
        pytest.raises(HTTPException) as exc,
    ):
        _call(project_id=str(doc["_id"]), user=user)

    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert detail["rejected_count"] == 1
    assert detail["rejected_entries"] == [
        {
            "id": "s2",
            "type": "counts",
            "url": "https://internal.example/s2.csv",
            "reason": INTERNAL_HOST_REASON,
        }
    ]
    assert "counts/s2" in detail["message"]
    assert INTERNAL_HOST_REASON in detail["message"]
    helper.assert_not_called()
    stored = mock_db["projects"].find_one({"_id": doc["_id"]})
    assert stored["workflows"][0]["data_collections"][0]["config"]["scan"]["mode"] == "url"


def test_entry_gate_checks_each_host_once_and_lists_every_entry(mock_db):
    # The verdict is per host, so a large manifest costs one check per host;
    # every entry on a rejected host is still listed individually.
    user = _user()
    doc = _project_doc(user.id, tags=["counts"])
    mock_db["projects"].insert_one(doc)
    manifest = """
    [
      {"id": "s1", "type": "counts", "url": "https://internal.example/s1.csv"},
      {"id": "s2", "type": "counts", "url": "https://internal.example/s2.csv"},
      {"id": "s3", "type": "counts", "url": "https://example.org/s3.csv"}
    ]
    """

    with (
        _serve(manifest),
        patch.object(
            manifest_ingest, "validate_remote_url", side_effect=_gate_rejecting_internal
        ) as gate,
        pytest.raises(HTTPException) as exc,
    ):
        _call(project_id=str(doc["_id"]), user=user, dry_run=True)

    assert exc.value.status_code == 400
    assert [e["id"] for e in exc.value.detail["rejected_entries"]] == ["s1", "s2"]
    # manifest URL + one call per distinct entry host
    checked = [c.args[0] for c in gate.call_args_list]
    assert checked == [
        "https://example.org/manifest.json",
        "https://internal.example/s1.csv",
        "https://example.org/s3.csv",
    ]
