"""Template endpoints.

Exports an existing project as a reusable template bundle (a ZIP of YAML files)
that the existing template engine can instantiate via
``depictio run --template <bundle> --data-root <path>``.

The bundle layout mirrors the in-repo templates so the reuse path is free::

    template.yaml          # project config + minimal template: block
    dashboards/<name>.yaml  # each dashboard exported as YAML
"""

import io
import re
import zipfile
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.api.v1.endpoints.dashboards_endpoints.routes import build_dashboard_yaml_content
from depictio.api.v1.endpoints.templates_endpoints.utils import build_template_config
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.users import User
from depictio.models.yaml_serialization.utils import (
    convert_for_yaml,
    dump_yaml,
    sanitize_filename,
)

templates_endpoint_router = APIRouter()


class TemplateExportRequest(BaseModel):
    project_id: str | None = None
    project_name: str | None = None
    template_id: str | None = None  # defaults to "user/<slug>/<version>"
    version: str = "1.0.0"
    description: str | None = None


def _slug(name: str) -> str:
    """Make a filesystem/identifier-safe slug from a project name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "project"


@templates_endpoint_router.post("/export")
async def export_project_as_template(
    request: TemplateExportRequest,
    current_user: User = Depends(get_user_or_anonymous),
) -> StreamingResponse:
    """Export a project (config + dashboards) as a template ZIP.

    Access mirrors the migrate export rules: admins may export any project; in
    public/demo mode non-admin visitors may export projects they can read
    (public or shared); otherwise export is admin-only.
    """
    if not current_user.is_admin and not settings.auth.is_public_mode:
        raise HTTPException(status_code=403, detail="Only administrators can export templates")

    # Resolve the project, permission-scoped for non-admin callers.
    query: dict[str, Any]
    if request.project_id:
        query = {"_id": ObjectId(request.project_id)}
    elif request.project_name:
        query = {"name": request.project_name}
    else:
        raise HTTPException(status_code=400, detail="Provide project_id or project_name")

    if not current_user.is_admin:
        user_oid = ObjectId(current_user.id)
        query["$or"] = [
            {"permissions.owners._id": user_oid},
            {"permissions.editors._id": user_oid},
            {"permissions.viewers._id": user_oid},
            {"is_public": True},
        ]

    project = projects_collection.find_one(query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_id = project["_id"]
    project_name = project.get("name", "project")
    slug = _slug(project_name)

    # Collect the project's main/standalone dashboards (child tabs are pulled in
    # by build_dashboard_yaml_content as nested multi-tab YAML).
    main_dashboards = list(
        dashboards_collection.find(
            {
                "project_id": project_id,
                "$or": [{"is_main_tab": True}, {"is_main_tab": {"$exists": False}}],
            }
        )
    )

    dashboard_files: dict[str, str] = {}  # zip path -> YAML content
    dashboard_rel_paths: list[str] = []
    used_names: set[str] = set()
    for dash in main_dashboards:
        title = dash.get("title") or "dashboard"
        base = sanitize_filename(title) or "dashboard"
        name = base
        i = 1
        while name in used_names:
            i += 1
            name = f"{base}_{i}"
        used_names.add(name)

        rel_path = f"dashboards/{name}.yaml"
        try:
            dashboard_files[rel_path] = build_dashboard_yaml_content(dash, project_name)
            dashboard_rel_paths.append(rel_path)
        except Exception as exc:  # noqa: BLE001 — skip a broken dashboard, keep exporting
            logger.warning("Skipping dashboard '%s' during template export: %s", title, exc)

    template_id = request.template_id or f"user/{slug}/{request.version}"
    description = request.description or f"Template exported from project '{project_name}'"

    try:
        template_dict, data_root = build_template_config(
            project,
            dashboard_rel_paths,
            template_id=template_id,
            version=request.version,
            description=description,
        )
    except Exception as exc:  # noqa: BLE001 — surface a clean 400 for invalid config
        logger.error("Failed to build template config for project %s: %s", project_id, exc)
        raise HTTPException(status_code=400, detail=f"Could not build template: {exc}") from exc

    template_yaml = dump_yaml(convert_for_yaml(template_dict))

    logger.info(
        "Template export: project=%s dashboards=%d data_root=%s",
        str(project_id),
        len(dashboard_rel_paths),
        data_root,
    )

    # Assemble the ZIP in memory.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("template.yaml", template_yaml)
        for rel_path, content in dashboard_files.items():
            zf.writestr(rel_path, content)
    buffer.seek(0)

    filename = f"{slug}-template.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
