"""Tests for POST /projects/refresh_manifest (`_refresh_manifest_in_project`).

Refresh re-fetches the manifest URLs already stored on each manifest-mode DC
and re-ingests in place — no scan-config writes, no revert bookkeeping. These
prove the contract: manifest DCs are discovered from the stored scan configs,
``sync_files`` is threaded into the re-ingest, a manifest that dropped a DC's
type marks it failed without running the scan, and per-DC fetch failures don't
block DCs backed by a different manifest.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest
from depictio.models.models.users import UserBase

MANIFEST_JSON = """
[
  {"id": "s1", "type": "counts", "url": "https://example.org/s1.csv"},
  {"id": "s2", "type": "counts", "url": "https://example.org/s2.csv", "run": "batch1"},
  {"id": "s1", "type": "annotations", "url": "https://example.org/a1.csv"}
]
"""

MANIFEST_COUNTS_ONLY = """
[
  {"id": "s1", "type": "counts", "url": "https://example.org/s1.csv"}
]
"""


def _user(is_admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


def _call(
    project_id: str = str(ObjectId()),
    user=None,
    data_collection_tag: str | None = None,
    dry_run: bool = False,
):
    return manifest_ingest._refresh_manifest_in_project(
        project_id=project_id,
        current_user=user or _user(),
        data_collection_tag=data_collection_tag,
        dry_run=dry_run,
    )


def _project_doc(
    owner_id: ObjectId,
    tags: list[str],
    manifest_url: str = "https://example.org/manifest.json",
    scan_mode: str = "manifest",
) -> dict:
    """A minimal project whose DCs already carry a manifest (or url) scan config."""
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanManifest,
        ScanURL,
    )
    from depictio.models.models.data_collections_types.table import DCTableConfig
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    data_collections = []
    for tag in tags:
        if scan_mode == "manifest":
            scan = Scan(
                mode="manifest",
                scan_parameters=ScanManifest(manifest_url=manifest_url, manifest_type=tag),
            )
        else:
            scan = Scan(mode="url", scan_parameters=ScanURL(url=f"https://example.org/{tag}.csv"))
        data_collections.append(
            DataCollection(
                data_collection_tag=tag,
                config=DataCollectionConfig(
                    type="table",
                    metatype="metadata",
                    scan=scan,
                    dc_specific_properties=DCTableConfig(format="csv"),
                ),
            )
        )
    workflow = Workflow(
        name="wf",
        workflow_tag="wf",
        engine=WorkflowEngine(name="python", version="3.12"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(structure="flat", locations=[manifest_url]),
        data_collections=data_collections,
    )
    return {
        "_id": ObjectId(),
        "name": "manifest-project",
        "permissions": {"owners": [{"_id": owner_id}]},
        "workflows": [workflow.mongo()],
    }


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
    ):
        yield database


@pytest.fixture()
def served_manifest():
    def _fake_download(url, dest_path, max_bytes=None, timeout_s=30.0):
        with open(dest_path, "w") as fh:
            fh.write(MANIFEST_JSON)
        return len(MANIFEST_JSON)

    with patch.object(manifest_ingest, "bounded_download", side_effect=_fake_download):
        yield


def test_invalid_project_id_400():
    with pytest.raises(HTTPException) as exc:
        _call(project_id="not-an-oid")
    assert exc.value.status_code == 400


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


def test_no_manifest_dcs_422(mock_db):
    user = _user()
    doc = _project_doc(user.id, tags=["counts"], scan_mode="url")
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user)
    assert exc.value.status_code == 422
    assert "no manifest-backed" in exc.value.detail


def test_unknown_tag_422(mock_db):
    user = _user()
    doc = _project_doc(user.id, tags=["counts"])
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user, data_collection_tag="nope")
    assert exc.value.status_code == 422
    assert "counts" in exc.value.detail  # available manifest DCs are surfaced


def test_dry_run_reports_planned_counts(mock_db, served_manifest):
    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)

    report = _call(project_id=str(doc["_id"]), user=user, dry_run=True)

    assert report.success is True
    assert report.dry_run is True
    by_tag = {r.data_collection_tag: r for r in report.refreshed}
    assert set(by_tag) == {"counts", "annotations"}
    assert all(r.status == "planned" for r in report.refreshed)
    assert by_tag["counts"].entries == 2
    assert by_tag["annotations"].entries == 1


def test_refresh_reingests_with_sync_files(mock_db, served_manifest):
    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)

    with patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest:
        report = _call(project_id=str(doc["_id"]), user=user)

    assert report.success is True
    assert all(r.status == "ingested" for r in report.refreshed)
    assert ingest.call_count == 2
    # sync_files must be forced: the scan's sha256(url|id) identity hash would
    # otherwise skip File updates for unchanged URLs with changed content.
    assert all(c.kwargs.get("sync_files") is True for c in ingest.call_args_list)
    # Refresh never rewrites the project document.
    stored = mock_db["projects"].find_one({"_id": doc["_id"]})
    assert stored["workflows"] == doc["workflows"]


def test_tag_filter_refreshes_only_that_dc(mock_db, served_manifest):
    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)

    with patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest:
        report = _call(project_id=str(doc["_id"]), user=user, data_collection_tag="counts")

    assert report.success is True
    assert [r.data_collection_tag for r in report.refreshed] == ["counts"]
    assert ingest.call_count == 1


def test_dropped_type_marks_failed_without_ingest(mock_db):
    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)

    def _counts_only(url, dest_path, max_bytes=None, timeout_s=30.0):
        with open(dest_path, "w") as fh:
            fh.write(MANIFEST_COUNTS_ONLY)
        return len(MANIFEST_COUNTS_ONLY)

    with (
        patch.object(manifest_ingest, "bounded_download", side_effect=_counts_only),
        patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest,
    ):
        report = _call(project_id=str(doc["_id"]), user=user)

    assert report.success is False
    by_tag = {r.data_collection_tag: r for r in report.refreshed}
    assert by_tag["counts"].status == "ingested"
    assert by_tag["annotations"].status == "failed"
    assert "annotations" in (by_tag["annotations"].message or "")
    # The emptied DC was never re-scanned — its data is left untouched.
    assert ingest.call_count == 1


def test_unfetchable_manifest_fails_per_dc(mock_db):
    # A stored URL the gateway rejects (e.g. a local path from a CLI ingest)
    # is a per-DC failure, not a 4xx — other DCs could still refresh.
    user = _user()
    doc = _project_doc(user.id, tags=["counts"], manifest_url="https://127.0.0.1/manifest.json")
    mock_db["projects"].insert_one(doc)

    with patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest:
        report = _call(project_id=str(doc["_id"]), user=user)

    assert report.success is False
    assert report.refreshed[0].status == "failed"
    assert "Could not fetch manifest" in (report.refreshed[0].message or "")
    ingest.assert_not_called()


def test_run_dc_ingest_threads_sync_files(mock_db):
    # Unit check on the seam itself: sync_files=True must reach the scan call.
    user = _user()
    doc = _project_doc(user.id, tags=["counts"])

    with (
        patch.object(dc_utils, "_build_cli_config_for_user", return_value=object()),
        patch(
            "depictio.cli.cli.utils.helpers.process_data_collection_helper",
            return_value={"result": "success"},
        ) as helper,
    ):
        dc_id = str(doc["workflows"][0]["data_collections"][0]["_id"])
        ok, message = manifest_ingest._run_dc_ingest(
            doc["workflows"][0], dc_id, user, sync_files=True
        )

    assert ok is True and message is None
    scan_call = next(c for c in helper.call_args_list if c.kwargs.get("mode") == "scan")
    assert scan_call.kwargs.get("command_parameters") == {"sync_files": True}
