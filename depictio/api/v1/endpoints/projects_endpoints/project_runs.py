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


# ── the files of one run ─────────────────────────────────────────────────────
# Each scan records the ids of the files it brought, found changed or failed to
# read (``scan_results[].files_id``), and what a changed
# file was before (``file_changes``); each file records its run and its
# collection. Together they say, per file, which scan brought it and which
# changed it, so the runs view can show what a scan changed without guessing
# from dates. A MultiQC report adds the samples and modules its last overwrite
# brought in or dropped.

#: Past this many files a run's list is cut (``truncated``).
MAX_RUN_FILES = 5000

# ``changed_files`` holds the files whose content moved since the scan before.
# A file read again without having moved (``updated_files``: a full refresh, or
# any refresh before changes were told apart) changed nothing and is left out.


class RunFileChange(BaseModel):
    """What one scan found changed in a file: [before, after] of each."""

    scan: int
    size: list[int | None] | None = None
    modified: list[str | None] | None = None


class RunReportChange(BaseModel):
    """The samples and modules a MultiQC report's last overwrite added or removed."""

    samples_added: list[str] = []
    samples_removed: list[str] = []
    modules_added: list[str] = []
    modules_removed: list[str] = []


class RunFile(BaseModel):
    id: str
    dc_id: str
    dc_tag: str | None
    filename: str
    location: str
    size: int | None = None
    modified: str | None = None
    registered: str | None = None
    #: Index (in ``RunFiles.scans``) of the scan that brought it; None when no
    #: scan lists it as new (it only ever failed, or predates the record).
    added_in: int | None = None
    changed_in: list[int] = []
    failed_in: list[int] = []
    changes: list[RunFileChange] = []
    #: A MultiQC report's: what its last overwrite changed, which the newest
    #: scan of ``changed_in`` brought.
    report_change: RunReportChange | None = None


class RunScanFiles(BaseModel):
    scan_time: str | None
    new: int
    changed: int
    failed: int


class RunFiles(BaseModel):
    run_tag: str
    scans: list[RunScanFiles]
    files: list[RunFile]
    truncated: bool = False


def _ids(scan: dict[str, Any], key: str) -> set[str]:
    return {str(i) for i in (scan.get("files_id") or {}).get(key) or []}


def build_run_files(
    project: dict[str, Any],
    run_docs: Iterable[dict[str, Any]],
    file_docs: Iterable[dict[str, Any]],
    run_tag: str,
    report_changes: dict[str, dict[str, Any]] | None = None,
) -> RunFiles:
    """The files of ``run_tag`` in ``project``, each with the scans that brought,
    changed or failed it. The scans of every workflow's run with
    that tag are read together, oldest first. ``report_changes`` maps a
    report's location to its ``last_change``."""
    workflow_ids = {str(wf.get("_id") or wf.get("id")) for wf in project.get("workflows") or []}
    tags = {
        str(dc.get("_id") or dc.get("id")): dc.get("data_collection_tag")
        for wf in project.get("workflows") or []
        for dc in wf.get("data_collections") or []
    }
    docs = [
        r
        for r in run_docs
        if r.get("run_tag") == run_tag and str(r.get("workflow_id")) in workflow_ids
    ]
    scans = sorted(
        (s for r in docs for s in r.get("scan_results") or [] if isinstance(s, dict)),
        key=lambda s: str(s.get("scan_time") or ""),
    )
    per_scan = [
        (_ids(s, "new_files"), _ids(s, "changed_files"), _ids(s, "other_failure_files"))
        for s in scans
    ]
    files: list[RunFile] = []
    truncated = False
    for doc in file_docs:
        if len(files) >= MAX_RUN_FILES:
            truncated = True
            break
        fid = str(doc.get("_id"))
        dc_id = str(doc.get("data_collection_id") or "")
        added = next((i for i, ids in enumerate(per_scan) if fid in ids[0]), None)
        location = str(doc.get("file_location") or "")
        report_change = (report_changes or {}).get(location)
        changes = [
            RunFileChange(scan=i, size=change.get("size"), modified=change.get("modified"))
            for i, s in enumerate(scans)
            if (change := (s.get("file_changes") or {}).get(fid))
        ]
        files.append(
            RunFile(
                id=fid,
                dc_id=dc_id,
                dc_tag=tags.get(dc_id),
                filename=str(doc.get("filename") or ""),
                location=location,
                size=doc.get("filesize"),
                modified=doc.get("modification_time"),
                registered=doc.get("registration_time"),
                added_in=added,
                changed_in=[i for i, ids in enumerate(per_scan) if fid in ids[1]],
                failed_in=[i for i, ids in enumerate(per_scan) if fid in ids[2]],
                changes=changes,
                report_change=RunReportChange(**report_change) if report_change else None,
            )
        )
    files.sort(key=lambda f: (f.dc_tag or "", f.filename, f.location))
    return RunFiles(
        run_tag=run_tag,
        scans=[
            RunScanFiles(scan_time=s.get("scan_time"), new=len(n), changed=len(c), failed=len(f))
            for s, (n, c, f) in zip(scans, per_scan, strict=True)
        ],
        files=files,
        truncated=truncated,
    )


def _report_changes(project: dict[str, Any], locations: list[str]) -> dict[str, dict[str, Any]]:
    """The ``last_change`` of the MultiQC reports read from these locations."""
    from depictio.api.v1.db import multiqc_collection

    dc_ids = [
        str(dc.get("_id") or dc.get("id"))
        for wf in project.get("workflows") or []
        for dc in wf.get("data_collections") or []
        if str(((dc.get("config") or {}).get("type") or "")).lower() == "multiqc"
    ]
    if not dc_ids or not locations:
        return {}
    return {
        str(doc["original_file_path"]): doc["last_change"]
        for doc in multiqc_collection.find(
            {
                "data_collection_id": {"$in": dc_ids},
                "original_file_path": {"$in": locations},
                "last_change": {"$ne": None},
            },
            {"original_file_path": 1, "last_change": 1},
        )
        if doc.get("last_change")
    }


def run_files(project: dict[str, Any], run_tag: str) -> RunFiles:
    from depictio.api.v1.db import files_collection

    ids = [ObjectId(wf["_id"]) for wf in project.get("workflows") or [] if wf.get("_id")]
    docs = (
        list(runs_collection.find({"workflow_id": {"$in": ids}, "run_tag": run_tag})) if ids else []
    )
    run_ids = [d["_id"] for d in docs]
    file_docs = (
        list(
            files_collection.find(
                {"run_id": {"$in": run_ids + [str(i) for i in run_ids]}},
                {"permissions": 0},
            ).limit(MAX_RUN_FILES + 1)
        )
        if run_ids
        else []
    )
    locations = [str(d.get("file_location") or "") for d in file_docs]
    return build_run_files(project, docs, file_docs, run_tag, _report_changes(project, locations))
