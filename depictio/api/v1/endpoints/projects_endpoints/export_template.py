"""Export a project + its dashboards as a reusable template bundle (RFC phase 5).

The inverse of template instantiation: take a live project, strip everything
runtime (ids, permissions, hashes, runs, timestamps), re-parameterize its data
bindings (stored manifest URLs back to ``{MANIFEST_URL}``, a local data-root
prefix back to ``{DATA_ROOT}``), export its dashboards as tag-based YAML, and
synthesize the ``template:`` block. The result is a ``template.yaml`` +
``dashboards/*.yaml`` bundle that drops into ``depictio/projects/<template_id>/``
and is auto-discovered by the resolver and the picker.

The round-trip is the contract: before returning, the bundle is self-checked —
the ``template:`` block must validate as ``TemplateMetadata`` and the
substituted config as ``Project`` — so a broken bundle is never emitted.

Per-project storage credentials are deliberately NOT exported: they live in
their own collection and never belong in a shareable file.
"""

import copy
import html
import io
import re
import zipfile
from datetime import datetime
from enum import Enum
from typing import Any

import yaml
from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel

from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.models.logging import logger


class ExportTemplateRequest(BaseModel):
    """Body of POST /projects/{project_id}/export_template."""

    # e.g. "my-lab/rnaseq-qc/1" — becomes the bundle's directory layout.
    template_id: str
    description: str | None = None
    version: str = "1.0.0"
    # Local path prefix to re-parameterize as {DATA_ROOT}. Defaults to the
    # DATA_ROOT recorded in template_origin when the project itself came from
    # a template.
    data_root: str | None = None


# Keys that are runtime state at any nesting level. flexible_metadata carries
# per-DC ingest bookkeeping (deltatable_size_bytes / deltatable_size_updated),
# which must not leak into a shareable bundle.
_RUNTIME_KEYS = {
    "_id",
    "id",
    "hash",
    "registration_time",
    "last_modified",
    "flexible_metadata",
}
# Keys that are runtime state on the project root only (on top of _RUNTIME_KEYS).
_ROOT_RUNTIME_KEYS = ("permissions", "yaml_config_path", "template_origin")
# Preferred top-level key order for the emitted template.yaml.
_ROOT_KEY_ORDER = (
    "name",
    "description",
    "project_type",
    "is_public",
    "realtime",
    "data_management_platform_project_url",
    "workflows",
    "joins",
    "links",
)


def _strip_runtime(node: Any) -> Any:
    """Recursively drop runtime keys and empty values from a config tree.

    ``description`` values are decoded back to plain text: MongoModel stores
    them HTML-escaped (``'`` as ``&#x27;``), and a bundle is authored YAML, so
    it carries the text the user wrote. Re-instantiation escapes it once again.
    """
    if isinstance(node, dict):
        cleaned: dict = {}
        for key, value in node.items():
            if key in _RUNTIME_KEYS:
                continue
            if key == "description" and isinstance(value, str):
                value = html.unescape(value)
            stripped = _strip_runtime(value)
            if stripped is None or stripped == {} or stripped == []:
                continue
            cleaned[key] = stripped
        return cleaned
    if isinstance(node, list):
        return [_strip_runtime(item) for item in node]
    if isinstance(node, ObjectId):
        return str(node)
    # Mongo docs built via .mongo() may still carry Python-native leaves that
    # yaml.dump would tag as !!python/object — coerce to plain YAML scalars.
    if isinstance(node, Enum):
        return node.value
    if isinstance(node, datetime):
        return node.strftime("%Y-%m-%d %H:%M:%S")
    return node


def _replace_strings(node: Any, mapping: dict[str, str]) -> Any:
    """Recursively substitute exact prefixes/values in every string."""
    if isinstance(node, dict):
        return {k: _replace_strings(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_replace_strings(item, mapping) for item in node]
    if isinstance(node, str):
        for concrete, placeholder in mapping.items():
            if node == concrete:
                return placeholder
            if node.startswith(concrete.rstrip("/") + "/"):
                return placeholder + node[len(concrete.rstrip("/")) :]
        return node
    return node


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_").lower()
    return slug or "dashboard"


def _parameterize(config: dict, data_root: str | None) -> list[dict]:
    """Rewrite concrete data bindings into template placeholders, in place.

    Returns the ``template.variables`` declarations for what was injected.
    A template binds ONE manifest: distinct stored manifest URLs all collapse
    onto {MANIFEST_URL} (with a warning) — multi-manifest projects need manual
    splitting before export.
    """
    manifest_urls: set[str] = set()
    for workflow in config.get("workflows", []) or []:
        for dc in workflow.get("data_collections", []) or []:
            scan = (dc.get("config") or {}).get("scan") or {}
            if str(scan.get("mode", "")).lower() != "manifest":
                continue
            params = scan.get("scan_parameters") or {}
            if params.get("manifest_url"):
                manifest_urls.add(params["manifest_url"])
                params["manifest_url"] = "{MANIFEST_URL}"
    if len(manifest_urls) > 1:
        logger.warning(
            f"Export collapses {len(manifest_urls)} distinct manifest URLs onto "
            f"{{MANIFEST_URL}}: {sorted(manifest_urls)}"
        )

    mapping = {url: "{MANIFEST_URL}" for url in manifest_urls}
    if data_root:
        mapping[data_root] = "{DATA_ROOT}"
    if mapping:
        for workflow in config.get("workflows", []) or []:
            location = workflow.get("data_location") or {}
            location["locations"] = _replace_strings(location.get("locations") or [], mapping)
            workflow["data_collections"] = _replace_strings(
                workflow.get("data_collections") or [], mapping
            )

    variables: list[dict] = []
    if manifest_urls:
        variables.append(
            {
                "name": "MANIFEST_URL",
                "description": "URL of the Data Manifest (JSON or CSV) listing "
                "{id, type, url[, run]} entries",
                "required": True,
            }
        )
    if data_root:
        variables.append(
            {
                "name": "DATA_ROOT",
                "description": "Root directory of the input data",
                "required": True,
            }
        )
    return variables


def _self_check(template_section: dict, config: dict) -> None:
    """Round-trip guard: the bundle must re-instantiate through the resolver.

    Validates the template block as TemplateMetadata and the
    placeholder-substituted config as Project (with dummy variables and
    permissions, mirroring what instantiation injects). Raising 422 here means
    a broken bundle is never emitted.
    """
    from depictio.cli.cli.utils.templates import substitute_template_variables
    from depictio.models.models.projects import Project
    from depictio.models.models.templates import TemplateMetadata

    try:
        TemplateMetadata(**template_section)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid template metadata: {exc}")

    dummy_vars = {
        "MANIFEST_URL": "https://example.org/manifest.json",
        "DATA_ROOT": "/tmp/depictio-template-check",
    }
    check_cfg = substitute_template_variables(copy.deepcopy(config), dummy_vars)
    check_cfg["permissions"] = {
        "owners": [{"_id": ObjectId(), "email": "template-check@example.org"}]
    }
    try:
        Project(**check_cfg)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Exported config does not round-trip through Project validation: {exc}",
        )


def build_template_bundle(
    project_id: str,
    current_user,
    *,
    template_id: str,
    description: str | None = None,
    version: str = "1.0.0",
    data_root: str | None = None,
) -> dict[str, str]:
    """{relative_path: file_content} for the template bundle. Sync — to_thread."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import dashboard_yaml_content
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _user_can_edit_project,
    )

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*", template_id):
        raise HTTPException(
            status_code=422,
            detail="template_id must be slash-separated path segments, e.g. 'my-lab/rnaseq-qc/1'.",
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

    # Default the data root from template provenance when the project itself
    # was instantiated from a template.
    if data_root is None:
        origin = project_dict.get("template_origin") or {}
        data_root = (origin.get("variables") or {}).get("DATA_ROOT")

    config = copy.deepcopy(project_dict)
    for key in _ROOT_RUNTIME_KEYS:
        config.pop(key, None)
    for workflow in config.get("workflows", []) or []:
        workflow.pop("runs", None)
        workflow.pop("workflow_tag", None)  # regenerated from engine/name
    config = _strip_runtime(config)

    variables = _parameterize(config, data_root)

    # Dashboards: main tabs (with their child-tab families) as tag-based YAML.
    dashboards: dict[str, str] = {}
    project_name = str(config.get("name") or project_dict.get("name") or "")
    main_docs = [
        doc
        for doc in dashboards_collection.find({"project_id": project_oid})
        if doc.get("is_main_tab", True) and not doc.get("parent_dashboard_id")
    ]
    for doc in main_docs:
        child_tabs = list(
            dashboards_collection.find({"parent_dashboard_id": doc["dashboard_id"]}).sort(
                "tab_order", 1
            )
        )
        name = _slugify(str(doc.get("title") or "dashboard"))
        candidate, n = name, 2
        while f"dashboards/{candidate}.yaml" in dashboards:
            candidate, n = f"{name}_{n}", n + 1
        dashboards[f"dashboards/{candidate}.yaml"] = dashboard_yaml_content(
            doc, project_name, child_tabs
        )

    template_section: dict[str, Any] = {
        "template_id": template_id,
        "description": description
        or f"Template exported from project '{project_name or project_id}'",
        "version": version,
        "variables": variables,
        # Paths in the template block are relative to the bundle root.
        "dashboards": sorted(dashboards),
    }

    _self_check(template_section, config)

    ordered: dict[str, Any] = {"template": template_section}
    for key in _ROOT_KEY_ORDER:
        if key in config:
            ordered[key] = config[key]
    for key, value in config.items():
        if key not in ordered:
            ordered[key] = value

    template_yaml = yaml.dump(
        ordered, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    return {"template.yaml": template_yaml, **dashboards}


def bundle_to_zip(bundle: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in bundle.items():
            archive.writestr(path, content)
    return buffer.getvalue()
