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

    async def _no_token(_user, _dry_run):
        return None

    with (
        patch.object(attach_run, "projects_collection", database["projects"]),
        patch.object(attach_run, "runs_collection", database["runs"]),
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


def test_locked_project_409(env):
    project = _store(env, _project(env.old, published_lock={"dashboard_ids": []}))
    status, _body = _call(project, env.new, dry_run=False)
    assert status == 409
    assert env.dispatch.call_count == 0
