"""Every scan that writes a workflow's runs has one leader, and followers gate on their scan.

Two scans write ``WorkflowRun`` documents: the recursive walk, and an
``s3_prefix`` scan of a ``sequencing-runs`` workflow (what a recursive
collection becomes under an ``s3://`` data root), one run per run directory.
Fanned out one task per collection, the ``s3_prefix`` ones raced to register
the same runs. They now get the scan leader the recursive ones have: it scans
for all of them, one after the other, and the others wait for it and only
process.

A leader records each scan outcome apart from its processing outcome, and a
follower is failed by its own scan only: a leader whose processing failed
leaves followers whose runs were scanned fine to be processed.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import install_s3_listing

RUN_PREFIX = "s3://b/data/"
RUN_KEYS = [
    "data/run_1/a.csv",
    "data/run_1/b.csv",
    "data/run_2/a.csv",
    "data/run_2/b.csv",
    "data/run_3/b.csv",  # a run only the second collection sees
]
OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.com"}


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    # Bucket "b" is public, so a listing needs no project storage.
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "b")


def _user() -> UserBase:
    return UserBase(id=ObjectId(OWNER["id"]), email=OWNER["email"], is_admin=True)


def _workflow(tag: str, dcs: list[tuple[str, str]], structure: str = "sequencing-runs") -> dict:
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanS3Prefix,
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
        if mode == "s3_prefix":
            scan = Scan(
                mode="s3_prefix",
                scan_parameters=ScanS3Prefix(prefix=RUN_PREFIX, pattern=f"{dc_tag}.csv"),
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
                    metatype="aggregate",
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
        data_location=WorkflowDataLocation(
            structure=structure,
            locations=[RUN_PREFIX],
            runs_regex="run_.*" if structure == "sequencing-runs" else None,
        ),
        data_collections=collections,
    ).mongo()


def _project() -> dict:
    return {
        "_id": ObjectId(),
        "name": "remote-runs",
        "permissions": {"owners": [{"_id": ObjectId(OWNER["id"])}]},
        "workflows": [
            _workflow("wf0", [("a", "s3_prefix"), ("b", "s3_prefix"), ("c", "url")]),
            _workflow("wf1", [("d", "s3_prefix"), ("e", "s3_prefix")], structure="flat"),
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


def test_the_s3_prefix_collections_of_a_run_structure_share_one_leader():
    project = _project()
    ids = _ids(project)
    leaders, followers = manifest_ingest._scan_leaders(
        project, _to_dispatch(project, ["c", "b", "a", "d", "e"])
    )
    # A flat workflow's s3_prefix scans register no run: nothing to lead.
    assert leaders == {"b": [ids["b"][0], ids["a"][0]]}
    assert followers == {"a": "b"}


def test_the_followers_wait_for_the_leader(monkeypatch):
    from depictio.api.v1.monitoring import store as monitoring_store

    monkeypatch.setattr(
        monitoring_store,
        "ingestion_runs_collection",
        mongomock.MongoClient()["depictio_test"]["ingestion_runs"],
    )
    project = _project()
    ids = _ids(project)
    with patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task") as task:
        manifest_ingest._dispatch_refresh_tasks(
            project_dict=project,
            to_dispatch=_to_dispatch(project, ["a", "b", "c", "d"]),
            current_user=_user(),
            preflight_failed=[],
            command="from_run",
        )
    payloads = {
        (call.kwargs.get("args") or call.args[0])[0]["dc_tag"]: (
            call.kwargs.get("args") or call.args[0]
        )[0]
        for call in task.apply_async.call_args_list
    }
    assert payloads["a"]["scan_dc_ids"] == [ids["a"][0], ids["b"][0]]
    assert (payloads["b"]["scan_leader"], payloads["b"]["depends_on"]) == ("a", ["a"])
    for tag in ("c", "d"):
        assert not {"scan_dc_ids", "scan_leader", "depends_on"} & set(payloads[tag])


# ── the leader's scans ───────────────────────────────────────────────────────


@pytest.fixture
def registry(monkeypatch):
    """The runs and files API the scans call, in memory, upserting the way the
    server's ``/runs/upsert_batch`` does: a known run_tag is updated by id (or
    left alone), an unknown one inserted."""
    from depictio.cli.cli.utils import scan as scan_module

    install_s3_listing(monkeypatch, dict.fromkeys(RUN_KEYS, b"x" * 10), page_size=2)
    state = SimpleNamespace(runs={}, files={})

    def _response(payload):
        response = MagicMock(status_code=200)
        response.json.return_value = payload
        return response

    def _upsert_runs(runs, CLI_config, update):
        known = {run["run_tag"] for run in state.runs.values()}
        for run in runs:
            if run.run_tag not in known:
                state.runs[str(run.id)] = {"_id": str(run.id), "run_tag": run.run_tag}

    def _create_files(files, CLI_config, update):
        for file in files:
            state.files[str(file.id)] = {
                "_id": str(file.id),
                "data_collection_id": str(file.data_collection_id),
                "file_location": file.file_location,
                "file_hash": file.file_hash,
                "run_id": str(file.run_id),
                "run_tag": file.run_tag,
            }

    monkeypatch.setattr(
        scan_module,
        "api_get_runs_by_wf_id",
        lambda wf_id, CLI_config: _response(list(state.runs.values())),
    )
    monkeypatch.setattr(
        scan_module,
        "api_get_files_by_dc_id",
        lambda dc_id, CLI_config: _response(
            [f for f in state.files.values() if f["data_collection_id"] == dc_id]
        ),
    )
    monkeypatch.setattr(scan_module, "api_upsert_runs_batch", _upsert_runs)
    monkeypatch.setattr(scan_module, "api_create_files", _create_files)
    monkeypatch.setattr(
        scan_module, "api_delete_file", lambda file_id, CLI_config: state.files.pop(file_id)
    )
    return state


def _cli_config():
    cli_config = MagicMock()
    # A fresh dict per call: each scan pops its "token".
    cli_config.user.model_dump.side_effect = lambda: {**OWNER, "token": None}
    return cli_config


def _lead(project: dict, tag: str, *, scan_side_effect=None, **kwargs):
    """``_run_dc_ingest`` for real down to the scans; processing answers success."""
    from depictio.cli.cli.utils import helpers
    from depictio.cli.cli.utils import scan as scan_module

    ids = _ids(project)
    calls: list[tuple[str, str]] = []

    def _helper(**call_kwargs):
        calls.append((call_kwargs["mode"], call_kwargs["dc_id"]))
        if call_kwargs["mode"] == "process":
            return {"result": "success"}
        if scan_side_effect is not None:
            scan_side_effect(call_kwargs["dc_id"])
        # What the helper's scan mode runs, minus its CLIConfig validation.
        return scan_module.scan_files_for_data_collection(
            workflow=call_kwargs["wf"],
            data_collection_id=call_kwargs["dc_id"],
            CLI_config=call_kwargs["CLI_config"],
            command_parameters=call_kwargs["command_parameters"],
        )

    outcomes: dict[str, str | None] = {}
    with (
        patch.object(dc_utils, "_build_cli_config_for_user", return_value=_cli_config()),
        patch.object(helpers, "process_data_collection_helper", side_effect=_helper),
        patch("depictio.cli.cli.utils.scan.scan_files_for_workflow") as walk,
    ):
        result = manifest_ingest._run_dc_ingest(
            project["workflows"][ids[tag][1]],
            ids[tag][0],
            _user(),
            sync_files=True,
            on_scanned=lambda dc_id, error: outcomes.__setitem__(dc_id, error),
            **kwargs,
        )
    walk.assert_not_called()
    return result, outcomes, calls


def test_the_leader_registers_each_run_once_for_all_its_followers(registry):
    project = _project()
    ids = _ids(project)
    a, b = ids["a"][0], ids["b"][0]

    result, outcomes, calls = _lead(project, "a", scan_dc_ids=[a, b])

    assert result == (True, None)
    # One task, one scan after the other, then its own processing only.
    assert calls == [("scan", a), ("scan", b), ("process", a)]
    assert outcomes == {a: None, b: None}
    # One document per run, and the files of both collections name it.
    run_ids = {run["run_tag"]: run["_id"] for run in registry.runs.values()}
    assert sorted(run_ids) == ["run_1", "run_2", "run_3"]
    assert len(registry.runs) == 3
    files = list(registry.files.values())
    assert {f["data_collection_id"] for f in files} == {a, b}
    assert all(f["run_id"] == run_ids[f["run_tag"]] for f in files)


def test_a_follower_whose_scan_fails_does_not_fail_the_leader(registry):
    project = _project()
    ids = _ids(project)
    a, b = ids["a"][0], ids["b"][0]
    # The follower's pattern now matches nothing: an empty collection.
    project["workflows"][0]["data_collections"][1]["config"]["scan"]["scan_parameters"][
        "pattern"
    ] = "nothing.csv"

    result, outcomes, calls = _lead(project, "a", scan_dc_ids=[a, b])

    assert result == (True, None)
    assert outcomes[a] is None
    assert outcomes[b].startswith("Scan failed: No object under")
    assert calls[-1] == ("process", a)


def test_a_follower_whose_scan_raises_is_failed_alone(registry):
    project = _project()
    ids = _ids(project)
    a, b = ids["a"][0], ids["b"][0]

    def _refuse(dc_id):
        if dc_id == b:
            raise RuntimeError("listing refused")

    result, outcomes, _calls = _lead(project, "a", scan_dc_ids=[a, b], scan_side_effect=_refuse)

    assert result == (True, None)
    assert outcomes == {a: None, b: "Scan failed: listing refused"}


def test_the_leaders_own_scan_raising_still_scans_its_followers(registry):
    project = _project()
    ids = _ids(project)
    a, b = ids["a"][0], ids["b"][0]

    def _refuse(dc_id):
        if dc_id == a:
            raise RuntimeError("listing refused")

    with pytest.raises(RuntimeError, match="listing refused"):
        _lead(project, "a", scan_dc_ids=[a, b], scan_side_effect=_refuse)
    # Its follower's runs were registered all the same.
    assert sorted(run["run_tag"] for run in registry.runs.values()) == ["run_1", "run_2", "run_3"]


def test_an_s3_prefix_follower_does_not_scan(registry):
    project = _project()
    ids = _ids(project)

    result, outcomes, calls = _lead(project, "b", scan=False)

    assert result == (True, None)
    assert calls == [("process", ids["b"][0])]
    assert outcomes == {}
    assert registry.runs == {}


# ── what the worker does with the outcomes ───────────────────────────────────


@pytest.fixture()
def worker_db():
    from depictio.api.v1.monitoring import store as monitoring_store

    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(monitoring_store, "ingestion_runs_collection", database["ingestion_runs"]),
        patch("depictio.api.v1.db.projects_collection", database["projects"]),
        patch(
            "depictio.api.v1.endpoints.projects_endpoints.storage_config.project_storage_for",
            return_value=None,
        ),
    ):
        yield database


def _run_doc(project: dict, leader: dict) -> dict:
    return {
        "run_id": "run_scan",
        "command": "from_run",
        "user_id": OWNER["id"],
        "project_id": str(project["_id"]),
        "status": "running",
        "steps": [
            {"name": "a", "detail": None, **leader},
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
        "user": {"id": OWNER["id"], "email": OWNER["email"], "is_admin": True},
        **extra,
    }


def _steps(database) -> dict[str, dict]:
    return {s["name"]: s for s in database["ingestion_runs"].find_one({})["steps"]}


def test_the_leader_records_its_scans_apart_from_its_processing(worker_db):
    from depictio.api.v1 import celery_tasks

    project = _project()
    ids = _ids(project)
    a, b = ids["a"][0], ids["b"][0]
    worker_db["projects"].insert_one(project)
    worker_db["ingestion_runs"].insert_one(_run_doc(project, {"status": "pending"}))

    def _ingest(*_args, on_scanned, **_kwargs):
        on_scanned(a, None)
        on_scanned(b, None)
        return False, "Processing failed: boom"

    with patch.object(manifest_ingest, "_run_dc_ingest", side_effect=_ingest):
        celery_tasks.manifest_refresh_dc_task(_payload(project, "a", scan_dc_ids=[a, b]))

    leader = _steps(worker_db)["a"]
    assert (leader["status"], leader["detail"]) == ("failed", "Processing failed: boom")
    assert leader["scans"] == {a: None, b: None}

    # Its follower was scanned fine: it is processed, not failed with it.
    with patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest:
        result = celery_tasks.manifest_refresh_dc_task(
            _payload(project, "b", scan_leader="a", depends_on=["a"])
        )
    assert result["ok"] is True
    assert ingest.call_args.kwargs["scan"] is False
    assert _steps(worker_db)["b"]["status"] == "success"


def test_the_scans_survive_a_processing_crash(worker_db):
    from depictio.api.v1 import celery_tasks

    project = _project()
    ids = _ids(project)
    a = ids["a"][0]
    worker_db["projects"].insert_one(project)
    worker_db["ingestion_runs"].insert_one(_run_doc(project, {"status": "pending"}))

    def _ingest(*_args, on_scanned, **_kwargs):
        on_scanned(a, None)
        raise RuntimeError("worker lost the table")

    with patch.object(manifest_ingest, "_run_dc_ingest", side_effect=_ingest):
        celery_tasks.manifest_refresh_dc_task(_payload(project, "a", scan_dc_ids=[a]))

    leader = _steps(worker_db)["a"]
    assert (leader["status"], leader["scans"]) == ("failed", {a: None})


def test_a_follower_whose_own_scan_failed_is_failed_with_its_reason(worker_db):
    from depictio.api.v1 import celery_tasks

    project = _project()
    ids = _ids(project)
    worker_db["projects"].insert_one(project)
    leader = {"status": "success", "scans": {ids["a"][0]: None, ids["b"][0]: "Scan failed: empty"}}
    worker_db["ingestion_runs"].insert_one(_run_doc(project, leader))

    with patch.object(manifest_ingest, "_run_dc_ingest") as ingest:
        result = celery_tasks.manifest_refresh_dc_task(
            _payload(project, "b", scan_leader="a", depends_on=["a"])
        )

    ingest.assert_not_called()
    assert result["ok"] is False
    step = _steps(worker_db)["b"]
    assert step["status"] == "failed"
    assert step["detail"] == "Scan failed: empty (scanned by 'a')"
