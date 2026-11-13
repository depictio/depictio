"""Registering a run again appends only its new scans.

The CLI sends a run back with every scan it holds: the stored ones and the one
it just made. A scan stored before a field was added lacks that field, and the
same scan sent back carries it unset (None): they are still the same scan.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bson import ObjectId

from depictio.api.v1.endpoints.runs_endpoints import routes


def _scan(time: str, **extra) -> dict:
    return {"scan_time": time, "stats": {"new_files": 1}, "files_id": {"new_files": []}, **extra}


def test_a_stored_scan_sent_back_with_a_new_unset_field_is_not_appended_again():
    workflow_id, run_id = ObjectId(), ObjectId()
    stored = {
        "_id": run_id,
        "workflow_id": workflow_id,
        "run_tag": "run_a",
        "scan_results": [_scan("t1")],
    }
    runs = MagicMock()
    runs.find.return_value = [stored]
    runs.find_one.return_value = stored
    sent = {
        "_id": run_id,
        "workflow_id": workflow_id,
        "run_tag": "run_a",
        # t1 as stored, now carrying the newer field unset, and the new scan t2.
        "scan_results": [_scan("t1", file_changes=None), _scan("t2", file_changes=None)],
    }
    run = SimpleNamespace(id=run_id, run_tag="run_a", mongo=lambda: dict(sent))
    payload = SimpleNamespace(runs=[run], update=True)

    with patch.object(routes, "runs_collection", runs):
        routes._apply_run_upserts(payload, workflow_id)

    [operations] = runs.bulk_write.call_args.args
    [update] = operations
    pushed = update._doc["$push"]["scan_results"]["$each"]
    assert [s["scan_time"] for s in pushed] == ["t2"]
