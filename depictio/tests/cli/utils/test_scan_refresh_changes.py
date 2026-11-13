"""A re-scan of a run that re-reads only what moved (``sync_changed`` +
``prune_missing``, what a server refresh uses), and says what moved.

``--sync-files`` re-uploads every registered file, so a refresh with nothing
new reported every file of every run as "updated" and re-ingested all of them.
"""

from unittest.mock import MagicMock, patch

import pytest

from depictio.cli.cli.utils.common import format_timestamp
from depictio.cli.cli.utils.scan import scan_run_for_multiple_data_collections
from depictio.cli.cli.utils.scan_utils import generate_file_hash
from depictio.cli.cli.utils.scan_walk import iter_run_files
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import WorkflowRun

from .test_scan_detection import make_dc


@pytest.fixture(autouse=True)
def set_depictio_context(monkeypatch):
    monkeypatch.setattr("depictio.models.config.DEPICTIO_CONTEXT", "CLI")
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "CLI")


def _registered(path, run_id, *, file_hash=None, size=None, modified=None) -> dict:
    (scanned,) = [s for s in iter_run_files(str(path.parent)) if s.path == str(path)]
    return {
        "_id": PyObjectId(),
        "file_location": scanned.path,
        "run_id": run_id,
        "file_hash": file_hash
        or generate_file_hash(
            scanned.name,
            scanned.size,
            format_timestamp(scanned.ctime),
            format_timestamp(scanned.mtime),
        ),
        "filesize": size if size is not None else scanned.size,
        "modification_time": modified or format_timestamp(scanned.mtime),
    }


def _scan(tmp_path, dc, existing, **kwargs):
    permissions = Permission(owners=[UserBase(id=PyObjectId(), email="scan@example.com")])
    run = WorkflowRun(
        id=PyObjectId(),
        workflow_id=PyObjectId(),
        run_tag="run_a",
        workflow_config_id=PyObjectId(),
        run_location=str(tmp_path),
        creation_time="2026-01-01 00:00:00",
        last_modification_time="2026-01-01 00:00:00",
        permissions=permissions,
    )
    ok = MagicMock(status_code=200)
    with (
        patch("depictio.cli.cli.utils.scan.api_create_files_chunked", return_value=[ok]) as pushed,
        patch("depictio.cli.cli.utils.scan.api_delete_files") as deleted,
    ):
        result = scan_run_for_multiple_data_collections(
            run_location=str(tmp_path),
            run_tag="run_a",
            workflow_config=MagicMock(id=PyObjectId()),
            data_collections=[dc],
            all_existing_files={str(dc.id): existing},
            workflow_id=run.workflow_id,
            existing_run=run,
            CLI_config=MagicMock(),
            permissions=permissions,
            rescan_folders=True,
            **kwargs,
        )
    return result, pushed, deleted


def test_a_refresh_pushes_the_changed_file_only_and_says_what_it_was(tmp_path):
    dc = make_dc(pattern=r".*\.csv")
    kept, moved = tmp_path / "kept.csv", tmp_path / "moved.csv"
    kept.write_text("a\n1\n")
    moved.write_text("a\n1\n2\n3\n")
    run_id = str(PyObjectId())
    existing = {
        str(kept): _registered(kept, run_id),
        str(moved): _registered(
            moved, run_id, file_hash="0" * 64, size=4, modified="2026-01-01 00:00:00"
        ),
    }

    run, pushed, _deleted = _scan(tmp_path, dc, existing, sync_changed=True, prune_missing=True)

    sent = [f.filename for call in pushed.call_args_list for f in call.kwargs["files"]]
    assert sent == ["moved.csv"]
    scan = run.scan_results[-1]
    assert scan.dc_stats["dc"]["unchanged_files"] == 1
    assert scan.dc_stats["dc"]["changed_files"] == 1
    assert scan.dc_stats["dc"]["updated_files"] == 0
    moved_id = existing[str(moved)]["_id"]
    assert scan.file_changes == {
        str(moved_id): {
            "size": [4, moved.stat().st_size],
            "modified": ["2026-01-01 00:00:00", scan.file_changes[str(moved_id)]["modified"][1]],
        }
    }


def test_a_refresh_with_nothing_new_pushes_nothing(tmp_path):
    dc = make_dc(pattern=r".*\.csv")
    kept = tmp_path / "kept.csv"
    kept.write_text("a\n1\n")
    existing = {str(kept): _registered(kept, str(PyObjectId()))}

    run, pushed, _deleted = _scan(tmp_path, dc, existing, sync_changed=True, prune_missing=True)

    assert pushed.call_count == 0
    scan = run.scan_results[-1]
    assert scan.dc_stats["dc"]["unchanged_files"] == 1
    assert scan.file_changes is None
    # Found, though not pushed: not a scan that "matched no file".
    from depictio.cli.cli.utils.scan import _files_matched

    assert _files_matched(run) == 1


def test_prune_missing_removes_a_file_gone_from_the_run(tmp_path):
    dc = make_dc(pattern=r".*\.csv")
    kept = tmp_path / "kept.csv"
    kept.write_text("a\n1\n")
    gone = {"_id": PyObjectId(), "file_location": str(tmp_path / "gone.csv"), "file_hash": "x"}
    existing = {str(kept): _registered(kept, str(PyObjectId())), gone["file_location"]: gone}

    run, _pushed, deleted = _scan(tmp_path, dc, existing, sync_changed=True, prune_missing=True)

    assert deleted.call_args.args[0] == [str(gone["_id"])]
    assert [str(i) for i in run.scan_results[-1].files_id["deleted_files"]] == [str(gone["_id"])]


def test_without_prune_a_gone_file_is_only_reported_missing(tmp_path):
    dc = make_dc(pattern=r".*\.csv")
    kept = tmp_path / "kept.csv"
    kept.write_text("a\n1\n")
    gone = {"_id": PyObjectId(), "file_location": str(tmp_path / "gone.csv"), "file_hash": "x"}
    existing = {str(kept): _registered(kept, str(PyObjectId())), gone["file_location"]: gone}

    run, _pushed, deleted = _scan(tmp_path, dc, existing, sync_changed=True)

    assert deleted.call_count == 0
    assert [str(i) for i in run.scan_results[-1].files_id["missing_files"]] == [str(gone["_id"])]
