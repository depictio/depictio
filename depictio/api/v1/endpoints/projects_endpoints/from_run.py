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

import copy
import os
from dataclasses import dataclass
from typing import Any, Literal

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

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
from depictio.api.v1.endpoints.projects_endpoints.run_records import RunInfoSummary
from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
    ProjectStorageConfigIn,
    RunStorageIn,
    read_settings,
)
from depictio.cli.cli.utils.multiqc_state import MULTIQC_STATE_LOCK
from depictio.cli.cli.utils.template_preview import FromRunDCPreview
from depictio.cli.cli.utils.template_preview import report_rows as _report_rows
from depictio.models.local_access import LocalPathRefused
from depictio.models.logging import logger
from depictio.models.s3_access import ProjectS3Config, S3AccessError, is_s3_url
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.from_template import locate_shipped_template as _locate_shipped
from depictio.project_builder.overlay import TemplateEdits, compose, renamed_workflows

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
    # Projects are private unless the request asks otherwise, whatever the template says.
    is_public: bool = False
    description: str | None = None
    # An ad-hoc template, as the Project Builder assembles it (``POST
    # /projects/builder/template``), instead of one of the server's own:
    # validated (``project_builder.validate``), never stored as a template.
    template: dict[str, Any] | None = None
    # ``template_id`` edited in the Project Builder: collections removed,
    # repointed or added (``project_builder.overlay``). The shipped template
    # is re-read and the edits applied to it; nothing else of it changes.
    edits: TemplateEdits | None = None
    # A folder holding several runs of one pipeline: the names of its
    # sub-folders that are runs (``folder_inspect``'s ``child_runs``), with
    # ``data_root`` the folder itself. Each run is resolved and previewed as
    # its own run folder and the previews are merged; the project is created
    # from the first, plus the collections only another run kept, and the
    # others are recorded on its workflows as ``attach_run`` records a run,
    # before the one ingestion that reads them all. The project remembers the
    # folder and the run names (``template_origin.data_root`` / ``.runs``), so
    # a refresh reads every run again. A folder on the server's disk only.
    runs: list[str] | None = None

    @field_validator("runs")
    @classmethod
    def _plain_distinct_runs(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(value) < 2 or len(set(value)) != len(value):
            raise ValueError("runs: two or more distinct sub-folder names.")
        if len(value) > 100:
            raise ValueError("runs: at most 100 runs at once.")
        for name in value:
            if not name or name in (".", "..") or "/" in name or "\\" in name:
                raise ValueError(f"runs: '{name}' is not the name of a sub-folder.")
        return value

    @field_validator("template_id")
    @classmethod
    def _well_formed_template_id(cls, value: str | None) -> str | None:
        return None if value is None else validate_template_id(value)

    @model_validator(mode="after")
    def _one_template(self) -> "FromRunRequest":
        if self.template is not None and self.template_id is not None:
            raise ValueError("Give template_id or template, not both.")
        if self.edits is not None and self.template_id is None:
            raise ValueError("Edits are edits of a template: give its template_id.")
        return self


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


def describe_run(template_id: str, info) -> DetectedTemplate | None:
    """What the run's own records say, for a request that named ``template_id``.

    The facts of :func:`describe_detection` (pipeline, version, engine) without
    choosing a template: it is the one asked for, and ``match`` says how it fits
    the run (``exact`` for the run's version, ``closest`` for another version of
    its pipeline, ``none`` for another pipeline, in which case no template is
    named). None when no engine recognised the folder.
    """
    if info is None:
        return None
    if template_id in info.template_ids():
        match: Literal["exact", "closest", "none"] = "exact"
    elif info.pipeline_name and template_id.rsplit("/", 1)[0] == info.pipeline_name:
        match = "closest"
    else:
        match = "none"
    named = template_id if match != "none" else None
    return DetectedTemplate(
        template_id=named,
        template_version=template_id.rsplit("/", 1)[-1] if named else None,
        pipeline=info.pipeline_name,
        version=info.pipeline_version,
        engine=info.engine,
        match=match,
    )


class RunInputFile(BaseModel):
    """One file of the run the template reads through a variable, such as its samplesheet.

    ``name`` is the variable (``SAMPLESHEET_FILE``), ``description`` and
    ``required`` as the template declares it. ``location`` is where it
    resolved to, a real path or an ``s3://`` URL, None when it is not set.
    ``found`` says whether the data root holds it, None when that cannot be
    told: a location outside the root, or one a partial listing does not name.
    ``used_by`` are the data collections that read it or that a conditional on
    it switches (see ``templates.variable_users``).
    """

    name: str
    description: str | None = None
    required: bool = False
    location: str | None = None
    found: bool | None = None
    used_by: list[str] = Field(default_factory=list)


class SharedRunSamples(BaseModel):
    """Samples one MultiQC collection finds in more than one run.

    The one ingestion merges the runs' reports: a sample named in two of them
    becomes one, its values mixed. An upload of several reports refuses that
    (``validate_multiqc_reports_uniform``), and so does a creation from several
    runs (``runs_share_samples``); the preview names them first.
    """

    data_collection_tag: str
    # The runs that name them, in the request's order.
    runs: list[str]
    count: int
    # The first few, sorted.
    samples: list[str]


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
    # What the folder said about its run: set when detection ran (no
    # template_id in the request), and, for a request that named its
    # template, from the run's own records when an engine recognised it (the
    # template chosen is never replaced; ``match`` says how it fits the run).
    detected_template: DetectedTemplate | None = None
    data_root: str
    detected_runs: list[str] = Field(default_factory=list)
    # The sub-folders read as runs when the request named several. The rows
    # count every run together; ``data_root``, ``run_info`` and the input
    # files are the first run's.
    runs: list[str] | None = None
    # MultiQC samples found in more than one of ``runs`` (empty for one run).
    shared_samples: list[SharedRunSamples] = Field(default_factory=list)
    resolved_variables: dict[str, str] = Field(default_factory=dict)
    data_collections: list[FromRunDCPreview] = Field(default_factory=list)
    dashboards: list[DashboardImportResult] = Field(default_factory=list)
    pruned_optional_dcs: list[str] = Field(default_factory=list)
    truncated: bool = False
    # What the run's own records say, as GET /projects/folder_inspect shows
    # them; None when no engine recognised the folder.
    run_info: RunInfoSummary | None = None
    # Each file variable the template declares (``*_FILE``), in its order.
    input_files: list[RunInputFile] = Field(default_factory=list)
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


def _request_read_config(
    data_root: str, storage: RunStorageIn | None
) -> tuple[ProjectStorageConfigIn | None, _RunFolderReads]:
    """The storage settings a request typed in for ``data_root``, and the reads they make.

    The settings apply to an ``s3://`` data root only, validated first as a
    saved config is (``RunStorageIn.settings_for``); without them, or for a
    folder on this computer, the read configuration is the instance's (see
    :func:`_run_folder_read_config`). Every route that opens a run folder a
    request names decides it here, so all of them read it alike.
    """
    settings_in = (
        storage.settings_for(data_root) if storage is not None and is_s3_url(data_root) else None
    )
    reads = _run_folder_read_config(read_settings(settings_in) if settings_in is not None else None)
    return settings_in, reads


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


def _build_local_data_root(data_root: str, *, request, current_user, count_files: bool = True):
    """A :class:`LocalDataRoot` on the real path of ``data_root``, once allowed.

    Refused, in this order: local folders off (422), a request not from this
    machine or not from an administrator (403, see ``require_local_caller``),
    a path the policy refuses (422, the policy's own message and code), a
    folder holding more than :data:`MAX_LOCAL_RUN_FILES` files (422, unless
    ``count_files`` is off).
    """
    policy = local_data_policy()
    if policy is None:
        raise CodedHTTPException(422, LOCAL_FOLDERS_OFF, "local_folders_off")
    require_local_caller(request, current_user)
    return _confined_local_root(policy, data_root, count_files=count_files)


def _confined_local_root(policy, data_root: str, *, count_files: bool = True):
    """A :class:`LocalDataRoot` on the real path of ``data_root`` under ``policy``.

    The checks on the folder itself, whoever asks: a path the policy refuses
    (422, the policy's own message and code), a folder holding more than
    :data:`MAX_LOCAL_RUN_FILES` files (422). The count guards the reads that
    walk the folder; ``count_files=False`` skips it for a caller that reads
    one bounded file of it (``run_file_preview``).
    """
    try:
        real = policy.confine(data_root, want="dir")
    except LocalPathRefused as exc:
        raise CodedHTTPException(422, exc.detail, exc.code) from exc
    if count_files and _holds_more_files_than(real, MAX_LOCAL_RUN_FILES):
        raise CodedHTTPException(
            422,
            f"'{data_root}' holds more than {MAX_LOCAL_RUN_FILES:,} files, far more than "
            "one pipeline run writes. Pick the output folder of a single run.",
            "local_run_too_large",
        )

    from depictio.cli.cli.utils.data_root import LocalDataRoot

    return LocalDataRoot(real)


def _build_data_root(
    data_root: str,
    read_config: _RunFolderReads,
    *,
    request=None,
    current_user=None,
    count_files: bool = True,
):
    """The one :class:`DataRoot` this request answers every question from.

    Refused by ``S3DataRoot.__init__`` from configuration alone, before a
    single request goes out, when the configuration does not allow the read
    (``S3AccessRefused``, see :func:`_run_folder_read_config`), so a bucket
    name never becomes an existence-and-region oracle. A local path goes
    through :func:`_build_local_data_root`, which needs the request (for its
    ``Host``) and the caller; ``count_files`` is passed on to it.
    """
    if _is_local_path(data_root):
        return _build_local_data_root(
            data_root, request=request, current_user=current_user, count_files=count_files
        )
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


def _read_run(root):
    """The run's provenance in ``root``, without choosing a template; None when
    no engine recognises it. For a request that named its template: the one
    read :func:`_detect_run` makes otherwise, with the same handling of a
    failed read."""
    from depictio.cli.cli.utils.run_detection import read_run_info_for_root

    try:
        return read_run_info_for_root(root)
    except S3AccessError:
        raise
    except (OSError, ValueError) as exc:
        logger.warning(f"Reading the run in {root.location} failed: {exc}")
        return None


def _run_info_report(info, root) -> RunInfoSummary | None:
    """What ``GET /projects/folder_inspect`` shows of run ``info``, read from ``root``.

    ``run_folders._run_info_summary``, with the policy a local root was
    confined with (``_build_local_data_root``), so the trace is read under
    the same guard as there.
    """
    from depictio.api.v1.endpoints.projects_endpoints.run_folders import _run_info_summary

    return _run_info_summary(info, root, None if root.is_remote else local_data_policy())


def _input_file(variable, value: str | None, root, users: list[str]) -> RunInputFile:
    """One :class:`RunInputFile`: template variable ``variable`` resolved to ``value``.

    Judged on the root's own terms: ``relative_of`` says whether the value
    lies below it, and ``exists`` whether it is there, which a partial
    listing cannot deny.
    """
    location = found = None
    if value:
        relative = root.relative_of(value)
        location = value if relative is None else root.url(relative)
        if relative is not None:
            found = True if root.exists(relative) else (None if root.truncated else False)
    return RunInputFile(
        name=variable.name,
        description=variable.description or None,
        required=variable.required,
        location=location,
        found=found,
        used_by=users,
    )


def _input_files(template_id: str, metadata, variables: dict[str, str], root) -> list[RunInputFile]:
    """One :class:`RunInputFile` per file variable (``*_FILE``) template
    ``template_id`` declares, in its order, resolved to ``variables``.

    ``variables`` is everything resolution settled, the run's auto-detected
    files and the template's defaults included, rather than the subset the
    preview reports.
    """
    from depictio.cli.cli.utils.templates import variable_users

    declared = [variable for variable in metadata.variables if variable.name.endswith("_FILE")]
    if not declared:
        return []
    users = variable_users(template_id, [variable.name for variable in declared])
    return [
        _input_file(variable, variables.get(variable.name), root, users[variable.name])
        for variable in declared
    ]


def _detect_template(root) -> tuple[str, DetectedTemplate, Any]:
    """The template id recognised in ``root``, with what the folder said, and the
    run's provenance it was decided from.

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
    return template_id, detected, info


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
        needed = [
            s[len("collection ") :] for s in row.missing_sources if s.startswith("collection ")
        ]
        files = [s for s in row.missing_sources if not s.startswith("collection ")]
        parts = []
        if files:
            parts.append(f"source(s) not found under the data root: {', '.join(files)}")
        if needed:
            parts.append(f"needs collection(s) that could not be built: {', '.join(needed)}")
        return f"Not ingested: {'; '.join(parts)}."
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


_NO_MULTIQC_REPORT = (
    "No MultiQC report in this run yet: the collection stays empty until its files exist."
)


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
    rows' ``missing_collections``). A MultiQC collection whose scan matches
    no report is skipped as well (nothing to ingest, not an error). Everything
    else is dispatched, other ``empty`` rows included: the scan's own verdict on those arrives from the worker.

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
            if (
                row is not None
                and row.status == "empty"
                and not row.matched
                and str((dc_dict.get("config") or {}).get("type") or "").lower() == "multiqc"
            ):
                # The scan found no report: the collection stays empty until
                # there is one. A worker would fail it ("No MultiQC parquet
                # files found"), which contradicts that promise.
                skipped.append((tag, dc_id, _NO_MULTIQC_REPORT))
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

    For a project made from a folder of several runs (``template_origin.runs``)
    this is that folder, not one of its runs, and its files are not counted:
    :func:`_stored_run_roots` opens the runs.
    """
    origin = project_dict.get("template_origin") or {}
    data_root = str(origin.get("data_root") or "")
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
            return _confined_local_root(policy, data_root, count_files=not origin.get("runs"))
        except CodedHTTPException as exc:
            logger.warning(f"Refresh pre-flight skipped ({exc.code}): {exc.detail}")
            return None
    return None


def _stored_run_roots(project_dict: dict[str, Any]) -> tuple[Any, list[tuple[str, Any]]] | None:
    """The run folder a project was made from, and the run folders it is read from.

    ``(folder, [(run name, root), ...])``: one entry with an empty name for a
    project made from one run folder (then ``folder`` is that root), one per run
    for a project made from a folder of runs, each confined and size-capped as at
    creation (the first one counted, as there). A run that has gone from the
    disk since is left out with a warning, what is left is still checked; all
    of them gone is None. None too when there is no folder to check, see
    :func:`_stored_run_folder`.
    """
    folder = _stored_run_folder(project_dict)
    if folder is None:
        return None
    names = [str(name) for name in (project_dict.get("template_origin") or {}).get("runs") or []]
    if not names:
        return folder, [("", folder)]
    policy = local_data_policy()
    if policy is None:  # pragma: no cover - the folder above was confined under one
        return None
    roots: list[tuple[str, Any]] = []
    for name in names:
        try:
            run = _confined_local_root(
                policy, os.path.join(folder.location, name), count_files=not roots
            )
        except CodedHTTPException as exc:
            logger.warning(f"Refresh pre-flight: run '{name}' skipped ({exc.code}): {exc.detail}")
            continue
        roots.append((name, run))
    return (folder, roots) if roots else None


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

    A project made from a folder of runs is previewed run by run and merged the
    way its creation did (:func:`_merge_run_rows`), so a collection whose files
    are in the second run only is as present now as it was then.

    None when there is no folder to check (see :func:`_stored_run_folder`):
    the refresh then dispatches as it always has.
    """
    found = _stored_run_roots(project_dict)
    if found is None:
        return None
    folder, runs = found

    from depictio.cli.cli.utils.template_preview import preview_data_collections

    per_run = [preview_data_collections(project_dict, root)[0] for _name, root in runs]
    rows = per_run[0] if len(per_run) == 1 else _merge_run_rows(per_run, [n for n, _r in runs])
    return folder.location, _preflight_split(project_dict, rows)


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
    is_public: bool = False,
    description: str | None = None,
    template: dict[str, Any] | None = None,
    edits: TemplateEdits | None = None,
    runs: list[str] | None = None,
) -> FromRunReport:
    """The full run folder → project + dashboards + dispatched ingestion flow.

    ``template_id=None`` recognises the template from the folder, unless
    ``template`` hands one in (the Project Builder's ad-hoc template), which is
    then held to ``validate_inline_template`` and resolved from memory.
    ``edits`` (with ``template_id``) apply the Project Builder's changes to the
    shipped template before it is resolved (``project_builder.overlay``). ``request``
    is the HTTP request, which a local data root needs for its ``Host`` guard.
    ``storage`` (an ``s3://`` data root only) is read with alone, validated
    first as a saved config is, and stored on the created project before its
    ingestion is dispatched; a dry run stores nothing. ``runs`` names
    sub-folders of a local ``data_root`` that are each a run. Each is resolved
    and previewed as a run folder of its own and the previews are merged
    (:func:`_merged_run_preview`); the project is made from the first run's
    resolution plus the collections only another run kept
    (:func:`_keep_collections_kept_elsewhere`), the others are added to the
    workflows' locations before the ingestion is dispatched, and the project
    remembers ``data_root`` and the run names as its origin.

    Sync: call via ``asyncio.to_thread``.
    """
    # The request model already enforces this; re-checked here so direct
    # callers cannot hand resolve_template a path either.
    if template_id is not None:
        try:
            validate_template_id(template_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    if template is not None and template_id is not None:
        raise HTTPException(status_code=422, detail="Give template_id or template, not both.")
    if edits is not None and template_id is None:
        raise HTTPException(
            status_code=422, detail="Edits are edits of a template: give its template_id."
        )

    if runs:
        if not _is_local_path(data_root):
            raise CodedHTTPException(
                422,
                "Several runs are read from a folder on the server's disk only. Create "
                "the project from one run, then add the others with Add run.",
                "runs_need_local",
            )
        if template is not None:
            raise CodedHTTPException(
                422,
                "Several runs are read with one of the server's templates only.",
                "runs_need_template",
            )
        if edits is not None and edits.additions:
            # The builder's collections are paths below the folder typed in,
            # while each run is resolved as a folder of its own: they would
            # match nothing.
            raise CodedHTTPException(
                422,
                "Collections added in the builder cannot be read across several runs yet: "
                "create the project from one run, or remove them.",
                "runs_with_additions",
            )
        parent = data_root
        data_root = os.path.join(parent, runs[0])

    storage_settings, read_config = _request_read_config(data_root, storage)
    root = _build_data_root(data_root, read_config, request=request, current_user=current_user)
    _assert_variables_confined(variables or {}, root)
    other_roots = [
        _build_data_root(
            os.path.join(parent, name),
            read_config,
            request=request,
            current_user=current_user,
            count_files=False,
        )
        for name in (runs or [])[1:]
    ]
    other_runs = [other.location for other in other_roots]
    # What the project remembers as the folder it was made from.
    origin_root = root
    if runs:
        origin_root = _build_data_root(
            parent, read_config, request=request, current_user=current_user, count_files=False
        )

    if template is not None:
        return _create_project_from_inline_template(
            template,
            root=root,
            read_config=read_config,
            storage_settings=storage_settings,
            current_user=current_user,
            project_name=project_name,
            dry_run=dry_run,
            is_public=is_public,
            description=description,
        )

    detected: DetectedTemplate | None = None
    if template_id is None:
        template_id, detected, run = _detect_template(root)
        try:
            validate_template_id(template_id)
        except ValueError as exc:  # pragma: no cover - detection yields catalog ids
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        # Detection did not run, so the run is read for the report alone.
        run = _read_run(root)

    # One root, two consumers. resolve_template gives the config the project is
    # built from; preview_data_root gives the per-collection rows the UI shows.
    # Both take a pre-built root, so this whole request costs one S3 listing.
    from depictio.cli.cli.utils.templates import resolve_template, resolve_template_config

    def resolve_on(on):
        try:
            if edits is not None and not edits.is_empty():
                resolution = resolve_template_config(
                    _edited_template(template_id, edits, remote=on.is_remote),
                    template_dir=locate_shipped_template(template_id).parent,
                    data_root=on,
                    project_name=project_name,
                    extra_vars=dict(variables) if variables else None,
                    CLI_config=read_config,
                    source=template_id,
                )
            else:
                resolution = resolve_template(
                    template_id=template_id,
                    data_root=on,
                    project_name=project_name,
                    extra_vars=dict(variables) if variables else None,
                    CLI_config=read_config,
                )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail=_template_not_found_detail(template_id, exc)
            )
        except S3AccessError:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Template resolution failed: {exc}")
        return resolution

    resolution = resolve_on(root)
    other_resolutions = [resolve_on(other) for other in other_roots]
    resolved_config, template_metadata, _origin, dashboard_paths, resolved_vars = resolution
    if detected is None:
        # A template was named: the run's own records are reported all the same.
        detected = describe_run(template_metadata.template_id, run)

    # Before anything is previewed, let alone created: nothing this template
    # resolved to may point outside the run folder, each run's own.
    _assert_data_collections_confined(resolved_config, root)
    for other, (other_config, *_rest) in zip(other_roots, other_resolutions, strict=True):
        _assert_data_collections_confined(other_config, other)
    if other_roots:
        _keep_collections_kept_elsewhere(
            resolved_config, [other_config for other_config, *_rest in other_resolutions]
        )
        _assert_takes_runs(resolved_config, root.location, other_runs)
        origin = resolved_config.get("template_origin")
        if isinstance(origin, dict):
            origin["data_root"] = origin_root.location
            origin["runs"] = list(runs or [])

    from depictio.cli.cli.utils.template_preview import preview_data_root

    def preview_on(on, on_resolution):
        try:
            # The resolution above, not the template again: edits live only there.
            return preview_data_root(
                template_id=template_id,
                data_root=on,
                variables=dict(variables) if variables else None,
                CLI_config=read_config,
                resolution=on_resolution,
            )
        except FileNotFoundError as exc:  # pragma: no cover - resolution already passed
            raise HTTPException(
                status_code=404, detail=_template_not_found_detail(template_id, exc)
            )
        except S3AccessError:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Data root preview failed: {exc}")

    preview = preview_on(root, resolution)
    shared_samples: list[SharedRunSamples] = []
    if other_roots:
        other_previews = [
            preview_on(other, other_resolution)
            for other, other_resolution in zip(other_roots, other_resolutions, strict=True)
        ]
        shared_samples = _samples_shared_across_runs(
            _multiqc_tags(resolved_config),
            list(
                zip(list(runs or []), [root, *other_roots], [preview, *other_previews], strict=True)
            ),
        )
        # What the one ingestion will read: every run, each resolved as its own
        # run folder, counted together.
        preview = _merged_run_preview(preview, other_previews, list(runs or [])[1:])

    report = FromRunReport(
        project_name=resolved_config.get("name", ""),
        template_id=template_metadata.template_id,
        detected_template=detected,
        data_root=root.location,
        detected_runs=list(preview.detected_runs),
        runs=list(runs) if runs else None,
        shared_samples=shared_samples,
        resolved_variables=dict(preview.resolved_variables),
        data_collections=_report_rows(preview.data_collections),
        pruned_optional_dcs=list(preview.pruned_optional_dcs),
        truncated=preview.truncated,
        run_info=_run_info_report(run, root),
        input_files=_input_files(template_id, template_metadata, resolved_vars, root),
        dry_run=dry_run,
    )

    if dry_run:
        report.success = True
        return report

    if shared_samples:
        raise CodedHTTPException(422, _shared_samples_detail(shared_samples), "runs_share_samples")

    create_payload = _new_project_document(
        resolved_config,
        current_user,
        origin_kind="run",
        origin_location=origin_root.location,
        is_public=is_public,
    )
    create_payload["description"] = description
    projects_collection.insert_one(create_payload)
    project_oid = create_payload["_id"]

    # Before the workers start: they read the run folder through
    # ``project_storage_for``, as any later refresh does.
    if storage_settings is not None:
        _save_storage_or_roll_back(project_oid, storage_settings)
        report.storage_saved = True
    report.project_id = str(project_oid)

    stored = projects_collection.find_one({"_id": project_oid}) or {}
    if other_runs:
        _record_other_runs(stored, other_runs)
        stored = projects_collection.find_one({"_id": project_oid}) or stored
    # The report's rows carry a pruned collection's reason; it has no step.
    preflight = _preflight_split(stored, preview.data_collections)

    # Import the template's dashboards in-process, before the workers start:
    # the shared import handler binds DC tags to the ids just persisted and
    # drops components whose optional DC was pruned (self-adapting import). No
    # collection has data yet, so the ones about to be ingested are named, or
    # every tile on an optional collection would go with the absent ones.
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import dcs_being_ingested

    with dcs_being_ingested({tag for tag, *_ in preflight.to_dispatch}):
        report.dashboards = _import_template_dashboards(
            dashboard_paths,
            template_id=template_metadata.template_id,
            template_version=template_metadata.version,
            project_id=project_oid,
            variables=resolved_vars,
            current_user=current_user,
            workflow_renames=renamed_workflows(edits),
        )
    all_ok = all(entry.success for entry in report.dashboards)

    # Fan the ingestion out. Everything the workers need is on the project
    # document, which they re-read for themselves; the run document in Mongo is
    # the durable status of record.
    if preflight.to_dispatch or preflight.failed or preflight.skipped:
        run_id, all_dispatched, _results = _dispatch_refresh_tasks(
            project_dict=stored,
            to_dispatch=preflight.to_dispatch,
            current_user=current_user,
            preflight_failed=preflight.failed,
            preflight_skipped=preflight.skipped,
            command="from_run",
            scan_modes=_scan_modes(stored),
            data_root=origin_root.location,
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


_SHARED_SAMPLES_SHOWN = 8


def _multiqc_tags(config: dict[str, Any]) -> set[str]:
    """The tags of a resolved template's MultiQC collections."""
    return {
        str(dc.get("data_collection_tag") or "")
        for workflow in config.get("workflows") or []
        for dc in workflow.get("data_collections") or []
        if str((dc.get("config") or {}).get("type") or "").lower() == "multiqc"
    }


# MultiQC keeps its state in the module: one report is read at a time, under
# the lock every MultiQC reader of the process takes.
_MULTIQC_READ = MULTIQC_STATE_LOCK
# (location, size) -> sample names, so the dialog's and the builder's previews
# of one folder read each report once. Bounded: emptied once it holds this many.
_SAMPLES_READ: dict[tuple[str, int], frozenset[str]] = {}
_SAMPLES_READ_MAX = 512


def _multiqc_samples_of(data: bytes) -> set[str]:
    """The samples a MultiQC report names: its canonical sample ids.

    Read as an upload of several reports is (``extract_multiqc_metadata``), not
    from the parquet's ``sample`` column, which also holds sequences and other
    keys. The canonical ids, not every name: a module's variants of a sample
    ("S1 - First read: Adapter 1", "S1_1") are the same sample. A report with
    no canonical ids falls back to its names.
    """
    import tempfile

    from depictio.cli.cli.utils.multiqc_processor import extract_multiqc_metadata

    with _MULTIQC_READ, tempfile.TemporaryDirectory(prefix="depictio_run_samples_") as tmp:
        path = os.path.join(tmp, "multiqc.parquet")
        with open(path, "wb") as handle:
            handle.write(data)
        metadata = extract_multiqc_metadata(path)
    return {str(s) for s in metadata.get("canonical_samples") or metadata.get("samples") or []}


def _report_sample_names(root, row) -> set[str] | None:
    """The sample names of the MultiQC reports a preview row found under ``root``.

    The row's ``samples`` (the first few reports: a run holds one or two). None
    when one of them cannot be read as a report: the check then says nothing
    rather than a half answer.
    """
    names: set[str] = set()
    for location in row.samples:
        rel = root.relative_of(location)
        if rel is None:
            return None
        try:
            key = (location, root.size(rel) or -1)
            if key not in _SAMPLES_READ:
                if len(_SAMPLES_READ) >= _SAMPLES_READ_MAX:
                    _SAMPLES_READ.clear()
                _SAMPLES_READ[key] = frozenset(_multiqc_samples_of(root.read_bytes(rel)))
        except Exception as exc:  # noqa: BLE001 - an unreadable report is not checked
            logger.warning(f"Shared-samples check skipped {location}: {exc}")
            return None
        names.update(_SAMPLES_READ[key])
    return names


def _samples_shared_across_runs(
    tags: set[str], per_run: list[tuple[str, Any, Any]]
) -> list[SharedRunSamples]:
    """Per MultiQC collection, the samples more than one run's reports name.

    ``per_run`` is ``(run name, its data root, its preview)``, in order.
    """
    shared_by_tag: list[SharedRunSamples] = []
    for tag in sorted(tags):
        owner: dict[str, str] = {}
        shared: dict[str, list[str]] = {}
        for name, root, preview in per_run:
            row = next((r for r in preview.data_collections if r.tag == tag), None)
            if row is None or not row.matched:
                continue
            names = _report_sample_names(root, row)
            if names is None:
                continue
            for sample in names:
                if sample in owner:
                    shared.setdefault(sample, [owner[sample]]).append(name)
                else:
                    owner[sample] = name
        if shared:
            runs = [name for name, *_rest in per_run if any(name in v for v in shared.values())]
            shared_by_tag.append(
                SharedRunSamples(
                    data_collection_tag=tag,
                    runs=runs,
                    count=len(shared),
                    samples=sorted(shared)[:_SHARED_SAMPLES_SHOWN],
                )
            )
    return shared_by_tag


def _shared_samples_detail(shared: list[SharedRunSamples]) -> str:
    """The refusal of a creation whose runs share samples."""
    parts = []
    for entry in shared:
        more = entry.count - len(entry.samples)
        names = ", ".join(entry.samples) + (f" and {more} more" if more > 0 else "")
        parts.append(
            f"{entry.data_collection_tag}: {entry.count} sample"
            f"{'' if entry.count == 1 else 's'} in more than one of "
            f"{', '.join(entry.runs)} ({names})"
        )
    return (
        "The runs name the same samples, which one MultiQC collection would merge: "
        + "; ".join(parts)
        + ". Read the runs as separate projects, or rename the samples in one of them."
    )


def _merged_run_preview(first, others, names: list[str]):
    """``first`` (the first run's preview) with what ``others`` found counted in.

    ``names`` are the other runs' folder names. The rows are merged by
    :func:`_merge_run_rows`; an optional collection pruned in every run stays
    pruned, one that a later run kept is no longer.
    """
    from dataclasses import replace

    rows = _merge_run_rows(
        [first.data_collections, *(other.data_collections for other in others)], ["", *names]
    )
    pruned = {row.tag for row in rows if row.status == "pruned"}
    detected_runs = list(
        dict.fromkeys([*first.detected_runs, *(r for other in others for r in other.detected_runs)])
    )
    return replace(
        first,
        data_collections=rows,
        pruned_optional_dcs=[tag for tag in first.pruned_optional_dcs if tag in pruned],
        detected_runs=detected_runs,
        truncated=first.truncated or any(other.truncated for other in others),
    )


_ROW_RANK = {"ok": 0, "empty": 1, "missing": 2, "pruned": 3}


def _merge_run_rows(per_run, names: list[str]):
    """One row per collection from each run's rows (``per_run[i]`` is run ``names[i]``'s).

    What the one ingestion will read, whichever way the rows were made, a
    creation's (each run resolved on its own) or a refresh's (the stored
    collections over each run):

    * a ``recursive`` scan reads every run: its counts add up, a collection
      found in any run is found, and the samples name their run;
    * a collection no run's resolution pruned from the first run's is the
      first's row; one the first run pruned or never had is the first row of
      a run that kept it (pruning is a union across runs, see
      :func:`_keep_collections_kept_elsewhere`);
    * a single file or URL is the row of the run whose folder holds it (the
      other runs cannot judge it), a recipe keeps the first run's row;
    * the recipes are then settled again from the merged rows, since a
      collection that is found in the second run only satisfies the recipes
      reading it (:func:`_settle_recipes`).
    """
    by_run = [{row.tag: row for row in rows} for rows in per_run]
    tags = list(dict.fromkeys(row.tag for rows in per_run for row in rows))
    merged = []
    for tag in tags:
        found = [(index, run[tag]) for index, run in enumerate(by_run) if tag in run]
        live = [(index, row) for index, row in found if row.status != "pruned"]
        merged.append(_merge_tag_rows(live or found[:1], names))
    return _settle_recipes(merged)


def _merge_tag_rows(candidates, names: list[str]):
    """The merged row of one collection from ``(run index, row)`` candidates, first run first."""
    from dataclasses import replace

    from depictio.cli.cli.utils.template_preview import PREVIEW_SAMPLES

    _first_index, row = candidates[0]
    mode = str(row.mode or "").lower() if row.kind == "scan" else ""
    if mode in ("single", "url"):
        # A row that counted nothing and reported ok did not look at the file:
        # the folder it was judged against does not hold it.
        return next(
            (cand for _i, cand in candidates if not (cand.status == "ok" and not cand.matched)),
            row,
        )
    if mode != "recursive":
        return row

    matched = row.matched
    samples = list(row.samples)
    status = row.status
    found_in = row.found_in
    for index, other in candidates[1:]:
        name = names[index]
        matched += other.matched
        # A sample relative to its run says which; a full path already does.
        samples += [
            sample if os.path.isabs(sample) or "://" in sample else f"{name}/{sample}"
            for sample in other.samples
        ]
        if _ROW_RANK.get(other.status, 9) < _ROW_RANK.get(status, 9):
            status = other.status
        if not row.matched and other.matched and found_in is None:
            found_in = f"{name}/{other.found_in}" if other.found_in else name
    merged = replace(
        row, matched=matched, samples=samples[:PREVIEW_SAMPLES], status=status, found_in=found_in
    )
    if status == "ok":
        merged = replace(merged, missing_sources=[], missing_collections=[])
    return merged


def _settle_recipes(rows):
    """``rows`` with each recipe row re-evaluated from the merged rows of the collections it reads.

    A recipe row was made from one run's rows, where a collection found in
    another run only was missing. A source of kind ``collection`` that is now
    settled (its row is ``ok``) counts as found, which can settle the recipe
    in turn, so this runs until nothing changes; the references form a DAG.
    The files a recipe reads are the first run's, as before.
    """
    from dataclasses import replace

    rows = list(rows)
    while True:
        settled = {row.tag for row in rows if row.status == "ok"}
        changed = False
        for index, row in enumerate(rows):
            if row.kind != "recipe" or row.recipe is None:
                continue
            pending = {
                source.dc_ref
                for source in row.recipe.sources
                if source.kind == "collection" and not source.found and source.dc_ref in settled
            }
            if not pending:
                continue
            sources = [
                replace(source, found=True, matched=1)
                if source.kind == "collection" and source.dc_ref in pending and not source.found
                else source
                for source in row.recipe.sources
            ]
            gone = {f"collection '{tag}'" for tag in pending}
            missing_sources = [text for text in row.missing_sources if text not in gone]
            rows[index] = replace(
                row,
                recipe=replace(row.recipe, sources=sources),
                matched=row.matched + len(pending),
                missing_sources=missing_sources,
                missing_collections=[t for t in row.missing_collections if t not in pending],
                status="missing" if missing_sources else "ok",
            )
            changed = True
        if not changed:
            return rows


def _keep_collections_kept_elsewhere(config: dict[str, Any], others: list[dict[str, Any]]) -> None:
    """Add to ``config`` (the first run's resolution) the collections only another run kept.

    Resolution prunes a collection for one run (an optional single file the
    run does not hold, a conditional on that run's own parameters); the project
    reads every run, so a collection is dropped only when every run dropped it.
    Its definition is that of the first run whose resolution kept it, appended
    to the workflow of the same name, with the links it takes part in whose
    other end is in the project. The template origin's manifest then lists it
    as included. In place.
    """
    workflows = {
        str(workflow.get("name")): workflow
        for workflow in config.get("workflows") or []
        if workflow.get("name") is not None
    }
    held = {
        str(dc.get("data_collection_tag"))
        for workflow in workflows.values()
        for dc in workflow.get("data_collections") or []
    }
    added: set[str] = set()
    for other in others:
        for workflow in other.get("workflows") or []:
            target = workflows.get(str(workflow.get("name")))
            if target is None:
                continue
            for dc in workflow.get("data_collections") or []:
                tag = str(dc.get("data_collection_tag"))
                if tag in held:
                    continue
                target.setdefault("data_collections", []).append(copy.deepcopy(dc))
                held.add(tag)
                added.add(tag)
    if not added:
        return

    links = config.setdefault("links", [])
    for other in others:
        for link in other.get("links") or []:
            ends = {link.get("source_dc_tag"), link.get("target_dc_tag")}
            if ends & added and ends <= held and link not in links:
                links.append(copy.deepcopy(link))
    origin = config.get("template_origin")
    if isinstance(origin, dict):
        for expected in origin.get("expected_data_collections") or []:
            if expected.get("data_collection_tag") in added:
                expected["included"] = True
                expected["removal_reason"] = None


def _assert_takes_runs(config: dict[str, Any], first: str, others: list[str]) -> None:
    """Refuse several runs for a template whose workflows cannot hold a second one.

    The rule ``attach_run`` applies to a project, applied to the resolved
    template before anything is created: a workflow takes another run when one
    of its collections is a ``recursive`` scan, and two runs of a flat workflow
    must not share a directory name.
    """
    from depictio.api.v1.endpoints.projects_endpoints.attach_run import (
        _flat_clash,
        attach_targets,
    )

    indexes, _blockers = attach_targets(config)
    if not indexes:
        raise CodedHTTPException(
            422,
            "This template reads one run per project: none of its data collections "
            "scans a folder of runs. Create one project per run.",
            "runs_not_supported",
        )
    for index in indexes:
        location = (config.get("workflows") or [])[index].get("data_location") or {}
        clash = _flat_clash(location.get("structure"), [first, *others])
        if clash:
            raise CodedHTTPException(422, clash, "run_name_clash")


def _record_other_runs(project: dict[str, Any], others: list[str]) -> None:
    """Add ``others`` to the locations of each workflow that takes a run, as attach_run does."""
    from depictio.api.v1.endpoints.projects_endpoints.attach_run import (
        attach_targets,
        merged_locations,
    )

    indexes, _blockers = attach_targets(project)
    workflows = project.get("workflows") or []
    updates: dict[str, Any] = {}
    for index in indexes:
        location = workflows[index].get("data_location") or {}
        locations = list(location.get("locations") or [])
        attached = list(location.get("attached_locations") or [])
        for other in others:
            locations, attached = merged_locations(locations, attached, other)
        updates[f"workflows.{index}.data_location.locations"] = locations
        updates[f"workflows.{index}.data_location.attached_locations"] = attached
    if updates:
        projects_collection.update_one({"_id": project["_id"]}, {"$set": updates})


def _edited_template(template_id: str, edits: TemplateEdits, *, remote: bool) -> dict[str, Any]:
    """The shipped template with the Project Builder's edits applied, as raw YAML."""
    try:
        raw, _path, _removed, _warnings = compose(template_id, edits, remote=remote)
    except BuilderRefused as exc:
        raise CodedHTTPException(exc.status, exc.detail, exc.code or "template_edits_invalid")
    return raw


def locate_shipped_template(template_id: str):
    """Where a shipped template lives: its dashboards are read next to it."""
    try:
        return _locate_shipped(template_id)
    except BuilderRefused as exc:
        raise CodedHTTPException(exc.status, exc.detail, exc.code or "template_not_found")


def _default_image_folders(config: dict[str, Any]) -> None:
    """Give each image collection without an ``s3_base_folder`` one in the server's bucket.

    The images are uploaded there at ingest, and served from there only; the
    Project Builder cannot know the bucket, so the server picks a fresh folder.
    """
    from uuid import uuid4

    from depictio.api.v1.configs.config import settings

    for workflow in config.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            dc_config = dc.get("config") or {}
            if str(dc_config.get("type") or "").lower() != "image":
                continue
            properties = dc_config.setdefault("dc_specific_properties", {})
            if not properties.get("s3_base_folder"):
                tag = dc.get("data_collection_tag") or "images"
                properties["s3_base_folder"] = (
                    f"s3://{settings.s3.bucket}/images/{uuid4().hex[:12]}/{tag}"
                )


def _create_project_from_inline_template(
    template: dict[str, Any],
    *,
    root,
    read_config,
    storage_settings,
    current_user,
    project_name: str | None,
    dry_run: bool,
    is_public: bool = False,
    description: str | None = None,
) -> FromRunReport:
    """``from_run`` for an ad-hoc template: validate, resolve from memory, preview, create.

    The same steps as a catalogue template, minus what an ad-hoc one cannot
    have (detection, dashboards, file variables), plus the builder's rules
    (``validate_inline_template``) before anything is resolved. Confinement to
    the run folder is checked on the resolved config as for any template.
    """
    from depictio.cli.cli.utils.template_preview import preview_data_root
    from depictio.project_builder.plan import check_project, declared_variables, resolve_inline
    from depictio.project_builder.validate import validate_inline_template

    try:
        validate_inline_template(template, remote=root.is_remote)
        resolution = resolve_inline(
            template, root, project_name=project_name, CLI_config=read_config
        )
        resolved_config = resolution[0]
        _assert_data_collections_confined(resolved_config, root)
        check_project(resolved_config)
    except BuilderRefused as exc:
        raise CodedHTTPException(exc.status, exc.detail, exc.code or "inline_template_invalid")
    template_metadata = resolution[1]
    run = _read_run(root)

    try:
        preview = preview_data_root(
            template_id=template_metadata.template_id, data_root=root, resolution=resolution
        )
    except S3AccessError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Data root preview failed: {exc}")

    report = FromRunReport(
        project_name=resolved_config.get("name", ""),
        template_id=template_metadata.template_id,
        data_root=root.location,
        detected_runs=list(preview.detected_runs),
        resolved_variables=declared_variables(preview.resolved_variables, template_metadata),
        data_collections=_report_rows(preview.data_collections),
        pruned_optional_dcs=list(preview.pruned_optional_dcs),
        truncated=preview.truncated,
        run_info=_run_info_report(run, root),
        dry_run=dry_run,
    )
    if dry_run:
        report.success = True
        return report

    _default_image_folders(resolved_config)
    create_payload = _new_project_document(
        resolved_config,
        current_user,
        origin_kind="run",
        origin_location=root.location,
        is_public=is_public,
    )
    create_payload["description"] = description
    projects_collection.insert_one(create_payload)
    project_oid = create_payload["_id"]
    if storage_settings is not None:
        _save_storage_or_roll_back(project_oid, storage_settings)
        report.storage_saved = True
    report.project_id = str(project_oid)

    stored = projects_collection.find_one({"_id": project_oid}) or {}
    preflight = _preflight_split(stored, preview.data_collections)
    all_ok = True
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
        all_ok = all_dispatched
    else:
        logger.warning(
            f"from_run created project '{report.project_name}' with no ingestable "
            "data collection; no ingestion run was opened."
        )
    report.success = all_ok
    return report
