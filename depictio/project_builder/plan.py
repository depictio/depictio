"""Resolve an ad-hoc template against a data root, and report what it would ingest.

Shared by the standalone server's ``/plan`` and by ``from_run``'s handling of
an inline template: the same ``resolve_template_config`` a template file goes
through, then the from_run dry-run preview, in the ``FromRunReport`` shape the
run-folder dialog already renders.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import ValidationError

from depictio.cli.cli.utils.data_root import DataRoot
from depictio.cli.cli.utils.template_preview import preview_data_root, report_rows
from depictio.cli.cli.utils.templates import resolve_template_config
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.validate import INVALID


def resolve_inline(
    template: dict[str, Any], root: DataRoot, *, project_name: str | None = None, CLI_config=None
) -> tuple:
    """``resolve_template_config`` over a copy of ``template`` (it is consumed)."""
    try:
        return resolve_template_config(
            copy.deepcopy(template),
            template_dir=None,
            data_root=root,
            project_name=project_name,
            CLI_config=CLI_config,
        )
    except ValueError as exc:
        raise BuilderRefused(422, f"Template resolution failed: {exc}", INVALID) from exc


def check_project(config: dict[str, Any]) -> None:
    """Validate a resolved config against the ``Project`` model, as creation will.

    Permissions are the server's to set at creation, so a stub stands in.
    """
    from depictio.models.models.projects import Project

    candidate = copy.deepcopy(config)
    candidate.pop("template_origin", None)
    candidate.setdefault("permissions", {"owners": [], "editors": [], "viewers": []})
    try:
        Project.model_validate(candidate)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ()))
        raise BuilderRefused(422, f"{where}: {first.get('msg')}", INVALID) from exc


def declared_variables(resolved: dict[str, str], metadata) -> dict[str, str]:
    """The resolved variables an ad-hoc template declares (``DATA_ROOT``).

    Resolution also fills generic defaults (``GROUP_COL``, ``METADATA_ID_COL``)
    that only a catalogue template's dashboards read; reporting them would
    offer settings the builder's template has no use for.
    """
    names = {variable.name for variable in metadata.variables}
    return {name: value for name, value in resolved.items() if name in names}


def plan_inline(
    template: dict[str, Any], root: DataRoot, *, project_name: str | None = None
) -> dict[str, Any]:
    """A dry-run ``FromRunReport`` (as a dict) for ``template`` under ``root``."""
    resolution = resolve_inline(template, root, project_name=project_name)
    config, metadata, _origin, _dashboards, _variables = resolution
    check_project(config)
    preview = preview_data_root(
        template_id=metadata.template_id, data_root=root, resolution=resolution
    )
    return {
        "project_id": None,
        "project_name": config.get("name") or "",
        "template_id": metadata.template_id,
        "detected_template": None,
        "data_root": root.location,
        "detected_runs": list(preview.detected_runs),
        "resolved_variables": declared_variables(preview.resolved_variables, metadata),
        "data_collections": [row.model_dump() for row in report_rows(preview.data_collections)],
        "dashboards": [],
        "pruned_optional_dcs": list(preview.pruned_optional_dcs),
        "truncated": preview.truncated,
        "run_info": None,
        "input_files": [],
        "run_id": None,
        "storage_saved": False,
        "dry_run": True,
        "success": True,
    }
