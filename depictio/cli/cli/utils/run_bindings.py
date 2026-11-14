"""What each run of a template project was resolved with (epic #1399).

A template is resolved against ONE data root: its ``{DATA_ROOT}``, its
``--var`` values and the files auto-detected there. A project with several
runs (``data_location.locations``) was resolved once per run, so three things
are kept per run location rather than overwritten by the latest one:

* a ``single`` collection's file (``ScanSingle.run_files``): each run's own
  ``metadata.tsv``, or one file for all runs when they bring the same bytes;
* a recipe's ``params`` (``TransformConfig.run_params``);
* the template variables (``TemplateOrigin.run_variables``).

The project-level value (``filename``, ``params``, ``variables``) is always the
first location's, which is what a single-run project has always held. A map is
stored only when the runs differ, so a single-run project keeps exactly the
configuration it had.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BindingReport:
    """What :func:`carry_run_bindings` did, for the attach/refresh summary."""

    per_run_single: list[str] = field(default_factory=list)
    shared_single: list[str] = field(default_factory=list)
    missing_single: list[str] = field(default_factory=list)
    per_run_params: list[str] = field(default_factory=list)
    per_run_variables: bool = False


def _real(location: str) -> str:
    return os.path.realpath(str(location))


def _sha256(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _remote_workflows(remote_project: dict) -> dict[str, dict]:
    return {
        wf.get("workflow_tag"): wf
        for wf in (remote_project.get("workflows") or [])
        if wf.get("workflow_tag")
    }


def _remote_dcs(remote_wf: dict) -> dict[str, dict]:
    return {
        dc.get("data_collection_tag"): dc
        for dc in (remote_wf.get("data_collections") or [])
        if dc.get("data_collection_tag")
    }


def _start(stored_map: Any, stored_value: Any, remote_locations: list[str]) -> dict[str, Any]:
    """The bindings the server holds: its per-run map, else its single value on
    its first location."""
    if isinstance(stored_map, dict) and stored_map:
        return dict(stored_map)
    if stored_value is not None and remote_locations:
        return {remote_locations[0]: stored_value}
    return {}


def _rebind(
    bindings: dict[str, Any], this: list[str], value: Any, locations: list[str]
) -> dict[str, Any]:
    """``bindings`` with this run's locations bound to ``value``, keyed and ordered
    by the project's locations; a binding of a location the project no longer has
    is dropped."""
    by_real = {_real(loc): v for loc, v in bindings.items()}
    for loc in this:
        by_real[_real(loc)] = value
    return {loc: by_real[_real(loc)] for loc in locations if _real(loc) in by_real}


def _first_value(bindings: dict[str, Any], locations: list[str], default: Any) -> Any:
    return bindings.get(locations[0], default) if locations else default


def _bind_single(dc, remote_dc: dict | None, this: list[str], locations, remote_locations, report):
    scan = dc.config.scan
    params = scan.scan_parameters
    remote_params = ((remote_dc or {}).get("config") or {}).get("scan") or {}
    remote_params = remote_params.get("scan_parameters") or {}
    if getattr(params, "scope", None) == "project":
        # Declared project-wide by the template: one file, the first run's.
        if not any(_real(loc) == _real(locations[0]) for loc in this) and remote_params.get(
            "filename"
        ):
            params.filename = remote_params["filename"]
        params.run_files = None
        return

    bindings = _start(
        remote_params.get("run_files"), remote_params.get("filename"), remote_locations
    )
    new_file = params.filename
    value = new_file
    if not os.path.isfile(new_file):
        # This run has no such file: it keeps the one the runs before it read.
        previous = [v for v in bindings.values() if v]
        if previous:
            value = previous[-1]
            report.missing_single.append(dc.data_collection_tag)
    else:
        sha = _sha256(new_file)
        for bound in bindings.values():
            if bound and bound != new_file and os.path.isfile(bound) and _sha256(bound) == sha:
                value = bound
                report.shared_single.append(dc.data_collection_tag)
                break
    bindings = _rebind(bindings, this, value, locations)
    params.filename = _first_value(bindings, locations, new_file)
    # One binding on the first location is what a single-run project always
    # held: no map. A collection that first appears with a later run keeps its
    # map, or its file would be read as the first run's.
    only_first = len(bindings) == 1 and _real(next(iter(bindings))) == _real(locations[0])
    if bindings and not only_first:
        params.run_files = bindings
        if len(set(bindings.values())) > 1:
            report.per_run_single.append(dc.data_collection_tag)
    else:
        params.run_files = None


def _bind_params(dc, remote_dc: dict | None, this: list[str], locations, remote_locations, report):
    transform = dc.config.transform
    remote_transform = ((remote_dc or {}).get("config") or {}).get("transform") or {}
    bindings = _start(
        remote_transform.get("run_params"), remote_transform.get("params") or {}, remote_locations
    )
    bindings = _rebind(bindings, this, dict(transform.params or {}), locations)
    first = _first_value(bindings, locations, dict(transform.params or {}))
    transform.params = first or transform.params
    if len(bindings) > 1 and any(v != first for v in bindings.values()):
        transform.run_params = bindings
        report.per_run_params.append(dc.data_collection_tag)
    else:
        transform.run_params = None


def carry_run_bindings(
    project_config, remote_project: dict, this_locations: dict[str, list[str]]
) -> BindingReport:
    """Keep what every run was resolved with, in place.

    ``project_config`` was resolved against ``this_locations`` (per workflow
    tag), and its ``data_location.locations`` already lists every run (after
    ``merge_run_locations`` or ``refresh_run_locations``). ``remote_project``
    is the server's document, which holds the other runs' bindings.
    """
    report = BindingReport()
    remote_wfs = _remote_workflows(remote_project)
    first_wf_locations: list[str] = []
    first_wf_this: list[str] = []
    first_wf_remote_locations: list[str] = []
    for wf in project_config.workflows:
        remote_wf = remote_wfs.get(wf.workflow_tag) or {}
        remote_locations = [
            str(loc) for loc in ((remote_wf.get("data_location") or {}).get("locations") or [])
        ]
        locations = [str(loc) for loc in (wf.data_location.locations or [])]
        this = [str(loc) for loc in this_locations.get(wf.workflow_tag, [])]
        if not first_wf_locations:
            first_wf_locations, first_wf_this = locations, this
            first_wf_remote_locations = remote_locations
        if not locations or not this:
            continue
        remote_dcs = _remote_dcs(remote_wf)
        for dc in wf.data_collections:
            remote_dc = remote_dcs.get(dc.data_collection_tag)
            scan = dc.config.scan
            if scan is not None and str(scan.mode).lower() == "single":
                _bind_single(dc, remote_dc, this, locations, remote_locations, report)
            if dc.config.transform is not None:
                _bind_params(dc, remote_dc, this, locations, remote_locations, report)

    origin = getattr(project_config, "template_origin", None)
    remote_origin = remote_project.get("template_origin") or {}
    if origin is not None and first_wf_locations and first_wf_this:
        bindings = _start(
            remote_origin.get("run_variables"),
            remote_origin.get("variables"),
            first_wf_remote_locations,
        )
        bindings = _rebind(bindings, first_wf_this, dict(origin.variables), first_wf_locations)
        first = _first_value(bindings, first_wf_locations, dict(origin.variables))
        resolved_here = any(_real(loc) == _real(first_wf_locations[0]) for loc in first_wf_this)
        if not resolved_here and remote_origin.get("data_root") is not None:
            origin.data_root = remote_origin["data_root"]
        origin.variables = first
        if len(bindings) > 1 and any(v != first for v in bindings.values()):
            origin.run_variables = bindings
            report.per_run_variables = True
        else:
            origin.run_variables = None
    return report


def run_params_for(transform, location: str | None) -> dict[str, str] | None:
    """The recipe params of the run at ``location``."""
    run_params = getattr(transform, "run_params", None)
    if run_params and location is not None:
        real = _real(location)
        for loc, params in run_params.items():
            if _real(loc) == real:
                return params
    return transform.params


def single_files(params, locations: list[str]) -> list[tuple[str, list[str]]]:
    """Each distinct file of a single collection with the run locations bound to it.

    Without a per-run map the one file belongs to the first location.
    """
    run_files = getattr(params, "run_files", None)
    if getattr(params, "scope", None) == "project":
        return [(params.filename, [])]
    if not run_files:
        return [(params.filename, locations[:1])]
    out: dict[str, list[str]] = {}
    for loc, path in run_files.items():
        out.setdefault(path, []).append(loc)
    return list(out.items())
