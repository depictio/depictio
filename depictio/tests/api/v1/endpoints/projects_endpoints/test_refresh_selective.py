"""A refresh reads again only what moved.

A collection read from files whose hash follows their bytes (``recursive``,
``single``, ``s3_prefix``) pushes only its new and changed files, and is not
rebuilt at all when its files and configuration are those of its last
successful refresh. A manifest or a URL collection is read again every time:
its hash names the source, not its content. ``full`` reads everything again.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest
from depictio.api.v1.monitoring import store as monitoring_store
from depictio.tests.api.v1.endpoints.projects_endpoints.test_refresh_manifest import (
    _project_doc,
    _user,
)


@pytest.fixture()
def db():
    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(manifest_ingest, "projects_collection", database["projects"]),
        patch.object(manifest_ingest, "files_collection", database["files"]),
        patch.object(manifest_ingest, "deltatables_collection", database["deltatables"]),
        patch.object(manifest_ingest, "multiqc_collection", database["multiqc"]),
        patch.object(monitoring_store, "ingestion_runs_collection", database["ingestion_runs"]),
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
    ):
        yield database


def _recursive(tmp_path) -> tuple[dict, str]:
    doc = _project_doc(_user().id, tags=["counts"], scan_mode="recursive", location=str(tmp_path))
    wf = doc["workflows"][0]
    return wf, str(wf["data_collections"][0]["_id"])


def _register(db, dc_id: str, name: str, file_hash: str) -> None:
    db["files"].insert_one(
        {
            "_id": ObjectId(),
            "data_collection_id": ObjectId(dc_id),
            "file_location": f"/data/{name}",
            "file_hash": file_hash,
        }
    )


def _ingest(wf: dict, dc_id: str, **kwargs):
    """(ok, message, the helper modes run, the scan's command parameters)."""
    with (
        patch.object(dc_utils, "_build_cli_config_for_user", return_value=object()),
        patch(
            "depictio.cli.cli.utils.helpers.process_data_collection_helper",
            return_value={"result": "success"},
        ) as helper,
        # A recursive collection is scanned by the one walk over the runs.
        patch(
            "depictio.cli.cli.utils.scan.scan_files_for_workflow",
            return_value={"result": "success"},
        ) as walk,
    ):
        ok, message = manifest_ingest._run_dc_ingest(wf, dc_id, _user(), **kwargs)
    modes = [c.kwargs.get("mode") for c in helper.call_args_list]
    scans = [c for c in helper.call_args_list if c.kwargs.get("mode") == "scan"]
    scan = scans[0] if scans else walk.call_args
    return ok, message, modes, scan.kwargs.get("command_parameters")


def test_a_walked_collection_pushes_only_what_changed_and_drops_what_is_gone(db, tmp_path):
    wf, dc_id = _recursive(tmp_path)
    _, _, _, params = _ingest(wf, dc_id)
    assert params["sync_files"] is False
    assert params["sync_changed"] is True and params["prune_missing"] is True


def test_a_single_file_collection_pushes_it_only_if_it_changed(db, tmp_path):
    doc = _project_doc(
        _user().id, tags=["counts"], scan_mode="single", location=str(tmp_path / "a.csv")
    )
    wf = doc["workflows"][0]
    _, _, _, params = _ingest(wf, str(wf["data_collections"][0]["_id"]))
    assert params == {"sync_changed": True}


def test_a_manifest_collection_is_read_again_every_time(db):
    doc = _project_doc(_user().id, tags=["counts"])
    wf = doc["workflows"][0]
    _, _, _, params = _ingest(wf, str(wf["data_collections"][0]["_id"]))
    assert params == {"sync_files": True}


def test_the_signature_follows_the_files_and_ignores_a_manifest(db, tmp_path):
    wf, dc_id = _recursive(tmp_path)
    assert manifest_ingest.collection_inputs_signature(wf, dc_id) is None  # no file yet
    _register(db, dc_id, "a.csv", "h1")
    first = manifest_ingest.collection_inputs_signature(wf, dc_id)
    assert first and first == manifest_ingest.collection_inputs_signature(wf, dc_id)
    db["files"].update_one({}, {"$set": {"file_hash": "h2"}})
    assert manifest_ingest.collection_inputs_signature(wf, dc_id) != first

    manifest = _project_doc(_user().id, tags=["counts"])["workflows"][0]
    manifest_dc = str(manifest["data_collections"][0]["_id"])
    _register(db, manifest_dc, "m.csv", "h1")
    assert manifest_ingest.collection_inputs_signature(manifest, manifest_dc) is None


def test_an_image_collection_is_never_left_alone(db, tmp_path):
    # Its images folder is read apart from its files: no signature covers it.
    wf, dc_id = _recursive(tmp_path)
    wf["data_collections"][0]["config"]["type"] = "image"
    _register(db, dc_id, "manifest.csv", "h1")
    assert manifest_ingest.collection_inputs_signature(wf, dc_id) is None


def test_what_a_multiqc_ingestion_writes_back_is_not_an_input(db, tmp_path):
    wf, dc_id = _recursive(tmp_path)
    wf["data_collections"][0]["config"]["type"] = "multiqc"
    wf["data_collections"][0]["config"]["dc_specific_properties"] = {"samples": ["S1", "S2"]}
    _register(db, dc_id, "multiqc.parquet", "h1")
    before = manifest_ingest.collection_inputs_signature(wf, dc_id)
    wf["data_collections"][0]["config"]["dc_specific_properties"] = {"samples": ["S2", "S1"]}
    assert manifest_ingest.collection_inputs_signature(wf, dc_id) == before


def test_an_unchanged_collection_with_its_data_is_left_as_it_was(db, tmp_path):
    wf, dc_id = _recursive(tmp_path)
    _register(db, dc_id, "a.csv", "h1")
    db["deltatables"].insert_one({"data_collection_id": ObjectId(dc_id), "aggregation": [{}]})
    signature = manifest_ingest.collection_inputs_signature(wf, dc_id)
    outcome: dict = {}

    ok, message, modes, _ = _ingest(wf, dc_id, previous_signature=signature, outcome=outcome)

    assert (ok, message) == (True, manifest_ingest.UNCHANGED_DETAIL)
    assert "process" not in modes
    assert outcome == {"inputs_signature": signature, "unchanged": True}


@pytest.mark.parametrize(
    "case",
    ["file_changed", "no_data", "full"],
)
def test_a_collection_is_rebuilt_when_it_cannot_be_left_alone(db, tmp_path, case):
    wf, dc_id = _recursive(tmp_path)
    _register(db, dc_id, "a.csv", "h1")
    signature = manifest_ingest.collection_inputs_signature(wf, dc_id)
    if case != "no_data":
        db["deltatables"].insert_one({"data_collection_id": ObjectId(dc_id), "aggregation": [{}]})
    if case == "file_changed":
        db["files"].update_one({}, {"$set": {"file_hash": "h2"}})
    outcome: dict = {}

    _, message, modes, _ = _ingest(
        wf, dc_id, previous_signature=signature, outcome=outcome, sync_files=case == "full"
    )

    assert "process" in modes
    assert message != manifest_ingest.UNCHANGED_DETAIL
    assert "unchanged" not in outcome


def _run(db, run_id: str, steps: list[dict], started: str, project_id: str = "p1") -> None:
    db["ingestion_runs"].insert_one(
        {"run_id": run_id, "project_id": project_id, "started_at": started, "steps": steps}
    )


def test_the_last_signature_comes_from_the_newest_other_run_and_only_if_it_succeeded(db):
    _run(
        db,
        "old",
        [{"name": "counts", "status": "success", "inputs_signature": "s-old"}],
        "2026-11-01",
    )
    _run(
        db,
        "new",
        [{"name": "counts", "status": "success", "inputs_signature": "s-new"}],
        "2026-11-02",
    )
    _run(db, "now", [{"name": "counts", "status": "running"}], "2026-11-03")
    _run(
        db,
        "other",
        [{"name": "counts", "status": "success", "inputs_signature": "x"}],
        "2026-11-04",
        "p2",
    )
    assert manifest_ingest.last_ingested_signature("p1", "counts", "now") == "s-new"

    _run(db, "failed", [{"name": "counts", "status": "failed"}], "2026-11-02T12")
    assert manifest_ingest.last_ingested_signature("p1", "counts", "now") is None
    assert manifest_ingest.last_ingested_signature("p1", "absent", "now") is None


def _task_payload(doc: dict, run_id: str, sync_files: bool) -> dict:
    user = _user()
    wf = doc["workflows"][0]
    dc = wf["data_collections"][0]
    return {
        "run_id": run_id,
        "project_id": str(doc["_id"]),
        "wf_index": 0,
        "dc_id": str(dc["_id"]),
        "dc_tag": dc["data_collection_tag"],
        "sync_files": sync_files,
        "user": {"id": str(user.id), "email": user.email, "is_admin": False},
    }


@pytest.mark.parametrize("sync_files", [False, True])
def test_the_task_hands_over_the_last_signature_and_records_the_new_one(db, tmp_path, sync_files):
    from depictio.api.v1 import celery_tasks
    from depictio.api.v1.endpoints.projects_endpoints import storage_config
    from depictio.api.v1.monitoring import store as monitoring_store

    doc = _project_doc(_user().id, tags=["counts"], scan_mode="recursive", location=str(tmp_path))
    db["projects"].insert_one(doc)
    _run(
        db,
        "before",
        [{"name": "counts", "status": "success", "inputs_signature": "s-before"}],
        "2026-11-01",
        str(doc["_id"]),
    )
    _run(db, "run1", [{"name": "counts", "status": "pending"}], "2026-11-02", str(doc["_id"]))
    seen: dict = {}

    def _fake_ingest(*_a, previous_signature=None, outcome=None, **_k):
        seen["previous"] = previous_signature
        outcome["inputs_signature"] = "s-now"
        return True, None

    with (
        patch.object(monitoring_store, "ingestion_runs_collection", db["ingestion_runs"]),
        patch("depictio.api.v1.db.projects_collection", db["projects"]),
        patch.object(storage_config, "project_storage_collection", db["project_storage"]),
        patch.object(manifest_ingest, "_run_dc_ingest", side_effect=_fake_ingest),
    ):
        celery_tasks.manifest_refresh_dc_task(_task_payload(doc, "run1", sync_files))

    assert seen["previous"] == (None if sync_files else "s-before")
    step = db["ingestion_runs"].find_one({"run_id": "run1"})["steps"][0]
    assert step["status"] == "success"
    assert step["inputs_signature"] == "s-now"
