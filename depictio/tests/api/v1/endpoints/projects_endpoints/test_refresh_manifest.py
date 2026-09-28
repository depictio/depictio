"""Tests for POST /projects/refresh_manifest (`_refresh_manifest_in_project`).

Refresh re-fetches the manifest URLs already stored on each manifest-mode DC
and re-ingests in place — no scan-config writes, no revert bookkeeping. These
prove the contract: refreshable DCs are discovered from the stored scan configs,
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
from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest, storage_config
from depictio.api.v1.remote_fetch import RemoteURLRejected
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
    location: str | None = None,
) -> dict:
    """A minimal project whose DCs already carry a manifest, url or local scan config."""
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Regex,
        Scan,
        ScanManifest,
        ScanRecursive,
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
        elif scan_mode == "recursive":
            scan = Scan(
                mode="recursive",
                scan_parameters=ScanRecursive(regex_config=Regex(pattern=r".*\.csv")),
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
        data_location=WorkflowDataLocation(structure="flat", locations=[location or manifest_url]),
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
        # The refresh flow resolves per-project storage credentials.
        patch.object(storage_config, "project_storage_collection", database["project_storage"]),
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


def test_a_url_dc_is_refreshable_too(mock_db):
    """Re-ingestion is scan-mode agnostic, so restricting refresh to manifest
    mode was only ever a restriction on the *selection*. A url DC gets past it
    and fails later, on this fixture's missing API token, not on a 422."""
    user = _user()
    doc = _project_doc(user.id, tags=["counts"], scan_mode="url")
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user)
    assert exc.value.status_code != 422


def test_a_local_dc_the_server_cannot_see_is_not_offered(mock_db):
    """A CLI-created project points at the user's own filesystem, which the API
    container has never seen. Offering a refresh button for it would only
    produce a scan failure with an unhelpful message."""
    user = _user()
    doc = _project_doc(
        user.id, tags=["counts"], scan_mode="recursive", location="/nowhere/the-server/can-see"
    )
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user)
    assert exc.value.status_code == 422
    assert "re-read" in exc.value.detail


def test_a_local_dc_the_server_can_see_is_offered(mock_db, tmp_path):
    """The same project on a server that does have the data root mounted."""
    user = _user()
    doc = _project_doc(user.id, tags=["counts"], scan_mode="recursive", location=str(tmp_path))
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user)
    assert exc.value.status_code != 422


def _transformed_project_doc(owner_id: ObjectId, tag: str, location: str) -> dict:
    """A minimal project with one scan-less (``source: transformed``) recipe DC.

    A recipe collection has no scan block at all: its inputs are read from
    the workflow's data root at process time, not from a per-DC location,
    so this omits ``scan`` entirely rather than reusing ``_project_doc``.
    """
    from depictio.models.models.data_collections import DataCollection, DataCollectionConfig
    from depictio.models.models.data_collections_types.table import DCTableConfig
    from depictio.models.models.transforms import TransformConfig
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    data_collection = DataCollection(
        data_collection_tag=tag,
        config=DataCollectionConfig(
            type="table",
            metatype="metadata",
            source="transformed",
            transform=TransformConfig(recipe="qiime2/taxonomy_composition.py"),
            dc_specific_properties=DCTableConfig(format="csv"),
        ),
    )
    workflow = Workflow(
        name="wf",
        workflow_tag="wf",
        engine=WorkflowEngine(name="python", version="3.12"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(structure="flat", locations=[location]),
        data_collections=[data_collection],
    )
    return {
        "_id": ObjectId(),
        "name": "transformed-project",
        "permissions": {"owners": [{"_id": owner_id}]},
        "workflows": [workflow.mongo()],
    }


def test_a_scanless_transformed_dc_under_a_remote_root_is_offered(mock_db):
    """The recipe layer reads a remote data root over the network regardless
    of what this container can see on disk, so a remote root always
    qualifies, same as a `url` or `s3_prefix` scan collection."""
    user = _user()
    doc = _transformed_project_doc(user.id, tag="taxonomy_composition", location="s3://bucket/run1")
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user)
    assert exc.value.status_code != 422


def test_a_scanless_transformed_dc_under_an_invisible_local_root_is_not_offered(mock_db):
    user = _user()
    doc = _transformed_project_doc(
        user.id, tag="taxonomy_composition", location="/nowhere/the-server/can-see"
    )
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user)
    assert exc.value.status_code == 422
    assert "re-read" in exc.value.detail


def test_unknown_tag_422(mock_db):
    user = _user()
    doc = _project_doc(user.id, tags=["counts"])
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _call(project_id=str(doc["_id"]), user=user, data_collection_tag="nope")
    assert exc.value.status_code == 422
    assert "counts" in exc.value.detail  # the refreshable DCs are surfaced


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


def test_async_run_dispatches_workers(mock_db, served_manifest):
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)

    with (
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task") as task,
    ):
        report = manifest_ingest._refresh_manifest_in_project(
            project_id=str(doc["_id"]), current_user=user, async_run=True
        )

    assert report.success is True
    assert report.run_id is not None
    assert all(r.status == "dispatched" for r in report.refreshed)
    assert task.apply_async.call_count == 2
    payloads = [
        c.kwargs.get("args", c.args[0] if c.args else None)[0]
        for c in task.apply_async.call_args_list
    ]
    assert all(p["run_id"] == report.run_id and p["sync_files"] is True for p in payloads)

    run_doc = mock_db["ingestion_runs"].find_one({"run_id": report.run_id})
    assert run_doc["status"] == "running"
    assert run_doc["command"] == "refresh_manifest"
    assert {s["name"]: s["status"] for s in run_doc["steps"]} == {
        "counts": "pending",
        "annotations": "pending",
    }


def test_async_task_body_updates_steps_and_finalizes(mock_db):
    from depictio.api.v1 import celery_tasks
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)
    mock_db["ingestion_runs"].insert_one(
        {
            "run_id": "run123",
            "command": "refresh_manifest",
            "user_id": str(user.id),
            "project_id": str(doc["_id"]),
            "status": "running",
            "steps": [
                {"name": "counts", "status": "pending", "detail": None},
                {"name": "annotations", "status": "pending", "detail": None},
            ],
            "data_collections": [
                {"tag": "counts", "file_count": 2},
                {"tag": "annotations", "file_count": 1},
            ],
        }
    )

    def _payload(tag: str) -> dict:
        wf = doc["workflows"][0]
        dc = next(d for d in wf["data_collections"] if d["data_collection_tag"] == tag)
        return {
            "run_id": "run123",
            "project_id": str(doc["_id"]),
            "wf_index": 0,
            "dc_id": str(dc["_id"]),
            "dc_tag": tag,
            "sync_files": True,
            "user": {"id": str(user.id), "email": user.email, "is_admin": False},
        }

    with (
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.db.projects_collection", mock_db["projects"]),
        patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)),
    ):
        celery_tasks.manifest_refresh_dc_task(_payload("counts"))
        run_doc = mock_db["ingestion_runs"].find_one({"run_id": "run123"})
        assert run_doc["status"] == "running"  # one step still pending

    with (
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.db.projects_collection", mock_db["projects"]),
        patch.object(manifest_ingest, "_run_dc_ingest", return_value=(False, "boom")),
    ):
        celery_tasks.manifest_refresh_dc_task(_payload("annotations"))

    run_doc = mock_db["ingestion_runs"].find_one({"run_id": "run123"})
    steps = {s["name"]: s for s in run_doc["steps"]}
    assert steps["counts"]["status"] == "success"
    assert steps["annotations"]["status"] == "failed"
    assert "boom" in (steps["annotations"]["detail"] or "")
    # One green + one red worker → the run closes as partial.
    assert run_doc["status"] == "partial"
    assert "boom" in (run_doc["error"] or "")


# ── recipe dependency waits (Fix 1) ─────────────────────────────────────────


def test_unfinished_dependencies_ignores_terminal_and_unseeded_names():
    from depictio.api.v1.celery_tasks import _unfinished_dependencies

    steps = [
        {"name": "a", "status": "success"},
        {"name": "b", "status": "failed"},
        {"name": "c", "status": "skipped"},
        {"name": "d", "status": "pending"},
        {"name": "e", "status": "running"},
    ]
    # "a"/"b"/"c" are terminal; "z" has no step in this run at all: neither
    # kind is waited for.
    assert _unfinished_dependencies(steps, ["a", "b", "c", "d", "e", "z"]) == ["d", "e"]


def _dependency_run_doc(project_id: str) -> dict:
    return {
        "run_id": "run_dep",
        "command": "from_run",
        "user_id": "someone",
        "project_id": project_id,
        "status": "running",
        "steps": [
            {"name": "counts", "status": "pending", "detail": None},
            {"name": "annotations", "status": "pending", "detail": None},
        ],
        "data_collections": [
            {"tag": "counts", "file_count": 2},
            {"tag": "annotations", "file_count": 1},
        ],
    }


def _dependency_payload(doc: dict, user, run_id: str = "run_dep") -> dict:
    dc = doc["workflows"][0]["data_collections"][1]
    return {
        "run_id": run_id,
        "project_id": str(doc["_id"]),
        "wf_index": 0,
        "dc_id": str(dc["_id"]),
        "dc_tag": "annotations",
        "sync_files": True,
        "user": {"id": str(user.id), "email": user.email, "is_admin": False},
        "depends_on": ["counts"],
    }


def test_task_waits_and_reschedules_while_a_dependency_is_unfinished(mock_db):
    from celery.exceptions import Retry

    from depictio.api.v1 import celery_tasks
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)
    mock_db["ingestion_runs"].insert_one(_dependency_run_doc(str(doc["_id"])))
    payload = _dependency_payload(doc, user)

    with (
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch.object(manifest_ingest, "_run_dc_ingest") as ingest,
        pytest.raises(Retry),
    ):
        celery_tasks.manifest_refresh_dc_task(payload)

    ingest.assert_not_called()  # never marked "running", never actually ingested
    run_doc = mock_db["ingestion_runs"].find_one({"run_id": "run_dep"})
    steps = {s["name"]: s for s in run_doc["steps"]}
    assert steps["annotations"]["status"] == "pending"  # still queued, not failed
    assert "counts" in (steps["annotations"]["detail"] or "")


def test_task_gives_up_after_the_wait_budget_and_fails_the_step(mock_db):
    from depictio.api.v1 import celery_tasks
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)
    mock_db["ingestion_runs"].insert_one(_dependency_run_doc(str(doc["_id"])))
    payload = _dependency_payload(doc, user)

    celery_tasks.manifest_refresh_dc_task.push_request(retries=celery_tasks._DEPENDENCY_MAX_WAITS)
    try:
        with (
            patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
            patch.object(manifest_ingest, "_run_dc_ingest") as ingest,
        ):
            result = celery_tasks.manifest_refresh_dc_task(payload)
    finally:
        celery_tasks.manifest_refresh_dc_task.pop_request()

    ingest.assert_not_called()
    assert result["ok"] is False
    assert "Gave up waiting for counts" in result["message"]
    run_doc = mock_db["ingestion_runs"].find_one({"run_id": "run_dep"})
    steps = {s["name"]: s for s in run_doc["steps"]}
    assert steps["annotations"]["status"] == "failed"
    assert "Gave up waiting for counts" in (steps["annotations"]["detail"] or "")
    # "counts" itself never finished, so the run cannot close yet.
    assert run_doc["status"] == "running"


def test_task_proceeds_immediately_once_its_dependency_is_terminal(mock_db):
    from depictio.api.v1 import celery_tasks
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)
    run_doc = _dependency_run_doc(str(doc["_id"]))
    run_doc["steps"][0]["status"] = "success"  # counts already finished
    mock_db["ingestion_runs"].insert_one(run_doc)
    payload = _dependency_payload(doc, user)

    with (
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.db.projects_collection", mock_db["projects"]),
        patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest,
    ):
        result = celery_tasks.manifest_refresh_dc_task(payload)

    ingest.assert_called_once()
    assert result["ok"] is True
    stored = mock_db["ingestion_runs"].find_one({"run_id": "run_dep"})
    steps = {s["name"]: s for s in stored["steps"]}
    assert steps["annotations"]["status"] == "success"
    assert stored["status"] == "success"


# ── optional-missing collections close the run clean (Fix 3) ───────────────


def test_finalizer_closes_a_run_with_only_skipped_non_success_steps_as_success(mock_db):
    """An optional collection seeded "skipped" is a nominal absence, not a
    failure: a run whose only non-success steps are skipped must still close
    "success", never "partial"."""
    from depictio.api.v1.celery_tasks import _finalize_manifest_refresh_run
    from depictio.api.v1.monitoring import store as monitoring_store

    mock_db["ingestion_runs"].insert_one(
        {
            "run_id": "run_skip_only",
            "command": "from_run",
            "user_id": "someone",
            "project_id": str(ObjectId()),
            "status": "running",
            "steps": [
                {"name": "counts", "status": "success", "detail": None},
                {
                    "name": "seed_only_canonical",
                    "status": "skipped",
                    "detail": "Skipped optional collection: not present under the data root.",
                },
            ],
            "data_collections": [],
        }
    )

    with patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]):
        _finalize_manifest_refresh_run("run_skip_only")

    run_doc = mock_db["ingestion_runs"].find_one({"run_id": "run_skip_only"})
    assert run_doc["status"] == "success"


def test_poll_endpoint_maps_run_to_report(mock_db):
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user()
    doc = _project_doc(user.id, tags=["counts"])
    mock_db["projects"].insert_one(doc)
    mock_db["ingestion_runs"].insert_one(
        {
            "run_id": "run456",
            "command": "refresh_manifest",
            "user_id": str(user.id),
            "project_id": str(doc["_id"]),
            "status": "success",
            "steps": [{"name": "counts", "status": "success", "detail": None}],
            "data_collections": [{"tag": "counts", "file_count": 2}],
        }
    )

    with patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]):
        report = manifest_ingest._get_refresh_run_report("run456", user)
        assert report.success is True
        assert report.run_id == "run456"
        assert report.refreshed[0].status == "ingested"
        assert report.refreshed[0].entries == 2
        # dc id rebuilt from the live project document
        expected_dc_id = str(doc["workflows"][0]["data_collections"][0]["_id"])
        assert report.refreshed[0].data_collection_id == expected_dc_id

        # Another (non-admin) user must not see the run.
        with pytest.raises(HTTPException) as exc:
            manifest_ingest._get_refresh_run_report("run456", _user())
        assert exc.value.status_code == 403

        with pytest.raises(HTTPException) as exc:
            manifest_ingest._get_refresh_run_report("nope", user)
        assert exc.value.status_code == 404


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


# One entry on a host the gateway rejects (the other host passes).
MANIFEST_WITH_INTERNAL_ENTRY = """
[
  {"id": "s1", "type": "counts", "url": "https://example.org/s1.csv"},
  {"id": "a1", "type": "annotations", "url": "https://internal.example/a1.csv"}
]
"""


def _serve(content: str):
    def _download(url, dest_path, max_bytes=None, timeout_s=30.0):
        with open(dest_path, "w") as fh:
            fh.write(content)
        return len(content)

    return patch.object(manifest_ingest, "bounded_download", side_effect=_download)


def test_rejected_entry_url_fails_every_dc_on_that_manifest(mock_db):
    # Entry URLs are gateway-checked at fetch time: a rejected entry fails the
    # manifest before any scan could register it, for every DC it backs.
    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)

    def _gate(url):
        if "internal.example" in url:
            raise RemoteURLRejected(
                "Host 'internal.example' is not in the administrator allowlist."
            )

    with (
        _serve(MANIFEST_WITH_INTERNAL_ENTRY),
        patch.object(manifest_ingest, "validate_remote_url", side_effect=_gate),
        patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest,
    ):
        report = _call(project_id=str(doc["_id"]), user=user)

    assert report.success is False
    assert [r.status for r in report.refreshed] == ["failed", "failed"]
    assert all("annotations/a1" in (r.message or "") for r in report.refreshed)
    ingest.assert_not_called()


def test_async_run_seeds_preflight_failures_into_run(mock_db):
    # A DC skipped before dispatch (its type vanished from the manifest) must
    # be visible to a caller that only polls the run, and must keep the run
    # from closing as "success".
    from depictio.api.v1.celery_tasks import _finalize_manifest_refresh_run
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user()
    doc = _project_doc(user.id, tags=["counts", "annotations"])
    mock_db["projects"].insert_one(doc)

    with (
        _serve(MANIFEST_COUNTS_ONLY),
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task") as task,
    ):
        report = manifest_ingest._refresh_manifest_in_project(
            project_id=str(doc["_id"]), current_user=user, async_run=True
        )
        assert report.success is False
        assert report.run_id is not None
        by_tag = {r.data_collection_tag: r for r in report.refreshed}
        assert by_tag["counts"].status == "dispatched"
        assert by_tag["annotations"].status == "failed"
        assert task.apply_async.call_count == 1  # the skipped DC never reaches a worker

        run_doc = mock_db["ingestion_runs"].find_one({"run_id": report.run_id})
        assert run_doc["status"] == "running"  # counts is still pending
        steps = {s["name"]: s for s in run_doc["steps"]}
        assert steps["counts"]["status"] == "pending"
        assert steps["annotations"]["status"] == "failed"
        assert "annotations" in (steps["annotations"]["detail"] or "")
        assert {d["tag"]: d["file_count"] for d in run_doc["data_collections"]} == {
            "counts": 1,
            "annotations": 0,
        }

        polled = manifest_ingest._get_refresh_run_report(report.run_id, user)
        assert polled.success is False
        polled_by_tag = {r.data_collection_tag: r for r in polled.refreshed}
        assert polled_by_tag["counts"].status == "dispatched"
        assert polled_by_tag["annotations"].status == "failed"
        assert polled_by_tag["annotations"].entries == 0
        assert "annotations" in (polled_by_tag["annotations"].message or "")

        # The worker finishes the dispatched DC: one green + one pre-flight
        # red closes the run as partial, never success.
        monitoring_store.set_ingestion_step(
            report.run_id,
            step={"name": "counts", "status": "success", "detail": None},
            current_step=None,
        )
        _finalize_manifest_refresh_run(report.run_id)
        run_doc = mock_db["ingestion_runs"].find_one({"run_id": report.run_id})
        assert run_doc["status"] == "partial"
        assert manifest_ingest._get_refresh_run_report(report.run_id, user).success is False


def test_async_run_all_preflight_failures_still_returns_run_id(mock_db):
    from depictio.api.v1.monitoring import store as monitoring_store

    user = _user()
    doc = _project_doc(user.id, tags=["counts"], manifest_url="https://127.0.0.1/manifest.json")
    mock_db["projects"].insert_one(doc)

    with (
        patch.object(monitoring_store, "ingestion_runs_collection", mock_db["ingestion_runs"]),
        patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task") as task,
    ):
        report = manifest_ingest._refresh_manifest_in_project(
            project_id=str(doc["_id"]), current_user=user, async_run=True
        )
        task.apply_async.assert_not_called()
        assert report.success is False
        assert report.run_id is not None
        assert [r.status for r in report.refreshed] == ["failed"]

        # Nothing was dispatched, so the run is closed right away as failed
        # and the poll endpoint reports the same failure.
        run_doc = mock_db["ingestion_runs"].find_one({"run_id": report.run_id})
        assert run_doc["status"] == "failed"
        assert "Could not fetch manifest" in (run_doc["error"] or "")
        polled = manifest_ingest._get_refresh_run_report(report.run_id, user)
        assert polled.success is False
        assert [r.status for r in polled.refreshed] == ["failed"]
        assert "Could not fetch manifest" in (polled.refreshed[0].message or "")
