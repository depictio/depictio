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

import asyncio
import copy
import re
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from depictio.api.v1.db import projects_collection
from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import (
    ManifestEntriesRejected,
    ManifestIngestDCResult,
    _fetch_and_parse_manifest,
    _manifest_field_map,
    _manifest_type_of,
    _run_dc_ingest,
)
from depictio.api.v1.remote_fetch import RemoteURLRejected, validate_remote_url
from depictio.models.logging import logger

# Same rule as export_template's build_template_bundle: slash-separated
# segments that start alphanumeric. Rules out "..", a leading "/" or "~", so
# an id handed to resolve_template can never spell a path outside the
# server's templates directory.
TEMPLATE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*")
TEMPLATE_ID_RULE = (
    "template_id must be slash-separated path segments, e.g. 'generic/manifest-tables/1'."
)


def validate_template_id(template_id: str) -> str:
    """Return ``template_id`` when well-formed, else raise ``ValueError``."""
    if not TEMPLATE_ID_PATTERN.fullmatch(template_id):
        raise ValueError(TEMPLATE_ID_RULE)
    return template_id


class FromManifestRequest(BaseModel):
    """Body of POST /projects/from_manifest."""

    manifest_url: str
    template_id: str
    project_name: str | None = None
    # Extra template variables ({VAR} placeholders beyond MANIFEST_URL).
    variables: dict[str, str] = Field(default_factory=dict)
    # Plan-only: resolve + coverage-check without creating anything.
    dry_run: bool = False

    @field_validator("template_id")
    @classmethod
    def _well_formed_template_id(cls, value: str) -> str:
        return validate_template_id(value)


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


def _shared_field_map(template_id: str, manifest_dcs: list[tuple[dict, dict]]) -> dict[str, str]:
    """The columns the template's manifest DCs read the one manifest with.

    The coverage check parses the manifest once, so it has to read the same
    columns as each DC's own scan will (``id_field: sample`` and the like).
    Every DC is backed by the same manifest here, so DCs that disagree cannot
    all be served by it: refused.
    """
    tags_by_map: dict[tuple[tuple[str, str], ...], list[str]] = {}
    for dc, scan_params in manifest_dcs:
        key = tuple(sorted(_manifest_field_map(scan_params).items()))
        tags_by_map.setdefault(key, []).append(str(dc.get("data_collection_tag", "")))
    if len(tags_by_map) > 1:
        maps = [dict(key) for key in tags_by_map]
        differing = [field for field in maps[0] if len({m[field] for m in maps}) > 1]
        readings = "; ".join(
            f"{', '.join(tags)} read "
            + ", ".join(f"{field} from '{dict(key)[field]}'" for field in differing)
            for key, tags in tags_by_map.items()
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"The manifest data collections of template '{template_id}' read the "
                f"manifest with different columns ({readings}). One manifest backs them "
                "all, so their id_field, type_field, url_field and run_field must match."
            ),
        )
    return dict(next(iter(tags_by_map)))


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


def _template_not_found_detail(template_id: str, exc: FileNotFoundError) -> str:
    """Client-facing 404 detail: the id and the catalogue, never a server path.

    ``locate_template``'s own message names the server's templates directory
    (useful on the CLI, not something an API caller should learn); the
    catalogue rides along on the exception when available.
    """
    available = getattr(exc, "available_templates", None)
    hint = ""
    if available is not None:
        hint = f" Available templates: {', '.join(available) or 'none found'}."
    return f"Template '{template_id}' not found.{hint}"


def _refuse_a_taken_project_name(name: str, current_user) -> None:
    """Refuse a name ``POST /projects/create`` refuses, with the error it gives.

    The same check that route runs, ``_project_exists`` over the projects the
    caller can see. The creation flows run synchronously in a worker thread,
    which has no event loop of its own, so the coroutine is run to completion
    here.
    """
    from depictio.api.v1.endpoints.projects_endpoints.routes import (
        _project_exists,
        _project_taken,
        get_project_from_name,
    )

    lookup = get_project_from_name(project_name=name, current_user=current_user)
    if asyncio.run(_project_exists(lookup)):
        raise HTTPException(status_code=409, detail=_project_taken("name")["message"])


def _import_template_dashboards(
    dashboard_paths: list[Path],
    *,
    template_id: str,
    project_id: ObjectId,
    variables: dict[str, str],
    current_user,
) -> list[DashboardImportResult]:
    """Import a template's dashboards into a new project, keyed as ``depictio ingest`` keys them.

    Each dashboard is filed under the source key the CLI gives it
    (``<template id without version>:<path in the template>``) and a child tab
    names its parent by that key, with the CLI's own options: titles kept, a
    dashboard the project already has kept. A later ``depictio ingest`` of the
    same project with this template so finds these dashboards instead of adding
    a second copy of each. In-process, through the shared import handler, which
    binds DC tags to the ids just persisted and drops components whose optional
    DC was pruned.
    """
    import yaml

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        import_dashboard_yaml_content,
    )
    from depictio.cli.cli.utils.templates import (
        _main_dashboard_of,
        dashboard_source_key,
        locate_template,
        substitute_template_variables,
    )

    try:
        template_dir: Path | None = locate_template(template_id).parent
    except FileNotFoundError:
        template_dir = None
    keys = [dashboard_source_key(path, template_id, template_dir) for path in dashboard_paths]

    # Every file first: a child tab is sent with the key of the file that holds
    # its parent, found by the parent's title.
    loaded: list[tuple[str, Any] | Exception] = []
    for path in dashboard_paths:
        try:
            text = path.read_text(encoding="utf-8")
            parsed = yaml.safe_load(text)
            if variables:
                parsed = substitute_template_variables(parsed, variables)
                # sort_keys=False: PyYAML sorts mapping keys by default, which
                # re-orders every dict-shaped component config.
                text = yaml.dump(
                    parsed, default_flow_style=False, allow_unicode=True, sort_keys=False
                )
            loaded.append((text, parsed))
        except Exception as exc:
            loaded.append(exc)
    main_keys: dict[str, str] = {}
    for key, item in zip(keys, loaded, strict=True):
        main = _main_dashboard_of(item[1]) if isinstance(item, tuple) else None
        if main is not None and isinstance(main.get("title"), str):
            main_keys.setdefault(main["title"], key)

    results: list[DashboardImportResult] = []
    for path, key, item in zip(dashboard_paths, keys, loaded, strict=True):
        entry = DashboardImportResult(path=str(path), success=False)
        try:
            if isinstance(item, Exception):
                raise item
            text, parsed = item
            parent_tag = parsed.get("parent_dashboard_tag") if isinstance(parsed, dict) else None
            result = import_dashboard_yaml_content(
                yaml_content=text,
                project_id=project_id,
                overwrite=False,
                current_user=current_user,
                source_key=key,
                keep_titles=True,
                parent_source_key=main_keys.get(parent_tag) if parent_tag else None,
                existing="keep",
            )
            entry.success = bool(result.get("success"))
            entry.dashboard_id = result.get("dashboard_id")
            entry.title = result.get("title")
        except HTTPException as exc:
            entry.error = f"HTTP {exc.status_code}: {exc.detail}"
        except Exception as exc:
            entry.error = str(exc)
        results.append(entry)
    return results


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
    if manifest_url[:5].lower() == "s3://":
        raise HTTPException(
            status_code=400,
            detail="s3:// manifest locations are not supported yet — serve the manifest over https.",
        )
    # The request model already enforces this; re-checked here so direct
    # callers can't hand resolve_template a path either.
    try:
        validate_template_id(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Resolve the template server-side. resolve_template is import-light CLI
    # code (yaml + models); data_root=None skips every filesystem-local step.
    from depictio.cli.cli.utils.templates import resolve_template

    extra_vars = {**(variables or {}), "MANIFEST_URL": manifest_url}
    try:
        resolved_config, template_metadata, _origin, dashboard_paths, resolved_vars = (
            resolve_template(
                template_id=template_id,
                data_root=None,
                project_name=project_name,
                extra_vars=extra_vars,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_template_not_found_detail(template_id, exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Template resolution failed: {exc}")

    manifest_dcs = _manifest_dcs(resolved_config)
    if not manifest_dcs:
        raise HTTPException(
            status_code=422,
            detail=f"Template '{template_id}' has no manifest-mode data collection — "
            "it cannot be instantiated from a manifest.",
        )

    field_map = _shared_field_map(template_id, manifest_dcs)
    try:
        manifest = _fetch_and_parse_manifest(manifest_url, field_map=field_map)
    except ManifestEntriesRejected as exc:
        raise HTTPException(status_code=400, detail=exc.detail())
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
        manifest_type = _manifest_type_of(scan_params, tag)
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

    # Create the project, with the identity and uniqueness rules of POST /projects/create.
    from depictio.api.v1.endpoints.projects_endpoints.utils import (
        validate_workflow_uniqueness_in_project,
    )
    from depictio.models.models.projects import Project
    from depictio.models.timestamps import utc_now_str

    _refuse_a_taken_project_name(resolved_config["name"], current_user)

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
    # Template links name their DCs by tag; store the new DCs' ids next to
    # them, as the CLI's template sync does, so readers that do not resolve
    # tags (link cleanup on DC deletion, for one) see real ids.
    from depictio.models.models.links import resolve_link_tag_refs

    resolve_link_tag_refs(create_payload)
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
            manifest_type = _manifest_type_of(scan.get("scan_parameters") or {}, tag)
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

    # The template's dashboards, after ingestion: components whose optional DC
    # ended up empty are dropped (self-adapting import).
    report.dashboards = _import_template_dashboards(
        dashboard_paths,
        template_id=template_metadata.template_id,
        project_id=project_oid,
        variables=resolved_vars,
        current_user=current_user,
    )

    report.success = all_ok and all(entry.success for entry in report.dashboards)
    return report
