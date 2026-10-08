"""Server-side manifest ingestion into an existing project (RFC remote-data, phase 2).

``POST /projects/ingest_manifest`` maps a Data Manifest's ``type`` values onto
the project's data-collection tags, switches each matched DC to
``scan.mode: manifest``, and runs scan + process in-process through the same
CLI helpers as the create-DC flows. The result is a per-DC ingestion report.

Sequencing per DC (mirrors ``_push_workflow_and_ingest``): the new scan config
is persisted *before* the helpers run (the helpers' API callbacks read the DC
from the project document) and reverted for any DC whose scan or process
fails, so a failed ingestion never leaves a manifest scan config pointing at
data that was never materialized. The scan also replaces the DC's File
records with the manifest's entries, so those are snapshotted before it and
put back on failure. Both writes touch that one DC only: the other DCs of the
call, and anything else edited in the meantime, are left as they are.

``POST /projects/refresh_manifest`` re-runs the stored scan of every data
collection this process can read again. First ingestion runs its DCs one
after the other; a refresh can instead fan them out to Celery workers
(``async_run``), polled through ``GET /projects/refresh_manifest/{run_id}``.
"""

import copy
import os
import tempfile
from collections.abc import Callable
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.db import files_collection, projects_collection
from depictio.api.v1.remote_fetch import (
    RemoteURLRejected,
    bounded_download,
    validate_remote_url,
)
from depictio.models.logging import logger
from depictio.models.models.manifest import DataManifest, manifest_field_map
from depictio.models.s3_access import ProjectS3Config

# Manifests are indexes, not data: cap them well below the data-file cap.
MANIFEST_MAX_BYTES = 50 * 1024 * 1024

# Rejected entries listed in a 400 body (the summary string names at most 5).
MAX_REJECTED_ENTRIES_LISTED = 20

S3_MANIFEST_UNSUPPORTED = (
    "s3:// manifest locations are not supported yet: serve the manifest over https."
)


class ManifestEntriesRejected(RemoteURLRejected):
    """One or more manifest entry URLs failed the fetch gateway's checks.

    ``str(exc)`` is a short client-safe summary (used as the per-DC message on
    refresh); ``detail()`` is the structured HTTP 400 body listing the
    offending entries. Nothing is registered or fetched when this is raised.
    """

    def __init__(self, rejected: list[dict[str, str]]):
        self.rejected = rejected
        count = len(rejected)
        shown = "; ".join(f"{r['type']}/{r['id']} ({r['reason']})" for r in rejected[:5])
        more = f"; and {count - 5} more" if count > 5 else ""
        noun = "entry" if count == 1 else "entries"
        super().__init__(
            f"{count} manifest {noun} rejected by the fetch gateway, nothing was ingested: "
            f"{shown}{more}"
        )

    def detail(self) -> dict:
        return {
            "message": str(self),
            "rejected_count": len(self.rejected),
            "rejected_entries": self.rejected[:MAX_REJECTED_ENTRIES_LISTED],
        }


def _reject_unsafe_entry_urls(manifest: DataManifest) -> None:
    """Run every entry URL through the fetch gateway before anything is registered.

    Parsing only checks entry URLs syntactically; the scan then registers each
    one as a File and the worker downloads it server-side. Without this gate a
    public manifest could point an entry at an internal service or the cloud
    metadata endpoint and have the response land in a readable Delta table.

    The gateway's verdict depends on scheme and host only (allow/deny lists,
    DNS, address ranges), so each distinct host is checked once: a manifest
    with thousands of entries on one host costs one resolution, not thousands.
    """
    verdicts: dict[tuple[str, str], str | None] = {}
    rejected: list[dict[str, str]] = []
    for entry in manifest.entries:
        parsed = urlparse(entry.url)
        key = (parsed.scheme.lower(), parsed.netloc.lower())
        if key not in verdicts:
            try:
                validate_remote_url(entry.url)
                verdicts[key] = None
            except RemoteURLRejected as exc:
                verdicts[key] = str(exc)
        reason = verdicts[key]
        if reason is not None:
            rejected.append(
                {"id": entry.id, "type": entry.type, "url": entry.url, "reason": reason}
            )
    if rejected:
        raise ManifestEntriesRejected(rejected)


class IngestManifestRequest(BaseModel):
    """Body of POST /projects/ingest_manifest."""

    project_id: str
    manifest_url: str
    # Column overrides for non-canonical manifests (see ScanManifest).
    id_field: str = "id"
    url_field: str = "url"
    type_field: str = "type"
    run_field: str | None = "run"
    # Plan-only: report the type→tag mapping without touching the project.
    dry_run: bool = False


class ManifestIngestDCResult(BaseModel):
    data_collection_tag: str
    data_collection_id: str
    entries: int
    status: str  # "ingested" | "failed" | "skipped" | "planned" (dry_run)
    message: str | None = None


class RefreshManifestRequest(BaseModel):
    """Body of POST /projects/refresh_manifest."""

    project_id: str
    # Restrict the refresh to one DC tag; None refreshes every manifest DC.
    data_collection_tag: str | None = None
    # Plan-only: report what would be refreshed without touching any data.
    dry_run: bool = False
    # Fan the per-DC re-ingestions out to Celery workers instead of running
    # them inline, for long manifests. The response then reports each DC as
    # "dispatched" with a run_id to poll via GET /projects/refresh_manifest/{run_id}.
    async_run: bool = False


class ManifestRefreshReport(BaseModel):
    project_id: str
    refreshed: list[ManifestIngestDCResult] = Field(default_factory=list)
    # Ingestion-run id for polling, set when async_run dispatched workers.
    run_id: str | None = None
    dry_run: bool = False
    success: bool = False


class ManifestIngestReport(BaseModel):
    project_id: str
    manifest_url: str
    manifest_entries: int
    matched: list[ManifestIngestDCResult] = Field(default_factory=list)
    # Manifest types with no matching DC tag: data the project can't hold yet.
    unmatched_manifest_types: list[str] = Field(default_factory=list)
    # Project DC tags the manifest says nothing about, left untouched.
    unmatched_dc_tags: list[str] = Field(default_factory=list)
    dry_run: bool = False
    success: bool = False


def _validate_manifest_url(manifest_url: str) -> None:
    """Gate a manifest URL before anything is fetched. Raises ``RemoteURLRejected``.

    The fetch gateway's own checks first, then the one location the gateway
    accepts but manifest fetching does not: ``s3://`` (tracked in the RFC).
    """
    validate_remote_url(manifest_url)
    if manifest_url[:5].lower() == "s3://":
        raise RemoteURLRejected(S3_MANIFEST_UNSUPPORTED)


def _fetch_and_parse_manifest(manifest_url: str, field_map: dict[str, str]) -> DataManifest:
    """Download the manifest through the SSRF gateway and parse it.

    Server context only accepts remote manifests (https; s3 is tracked in the
    RFC): local paths are a CLI affordance. Format is decided by extension
    then content sniffing, same as the CLI's ``fetch_manifest``.

    Every entry URL is gateway-validated before the manifest is returned
    (raises ``ManifestEntriesRejected``, a ``RemoteURLRejected``), so no
    caller can register an entry the worker must not fetch.
    """
    tmp = tempfile.NamedTemporaryFile(prefix="depictio_manifest_", delete=False)
    tmp.close()
    try:
        bounded_download(manifest_url, tmp.name, max_bytes=MANIFEST_MAX_BYTES)
        with open(tmp.name, encoding="utf-8") as fh:
            text = fh.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    manifest = DataManifest.parse(text, source=manifest_url, field_map=field_map)
    _reject_unsafe_entry_urls(manifest)
    return manifest


def _manifest_field_map(scan_params: dict) -> dict[str, str]:
    """Canonical manifest field -> the column a DC's manifest scan reads it from.

    The map ``scan_manifest_for_data_collection`` parses with: ``ScanManifest``'s
    defaults, an empty override reading the canonical column. ``run`` is always
    named, since an absent one reads the ``run`` column anyway, so two DCs that
    read the same columns get equal maps.
    """
    return {
        "id": scan_params.get("id_field") or "id",
        "type": scan_params.get("type_field") or "type",
        "url": scan_params.get("url_field") or "url",
        "run": scan_params.get("run_field") or "run",
    }


def _manifest_type_of(scan_params: dict, tag: str) -> str:
    """The manifest ``type`` a DC consumes: its ``manifest_type``, else its tag.

    ``ScanManifest`` requires a non-empty ``manifest_type`` and strips it, so a
    stored DC always carries one, and ingestion writes the tag there (the
    convention). The fallback covers a template not validated yet: an empty
    value counts the tag's rows rather than rows of type ``''``, and the model
    refuses it when the project is built.
    """
    return str(scan_params.get("manifest_type") or "").strip() or tag


def _live_dc_index(project_dict: dict) -> dict[str, tuple[int, int]]:
    """{dc_tag: (workflow_index, dc_index)} across all of the project's workflows."""
    index: dict[str, tuple[int, int]] = {}
    for wf_i, wf in enumerate(project_dict.get("workflows", []) or []):
        for dc_i, dc in enumerate(wf.get("data_collections", []) or []):
            tag = dc.get("data_collection_tag")
            if tag and tag not in index:
                index[tag] = (wf_i, dc_i)
    return index


def _dc_id(dc_dict: dict) -> str:
    """A stored data collection's id as a string, ``""`` when it has none."""
    return str(dc_dict.get("_id") or dc_dict.get("id") or "")


def _load_editable_project(project_id: str, current_user) -> tuple[ObjectId, dict]:
    """The project's id and document, once ``current_user`` may edit it.

    400 for a malformed id, 404 for an unknown project, 403 without edit
    permission.
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _user_can_edit_project,
    )

    try:
        project_oid = ObjectId(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid project_id: {exc}")

    project_dict = projects_collection.find_one({"_id": project_oid})
    if not project_dict:
        raise HTTPException(status_code=404, detail="Project not found.")
    if not _user_can_edit_project(
        project_dict, current_user.id, getattr(current_user, "is_admin", False)
    ):
        raise HTTPException(
            status_code=403, detail="You don't have edit permission on this project."
        )
    return project_oid, project_dict


def _set_dc_scan(project_oid: ObjectId, dc_oid, scan: dict | None) -> None:
    """``$set`` one data collection's ``config.scan``, and nothing else of the project.

    A ``$set`` of the whole ``workflows`` array would write back the copy this
    request read, wiping the ``flexible_metadata`` the deltatable upsert wrote
    for a DC ingested earlier in the same call, and any concurrent edit. The
    path is positional (mongomock, the test backend, has no array filters), so
    the position is read from the current document and the write is guarded by
    the DC's id: a DC that moved in between is never confused with the one now
    at its old position.
    """
    current = projects_collection.find_one({"_id": project_oid}, {"workflows": 1}) or {}
    for wf_i, wf in enumerate(current.get("workflows") or []):
        for dc_i, dc in enumerate(wf.get("data_collections") or []):
            if dc.get("_id") != dc_oid:
                continue
            path = f"workflows.{wf_i}.data_collections.{dc_i}"
            result = projects_collection.update_one(
                {"_id": project_oid, f"{path}._id": dc_oid},
                {"$set": {f"{path}.config.scan": scan}},
            )
            if result.matched_count:
                return
    logger.warning(
        f"Data collection {dc_oid} not found in project {project_oid}: its scan config "
        "was not written."
    )


def _dc_files(dc_id: str) -> list[dict]:
    """Every File record of a data collection, as stored."""
    if not ObjectId.is_valid(dc_id):
        return []
    return list(files_collection.find({"data_collection_id": ObjectId(dc_id)}))


def _restore_dc_files(dc_id: str, snapshot: list[dict]) -> None:
    """Put a data collection's File records back to ``snapshot``.

    The manifest scan deletes the records absent from the manifest and
    registers one per entry; this undoes both, ids included.
    """
    if not ObjectId.is_valid(dc_id):
        return
    files_collection.delete_many({"data_collection_id": ObjectId(dc_id)})
    if snapshot:
        files_collection.insert_many(snapshot)


def _revert_dc_ingest(
    project_oid: ObjectId, dc_dict: dict, scan: dict | None, files_before: list[dict]
) -> None:
    """One DC back to its pre-ingest scan config and File records, so a failed
    run never leaves a manifest config, or the manifest's files, with no data
    behind them."""
    dc_dict["config"]["scan"] = scan
    _set_dc_scan(project_oid, dc_dict.get("_id"), scan)
    _restore_dc_files(_dc_id(dc_dict), files_before)


def _registers_runs(workflow_dict: dict, dc_dict: dict) -> bool:
    """Whether a data collection's scan writes the workflow's ``WorkflowRun`` documents.

    Two scans do. The ``recursive`` walk (``scan_files_for_workflow``) registers
    one run per run folder. An ``s3_prefix`` scan of a ``sequencing-runs``
    workflow (``scan_s3_prefix_for_data_collection``), which is what a recursive
    collection becomes under an ``s3://`` data root, registers one run per run
    directory under its prefix. Every other scan (single, url, manifest, a flat
    s3_prefix) registers files only: the run its files name is never written.
    """
    mode = str(((dc_dict.get("config") or {}).get("scan") or {}).get("mode") or "").lower()
    if mode == "recursive":
        return True
    location = workflow_dict.get("data_location") or {}
    return (
        mode == "s3_prefix"
        and location.get("structure") == "sequencing-runs"
        and bool(location.get("runs_regex"))
    )


def _scan_failure(scan_result: dict | None) -> str | None:
    """The message a scan that did not succeed fails its collection with, else None."""
    if (scan_result or {}).get("result") == "success":
        return None
    return f"Scan failed: {(scan_result or {}).get('message', 'unknown error')}"


def _run_dc_ingest(
    workflow_dict: dict,
    dc_id: str,
    current_user,
    sync_files: bool = False,
    remote_storage_options: ProjectS3Config | None = None,
    *,
    scan: bool = True,
    scan_dc_ids: list[str] | None = None,
    on_scanned: Callable[[str, str | None], None] | None = None,
) -> tuple[bool, str | None]:
    """Scan + process one DC through the CLI helpers. Returns (ok, error_message).

    A ``recursive`` collection is scanned the way the CLI scans it, by
    ``scan_files_for_workflow``: one walk of the workflow's run folders that
    registers the runs and the files of every recursive collection named in
    ``scan_dc_ids`` (this one alone when None). Collections of one workflow
    share its runs, so in a fan-out one task scans for all of them and the
    others pass ``scan=False`` and only process (see ``_scan_leaders``). A
    collection of ``scan_dc_ids`` that is not walked (an ``s3_prefix`` one
    that registers runs) is scanned here on its own, after the walk, so the
    runs are still written by one task at a time.

    A scan leader scans for every collection of ``scan_dc_ids`` whatever the
    outcome of the others, and reports each outcome to ``on_scanned`` as
    ``(dc_id, error message or None)`` as soon as it is known: that is what a
    follower is ingested or failed on, never the leader's own processing. A
    follower's scan that raises is that follower's failure, not the leader's.

    Synchronous on purpose: the helpers use a sync httpx client back into
    this same FastAPI process (see ``_push_workflow_and_ingest``).

    ``sync_files=True`` forces File-record updates during the scan. The scan's
    change detection keys on ``sha256(url|id)``, an *identity* hash, so a
    refresh over a manifest whose URLs are unchanged but whose remote content
    moved would otherwise skip the File metadata update.

    A data collection with no scan block at all (a ``source: transformed``
    recipe collection) is processed without being scanned: it registers no
    files, its inputs are read from the workflow's data root by the recipe
    layer at process time, and the per-DC scan only speaks
    single/url/s3_prefix/manifest so it would raise on one. The from_run
    fan-out passes such collections, and so does a refresh when the
    workflow's data root is readable from here (see ``_server_can_reread``);
    the manifest flows only ever pass manifest-mode collections.
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _build_cli_config_for_user,
    )
    from depictio.cli.cli.utils.helpers import process_data_collection_helper
    from depictio.models.models.workflows import Workflow

    try:
        # Parse a copy: pydantic's before-validators mutate nested input dicts
        # in place (e.g. replacing dc_specific_properties with model
        # instances), and the caller still $sets workflow_dict back to Mongo.
        workflow = Workflow(**copy.deepcopy(workflow_dict))
    except Exception as exc:
        return False, f"Could not parse workflow: {exc}"

    cli_config = _build_cli_config_for_user(
        current_user, remote_storage_options=remote_storage_options
    )

    def _mode(dc) -> str:
        return dc.config.scan.mode.lower() if dc.config.scan else ""

    target = next((dc for dc in workflow.data_collections if str(dc.id) == dc_id), None)
    if scan:
        wanted = set(scan_dc_ids or []) | {dc_id}
        walked = [
            dc
            for dc in workflow.data_collections
            if str(dc.id) in wanted and _mode(dc) == "recursive"
        ]
        # Every other collection with a scan block is scanned on its own; one
        # with none (a recipe) has nothing to scan. An unknown target is
        # scanned too, so the helper says it is not found.
        listed = [
            str(dc.id)
            for dc in workflow.data_collections
            if str(dc.id) in wanted and _mode(dc) not in ("", "recursive")
        ]
        if target is None:
            listed.append(dc_id)

        # (collection ids, whether they are the one walk), the walk first.
        units: list[tuple[list[str], bool]] = (
            [([str(dc.id) for dc in walked], True)] if walked else []
        )
        units += [([scanned_id], False) for scanned_id in listed]
        own_error: str | None = None
        own_exc: Exception | None = None
        for unit, is_walk in units:
            try:
                if is_walk:
                    from depictio.cli.cli.utils.scan import scan_files_for_workflow

                    scan_result = scan_files_for_workflow(
                        workflow=workflow,
                        data_collections=walked,
                        CLI_config=cli_config,
                        # A refresh re-walks the runs already registered, as it
                        # re-reads every other source: overwrite-with-report.
                        command_parameters={
                            "sync_files": sync_files,
                            "rescan_folders": True,
                            "rich_tables": False,
                        },
                    )
                else:
                    scan_result = process_data_collection_helper(
                        CLI_config=cli_config,
                        wf=workflow,
                        dc_id=unit[0],
                        mode="scan",
                        command_parameters={"sync_files": True} if sync_files else {},
                    )
                error = _scan_failure(scan_result)
            except Exception as exc:
                # The other collections are still scanned: a follower is
                # failed by its own scan, never by another one's. This one's
                # own exception is raised once they are, as it always was.
                error = f"Scan failed: {getattr(exc, 'detail', None) or exc}"
                if dc_id in unit:
                    own_exc = exc
                else:
                    logger.error(f"Scan of data collection(s) {', '.join(unit)} failed: {error}")
            if on_scanned is not None:
                for scanned_id in unit:
                    on_scanned(scanned_id, error)
            if dc_id in unit:
                own_error = error
        if own_exc is not None:
            raise own_exc
        if own_error is not None:
            return False, own_error

    process_result = process_data_collection_helper(
        CLI_config=cli_config,
        wf=workflow,
        dc_id=dc_id,
        mode="process",
        command_parameters={"overwrite": True},
    )
    if (process_result or {}).get("result") != "success":
        return False, f"Processing failed: {(process_result or {}).get('message', 'unknown error')}"
    return True, None


def _run_dc_ingest_or_fail(
    workflow_dict: dict,
    dc_id: str,
    tag: str,
    current_user,
    *,
    action: str,
    sync_files: bool = False,
    remote_storage_options: ProjectS3Config | None = None,
) -> tuple[bool, str | None]:
    """``_run_dc_ingest``, with a helper crash folded into a per-DC failure.

    An ``HTTPException`` still propagates: it answers the request, not one DC.
    ``action`` names the flow in the log line.
    """
    try:
        return _run_dc_ingest(
            workflow_dict,
            dc_id,
            current_user,
            sync_files=sync_files,
            remote_storage_options=remote_storage_options,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"{action} crashed for DC '{tag}': {exc}")
        return False, str(exc)


def _ingest_manifest_into_project(
    *,
    project_id: str,
    manifest_url: str,
    current_user,
    id_field: str = "id",
    url_field: str = "url",
    type_field: str = "type",
    run_field: str | None = "run",
    dry_run: bool = False,
) -> ManifestIngestReport:
    """Map a manifest onto an existing project's DC tags and ingest each match.

    Synchronous on purpose (sync httpx callbacks in the CLI helpers): callers
    must dispatch via ``asyncio.to_thread``.
    """
    # Gateway rejection must precede any database access.
    try:
        _validate_manifest_url(manifest_url)
    except RemoteURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    project_oid, project_dict = _load_editable_project(project_id, current_user)

    field_map = manifest_field_map(
        id_field=id_field, type_field=type_field, url_field=url_field, run_field=run_field
    )
    try:
        manifest = _fetch_and_parse_manifest(manifest_url, field_map)
    except ManifestEntriesRejected as exc:
        raise HTTPException(status_code=400, detail=exc.detail())
    except RemoteURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse manifest: {exc}")
    if not manifest.entries:
        raise HTTPException(status_code=422, detail="Manifest contains no entries.")

    live = _live_dc_index(project_dict)
    manifest_types = manifest.types()
    matched_tags = sorted(tag for tag in live if tag in manifest_types)
    if not matched_tags:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No manifest type matches a data collection tag. "
                f"Manifest types: {sorted(manifest_types)}; project tags: {sorted(live)}."
            ),
        )

    report = ManifestIngestReport(
        project_id=str(project_oid),
        manifest_url=manifest_url,
        manifest_entries=len(manifest.entries),
        unmatched_manifest_types=sorted(manifest_types - set(matched_tags)),
        unmatched_dc_tags=sorted(set(live) - set(matched_tags)),
        dry_run=dry_run,
    )

    # (tag, workflow index, DC dict, entries), the DC dicts inside a working
    # copy of the project's workflows. Each DC's scan config is written back
    # on its own (``_set_dc_scan``), never the whole array.
    workflows = copy.deepcopy(project_dict.get("workflows", []) or [])
    targets: list[tuple[str, int, dict, int]] = []
    for tag in matched_tags:
        wf_i, dc_i = live[tag]
        dc_dict = workflows[wf_i]["data_collections"][dc_i]
        targets.append((tag, wf_i, dc_dict, len(manifest.entries_for_type(tag))))

    if dry_run:
        report.matched = [
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=_dc_id(dc_dict),
                entries=entry_count,
                status="planned",
            )
            for tag, _wf_i, dc_dict, entry_count in targets
        ]
        report.success = True
        return report

    # ScanManifest is imported here with the rest of the model graph, to keep
    # API import-time cheap (same convention as the datacollections helpers).
    from depictio.models.models.data_collections import ScanManifest

    original_scans: dict[str, dict] = {}  # tag -> pre-ingest scan dict
    for tag, _wf_i, dc_dict, _entry_count in targets:
        scan_manifest = ScanManifest(
            manifest_url=manifest_url,
            manifest_type=tag,
            id_field=id_field,
            url_field=url_field,
            type_field=type_field,
            run_field=run_field,
        )
        original_scans[tag] = copy.deepcopy((dc_dict.get("config") or {}).get("scan"))
        dc_dict.setdefault("config", {})["scan"] = {
            "mode": "manifest",
            "scan_parameters": scan_manifest.model_dump(),
        }

    # Resolve the project's storage settings before touching the project
    # document: an unusable config (unreadable secret, endpoint no longer
    # allowed) must fail before any scan config is written, so there is
    # nothing to revert.
    from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
        project_storage_for,
    )

    remote_options = project_storage_for(project_oid)

    all_ok = True
    for tag, wf_i, dc_dict, entry_count in targets:
        dc_id = _dc_id(dc_dict)

        # Persist this DC's manifest scan config first: the helpers' API
        # callbacks read the DC config from the project document. Its File
        # records are snapshotted before the scan swaps them for the entries.
        files_before = _dc_files(dc_id)
        _set_dc_scan(project_oid, dc_dict.get("_id"), dc_dict["config"]["scan"])
        try:
            ok, message = _run_dc_ingest_or_fail(
                workflows[wf_i],
                dc_id,
                tag,
                current_user,
                action="Manifest ingest",
                remote_storage_options=remote_options,
            )
        except HTTPException:
            # Aborts the whole call (no API token, say). This DC's config is
            # already written, so revert it first; later DCs never were.
            _revert_dc_ingest(project_oid, dc_dict, original_scans.get(tag), files_before)
            raise
        if not ok:
            all_ok = False
            _revert_dc_ingest(project_oid, dc_dict, original_scans.get(tag), files_before)
        report.matched.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=dc_id,
                entries=entry_count,
                status="ingested" if ok else "failed",
                message=message,
            )
        )

    report.success = all_ok
    return report


# Scan modes whose source this process reads over the network, through the
# fetch gateway or the S3 target resolution, which decide for the user asking.
_REMOTE_SCAN_MODES = frozenset({"manifest", "url", "s3_prefix"})


def _server_can_reread(workflow: dict, mode: str, scan_params: dict) -> bool:
    """Whether this process may scan the data collection's source again.

    A remote source qualifies. A local path stored on a project is its owner's
    word, and this process can read far more of its own disk than any user may
    (its keys, its environment), so it never re-reads one on a user's behalf,
    even when the path exists here: a project ingested from a local folder is
    refreshed by the CLI that ingested it. The one exception is a server that
    is the user's own computer (``depictio local``): there a local source
    qualifies when the active local-data policy lets this server read it and
    it is still on disk, as at creation.

    ``mode == ""`` is a ``source: transformed`` recipe collection: it has no
    scan block of its own, so there is no per-DC location to check. Its
    inputs are read from the *workflow's* data root at process time (see
    ``_run_dc_ingest``), so it qualifies when every location of that root is
    an ``s3://`` prefix, which the recipe layer reads through the S3 target
    resolution, or a folder the local-data policy allows.
    """
    if mode in _REMOTE_SCAN_MODES:
        return True
    locations = [str(loc) for loc in (workflow.get("data_location") or {}).get("locations") or []]
    if mode == "single":
        filename = str(scan_params.get("filename") or "")
        return _policy_reads(filename) and os.path.isfile(filename)
    if mode == "recursive":
        return (
            bool(locations)
            and all(_policy_reads(location) for location in locations)
            and any(os.path.isdir(location) for location in locations)
        )
    if mode == "":
        return bool(locations) and all(
            location[:5].lower() == "s3://" or _policy_reads(location) for location in locations
        )
    return False


def _policy_reads(path: str) -> bool:
    """Whether ``path`` lies under a root of the active local-data policy.

    The roots only, as at creation (``LocalDataPolicy.confine``): the server's
    own folders (its temporary directory, the bundled projects) are read for
    the request that wrote them, never re-read from a path stored on a
    project. False when local folders are off, which they are everywhere but
    on a single-user ``depictio local`` server with roots configured.
    """
    from depictio.api.v1.configs.settings_models import local_data_policy

    policy = local_data_policy()
    return policy is not None and bool(path) and policy.allows(path)


def _refreshable_dc_index(project_dict: dict) -> dict[str, tuple[int, int, dict, str]]:
    """Every data collection this process can scan again, as
    ``{dc_tag: (workflow_index, dc_index, scan_parameters, mode)}``.

    Re-ingestion is scan-mode agnostic: ``_run_dc_ingest`` parses the workflow
    and calls scan then process, exactly as the CLI would. Manifest mode was
    only ever special in the *selection*, so widening it here turns the refresh
    button into a browser-triggered re-run for a project the CLI created, which
    is the whole point of having one.
    """
    index: dict[str, tuple[int, int, dict, str]] = {}
    for wf_i, wf in enumerate(project_dict.get("workflows", []) or []):
        for dc_i, dc in enumerate(wf.get("data_collections", []) or []):
            tag = dc.get("data_collection_tag")
            if not tag or tag in index:
                continue
            scan = (dc.get("config") or {}).get("scan") or {}
            mode = str(scan.get("mode", "")).lower()
            scan_params = scan.get("scan_parameters") or {}
            if _server_can_reread(wf, mode, scan_params):
                index[tag] = (wf_i, dc_i, scan_params, mode)
    return index


def _manifest_preflight_entries(
    tag: str, scan_params: dict, manifests: dict[tuple, DataManifest | str]
) -> int | str:
    """Entries a manifest DC would re-ingest, or the message saying why it must
    be skipped (same "value or error text" shape as the ``manifests`` cache).

    Manifest mode is the one mode whose source can be checked before running:
    the manifest is a document this process can fetch and count. That check is
    worth keeping because a manifest that fetches fine but has lost the DC's
    type would otherwise empty the collection silently.

    ``manifests`` caches by (url, field map) across DCs, so several collections
    backed by the same manifest fetch it once, and one dead manifest fails only
    the collections that use it.
    """
    manifest_url = str(scan_params.get("manifest_url") or "")
    field_map = _manifest_field_map(scan_params)

    key = (manifest_url, tuple(sorted(field_map.items())))
    if key not in manifests:
        try:
            # The stored URL may predate the gateway or come from a CLI
            # ingest of a local manifest path: re-validate before fetching.
            _validate_manifest_url(manifest_url)
            manifests[key] = _fetch_and_parse_manifest(manifest_url, field_map)
        except ManifestEntriesRejected as exc:
            # Fetched fine, but an entry points somewhere the worker must
            # not read: a per-DC failure like any other, before dispatch.
            manifests[key] = str(exc)
        except (RemoteURLRejected, ValueError) as exc:
            manifests[key] = f"Could not fetch manifest: {exc}"

    manifest = manifests[key]
    if isinstance(manifest, str):
        return manifest

    manifest_type = _manifest_type_of(scan_params, tag)
    entry_count = len(manifest.entries_for_type(manifest_type))
    if entry_count == 0:
        return (
            f"Manifest has no entries of type '{manifest_type}': "
            "refresh skipped to avoid emptying the data collection."
        )
    return entry_count


def _refresh_manifest_in_project(
    *,
    project_id: str,
    current_user,
    data_collection_tag: str | None = None,
    dry_run: bool = False,
    async_run: bool = False,
) -> ManifestRefreshReport:
    """Re-run each refreshable DC's stored scan and re-ingest it in place.

    Refresh semantics are overwrite-with-report (RFC open question 2): the scan
    prunes File records for entries that vanished from the source, ``sync_files``
    forces metadata updates for kept entries, and the Delta table is rebuilt
    from the resulting file set. The scan configs are already persisted on the
    project, so (unlike first ingestion) nothing is written to the project
    document and no revert bookkeeping is needed. A manifest that no longer has
    any row of a DC's type marks that DC failed *without* running the scan, so
    a refresh never silently empties a data collection.

    A project made from a run folder (``template_origin.data_root``) gets the
    pre-flight its creation had, taken again against that folder
    (``from_run._refresh_preflight``), so the same folder gets the same
    verdicts: an optional collection whose source is absent is skipped, a
    required one that only misses such collections is skipped, a required one
    missing a source of its own fails, and none of them is dispatched, so a
    collection ingested before keeps its table as it was. Decided over the
    whole project, then narrowed to ``data_collection_tag``, so refreshing one
    collection answers what refreshing all of them would for it. A
    manifest-driven project has no data root, so only its manifest pre-flight
    runs, as before.

    In ``async_run`` mode those pre-flight verdicts are also seeded into the
    ingestion-run document as failed or skipped steps, so a caller that only
    polls ``GET /projects/refresh_manifest/{run_id}`` sees them and the run
    can never close as "success" around a DC that failed pre-flight.

    Synchronous on purpose (sync httpx callbacks in the CLI helpers): callers
    must dispatch via ``asyncio.to_thread``.
    """
    project_oid, project_dict = _load_editable_project(project_id, current_user)

    refreshable_index = _refreshable_dc_index(project_dict)
    if not refreshable_index:
        raise HTTPException(
            status_code=422,
            detail=(
                "Project has no data collections this server can re-read. Remote "
                "sources (a manifest, a URL, an s3:// prefix) can be refreshed here; "
                "data ingested from a local folder is refreshed with the CLI."
            ),
        )
    if data_collection_tag is not None:
        if data_collection_tag not in refreshable_index:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"'{data_collection_tag}' is not a data collection this server can "
                    f"re-read. Refreshable in this project: {sorted(refreshable_index)}."
                ),
            )
        refreshable_index = {data_collection_tag: refreshable_index[data_collection_tag]}

    report = ManifestRefreshReport(project_id=str(project_oid), dry_run=dry_run)
    workflows = project_dict.get("workflows", []) or []

    # The project's storage settings, resolved once; async workers re-resolve
    # for themselves so no secret ever crosses the broker.
    remote_options: ProjectS3Config | None = None
    if not dry_run and not async_run:
        from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
            project_storage_for,
        )

        remote_options = project_storage_for(project_oid)

    # The run folder's own verdicts, before anything is dispatched: an
    # S3AccessError here is the read every worker would have failed on.
    from depictio.api.v1.endpoints.projects_endpoints.from_run import _refresh_preflight

    folder_preflight = _refresh_preflight(project_dict)
    data_root: str | None = None
    folder_failed: dict[str, str] = {}
    folder_skipped: dict[str, str] = {}
    folder_matched: dict[str, int] = {}
    if folder_preflight is not None:
        data_root, split = folder_preflight
        folder_failed = {tag: message for tag, _dc_id, message in split.failed}
        folder_skipped = {tag: message for tag, _dc_id, message in split.skipped}
        folder_matched = {tag: matched for tag, _dc_id, _wf_i, matched in split.to_dispatch}

    # Each DC carries its own manifest URL + field map; fetch each distinct
    # combination once. Failures are per-DC, not global: one dead manifest
    # must not block refreshing DCs backed by a different one.
    manifests: dict[tuple, DataManifest | str] = {}  # key -> manifest or error text
    to_dispatch: list[tuple[str, str, int, int]] = []  # (tag, dc_id, wf_i, entries)
    preflight_failed: list[tuple[str, str, str]] = []  # (tag, dc_id, message), async only
    preflight_skipped: list[tuple[str, str, str]] = []  # same, async only
    all_ok = True

    def _fail_preflight(tag: str, dc_id: str, message: str) -> None:
        nonlocal all_ok
        all_ok = False
        report.refreshed.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=dc_id,
                entries=0,
                status="failed",
                message=message,
            )
        )
        if async_run and not dry_run:
            preflight_failed.append((tag, dc_id, message))

    def _skip_preflight(tag: str, dc_id: str, message: str) -> None:
        # A skip leaves the refresh successful. In async mode the dispatch
        # seeds its step and reports it back, so it is reported here otherwise.
        if async_run and not dry_run:
            preflight_skipped.append((tag, dc_id, message))
            return
        report.refreshed.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=dc_id,
                entries=0,
                status="skipped",
                message=message,
            )
        )

    for tag, (wf_i, dc_i, scan_params, mode) in refreshable_index.items():
        dc_id = _dc_id(workflows[wf_i]["data_collections"][dc_i])

        # A manifest DC is checked against its manifest, every other one
        # against the run folder when the project has one. Without either, a
        # mode discovers its own files during the scan, with no entry count to
        # report before running.
        entry_count = 0
        if mode == "manifest":
            preflight = _manifest_preflight_entries(tag, scan_params, manifests)
            if isinstance(preflight, str):
                _fail_preflight(tag, dc_id, preflight)
                continue
            entry_count = preflight
        elif tag in folder_failed:
            _fail_preflight(tag, dc_id, folder_failed[tag])
            continue
        elif tag in folder_skipped:
            _skip_preflight(tag, dc_id, folder_skipped[tag])
            continue
        else:
            entry_count = folder_matched.get(tag, 0)

        if dry_run:
            report.refreshed.append(
                ManifestIngestDCResult(
                    data_collection_tag=tag,
                    data_collection_id=dc_id,
                    entries=entry_count,
                    status="planned",
                )
            )
            continue

        if async_run:
            to_dispatch.append((tag, dc_id, wf_i, entry_count))
            continue

        ok, message = _run_dc_ingest_or_fail(
            workflows[wf_i],
            dc_id,
            tag,
            current_user,
            action="Refresh",
            sync_files=True,
            remote_storage_options=remote_options,
        )
        if not ok:
            all_ok = False
        report.refreshed.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=dc_id,
                entries=entry_count,
                status="ingested" if ok else "failed",
                message=message,
            )
        )

    # These lists are only ever filled in async (non-dry) mode. A run document
    # is created even when no DC got past pre-flight, so the caller always
    # gets a run_id and the poll endpoint shows why.
    if to_dispatch or preflight_failed or preflight_skipped:
        # The run's own record of each DC's mode: "recipe" for the one
        # scan-less mode ("") the dispatcher would otherwise default to
        # "manifest" for, same label from_run.py already uses.
        scan_modes = {
            tag: mode or "recipe"
            for tag, (_wf_i, _dc_i, _params, mode) in refreshable_index.items()
        }
        run_id, dispatch_ok, dispatched = _dispatch_refresh_tasks(
            project_dict=project_dict,
            to_dispatch=to_dispatch,
            current_user=current_user,
            preflight_failed=preflight_failed,
            preflight_skipped=preflight_skipped,
            scan_modes=scan_modes,
            data_root=data_root,
        )
        report.run_id = run_id
        report.refreshed.extend(dispatched)
        all_ok = all_ok and dispatch_ok

    report.success = all_ok
    return report


def _recipe_dependencies(project_dict: dict) -> dict[str, list[str]]:
    """{dc_tag: [dc_ref, ...]} for every recipe-backed (``source: transformed``) DC.

    A recipe's ``SOURCES`` may read another collection's Delta table by tag
    (``RecipeSource.dc_ref``, see ``deltatables.py``'s recipe path): a required
    ref that isn't written yet fails the step, an optional one silently runs
    without it. ``_dispatch_refresh_tasks`` uses this to make a dependent DC's
    task wait for its dc_ref's step to go terminal first: see
    ``manifest_refresh_dc_task``.

    A recipe that fails to load is not this function's problem to raise on:
    the DC's own ingestion hits the same failure and reports it as *its*
    error, so a load failure here just means "no known dependencies", not
    "block dispatch".
    """
    from depictio.recipes import load_recipe

    dependencies: dict[str, list[str]] = {}
    for workflow in project_dict.get("workflows", []) or []:
        for dc in workflow.get("data_collections", []) or []:
            tag = dc.get("data_collection_tag")
            if not tag:
                continue
            config = dc.get("config") or {}
            if str(config.get("source") or "") != "transformed":
                continue
            recipe = (config.get("transform") or {}).get("recipe")
            if not recipe:
                continue
            try:
                module = load_recipe(recipe)
            except Exception as exc:
                logger.warning(f"Could not load recipe '{recipe}' for DC '{tag}': {exc}")
                continue
            refs: list[str] = []
            for source in getattr(module, "SOURCES", []):
                ref = getattr(source, "dc_ref", None)
                if ref and ref not in refs:
                    refs.append(ref)
            dependencies[tag] = refs
    return dependencies


def _scan_leaders(
    project_dict: dict, to_dispatch: list[tuple[str, str, int, int]]
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Who scans for the run-registering collections of each workflow in a fan-out.

    Those are the collections whose scan writes the workflow's ``WorkflowRun``
    documents (``_registers_runs``): the recursive ones, whose walk of the run
    folders registers one run per folder, and the ``s3_prefix`` ones of a
    ``sequencing-runs`` workflow, which register one per run directory under
    the prefix. Every one of them shares the workflow's runs. One task per
    collection, each scanning for itself, would race to create the same runs
    (two documents for one run, or files naming a run that is never written).
    So the first of them to be dispatched is the scan leader and scans for all
    of them, one after the other; the others wait for its step
    (``depends_on``) and only process.

    Returns ``({leader_tag: [dc_id, ...]}, {follower_tag: leader_tag})``.
    """
    workflows = project_dict.get("workflows") or []
    members: dict[int, list[tuple[str, str]]] = {}
    for tag, dc_id, wf_i, _entries in to_dispatch:
        workflow = workflows[wf_i] if wf_i < len(workflows) else {}
        dc = next((d for d in workflow.get("data_collections") or [] if _dc_id(d) == dc_id), {})
        if _registers_runs(workflow, dc):
            members.setdefault(wf_i, []).append((tag, dc_id))

    leaders: dict[str, list[str]] = {}
    followers: dict[str, str] = {}
    for group in members.values():
        leader_tag = group[0][0]
        leaders[leader_tag] = [dc_id for _tag, dc_id in group]
        followers.update({tag: leader_tag for tag, _dc_id in group[1:]})
    return leaders, followers


def _not_built_detail(refs: list[str], absent: set[str]) -> str:
    """Why a collection whose own inputs are there is skipped: what it reads is not."""

    def _clause(tags: list[str], adjective: str, state: str) -> str:
        names = ", ".join(f"'{tag}'" for tag in tags)
        noun, verb = ("collections", "are") if len(tags) > 1 else ("collection", "is")
        return f"the {adjective}{noun} {names} it reads {verb} {state}"

    optional = [ref for ref in refs if ref in absent]
    unbuilt = [ref for ref in refs if ref not in absent]
    clauses = []
    if optional:
        clauses.append(_clause(optional, "optional ", "absent from this run"))
    if unbuilt:
        clauses.append(_clause(unbuilt, "", "not built in this run either"))
    return f"Not built: {', and '.join(clauses)}."


def _skip_dependants_of_absent_collections(
    preflight_failed: list[tuple[str, str, str]],
    preflight_skipped: list[tuple[str, str, str]],
    missing_collections: dict[str, list[str]],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Move to the skipped steps a pre-flight failure that only reads skipped collections.

    A required collection whose own files are all there, but which reads
    (``dc_ref``) an optional collection this run skips, cannot be built for that
    reason alone: the absence is nominal, so it is skipped, saying which
    collection it is missing, rather than failed. One that misses a file of its
    own, or reads a collection that failed, stays failed. Repeated until nothing
    moves, so a chain built on one absent collection is skipped whole.

    Decided from structure, never from a message: ``missing_collections`` maps
    the tag of a failure that misses other collections and nothing else to
    their tags (from the preview's ``missing_collections``), and the absent
    collections are the tags of ``preflight_skipped``. A failure it does not
    name stays failed, whatever its detail says.

    Returns ``(preflight_failed, preflight_skipped)`` with those entries moved.
    """
    failed = list(preflight_failed)
    skipped = list(preflight_skipped)
    absent = {tag for tag, _dc_id, _message in skipped}
    unbuilt: set[str] = set()
    moved = True
    while moved:
        moved = False
        for entry in list(failed):
            tag, dc_id, _message = entry
            refs = missing_collections.get(tag) or []
            if not refs or any(ref not in absent and ref not in unbuilt for ref in refs):
                continue
            failed.remove(entry)
            skipped.append((tag, dc_id, _not_built_detail(refs, absent)))
            unbuilt.add(tag)
            moved = True
    return failed, skipped


def _dispatch_refresh_tasks(
    *,
    project_dict: dict,
    to_dispatch: list[tuple[str, str, int, int]],
    current_user,
    preflight_failed: list[tuple[str, str, str]],
    preflight_skipped: list[tuple[str, str, str]] | None = None,
    command: str = "refresh_manifest",
    scan_modes: dict[str, str] | None = None,
    data_root: str | None = None,
) -> tuple[str, bool, list[ManifestIngestDCResult]]:
    """Fan the per-DC ingestions out to Celery, backed by an ingestion run.

    Steps are pre-seeded (one per DC tag, status "pending") so the workers'
    ``set_ingestion_step`` positional updates are atomic under concurrency.
    Poll ``GET /projects/refresh_manifest/{run_id}`` for the aggregate report:
    Mongo is the durable status of record; Celery is only the transport.

    ``preflight_failed`` DCs (manifest unfetchable, entry rejected, type
    dropped from the manifest, a source absent from the data root) never reach
    a worker but are seeded as already-failed steps with ``file_count=0``: the
    finalizer computes the run status from the seeded steps, so leaving them
    out would let the run close as "success" with the skipped DC silently
    absent from the poll report. ``preflight_skipped`` is the same idea for a
    collection whose absence is nominal (an optional template collection this
    run folder never produces, or one that only reads such a collection: see
    ``from_run._preflight_split``, which decides both lists for a run
    folder), seeded "skipped" rather than "failed" so the run can still close
    "success" around it (see ``_finalize_manifest_refresh_run``). It defaults
    to empty, so a manifest refresh, which never has one, is unaffected.

    A recipe DC's payload carries ``depends_on`` (see ``_recipe_dependencies``)
    for every dc_ref that still has a step *in this run* (``seeded_tags``
    below), and ``manifest_refresh_dc_task`` waits for those steps to go
    terminal before it actually ingests. Waiting on direct dependencies only
    is enough: a dependency's own dependencies already had to go terminal
    before it could, so by the time a step stops being pending/running,
    everything upstream of it has already settled. A dependency cycle (there
    are none in the catalog today) would simply hold every step in it pending
    until each one's wait budget in ``manifest_refresh_dc_task`` runs out, and
    each would then fail naming what it was still waiting for.

    The collections of one workflow that register its runs get a scan leader
    (see ``_scan_leaders``): its payload carries ``scan_dc_ids``, the
    collections it scans for, and each of the others ``scan_leader``, its tag,
    which is also added to ``depends_on``.

    Shared with ``POST /projects/from_run``, which needs exactly this: a
    durable run whose steps a worker updates and a caller polls. The two flows
    differ only in bookkeeping, which is what the keyword arguments carry:
    ``command`` labels the run (and is what ``_get_refresh_run_report`` accepts),
    ``scan_modes`` records each DC's real mode instead of assuming "manifest",
    and ``data_root`` notes the run folder a from_run, or a refresh of its
    project, read from. Their defaults are the manifest refresh's own values.

    Returns ``(run_id, all_dispatched, results)``; the caller owns its report
    shape and attaches these itself.
    """
    from uuid import uuid4

    from depictio.api.v1.monitoring import store
    from depictio.models.models.monitoring import (
        IngestionDataCollection,
        IngestionRun,
        IngestionStep,
    )

    skipped = preflight_skipped or []
    modes = scan_modes or {}
    run_id = uuid4().hex
    # One step per DC, as (tag, step status, step detail, file count):
    # pre-flight failures first, then pre-flight skips, then the DCs a worker
    # will actually run.
    seeds: list[tuple[str, str, str | None, int]] = (
        [(tag, "failed", message, 0) for tag, _dc_id, message in preflight_failed]
        + [(tag, "skipped", message, 0) for tag, _dc_id, message in skipped]
        + [(tag, "pending", None, entries) for tag, _dc_id, _wf_i, entries in to_dispatch]
    )
    data_collections = [
        IngestionDataCollection(tag=tag, scan_mode=modes.get(tag, "manifest"), file_count=count)
        for tag, _status, _detail, count in seeds
    ]
    steps = [
        IngestionStep(name=tag, status=status, detail=detail)
        for tag, status, detail, _count in seeds
    ]
    store.create_ingestion_run(
        IngestionRun(
            run_id=run_id,
            source="ui",
            cli_instance_label="Web UI",
            user_id=str(current_user.id),
            email=getattr(current_user, "email", None),
            project_id=str(project_dict["_id"]),
            project_name=project_dict.get("name"),
            command=command,
            data_root=data_root,
            data_collections=data_collections,
            status="running",
            steps=steps,
        )
    )

    # Task import is lazy: the API process only needs the signature, and tests
    # patch the dispatch without a broker.
    from depictio.api.v1.celery_tasks import manifest_refresh_dc_task

    # Every tag that has a step in this run: a dependency pruned at
    # resolution, or simply not part of this run, is not waited for.
    seeded_tags = {tag for tag, _status, _detail, _count in seeds}
    dependencies = _recipe_dependencies(project_dict)
    scan_leaders, scan_followers = _scan_leaders(project_dict, to_dispatch)

    user_ctx = {
        "id": str(current_user.id),
        "email": getattr(current_user, "email", None),
        "is_admin": bool(getattr(current_user, "is_admin", False)),
    }
    results: list[ManifestIngestDCResult] = [
        ManifestIngestDCResult(
            data_collection_tag=tag,
            data_collection_id=dc_id,
            entries=0,
            status="skipped",
            message=message,
        )
        for tag, dc_id, message in skipped
    ]
    all_dispatched = True
    for tag, dc_id, wf_i, entries in to_dispatch:
        payload = {
            "run_id": run_id,
            "project_id": str(project_dict["_id"]),
            "wf_index": wf_i,
            "dc_id": dc_id,
            "dc_tag": tag,
            "sync_files": True,
            "user": user_ctx,
        }
        deps = [dep for dep in dependencies.get(tag, []) if dep in seeded_tags]
        if tag in scan_leaders:
            payload["scan_dc_ids"] = scan_leaders[tag]
        if tag in scan_followers:
            payload["scan_leader"] = scan_followers[tag]
            if scan_followers[tag] not in deps:
                deps.append(scan_followers[tag])
        if deps:
            payload["depends_on"] = deps
        try:
            manifest_refresh_dc_task.apply_async(args=[payload])
            status, message = "dispatched", None
        except Exception as exc:  # broker down: a per-DC failure, not a 5xx
            logger.error(f"Could not dispatch ingestion for DC '{tag}': {exc}")
            all_dispatched = False
            status, message = "failed", f"Could not dispatch worker task: {exc}"
            store.set_ingestion_step(
                run_id,
                step={"name": tag, "status": "failed", "detail": message},
                current_step=None,
            )
        results.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=dc_id,
                entries=entries,
                status=status,
                message=message,
            )
        )
    if not all_dispatched or not to_dispatch:
        # With nothing dispatched (every DC failed pre-flight, or the broker
        # refused them all) no worker will ever finalize the run: close it
        # now (no-op while any step is still pending/running).
        from depictio.api.v1.celery_tasks import _finalize_manifest_refresh_run

        _finalize_manifest_refresh_run(run_id)
    return run_id, all_dispatched, results


# Every command whose run document this poll route serves. Both flows write the
# run with the same shape (pre-seeded steps a worker updates), so one route
# answers for both; a run from any other command (a CLI ``run``, a UI upload)
# belongs to another report and is not found here.
_POLLABLE_RUN_COMMANDS = frozenset({"refresh_manifest", "from_run"})

_REFRESH_STEP_TO_DC_STATUS = {
    "pending": "dispatched",
    "running": "running",
    "success": "ingested",
    "failed": "failed",
    "skipped": "skipped",
}


def _get_refresh_run_report(run_id: str, current_user) -> ManifestRefreshReport:
    """Aggregate an async ingestion run into the same report shape as sync mode.

    Serves both the async manifest refresh and the background ingestion a
    ``POST /projects/from_run`` opens (see ``_POLLABLE_RUN_COMMANDS``).
    """
    from depictio.api.v1.monitoring import store

    doc = store.get_ingestion_run(run_id)
    if not doc or doc.get("command") not in _POLLABLE_RUN_COMMANDS:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    if not getattr(current_user, "is_admin", False) and doc.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="This refresh run belongs to another user.")

    entries_by_tag = {
        dc.get("tag"): dc.get("file_count") or 0 for dc in doc.get("data_collections") or []
    }
    # dc ids aren't stored on the run: rebuild the mapping from the live
    # project (empty if the project has been deleted since).
    dc_ids_by_tag: dict[str, str] = {}
    project_dict = (
        projects_collection.find_one({"_id": ObjectId(doc["project_id"])})
        if doc.get("project_id")
        else None
    )
    if project_dict:
        # Every collection, not just the currently refreshable ones: this
        # reports a run that already happened, and a source that has become
        # unreadable since (an unmounted data root) must not lose its id in the
        # report of the run that refreshed it.
        workflows = project_dict.get("workflows") or []
        dc_ids_by_tag = {
            tag: _dc_id(workflows[wf_i]["data_collections"][dc_i])
            for tag, (wf_i, dc_i) in _live_dc_index(project_dict).items()
        }

    report = ManifestRefreshReport(project_id=str(doc.get("project_id") or ""), run_id=run_id)
    for step in doc.get("steps") or []:
        tag = str(step.get("name") or "")
        report.refreshed.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=dc_ids_by_tag.get(tag, ""),
                entries=entries_by_tag.get(tag, 0),
                status=_REFRESH_STEP_TO_DC_STATUS.get(str(step.get("status")), "failed"),
                message=step.get("detail"),
            )
        )
    report.success = doc.get("status") == "success"
    return report
