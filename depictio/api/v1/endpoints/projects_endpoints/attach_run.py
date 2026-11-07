"""Add another run (an output folder of the same pipeline) to an existing project.

``POST /projects/{project_id}/attach_run`` is the browser twin of
``depictio ingest --attach-run`` (``cli/commands/run.py``: ``merge_run_locations``
and ``attach_run_to_project``). The new folder is checked against the project's
template, previewed with the engine ``from_run`` uses, recorded on the project,
and the project's ingestion is handed to Celery through the same
``_dispatch_refresh_tasks`` machinery. The caller polls
``GET /projects/refresh_manifest/{run_id}``.

Which projects can take a second run
------------------------------------
Only a project made from a template (``template_origin`` set) and only where
the scan of its data collections can walk several roots. That is the
``recursive`` scan: it walks ``workflow.data_location.locations``, so the new
folder is appended there (and to ``attached_locations``, so a refresh keeps it)
exactly as the CLI does.

* Works: a project made from a run folder on the server's disk
  (``depictio local``), whose collections are ``recursive`` scans, with any
  ``single`` / ``url`` / ``manifest`` / recipe collection next to them. A
  ``single`` collection keeps pointing at its original file (nothing here
  rewrites a scan), which is what the CLI preserves explicitly.
* Does NOT work (422 ``cannot_attach``): a project made from an ``s3://`` run
  folder. Its collections are ``s3_prefix`` scans, and a prefix scan has one
  ``prefix`` (``ScanS3Prefix``) and ignores ``data_location.locations``, so a
  second prefix cannot be expressed without a model change. A new folder on the
  local disk cannot be attached to such a project either, and an ``s3://`` folder
  cannot be attached to a ``recursive`` project (a disk walk cannot list it).

No data collection is created here, so there is no ``DataOrigin`` to stamp; if a
future version creates one, it carries ``origin=DataOrigin(kind="run",
location=data_root)``.

Logic duplicated from the CLI (not imported, the API never imports
``cli.commands``): ``_distinct`` / ``_record_location`` mirror
``merge_run_locations``; ``_flat_clash`` mirrors ``scan.flat_run_tag_clash``.
"""

import os
from typing import Any, Literal

from bson import ObjectId
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from depictio.api.v1.db import projects_collection, runs_collection
from depictio.api.v1.endpoints.projects_endpoints.from_run import (
    DetectedTemplate,
    _build_data_root,
    _detect_run,
    _request_read_config,
    _scan_modes,
    describe_detection,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import _dispatch_refresh_tasks
from depictio.api.v1.endpoints.projects_endpoints.publish_lock import assert_project_unlocked
from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
    ProjectStorageConfigIn,
    RunStorageIn,
    project_storage_for,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.logging import logger
from depictio.models.s3_access import S3AccessError, is_s3_url

MatchKind = Literal["exact", "closest", "none", "other_pipeline"]


class AttachRunRequest(BaseModel):
    """Body of POST /projects/{project_id}/attach_run."""

    # The new run: an s3:// prefix or, when local folders are on, a path on disk
    # (same rules as ``FromRunRequest.data_root``).
    data_root: str
    # Plan only (the default): report, write nothing, dispatch nothing.
    dry_run: bool = True
    # A private bucket's keys for an s3:// data_root. The project's own saved
    # storage settings apply when this is absent.
    storage: RunStorageIn | None = None


class AttachRunDC(BaseModel):
    """What one data collection would find in the new folder."""

    tag: str
    matched: int = 0
    status: str = "ok"


class AttachRunReport(BaseModel):
    project_id: str
    # The new folder as resolved (a local path is its real path).
    data_root: str
    # The project's template.
    template_id: str
    # The pipeline and version recognised in the new folder, None when unrecognised.
    detected: DetectedTemplate | None = None
    match: MatchKind = "none"
    new_runs: list[str] = Field(default_factory=list)
    existing_runs: list[str] = Field(default_factory=list)
    data_collections: list[AttachRunDC] = Field(default_factory=list)
    # Ingestion to poll via GET /projects/refresh_manifest/{run_id}; None on a dry run.
    run_id: str | None = None
    dry_run: bool = True
    warnings: list[str] = Field(default_factory=list)


# ── pure helpers ─────────────────────────────────────────────────────────────


def _real(location: str) -> str:
    return location if "://" in location else os.path.realpath(location)


def _pipeline_of(template_id: str) -> str:
    """``nf-core/ampliseq`` of ``nf-core/ampliseq/2.16.0``."""
    return template_id.rsplit("/", 1)[0] if "/" in template_id else template_id


def classify_match(project_template_id: str, detected_template_id: str | None) -> MatchKind:
    """How the template recognised in the new folder relates to the project's."""
    if not detected_template_id:
        return "none"
    if detected_template_id == project_template_id:
        return "exact"
    if _pipeline_of(detected_template_id) == _pipeline_of(project_template_id):
        return "closest"
    return "other_pipeline"


def _flat_clash(structure: str | None, locations: list[str]) -> str | None:
    """Why two locations of a flat workflow would be one run (same directory name)."""
    if structure != "flat":
        return None
    first_by_tag: dict[str, str] = {}
    for location in locations:
        tag = os.path.basename(os.path.normpath(location))
        first = first_by_tag.setdefault(tag, location)
        if _real(first) != _real(location):
            return (
                f"{first} and {location} would both be run '{tag}': a flat workflow names "
                "each run after its directory. Rename one of the directories."
            )
    return None


def _scan_of(dc: dict[str, Any]) -> dict[str, Any]:
    return (dc.get("config") or {}).get("scan") or {}


def attach_targets(project: dict[str, Any]) -> tuple[list[int], list[str]]:
    """``(indexes of the workflows that can take a second run, tags that block it)``.

    A workflow takes one when at least one of its data collections is a
    ``recursive`` scan. A blocker is an ``s3_prefix`` collection reading under
    the project's own run folder or locations: one prefix, no second root.
    """
    origin_root = str((project.get("template_origin") or {}).get("data_root") or "")
    indexes: list[int] = []
    blockers: list[str] = []
    for index, workflow in enumerate(project.get("workflows") or []):
        location = workflow.get("data_location") or {}
        bases = [b.rstrip("/") for b in [origin_root, *(location.get("locations") or [])] if b]
        recursive = False
        for dc in workflow.get("data_collections") or []:
            scan = _scan_of(dc)
            mode = str(scan.get("mode") or "").lower()
            if mode == "recursive":
                recursive = True
            elif mode == "s3_prefix":
                prefix = str((scan.get("scan_parameters") or {}).get("prefix") or "")
                if any(prefix.rstrip("/").startswith(b) for b in bases if "://" in b):
                    blockers.append(str(dc.get("data_collection_tag") or "?"))
        if recursive:
            indexes.append(index)
    return indexes, blockers


def merged_locations(
    locations: list[str], attached: list[str], new_location: str
) -> tuple[list[str], list[str]]:
    """The workflow's locations and attached record with ``new_location`` added.

    Existing locations are all kept, in order; the new one goes last (as in
    ``merge_run_locations``).
    """
    return [*locations, new_location], [*attached, new_location]


def _existing_runs(project: dict[str, Any], indexes: list[int]) -> list[str]:
    """Run tags the project holds: registered runs, plus the names of flat locations."""
    tags: list[str] = []
    workflows = project.get("workflows") or []
    ids: list[Any] = []
    for index in indexes:
        workflow = workflows[index]
        wf_id = workflow.get("_id") or workflow.get("id")
        if wf_id:
            ids += [wf_id, str(wf_id)]
        location = workflow.get("data_location") or {}
        if location.get("structure") == "flat":
            tags += [
                os.path.basename(os.path.normpath(loc)) for loc in location.get("locations") or []
            ]
    if ids:
        tags += [
            str(run.get("run_tag")) for run in runs_collection.find({"workflow_id": {"$in": ids}})
        ]
    return sorted({tag for tag in tags if tag})


def _preview_variables(origin: dict[str, Any]) -> dict[str, str]:
    """The project's template variables that do not point into its first run folder."""
    old_root = str(origin.get("data_root") or "")
    variables = origin.get("variables") or {}
    return {
        name: str(value)
        for name, value in variables.items()
        if name != "DATA_ROOT" and not (old_root and old_root in str(value))
    }


def _storage_for_request(
    payload: AttachRunRequest, project_id: str
) -> tuple[ProjectStorageConfigIn | None, Any]:
    """Read config of the new folder: typed-in storage, else the project's saved one."""
    settings_in, reads = _request_read_config(payload.data_root, payload.storage)
    if settings_in is None and is_s3_url(payload.data_root):
        from depictio.api.v1.endpoints.projects_endpoints.from_run import _run_folder_read_config

        saved = project_storage_for(project_id)
        if saved is not None:
            reads = _run_folder_read_config(saved)
    return settings_in, reads


# ── the work (sync, run off the event loop) ──────────────────────────────────


def _attach_run_sync(
    project_id: str, payload: AttachRunRequest, request: Request | None, current_user
) -> AttachRunReport:
    project = projects_collection.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    origin = project.get("template_origin") or {}
    template_id = str(origin.get("template_id") or "")
    if not template_id:
        raise CodedHTTPException(
            422,
            "Only a project made from a pipeline template can take another run.",
            "not_a_pipeline_project",
        )

    indexes, blockers = attach_targets(project)
    if blockers or not indexes:
        why = (
            f"Data collection(s) {', '.join(sorted(set(blockers)))} read one s3:// prefix, "
            "and a prefix scan cannot take a second run folder."
            if blockers
            else "No data collection of this project scans a run folder, so a new "
            "run would never be read."
        )
        raise CodedHTTPException(
            422,
            f"{why} Only projects made from a folder on the server's disk can take another run.",
            "cannot_attach",
        )
    if is_s3_url(payload.data_root):
        raise CodedHTTPException(
            422,
            "This project scans folders on the server's disk, so the new run must be one "
            "too, not an s3:// prefix.",
            "cannot_attach",
        )

    _storage, reads = _storage_for_request(payload, project_id)
    root = _build_data_root(payload.data_root, reads, request=request, current_user=current_user)
    new_location = root.location

    workflows = project.get("workflows") or []
    for index in indexes:
        data_location = workflows[index].get("data_location") or {}
        held = [
            *(data_location.get("locations") or []),
            *(data_location.get("attached_locations") or []),
        ]
        if any(_real(loc) == _real(new_location) for loc in held):
            raise CodedHTTPException(
                409, f"{new_location} is already part of this project.", "already_attached"
            )

    try:
        detected_id, info = _detect_run(root)
    except S3AccessError:
        raise
    detected = describe_detection(detected_id, info)
    warnings: list[str] = []
    match = classify_match(template_id, detected_id)
    if match == "none" and info is not None and info.pipeline_name:
        if _pipeline_of(template_id) != info.pipeline_name:
            match = "other_pipeline"
    if match == "other_pipeline":
        found = detected.pipeline if detected and detected.pipeline else detected_id
        raise CodedHTTPException(
            422,
            f"This folder is a '{found}' run, but the project was made from "
            f"'{_pipeline_of(template_id)}'. Attach a run of the same pipeline.",
            "other_pipeline",
        )
    if match == "closest":
        warnings.append(
            f"The folder is another version of the pipeline ({detected_id}); the project "
            f"keeps reading it with its own template ({template_id})."
        )
    if match == "none":
        warnings.append(
            "The pipeline that produced this folder was not recognised; it is judged by "
            "what the project's data collections find in it."
        )

    from depictio.cli.cli.utils.template_preview import preview_data_root

    try:
        preview = preview_data_root(
            template_id=template_id,
            data_root=root,
            variables=_preview_variables(origin) or None,
            CLI_config=reads,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template not found: {exc}")
    except S3AccessError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Data root preview failed: {exc}")

    rows = {row.tag: row for row in preview.data_collections}
    # A single / url collection reads its original file, never the new run: it
    # is "kept", not "ok", so the report does not promise it the new files.
    singles = {
        tag for tag, row in rows.items() if row.mode and str(row.mode).lower() in ("single", "url")
    }
    report = AttachRunReport(
        project_id=project_id,
        data_root=new_location,
        template_id=template_id,
        detected=detected,
        match=match,
        data_collections=[
            AttachRunDC(
                tag=row.tag,
                matched=row.matched,
                status="kept" if row.tag in singles and row.status == "ok" else row.status,
            )
            for row in preview.data_collections
        ],
        dry_run=payload.dry_run,
        warnings=warnings,
    )
    if match == "none" and not any(row.matched for row in rows.values()):
        raise CodedHTTPException(
            422,
            "No data collection of the project finds anything in this folder, and its "
            "pipeline was not recognised. It does not look like a run of this pipeline.",
            "other_pipeline",
        )

    existing = _existing_runs(project, indexes)
    structure = (workflows[indexes[0]].get("data_location") or {}).get("structure")
    found = (
        list(preview.detected_runs)
        if structure == "sequencing-runs"
        else [os.path.basename(os.path.normpath(new_location))]
    )
    report.existing_runs = existing
    report.new_runs = [run for run in found if run not in existing]

    for index in indexes:
        data_location = workflows[index].get("data_location") or {}
        locations, _attached = merged_locations(
            list(data_location.get("locations") or []), [], new_location
        )
        clash = _flat_clash(data_location.get("structure"), locations)
        if clash:
            raise CodedHTTPException(422, clash, "run_name_clash")

    if payload.dry_run:
        return report

    # ---- write: record the location on each real workflow, nothing else ----
    updates: dict[str, Any] = {}
    for index in indexes:
        data_location = workflows[index].get("data_location") or {}
        locations, attached = merged_locations(
            list(data_location.get("locations") or []),
            list(data_location.get("attached_locations") or []),
            new_location,
        )
        updates[f"workflows.{index}.data_location.locations"] = locations
        updates[f"workflows.{index}.data_location.attached_locations"] = attached
    projects_collection.update_one({"_id": project["_id"]}, {"$set": updates})
    stored = projects_collection.find_one({"_id": project["_id"]}) or project

    # Dispatch what can ingest from the new folder; a single / url collection is
    # always re-run (it reads its original file and its dependants need the rebuild).
    to_dispatch: list[tuple[str, str, int, int]] = []
    for wf_index, workflow in enumerate(stored.get("workflows") or []):
        for dc in workflow.get("data_collections") or []:
            tag = str(dc.get("data_collection_tag") or "")
            row = rows.get(tag)
            mode = str(_scan_of(dc).get("mode") or "").lower()
            if row is not None and row.status in ("missing", "pruned") and mode != "single":
                continue
            dc_id = str(dc.get("_id") or dc.get("id") or "")
            to_dispatch.append((tag, dc_id, wf_index, row.matched if row else 0))
    if not to_dispatch:
        report.warnings.append(
            "No data collection could ingest from this folder; nothing was started."
        )
        return report

    # ``command="from_run"``: the only run command besides refresh_manifest that
    # GET /projects/refresh_manifest/{run_id} serves.
    run_id, all_dispatched, _results = _dispatch_refresh_tasks(
        project_dict=stored,
        to_dispatch=to_dispatch,
        current_user=current_user,
        preflight_failed=[],
        preflight_skipped=[],
        command="from_run",
        scan_modes=_scan_modes(stored),
        data_root=new_location,
    )
    report.run_id = run_id
    if not all_dispatched:
        report.warnings.append("Some ingestion tasks could not be dispatched; see the run.")
        logger.warning(f"attach_run: partial dispatch for project {project_id}")
    return report


# ── the handler ──────────────────────────────────────────────────────────────


async def attach_run(
    project_id: str,
    payload: AttachRunRequest,
    request: Request,
    current_user=Depends(get_user_or_anonymous),
) -> Any:
    """Attach another run folder of the same pipeline to this project.

    ``dry_run`` (the default) reports what the folder holds and writes nothing.
    A real call records the folder on the project and starts its ingestion;
    poll ``run_id`` via ``GET /projects/refresh_manifest/{run_id}``. Errors
    answer ``{detail, code}``: ``not_a_pipeline_project``, ``other_pipeline``,
    ``cannot_attach`` (422), ``already_attached`` (409), a published project 409.
    """
    # routes.py imports this module, so its helpers are imported at call time.
    from depictio.api.v1.endpoints.projects_endpoints import routes
    from depictio.api.v1.endpoints.projects_endpoints.utils import _async_get_project_from_id

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    routes._reject_non_admin_in_public_mode(current_user, "Attaching a run")
    if not ObjectId.is_valid(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    visible = _async_get_project_from_id(ObjectId(project_id), current_user, projects_collection)
    if not routes._may_trigger_ingestion(visible, current_user):
        raise HTTPException(status_code=403, detail="Editor access is required to attach a run.")
    assert_project_unlocked(project_id)
    await routes._ensure_cli_token_unless_dry_run(current_user, payload.dry_run)
    return await routes._run_coded_off_loop(
        _attach_run_sync, project_id, payload, request, current_user
    )


__all__ = ["AttachRunReport", "AttachRunRequest", "attach_run"]
