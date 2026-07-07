"""Dashboard-mode export: picks + viz specs → ``project.yaml`` + ``dashboard.yaml``.

Assembles the two artefacts the live stack ingests:

- ``project.yaml`` — one Python workflow whose Data Collections are the picked
  files (single-file scans, or a recursive scan from a config-by-example glob).
  Mirrors the on-disk shape of ``depictio/projects/init/iris/project.yaml`` and is
  validated per-DC with the real ``DataCollection`` model. (Permissions are added
  by ``depictio run`` at import time, exactly as for the reference projects, so
  they are intentionally absent here.)
- ``dashboard.yaml`` — a ``DashboardDataLite`` whose components are the attached
  viz specs, positioned with ``auto_generate_layout`` and validated before write.
"""

from __future__ import annotations

from fnmatch import translate as _glob_to_regex
from pathlib import Path, PurePosixPath
from typing import Any

from depictio.authoring.paths import safe_resolve

# Fields the studio frontend may send per component that are NOT part of a
# DashboardDataLite component (they belong to the builder's runtime state).
_RUNTIME_ONLY_KEYS = {"index", "wf_id", "dc_id", "project_id", "last_updated", "dc_config"}


def _new_oid() -> str:
    from bson import ObjectId

    return str(ObjectId())


def _fmt_and_sep(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    fmt = {
        ".tsv": "tsv",
        ".txt": "tsv",
        ".csv": "csv",
        ".parquet": "parquet",
        ".feather": "feather",
    }.get(suffix, "csv")
    sep = "\t" if fmt == "tsv" else ","
    return fmt, sep


def _scan_for(root: Path, dc: dict[str, Any]) -> dict[str, Any]:
    """Build a Scan block for one Data Collection input."""
    path = safe_resolve(root, dc["path"])
    mode = (dc.get("mode") or "single").lower()
    if mode == "recursive":
        glob = dc.get("glob") or f"**/{path.name}"
        pattern = _glob_to_regex(PurePosixPath(glob).name)
        return {
            "mode": "recursive",
            "scan_parameters": {"regex_config": {"pattern": pattern}},
        }
    return {"mode": "single", "scan_parameters": {"filename": str(path)}}


def _data_collection(root: Path, dc: dict[str, Any]) -> dict[str, Any]:
    path = safe_resolve(root, dc["path"])
    fmt, sep = _fmt_and_sep(path)
    props: dict[str, Any] = {"format": fmt}
    if fmt in {"csv", "tsv"}:
        props["polars_kwargs"] = {"separator": sep}
    if dc.get("columns_description"):
        props["columns_description"] = dc["columns_description"]
    return {
        "id": _new_oid(),
        "data_collection_tag": dc["dc_tag"],
        "description": dc.get("description", ""),
        "config": {
            "type": "table",
            "metatype": "metadata",
            "scan": _scan_for(root, dc),
            "dc_specific_properties": props,
        },
    }


def build_project(
    root: Path,
    name: str,
    workflow_name: str,
    data_collections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble (and validate) the project.yaml dict."""
    import copy

    from depictio.models.models.data_collections import DataCollection

    dc_dicts = [_data_collection(root, dc) for dc in data_collections]
    # Validate each DC through the real model (raises on any invalid scan/config).
    # Validate a deep copy: the model's before-validators mutate their input dict
    # (e.g. Scan replaces scan_parameters with a ScanSingle instance), which would
    # otherwise leave un-serialisable model objects in the YAML-bound dict.
    for dc in dc_dicts:
        DataCollection.model_validate(copy.deepcopy(dc))

    return {
        "id": _new_oid(),
        "name": name,
        "project_type": "basic",
        "is_public": True,
        "workflows": [
            {
                "id": _new_oid(),
                "name": workflow_name,
                "engine": {"name": "python"},
                "data_location": {
                    "structure": "flat",
                    "locations": [str(Path(root).resolve())],
                },
                "data_collections": dc_dicts,
            }
        ],
    }


def _lite_component(component: dict[str, Any], workflow_tag: str, index: int) -> dict[str, Any]:
    from depictio.models.yaml_serialization.utils import auto_generate_layout

    comp = {k: v for k, v in component.items() if k not in _RUNTIME_ONLY_KEYS}
    comp_type = comp.get("component_type", "figure")
    comp.setdefault("workflow_tag", workflow_tag)
    layout = auto_generate_layout(index, comp_type)
    comp["layout"] = {k: layout[k] for k in ("x", "y", "w", "h")}
    return comp


def build_dashboard_yaml(
    title: str,
    subtitle: str,
    project_name: str,
    workflow_tag: str,
    components: list[dict[str, Any]],
) -> str:
    """Assemble, validate, and serialise the dashboard.yaml."""
    from depictio.models.models.dashboards import DashboardDataLite

    lite_components = [_lite_component(c, workflow_tag, i) for i, c in enumerate(components)]
    dashboard = DashboardDataLite.model_validate(
        {
            "title": title,
            "subtitle": subtitle,
            "project_tag": project_name,
            "components": lite_components,
        }
    )
    return dashboard.to_yaml()


def export_dashboard(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Full dashboard-mode export.

    ``payload`` = ``{name, title, subtitle?, workflow_name?, data_collections:
    [...], components: [...]}``. Returns the two YAML strings plus the validated
    project dict.
    """
    import yaml

    root = Path(root).resolve()
    name = payload["name"]
    workflow_name = payload.get("workflow_name") or "studio_workflow"
    workflow_tag = f"python/{workflow_name}"

    project = build_project(root, name, workflow_name, payload["data_collections"])
    dashboard_yaml = build_dashboard_yaml(
        title=payload.get("title") or name,
        subtitle=payload.get("subtitle", ""),
        project_name=name,
        workflow_tag=workflow_tag,
        components=payload.get("components", []),
    )
    project_yaml = yaml.safe_dump(project, sort_keys=False, indent=2)
    return {
        "project_yaml": project_yaml,
        "dashboard_yaml": dashboard_yaml,
        "project": project,
    }
