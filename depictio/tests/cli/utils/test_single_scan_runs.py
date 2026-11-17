"""A one-file collection's files point at the runs they belong to (epic #1399)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from depictio.cli.cli.utils import scan as scan_module

ATHENS_ID = str(ObjectId())


def _response(status: int, body):
    return SimpleNamespace(status_code=status, json=lambda: body, text="")


@pytest.fixture
def project(tmp_path):
    runs = {}
    for name in ("run_athens", "run_barcelona"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "metadata.tsv").write_text("sample\nx\n")
        runs[name] = str(tmp_path / name)
    params = SimpleNamespace(
        filename=f"{runs['run_athens']}/metadata.tsv",
        run_files={loc: f"{loc}/metadata.tsv" for loc in runs.values()},
        scope=None,
    )
    dc = SimpleNamespace(
        id=ObjectId(),
        data_collection_tag="metadata",
        config=SimpleNamespace(scan=SimpleNamespace(mode="single", scan_parameters=params)),
    )
    workflow = SimpleNamespace(
        id=ObjectId(),
        workflow_tag="wf",
        data_collections=[dc],
        data_location=SimpleNamespace(
            locations=list(runs.values()), structure="flat", runs_regex=None
        ),
        config=None,
    )
    return workflow, dc, runs


def _scan(workflow, dc, existing_files=(), known_runs=None):
    seen_runs: list = []
    upserted: list = []

    def process_files(path, run, **kwargs):
        seen_runs.append((run.run_tag, str(run.id), run.run_location))
        return [SimpleNamespace(scan_result={"result": "success"}, file=MagicMock())]

    known = known_runs if known_runs is not None else [{"_id": ATHENS_ID, "run_tag": "run_athens"}]
    config = SimpleNamespace(user=MagicMock())
    with (
        patch.object(scan_module, "UserBase", MagicMock()),
        patch.object(scan_module, "Permission", MagicMock()),
        patch.object(scan_module, "WorkflowRun", side_effect=lambda **kw: SimpleNamespace(**kw)),
        patch.object(scan_module, "process_files", side_effect=process_files),
        patch.object(scan_module, "api_get_runs_by_wf_id", return_value=_response(200, known)),
        patch.object(
            scan_module, "api_get_files_by_dc_id", return_value=_response(200, list(existing_files))
        ),
        patch.object(scan_module, "api_create_files") as create,
        patch.object(scan_module, "api_delete_file") as delete,
        patch.object(
            scan_module,
            "api_upsert_runs_batch",
            side_effect=lambda runs, cfg, update: (
                upserted.append((runs, update)) or _response(200, {})
            ),
        ),
    ):
        result = scan_module.scan_files_for_data_collection(
            workflow, str(dc.id), config, {"sync_files": False}
        )
    return result, seen_runs, upserted, create, delete


def test_a_file_bound_to_a_registered_run_points_at_it(project):
    workflow, dc, runs = project
    result, seen, upserted, create, _ = _scan(workflow, dc)
    assert result == {"result": "success"}
    by_tag = {tag: (rid, loc) for tag, rid, loc in seen}
    assert by_tag["run_athens"] == (ATHENS_ID, runs["run_athens"])
    # Barcelona had no run yet: it is inserted, never updated.
    ((new_runs, update),) = upserted
    assert [r.run_tag for r in new_runs] == ["run_barcelona"]
    assert update is False
    assert str(new_runs[0].id) == by_tag["run_barcelona"][0]
    create.assert_called_once()


def test_a_file_registered_under_a_run_that_was_never_stored_is_registered_again(project):
    workflow, dc, runs = project
    stale = {
        "_id": str(ObjectId()),
        "file_location": f"{runs['run_athens']}/metadata.tsv",
        "run_tag": "run_athens",
        "run_id": str(ObjectId()),
    }
    _, _, _, _, delete = _scan(workflow, dc, existing_files=[stale])
    delete.assert_called_once()
    assert delete.call_args.args[0] == stale["_id"]


def test_a_shared_file_is_never_registered_as_a_run(project):
    workflow, dc, runs = project
    shared = f"{runs['run_athens']}/metadata.tsv"
    dc.config.scan.scan_parameters.run_files = {loc: shared for loc in runs.values()}
    _, seen, upserted, _, _ = _scan(workflow, dc, known_runs=[])
    assert [tag for tag, _, _ in seen] == ["metadata-single-file-scan"]
    assert upserted == []
