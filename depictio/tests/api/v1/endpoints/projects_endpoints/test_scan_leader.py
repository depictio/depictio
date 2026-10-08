"""Recursive data collections of one workflow are scanned once, by a scan leader.

Every recursive collection of a workflow shares its runs: one walk registers a
``WorkflowRun`` per run folder for all of them. Fanned out one task per
collection, each scanning for itself, the tasks would race to create the same
runs. So ``_dispatch_refresh_tasks`` makes the first one the leader (it scans
for all of them), the others wait for its step (``depends_on``) and only
process, and a failed leader fails them with a message that says why.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest
from depictio.models.models.users import UserBase


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")


def _user() -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=True)


def _workflow(tag: str, dcs: list[tuple[str, str]], location: str = "/data/run42"):
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Regex,
        Scan,
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

    collections = []
    for dc_tag, mode in dcs:
        if mode == "recursive":
            scan = Scan(
                mode="recursive",
                scan_parameters=ScanRecursive(regex_config=Regex(pattern=rf"{dc_tag}\.csv")),
            )
        else:
            scan = Scan(
                mode="url", scan_parameters=ScanURL(url=f"https://example.org/{dc_tag}.csv")
            )
        collections.append(
            DataCollection(
                data_collection_tag=dc_tag,
                config=DataCollectionConfig(
                    type="table",
                    metatype="metadata",
                    scan=scan,
                    dc_specific_properties=DCTableConfig(format="csv"),
                ),
            )
        )
    return Workflow(
        name=tag,
        workflow_tag=tag,
        engine=WorkflowEngine(name="nextflow", version="25.10"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(structure="flat", locations=[location]),
        data_collections=collections,
    ).mongo()


def _project() -> dict:
    return {
        "_id": ObjectId(),
        "name": "run42",
        "permissions": {"owners": [{"_id": ObjectId()}]},
        "workflows": [
            _workflow("wf0", [("a", "recursive"), ("b", "recursive"), ("c", "url")]),
            _workflow("wf1", [("d", "recursive")]),
        ],
    }


def _ids(project: dict) -> dict[str, tuple[str, int]]:
    return {
        dc["data_collection_tag"]: (str(dc["_id"]), wf_i)
        for wf_i, wf in enumerate(project["workflows"])
        for dc in wf["data_collections"]
    }


def _to_dispatch(project: dict, order: list[str]) -> list[tuple[str, str, int, int]]:
    ids = _ids(project)
    return [(tag, ids[tag][0], ids[tag][1], 0) for tag in order]


# ── who leads ────────────────────────────────────────────────────────────────


def test_the_first_recursive_dc_of_each_workflow_leads():
    project = _project()
    ids = _ids(project)
    leaders, followers = manifest_ingest._scan_leaders(
        project, _to_dispatch(project, ["c", "b", "a", "d"])
    )
    # Dispatch order decides: "b" comes first in wf0.
    assert leaders == {"b": [ids["b"][0], ids["a"][0]], "d": [ids["d"][0]]}
    assert followers == {"a": "b"}


def test_a_collection_left_out_of_the_run_is_not_scanned_for():
    project = _project()
    ids = _ids(project)
    leaders, followers = manifest_ingest._scan_leaders(project, _to_dispatch(project, ["a"]))
    assert leaders == {"a": [ids["a"][0]]}
    assert followers == {}


@pytest.fixture()
def run_store():
    from depictio.api.v1.monitoring import store as monitoring_store

    database = mongomock.MongoClient()["depictio_test"]
    with patch.object(monitoring_store, "ingestion_runs_collection", database["ingestion_runs"]):
        yield database


def test_followers_wait_for_the_leader_and_the_leader_carries_the_scan(run_store):
    project = _project()
    ids = _ids(project)
    with patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task") as task:
        _run_id, ok, _results = manifest_ingest._dispatch_refresh_tasks(
            project_dict=project,
            to_dispatch=_to_dispatch(project, ["a", "b", "c", "d"]),
            current_user=_user(),
            preflight_failed=[],
            command="from_run",
        )
    assert ok is True
    payloads = {
        (call.kwargs.get("args") or call.args[0])[0]["dc_tag"]: (
            call.kwargs.get("args") or call.args[0]
        )[0]
        for call in task.apply_async.call_args_list
    }
    assert payloads["a"]["scan_dc_ids"] == [ids["a"][0], ids["b"][0]]
    assert "scan_leader" not in payloads["a"] and "depends_on" not in payloads["a"]
    assert payloads["b"]["scan_leader"] == "a"
    assert payloads["b"]["depends_on"] == ["a"]
    assert "scan_dc_ids" not in payloads["b"]
    for key in ("scan_dc_ids", "scan_leader", "depends_on"):
        assert key not in payloads["c"]
    assert payloads["d"]["scan_dc_ids"] == [ids["d"][0]]


# ── what the worker does with it ─────────────────────────────────────────────


def _run_doc(project: dict, leader_status: str) -> dict:
    return {
        "run_id": "run_scan",
        "command": "from_run",
        "user_id": "someone",
        "project_id": str(project["_id"]),
        "status": "running",
        "steps": [
            {"name": "a", "status": leader_status, "detail": None},
            {"name": "b", "status": "pending", "detail": None},
        ],
        "data_collections": [{"tag": "a", "file_count": 0}, {"tag": "b", "file_count": 0}],
    }


def _payload(project: dict, tag: str, **extra) -> dict:
    ids = _ids(project)
    return {
        "run_id": "run_scan",
        "project_id": str(project["_id"]),
        "wf_index": ids[tag][1],
        "dc_id": ids[tag][0],
        "dc_tag": tag,
        "sync_files": True,
        "user": {"id": str(ObjectId()), "email": "owner@example.com", "is_admin": True},
        **extra,
    }


@pytest.fixture()
def worker_db(run_store):
    projects = mongomock.MongoClient()["depictio_test"]["projects"]
    with (
        patch("depictio.api.v1.db.projects_collection", projects),
        patch(
            "depictio.api.v1.endpoints.projects_endpoints.storage_config.project_storage_for",
            return_value=None,
        ),
    ):
        yield run_store, projects


def test_a_follower_of_a_failed_leader_fails_without_ingesting(worker_db):
    from depictio.api.v1 import celery_tasks

    runs, projects = worker_db
    project = _project()
    projects.insert_one(project)
    runs["ingestion_runs"].insert_one(_run_doc(project, "failed"))

    with patch.object(manifest_ingest, "_run_dc_ingest") as ingest:
        result = celery_tasks.manifest_refresh_dc_task(
            _payload(project, "b", scan_leader="a", depends_on=["a"])
        )

    ingest.assert_not_called()
    assert result["ok"] is False
    steps = {s["name"]: s for s in runs["ingestion_runs"].find_one({})["steps"]}
    assert steps["b"]["status"] == "failed"
    assert "'a'" in steps["b"]["detail"]


def test_a_follower_of_a_finished_leader_only_processes(worker_db):
    from depictio.api.v1 import celery_tasks

    runs, projects = worker_db
    project = _project()
    projects.insert_one(project)
    runs["ingestion_runs"].insert_one(_run_doc(project, "success"))

    with patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest:
        result = celery_tasks.manifest_refresh_dc_task(
            _payload(project, "b", scan_leader="a", depends_on=["a"])
        )

    assert result["ok"] is True
    assert ingest.call_args.kwargs["scan"] is False
    assert "scan_dc_ids" not in ingest.call_args.kwargs


def test_the_leader_scans_for_its_followers(worker_db):
    from depictio.api.v1 import celery_tasks

    runs, projects = worker_db
    project = _project()
    ids = _ids(project)
    projects.insert_one(project)
    runs["ingestion_runs"].insert_one(_run_doc(project, "pending"))

    scan_ids = [ids["a"][0], ids["b"][0]]
    with patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest:
        celery_tasks.manifest_refresh_dc_task(_payload(project, "a", scan_dc_ids=scan_ids))

    assert ingest.call_args.kwargs["scan_dc_ids"] == scan_ids
    assert "scan" not in ingest.call_args.kwargs


def test_a_task_without_scan_keys_calls_ingest_as_before(worker_db):
    from depictio.api.v1 import celery_tasks

    runs, projects = worker_db
    project = _project()
    projects.insert_one(project)
    runs["ingestion_runs"].insert_one(_run_doc(project, "pending"))

    with patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest:
        celery_tasks.manifest_refresh_dc_task(_payload(project, "a"))

    assert set(ingest.call_args.kwargs) == {"sync_files", "remote_storage_options"}


# ── the scan itself ──────────────────────────────────────────────────────────


def _ingest(project: dict, tag: str, **kwargs):
    ids = _ids(project)
    with (
        patch.object(dc_utils, "_build_cli_config_for_user", return_value=object()),
        patch(
            "depictio.cli.cli.utils.scan.scan_files_for_workflow",
            return_value={"result": "success"},
        ) as walk,
        patch(
            "depictio.cli.cli.utils.helpers.process_data_collection_helper",
            return_value={"result": "success"},
        ) as helper,
    ):
        ok, message = manifest_ingest._run_dc_ingest(
            project["workflows"][ids[tag][1]], ids[tag][0], _user(), sync_files=True, **kwargs
        )
    return ok, message, walk, helper


def test_the_leader_walks_once_for_every_collection_it_scans_for():
    project = _project()
    ids = _ids(project)
    ok, message, walk, helper = _ingest(project, "a", scan_dc_ids=[ids["a"][0], ids["b"][0]])

    assert (ok, message) == (True, None)
    walk.assert_called_once()
    scanned = sorted(dc.data_collection_tag for dc in walk.call_args.kwargs["data_collections"])
    assert scanned == ["a", "b"]
    assert walk.call_args.kwargs["command_parameters"]["sync_files"] is True
    # No per-collection scan, which speaks no recursive mode: just the process.
    assert [c.kwargs["mode"] for c in helper.call_args_list] == ["process"]


def test_a_follower_does_not_walk():
    project = _project()
    ok, _message, walk, helper = _ingest(project, "b", scan=False)
    assert ok is True
    walk.assert_not_called()
    assert [c.kwargs["mode"] for c in helper.call_args_list] == ["process"]


def test_a_lone_recursive_collection_scans_for_itself():
    project = _project()
    _ok, _message, walk, _helper = _ingest(project, "d")
    assert [dc.data_collection_tag for dc in walk.call_args.kwargs["data_collections"]] == ["d"]


def test_a_failed_walk_fails_the_collection():
    project = _project()
    ids = _ids(project)
    with (
        patch.object(dc_utils, "_build_cli_config_for_user", return_value=object()),
        patch(
            "depictio.cli.cli.utils.scan.scan_files_for_workflow",
            return_value={"result": "error", "message": "No locations configured"},
        ),
        patch("depictio.cli.cli.utils.helpers.process_data_collection_helper") as helper,
    ):
        ok, message = manifest_ingest._run_dc_ingest(project["workflows"][0], ids["a"][0], _user())
    assert ok is False
    assert "No locations configured" in message
    helper.assert_not_called()
