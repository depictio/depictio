"""The runs of a project, one by one: their folder, when they were seen, every
scan, and how many files each collection found in each of them.

Pure read over the ``runs`` documents, like the ingestion report. A collection
read from one file records a run of its own (``<tag>-single-file-scan``): it is
not a run of the pipeline, so it is left out.
"""

from __future__ import annotations

from typing import Any, Iterable

from bson import ObjectId
from pydantic import BaseModel

from depictio.api.v1.db import runs_collection

SINGLE_FILE_SUFFIX = "-single-file-scan"


class RunScan(BaseModel):
    scan_time: str | None
    files_total: int
    files_new: int
    files_updated: int
    files_skipped: int
    files_failed: int


class ProjectRun(BaseModel):
    run_tag: str
    workflow: str | None
    run_location: str | None
    folder_created: str | None
    folder_modified: str | None
    registered: str | None
    run_hash: str | None
    status: str
    files: int
    #: Files each collection of the run's workflow found in its latest scan;
    #: 0 for one that found nothing.
    dc_files: dict[str, int]
    scans: list[RunScan]


class ProjectRuns(BaseModel):
    runs: list[ProjectRun]


def _sum(stats: dict[str, dict[str, Any]], key: str) -> int:
    return sum(int((s or {}).get(key, 0) or 0) for s in stats.values())


def _scan(scan: dict[str, Any]) -> RunScan:
    stats = scan.get("dc_stats") or {}
    return RunScan(
        scan_time=scan.get("scan_time"),
        files_total=_sum(stats, "total_files"),
        files_new=_sum(stats, "new_files"),
        files_updated=_sum(stats, "updated_files"),
        files_skipped=_sum(stats, "skipped_files"),
        files_failed=_sum(stats, "other_failure_files"),
    )


def _latest_stats(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scans = [s for s in run.get("scan_results") or [] if isinstance(s, dict)]
    return (scans[-1].get("dc_stats") if scans else None) or {}


def build_project_runs(project: dict[str, Any], run_docs: Iterable[dict[str, Any]]) -> ProjectRuns:
    workflows = {str(wf.get("_id") or wf.get("id")): wf for wf in project.get("workflows") or []}
    docs = [
        r
        for r in run_docs
        if r.get("run_tag") and not str(r["run_tag"]).endswith(SINGLE_FILE_SUFFIX)
    ]
    # What a run of a workflow is expected to hold: every collection that found
    # files in at least one of its runs. A collection derived from others, or
    # read from one fixed file, is never scanned per run and so never expected.
    expected: dict[str, set[str]] = {}
    for run in docs:
        found = {
            t
            for t, st in _latest_stats(run).items()
            if int((st or {}).get("total_files", 0) or 0) > 0
        }
        expected.setdefault(str(run.get("workflow_id")), set()).update(found)

    runs: list[ProjectRun] = []
    for run in docs:
        workflow = workflows.get(str(run.get("workflow_id"))) or {}
        scans = [s for s in run.get("scan_results") or [] if isinstance(s, dict)]
        latest = _latest_stats(run)
        dc_files = {t: 0 for t in expected.get(str(run.get("workflow_id")), set())}
        for dc_tag, stats in latest.items():
            n = int((stats or {}).get("total_files", 0) or 0)
            if n > 0 or dc_tag in dc_files:
                dc_files[dc_tag] = n
        if not scans:
            status = "no_scan"
        elif _sum(latest, "other_failure_files") > 0:
            status = "partial"
        elif any(n == 0 for n in dc_files.values()):
            status = "incomplete"
        else:
            status = "ok"
        runs.append(
            ProjectRun(
                run_tag=str(run["run_tag"]),
                workflow=workflow.get("name"),
                run_location=run.get("run_location"),
                folder_created=run.get("creation_time"),
                folder_modified=run.get("last_modification_time"),
                registered=run.get("registration_time"),
                run_hash=run.get("run_hash") or None,
                status=status,
                # The latest scan's count: ``files_id`` is not kept up to date
                # when a run is scanned again.
                files=_sum(latest, "total_files") if scans else len(run.get("files_id") or []),
                dc_files=dict(sorted(dc_files.items())),
                scans=[_scan(s) for s in scans],
            )
        )
    runs.sort(key=lambda r: r.run_tag)
    return ProjectRuns(runs=runs)


def project_runs(project: dict[str, Any]) -> ProjectRuns:
    ids = [ObjectId(wf["_id"]) for wf in project.get("workflows") or [] if wf.get("_id")]
    if not ids:
        return ProjectRuns(runs=[])
    return build_project_runs(project, runs_collection.find({"workflow_id": {"$in": ids}}))
