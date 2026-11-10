"""The runs view of a project: one row per pipeline run, with its scans and
the files each collection found in it."""

from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints.project_runs import build_project_runs

WF = ObjectId()


def _project():
    return {
        "workflows": [
            {
                "_id": WF,
                "name": "nf-core/rnaseq",
                "data_collections": [
                    {"data_collection_tag": "counts", "config": {"scan": {"mode": "recursive"}}},
                    {"data_collection_tag": "qc", "config": {"scan": {"mode": "recursive"}}},
                    {"data_collection_tag": "samplesheet", "config": {"scan": {"mode": "single"}}},
                ],
            }
        ]
    }


def _scan(time, counts, qc, failed=0):
    return {
        "scan_time": time,
        "dc_stats": {
            "counts": {"total_files": counts, "new_files": counts},
            "qc": {"total_files": qc, "updated_files": qc, "other_failure_files": failed},
        },
    }


def test_a_run_lists_its_scans_and_the_files_of_each_collection():
    run = {
        "workflow_id": WF,
        "run_tag": "run_b",
        "run_location": "/data/run_b",
        "creation_time": "2026-01-01 10:00:00",
        "files_id": [ObjectId(), ObjectId()],
        "scan_results": [_scan("2026-01-02 10:00:00", 1, 0), _scan("2026-01-03 10:00:00", 1, 1)],
    }
    (row,) = build_project_runs(_project(), [run]).runs
    assert row.workflow == "nf-core/rnaseq"
    assert row.files == 2
    assert row.dc_files == {"counts": 1, "qc": 1}
    assert [s.scan_time for s in row.scans] == ["2026-01-02 10:00:00", "2026-01-03 10:00:00"]
    assert row.scans[1].files_updated == 1
    assert row.status == "ok"


def test_a_collection_found_in_another_run_but_not_this_one_marks_it_incomplete():
    complete = {"workflow_id": WF, "run_tag": "run_a", "scan_results": [_scan("t", 3, 1)]}
    missing = {"workflow_id": WF, "run_tag": "run_b", "scan_results": [_scan("t", 3, 0)]}
    rows = build_project_runs(_project(), [complete, missing]).runs
    assert [(r.run_tag, r.dc_files["qc"], r.status) for r in rows] == [
        ("run_a", 1, "ok"),
        ("run_b", 0, "incomplete"),
    ]


def test_a_collection_no_run_holds_is_not_expected():
    """Derived and fixed-file collections are never scanned per run: a run
    that lacks them is not incomplete."""
    run = {"workflow_id": WF, "run_tag": "run_a", "scan_results": [_scan("t", 3, 0)]}
    (row,) = build_project_runs(_project(), [run]).runs
    assert row.dc_files == {"counts": 3}
    assert row.status == "ok"


def test_failures_and_missing_scans_have_their_own_status():
    failed = {"workflow_id": WF, "run_tag": "run_a", "scan_results": [_scan("t", 1, 1, failed=1)]}
    unscanned = {"workflow_id": WF, "run_tag": "run_b"}
    rows = build_project_runs(_project(), [unscanned, failed]).runs
    assert [(r.run_tag, r.status) for r in rows] == [("run_a", "partial"), ("run_b", "no_scan")]


def test_a_one_file_collection_is_not_a_run():
    single = {"workflow_id": WF, "run_tag": "samplesheet-single-file-scan", "scan_results": []}
    assert build_project_runs(_project(), [single]).runs == []
