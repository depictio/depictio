"""Server-side manifest ingestion into an existing project (RFC remote-data, phase 2).

``POST /projects/ingest_manifest`` maps a Data Manifest's ``type`` values onto
the project's data-collection tags, switches each matched DC to
``scan.mode: manifest``, and runs scan + process in-process through the same
CLI helpers as the create-DC flows. The result is a per-DC ingestion report.

Sequencing per DC (mirrors ``_push_workflow_and_ingest``): the new scan config
is persisted *before* the helpers run — the helpers' API callbacks read the DC
from the project document — and reverted for any DC whose scan or process
fails, so a failed ingestion never leaves a manifest scan config pointing at
data that was never materialized.

Fan-out is sequential for now; Celery parallelism is a phase-4 concern
(the report shape is already per-DC so the switch is internal).
"""

import copy
import os
import tempfile

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.db import projects_collection
from depictio.api.v1.remote_fetch import (
    RemoteURLRejected,
    bounded_download,
    validate_remote_url,
)
from depictio.models.logging import logger
from depictio.models.models.manifest import DataManifest

# Manifests are indexes, not data — cap them well below the data-file cap.
MANIFEST_MAX_BYTES = 50 * 1024 * 1024


class IngestManifestRequest(BaseModel):
    """Body of POST /projects/ingest_manifest."""

    project_id: str
    manifest_url: str
    # Column overrides for non-canonical manifests (see ScanManifest).
    id_field: str = "id"
    url_field: str = "url"
    type_field: str = "type"
    run_field: str | None = "run"
    # Plan-only: report the type→tag mapping without touching the project.
    dry_run: bool = False


class ManifestIngestDCResult(BaseModel):
    data_collection_tag: str
    data_collection_id: str
    entries: int
    status: str  # "ingested" | "failed" | "planned" (dry_run)
    message: str | None = None


class ManifestIngestReport(BaseModel):
    project_id: str
    manifest_url: str
    manifest_entries: int
    matched: list[ManifestIngestDCResult] = Field(default_factory=list)
    # Manifest types with no matching DC tag — data the project can't hold yet.
    unmatched_manifest_types: list[str] = Field(default_factory=list)
    # Project DC tags the manifest says nothing about — left untouched.
    unmatched_dc_tags: list[str] = Field(default_factory=list)
    dry_run: bool = False
    success: bool = False


def _fetch_and_parse_manifest(manifest_url: str, field_map: dict[str, str]) -> DataManifest:
    """Download the manifest through the SSRF gateway and parse it.

    Server context only accepts remote manifests (https; s3 is tracked in the
    RFC) — local paths are a CLI affordance. Format is decided by extension
    then content sniffing, same as the CLI's ``fetch_manifest``.
    """
    tmp = tempfile.NamedTemporaryFile(prefix="depictio_manifest_", delete=False)
    tmp.close()
    try:
        bounded_download(manifest_url, tmp.name, max_bytes=MANIFEST_MAX_BYTES)
        with open(tmp.name, encoding="utf-8") as fh:
            text = fh.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    stripped = text.lstrip()
    looks_json = manifest_url.split("?", 1)[0].endswith(".json") or stripped.startswith(("{", "["))
    if looks_json:
        return DataManifest.from_json(text, source=manifest_url, field_map=field_map)
    return DataManifest.from_csv(text, source=manifest_url, field_map=field_map)


def _live_dc_index(project_dict: dict) -> dict[str, tuple[int, int]]:
    """{dc_tag: (workflow_index, dc_index)} across all of the project's workflows."""
    index: dict[str, tuple[int, int]] = {}
    for wf_i, wf in enumerate(project_dict.get("workflows", []) or []):
        for dc_i, dc in enumerate(wf.get("data_collections", []) or []):
            tag = dc.get("data_collection_tag")
            if tag and tag not in index:
                index[tag] = (wf_i, dc_i)
    return index


def _run_dc_ingest(workflow_dict: dict, dc_id: str, current_user) -> tuple[bool, str | None]:
    """Scan + process one DC through the CLI helpers. Returns (ok, error_message).

    Synchronous on purpose — the helpers use a sync httpx client back into
    this same FastAPI process (see ``_push_workflow_and_ingest``).
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _build_cli_config_for_user,
    )
    from depictio.cli.cli.utils.helpers import process_data_collection_helper
    from depictio.models.models.workflows import Workflow

    try:
        # Parse a copy: pydantic's before-validators mutate nested input dicts
        # in place (e.g. replacing dc_specific_properties with model
        # instances), and the caller still $sets workflow_dict back to Mongo.
        workflow = Workflow(**copy.deepcopy(workflow_dict))
    except Exception as exc:
        return False, f"Could not parse workflow: {exc}"

    cli_config = _build_cli_config_for_user(current_user)

    scan_result = process_data_collection_helper(
        CLI_config=cli_config, wf=workflow, dc_id=dc_id, mode="scan"
    )
    if (scan_result or {}).get("result") != "success":
        return False, f"Scan failed: {(scan_result or {}).get('message', 'unknown error')}"

    process_result = process_data_collection_helper(
        CLI_config=cli_config,
        wf=workflow,
        dc_id=dc_id,
        mode="process",
        command_parameters={"overwrite": True},
    )
    if (process_result or {}).get("result") != "success":
        return False, f"Processing failed: {(process_result or {}).get('message', 'unknown error')}"
    return True, None


def _ingest_manifest_into_project(
    *,
    project_id: str,
    manifest_url: str,
    current_user,
    id_field: str = "id",
    url_field: str = "url",
    type_field: str = "type",
    run_field: str | None = "run",
    dry_run: bool = False,
) -> ManifestIngestReport:
    """Map a manifest onto an existing project's DC tags and ingest each match.

    Synchronous on purpose (sync httpx callbacks in the CLI helpers) — callers
    must dispatch via ``asyncio.to_thread``.
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _user_can_edit_project,
    )

    # Gateway rejection must precede any database access.
    try:
        validate_remote_url(manifest_url)
    except RemoteURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if manifest_url.startswith("s3://"):
        raise HTTPException(
            status_code=400,
            detail="s3:// manifest locations are not supported yet — serve the manifest over https.",
        )

    try:
        project_oid = ObjectId(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid project_id: {exc}")

    project_dict = projects_collection.find_one({"_id": project_oid})
    if not project_dict:
        raise HTTPException(status_code=404, detail="Project not found.")
    if not _user_can_edit_project(
        project_dict, current_user.id, getattr(current_user, "is_admin", False)
    ):
        raise HTTPException(
            status_code=403, detail="You don't have edit permission on this project."
        )

    field_map = {"id": id_field, "type": type_field, "url": url_field}
    if run_field:
        field_map["run"] = run_field
    try:
        manifest = _fetch_and_parse_manifest(manifest_url, field_map)
    except RemoteURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse manifest: {exc}")
    if not manifest.entries:
        raise HTTPException(status_code=422, detail="Manifest contains no entries.")

    live = _live_dc_index(project_dict)
    manifest_types = manifest.types()
    matched_tags = sorted(tag for tag in live if tag in manifest_types)
    if not matched_tags:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No manifest type matches a data collection tag. "
                f"Manifest types: {sorted(manifest_types)}; project tags: {sorted(live)}."
            ),
        )

    report = ManifestIngestReport(
        project_id=str(project_oid),
        manifest_url=manifest_url,
        manifest_entries=len(manifest.entries),
        unmatched_manifest_types=sorted(manifest_types - set(matched_tags)),
        unmatched_dc_tags=sorted(set(live) - set(matched_tags)),
        dry_run=dry_run,
    )

    # ScanManifest is imported here with the rest of the model graph — keep
    # API import-time cheap, same convention as the datacollections helpers.
    from depictio.models.models.data_collections import ScanManifest

    workflows = copy.deepcopy(project_dict.get("workflows", []) or [])
    original_scans: dict[str, dict] = {}  # tag -> pre-ingest scan dict
    for tag in matched_tags:
        wf_i, dc_i = live[tag]
        dc_dict = workflows[wf_i]["data_collections"][dc_i]
        entry_count = len(manifest.entries_for_type(tag))

        if dry_run:
            report.matched.append(
                ManifestIngestDCResult(
                    data_collection_tag=tag,
                    data_collection_id=str(dc_dict.get("_id") or dc_dict.get("id") or ""),
                    entries=entry_count,
                    status="planned",
                )
            )
            continue

        scan_manifest = ScanManifest(
            manifest_url=manifest_url,
            manifest_type=tag,
            id_field=id_field,
            url_field=url_field,
            type_field=type_field,
            run_field=run_field,
        )
        original_scans[tag] = copy.deepcopy((dc_dict.get("config") or {}).get("scan"))
        dc_dict.setdefault("config", {})["scan"] = {
            "mode": "manifest",
            "scan_parameters": scan_manifest.model_dump(),
        }

    if dry_run:
        report.success = True
        return report

    # Persist the manifest scan configs first — the helpers' API callbacks
    # read the DC config from the project document.
    projects_collection.update_one({"_id": project_oid}, {"$set": {"workflows": workflows}})

    all_ok = True
    for tag in matched_tags:
        wf_i, dc_i = live[tag]
        dc_dict = workflows[wf_i]["data_collections"][dc_i]
        dc_id = str(dc_dict.get("_id") or dc_dict.get("id") or "")
        entry_count = len(manifest.entries_for_type(tag))
        try:
            ok, message = _run_dc_ingest(workflows[wf_i], dc_id, current_user)
        except HTTPException:
            raise
        except Exception as exc:  # helper crash — treat as a per-DC failure
            logger.error(f"Manifest ingest crashed for DC '{tag}': {exc}")
            ok, message = False, str(exc)
        if not ok:
            all_ok = False
            # Revert this DC to its pre-ingest scan config so a failed run
            # never leaves a manifest config with no data behind it.
            dc_dict["config"]["scan"] = original_scans.get(tag)
        report.matched.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=dc_id,
                entries=entry_count,
                status="ingested" if ok else "failed",
                message=message,
            )
        )

    if not all_ok:
        projects_collection.update_one({"_id": project_oid}, {"$set": {"workflows": workflows}})

    report.success = all_ok
    return report
