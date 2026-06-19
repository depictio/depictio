"""Catalog compose endpoint — matches ingested DCs against catalog entries.

GET /catalog/project/{project_id}/compose
  Returns recognized catalog modules for a project, grouped by tool. Each
  match includes the dc_id / wf_id so the React builder can jump straight to
  Step 2 with roles pre-filled.
"""

from __future__ import annotations

import logging
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from depictio.api.v1.db import files_collection, projects_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.catalog.payload import (
    CatalogPayloadError,
    advanced_viz_persist_config,
    build_payload,
)
from depictio.models.components.advanced_viz.catalog import load_catalog_entries
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

catalog_endpoint_router = APIRouter()


def _render_to_dict(render, output) -> dict[str, Any]:
    """Serialise a render's ``renders_as`` declaration for the React builder.

    For advanced_viz renders, also attach the pre-computed ``config`` blob (role
    bindings + data-derived viz-control defaults) so a catalog-added component
    persists exactly what the preview rendered — see ``advanced_viz_persist_config``.
    """
    spec = render.model_dump(exclude_none=True, exclude_defaults=True)
    if render.component == "advanced_viz":
        config = advanced_viz_persist_config(output, render)
        if config is not None:
            spec["config"] = config
    return spec


def _match_dc_to_catalog(basename: str, full_path: str, entries) -> list[dict[str, Any]]:
    """Return catalog output matches for a DC identified by basename + full path.

    Checks both find.filename (fnmatch on basename) and find.path_glob
    (PurePosixPath.match on the full path, which handles ** patterns).
    """
    matches = []
    for entry in entries:
        for output in entry.outputs:
            find = output.find
            matched = (find.filename and fnmatch(basename, find.filename)) or (
                find.path_glob and PurePosixPath(full_path).match(find.path_glob)
            )
            if matched:
                matches.append(
                    {
                        "tool_id": entry.id,
                        "tool_name": entry.name,
                        "output_id": output.id,
                        "description": output.description or "",
                        "renders_as": [
                            _render_to_dict(r, output) for r in (output.renders_as or [])
                        ],
                    }
                )
    return matches


def _add_matches(
    modules_by_tool: dict[str, dict[str, Any]],
    matches: list[dict[str, Any]],
    dc_id: str,
    wf_id: str,
    dc_tag: str,
) -> None:
    for match in matches:
        tool_id = match["tool_id"]
        if tool_id not in modules_by_tool:
            modules_by_tool[tool_id] = {
                "tool_id": tool_id,
                "tool_name": match["tool_name"],
                "matches": [],
            }
        modules_by_tool[tool_id]["matches"].append(
            {
                "output_id": match["output_id"],
                "description": match["description"],
                "dc_id": dc_id,
                "wf_id": wf_id,
                "dc_tag": dc_tag,
                "renders_as": match["renders_as"],
            }
        )


@catalog_endpoint_router.get("/project/{project_id}/compose")
async def compose_project(
    project_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Return recognized catalog modules for a project, grouped by tool_id."""
    try:
        oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    current_user_id = ObjectId(current_user.id)
    permission_query: dict[str, Any] = {
        "_id": oid,
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }
    if current_user.is_admin:
        permission_query = {"_id": oid}

    project = projects_collection.find_one(permission_query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        entries = load_catalog_entries()
    except Exception:
        logger.exception("Failed to load catalog entries")
        raise HTTPException(status_code=500, detail="Catalog unavailable")

    modules_by_tool: dict[str, dict[str, Any]] = {}

    # Collect recursive-scan DC ids for a single bulk files query.
    recursive_dc_ids: list[ObjectId] = []
    dc_meta: dict[str, dict[str, Any]] = {}  # dc_id_str -> {wf_id, dc_tag}

    for workflow in project.get("workflows", []):
        wf_id = str(workflow.get("_id", ""))
        for dc in workflow.get("data_collections", []):
            if not isinstance(dc, dict):
                continue
            dc_tag_raw = dc.get("data_collection_tag", "?")
            config = dc.get("config", {})
            if not isinstance(config, dict):
                logger.debug("catalog/compose: DC %s skipped — config not a dict", dc_tag_raw)
                continue
            dc_type = config.get("type", "").lower()
            if dc_type != "table":
                logger.debug(
                    "catalog/compose: DC %s skipped — type=%r (not table)", dc_tag_raw, dc_type
                )
                continue
            scan = config.get("scan", {})
            if not isinstance(scan, dict):
                logger.debug("catalog/compose: DC %s skipped — scan not a dict", dc_tag_raw)
                continue
            params = scan.get("scan_parameters", {})
            if not isinstance(params, dict):
                logger.debug(
                    "catalog/compose: DC %s skipped — scan_parameters not a dict", dc_tag_raw
                )
                continue

            dc_id_str = str(dc.get("_id", ""))
            dc_tag = dc.get("data_collection_tag", dc_id_str)
            scan_mode = scan.get("mode", "")

            if scan_mode == "single":
                filename = params.get("filename", "")
                if not filename:
                    logger.debug(
                        "catalog/compose: DC %s skipped — single mode but no filename", dc_tag
                    )
                    continue
                basename = Path(filename).name
                logger.debug("catalog/compose: DC %s — single filename=%r", dc_tag, filename)
                _add_matches(
                    modules_by_tool,
                    _match_dc_to_catalog(basename, filename, entries),
                    dc_id_str,
                    wf_id,
                    dc_tag,
                )

            elif scan_mode == "recursive":
                try:
                    dc_oid = ObjectId(dc_id_str)
                    recursive_dc_ids.append(dc_oid)
                    dc_meta[dc_id_str] = {"wf_id": wf_id, "dc_tag": dc_tag}
                except Exception:
                    logger.debug("catalog/compose: DC %s — invalid ObjectId, skipping", dc_tag)
            else:
                logger.debug(
                    "catalog/compose: DC %s skipped — unknown scan mode %r", dc_tag, scan_mode
                )

    # Bulk-resolve recursive DCs via the files collection (one query).
    if recursive_dc_ids:
        for file_doc in files_collection.find(
            {"data_collection_id": {"$in": recursive_dc_ids}},
            {"file_location": 1, "filename": 1, "data_collection_id": 1},
        ):
            dc_oid = file_doc.get("data_collection_id")
            dc_id_str = str(dc_oid)
            meta = dc_meta.get(dc_id_str)
            if not meta:
                continue
            file_location = file_doc.get("file_location", "")
            basename = Path(file_location).name if file_location else file_doc.get("filename", "")
            if not basename:
                continue
            logger.debug(
                "catalog/compose: recursive DC %s — file_location=%r", meta["dc_tag"], file_location
            )
            _add_matches(
                modules_by_tool,
                _match_dc_to_catalog(basename, file_location, entries),
                dc_id_str,
                meta["wf_id"],
                meta["dc_tag"],
            )

    return {"modules": list(modules_by_tool.values())}


@catalog_endpoint_router.get("/output/{output_id}/preview-payload")
async def preview_output_payload(
    output_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Compute and return the preview payload for a catalog output (from its fixture).

    The payload contains pre-rendered Plotly JSON (figures), card values, table
    schemas, and advanced-viz data — ready for the React preview panel to render
    without any live API calls.
    """
    try:
        entries = load_catalog_entries()
    except Exception:
        logger.exception("Failed to load catalog entries")
        raise HTTPException(status_code=500, detail="Catalog unavailable")

    for entry in entries:
        for output in entry.outputs:
            if output.id == output_id:
                try:
                    payload = build_payload(output, theme="light", tool=entry)
                    return payload
                except CatalogPayloadError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                except Exception:
                    logger.exception("Failed to build preview for output %s", output_id)
                    raise HTTPException(status_code=500, detail="Preview generation failed")

    raise HTTPException(status_code=404, detail=f"Output {output_id!r} not found in catalog")


@catalog_endpoint_router.get("/output/{output_id}/preview-html", response_class=HTMLResponse)
async def preview_output_html(
    output_id: str,
    render_id: str | None = Query(None, description="If given, only this render index is shown"),
    current_user: User = Depends(get_user_or_anonymous),
) -> HTMLResponse:
    """Serve the standalone catalog-preview HTML for an output (uses fixture data).

    The HTML embeds the pre-built catalog-preview bundle with the real
    ComponentRenderer and the pre-computed payload — no live API calls inside.
    Pass ``?render_id=<output_id>-<idx>`` to preview a single component in isolation.
    """
    from depictio.catalog.payload import render_html

    try:
        entries = load_catalog_entries()
    except Exception:
        logger.exception("Failed to load catalog entries")
        raise HTTPException(status_code=500, detail="Catalog unavailable")

    for entry in entries:
        for output in entry.outputs:
            if output.id == output_id:
                try:
                    html = render_html(output, theme="light", tool=entry, render_id=render_id)
                    return HTMLResponse(content=html)
                except CatalogPayloadError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                except Exception:
                    logger.exception("Failed to render preview HTML for output %s", output_id)
                    raise HTTPException(status_code=500, detail="Preview generation failed")

    raise HTTPException(status_code=404, detail=f"Output {output_id!r} not found in catalog")
