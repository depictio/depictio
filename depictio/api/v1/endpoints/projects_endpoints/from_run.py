"""Create a project from a template and a run folder (RFC remote-data, phase 4).

``POST /projects/from_run`` is the browser twin of
``depictio ingest <run folder> --template <id>``: name a template and an
``s3://`` run prefix, get back what each data collection would find under it,
and - unless it is a dry run - a project whose ingestion has been handed to
Celery workers. Without a template, the pipeline is recognised from the folder
itself (``run_detection.detect_template_for_root``).

On a server that is the user's own computer (``depictio local``, see
``settings_models.local_data_policy``) the run folder may also be a folder on
that disk: an absolute or ``~/`` path, confined to the allowed roots, read only
for a request from this machine (loopback ``Host``) by an administrator, and no
larger than :data:`MAX_LOCAL_RUN_FILES` files.

The engine is entirely reused. ``resolve_template`` produces the project config
(repointing every data collection at the remote root), ``preview_data_root``
reports what each of them would match, and the refresh machinery in
:mod:`manifest_ingest` carries the fan-out. This module is the HTTP shape
around them plus the two checks a browser-facing caller needs that the CLI does
not: the data root has to be an object-store prefix (or allowed local folder)
this server may read, and the resolved data collections have to stay inside it.

The data root is built **once** and handed to both ``resolve_template`` and
``preview_data_root``. Both accept a pre-built root; passing the location twice
would cost two full S3 listings for one request.

What the preview says decides what is dispatched (:func:`_preflight_split`),
and a later refresh of the project decides again the same way against the same
folder (:func:`_refresh_preflight`), so a folder that created cleanly refreshes
cleanly.

How the run folder is read is decided from the same inputs the workers decide
from, so the preview never accepts a folder the ingestion then refuses (see
:func:`_run_folder_read_config`). A run folder in a private bucket comes with
storage settings (``FromRunRequest.storage``): the preview reads with them
alone, and the creation stores them on the new project before any worker
starts, so the workers read with the same ones. A refused or failed S3 read
is left to propagate as ``S3AccessError``: the API answers it with
``{detail, code}``. So does every refusal raised here as
``CodedHTTPException`` (a local folder, an unrecognised pipeline), which the
route turns into the same body.

Synchronous throughout (the CLI helpers use sync httpx back into this same
FastAPI process) - the route dispatches via ``asyncio.to_thread``. Ingestion
itself is not: a real run folder is minutes of work, so it goes to workers and
the caller polls ``GET /projects/refresh_manifest/{run_id}``.
"""

import os
from dataclasses import dataclass
from typing import Any, Literal

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig, local_data_policy
from depictio.api.v1.db import projects_collection
from depictio.api.v1.endpoints.projects_endpoints.from_manifest import (
    DashboardImportResult,
    _import_template_dashboards,
    _new_project_document,
    _template_not_found_detail,
    validate_template_id,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import (
    CodedHTTPException,
    require_local_caller,
)
from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import (
    _dispatch_refresh_tasks,
    _skip_dependants_of_absent_collections,
)
from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
    ProjectStorageConfigIn,
    RunStorageIn,
    read_settings,
)
from depictio.models.local_access import LocalPathRefused
from depictio.models.logging import logger
from depictio.models.s3_access import ProjectS3Config, S3AccessError, is_s3_url

DATA_ROOT_RULE = (
    "data_root must be an s3:// prefix. The server cannot list a directory on the "
    "machine running the browser, and an https:// URL exposes no listing operation, "
    "so a run folder has to be named as an object-store prefix."
)
DATA_ROOT_RULE_LOCAL = (
    "data_root must be an s3:// prefix or a folder on this computer: an absolute path "
    "such as /Users/me/results/run42, or one starting with ~/."
)
LOCAL_FOLDERS_OFF = (
    "This server does not read folders on its own disk, so data_root must be an s3:// "
    "prefix. Folders on your computer can be used when Depictio runs on it, with "
    "`depictio local`."
)

# A run folder with more files than this is refused rather than walked: it is
# far past one pipeline run, and most likely a parent folder picked by mistake.
# Matches the ceiling on one S3 listing (``data_root.DEFAULT_MAX_KEYS``).
MAX_LOCAL_RUN_FILES = 100_000


class FromRunRequest(BaseModel):
    """Body of POST /projects/from_run."""

    # One pipeline run's output: an s3:// prefix, or, when local folders are
    # on, an absolute or ~/ path on the server's disk.
    data_root: str
    # None: recognise the pipeline from the folder.
    template_id: str | None = None
    project_name: str | None = None
    # Extra template variables ({VAR} placeholders), same as ``--var`` on the CLI.
    variables: dict[str, str] = Field(default_factory=dict)
    # Plan-only: resolve + preview without creating or ingesting anything.
    dry_run: bool = False
    # A private bucket's endpoint and keys, for an s3:// data_root only: the
    # run folder is read with them alone, and they become the new project's
    # storage settings. Ignored for a folder on this computer.
    storage: RunStorageIn | None = None

    @field_validator("template_id")
    @classmethod
    def _well_formed_template_id(cls, value: str | None) -> str | None:
        return None if value is None else validate_template_id(value)


class DetectedTemplate(BaseModel):
    """What the run folder said about the run that produced it.

    The other fields are None when the folder did not say. ``template_id`` is
    nullable to match the viewer's type, but a report always names one: a
    folder no installed template fits is a 422 ``template_not_detected``.
    ``GET /projects/folder_inspect`` answers in the same shape, and there it
    can be None.

    ``match`` says how the template was chosen: ``exact`` when its version is
    the run's, ``closest`` when it is another version of the same pipeline,
    ``none`` when no installed template fits the run.
    """

    template_id: str | None = None
    template_version: str | None = None
    pipeline: str | None = None
    version: str | None = None
    engine: str | None = None
    match: Literal["exact", "closest", "none"] | None = None


def describe_detection(template_id: str | None, info) -> DetectedTemplate | None:
    """What ``run_detection.detect_template_for_root`` answered, in the report's shape.

    None when no engine recognised the folder (``info`` is None). The template
    is an ``exact`` match when it is one of the ids the run itself suggests
    (``WorkflowRunInfo.template_ids``: its version as written, or normalised),
    and ``closest`` otherwise, since ``select_template_for_run`` falls back to
    another shipped version of the same pipeline only.
    """
    if info is None:
        return None
    if not template_id:
        match = "none"
    elif template_id in info.template_ids():
        match = "exact"
    else:
        match = "closest"
    return DetectedTemplate(
        template_id=template_id or None,
        template_version=template_id.rsplit("/", 1)[-1] if template_id else None,
        pipeline=info.pipeline_name,
        version=info.pipeline_version,
        engine=info.engine,
        match=match,
    )


class FromRunRecipeSource(BaseModel):
    """What one source of a recipe found under the data root.

    The wire shape of ``template_preview.RecipeSourcePreview``: ``kind`` is
    ``collection`` for a source read from another data collection, ``file``
    for a glob or a path, and ``url`` for a URL outside the data root, which
    is read at ingest and so is neither found nor missing here (``found`` is
    None).
    """

    ref: str
    kind: Literal["file", "collection", "url"]
    pattern: str | None = None
    dc_ref: str | None = None
    optional: bool = False
    matched: int = 0
    samples: list[str] = Field(default_factory=list)
    found: bool | None = None


class FromRunRecipePreview(BaseModel):
    """The recipe a data collection is built with, and what each of its sources found."""

    name: str
    summary: str | None = None
    sources: list[FromRunRecipeSource] = Field(default_factory=list)


class FromRunDCPreview(BaseModel):
    """What one data collection would find under the data root.

    The wire shape of ``template_preview.DataCollectionPreview``: ``status`` is
    one of ``ok`` / ``empty`` / ``missing`` / ``pruned`` and ``kind`` is
    ``scan`` or ``recipe``. ``rule`` is what a scanning collection looks for,
    as the template wrote it, ``samples`` the first few locations it matched,
    and ``recipe`` is set for a recipe collection.
    """

    data_collection_tag: str
    kind: str
    mode: str | None = None
    location: str = ""
    matched: int = 0
    missing_sources: list[str] = Field(default_factory=list)
    optional: bool = False
    status: str = "ok"
    rule: str | None = None
    samples: list[str] = Field(default_factory=list)
    recipe: FromRunRecipePreview | None = None


def _report_recipe(recipe) -> FromRunRecipePreview | None:
    """A ``template_preview.RecipePreview`` in the report's shape, None for none."""
    if recipe is None:
        return None
    return FromRunRecipePreview(
        name=recipe.name,
        summary=recipe.summary,
        sources=[
            FromRunRecipeSource(
                ref=source.ref,
                kind=source.kind,
                pattern=source.pattern,
                dc_ref=source.dc_ref,
                optional=source.optional,
                matched=source.matched,
                samples=list(source.samples),
                found=source.found,
            )
            for source in recipe.sources
        ],
    )


def _report_rows(preview_rows) -> list[FromRunDCPreview]:
    """``template_preview.DataCollectionPreview`` rows in the report's shape, one per tag."""
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
            rule=row.rule,
            samples=list(row.samples),
            recipe=_report_recipe(row.recipe),
        )
        for row in preview_rows
    }
    return list(rows.values())


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
    # The template used: the one asked for, or the one detected.
    template_id: str
    # Set whenever detection ran (no template_id in the request).
    detected_template: DetectedTemplate | None = None
    data_root: str
    detected_runs: list[str] = Field(default_factory=list)
    resolved_variables: dict[str, str] = Field(default_factory=dict)
    data_collections: list[FromRunDCPreview] = Field(default_factory=list)
    dashboards: list[DashboardImportResult] = Field(default_factory=list)
    pruned_optional_dcs: list[str] = Field(default_factory=list)
    truncated: bool = False
    # Ingestion-run id to poll via GET /projects/refresh_manifest/{run_id}.
    run_id: str | None = None
    # The request's storage settings were stored on the created project.
    storage_saved: bool = False
    dry_run: bool = False
    success: bool = False


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

    The locations are those of ``bindings.scan_locations``: a recipe collection
    names none, and a ``manifest`` one's URL is a document fetched through the
    SSRF gateway at ingest time, that mode's own control, never expected to
    live under the run folder.
    """
    from depictio.cli.cli.utils.bindings import scan_locations

    for workflow in config.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            tag = dc.get("data_collection_tag") or "?"
            for location in scan_locations(workflow, dc):
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
    """The fields of a CLI configuration ``remote_fetch.s3_read_target`` reads.

    Deciding how a location is read needs no user and no token, and a dry run
    mints none, so the preview carries these alone. ``storage_only``: the
    storage settings were typed in with the request, and decide every read.
    """

    s3_storage: S3DepictioCLIConfig
    remote_storage_options: ProjectS3Config | None = None
    storage_only: bool = False


def _run_folder_read_config(storage: ProjectS3Config | None = None) -> _RunFolderReads:
    """The read configuration of the preview, the same the workers will read with.

    A worker reads with ``_build_cli_config_for_user``: the instance's S3
    settings (``settings.s3``, which name the instance's own bucket, refused as
    a data source) and the project's storage settings (``project_storage_for``).

    Without ``storage`` the project has none, so both sides decide from the
    instance settings and the bucket lists alone: an administrator-listed
    public bucket is read unsigned, a credentialed one with the server's own
    credentials, anything else is refused. With ``storage`` (settings typed in
    for a private bucket, stored on the project when it is created) every read
    is made with them and nothing else, the instance's bucket still refused.
    """
    from depictio.api.v1.configs.config import settings

    return _RunFolderReads(
        s3_storage=settings.s3, remote_storage_options=storage, storage_only=storage is not None
    )


def _is_local_path(data_root: str) -> bool:
    """Whether ``data_root`` is spelled as a path on this disk: absolute or ``~/``."""
    return data_root.startswith("/") or data_root == "~" or data_root.startswith("~/")


def _holds_more_files_than(folder: str, limit: int) -> bool:
    """Whether ``folder`` holds more than ``limit`` files, counting no further.

    ``followlinks=False``: a symlinked directory is neither walked nor counted
    into, so a link to a large tree elsewhere cannot make the walk endless.
    """
    count = 0
    for _dirpath, _dirnames, filenames in os.walk(folder, followlinks=False):
        count += len(filenames)
        if count > limit:
            return True
    return False


def _build_local_data_root(data_root: str, *, request, current_user):
    """A :class:`LocalDataRoot` on the real path of ``data_root``, once allowed.

    Refused, in this order: local folders off (422), a request not from this
    machine or not from an administrator (403, see ``require_local_caller``),
    a path the policy refuses (422, the policy's own message and code), a
    folder holding more than :data:`MAX_LOCAL_RUN_FILES` files (422).
    """
    policy = local_data_policy()
    if policy is None:
        raise CodedHTTPException(422, LOCAL_FOLDERS_OFF, "local_folders_off")
    require_local_caller(request, current_user)
    return _confined_local_root(policy, data_root)


def _confined_local_root(policy, data_root: str):
    """A :class:`LocalDataRoot` on the real path of ``data_root`` under ``policy``.

    The checks on the folder itself, whoever asks: a path the policy refuses
    (422, the policy's own message and code), a folder holding more than
    :data:`MAX_LOCAL_RUN_FILES` files (422).
    """
    try:
        real = policy.confine(data_root, want="dir")
    except LocalPathRefused as exc:
        raise CodedHTTPException(422, exc.detail, exc.code) from exc
    if _holds_more_files_than(real, MAX_LOCAL_RUN_FILES):
        raise CodedHTTPException(
            422,
            f"'{data_root}' holds more than {MAX_LOCAL_RUN_FILES:,} files, far more than "
            "one pipeline run writes. Pick the output folder of a single run.",
            "local_run_too_large",
        )

    from depictio.cli.cli.utils.data_root import LocalDataRoot

    return LocalDataRoot(real)


def _build_data_root(
    data_root: str, read_config: _RunFolderReads, *, request=None, current_user=None
):
    """The one :class:`DataRoot` this request answers every question from.

    Refused by ``S3DataRoot.__init__`` from configuration alone, before a
    single request goes out, when the configuration does not allow the read
    (``S3AccessRefused``, see :func:`_run_folder_read_config`), so a bucket
    name never becomes an existence-and-region oracle. A local path goes
    through :func:`_build_local_data_root`, which needs the request (for its
    ``Host``) and the caller.
    """
    if _is_local_path(data_root):
        return _build_local_data_root(data_root, request=request, current_user=current_user)
    if not is_s3_url(data_root):
        rule = DATA_ROOT_RULE_LOCAL if local_data_policy() is not None else DATA_ROOT_RULE
        raise CodedHTTPException(422, rule, "data_root_unsupported")

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


def _detect_run(root) -> tuple[str | None, Any]:
    """``run_detection.detect_template_for_root`` on ``root``: the template id
    and the run's provenance, each None when not found.

    A read that fails while looking is logged and found nothing, except an S3
    refusal or failure, which propagates with its own code.
    """
    from depictio.cli.cli.utils.run_detection import detect_template_for_root

    try:
        return detect_template_for_root(root)
    except S3AccessError:
        raise
    except (OSError, ValueError) as exc:
        logger.warning(f"Template detection failed for {root.location}: {exc}")
        return None, None


def _detect_template(root) -> tuple[str, DetectedTemplate]:
    """The template id recognised in ``root``, with what the folder said.

    A folder no installed template fits is a 422 coded
    ``template_not_detected``: the caller picks one. A read that fails while
    looking is the same answer, except an S3 refusal or failure, which keeps
    its own code (see :func:`_detect_run`).
    """
    template_id, info = _detect_run(root)
    detected = describe_detection(template_id, info) or DetectedTemplate()
    if not template_id:
        if detected.pipeline:
            run = " ".join(part for part in (detected.pipeline, detected.version) if part)
            detail = (
                f"This folder looks like a {run} run, but no installed template matches "
                "it. Pick a template to continue."
            )
        else:
            detail = (
                "The pipeline that produced this folder was not recognised. Pick a "
                "template to continue."
            )
        raise CodedHTTPException(422, detail, "template_not_detected")
    return template_id, detected


def _skip_reason(row) -> str:
    """The step detail of a data collection the preview called ``missing``,
    which is never dispatched.

    A required collection's failed step says it as is, an optional one's
    skipped step after "Skipped optional collection: " (see
    :func:`_preflight_split`). A required one that misses nothing but absent
    optional collections ends skipped instead, with the detail
    ``_skip_dependants_of_absent_collections`` words for it. Display only:
    what is skipped is decided from the preview's ``missing_collections``,
    never from this text.
    """
    if row.missing_sources:
        return (
            "Not ingested: source(s) not found under the data root: "
            f"{', '.join(row.missing_sources)}."
        )
    return f"Not ingested: '{row.location}' is not present under the data root."


def _missing_collections_only(preview_rows) -> dict[str, list[str]]:
    """``{tag: [collection tag, ...]}`` for each required collection of the
    preview that misses other collections and nothing else (no file of its own).

    What :func:`_preflight_split` skips rather than fails when those
    collections are optional and absent (see
    ``manifest_ingest._skip_dependants_of_absent_collections``). Read from the
    preview rows' ``missing_collections``, so no message wording decides it.
    """
    # ``missing_sources`` lists those collections and the row's own missing
    # files, so the same length means no file of its own.
    return {
        row.tag: list(row.missing_collections)
        for row in preview_rows
        if not row.optional
        and row.missing_collections
        and len(row.missing_collections) == len(row.missing_sources)
    }


@dataclass(frozen=True)
class _Preflight:
    """What the pre-flight decided for each collection of a project.

    In the shapes ``_dispatch_refresh_tasks`` takes: ``to_dispatch`` as
    ``(tag, dc_id, workflow index, files matched)``, the others as
    ``(tag, dc_id, step detail)`` for an already-terminal step.
    """

    to_dispatch: list[tuple[str, str, int, int]]
    failed: list[tuple[str, str, str]]
    skipped: list[tuple[str, str, str]]


def _preflight_split(project_dict: dict[str, Any], preview_rows) -> _Preflight:
    """Split a project's collections on the preview of its run folder.

    The one decision both a creation and a refresh make (see
    :func:`_refresh_preflight`). A collection whose source is not there will
    never ingest, so it is not dispatched: a required one is seeded as a
    failed step saying why, instead of showing the UI a task that was never
    going to succeed; one the template itself marks optional is a nominal
    absence (a route the run didn't take), seeded "skipped" so the run can
    still close clean around it. A required one that misses nothing but such
    collections is skipped too
    (``manifest_ingest._skip_dependants_of_absent_collections``, from the
    rows' ``missing_collections``). Everything else is dispatched, ``empty``
    rows included: the scan's own verdict on those arrives from the worker.

    Decided over every collection of the project, so a caller refreshing
    only some of them still sees each absent optional collection their
    dependants read. A collection with no row (a ``pruned`` one is not in
    the project at all: resolution dropped it) is dispatched.
    """
    rows = {row.tag: row for row in preview_rows}
    to_dispatch: list[tuple[str, str, int, int]] = []
    failed: list[tuple[str, str, str]] = []
    skipped: list[tuple[str, str, str]] = []
    for wf_index, workflow_dict in enumerate(project_dict.get("workflows") or []):
        for dc_dict in workflow_dict.get("data_collections") or []:
            tag = str(dc_dict.get("data_collection_tag") or "")
            dc_id = str(dc_dict.get("_id") or dc_dict.get("id") or "")
            row = rows.get(tag)
            if row is not None and row.status == "missing":
                if row.optional:
                    skipped.append(
                        (tag, dc_id, f"Skipped optional collection: {_skip_reason(row)}")
                    )
                else:
                    failed.append((tag, dc_id, _skip_reason(row)))
                continue
            to_dispatch.append((tag, dc_id, wf_index, row.matched if row else 0))
    failed, skipped = _skip_dependants_of_absent_collections(
        failed, skipped, _missing_collections_only(rows.values())
    )
    return _Preflight(to_dispatch=to_dispatch, failed=failed, skipped=skipped)


def _stored_run_folder(project_dict: dict[str, Any]):
    """The :class:`DataRoot` of the run folder a project was made from, or None.

    ``template_origin.data_root``, read the way the project's refresh workers
    read it (``_build_cli_config_for_user``): an ``s3://`` root with the
    instance's S3 settings and the project's storage settings
    (``project_storage_for``), so the pre-flight reads it exactly as the
    workers will; a folder on this disk only under the active local data
    policy, confined and size-capped as at creation. Not the caller check of
    a creation: that one guards which folder becomes a project, and this one
    already is. The pre-flight reads no more of it than the workers it gates.

    None when there is no data root (a manifest-driven project, or one not
    made from a template), and for a folder on disk that local folders being
    off or the policy now refusing it leaves unread: a shared server that
    happens to see a CLI user's folder refreshes it as it always has, with no
    pre-flight. Raises ``S3AccessError`` when the ``s3://`` root cannot be
    listed.
    """
    data_root = str((project_dict.get("template_origin") or {}).get("data_root") or "")
    if is_s3_url(data_root):
        from depictio.api.v1.configs.config import settings
        from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
            project_storage_for,
        )
        from depictio.cli.cli.utils.data_root import as_data_root

        reads = _RunFolderReads(
            s3_storage=settings.s3, remote_storage_options=project_storage_for(project_dict["_id"])
        )
        try:
            return as_data_root(data_root, reads)
        except ValueError as exc:  # pragma: no cover - creation parsed this very prefix
            logger.warning(f"Refresh pre-flight skipped, data root '{data_root}': {exc}")
            return None
    if _is_local_path(data_root):
        policy = local_data_policy()
        if policy is None:
            return None
        try:
            return _confined_local_root(policy, data_root)
        except CodedHTTPException as exc:
            logger.warning(f"Refresh pre-flight skipped ({exc.code}): {exc.detail}")
            return None
    return None


def _refresh_preflight(project_dict: dict[str, Any]) -> tuple[str, _Preflight] | None:
    """The creation's pre-flight, taken again when a project made from a run
    folder is refreshed: that folder's location, and the split.

    The rows are ``preview_data_collections`` over the stored collections,
    which are the ones the creation previewed, and the split is the
    creation's own (:func:`_preflight_split`), so the same folder gets the
    same verdicts: an optional collection whose source is absent is skipped,
    a required one that only misses such collections is skipped, and one
    missing a source of its own fails. None of those is dispatched, so a
    collection ingested before whose files went away keeps its table as it
    was.

    None when there is no folder to check (see :func:`_stored_run_folder`):
    the refresh then dispatches as it always has.
    """
    root = _stored_run_folder(project_dict)
    if root is None:
        return None

    from depictio.cli.cli.utils.template_preview import preview_data_collections

    rows, _runs = preview_data_collections(project_dict, root)
    return root.location, _preflight_split(project_dict, rows)


def _scan_modes(project_dict: dict[str, Any]) -> dict[str, str]:
    """``{tag: scan mode}`` of every collection of a project, as its ingestion run
    records them: ``"recipe"`` for one with no scan block."""
    modes: dict[str, str] = {}
    for workflow_dict in project_dict.get("workflows") or []:
        for dc_dict in workflow_dict.get("data_collections") or []:
            scan = (dc_dict.get("config") or {}).get("scan") or {}
            tag = str(dc_dict.get("data_collection_tag") or "")
            modes[tag] = str(scan.get("mode") or "") or "recipe"
    return modes


def _save_storage_or_roll_back(project_oid: ObjectId, settings_in: ProjectStorageConfigIn) -> None:
    """Store the new project's storage settings, or delete the project and answer why.

    Called right after the insert, before anything else is made for the
    project, so a failure leaves only the documents removed here. Never says
    or logs more of the error than its type: it was raised holding the secret.
    """
    from depictio.api.v1.endpoints.projects_endpoints import storage_config

    try:
        storage_config._store_project_storage(project_oid, settings_in)
    except Exception as exc:
        # No project without the settings its collections are read with.
        storage_config.project_storage_collection.delete_one({"project_id": project_oid})
        projects_collection.delete_one({"_id": project_oid})
        if isinstance(exc, HTTPException | S3AccessError):
            raise
        logger.error(
            f"Could not save the storage settings of new project {project_oid} "
            f"({type(exc).__name__}); the project was removed."
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "The storage settings could not be saved, so the project was not created. "
                "Try again; if it keeps failing, ask an administrator to check the "
                "server's secrets key."
            ),
        ) from None


def _create_project_from_run(
    *,
    data_root: str,
    template_id: str | None = None,
    current_user,
    project_name: str | None = None,
    variables: dict[str, str] | None = None,
    dry_run: bool = False,
    request=None,
    storage: RunStorageIn | None = None,
) -> FromRunReport:
    """The full run folder → project + dashboards + dispatched ingestion flow.

    ``template_id=None`` recognises the template from the folder. ``request``
    is the HTTP request, which a local data root needs for its ``Host`` guard.
    ``storage`` (an ``s3://`` data root only) is read with alone, validated
    first as a saved config is, and stored on the created project before its
    ingestion is dispatched; a dry run stores nothing.

    Sync: call via ``asyncio.to_thread``.
    """
    # The request model already enforces this; re-checked here so direct
    # callers cannot hand resolve_template a path either.
    if template_id is not None:
        try:
            validate_template_id(template_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    storage_settings = (
        storage.settings_for(data_root) if storage is not None and is_s3_url(data_root) else None
    )
    read_config = _run_folder_read_config(
        read_settings(storage_settings) if storage_settings is not None else None
    )
    root = _build_data_root(data_root, read_config, request=request, current_user=current_user)
    _assert_variables_confined(variables or {}, root)

    detected: DetectedTemplate | None = None
    if template_id is None:
        template_id, detected = _detect_template(root)
        try:
            validate_template_id(template_id)
        except ValueError as exc:  # pragma: no cover - detection yields catalog ids
            raise HTTPException(status_code=422, detail=str(exc))

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

    report = FromRunReport(
        project_name=resolved_config.get("name", ""),
        template_id=template_metadata.template_id,
        detected_template=detected,
        data_root=root.location,
        detected_runs=list(preview.detected_runs),
        resolved_variables=dict(preview.resolved_variables),
        data_collections=_report_rows(preview.data_collections),
        pruned_optional_dcs=list(preview.pruned_optional_dcs),
        truncated=preview.truncated,
        dry_run=dry_run,
    )

    if dry_run:
        report.success = True
        return report

    create_payload = _new_project_document(resolved_config, current_user)
    projects_collection.insert_one(create_payload)
    project_oid = create_payload["_id"]

    # Before the workers start: they read the run folder through
    # ``project_storage_for``, as any later refresh does.
    if storage_settings is not None:
        _save_storage_or_roll_back(project_oid, storage_settings)
        report.storage_saved = True
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
    # The report's rows carry a pruned collection's reason; it has no step.
    preflight = _preflight_split(stored, preview.data_collections)
    if preflight.to_dispatch or preflight.failed or preflight.skipped:
        run_id, all_dispatched, _results = _dispatch_refresh_tasks(
            project_dict=stored,
            to_dispatch=preflight.to_dispatch,
            current_user=current_user,
            preflight_failed=preflight.failed,
            preflight_skipped=preflight.skipped,
            command="from_run",
            scan_modes=_scan_modes(stored),
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
