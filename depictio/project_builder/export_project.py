"""Project-mode export: picks → ``project.yaml``.

Assembles the single artefact the live stack ingests to set up data:

- ``project.yaml`` — one *or several* workflows, each with its own engine +
  ``data_location`` (folder + structure) and its Data Collections (single-file
  scans, or a recursive scan from a config-by-example glob). Mirrors the on-disk
  shape of ``depictio/projects/init/penguins/project.yaml`` and is validated with
  the real ``DataCollection`` + ``Project`` models. (Permissions are added by
  ``depictio run`` at import time, exactly as for the reference projects, so they
  are intentionally absent here.)

The dashboard is authored separately, later, in the editor of a real deployment —
after ``depictio run`` imports this project. The Project Builder stops at the data setup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from depictio.project_builder.paths import safe_resolve
from depictio.project_builder.recognize import glob_to_pattern

# The emitted file name — matches the CLI convention
# (``depictio/cli/configs/nf-core/rnaseq/depictio_project.yaml``) so the user can
# run ``depictio run --project <root>/depictio_project.yaml`` immediately.
PROJECT_YAML_NAME = "depictio_project.yaml"


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
    """Build a Scan block for one Data Collection input.

    Recursive scans use the user-edited ``pattern`` verbatim when present (so the
    regex shown in the Project Builder is exactly what is written), else derive it from the
    ``glob``. Optional ``max_depth`` / ``ignore`` map onto ``ScanRecursive``.
    """
    path = safe_resolve(root, dc["path"])
    mode = (dc.get("mode") or "single").lower()
    if mode == "recursive":
        pattern = dc.get("pattern")
        if not pattern:
            glob = dc.get("glob") or f"**/{path.name}"
            pattern = glob_to_pattern(glob)
        scan_parameters: dict[str, Any] = {"regex_config": {"pattern": pattern}}
        if dc.get("max_depth") is not None:
            scan_parameters["max_depth"] = dc["max_depth"]
        if dc.get("ignore"):
            scan_parameters["ignore"] = list(dc["ignore"])
        return {"mode": "recursive", "scan_parameters": scan_parameters}
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


def _workflow(root: Path, wf: dict[str, Any]) -> dict[str, Any]:
    """Build one Workflow dict: its engine, data_location (folder + structure) and DCs.

    ``folder`` is the workflow's ``data_location`` root, relative to the Project Builder launch
    ``root`` (``""`` = the launch dir itself); it is resolved through ``safe_resolve``
    so it cannot escape. DC ``path``/glob stay relative to the launch ``root`` — only
    ``data_location.locations`` carries the per-workflow folder.
    """
    name = wf.get("name")
    if not name:
        raise ValueError("every workflow needs a name")
    dcs = wf.get("data_collections") or []
    if not dcs:
        raise ValueError(f"workflow {name!r} needs at least one data collection")

    location = safe_resolve(root, wf.get("folder") or "")
    structure = (wf.get("structure") or "flat").lower()
    data_location: dict[str, Any] = {"structure": structure, "locations": [str(location)]}
    if structure == "sequencing-runs":
        data_location["runs_regex"] = wf.get("runs_regex") or "run_*"

    workflow: dict[str, Any] = {
        "id": _new_oid(),
        "name": name,
        "engine": {"name": wf.get("engine") or "python"},
        "data_location": data_location,
        "data_collections": [_data_collection(root, dc) for dc in dcs],
    }
    # Optional provenance from the repo-metadata step.
    if wf.get("version"):
        workflow["version"] = wf["version"]
    if wf.get("repository_url"):
        workflow["repository_url"] = wf["repository_url"]
    if wf.get("catalog"):
        workflow["catalog"] = wf["catalog"]
    return workflow


def build_project(
    root: Path,
    name: str,
    workflows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble (and validate) the multi-workflow project.yaml dict.

    Enforces the two invariants the model only *warns* about: workflow names unique,
    and DC tags unique across the whole project. Validates each DC through
    ``DataCollection`` and the assembled project through ``Project`` (with a stub
    ``permissions`` — ``depictio run`` injects the real one at import).
    """
    import copy

    from depictio.models.models.data_collections import DataCollection
    from depictio.models.models.projects import Project

    if not workflows:
        raise ValueError("a project needs at least one workflow")

    names = [w.get("name") for w in workflows]
    if len(names) != len(set(names)):
        raise ValueError("workflow names must be unique within a project")

    wf_dicts = [_workflow(root, w) for w in workflows]

    # DC tags must be unique across all workflows (the model only warns).
    # Validate a deep copy of each DC: the model's before-validators mutate their
    # input dict, which would otherwise leave un-serialisable objects in the YAML.
    seen_tags: set[str] = set()
    for wf in wf_dicts:
        for dc in wf["data_collections"]:
            tag = dc["data_collection_tag"]
            if tag in seen_tags:
                raise ValueError(f"data collection tag {tag!r} is used by more than one workflow")
            seen_tags.add(tag)
            DataCollection.model_validate(copy.deepcopy(dc))

    project = {
        "id": _new_oid(),
        "name": name,
        "project_type": "basic",
        "is_public": True,
        "workflows": wf_dicts,
    }

    # Validate the whole project (workflows + data_location) against the real model.
    to_validate = copy.deepcopy(project)
    to_validate["permissions"] = {"owners": [], "editors": [], "viewers": []}
    Project.model_validate(to_validate)

    return project


def export_project(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Project-mode export.

    ``payload`` = ``{name, workflows: [{name, engine?, folder?, structure?,
    runs_regex?, data_collections: [...]}]}``. Builds and validates the project dict,
    writes ``depictio_project.yaml`` into the root, and returns the YAML string, the
    validated dict, and the written path.
    """
    import yaml

    root = Path(root).resolve()
    name = payload["name"]
    workflows = payload.get("workflows") or []

    project = build_project(root, name, workflows)
    project_yaml = yaml.safe_dump(project, sort_keys=False, indent=2)

    written = root / PROJECT_YAML_NAME
    written.write_text(project_yaml)

    return {
        "project_yaml": project_yaml,
        "project": project,
        "written_path": str(written),
    }
