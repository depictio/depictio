"""Agent tools that turn a pipeline run folder into a Depictio project.

Thin wrappers around the REST flow behind ``POST /projects/from_run`` (the
browser twin of ``depictio run --template <id> --data-root s3://...``), with
its gates in the same order: the public/demo-mode refusal of
``_reject_non_admin_in_public_mode``, the long-lived CLI token the workers
authenticate with, then ``_create_project_from_run`` itself, which owns every
data check (template id shape, ``s3://`` only, the remote-bucket allowlist,
variables and data collections confined to the data root, project name
uniqueness). Nothing is re-implemented here, so the agent can read exactly what
a browser user could, and no local path on the server is ever listed: the REST
route refuses anything but an ``s3://`` prefix, and so do these tools.

Template auto-detection (``detect_template_from_run_dir``) reads a local run
directory, which the server must not do on a caller's behalf, so a template id
is always required; ``list_templates`` is how an agent picks one.

Every tool here is hidden unless ``settings.mcp.enable_ingest`` is on. The two
that touch a data root also need the ``ingest`` scope; the read-only listing
and status tools need ``read``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.registry import ToolError, agent_tool
from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import projects_collection
from depictio.api.v1.endpoints.projects_endpoints import from_run, manifest_ingest
from depictio.api.v1.endpoints.projects_endpoints.from_manifest import validate_template_id
from depictio.api.v1.endpoints.projects_endpoints.templates_catalog import list_templates_catalog

MAX_REPORTED_RUNS = 5


def _ingest_enabled() -> bool:
    return bool(settings.mcp.enable_ingest)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListTemplatesArgs(_Args):
    pass


class RunArgs(_Args):
    data_root: str = Field(
        description="An s3:// prefix holding one pipeline run's output (local paths are refused)."
    )
    template_id: str = Field(description="A template id from list_templates.")
    project_name: str | None = Field(
        default=None, max_length=200, description="Defaults to the template's project name."
    )
    variables: dict[str, str] = Field(
        default_factory=dict,
        description="Template variables ({VAR} placeholders); values must stay under data_root.",
    )

    @field_validator("template_id")
    @classmethod
    def _well_formed_template_id(cls, value: str) -> str:
        return validate_template_id(value)


class IngestionStatusArgs(_Args):
    run_id: str | None = Field(
        default=None, description="The run_id create_project_from_run returned."
    )
    project_id: str | None = Field(
        default=None, description="A project: its ingestion report (expected vs found)."
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> IngestionStatusArgs:
        if (self.run_id is None) == (self.project_id is None):
            raise ValueError("give exactly one of run_id or project_id")
        return self


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _reject_in_public_mode(user: Any) -> None:
    """``POST /projects/from_run``'s own gate (lazy: the routes module is heavy)."""
    from depictio.api.v1.endpoints.projects_endpoints.routes import (
        _reject_non_admin_in_public_mode,
    )

    _reject_non_admin_in_public_mode(user, "Project creation")


def _run_from_folder(ctx: ToolContext, args: RunArgs, *, dry_run: bool) -> dict[str, Any]:
    report = from_run._create_project_from_run(
        data_root=args.data_root,
        template_id=args.template_id,
        current_user=ctx.user,
        project_name=args.project_name,
        variables=dict(args.variables),
        dry_run=dry_run,
    )
    return report.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@agent_tool(
    name="list_templates",
    scope="read",
    description=(
        "The project templates this server ships (one per pipeline and version): template_id, "
        "name, description, version, the variables a run may need and how many dashboards "
        "it brings. Use a template_id with preview_run / create_project_from_run."
    ),
    input_model=ListTemplatesArgs,
    enabled=_ingest_enabled,
)
async def list_templates(ctx: ToolContext, args: ListTemplatesArgs) -> dict[str, Any]:
    catalog = await asyncio.to_thread(list_templates_catalog)
    return {
        "templates": [
            {
                "template_id": t.template_id,
                "name": t.name,
                "description": t.description,
                "version": t.version,
                "variables": [v.model_dump() for v in t.variables],
                "dashboards": len(t.dashboards),
            }
            for t in catalog.templates
        ]
    }


@agent_tool(
    name="preview_run",
    scope="ingest",
    description=(
        "Dry run of create_project_from_run: resolve the template against an s3:// run "
        "folder and report, per data collection, how many files it would match and which "
        "are missing, plus the detected runs and resolved variables. Creates nothing. "
        "Run it first and check that required collections are 'ok'."
    ),
    input_model=RunArgs,
    enabled=_ingest_enabled,
)
async def preview_run(ctx: ToolContext, args: RunArgs) -> dict[str, Any]:
    _reject_in_public_mode(ctx.user)
    return await asyncio.to_thread(_run_from_folder, ctx, args, dry_run=True)


@agent_tool(
    name="create_project_from_run",
    scope="ingest",
    description=(
        "Create a project (owned by the user) from a template and an s3:// run folder, "
        "import the template's dashboards and hand ingestion to background workers. "
        "Fails with 409 when the project name exists. Returns the project id and a run_id: "
        "ingestion takes minutes, poll get_ingestion_status(run_id). Call preview_run first."
    ),
    input_model=RunArgs,
    writes=True,
    enabled=_ingest_enabled,
)
async def create_project_from_run(ctx: ToolContext, args: RunArgs) -> dict[str, Any]:
    _reject_in_public_mode(ctx.user)
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _ensure_user_cli_token,
    )

    await _ensure_user_cli_token(ctx.user)
    return await asyncio.to_thread(_run_from_folder, ctx, args, dry_run=False)


def _status(ctx: ToolContext, args: IngestionStatusArgs) -> dict[str, Any]:
    if args.run_id is not None:
        # Owner-or-admin check and the 404 for unknown runs live in the helper.
        report = manifest_ingest._get_refresh_run_report(args.run_id, ctx.user)
        from depictio.api.v1.monitoring import store

        run = store.get_ingestion_run(args.run_id) or {}
        return {
            **report.model_dump(mode="json"),
            "status": run.get("status"),
            "finished": run.get("status") not in (None, "running"),
        }

    from bson import ObjectId

    from depictio.api.v1.endpoints.projects_endpoints.ingestion_report import (
        build_ingestion_report,
    )
    from depictio.api.v1.endpoints.projects_endpoints.utils import _async_get_project_from_id

    try:
        project_oid = ObjectId(args.project_id)
    except Exception as exc:
        raise ToolError(f"Invalid project_id: {args.project_id!r}", status=400) from exc
    project = _async_get_project_from_id(project_oid, ctx.user, projects_collection)
    report = build_ingestion_report(project).model_dump(mode="json")
    report["runs"] = report.get("runs", [])[:MAX_REPORTED_RUNS]
    # Parameters and tool versions of the pipeline run: large, and not a status.
    report.pop("run_provenance", None)
    return report


@agent_tool(
    name="get_ingestion_status",
    scope="read",
    description=(
        "Ingestion progress. With run_id (from create_project_from_run): per data collection "
        "status (ingested/failed/skipped) and whether the run finished. With project_id: the "
        "project's ingestion report, expected vs identified data collections and a health "
        "summary."
    ),
    input_model=IngestionStatusArgs,
    enabled=_ingest_enabled,
)
async def get_ingestion_status(ctx: ToolContext, args: IngestionStatusArgs) -> dict[str, Any]:
    return await asyncio.to_thread(_status, ctx, args)
