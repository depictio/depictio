"""Pure helpers for exporting an existing project as a reusable template.

These functions take a stored project document (MongoDB dict) and produce the
``template.yaml`` content consumed by the existing template engine
(``resolve_template`` / ``depictio run --template``). They are deliberately
side-effect free so they can be unit-tested without a database.

The produced template is intentionally simple: a project config plus a minimal
``template:`` block declaring a single ``DATA_ROOT`` variable. Filesystem data
paths are re-parameterized to ``{DATA_ROOT}`` so a colleague can instantiate the
template against their own copy of the data. No data files travel with the
template.
"""

import copy
import os
from typing import Any

from depictio.models.models.templates import TemplateMetadata

# Project config keys kept in the exported template (everything else — _id,
# permissions, hash, registration_time, template_origin, … — is dropped).
CONFIG_KEYS = [
    "name",
    "project_type",
    "is_public",
    "data_management_platform_project_url",
    "workflows",
    "data_collections",
    "joins",
    "links",
]

# Identity / DB-only keys stripped recursively from the config so a fresh
# instantiation mints new ObjectIds and is owned by the importing user.
IDENTITY_KEYS = {"_id", "id", "hash", "registration_time", "depictio_version"}

DATA_ROOT_TOKEN = "{DATA_ROOT}"


def strip_identity(obj: Any) -> Any:
    """Recursively drop identity/DB-only keys from a config structure."""
    if isinstance(obj, dict):
        return {k: strip_identity(v) for k, v in obj.items() if k not in IDENTITY_KEYS}
    if isinstance(obj, list):
        return [strip_identity(item) for item in obj]
    return obj


def _dc_filename(dc: dict) -> Any:
    """Return the single-scan ``filename`` of a data collection, if any."""
    scan = (dc.get("config") or {}).get("scan") or {}
    scan_parameters = scan.get("scan_parameters") or {}
    return scan_parameters.get("filename")


def collect_fs_paths(config: dict) -> list[str]:
    """Collect absolute filesystem paths referenced by the project config.

    Looks at workflow ``data_location.locations`` and single-scan data
    collection ``filename`` entries (both under workflows and as top-level
    data collections for basic projects).
    """
    paths: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and os.path.isabs(value):
            paths.append(value)

    for wf in config.get("workflows") or []:
        data_location = wf.get("data_location") or {}
        for loc in data_location.get("locations") or []:
            add(loc)
        for dc in wf.get("data_collections") or []:
            add(_dc_filename(dc))

    for dc in config.get("data_collections") or []:
        add(_dc_filename(dc))

    return paths


def compute_data_root(paths: list[str]) -> str | None:
    """Compute the common data-root directory across the collected paths."""
    if not paths:
        return None
    unique = sorted(set(paths))
    if len(unique) == 1:
        only = unique[0]
        # A lone file path → use its directory as the root.
        return only if not os.path.splitext(only)[1] else os.path.dirname(only)
    return os.path.commonpath(unique)


def _to_data_root(path: Any, root: str) -> Any:
    """Replace the ``root`` prefix of an absolute path with ``{DATA_ROOT}``."""
    if not isinstance(path, str) or not os.path.isabs(path):
        return path
    if path == root:
        return DATA_ROOT_TOKEN
    try:
        if os.path.commonpath([path, root]) == root:
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            return f"{DATA_ROOT_TOKEN}/{rel}"
    except ValueError:
        # Different drives / un-comparable paths — leave untouched.
        pass
    return path


def _parameterize_dc(dc: dict, root: str) -> None:
    scan = (dc.get("config") or {}).get("scan") or {}
    scan_parameters = scan.get("scan_parameters") or {}
    if "filename" in scan_parameters:
        scan_parameters["filename"] = _to_data_root(scan_parameters["filename"], root)


def parameterize_paths(config: dict, root: str) -> None:
    """In-place: rewrite absolute data paths under ``root`` to ``{DATA_ROOT}``."""
    for wf in config.get("workflows") or []:
        data_location = wf.get("data_location") or {}
        locations = data_location.get("locations")
        if isinstance(locations, list):
            data_location["locations"] = [_to_data_root(loc, root) for loc in locations]
        for dc in wf.get("data_collections") or []:
            _parameterize_dc(dc, root)
    for dc in config.get("data_collections") or []:
        _parameterize_dc(dc, root)


def build_template_config(
    project_doc: dict,
    dashboard_rel_paths: list[str],
    *,
    template_id: str,
    version: str,
    description: str,
) -> tuple[dict, str | None]:
    """Build the full ``template.yaml`` content from a stored project document.

    Returns a tuple ``(template_dict, data_root)`` where ``template_dict`` is the
    ``template:`` block merged with the cleaned project config, and ``data_root``
    is the detected common data-root prefix (or ``None`` if the project has no
    filesystem paths to parameterize).
    """
    clean: dict[str, Any] = {}
    for key in CONFIG_KEYS:
        if key in project_doc and project_doc[key] not in (None, [], {}):
            clean[key] = copy.deepcopy(project_doc[key])

    clean = strip_identity(clean)

    data_root = compute_data_root(collect_fs_paths(clean))
    if data_root:
        parameterize_paths(clean, data_root)

    template_block: dict[str, Any] = {
        "template_id": template_id,
        "description": description,
        "version": version,
        "variables": [
            {
                "name": "DATA_ROOT",
                "description": "Root directory containing this project's data",
                "required": True,
            }
        ],
        "dashboards": dashboard_rel_paths,
    }
    # Validate the metadata block against the template model (raises on error).
    TemplateMetadata(**template_block)

    return {"template": template_block, **clean}, data_root
