"""Manifest-driven project creation (RFC remote-data, phase 3).

``POST /projects/from_manifest`` orchestrates the full zero-install flow:
fetch a Data Manifest through the SSRF gateway, resolve a manifest-driven
template server-side (``resolve_template`` with ``data_root=None``), check the
manifest's ``type`` coverage against the template's DC tags, create the
project, ingest each manifest-backed DC through the same CLI helpers as
``/projects/ingest_manifest``, and import the template's dashboards in-process
(no HTTP-to-self). The result is one report the UI can act on — including the
dashboard ids to redirect to.

Synchronous throughout (the CLI helpers use sync httpx back into this same
FastAPI process) — the route dispatches via ``asyncio.to_thread``.
"""

import copy
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.db import projects_collection
from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import (
    ManifestIngestDCResult,
    _fetch_and_parse_manifest,
    _run_dc_ingest,
)
from depictio.api.v1.remote_fetch import RemoteURLRejected, validate_remote_url
from depictio.models.logging import logger


class FromManifestRequest(BaseModel):
    """Body of POST /projects/from_manifest."""

    manifest_url: str
    template_id: str
    project_name: str | None = None
    # Extra template variables ({VAR} placeholders beyond MANIFEST_URL).
    variables: dict[str, str] = Field(default_factory=dict)
    # Plan-only: resolve + coverage-check without creating anything.
    dry_run: bool = False


class DashboardImportResult(BaseModel):
    path: str
    success: bool
    dashboard_id: str | None = None
    title: str | None = None
    error: str | None = None


class FromManifestReport(BaseModel):
    project_id: str | None = None
    project_name: str
    template_id: str
    manifest_url: str
    manifest_entries: int
    ingestion: list[ManifestIngestDCResult] = Field(default_factory=list)
    dashboards: list[DashboardImportResult] = Field(default_factory=list)
    # Manifest types no template DC consumes — data the template can't show.
    unmatched_manifest_types: list[str] = Field(default_factory=list)
    # Optional DCs pruned because the manifest has no rows of their type.
    pruned_optional_dcs: list[str] = Field(default_factory=list)
    dry_run: bool = False
    success: bool = False


def _manifest_dcs(config: dict[str, Any]) -> list[tuple[dict, dict]]:
    """[(dc_dict, scan_parameters)] for every manifest-mode DC in the config."""
    found: list[tuple[dict, dict]] = []
    for workflow in config.get("workflows", []) or []:
        for dc in workflow.get("data_collections", []) or []:
            scan = (dc.get("config") or {}).get("scan") or {}
            if str(scan.get("mode", "")).lower() == "manifest":
                found.append((dc, scan.get("scan_parameters") or {}))
    return found


def _prune_dcs(config: dict[str, Any], tags: set[str]) -> None:
    """Drop the given DC tags from all workflows, and links referencing them."""
    for workflow in config.get("workflows", []) or []:
        workflow["data_collections"] = [
            dc
            for dc in workflow.get("data_collections", []) or []
            if dc.get("data_collection_tag") not in tags
        ]
    if config.get("links"):
        config["links"] = [
            link
            for link in config["links"]
            if link.get("source_dc_tag") not in tags and link.get("target_dc_tag") not in tags
        ]


def _create_project_from_manifest(
    *,
    manifest_url: str,
    template_id: str,
    current_user,
    project_name: str | None = None,
    variables: dict[str, str] | None = None,
    dry_run: bool = False,
) -> FromManifestReport:
    """The full manifest → project + dashboards flow. Sync — call via to_thread."""
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

    # Resolve the template server-side. resolve_template is import-light CLI
    # code (yaml + models); data_root=None skips every filesystem-local step.
    from depictio.cli.cli.utils.templates import resolve_template, substitute_template_variables

    extra_vars = {**(variables or {}), "MANIFEST_URL": manifest_url}
    try:
        resolved_config, _meta, _origin, dashboard_paths, resolved_vars = resolve_template(
            template_id=template_id,
            data_root=None,
            project_name=project_name,
            extra_vars=extra_vars,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Template resolution failed: {exc}")

    manifest_dcs = _manifest_dcs(resolved_config)
    if not manifest_dcs:
        raise HTTPException(
            status_code=422,
            detail=f"Template '{template_id}' has no manifest-mode data collection — "
            "it cannot be instantiated from a manifest.",
        )

    try:
        manifest = _fetch_and_parse_manifest(
            manifest_url, field_map={"id": "id", "type": "type", "url": "url", "run": "run"}
        )
    except RemoteURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse manifest: {exc}")
    if not manifest.entries:
        raise HTTPException(status_code=422, detail="Manifest contains no entries.")

    # Coverage check: every required manifest DC needs ≥1 row of its type;
    # optional ones with no rows are pruned (same semantics as template
    # conditionals — recorded so the report explains the gap).
    consumed_types: set[str] = set()
    pruned: set[str] = set()
    planned: list[ManifestIngestDCResult] = []
    for dc, scan_params in manifest_dcs:
        tag = dc.get("data_collection_tag", "")
        manifest_type = scan_params.get("manifest_type", tag)
        consumed_types.add(manifest_type)
        entry_count = len(manifest.entries_for_type(manifest_type))
        if entry_count == 0:
            if dc.get("optional"):
                pruned.add(tag)
                continue
            raise HTTPException(
                status_code=422,
                detail=f"Manifest has no entries of type '{manifest_type}' required by "
                f"data collection '{tag}'. Manifest types: {sorted(manifest.types())}.",
            )
        planned.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id="",
                entries=entry_count,
                status="planned",
            )
        )
    if pruned:
        _prune_dcs(resolved_config, pruned)

    report = FromManifestReport(
        project_name=resolved_config.get("name", ""),
        template_id=template_id,
        manifest_url=manifest_url,
        manifest_entries=len(manifest.entries),
        unmatched_manifest_types=sorted(manifest.types() - consumed_types),
        pruned_optional_dcs=sorted(pruned),
        dry_run=dry_run,
    )

    if dry_run:
        report.ingestion = planned
        report.success = True
        return report

    # Create the project — same identity/uniqueness rules as POST /projects/create.
    from depictio.api.v1.endpoints.projects_endpoints.utils import (
        validate_workflow_uniqueness_in_project,
    )
    from depictio.models.models.projects import Project
    from depictio.models.timestamps import utc_now_str

    if projects_collection.find_one({"name": resolved_config["name"]}):
        raise HTTPException(
            status_code=409,
            detail=f"A project named '{resolved_config['name']}' already exists — "
            "pass a different project_name.",
        )

    project_config = copy.deepcopy(resolved_config)
    project_config["permissions"] = {
        "owners": [{"_id": ObjectId(current_user.id), "email": current_user.email}],
        "editors": [],
        "viewers": [],
    }
    try:
        project = Project(**project_config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Resolved project config invalid: {exc}")
    validate_workflow_uniqueness_in_project(project)

    create_payload = project.mongo()
    create_payload["registration_time"] = utc_now_str()
    create_payload["last_modified"] = create_payload["registration_time"]
    projects_collection.insert_one(create_payload)
    project_oid = create_payload["_id"]
    report.project_id = str(project_oid)

    # Ingest each manifest DC through the CLI helpers, reading the workflow
    # dicts back from the stored document (the helpers' API callbacks resolve
    # the DC config from the project document, ids included).
    stored = projects_collection.find_one({"_id": project_oid}) or {}
    all_ok = True
    for workflow_dict in stored.get("workflows", []) or []:
        for dc_dict in workflow_dict.get("data_collections", []) or []:
            scan = (dc_dict.get("config") or {}).get("scan") or {}
            if str(scan.get("mode", "")).lower() != "manifest":
                continue
            tag = dc_dict.get("data_collection_tag", "")
            dc_id = str(dc_dict.get("_id") or dc_dict.get("id") or "")
            manifest_type = (scan.get("scan_parameters") or {}).get("manifest_type", tag)
            entry_count = len(manifest.entries_for_type(manifest_type))
            try:
                ok, message = _run_dc_ingest(workflow_dict, dc_id, current_user)
            except HTTPException:
                raise
            except Exception as exc:  # helper crash — treat as a per-DC failure
                logger.error(f"from_manifest ingest crashed for DC '{tag}': {exc}")
                ok, message = False, str(exc)
            all_ok = all_ok and ok
            report.ingestion.append(
                ManifestIngestDCResult(
                    data_collection_tag=tag,
                    data_collection_id=dc_id,
                    entries=entry_count,
                    status="ingested" if ok else "failed",
                    message=message,
                )
            )

    # Import the template's dashboards in-process. The shared import handler
    # does the tag → id binding and drops components whose optional DC ended
    # up empty (self-adapting import).
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        import_dashboard_yaml_content,
    )

    for path in dashboard_paths:
        entry = DashboardImportResult(path=str(path), success=False)
        try:
            yaml_text = path.read_text(encoding="utf-8")
            if resolved_vars:
                import yaml as _yaml

                parsed = substitute_template_variables(_yaml.safe_load(yaml_text), resolved_vars)
                yaml_text = _yaml.dump(parsed, default_flow_style=False, allow_unicode=True)
            result = import_dashboard_yaml_content(
                yaml_text, project_oid, overwrite=True, current_user=current_user
            )
            entry.success = bool(result.get("success"))
            entry.dashboard_id = result.get("dashboard_id")
            entry.title = result.get("title")
        except HTTPException as exc:
            entry.error = f"HTTP {exc.status_code}: {exc.detail}"
            all_ok = False
        except Exception as exc:
            entry.error = str(exc)
            all_ok = False
        report.dashboards.append(entry)

    report.success = all_ok
    return report
