"""Server-side manifest ingestion into an existing project (RFC remote-data, phase 2).

``POST /projects/ingest_manifest`` maps a Data Manifest's ``type`` values onto
the project's data-collection tags, switches each matched DC to
``scan.mode: manifest``, and runs scan + process in-process through the same
CLI helpers as the create-DC flows. The result is a per-DC ingestion report.

Sequencing per DC (mirrors ``_push_workflow_and_ingest``): the new scan config
is persisted *before* the helpers run — the helpers' API callbacks read the DC
from the project document — and reverted for any DC whose scan or process
fails, so a failed ingestion never leaves a manifest scan config pointing at
data that was never materialized.

Fan-out is sequential for now; Celery parallelism is a phase-4 concern
(the report shape is already per-DC so the switch is internal).
"""

import copy
import os
import tempfile
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.db import projects_collection
from depictio.api.v1.remote_fetch import (
    RemoteURLRejected,
    bounded_download,
    validate_remote_url,
)
from depictio.models.logging import logger
from depictio.models.models.manifest import DataManifest

# Manifests are indexes, not data — cap them well below the data-file cap.
MANIFEST_MAX_BYTES = 50 * 1024 * 1024

# Rejected entries listed in a 400 body (the summary string names at most 5).
MAX_REJECTED_ENTRIES_LISTED = 20


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
    status: str  # "ingested" | "failed" | "planned" (dry_run)
    message: str | None = None


class RefreshManifestRequest(BaseModel):
    """Body of POST /projects/refresh_manifest."""

    project_id: str
    # Restrict the refresh to one DC tag; None refreshes every manifest DC.
    data_collection_tag: str | None = None
    # Plan-only: report what would be refreshed without touching any data.
    dry_run: bool = False
    # Fan the per-DC re-ingestions out to Celery workers instead of running
    # them inline — for long manifests. The response then reports each DC as
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
    # Manifest types with no matching DC tag — data the project can't hold yet.
    unmatched_manifest_types: list[str] = Field(default_factory=list)
    # Project DC tags the manifest says nothing about — left untouched.
    unmatched_dc_tags: list[str] = Field(default_factory=list)
    dry_run: bool = False
    success: bool = False


def _fetch_and_parse_manifest(manifest_url: str, field_map: dict[str, str]) -> DataManifest:
    """Download the manifest through the SSRF gateway and parse it.

    Server context only accepts remote manifests (https; s3 is tracked in the
    RFC) — local paths are a CLI affordance. Format is decided by extension
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

    stripped = text.lstrip()
    looks_json = manifest_url.split("?", 1)[0].endswith(".json") or stripped.startswith(("{", "["))
    if looks_json:
        manifest = DataManifest.from_json(text, source=manifest_url, field_map=field_map)
    else:
        manifest = DataManifest.from_csv(text, source=manifest_url, field_map=field_map)
    _reject_unsafe_entry_urls(manifest)
    return manifest


def _live_dc_index(project_dict: dict) -> dict[str, tuple[int, int]]:
    """{dc_tag: (workflow_index, dc_index)} across all of the project's workflows."""
    index: dict[str, tuple[int, int]] = {}
    for wf_i, wf in enumerate(project_dict.get("workflows", []) or []):
        for dc_i, dc in enumerate(wf.get("data_collections", []) or []):
            tag = dc.get("data_collection_tag")
            if tag and tag not in index:
                index[tag] = (wf_i, dc_i)
    return index


def _run_dc_ingest(
    workflow_dict: dict,
    dc_id: str,
    current_user,
    sync_files: bool = False,
    remote_storage_options: dict | None = None,
) -> tuple[bool, str | None]:
    """Scan + process one DC through the CLI helpers. Returns (ok, error_message).

    Synchronous on purpose — the helpers use a sync httpx client back into
    this same FastAPI process (see ``_push_workflow_and_ingest``).

    ``sync_files=True`` forces File-record updates during the scan. The scan's
    change detection keys on ``sha256(url|id)`` — an *identity* hash — so a
    refresh over a manifest whose URLs are unchanged but whose remote content
    moved would otherwise skip the File metadata update.

    A data collection with no scan block at all (a ``source: transformed``
    recipe collection) is processed without being scanned: it registers no
    files, its inputs are read from the workflow's data root by the recipe
    layer at process time, and the per-DC scan only speaks
    single/url/s3_prefix/manifest so it would raise on one. Unreachable from
    the refresh flow — ``_refreshable_dc_index`` never selects a collection
    without a scan mode — and from the manifest flows, which only ever pass
    manifest-mode collections; it is the from_run fan-out that needs it.
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

    target = next((dc for dc in workflow.data_collections if str(dc.id) == dc_id), None)
    if target is None or target.config.scan is not None:
        scan_result = process_data_collection_helper(
            CLI_config=cli_config,
            wf=workflow,
            dc_id=dc_id,
            mode="scan",
            command_parameters={"sync_files": True} if sync_files else {},
        )
        if (scan_result or {}).get("result") != "success":
            return False, f"Scan failed: {(scan_result or {}).get('message', 'unknown error')}"

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

    Synchronous on purpose (sync httpx callbacks in the CLI helpers) — callers
    must dispatch via ``asyncio.to_thread``.
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _user_can_edit_project,
    )

    # Gateway rejection must precede any database access.
    try:
        validate_remote_url(manifest_url)
    except RemoteURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if manifest_url.startswith("s3://"):
        raise HTTPException(
            status_code=400,
            detail="s3:// manifest locations are not supported yet — serve the manifest over https.",
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

    field_map = {"id": id_field, "type": type_field, "url": url_field}
    if run_field:
        field_map["run"] = run_field
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

    # ScanManifest is imported here with the rest of the model graph — keep
    # API import-time cheap, same convention as the datacollections helpers.
    from depictio.models.models.data_collections import ScanManifest

    workflows = copy.deepcopy(project_dict.get("workflows", []) or [])
    original_scans: dict[str, dict] = {}  # tag -> pre-ingest scan dict
    for tag in matched_tags:
        wf_i, dc_i = live[tag]
        dc_dict = workflows[wf_i]["data_collections"][dc_i]
        entry_count = len(manifest.entries_for_type(tag))

        if dry_run:
            report.matched.append(
                ManifestIngestDCResult(
                    data_collection_tag=tag,
                    data_collection_id=str(dc_dict.get("_id") or dc_dict.get("id") or ""),
                    entries=entry_count,
                    status="planned",
                )
            )
            continue

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

    if dry_run:
        report.success = True
        return report

    # Resolve the project's storage credentials before touching the project
    # document: an unusable config (unreadable secret, endpoint no longer
    # allowed) must fail before any scan config is written, so there is
    # nothing to revert.
    from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
        storage_options_for_project,
    )

    remote_options = storage_options_for_project(project_oid)

    # Persist the manifest scan configs first — the helpers' API callbacks
    # read the DC config from the project document.
    projects_collection.update_one({"_id": project_oid}, {"$set": {"workflows": workflows}})

    all_ok = True
    for tag in matched_tags:
        wf_i, dc_i = live[tag]
        dc_dict = workflows[wf_i]["data_collections"][dc_i]
        dc_id = str(dc_dict.get("_id") or dc_dict.get("id") or "")
        entry_count = len(manifest.entries_for_type(tag))
        try:
            ok, message = _run_dc_ingest(
                workflows[wf_i], dc_id, current_user, remote_storage_options=remote_options
            )
        except HTTPException:
            raise
        except Exception as exc:  # helper crash — treat as a per-DC failure
            logger.error(f"Manifest ingest crashed for DC '{tag}': {exc}")
            ok, message = False, str(exc)
        if not ok:
            all_ok = False
            # Revert this DC to its pre-ingest scan config so a failed run
            # never leaves a manifest config with no data behind it.
            dc_dict["config"]["scan"] = original_scans.get(tag)
        report.matched.append(
            ManifestIngestDCResult(
                data_collection_tag=tag,
                data_collection_id=dc_id,
                entries=entry_count,
                status="ingested" if ok else "failed",
                message=message,
            )
        )

    if not all_ok:
        projects_collection.update_one({"_id": project_oid}, {"$set": {"workflows": workflows}})

    report.success = all_ok
    return report


# Scan modes whose source this process reads over the network, so it can always
# read it again. The local modes depend on whether the data root happens to be
# visible from this container, which is checked per data collection.
_REMOTE_SCAN_MODES = frozenset({"manifest", "url", "s3_prefix"})


def _server_can_reread(workflow: dict, mode: str, scan_params: dict) -> bool:
    """Whether this process could scan the data collection's source again.

    A remote source always qualifies. A local one only if the path is visible
    from *this* container: a CLI-created project normally points at the user's
    own filesystem, which the API has never seen, and offering a refresh button
    for it would only produce a scan failure with an unhelpful message.
    """
    if mode in _REMOTE_SCAN_MODES:
        return True
    if mode == "single":
        return os.path.isfile(str(scan_params.get("filename") or ""))
    if mode == "recursive":
        locations = (workflow.get("data_location") or {}).get("locations") or []
        return any(os.path.isdir(str(location)) for location in locations)
    return False


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
    field_map = {
        "id": scan_params.get("id_field") or "id",
        "type": scan_params.get("type_field") or "type",
        "url": scan_params.get("url_field") or "url",
    }
    run_field = scan_params.get("run_field")
    if run_field:
        field_map["run"] = run_field

    key = (manifest_url, tuple(sorted(field_map.items())))
    if key not in manifests:
        try:
            # The stored URL may predate the gateway or come from a CLI
            # ingest of a local manifest path — re-validate before fetching.
            validate_remote_url(manifest_url)
            if manifest_url.startswith("s3://"):
                raise RemoteURLRejected(
                    "s3:// manifest locations are not supported yet — "
                    "serve the manifest over https."
                )
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

    manifest_type = str(scan_params.get("manifest_type") or tag)
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
    project, so — unlike first ingestion — nothing is written to the project
    document and no revert bookkeeping is needed. A manifest that no longer has
    any row of a DC's type marks that DC failed *without* running the scan, so
    a refresh never silently empties a data collection.

    In ``async_run`` mode those pre-flight failures are also seeded into the
    ingestion-run document as failed steps, so a caller that only polls
    ``GET /projects/refresh_manifest/{run_id}`` sees them and the run can
    never close as "success" around a DC that was skipped.

    Synchronous on purpose (sync httpx callbacks in the CLI helpers) — callers
    must dispatch via ``asyncio.to_thread``.
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

    refreshable_index = _refreshable_dc_index(project_dict)
    if not refreshable_index:
        raise HTTPException(
            status_code=422,
            detail=(
                "Project has no data collections this server can re-read. Remote "
                "sources can always be refreshed; a local one only if its path is "
                "visible from the server."
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

    # Project-scoped read credentials (per-project storage config), resolved
    # once; async workers re-resolve for themselves so no secret ever crosses
    # the broker.
    remote_options: dict | None = None
    if not dry_run and not async_run:
        from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
            storage_options_for_project,
        )

        remote_options = storage_options_for_project(project_oid)

    # Each DC carries its own manifest URL + field map; fetch each distinct
    # combination once. Failures are per-DC, not global — one dead manifest
    # must not block refreshing DCs backed by a different one.
    manifests: dict[tuple, DataManifest | str] = {}  # key -> manifest or error text
    to_dispatch: list[tuple[str, str, int, int]] = []  # (tag, dc_id, wf_i, entries)
    preflight_failed: list[tuple[str, str, str]] = []  # (tag, dc_id, message), async only
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

    for tag, (wf_i, dc_i, scan_params, mode) in refreshable_index.items():
        dc_dict = workflows[wf_i]["data_collections"][dc_i]
        dc_id = str(dc_dict.get("_id") or dc_dict.get("id") or "")

        # Only manifest mode has a pre-flight. Every other mode discovers its
        # own files during the scan, so there is nothing to check up front and
        # no entry count to report before running.
        entry_count = 0
        if mode == "manifest":
            preflight = _manifest_preflight_entries(tag, scan_params, manifests)
            if isinstance(preflight, str):
                _fail_preflight(tag, dc_id, preflight)
                continue
            entry_count = preflight

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

        try:
            ok, message = _run_dc_ingest(
                workflows[wf_i],
                dc_id,
                current_user,
                sync_files=True,
                remote_storage_options=remote_options,
            )
        except HTTPException:
            raise
        except Exception as exc:  # helper crash — treat as a per-DC failure
            logger.error(f"Refresh crashed for DC '{tag}': {exc}")
            ok, message = False, str(exc)
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

    # Both lists are only ever filled in async (non-dry) mode. A run document
    # is created even when every DC failed pre-flight, so the caller always
    # gets a run_id and the poll endpoint shows the failures.
    if to_dispatch or preflight_failed:
        run_id, dispatch_ok, dispatched = _dispatch_refresh_tasks(
            project_dict=project_dict,
            to_dispatch=to_dispatch,
            current_user=current_user,
            preflight_failed=preflight_failed,
        )
        report.run_id = run_id
        report.refreshed.extend(dispatched)
        all_ok = all_ok and dispatch_ok

    report.success = all_ok
    return report


def _dispatch_refresh_tasks(
    *,
    project_dict: dict,
    to_dispatch: list[tuple[str, str, int, int]],
    current_user,
    preflight_failed: list[tuple[str, str, str]],
    command: str = "refresh_manifest",
    scan_modes: dict[str, str] | None = None,
    data_root: str | None = None,
) -> tuple[str, bool, list[ManifestIngestDCResult]]:
    """Fan the per-DC ingestions out to Celery, backed by an ingestion run.

    Steps are pre-seeded (one per DC tag, status "pending") so the workers'
    ``set_ingestion_step`` positional updates are atomic under concurrency.
    Poll ``GET /projects/refresh_manifest/{run_id}`` for the aggregate report —
    Mongo is the durable status of record; Celery is only the transport.

    ``preflight_failed`` DCs (manifest unfetchable, entry rejected, type
    dropped from the manifest, a source absent from the data root) never reach
    a worker but are seeded as already-failed steps with ``file_count=0``: the
    finalizer computes the run status from the seeded steps, so leaving them
    out would let the run close as "success" with the skipped DC silently
    absent from the poll report.

    Shared with ``POST /projects/from_run``, which needs exactly this: a
    durable run whose steps a worker updates and a caller polls. The two flows
    differ only in bookkeeping, which is what the keyword arguments carry —
    ``command`` labels the run (and is what ``_get_refresh_run_report`` accepts),
    ``scan_modes`` records each DC's real mode instead of assuming "manifest",
    and ``data_root`` notes the prefix a from_run ingested from. Their defaults
    are the manifest refresh's own values.

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

    modes = scan_modes or {}
    run_id = uuid4().hex
    # Pre-flight failures first, then the DCs a worker will actually run.
    data_collections = [
        IngestionDataCollection(tag=tag, scan_mode=modes.get(tag, "manifest"), file_count=0)
        for tag, _dc_id, _message in preflight_failed
    ] + [
        IngestionDataCollection(tag=tag, scan_mode=modes.get(tag, "manifest"), file_count=entries)
        for tag, _dc_id, _wf_i, entries in to_dispatch
    ]
    steps = [
        IngestionStep(name=tag, status="failed", detail=message)
        for tag, _dc_id, message in preflight_failed
    ] + [IngestionStep(name=tag, status="pending") for tag, _dc_id, _wf_i, _entries in to_dispatch]
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

    user_ctx = {
        "id": str(current_user.id),
        "email": getattr(current_user, "email", None),
        "is_admin": bool(getattr(current_user, "is_admin", False)),
    }
    results: list[ManifestIngestDCResult] = []
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
        try:
            manifest_refresh_dc_task.apply_async(args=[payload])
            status, message = "dispatched", None
        except Exception as exc:  # broker down — a per-DC failure, not a 5xx
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
# run with the same shape — pre-seeded steps a worker updates — so one route
# answers for both; a run from any other command (a CLI ``run``, a UI upload)
# belongs to another report and is not found here.
_POLLABLE_RUN_COMMANDS = frozenset({"refresh_manifest", "from_run"})

_REFRESH_STEP_TO_DC_STATUS = {
    "pending": "dispatched",
    "running": "running",
    "success": "ingested",
    "failed": "failed",
}


def _get_refresh_run_report(run_id: str, current_user) -> ManifestRefreshReport:
    """Aggregate an async ingestion run into the same report shape as sync mode.

    Serves both the async manifest refresh and the background ingestion a
    ``POST /projects/from_run`` opens — see ``_POLLABLE_RUN_COMMANDS``.
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
    # dc ids aren't stored on the run — rebuild the mapping from the live
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
        for wf in project_dict.get("workflows") or []:
            for dc in wf.get("data_collections") or []:
                tag = dc.get("data_collection_tag")
                if tag and tag not in dc_ids_by_tag:
                    dc_ids_by_tag[tag] = str(dc.get("_id") or dc.get("id") or "")

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
