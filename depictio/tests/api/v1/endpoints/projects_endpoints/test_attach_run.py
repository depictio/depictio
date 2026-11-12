"""Tests for POST /projects/{id}/attach_run (``attach_run.attach_run``).

No network, no broker: the data root, the run detection, the template preview
and the Celery dispatch are replaced at their seams in ``attach_run``. What is
checked is the contract of the handler: which projects and folders it refuses
(with which code), that a dry run writes nothing, and that a real attach records
the folder on the workflow, leaves ``single`` bindings alone and dispatches the
ingestion.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from starlette.requests import Request

from depictio.api.v1.endpoints.projects_endpoints import attach_run, publish_lock, routes, utils
from depictio.models.models.users import UserBase

TEMPLATE_ID = "nf-core/ampliseq/2.16.0"


def _admin() -> UserBase:
    return UserBase(id=ObjectId(), email="admin@example.com", is_admin=True)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def _project(old: str, **overrides) -> dict:
    doc = {
        "_id": ObjectId(),
        "name": "p",
        "template_origin": {"template_id": TEMPLATE_ID, "data_root": old, "variables": {}},
        "workflows": [
            {
                "_id": ObjectId(),
                "workflow_tag": "ampliseq",
                "data_location": {"structure": "flat", "locations": [old]},
                "data_collections": [
                    {
                        "_id": ObjectId(),
                        "data_collection_tag": "counts",
                        "config": {"scan": {"mode": "recursive", "scan_parameters": {}}},
                    },
                    {
                        "_id": ObjectId(),
                        "data_collection_tag": "samplesheet",
                        "config": {
                            "scan": {
                                "mode": "single",
                                "scan_parameters": {"filename": f"{old}/samples.csv"},
                            }
                        },
                    },
                ],
            }
        ],
    }
    doc.update(overrides)
    return doc


def _info(pipeline: str = "nf-core/ampliseq"):
    return SimpleNamespace(
        pipeline_name=pipeline,
        pipeline_version="2.16.0",
        engine="nextflow",
        template_ids=lambda: [f"{pipeline}/2.16.0"],
    )


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """A mongomock project store plus every seam of the handler stubbed."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    database = mongomock.MongoClient()["depictio_test"]
    old, new = tmp_path / "run1", tmp_path / "run2"
    old.mkdir()
    new.mkdir()
    state = SimpleNamespace(
        db=database,
        old=str(old),
        new=str(new),
        detect=(TEMPLATE_ID, _info()),
        dispatch=MagicMock(return_value=("run-123", True, [])),
    )
    rows = [
        SimpleNamespace(tag="counts", matched=3, status="ok", mode="recursive"),
        SimpleNamespace(tag="samplesheet", matched=1, status="ok", mode="single"),
    ]
    preview = SimpleNamespace(data_collections=rows, detected_runs=[])
    state.rows = rows
    # The samples the new run's MultiQC reports name.
    state.new_samples = set()

    async def _no_token(_user, _dry_run):
        return None

    with (
        patch.object(attach_run, "projects_collection", database["projects"]),
        patch.object(attach_run, "runs_collection", database["runs"]),
        patch.object(attach_run, "multiqc_collection", database["multiqc"]),
        patch.object(attach_run, "files_collection", database["files"]),
        patch.object(attach_run, "_report_sample_names", lambda _root, _row: state.new_samples),
        patch.object(
            publish_lock, "_db", lambda: SimpleNamespace(projects_collection=database["projects"])
        ),
        patch.object(
            attach_run,
            "_build_data_root",
            lambda data_root, *_a, **_k: SimpleNamespace(location=data_root),
        ),
        patch.object(attach_run, "_detect_run", lambda _root: state.detect),
        patch.object(attach_run, "_dispatch_refresh_tasks", state.dispatch),
        patch.object(routes, "_ensure_cli_token_unless_dry_run", _no_token),
        patch.object(routes, "_reject_non_admin_in_public_mode", lambda *_a: None),
        patch.object(
            utils,
            "_async_get_project_from_id",
            lambda pid, _user, coll: coll.find_one({"_id": ObjectId(str(pid))}),
        ),
        patch(
            "depictio.cli.cli.utils.template_preview.preview_data_root",
            lambda **_kw: preview,
        ),
    ):
        yield state


def _call(project: dict, data_root: str, dry_run: bool = True):
    """(status, body): the report as a dict, or the refusal's ``{detail, code}``."""
    payload = attach_run.AttachRunRequest(data_root=data_root, dry_run=dry_run)
    try:
        result = asyncio.run(
            attach_run.attach_run(str(project["_id"]), payload, _request(), _admin())
        )
    except HTTPException as exc:
        return exc.status_code, {"detail": exc.detail}
    if hasattr(result, "body"):
        return result.status_code, json.loads(result.body)
    return 200, result.model_dump()


def _store(env, project: dict) -> dict:
    env.db["projects"].insert_one(project)
    return project


def test_non_pipeline_project_422(env):
    project = _store(env, _project(env.old, template_origin=None))
    status, body = _call(project, env.new)
    assert (status, body["code"]) == (422, "not_a_pipeline_project")


def test_other_pipeline_422(env):
    env.detect = ("nf-core/rnaseq/3.14.0", _info("nf-core/rnaseq"))
    project = _store(env, _project(env.old))
    status, body = _call(project, env.new)
    assert (status, body["code"]) == (422, "other_pipeline")
    assert env.dispatch.call_count == 0


def test_already_attached_409(env):
    project = _store(env, _project(env.old))
    status, body = _call(project, env.old)
    assert (status, body["code"]) == (409, "already_attached")


def test_s3_prefix_project_cannot_attach(env):
    project = _project(env.old)
    project["template_origin"]["data_root"] = "s3://b/run1"
    project["workflows"][0]["data_location"]["locations"] = ["s3://b/run1"]
    project["workflows"][0]["data_collections"][0]["config"]["scan"] = {
        "mode": "s3_prefix",
        "scan_parameters": {"prefix": "s3://b/run1/", "pattern": "*"},
    }
    _store(env, project)
    status, body = _call(project, env.new)
    assert (status, body["code"]) == (422, "cannot_attach")


def test_dry_run_reports_runs_and_writes_nothing(env):
    project = _store(env, _project(env.old))
    before = env.db["projects"].find_one({"_id": project["_id"]})
    status, body = _call(project, env.new, dry_run=True)
    assert status == 200
    assert body["match"] == "exact"
    assert body["new_runs"] == ["run2"]
    assert body["existing_runs"] == ["run1"]
    assert {d["tag"]: d["matched"] for d in body["data_collections"]} == {
        "counts": 3,
        "samplesheet": 1,
    }
    # A single-file collection keeps its original file: "kept", not "ok".
    assert {d["tag"]: d["status"] for d in body["data_collections"]} == {
        "counts": "ok",
        "samplesheet": "kept",
    }
    assert body["run_id"] is None and body["dry_run"] is True
    assert env.db["projects"].find_one({"_id": project["_id"]}) == before
    assert env.dispatch.call_count == 0


def test_real_attach_records_location_keeps_single_and_dispatches(env):
    project = _store(env, _project(env.old))
    status, body = _call(project, env.new, dry_run=False)
    assert status == 200
    assert body["run_id"] == "run-123"
    stored = env.db["projects"].find_one({"_id": project["_id"]})
    location = stored["workflows"][0]["data_location"]
    assert location["locations"] == [env.old, env.new]
    assert location["attached_locations"] == [env.new]
    single = stored["workflows"][0]["data_collections"][1]["config"]["scan"]
    assert single["scan_parameters"]["filename"] == f"{env.old}/samples.csv"
    kwargs = env.dispatch.call_args.kwargs
    assert kwargs["data_root"] == env.new
    assert {entry[0] for entry in kwargs["to_dispatch"]} == {"counts", "samplesheet"}
    # The new run tags are persisted on the ingestion run, not only in the response.
    assert kwargs["run_tags"] == ["run2"]


def test_locked_project_409(env):
    project = _store(env, _project(env.old, published_lock={"dashboard_ids": []}))
    status, _body = _call(project, env.new, dry_run=False)
    assert status == 409
    assert env.dispatch.call_count == 0


def test_a_run_added_beside_the_runs_of_a_folder_of_runs_joins_them(env):
    """The refresh pre-flight reads the run names the origin holds, so a run
    attached from the same folder has to be one of them."""
    import os

    parent = os.path.dirname(env.old)
    project = _project(env.old)
    project["template_origin"]["data_root"] = parent
    project["template_origin"]["runs"] = ["run1"]
    _store(env, project)
    status, _body = _call(project, env.new, dry_run=False)
    assert status == 200
    stored = env.db["projects"].find_one({"_id": project["_id"]})
    assert stored["template_origin"]["runs"] == ["run1", "run2"]
    assert stored["template_origin"]["data_root"] == parent


def test_a_single_run_project_gains_no_run_names_when_one_is_attached(env):
    project = _store(env, _project(env.old))
    _call(project, env.new, dry_run=False)
    stored = env.db["projects"].find_one({"_id": project["_id"]})
    assert "runs" not in stored["template_origin"]


def _with_multiqc(env, project: dict, samples_by_run: dict[str, list[str]]) -> dict:
    """``project`` with a MultiQC collection whose ingested reports name these samples."""
    dc_id = ObjectId()
    project["workflows"][0]["data_collections"].append(
        {
            "_id": dc_id,
            "data_collection_tag": "multiqc_data",
            "config": {"type": "MultiQC", "scan": {"mode": "recursive", "scan_parameters": {}}},
        }
    )
    for run, samples in samples_by_run.items():
        path = f"/data/{run}/multiqc/multiqc_data/multiqc.parquet"
        env.db["multiqc"].insert_one(
            {
                "data_collection_id": str(dc_id),
                "metadata": {"samples": samples},
                "original_file_path": path,
            }
        )
        env.db["files"].insert_one({"file_location": path, "run_tag": run})
    env.rows.append(
        SimpleNamespace(tag="multiqc_data", matched=1, status="ok", mode="recursive", samples=[])
    )
    return _store(env, project)


def test_a_run_whose_reports_name_samples_already_in_the_project_is_flagged(env):
    project = _with_multiqc(env, _project(env.old), {"run1": ["S1", "S2", "S3"]})
    env.new_samples = {"S2", "S3", "S9"}
    status, body = _call(project, env.new, dry_run=True)
    assert status == 200
    assert body["shared_samples"] == [
        {
            "data_collection_tag": "multiqc_data",
            "runs": ["run1", "run2"],
            "count": 2,
            "samples": ["S2", "S3"],
        }
    ]


def test_samples_are_compared_by_their_canonical_ids(env):
    # A report lists each module's variants of a sample; the check names the sample once.
    project = _with_multiqc(env, _project(env.old), {"run1": ["S1", "S1 - First read: Adapter 1"]})
    env.db["multiqc"].update_one({}, {"$set": {"metadata.canonical_samples": ["S1"]}})
    env.new_samples = {"S1"}
    status, body = _call(project, env.new, dry_run=True)
    assert status == 200
    assert [(s["count"], s["samples"]) for s in body["shared_samples"]] == [(1, ["S1"])]


def test_a_run_sharing_samples_is_refused_and_nothing_is_written(env):
    project = _with_multiqc(env, _project(env.old), {"run1": ["S1"]})
    env.new_samples = {"S1"}
    before = env.db["projects"].find_one({"_id": project["_id"]})
    status, body = _call(project, env.new, dry_run=False)
    assert (status, body["code"]) == (422, "runs_share_samples")
    assert "S1" in body["detail"]
    assert env.db["projects"].find_one({"_id": project["_id"]}) == before
    assert env.dispatch.call_count == 0


def test_a_run_with_its_own_samples_passes(env):
    project = _with_multiqc(env, _project(env.old), {"run1": ["S1", "S2"]})
    env.new_samples = {"S3"}
    status, body = _call(project, env.new, dry_run=False)
    assert status == 200
    assert body["shared_samples"] == []
    assert body["run_id"] == "run-123"
