"""Find the run folder a project is created from: browse S3, inspect, search.

Three reads back the viewer's run-folder picker for ``POST /projects/from_run``:

- ``GET /projects/s3_dirs``: the sub-folders of an ``s3://`` location an
  administrator listed for every user (``DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS``,
  ``DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS``), or those locations themselves.
  The S3 twin of ``GET /projects/local_dirs``, in the same shape;
- ``GET /projects/folder_inspect``: what one folder holds, which installed
  template fits the run in it, and what the run's own records say about it;
- ``GET /projects/find_runs``: the run folders below a folder.

A folder on this computer goes through the guards and the policy of
:mod:`local_dirs` (local folders on, an administrator, a loopback ``Host``, a
path the policy confines), so these reads see what the folder browser lists.
An ``s3://`` location is resolved the way ``from_run`` resolves its run folder
(:func:`from_run._run_folder_read_config`), so the picker never offers a
location the creation then refuses: a malformed location, the instance's own
bucket and anything no listed entry holds are refused before a request goes
out, and every request goes through the resolved target's client.

A private bucket is read with storage settings typed in next to the location
(the POST twins of the three routes, body field ``storage``): the location is
then read with them alone, whatever the lists say, and browsing reaches the
whole bucket, as far as the keys allow.

Every read is bounded: one listing page per S3 folder (and one more below its
``multiqc/``, when it has one, to tell a run marker from a folder that only
shares the name), a capped walk below a local folder, a capped key listing
below an S3 prefix, and template detection for the first
:data:`FIND_DETECT_RUNS` runs found.

Synchronous: the routes dispatch via ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import deque
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from depictio.api.v1 import remote_fetch
from depictio.api.v1.configs.settings_models import local_data_policy
from depictio.api.v1.endpoints.projects_endpoints.from_run import (
    DetectedTemplate,
    _build_data_root,
    _detect_run,
    _is_local_path,
    _run_folder_read_config,
    _RunFolderReads,
    describe_detection,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import (
    MAX_ENTRIES,
    MULTIQC,
    NOISE_DIRS,
    PIPELINE_INFO,
    RUN_MARKERS,
    CodedHTTPException,
    LocalDirEntry,
    LocalDirListing,
    active_local_policy,
    is_directory,
    is_hidden_name,
    is_multiqc_output,
    require_local_caller,
    run_markers,
)
from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
    RunStorageIn,
    read_settings,
)
from depictio.models.local_access import LocalDataPolicy, LocalPathRefused
from depictio.models.logging import logger
from depictio.models.models.run_info import WorkflowRunInfo
from depictio.models.s3_access import (
    S3AccessFailed,
    S3AccessRefused,
    S3Target,
    ensure_region,
    folder_prefix,
    is_instance_bucket,
    is_s3_url,
    iter_object_pages,
    parse_bucket_list,
    split_s3_url,
)

# How many names of each kind folder_inspect returns; its counts cover them all.
# Enough to list a run folder's top level in full. The work stays bounded by
# MAX_INSPECT_ENTRIES locally and by one listing page (1,000 keys) on S3.
MAX_NAMES = 200
# Entries of a local folder folder_inspect looks at before saying ``truncated``.
MAX_INSPECT_ENTRIES = 10_000

# The run's parameters folder_inspect returns, and the characters of each value.
MAX_RUN_PARAMS = 200
MAX_PARAM_CHARS = 300
# A parameter whose name says it holds a credential is shown as this instead.
HIDDEN_PARAM = "(hidden)"
SECRET_PARAM_NAME = re.compile(
    r"passw(or)?d|passphrase|secret|token|credential|api_?key|access_?key|private_?key"
    r"|hook_?url|webhook",
    re.IGNORECASE,
)

# find_runs below a local folder: how deep, and how many folders it opens.
FIND_MAX_DEPTH = 6
FIND_MAX_DIRS = 5_000
# find_runs below an s3:// prefix: how many keys it lists.
FIND_MAX_KEYS = 20_000
# find_runs either way: how many runs it returns, and detects the template of.
FIND_MAX_RUNS = 100
FIND_DETECT_RUNS = 50

# The ``relative`` of a run that is the searched folder itself.
SELF = "."

# A Nextflow task folder of its work directory: two lowercase hex digits
# (``work/3f/a1b2c3.../``).
NEXTFLOW_TASK_FOLDER = re.compile(r"[0-9a-f]{2}")
# What else Nextflow keeps there: remote inputs staged in (``stage-<id>``), and
# the conda and singularity caches when no cache folder is set.
NEXTFLOW_WORK_EXTRAS = ("conda", "singularity")

LOCATION_RULE = "Give an s3:// location, such as s3://bucket/results/run42/."
LOCATION_RULE_LOCAL = (
    "Give an s3:// location or a folder on this computer: an absolute path such as "
    "/Users/me/results/run42, or one starting with ~/."
)


class S3DirListing(LocalDirListing):
    """One ``s3://`` location's sub-folders, or the allowed locations when ``path`` is None.

    The shape of :class:`LocalDirListing`, every path an ``s3://`` URL ending
    in ``/``. On an entry ``has_children`` is always True and ``looks_like_run``
    always False: knowing would cost a request per entry. The listing's own
    ``looks_like_run`` says whether the listed location holds ``pipeline_info/``,
    or a ``multiqc/`` holding MultiQC output (see :func:`_s3_markers`).
    """


class FolderNames(BaseModel):
    """How many entries of one kind a folder holds, and the first
    :data:`MAX_NAMES` names, sorted."""

    count: int = 0
    names: list[str] = Field(default_factory=list)


RunReportKind = Literal[
    "software_versions", "params", "execution_report", "execution_trace", "pipeline_dag"
]

# Which ``WorkflowRunInfo`` field holds the location of each kind of report.
_REPORT_FIELDS: tuple[tuple[RunReportKind, str], ...] = (
    ("software_versions", "software_versions_path"),
    ("params", "params_json_path"),
    ("execution_report", "execution_report_path"),
    ("execution_trace", "execution_trace_path"),
    ("pipeline_dag", "pipeline_dag_path"),
)


class RunReportFile(BaseModel):
    """One file the run's engine wrote about the run, such as its execution report.

    ``location`` is its real path, or its ``s3://`` URL. ``size`` is in bytes,
    None when unknown.
    """

    kind: RunReportKind
    location: str
    name: str
    size: int | None = None


class RunInfoSummary(BaseModel):
    """What the run's own records say about it, for display.

    ``params`` holds at most :data:`MAX_RUN_PARAMS` of the run's parameters,
    by name: a list or a mapping is written as JSON, a long text is cut at
    :data:`MAX_PARAM_CHARS` characters, and a parameter whose name says it
    holds a credential is shown as :data:`HIDDEN_PARAM`. ``params_total`` is
    how many the run has. ``extra`` is the engine's other details that are a
    single text or number.
    """

    engine: str | None = None
    engine_version: str | None = None
    run_name: str | None = None
    homepage: str | None = None
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    params_total: int = 0
    tools_executed: list[str] = Field(default_factory=list)
    reports: list[RunReportFile] = Field(default_factory=list)
    extra: dict[str, str] = Field(default_factory=dict)


class FolderInspection(BaseModel):
    """What one folder holds, direct children only, and the run in it.

    ``detected`` is None when detection was not asked for, or when no engine
    recognised the folder. ``run_info`` is set whenever ``detected`` is, even
    when no installed template fits the run.
    """

    location: str
    source: Literal["local", "s3"]
    name: str
    looks_like_run: bool = False
    markers: list[str] = Field(default_factory=list)
    folders: FolderNames = Field(default_factory=FolderNames)
    files: FolderNames = Field(default_factory=FolderNames)
    truncated: bool = False
    detected: DetectedTemplate | None = None
    run_info: RunInfoSummary | None = None


class FoundRun(BaseModel):
    """One run folder below the searched folder.

    ``relative`` is its path from the searched folder (``"."`` for that folder
    itself), ``location`` its real path or ``s3://`` URL.
    """

    location: str
    name: str
    relative: str
    markers: list[str] = Field(default_factory=list)
    detected: DetectedTemplate | None = None


class S3DirsRequest(BaseModel):
    """Body of POST /projects/s3_dirs: the query of the GET route, and storage settings.

    Without ``url`` the listed locations are answered and ``storage`` is not used.
    """

    url: str | None = None
    storage: RunStorageIn | None = None


class FolderInspectRequest(BaseModel):
    """Body of POST /projects/folder_inspect. ``storage`` is for an ``s3://`` location."""

    location: str
    detect: bool = True
    storage: RunStorageIn | None = None


class FindRunsRequest(BaseModel):
    """Body of POST /projects/find_runs. ``storage`` is for an ``s3://`` location."""

    location: str
    storage: RunStorageIn | None = None


class FoundRuns(BaseModel):
    """The run folders below ``location``, sorted by ``relative``.

    ``scanned`` is how many folders the search opened (local) or keys it
    listed (S3). ``truncated`` says a bound stopped it: the depth, the number
    of folders or keys, or more than :data:`FIND_MAX_RUNS` runs.
    """

    location: str
    runs: list[FoundRun] = Field(default_factory=list)
    truncated: bool = False
    scanned: int = 0


# ── locations ────────────────────────────────────────────────────────────────


def _unsupported_location() -> CodedHTTPException:
    rule = LOCATION_RULE_LOCAL if local_data_policy() is not None else LOCATION_RULE
    return CodedHTTPException(422, rule, "location_unsupported")


def _local_folder(location: str, *, request, current_user) -> tuple[LocalDataPolicy, str]:
    """The policy and the real path of local folder ``location``, once allowed.

    The refusals of ``GET /projects/local_dirs``: 404 when local folders are
    off or the policy refuses the path, 403 for a foreign ``Host`` or a
    non-administrator.
    """
    policy = active_local_policy()
    require_local_caller(request, current_user)
    try:
        return policy, policy.confine(location, want="dir")
    except LocalPathRefused as exc:
        raise CodedHTTPException(404, exc.detail, exc.code) from exc


def allowed_s3_locations() -> list[tuple[str, str]]:
    """``(bucket, prefix)`` of every location listed for every user, public ones first.

    The instance's own bucket is left out even when listed: it is never read
    as a data source. Each location once, as the administrator spelled it.
    """
    policy = remote_fetch.remote_policy()
    instance_s3 = _run_folder_read_config().s3_storage
    locations: list[tuple[str, str]] = []
    for raw in (policy.public_s3_buckets, policy.credentialed_s3_buckets):
        for bucket, prefix in parse_bucket_list(raw):
            if is_instance_bucket(bucket, instance_s3) or (bucket, prefix) in locations:
                continue
            locations.append((bucket, prefix))
    return locations


@dataclass(frozen=True)
class _S3Folder:
    """An ``s3://`` location the server may read, taken as a folder."""

    target: S3Target
    bucket: str
    # "" for the bucket itself, else ending in "/".
    prefix: str
    # The prefix of the outermost listed location holding it, same spelling;
    # "" (the bucket) when it is read with storage settings.
    root: str
    # What every other read of the folder (detection) is decided from.
    reads: _RunFolderReads

    @property
    def url(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"

    @property
    def name(self) -> str:
        return self.prefix.rstrip("/").rsplit("/", 1)[-1] if self.prefix else self.bucket

    @property
    def parent(self) -> str | None:
        """One level up, None at the listed location it was reached from."""
        if self.prefix == self.root:
            return None
        return f"s3://{self.bucket}/{folder_prefix(self.prefix.rstrip('/').rpartition('/')[0])}"

    def child(self, name: str) -> str:
        return f"{self.url}{name}/"


def _s3_folder(url: str, storage: RunStorageIn | None = None) -> _S3Folder:
    """The folder ``url`` names, once the configuration lets the server read it.

    Decided from configuration alone, before any request: a malformed
    location, the instance's own bucket and a bucket nobody listed are refused
    by ``resolve_s3_target`` (``S3AccessRefused``, code ``s3_refused``), and so
    is a location above the listed one (``s3://b/`` when only ``s3://b/runs``
    is listed). The listed locations are then checked once more, so nothing
    outside them is browsed whatever the process context. Only then is the
    bucket asked for its region, once per process, as for any run folder.

    With ``storage`` the settings are validated as a saved config is (see
    ``RunStorageIn.settings_for``: 400 or 422, the instance's bucket
    ``S3AccessRefused``) and the folder is read with them alone; the lists do
    not apply, and the bucket itself is the root.
    """
    bucket, key = split_s3_url(url)
    prefix = folder_prefix(key)
    location = f"s3://{bucket}/{prefix}"
    if storage is not None:
        reads = _run_folder_read_config(read_settings(storage.settings_for(location)))
        target = remote_fetch.s3_read_target(location, reads)
        root = ""
    else:
        reads = _run_folder_read_config()
        target = remote_fetch.s3_read_target(location, reads)
        holding = [
            listed
            for listed_bucket, listed in allowed_s3_locations()
            if listed_bucket == bucket and (not listed or prefix.startswith(f"{listed}/"))
        ]
        if not holding:
            raise S3AccessRefused(f"{location} is not a location this server lets you browse.")
        # The outermost one, so going up stops where nothing is readable any more.
        root = folder_prefix(min(holding, key=len))
    return _S3Folder(
        target=ensure_region(target), bucket=bucket, prefix=prefix, root=root, reads=reads
    )


def _first_page(folder: _S3Folder) -> dict:
    """One ``Delimiter="/"`` listing page of ``folder``: its direct children, at
    most 1,000 (the S3 page size). An empty dict when the prefix holds nothing."""
    return next(iter_object_pages(folder.target, folder.prefix, delimiter="/"), {})


def _page_folders(folder: _S3Folder, page: dict) -> list[str]:
    """The sub-folder names on a ``Delimiter="/"`` page of ``folder``, sorted."""
    names = {
        str(common.get("Prefix") or "")[len(folder.prefix) :].strip("/")
        for common in page.get("CommonPrefixes") or []
    }
    return sorted(name for name in names if name)


def _page_files(folder: _S3Folder, page: dict) -> list[str]:
    """The object names on a ``Delimiter="/"`` page of ``folder``, sorted.

    The zero-byte key some consoles create to stand for the folder itself is
    not one of them.
    """
    names = {str(obj.get("Key") or "")[len(folder.prefix) :] for obj in page.get("Contents") or []}
    return sorted(name for name in names if name and "/" not in name)


def _multiqc_output_below(parts: list[str]) -> bool:
    """Whether the segments of a key below a ``multiqc/`` folder are MultiQC
    output, in that folder or one folder down: ``multiqc_data/...``,
    ``multiqc.parquet``, ``star_salmon/multiqc_report.html`` (see
    :func:`~local_dirs.is_multiqc_output`)."""
    for depth in (0, 1):
        if depth >= len(parts):
            return False
        is_dir = depth < len(parts) - 1
        if is_multiqc_output(parts[depth], is_dir=is_dir):
            return True
        if not is_dir:
            return False
    return False


def _s3_holds_multiqc_output(folder: _S3Folder) -> bool:
    """Whether the ``multiqc/`` of ``folder`` holds MultiQC output, from one page
    of the keys below it (at most 1,000, the S3 page size), each read as
    :func:`_run_of` reads it.

    One page settles it unless the sub-folders sorting before MultiQC's own
    entries hold over 1,000 keys between them. A page that cannot be read says
    no: the marker is a hint, and the read that matters reports the failure.
    """
    prefix = f"{folder.prefix}{MULTIQC}/"
    try:
        page = next(iter_object_pages(folder.target, prefix), {})
    except S3AccessFailed as exc:
        logger.info(f"run_folders: cannot list {folder.url}{MULTIQC}/: {exc.code}")
        return False
    return any(
        _multiqc_output_below(str(obj.get("Key") or "")[len(prefix) :].split("/"))
        for obj in page.get("Contents") or []
    )


def _s3_markers(folder: _S3Folder, folder_names: list[str]) -> list[str]:
    """The run markers among the sub-folders ``folder_names`` of ``folder``, in
    name order (see :data:`~local_dirs.RUN_MARKERS`).

    A ``Delimiter`` page cannot see inside ``multiqc/``, so a ``multiqc/``
    among them costs one more page (:func:`_s3_holds_multiqc_output`); none
    is asked for otherwise.
    """
    return sorted(
        marker
        for marker in RUN_MARKERS
        if marker in folder_names and (marker != MULTIQC or _s3_holds_multiqc_output(folder))
    )


# ── GET /projects/s3_dirs ────────────────────────────────────────────────────


def list_s3_dirs(url: str | None, storage: RunStorageIn | None = None) -> S3DirListing:
    """The sub-folders of ``url``, or the listed locations without one.

    Refusals are ``S3AccessError`` (see :func:`_s3_folder`): the API answers
    them ``{detail, code}``. A prefix that holds nothing lists as empty.
    ``url`` is read with ``storage`` when given; without ``url`` it is unused.
    """
    if not url:
        return S3DirListing(
            entries=[
                LocalDirEntry(
                    name=f"{bucket}/{prefix}" if prefix else bucket,
                    path=f"s3://{bucket}/{folder_prefix(prefix)}",
                    has_children=True,
                )
                for bucket, prefix in allowed_s3_locations()
            ]
        )

    folder = _s3_folder(url, storage)
    page = _first_page(folder)
    names = _page_folders(folder, page)
    return S3DirListing(
        path=folder.url,
        root=f"s3://{folder.bucket}/{folder.root}",
        parent=folder.parent,
        # pipeline_info/ first: then no page is asked for below multiqc/.
        looks_like_run=PIPELINE_INFO in names or bool(_s3_markers(folder, names)),
        entries=[
            LocalDirEntry(name=name, path=folder.child(name), has_children=True)
            for name in names[:MAX_ENTRIES]
        ],
        truncated=len(names) > MAX_ENTRIES or bool(page.get("IsTruncated")),
    )


# ── GET /projects/folder_inspect ─────────────────────────────────────────────


def _detect(root) -> DetectedTemplate | None:
    """The run in data root ``root`` and the template that fits it, or None when
    no engine recognises it. A read that fails while looking is None too,
    except an S3 refusal or failure, which keeps its own code."""
    return _detect_with_info(root)[0]


def _detect_with_info(root) -> tuple[DetectedTemplate | None, WorkflowRunInfo | None]:
    """:func:`_detect`, and the run's provenance it was decided from (None alike)."""
    template_id, info = _detect_run(root)
    return describe_detection(template_id, info), info


def _clipped(text: str) -> str:
    return text if len(text) <= MAX_PARAM_CHARS else f"{text[:MAX_PARAM_CHARS]}..."


def _param_value(value: object) -> str | int | float | bool | None:
    """One run parameter as :class:`RunInfoSummary` shows it."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        # NaN and infinity are not JSON.
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _clipped(value)
    try:
        text = json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return _clipped(text)


def _run_params(params: dict) -> dict[str, str | int | float | bool | None]:
    """The first :data:`MAX_RUN_PARAMS` of ``params`` by name, as shown."""
    named = sorted(((str(name), value) for name, value in params.items()), key=lambda p: p[0])
    return {
        name: HIDDEN_PARAM if SECRET_PARAM_NAME.search(name) else _param_value(value)
        for name, value in named[:MAX_RUN_PARAMS]
    }


def _run_extra(extra: dict) -> dict[str, str]:
    """The entries of ``WorkflowRunInfo.extra`` that are one text or number, as text."""
    return {
        str(name): _clipped(str(value))
        for name, value in sorted(extra.items(), key=lambda item: str(item[0]))
        if isinstance(value, str | int | float) and not isinstance(value, bool)
    }


def _report_size(
    location: str, root, policy: LocalDataPolicy | None, listed: dict[str, int] | None
) -> int | None:
    """The size of report ``location`` of data root ``root``, None when unknown.

    Never a read of the file. An ``s3://`` root answers from the sizes of the
    listing it already holds (``listed``, by root-relative path). A local one
    stats a location below the root only, and only where ``policy`` lets the
    server read data; without a policy, no size.
    """
    relative = root.relative_of(location)
    if relative is None:
        return None
    if listed is not None:
        size = listed.get(relative)
        return size if size is not None and size >= 0 else None
    if policy is None or not policy.allows(location):
        return None
    try:
        return os.stat(location).st_size
    except OSError:
        return None


def _run_info_summary(
    info: WorkflowRunInfo | None, root, policy: LocalDataPolicy | None = None
) -> RunInfoSummary | None:
    """What :class:`RunInfoSummary` shows of ``info``, the run read from ``root``.

    The report locations are those ``run_detection.read_run_info_for_root``
    mapped back below the root; ``policy`` is the local-data policy a local
    root was confined with (see :func:`_report_size`).
    """
    if info is None:
        return None
    objects = getattr(root, "objects", None)
    listed = {obj.relative: obj.size for obj in objects} if objects is not None else None
    reports: list[RunReportFile] = []
    for kind, field_name in _REPORT_FIELDS:
        location = getattr(info, field_name)
        if not location:
            continue
        reports.append(
            RunReportFile(
                kind=kind,
                location=location,
                name=location.rstrip("/").rsplit("/", 1)[-1],
                size=_report_size(location, root, policy, listed),
            )
        )
    return RunInfoSummary(
        engine=info.engine,
        engine_version=info.engine_version,
        run_name=info.run_name,
        homepage=info.homepage,
        params=_run_params(info.params),
        params_total=len(info.params),
        tools_executed=sorted(info.tools_executed),
        reports=reports,
        extra=_run_extra(info.extra),
    )


def _local_children(policy: LocalDataPolicy, folder: str) -> tuple[list[str], list[str], bool]:
    """``(folder names, file names, truncated)`` of real folder ``folder``.

    What the policy lets the server read only: no dot-names, no symlink that
    leaves the roots, no folder Depictio keeps for itself. The noise folders
    the listing hides (:data:`~local_dirs.NOISE_DIRS`) are left out too. At
    most :data:`MAX_INSPECT_ENTRIES` entries are looked at. A folder the
    server may not read holds nothing.
    """
    folders: list[str] = []
    files: list[str] = []
    try:
        with os.scandir(folder) as scan:
            for examined, entry in enumerate(scan):
                if examined == MAX_INSPECT_ENTRIES:
                    return sorted(folders), sorted(files), True
                if entry.name.startswith(".") or not policy.allows(entry.path):
                    continue
                if is_directory(entry):
                    if entry.name not in NOISE_DIRS:
                        folders.append(entry.name)
                elif entry.is_file():
                    files.append(entry.name)
    except OSError as exc:
        logger.info(f"folder_inspect: cannot list {folder}: {exc}")
    return sorted(folders), sorted(files), False


def _inspection(
    *,
    location: str,
    source: Literal["local", "s3"],
    name: str,
    folders: list[str],
    files: list[str],
    markers: list[str],
    truncated: bool,
    detected: DetectedTemplate | None,
    run_info: RunInfoSummary | None = None,
) -> FolderInspection:
    return FolderInspection(
        location=location,
        source=source,
        name=name,
        looks_like_run=bool(markers),
        markers=markers,
        folders=FolderNames(count=len(folders), names=folders[:MAX_NAMES]),
        files=FolderNames(count=len(files), names=files[:MAX_NAMES]),
        truncated=truncated,
        detected=detected,
        run_info=run_info,
    )


def inspect_folder(
    location: str,
    *,
    detect: bool = True,
    storage: RunStorageIn | None = None,
    request,
    current_user,
) -> FolderInspection:
    """What ``location`` holds, and, with ``detect``, the template its run fits.

    A local folder answers the refusals of ``GET /projects/local_dirs``; an
    ``s3://`` one those of ``GET /projects/s3_dirs``, read with ``storage``
    when given; anything else is a 422 ``location_unsupported``. Detection
    reads the folder the way ``POST /projects/from_run`` does, so what it names
    is what the creation would pick. ``run_info`` comes from that same read:
    the sizes of the run's reports from the S3 listing it made, or from the
    files themselves on this computer, never from their contents.
    """
    if is_s3_url(location):
        folder = _s3_folder(location, storage)
        page = _first_page(folder)
        detected = run_info = None
        if detect:
            root = _build_data_root(folder.url, folder.reads)
            detected, info = _detect_with_info(root)
            run_info = _run_info_summary(info, root)
        folders = _page_folders(folder, page)
        return _inspection(
            location=folder.url,
            source="s3",
            name=folder.name,
            folders=folders,
            files=_page_files(folder, page),
            markers=_s3_markers(folder, folders),
            truncated=bool(page.get("IsTruncated")),
            detected=detected,
            run_info=run_info,
        )
    if not _is_local_path(location):
        raise _unsupported_location()

    policy, real = _local_folder(location, request=request, current_user=current_user)
    folders, files, truncated = _local_children(policy, real)
    detected = run_info = None
    if detect:
        from depictio.cli.cli.utils.data_root import LocalDataRoot

        root = LocalDataRoot(real)
        detected, info = _detect_with_info(root)
        run_info = _run_info_summary(info, root, policy)
    return _inspection(
        location=real,
        source="local",
        name=os.path.basename(real) or real,
        folders=folders,
        files=files,
        markers=run_markers(real, folders, policy),
        truncated=truncated,
        detected=detected,
        run_info=run_info,
    )


# ── GET /projects/find_runs ──────────────────────────────────────────────────


def _walk_names(folder: str) -> list[str]:
    """The sub-directory names of real folder ``folder``, hidden ones left out
    (dot-names, :data:`~local_dirs.NOISE_DIRS`): plain folders first, then
    symlinked ones, each in name order.

    Plain first, so a link to a folder of the same parent (``latest`` to
    ``run42``) is the copy the search drops, not the folder itself.
    """
    plain: list[str] = []
    linked: list[str] = []
    try:
        with os.scandir(folder) as scan:
            for entry in scan:
                if is_hidden_name(entry.name) or not is_directory(entry):
                    continue
                (linked if entry.is_symlink() else plain).append(entry.name)
    except OSError as exc:
        logger.info(f"find_runs: cannot list {folder}: {exc}")
    return sorted(plain) + sorted(linked)


def _is_nextflow_work(name: str, folder_names: list[str]) -> bool:
    """Whether a folder named ``name`` holding sub-folders ``folder_names`` is a
    Nextflow work directory: ``work``, holding task folders named by two hex
    digits and nothing but Nextflow's own (see :data:`NEXTFLOW_WORK_EXTRAS`).

    It can hold tens of thousands of folders, and never a run's results.
    """
    if name != "work" or not any(NEXTFLOW_TASK_FOLDER.fullmatch(n) for n in folder_names):
        return False
    return all(
        NEXTFLOW_TASK_FOLDER.fullmatch(n) or n.startswith("stage-") or n in NEXTFLOW_WORK_EXTRAS
        for n in folder_names
    )


def _find_local_runs(policy: LocalDataPolicy, start: str) -> FoundRuns:
    """The run folders at most :data:`FIND_MAX_DEPTH` levels below real folder
    ``start``, breadth first. ``truncated`` when a folder at that depth holds
    sub-folders, as for the other bounds.

    A folder is confined by the policy when it is opened, not when it is
    found, so the cost is bounded by the :data:`FIND_MAX_DIRS` folders opened
    whatever their size. A hidden, denied or escaping folder is never opened,
    a link to a folder already opened is not opened twice, and neither a run
    nor a Nextflow work directory (:func:`_is_nextflow_work`) is searched
    below. The queue never holds more folders than are left to open.
    """
    found: list[FoundRun] = []
    queue: deque[tuple[str, str, int]] = deque([(start, "", 0)])
    opened: set[str] = set()
    truncated = False
    while queue:
        path, relative, depth = queue.popleft()
        try:
            folder = policy.confine(path, want="dir")
        except LocalPathRefused:
            continue
        if folder in opened:
            continue
        if len(opened) == FIND_MAX_DIRS:
            truncated = True
            break
        opened.add(folder)

        names = _walk_names(folder)
        markers = run_markers(folder, names, policy)
        if markers:
            found.append(
                FoundRun(
                    location=folder,
                    name=relative.rsplit("/", 1)[-1] if relative else os.path.basename(folder),
                    relative=relative or SELF,
                    markers=markers,
                )
            )
            continue
        if _is_nextflow_work(os.path.basename(path), names):
            # Left out on purpose, as a hidden folder is: not a bound.
            continue
        if depth == FIND_MAX_DEPTH:
            # Folders below are left unsearched: a bound stopped the search.
            truncated = truncated or bool(names)
            continue
        for name in names:
            if len(opened) + len(queue) >= FIND_MAX_DIRS:
                truncated = True
                break
            queue.append(
                (os.path.join(folder, name), f"{relative}/{name}" if relative else name, depth + 1)
            )

    found.sort(key=lambda run: run.relative)
    if len(found) > FIND_MAX_RUNS:
        found, truncated = found[:FIND_MAX_RUNS], True

    from depictio.cli.cli.utils.data_root import LocalDataRoot

    for run in found[:FIND_DETECT_RUNS]:
        run.detected = _detect(LocalDataRoot(run.location))
    return FoundRuns(location=start, runs=found, truncated=truncated, scanned=len(opened))


def _run_of(relative_key: str) -> tuple[str, str] | None:
    """``(run, marker)`` for a key relative to the searched prefix, or None.

    The run is the part before the key's first ``pipeline_info/`` segment, or
    before a ``multiqc/`` one whose rest is MultiQC output
    (:func:`_multiqc_output_below`). A key below a Nextflow task folder
    (``work/3f/...``) is no run's: a task holds copies of whatever it read.
    """
    parts = relative_key.split("/")
    folders = parts[:-1]
    for index, part in enumerate(folders):
        if (
            part == "work"
            and index + 1 < len(folders)
            and NEXTFLOW_TASK_FOLDER.fullmatch(folders[index + 1])
        ):
            return None
        if part == PIPELINE_INFO or (part == MULTIQC and _multiqc_output_below(parts[index + 1 :])):
            return "/".join(parts[:index]), part
    return None


def _find_s3_runs(location: str, storage: RunStorageIn | None = None) -> FoundRuns:
    """The run folders below ``location``, from one listing of at most
    :data:`FIND_MAX_KEYS` keys. A run inside another run is not one of them."""
    folder = _s3_folder(location, storage)
    markers: dict[str, set[str]] = {}
    examined = 0
    truncated = False
    for page in iter_object_pages(folder.target, folder.prefix):
        for obj in page.get("Contents") or []:
            if examined == FIND_MAX_KEYS:
                truncated = True
                break
            examined += 1
            hit = _run_of(str(obj.get("Key") or "")[len(folder.prefix) :])
            if hit is not None:
                markers.setdefault(hit[0], set()).add(hit[1])
        if truncated or (examined == FIND_MAX_KEYS and page.get("IsTruncated", True)):
            truncated = True
            break

    kept: list[str] = []
    # Shallowest first, so a run is seen before anything inside it.
    for run in sorted(markers, key=lambda run: (run.count("/") if run else -1, run)):
        if not any(not outer or run.startswith(f"{outer}/") for outer in kept):
            kept.append(run)
    runs = [
        FoundRun(
            location=folder.child(run) if run else folder.url,
            name=run.rsplit("/", 1)[-1] if run else folder.name,
            relative=run or SELF,
            markers=sorted(markers[run]),
        )
        for run in kept
    ]
    runs.sort(key=lambda found: found.relative)
    if len(runs) > FIND_MAX_RUNS:
        runs, truncated = runs[:FIND_MAX_RUNS], True
    return FoundRuns(location=folder.url, runs=runs, truncated=truncated, scanned=examined)


def find_runs(
    location: str, *, storage: RunStorageIn | None = None, request, current_user
) -> FoundRuns:
    """The run folders below ``location``: those holding ``pipeline_info/``, or a
    ``multiqc/`` holding MultiQC output (``multiqc_data/``, ``multiqc.parquet``
    or a ``*multiqc_report.html``, in it or one folder down), the searched
    folder itself included.

    Same refusals as :func:`inspect_folder`, and the same use of ``storage``.
    Below a local folder, the first :data:`FIND_DETECT_RUNS` runs carry the
    template detected for them; below an ``s3://`` prefix none do, since each
    would cost a listing of its own.
    """
    if is_s3_url(location):
        return _find_s3_runs(location, storage)
    if not _is_local_path(location):
        raise _unsupported_location()
    policy, real = _local_folder(location, request=request, current_user=current_user)
    return _find_local_runs(policy, real)
