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


# ── the files of one run ─────────────────────────────────────────────────────

from depictio.api.v1.endpoints.projects_endpoints.project_runs import build_run_files  # noqa: E402

COUNTS_DC, QC_DC = ObjectId(), ObjectId()


def _project_with_ids():
    project = _project()
    dcs = project["workflows"][0]["data_collections"]
    dcs[0]["_id"], dcs[1]["_id"] = COUNTS_DC, QC_DC
    return project


def _file(dc, name, **extra):
    return {
        "_id": ObjectId(),
        "data_collection_id": dc,
        "filename": name,
        "file_location": f"/data/run_b/{name}",
        "filesize": 10,
        "modification_time": "2026-01-02 09:00:00",
        "registration_time": "2026-01-02 10:00:00",
        **extra,
    }


def _scan_ids(time, new=(), reread=(), failed=(), changed=(), file_changes=None):
    return {
        "scan_time": time,
        "dc_stats": {},
        "files_id": {
            "new_files": [f["_id"] for f in new],
            "updated_files": [f["_id"] for f in reread],
            "changed_files": [f["_id"] for f in changed],
            "other_failure_files": [f["_id"] for f in failed],
        },
        "file_changes": file_changes,
    }


def test_each_file_of_a_run_says_which_scan_brought_it_and_a_reread_changes_nothing():
    counts = _file(COUNTS_DC, "counts.tsv")
    qc = _file(QC_DC, "qc.json")
    late = _file(QC_DC, "late.json")
    run = {
        "_id": ObjectId(),
        "workflow_id": WF,
        "run_tag": "run_b",
        "scan_results": [
            _scan_ids("2026-01-02 10:00:00", new=[counts, qc]),
            _scan_ids("2026-01-03 10:00:00", new=[late], reread=[qc]),
        ],
    }
    report = build_run_files(_project_with_ids(), [run], [counts, qc, late], "run_b")

    assert [s.scan_time for s in report.scans] == ["2026-01-02 10:00:00", "2026-01-03 10:00:00"]
    # qc.json was only read again in the second scan: that changed nothing.
    assert [(s.new, s.changed, s.failed) for s in report.scans] == [(2, 0, 0), (1, 0, 0)]
    by_name = {f.filename: f for f in report.files}
    assert by_name["counts.tsv"].dc_tag == "counts"
    assert (by_name["counts.tsv"].added_in, by_name["counts.tsv"].changed_in) == (0, [])
    assert (by_name["qc.json"].added_in, by_name["qc.json"].changed_in) == (0, [])
    assert by_name["late.json"].added_in == 1
    # Grouped by collection, then by name.
    assert [f.filename for f in report.files] == ["counts.tsv", "late.json", "qc.json"]


def test_a_file_that_failed_is_marked_in_that_scan():
    bad = _file(QC_DC, "bad.json")
    run = {
        "_id": ObjectId(),
        "workflow_id": WF,
        "run_tag": "run_b",
        "scan_results": [_scan_ids("t1", failed=[bad])],
    }
    (f,) = build_run_files(_project_with_ids(), [run], [bad], "run_b").files
    assert f.failed_in == [0]
    assert f.added_in is None


def test_only_the_runs_of_the_project_with_that_tag_are_read():
    mine = _file(COUNTS_DC, "mine.tsv")
    other_run = {
        "_id": ObjectId(),
        "workflow_id": ObjectId(),
        "run_tag": "run_b",
        "scan_results": [],
    }
    run = {
        "_id": ObjectId(),
        "workflow_id": WF,
        "run_tag": "run_b",
        "scan_results": [_scan_ids("t1", new=[mine])],
    }
    report = build_run_files(_project_with_ids(), [other_run, run], [mine], "run_b")
    assert [f.filename for f in report.files] == ["mine.tsv"]
    assert len(report.scans) == 1


def test_a_changed_file_says_what_it_was_and_what_its_report_changed():
    qc = _file(QC_DC, "multiqc.parquet", filesize=140)
    run = {
        "_id": ObjectId(),
        "workflow_id": WF,
        "run_tag": "run_b",
        "scan_results": [
            _scan_ids("t1", new=[qc]),
            _scan_ids(
                "t2",
                changed=[qc],
                file_changes={str(qc["_id"]): {"size": [132, 140], "modified": ["m1", "m2"]}},
            ),
        ],
    }
    change = {
        "samples_added": ["S3"],
        "samples_removed": [],
        "modules_added": [],
        "modules_removed": ["fastp"],
    }
    report = build_run_files(
        _project_with_ids(), [run], [qc], "run_b", {qc["file_location"]: change}
    )

    (f,) = report.files
    assert f.changed_in == [1]
    assert [(c.scan, c.size, c.modified) for c in f.changes] == [(1, [132, 140], ["m1", "m2"])]
    assert f.report_change is not None and f.report_change.samples_added == ["S3"]
    assert f.report_change.modules_removed == ["fastp"]
    assert [s.changed for s in report.scans] == [0, 1]


def test_a_single_file_bound_to_a_run_is_counted_under_it():
    """A one-file collection bound per run (epic #1399) is registered under
    the run, outside the recursive scan's stats: it counts in that run."""
    a = {"workflow_id": WF, "run_tag": "run_a", "scan_results": [_scan("t", 3, 1)]}
    b = {"workflow_id": WF, "run_tag": "run_b", "scan_results": [_scan("t", 3, 1)]}
    rows = build_project_runs(
        _project(), [a, b], single_files={"run_a": {"samplesheet": 1}, "run_b": {"samplesheet": 1}}
    ).runs
    assert [r.dc_files for r in rows] == [
        {"counts": 3, "qc": 1, "samplesheet": 1},
        {"counts": 3, "qc": 1, "samplesheet": 1},
    ]
    assert [r.files for r in rows] == [5, 5]


def test_a_shared_single_file_never_makes_another_run_incomplete():
    """One file kept for every run is counted under the run that brought it,
    and the other runs are not missing it."""
    a = {"workflow_id": WF, "run_tag": "run_a", "scan_results": [_scan("t", 3, 1)]}
    b = {"workflow_id": WF, "run_tag": "run_b", "scan_results": [_scan("t", 3, 1)]}
    rows = build_project_runs(_project(), [a, b], single_files={"run_a": {"samplesheet": 1}}).runs
    assert [(r.run_tag, r.dc_files.get("samplesheet"), r.status) for r in rows] == [
        ("run_a", 1, "ok"),
        ("run_b", None, "ok"),
    ]


def test_a_run_lists_the_recipe_collections_it_fed():
    from depictio.api.v1.endpoints.projects_endpoints.project_runs import outputs_by_run

    alpha, bray = ObjectId(), ObjectId()
    project = {
        "workflows": [
            {
                "_id": WF,
                "data_collections": [
                    {
                        "_id": alpha,
                        "data_collection_tag": "alpha",
                        "config": {"source": "transformed"},
                    },
                    {
                        "_id": bray,
                        "data_collection_tag": "bray",
                        "config": {"source": "transformed"},
                    },
                ],
            }
        ]
    }
    outputs = outputs_by_run(
        project,
        {
            str(alpha): [
                {"run_tags": ["run_a"], "run_scope": "run"},
                {"run_tags": ["run_b"], "run_scope": "run"},
            ],
            str(bray): [
                {"run_tags": ["run_a"]},
                {
                    "run_tags": ["run_a", "run_b"],
                    "computed_from_runs": ["run_a", "run_b"],
                    "run_scope": "aggregate",
                },
            ],
        },
    )
    assert outputs == {
        "run_a": {"alpha": "run", "bray": "aggregate"},
        "run_b": {"alpha": "run", "bray": "aggregate"},
    }
    run = {"workflow_id": WF, "run_tag": "run_b", "scan_results": [_scan("t", 3, 1)]}
    (row,) = build_project_runs(_project(), [run], outputs=outputs).runs
    assert row.dc_outputs == {"alpha": "run", "bray": "aggregate"}
