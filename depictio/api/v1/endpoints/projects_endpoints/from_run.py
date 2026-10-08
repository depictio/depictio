"""Create a project from a template and a run folder (RFC remote-data, phase 4).

``POST /projects/from_run`` is the browser twin of
``depictio ingest <run folder> --template <id>``: name a template and an
``s3://`` run prefix, get back what each data collection would find under it,
and - unless it is a dry run - a project whose ingestion has been handed to
Celery workers.

The engine is entirely reused. ``resolve_template`` produces the project config
(repointing every data collection at the remote root), ``preview_data_root``
reports what each of them would match, and the refresh machinery in
:mod:`manifest_ingest` carries the fan-out. This module is the HTTP shape
around them plus the two checks a browser-facing caller needs that the CLI does
not: the data root has to be an object-store prefix this server is allowed to
read, and the resolved data collections have to stay inside it.

The data root is built **once** and handed to both ``resolve_template`` and
``preview_data_root``. Both accept a pre-built root; passing the location twice
would cost two full S3 listings for one request.

How the run folder is read is decided from the same inputs the workers decide
from, so the preview never accepts a folder the ingestion then refuses (see
:func:`_run_folder_read_config`). A refused or failed S3 read is left to
propagate as ``S3AccessError``: the API answers it with ``{detail, code}``.

Synchronous throughout (the CLI helpers use sync httpx back into this same
FastAPI process) - the route dispatches via ``asyncio.to_thread``. Ingestion
itself is not: a real run folder is minutes of work, so it goes to workers and
the caller polls ``GET /projects/refresh_manifest/{run_id}``.
"""

import copy
from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.api.v1.db import projects_collection
from depictio.api.v1.endpoints.projects_endpoints.from_manifest import (
    DashboardImportResult,
    _import_template_dashboards,
    _refuse_a_taken_project_name,
    _template_not_found_detail,
    validate_template_id,
)
from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import (
    _dispatch_refresh_tasks,
)
from depictio.models.logging import logger
from depictio.models.s3_access import ProjectS3Config, S3AccessError

DATA_ROOT_RULE = (
    "data_root must be an s3:// prefix. The server cannot list a directory on the "
    "machine running the browser, and an https:// URL exposes no listing operation, "
    "so a run folder has to be named as an object-store prefix."
)

# Scan modes whose resolved parameters name a location, and the parameter that
# holds it. ``manifest`` is deliberately absent: its URL is a document fetched
# through the SSRF gateway at ingest time, which is that mode's own control,
# and it is never expected to live under the run folder.
_SCAN_LOCATION_FIELDS = {
    "single": "filename",
    "url": "url",
    "s3_prefix": "prefix",
}


class FromRunRequest(BaseModel):
    """Body of POST /projects/from_run."""

    # An s3:// prefix holding one pipeline run's output.
    data_root: str
    template_id: str
    project_name: str | None = None
    # Extra template variables ({VAR} placeholders), same as ``--var`` on the CLI.
    variables: dict[str, str] = Field(default_factory=dict)
    # Plan-only: resolve + preview without creating or ingesting anything.
    dry_run: bool = False

    @field_validator("template_id")
    @classmethod
    def _well_formed_template_id(cls, value: str) -> str:
        return validate_template_id(value)


class FromRunDCPreview(BaseModel):
    """What one data collection would find under the data root.

    The wire shape of ``template_preview.DataCollectionPreview``: ``status`` is
    one of ``ok`` / ``empty`` / ``missing`` / ``pruned`` and ``kind`` is
    ``scan`` or ``recipe``.
    """

    data_collection_tag: str
    kind: str
    mode: str | None = None
    location: str = ""
    matched: int = 0
    missing_sources: list[str] = Field(default_factory=list)
    optional: bool = False
    status: str = "ok"


class FromRunReport(BaseModel):
    """Result of a from_run request: the plan, and what was created from it.

    ``success`` answers "did the request do what it was asked": the project was
    created, its dashboards imported, and every ingestable data collection
    handed to a worker. It deliberately does *not* flip because a collection
    came up ``missing`` - that is a fact about the run folder, reported per
    collection, and the ingestion's own verdict arrives later on ``run_id``.
    """

    project_id: str | None = None
    project_name: str
    template_id: str
    data_root: str
    detected_runs: list[str] = Field(default_factory=list)
    resolved_variables: dict[str, str] = Field(default_factory=dict)
    data_collections: list[FromRunDCPreview] = Field(default_factory=list)
    dashboards: list[DashboardImportResult] = Field(default_factory=list)
    pruned_optional_dcs: list[str] = Field(default_factory=list)
    truncated: bool = False
    # Ingestion-run id to poll via GET /projects/refresh_manifest/{run_id}.
    run_id: str | None = None
    dry_run: bool = False
    success: bool = False


def _dc_locations(workflow: dict[str, Any], dc: dict[str, Any]) -> list[str]:
    """Every location the resolved data collection would read from.

    Recipe collections are absent on purpose: they have no scan block, and
    their sources are resolved *through* the data root by the recipe layer, so
    they cannot name a location of their own.
    """
    scan = ((dc.get("config") or {}).get("scan")) or {}
    mode = str(scan.get("mode") or "").lower()
    parameters = scan.get("scan_parameters") or {}

    field = _SCAN_LOCATION_FIELDS.get(mode)
    if field:
        value = parameters.get(field)
        return [str(value)] if value else []
    if mode == "recursive":
        # A local walk names its bases on the workflow, not on the DC.
        return [str(loc) for loc in (workflow.get("data_location") or {}).get("locations") or []]
    return []


def _assert_data_collections_confined(config: dict[str, Any], root) -> None:
    """Refuse a resolved template whose data collections reach outside the root.

    A security control, and a correctness check with it: a collection pointing
    somewhere other than the run folder cannot be part of that run anyway.

    Nothing else catches it. ``ScanSingle.validate_filename`` performs no path
    validation in server context (its existence check is gated on
    ``DEPICTIO_CONTEXT == "cli"``), and ``bindings.remote_scan_for_dc`` copies a
    ``single`` collection's ``filename`` through verbatim into ``url`` mode, so
    an absolute path such as ``/app/depictio/...`` - where the JWT signing key
    is mounted - would otherwise survive resolution and be registered as a file
    for the worker to read. The preview does not catch it either: a location
    outside the root is reported ``ok`` with no matches, because from the
    preview's point of view it simply cannot be counted.

    Every template on this instance is one the maintainers shipped, so today
    this should never fire. It becomes the primary control the moment uploaded
    template bundles land, which is why it is written now rather than then.
    """
    for workflow in config.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            tag = dc.get("data_collection_tag") or "?"
            for location in _dc_locations(workflow, dc):
                # ``relative_of`` answering None is the root's own definition of
                # "not mine": a different bucket, a foreign scheme, or an
                # absolute path on this container's filesystem.
                if root.relative_of(location) is None:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Data collection '{tag}' resolves to '{location}', which is not "
                            f"under the data root '{root.location}'. A template used from a "
                            "run folder must read only from that folder."
                        ),
                    )


@dataclass(frozen=True)
class _RunFolderReads:
    """The two fields of a CLI configuration ``remote_fetch.s3_read_target`` reads.

    Deciding how a location is read needs no user and no token, and a dry run
    mints none, so the preview carries these two alone.
    """

    s3_storage: S3DepictioCLIConfig
    remote_storage_options: ProjectS3Config | None = None


def _run_folder_read_config() -> _RunFolderReads:
    """The read configuration of the preview, the same the workers will read with.

    A worker reads with ``_build_cli_config_for_user``: the instance's S3
    settings (``settings.s3``, which name the instance's own bucket, refused as
    a data source) and the project's storage settings (``project_storage_for``).
    A project created from a run folder has no storage settings yet, so both
    sides decide from the instance settings and the bucket lists alone: an
    administrator-listed public bucket is read unsigned, a credentialed one with
    the server's own credentials, anything else is refused.
    """
    from depictio.api.v1.configs.config import settings

    return _RunFolderReads(s3_storage=settings.s3)


def _build_data_root(data_root: str, read_config: _RunFolderReads):
    """The one :class:`DataRoot` this request answers every question from.

    Refused by ``S3DataRoot.__init__`` from configuration alone, before a
    single request goes out, when the configuration does not allow the read
    (``S3AccessRefused``, see :func:`_run_folder_read_config`), so a bucket
    name never becomes an existence-and-region oracle.
    """
    if not data_root.lower().startswith("s3://"):
        raise HTTPException(status_code=422, detail=DATA_ROOT_RULE)

    from depictio.cli.cli.utils.data_root import as_data_root

    try:
        root = as_data_root(data_root, read_config)
    except S3AccessError:
        raise
    except ValueError as exc:
        # A malformed prefix: the caller's to fix, and nothing has talked to S3.
        raise HTTPException(status_code=422, detail=str(exc))
    if root is None:  # pragma: no cover - as_data_root only returns None for None
        raise HTTPException(status_code=422, detail=DATA_ROOT_RULE)
    return root


def _assert_variables_confined(variables: dict[str, str], root) -> None:
    """Refuse a template variable whose value would read from outside the data root.

    ``resolve_template``'s ``{VAR}`` substitution has a local-filesystem
    fallback for a value that doesn't resolve under the given root: right for
    the CLI, where the run lives on the operator's own disk and a path
    elsewhere on it is unremarkable, wrong for a server accepting a variable
    from a browser, which must never go probing its own filesystem on a
    user's behalf. Gating that fallback itself on CLI context is the other
    half of this fix, in ``templates.py``; this is the clear error in front
    of it, raised before ``resolve_template`` ever runs.

    A value with no leading ``/``, no ``://`` and no ``..`` segment is a plain
    key relative to the root (``"input/Metadata_full.tsv"``, ``"habitat"``)
    and passes untouched: that's the overwhelming majority of variables, and
    they can't name anything outside the root to begin with. A ``..`` segment
    is refused outright: unlike an absolute path or a URL, a literal ``..`` in
    an otherwise root-relative value is not something ``root.relative_of``
    resolves away, so it cannot be trusted to answer for it.
    """
    for name, value in variables.items():
        segments = value.split("/")
        if ".." in segments:
            escapes = True
        elif value.startswith("/") or "://" in value:
            escapes = root.relative_of(value) is None
        else:
            escapes = False
        if escapes:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Variable '{name}' points outside the data root '{root.location}'. "
                    "A template used from a run folder must read only from that folder."
                ),
            )


def _skip_reason(row) -> str:
    """Why a data collection the preview called ``missing`` isn't dispatched.

    Used verbatim for a required collection's failed-step detail; prefixed
    with "Skipped optional collection: " for an optional one's skipped-step
    detail (see the ``preflight_failed`` / ``preflight_skipped`` split in
    ``_create_project_from_run``).
    """
    if row.missing_sources:
        return (
            "Not ingested: source(s) not found under the data root: "
            f"{', '.join(row.missing_sources)}."
        )
    return f"Not ingested: '{row.location}' is not present under the data root."


def _create_project_from_run(
    *,
    data_root: str,
    template_id: str,
    current_user,
    project_name: str | None = None,
    variables: dict[str, str] | None = None,
    dry_run: bool = False,
) -> FromRunReport:
    """The full run folder → project + dashboards + dispatched ingestion flow.

    Sync: call via ``asyncio.to_thread``.
    """
    # The request model already enforces this; re-checked here so direct
    # callers cannot hand resolve_template a path either.
    try:
        validate_template_id(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    read_config = _run_folder_read_config()
    root = _build_data_root(data_root, read_config)
    _assert_variables_confined(variables or {}, root)

    # One root, two consumers. resolve_template gives the config the project is
    # built from; preview_data_root gives the per-collection rows the UI shows.
    # Both take a pre-built root, so this whole request costs one S3 listing.
    from depictio.cli.cli.utils.templates import resolve_template

    try:
        resolved_config, template_metadata, _origin, dashboard_paths, resolved_vars = (
            resolve_template(
                template_id=template_id,
                data_root=root,
                project_name=project_name,
                extra_vars=dict(variables) if variables else None,
                CLI_config=read_config,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_template_not_found_detail(template_id, exc))
    except S3AccessError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Template resolution failed: {exc}")

    # Before anything is previewed, let alone created: nothing this template
    # resolved to may point outside the run folder.
    _assert_data_collections_confined(resolved_config, root)

    from depictio.cli.cli.utils.template_preview import preview_data_root

    try:
        preview = preview_data_root(
            template_id=template_id,
            data_root=root,
            variables=dict(variables) if variables else None,
            CLI_config=read_config,
        )
    except FileNotFoundError as exc:  # pragma: no cover - resolution already passed
        raise HTTPException(status_code=404, detail=_template_not_found_detail(template_id, exc))
    except S3AccessError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Data root preview failed: {exc}")

    rows = {
        row.tag: FromRunDCPreview(
            data_collection_tag=row.tag,
            kind=row.kind,
            mode=row.mode,
            location=row.location,
            matched=row.matched,
            missing_sources=list(row.missing_sources),
            optional=row.optional,
            status=row.status,
        )
        for row in preview.data_collections
    }
    report = FromRunReport(
        project_name=resolved_config.get("name", ""),
        template_id=template_metadata.template_id,
        data_root=root.location,
        detected_runs=list(preview.detected_runs),
        resolved_variables=dict(preview.resolved_variables),
        data_collections=list(rows.values()),
        pruned_optional_dcs=list(preview.pruned_optional_dcs),
        truncated=preview.truncated,
        dry_run=dry_run,
    )

    if dry_run:
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
    create_payload["registration_time"] = utc_now_str()
    create_payload["last_modified"] = create_payload["registration_time"]
    projects_collection.insert_one(create_payload)
    project_oid = create_payload["_id"]
    report.project_id = str(project_oid)

    # Import the template's dashboards in-process, before the workers start:
    # the shared import handler binds DC tags to the ids just persisted and
    # drops components whose optional DC was pruned (self-adapting import).
    report.dashboards = _import_template_dashboards(
        dashboard_paths,
        template_id=template_metadata.template_id,
        project_id=project_oid,
        variables=resolved_vars,
        current_user=current_user,
    )
    all_ok = all(entry.success for entry in report.dashboards)

    # Fan the ingestion out. Everything the workers need is on the project
    # document, which they re-read for themselves; the run document in Mongo is
    # the durable status of record.
    stored = projects_collection.find_one({"_id": project_oid}) or {}
    to_dispatch: list[tuple[str, str, int, int]] = []
    preflight_failed: list[tuple[str, str, str]] = []
    preflight_skipped: list[tuple[str, str, str]] = []
    scan_modes: dict[str, str] = {}
    for wf_index, workflow_dict in enumerate(stored.get("workflows") or []):
        for dc_dict in workflow_dict.get("data_collections") or []:
            tag = str(dc_dict.get("data_collection_tag") or "")
            dc_id = str(dc_dict.get("_id") or dc_dict.get("id") or "")
            scan = (dc_dict.get("config") or {}).get("scan") or {}
            scan_modes[tag] = str(scan.get("mode") or "") or "recipe"
            row = rows.get(tag)
            # A collection whose source is not there will never ingest. A
            # required one is seeded as a failed step saying why, instead of
            # showing the UI a task that was never going to succeed; one the
            # template itself marks optional is a nominal absence (a route the
            # run didn't take), seeded "skipped" so the run can still close
            # clean around it. (A ``pruned`` collection is not in the project
            # at all: resolution dropped it, so it cannot reach this loop;
            # the report's rows carry its reason.)
            if row is not None and row.status == "missing":
                if row.optional:
                    preflight_skipped.append(
                        (tag, dc_id, f"Skipped optional collection: {_skip_reason(row)}")
                    )
                else:
                    preflight_failed.append((tag, dc_id, _skip_reason(row)))
                continue
            to_dispatch.append((tag, dc_id, wf_index, row.matched if row else 0))

    if to_dispatch or preflight_failed or preflight_skipped:
        run_id, all_dispatched, _results = _dispatch_refresh_tasks(
            project_dict=stored,
            to_dispatch=to_dispatch,
            current_user=current_user,
            preflight_failed=preflight_failed,
            preflight_skipped=preflight_skipped,
            command="from_run",
            scan_modes=scan_modes,
            data_root=root.location,
        )
        report.run_id = run_id
        all_ok = all_ok and all_dispatched
    else:
        logger.warning(
            f"from_run created project '{report.project_name}' with no ingestable "
            "data collection; no ingestion run was opened."
        )

    report.success = all_ok
    return report
