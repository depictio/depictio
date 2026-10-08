import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from bson import ObjectId
from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from depictio.api.v1.remote_fetch import (
    RemoteFetchFailed,
    direct_fetch_text,
    direct_probe,
    fetch_validated_text,
    is_public_s3_location,
    is_server_context,
    probe_remote_url,
    public_s3_region,
    validate_remote_url,
)
from depictio.cli.cli.utils.api_calls import (
    api_create_files,
    api_create_files_chunked,
    api_delete_file,
    api_delete_files,
    api_delete_runs,
    api_get_files_by_dc_id,
    api_get_runs_by_wf_id,
    api_upsert_runs_batch,
)
from depictio.cli.cli.utils.common import format_timestamp
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_data_collection_light,
    rich_print_summary_scan_table_enhanced,
)
from depictio.cli.cli.utils.scan_utils import (
    collect_run_candidates,
    construct_full_regex,
    data_collection_full_regex,
    describe_empty_scan_outcome,
    describe_unmatched_run_scan,
    file_matches_data_collection,
    generate_file_hash,
    generate_run_hash,
    regex_match,
)
from depictio.cli.cli.utils.scan_walk import (
    ScannedPath,
    is_ignored,
    iter_run_files,
    run_signature,
)
from depictio.cli.cli.utils.state import ProjectScanState, RunState, load_state, save_state
from depictio.cli.cli_logging import logger
from depictio.models.models.base import PyObjectId
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.files import (
    NOT_UPLOADED_SCAN_REASONS,
    File,
    FileScanResult,
)
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import (
    Workflow,
    WorkflowConfig,
    WorkflowDataLocation,
    WorkflowRun,
    WorkflowRunScan,
)

#: Counter keys carried by every per-data-collection scan stat block. Declared
#: once so the run-level aggregate stays in sync when a counter is added.
SCAN_STAT_KEYS: tuple[str, ...] = (
    "total_files",
    "updated_files",
    "new_files",
    "changed_files",
    "unchanged_files",
    "missing_files",
    "deleted_files",
    "vanished_files",
    "skipped_files",
    "other_failure_files",
)

#: File-id buckets persisted on each ``WorkflowRunScan``. Deliberately narrower
#: than SCAN_STAT_KEYS: unchanged files are the bulk of a steady-state scan and
#: listing their ids would bloat the run document for no benefit, while a
#: departure has to be identifiable: reconstructing "which files backed this
#: data collection at time T" needs the ids, and under --sync-files the records
#: themselves are gone.
SCAN_FILE_ID_BUCKETS: tuple[str, ...] = (
    "updated_files",
    "new_files",
    "changed_files",
    "skipped_files",
    "other_failure_files",
    "deleted_files",
    "missing_files",
)


@dataclass(frozen=True, slots=True)
class _ScanBounds:
    """A data collection's ``max_depth``/``ignore`` restrictions."""

    max_depth: int | None
    ignore: tuple[str, ...]

    @property
    def is_unbounded(self) -> bool:
        return self.max_depth is None and not self.ignore

    def allows(self, scanned: ScannedPath) -> bool:
        if self.max_depth is not None and scanned.rel_path.count("/") > self.max_depth:
            return False
        return not is_ignored(scanned.match_name, scanned.rel_path, self.ignore)


def _dc_scan_bounds(dc: DataCollection) -> _ScanBounds:
    """Read a data collection's scan bounds, defaulting to unbounded."""
    params = dc.config.scan.scan_parameters if dc.config.scan else None
    return _ScanBounds(
        max_depth=getattr(params, "max_depth", None),
        ignore=tuple(getattr(params, "ignore", None) or ()),
    )


def _walk_bounds(data_collections: list[DataCollection]) -> _ScanBounds:
    """The most permissive bounds across data collections.

    The run tree is walked once and shared, so directory-level pruning may only
    drop what *every* data collection excludes; each one re-applies its own
    bounds as a filter afterwards. When they all agree — the common case — the
    prune still happens during the walk and nothing under an ignored folder is
    ever stat'd.
    """
    per_dc = [_dc_scan_bounds(dc) for dc in data_collections]
    if not per_dc:
        return _ScanBounds(max_depth=None, ignore=())

    depths = [bounds.max_depth for bounds in per_dc]
    walk_depth = None if any(d is None for d in depths) else max(d for d in depths if d is not None)

    common_ignore = set(per_dc[0].ignore)
    for bounds in per_dc[1:]:
        common_ignore &= set(bounds.ignore)

    return _ScanBounds(max_depth=walk_depth, ignore=tuple(sorted(common_ignore)))


def _warn_enforced_scan_bounds(data_collections: list[DataCollection]) -> None:
    """Announce that ``max_depth``/``ignore`` are now enforced.

    Both fields have been accepted by the config model and silently dropped, so
    any project that set them has been registering files its own config asked to
    exclude. Enforcing them is the fix, but it *removes* files from an existing
    project's view — which deserves saying out loud rather than showing up as an
    unexplained drop in counts.
    """
    bounded = []
    for dc in data_collections:
        bounds = _dc_scan_bounds(dc)
        if not bounds.is_unbounded:
            bounded.append((dc.data_collection_tag, bounds))

    if not bounded:
        return

    details = ", ".join(
        f"{tag} (max_depth={bounds.max_depth}, ignore={list(bounds.ignore)})"
        for tag, bounds in bounded
    )
    rich_print_checked_statement(
        f"Now enforcing scan max_depth/ignore for: {details}. These were previously parsed "
        "but never applied, so fewer files may be registered than in earlier runs. "
        "Pass --legacy-scan-depth to restore the old behaviour for one release.",
        "warning",
    )


def scan_single_file(
    file_location: str,
    run: WorkflowRun,
    data_collection: "DataCollection",
    permissions: Permission,
    existing_files: dict[str, dict],
    update_files: bool,
    full_regex: str | None = None,
    skip_regex: bool = False,
    scanned: ScannedPath | None = None,
    sync_changed: bool = False,
) -> FileScanResult | None:
    """
    Process a single file.

    Checks if the filename matches the regex pattern.
    If the file already exists (based on its file_location), it will skip (unless update_files is True).
    Otherwise, the file details are collected and a File instance is created.

    Args:
        file_location (str): The full path to the file.
        run (WorkflowRun): The run instance to associate with the file.
        data_collection (DataCollection): The data collection configuration.
        permissions (Permission): The permissions for the file.
        existing_files (List[dict]): Existing files from the database.
        update_files (bool): Whether to update existing file entries.
        full_regex (str): The regex pattern to match the filename.
        skip_regex (bool): Whether to skip the regex check.
        scanned (ScannedPath): Metadata already read by ``iter_run_files``. When
            provided, ``file_location`` is ignored and no filesystem call is made
            here — the walker's single ``scandir`` stat is reused instead of
            re-issuing ``realpath`` plus three ``stat`` calls per file.
        sync_changed (bool): Whether a registered file whose metadata hash moved
            should be re-uploaded. Narrower than ``update_files``, which
            re-uploads every registered file regardless.

    Returns:
        Optional[File]: A File instance if the file is valid; otherwise, None.
    """

    if scanned is not None:
        file_location = scanned.path
        file_name = scanned.name
    else:
        # Record the real on-disk path, resolving any symlinks in the scanned path.
        # Runs can be scanned through an intermediate symlink (e.g. per-run isolation
        # that points --data-root at a temporary symlink tree), and the stored path
        # should be the original target, not the transient symlink. file_hash is
        # derived from basename + size + mtime (not the path), so this does not affect
        # change detection or hash-based dedup.
        file_location = os.path.realpath(file_location)
        file_name = os.path.basename(file_location)

    if not skip_regex:
        if full_regex is None:
            raise ValueError("full_regex must be provided unless skip_regex is True")
        match, _ = regex_match(file_name, full_regex)
        if not match:
            # logger.debug(f"File {file_name} does not match regex, skipping.")
            return None

    # Get file details. Kept after the regex check so a non-matching file still
    # costs nothing on the legacy (non-``scanned``) path.
    if scanned is not None:
        creation_time_iso = format_timestamp(scanned.ctime)
        modification_time_iso = format_timestamp(scanned.mtime)
        filesize = scanned.size
    else:
        creation_time_iso = format_timestamp(os.path.getctime(file_location))
        modification_time_iso = format_timestamp(os.path.getmtime(file_location))
        filesize = os.path.getsize(file_location)

    # A zero-byte output is a step that wrote nothing (SEACR on a library with
    # no peaks): it holds no rows, and a File cannot have size zero.
    if filesize == 0:
        rich_print_checked_statement(
            f"Skipped empty file {escape(file_location)}: zero bytes, no rows", "warning"
        )
        return None

    file_hash = generate_file_hash(file_name, filesize, creation_time_iso, modification_time_iso)
    logger.debug(f"File Hash for {file_name}: {file_hash}")

    scan_result = None
    file_id = None

    # Direct dict lookup. This used to be a linear scan over a freshly
    # materialized copy of the key view, i.e. O(files_in_run x files_in_db) plus
    # one list allocation per file. Note also that the removed
    # ``logger.debug(f"Existing Files: {existing_files}")`` stringified the whole
    # registry once per scanned file, regardless of log level.
    existing_file = existing_files.get(file_location)
    if existing_file is not None:
        file_id = existing_file["_id"]
        changed = existing_file["file_hash"] != file_hash

        if update_files:
            # --sync-files: re-upload unconditionally, changed or not.
            logger.debug(f"Updating existing file {file_name}.")
            scan_result = {"result": "success", "reason": "updated"}
        elif changed:
            # This comparison was already being computed and then thrown away in
            # a debug log, so a file rewritten in place stayed invisible unless
            # the user reached for --sync-files and re-uploaded everything.
            logger.debug(f"File {file_name} changed since last scan.")
            scan_result = {
                "result": "success" if sync_changed else "failure",
                "reason": "changed",
            }
        else:
            logger.debug(f"File {file_name} unchanged since last scan.")
            scan_result = {"result": "failure", "reason": "unchanged"}

    # Create the File instance.
    file_instance = File(
        id=PyObjectId(file_id) if file_id else PyObjectId(),
        filename=file_name,
        file_location=file_location,
        creation_time=creation_time_iso,
        modification_time=modification_time_iso,
        file_hash=file_hash,
        filesize=filesize,
        data_collection_id=data_collection.id,
        run_id=run.id,
        run_tag=run.run_tag,
        permissions=permissions,
    )

    if not scan_result:
        reason = "added" if existing_file is None else "updated"
        scan_result = {"result": "success", "reason": reason}

    logger.debug(f"Scan Result: {scan_result}")

    file_scan_result = FileScanResult(
        file=file_instance,
        scan_result=scan_result,
        scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    logger.debug(f"File Scan Result: {file_scan_result}")
    return file_scan_result


def process_files(
    path: str,
    run: WorkflowRun,
    data_collection: "DataCollection",
    permissions: Permission,
    existing_files: dict[str, dict],
    update_files: bool = False,
    skip_regex: bool = False,
    sync_changed: bool = False,
    honor_scan_bounds: bool = True,
) -> list[FileScanResult]:
    """
    Scan files from a given directory or a single file path.

    If 'path' is a directory, scan it with iter_run_files.
    If it's a file, process that file directly.

    Args:
        path (str): The directory or file path to scan.
        run (WorkflowRun): The run instance to associate with the files.
        data_collection (DataCollection): The data collection configuration.
        existing_files (List[dict]): The list of files already in the database.
        update_files (bool): Whether to update files that already exist.
        skip_regex (bool): Whether to skip the regex check.

    Returns:
        List[File]: A list of File instances representing the scanned files.
    """
    logger.debug(f"Scanning path: {path}")

    if not os.path.exists(path):
        raise ValueError(f"The path '{path}' does not exist.")

    file_list = []

    # For recursive scans, build the regex from configuration.
    full_regex = None
    if (
        not skip_regex
        and data_collection.config.scan
        and hasattr(data_collection.config.scan.scan_parameters, "regex_config")
    ):
        regex_config = data_collection.config.scan.scan_parameters.regex_config
        full_regex = (
            construct_full_regex(regex=regex_config)  # type: ignore[invalid-argument-type]
            if getattr(regex_config, "wildcards", False)
            else regex_config.pattern  # type: ignore[unresolved-attribute]
        )
        logger.debug(f"Full Regex: {full_regex}")

    if os.path.isdir(path):
        logger.debug(f"Scanning directory: {path}")
        bounds = _dc_scan_bounds(data_collection) if honor_scan_bounds else _ScanBounds(None, ())
        for scanned in iter_run_files(path, max_depth=bounds.max_depth, ignore=list(bounds.ignore)):
            file_instance = scan_single_file(
                file_location=scanned.path,
                run=run,
                data_collection=data_collection,
                permissions=permissions,
                existing_files=existing_files,
                update_files=update_files,
                full_regex=full_regex,
                skip_regex=skip_regex,
                scanned=scanned,
                sync_changed=sync_changed,
            )
            if file_instance:
                file_list.append(file_instance)
    elif os.path.isfile(path):
        logger.debug(f"Scanning single file: {path}")
        file_instance = scan_single_file(
            file_location=path,
            run=run,
            data_collection=data_collection,
            permissions=permissions,
            existing_files=existing_files,
            update_files=update_files,
            full_regex=full_regex,
            skip_regex=skip_regex,
            sync_changed=sync_changed,
        )
        logger.debug(f"File Instance: {file_instance}")
        if file_instance:
            file_list.append(file_instance)
    else:
        raise ValueError(f"Path '{path}' is neither a file nor a directory.")

    return file_list


def scan_run_for_multiple_data_collections(
    run_location: str,
    run_tag: str,
    workflow_config: WorkflowConfig,
    data_collections: list[DataCollection],
    all_existing_files: dict,
    workflow_id: ObjectId,
    existing_run: WorkflowRun | None,
    CLI_config: CLIConfig,
    permissions: Permission,
    rescan_folders: bool = False,
    update_files: bool = False,
    sync_changed: bool = False,
    honor_scan_bounds: bool = True,
    prewalked: list[ScannedPath] | None = None,
    dry_run: bool = False,
    concurrency: int = 4,
    upload_chunk_size: int = 1000,
) -> WorkflowRun | None:
    """
    Scan a single run for multiple data collections simultaneously.

    ``prewalked`` lets the caller hand over a walk it already performed (the
    state-cache signature check does one), so the tree is never walked twice.
    ``dry_run`` reports what would happen without writing anything to the server.
    """
    if not os.path.exists(run_location):
        raise ValueError(f"The directory '{run_location}' does not exist.")
    if not os.path.isdir(run_location):
        raise ValueError(f"'{run_location}' is not a directory.")

    creation_time = format_timestamp(os.path.getctime(run_location))
    last_modification_time = format_timestamp(os.path.getmtime(run_location))

    if existing_run:
        logger.debug(f"Run {run_tag} already exists in the database.")
        if rescan_folders:
            logger.info(f"Reprocessing run {run_tag}...")
            workflow_run = existing_run
        else:
            logger.info(f"Skipping existing run {run_tag}.")
            return None
    else:
        workflow_run = WorkflowRun(
            workflow_id=PyObjectId(workflow_id),
            run_tag=run_tag,
            files_id=[],
            workflow_config_id=workflow_config.id,
            run_location=run_location,
            creation_time=creation_time,
            last_modification_time=last_modification_time,
            run_hash="",
            permissions=permissions,
        )

    # Walk the run tree once and share it across every data collection. The
    # stat metadata rides along, so the per-DC loops below never touch the
    # filesystem again — they only re-run the regex.
    if prewalked is not None:
        all_files_in_run: list[ScannedPath] = prewalked
    else:
        walk_bounds = _walk_bounds(data_collections) if honor_scan_bounds else _ScanBounds(None, ())
        all_files_in_run = list(
            iter_run_files(
                run_location,
                max_depth=walk_bounds.max_depth,
                ignore=list(walk_bounds.ignore),
            )
        )

    # Process files for each data collection
    all_processed_files = []
    dc_stats = {}  # This will store per-data-collection stats
    dc_file_ids = {}

    logger.debug(f"Processing {len(data_collections)} data collections for run {run_tag}")

    for dc in data_collections:
        logger.debug(
            f"Processing files for data collection {dc.data_collection_tag} in run {run_tag}"
        )

        # Get existing files for this data collection
        existing_files_for_dc = all_existing_files.get(str(dc.id), {})
        logger.debug(
            f"Existing files for DC {dc.data_collection_tag}: {len(existing_files_for_dc)}"
        )

        # Build regex for this data collection (only for recursive scans)
        full_regex = data_collection_full_regex(dc)
        if full_regex is None:
            logger.warning(
                f"Data collection {dc.data_collection_tag} does not have scan config or regex_config (likely single-file scan or MultiQC)"
            )
            continue
        logger.debug(f"Regex for DC {dc.data_collection_tag}: {full_regex}")

        # A temporary run used only for file association — invariant across
        # every file in this run, so build it once here instead of
        # reallocating an identical WorkflowRun inside the per-file loop.
        temp_run = WorkflowRun(
            id=workflow_run.id,
            workflow_id=PyObjectId(workflow_id),
            run_tag=run_tag,
            files_id=[],
            workflow_config_id=workflow_config.id,
            run_location=run_location,
            creation_time=creation_time,
            last_modification_time=last_modification_time,
            run_hash="",
            permissions=permissions,
        )

        # Process files that match this data collection's regex
        # The shared walk is pruned only to what every data collection excludes,
        # so each one re-applies its own bounds here.
        dc_bounds = _dc_scan_bounds(dc) if honor_scan_bounds else None
        if dc_bounds is not None and dc_bounds.is_unbounded:
            dc_bounds = None

        dc_file_scan_results = []
        for scanned in all_files_in_run:
            if dc_bounds is not None and not dc_bounds.allows(scanned):
                continue
            # Matched on the walked path rather than the symlink-resolved one,
            # which is what this loop has always compared.
            if not file_matches_data_collection(scanned.walk_path, run_location, full_regex):
                continue

            logger.debug(f"File {scanned.match_name} matches DC {dc.data_collection_tag}")

            # skip_regex=True because we already matched in the loop above
            file_scan_result = scan_single_file(
                file_location=scanned.path,
                run=temp_run,
                data_collection=dc,
                permissions=permissions,
                existing_files=existing_files_for_dc,
                update_files=update_files,
                full_regex=full_regex,
                skip_regex=True,
                scanned=scanned,
                sync_changed=sync_changed,
            )

            if file_scan_result:
                dc_file_scan_results.append(file_scan_result)

        # Process the scan results for this data collection. Bucket by reason
        # once rather than re-walking the result list per counter.
        by_reason: defaultdict[str, list] = defaultdict(list)
        for sc in dc_file_scan_results:
            by_reason[sc.scan_result["reason"]].append(sc.file.id)

        old_updated_files = by_reason["updated"]
        new_files = by_reason["added"]
        files_unchanged = by_reason["unchanged"]
        files_changed = by_reason["changed"]

        # "skipped" stays the umbrella for "already registered, not re-uploaded"
        # so counts remain comparable with scans predating hash detection.
        # Anything failing outside that set is a genuine failure.
        files_skipped = [
            sc.file.id
            for sc in dc_file_scan_results
            if sc.scan_result["result"] == "failure"
            and sc.scan_result["reason"] in NOT_UPLOADED_SCAN_REASONS
        ]
        files_other_failure = [
            sc.file.id
            for sc in dc_file_scan_results
            if sc.scan_result["result"] == "failure"
            and sc.scan_result["reason"] not in NOT_UPLOADED_SCAN_REASONS
        ]

        # Registered files this scan did not encounter. Computed here rather
        # than inside the branch below: a data collection that matched nothing
        # in this run still needs the number, and that is precisely the case
        # where every one of its files under this run has disappeared.
        missing_files_location = set(existing_files_for_dc.keys()) - {
            str(sc.file.file_location) for sc in dc_file_scan_results
        }

        # Hoisted so the id buckets below are always defined: a data collection
        # that matched nothing this cycle still needs an (empty) entry.
        missing_files: list[str] = []

        if dc_file_scan_results:
            # ``result`` already encodes "should this be uploaded": added always,
            # changed only under --sync-changed, updated only under --sync-files.
            files_to_upload = [
                sc.file for sc in dc_file_scan_results if sc.scan_result["result"] == "success"
            ]

            # Upload files for this data collection
            if files_to_upload:
                logger.info(f"Files to add for DC {dc.data_collection_tag}: {len(files_to_upload)}")
                if dry_run:
                    rich_print_checked_statement(
                        f"[dry-run] Would register {len(files_to_upload)} file(s) "
                        f"for {escape(dc.data_collection_tag)}",
                        "info",
                    )
                else:
                    # /files/upsert_batch uses $setOnInsert when update=False, which
                    # would silently discard the new metadata of a file that already
                    # exists — so pushing changed files has to ask for $set.
                    responses = api_create_files_chunked(
                        files=files_to_upload,
                        CLI_config=CLI_config,
                        update=update_files or sync_changed,
                        chunk_size=upload_chunk_size,
                        concurrency=concurrency,
                    )
                    # A rejected chunk means those files were never registered.
                    # Unchecked, the scan reports success and the Delta table is
                    # then built from an incomplete file set with nothing
                    # anywhere saying so. Reachable, not theoretical: the server
                    # enforces a 5000-file ceiling per batch.
                    failed = [r for r in responses if r.status_code != 200]
                    if failed:
                        codes = sorted({str(r.status_code) for r in failed})
                        raise RuntimeError(
                            f"{len(failed)} of {len(responses)} file batches failed for "
                            f"'{dc.data_collection_tag}' (HTTP {', '.join(codes)}). "
                            "Files are only partially registered: re-run the scan."
                        )

            # Handle missing files
            missing_files = [
                str(existing_files_for_dc[file_location]["_id"])
                for file_location in missing_files_location
            ]

            if missing_files and update_files:
                logger.info(f"Files to remove for DC {dc.data_collection_tag}: {missing_files}")
                if dry_run:
                    rich_print_checked_statement(
                        f"[dry-run] Would remove {len(missing_files)} stale file(s) "
                        f"from {escape(dc.data_collection_tag)}",
                        "info",
                    )
                else:
                    api_delete_files(missing_files, CLI_config, concurrency=concurrency)

            # Collect all files for this run
            all_processed_files.extend(files_to_upload)

        # Store file IDs for this data collection. ``changed_files`` is worth
        # persisting because it is small and actionable; ``unchanged_files`` is
        # the bulk of a steady-state scan and would only bloat the run document.
        dc_file_ids[dc.data_collection_tag] = {
            "updated_files": old_updated_files,
            "new_files": new_files,
            "changed_files": files_changed,
            "skipped_files": files_skipped,
            "other_failure_files": files_other_failure,
            # A file that left the filesystem was the one event the run ledger
            # could not describe: the ids were computed to drive the delete call
            # and then thrown away, leaving only a count — and under
            # --sync-files the records are hard-deleted, so that count was the
            # only surviving trace. Split by fate, mirroring dc_stats below:
            # deleted_files were actually removed, missing_files merely went
            # absent from the scan while their records were left in place.
            "deleted_files": missing_files if update_files else [],
            "missing_files": [] if update_files else missing_files,
        }

        # Calculate missing files count.
        #
        # Careful with this number: ``existing_files_for_dc`` spans every run of
        # the collection while ``dc_file_scan_results`` covers only this one, so
        # for a multi-run collection it counts most of the other runs' files as
        # "missing". It is kept as-is because the summary tables have always
        # shown it, but nothing may decide anything on it.
        missing_files_count = (
            len(existing_files_for_dc) - len(dc_file_scan_results) if existing_files_for_dc else 0
        )

        # A registered file that lives under *this* run and was not seen this
        # time has genuinely disappeared. Unlike the count above this one is
        # scoped correctly, which is what lets a deletion mark the collection as
        # changed instead of the table quietly keeping rows for a file that is
        # no longer on disk. Registered locations are resolved paths, so the run
        # is too: a run reached through a symlink would otherwise match nothing.
        run_prefix = os.path.join(os.path.realpath(run_location), "")
        vanished_files = [
            location for location in missing_files_location if str(location).startswith(run_prefix)
        ]

        # Store stats for this data collection - THIS IS KEY!
        dc_stats[dc.data_collection_tag] = {
            "total_files": len(dc_file_scan_results),
            "updated_files": len(old_updated_files),
            "new_files": len(new_files),
            "changed_files": len(files_changed),
            "unchanged_files": len(files_unchanged),
            "missing_files": missing_files_count if not update_files else 0,
            "deleted_files": missing_files_count if update_files else 0,
            "vanished_files": len(vanished_files),
            "skipped_files": len(files_skipped),
            "other_failure_files": len(files_other_failure),
        }

        logger.debug(f"DC Stats for {dc.data_collection_tag}: {dc_stats[dc.data_collection_tag]}")

    # Log the final dc_stats to verify it's populated
    logger.debug(f"Final dc_stats for run {run_tag}: {dc_stats}")

    # Update the workflow run with all files
    workflow_run.files_id = [file.id for file in all_processed_files]

    # Generate aggregate stats for the run (sum across all data collections).
    # Driven by SCAN_STAT_KEYS so a new counter shows up in the run total
    # without a second edit here.
    aggregate_stats = {
        key: sum(stats.get(key, 0) for stats in dc_stats.values()) for key in SCAN_STAT_KEYS
    }

    logger.debug(f"Aggregate Stats for run {run_tag}: {aggregate_stats}")

    # Combine file IDs from all data collections. Driven by the bucket names so
    # a new bucket shows up in the run total without a second edit here.
    combined_files_id: dict[str, list] = {bucket: [] for bucket in SCAN_FILE_ID_BUCKETS}
    for file_ids in dc_file_ids.values():
        for bucket in SCAN_FILE_ID_BUCKETS:
            combined_files_id[bucket].extend(file_ids.get(bucket, []))

    # Create the WorkflowRunScan with dc_stats
    scan_result = WorkflowRunScan(
        stats=aggregate_stats,
        files_id=combined_files_id,
        dc_stats=dc_stats,  # Make sure this is set!
        scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    logger.debug(f"Created WorkflowRunScan with dc_stats: {scan_result.dc_stats}")

    # Store dc_stats for table display (temporary storage)
    workflow_run._dc_stats_for_display = dc_stats

    # Carry the tree signature back so the caller can cache it without walking
    # the run a second time.
    workflow_run._scan_signature = run_signature(all_files_in_run)
    workflow_run._scan_file_count = len(all_files_in_run)

    logger.debug(f"Storing dc_stats for display on run {run_tag}: {dc_stats}")

    if workflow_run.scan_results is None:
        workflow_run.scan_results = []
    workflow_run.scan_results.append(scan_result)

    # Generate the hash for the run
    run_hash = generate_run_hash(
        run_location, creation_time, last_modification_time, all_processed_files
    )
    workflow_run.run_hash = run_hash

    return workflow_run


def flat_run_tag(location: str) -> str:
    """The run a ``structure: flat`` location is registered as: its directory's name."""
    return os.path.basename(os.path.normpath(location))


def flat_run_tag_clash(data_location: WorkflowDataLocation) -> str | None:
    """Why two locations of a flat workflow would be registered as one run, or ``None``.

    A flat run is named after its directory, so ``/scratch/a/results`` and
    ``/scratch/b/results`` would both be run ``results``: the scan registers the
    files of both under it, and every sample is listed twice. The same directory
    reached twice, through a symlink for instance, is one run.
    """
    if data_location.structure != "flat":
        return None
    first_by_tag: dict[str, str] = {}
    for location in data_location.locations:
        tag = flat_run_tag(location)
        first = first_by_tag.setdefault(tag, location)
        if os.path.realpath(first) != os.path.realpath(location):
            return (
                f"{first} and {location} would both be run '{tag}': a flat workflow names "
                "each run after its directory, so their samples would be listed twice. "
                "Rename one of the directories, or ingest it into another project."
            )
    return None


def _run_to_rescan(existing_run: WorkflowRun | None, run_location: str) -> WorkflowRun | None:
    """The registered run a rescan of ``run_location`` updates, or ``None`` for a new one.

    A run of the same name registered from another directory is not it: a results
    directory that moved leaves one behind. Reused, it kept the files of the old
    directory next to those of the new one, and every sample was listed twice. As a
    new run, the old one is removed with its files once the scan is done.
    """
    if existing_run and os.path.realpath(existing_run.run_location) != os.path.realpath(
        run_location
    ):
        return None
    return existing_run


@dataclass(slots=True)
class _PendingRun:
    """A run that still needs scanning."""

    location: str
    tag: str
    #: Populated when the state cache forced a walk to compute the signature.
    #: Handed to the scan so the tree is never walked twice in one invocation.
    scanned: list[ScannedPath] | None = None
    signature: str | None = None


@dataclass(slots=True)
class _PendingLocation:
    """Runs still needing a scan under one configured location.

    Resolving this up front, before any file registry is fetched, is what makes
    a no-op scan cheap: with nothing pending there is nothing to compare
    against, so the per-data-collection ``/files/list`` calls are skipped
    entirely.
    """

    location: str
    structure: str
    runs: list[_PendingRun]
    #: Every run found on disk under this location, as ``(run_tag, run_location)``
    #: pairs, including the ones that did not need a scan. The missing-run cleanup
    #: compares the registry against *this*, not against the runs that were
    #: scanned: a run skipped because the state cache proved it unchanged is still
    #: very much present, and deleting it would take its files with it.
    present: list[tuple[str, str]] = field(default_factory=list)
    #: Registered runs left alone: already ingested, or unchanged since the last
    #: scan. A scan that skips every run is a legitimate no-op, not an empty one.
    skipped: int = 0

    @property
    def present_tags(self) -> list[str]:
        return [tag for tag, _ in self.present]


def _fetch_existing_files(
    data_collections: list[DataCollection], CLI_config: CLIConfig
) -> dict[str, dict[str, dict]]:
    """Load each data collection's registered files, keyed by file location."""
    all_existing_files: dict[str, dict[str, dict]] = {}

    def _load(dc: DataCollection) -> None:
        response = api_get_files_by_dc_id(dc_id=str(dc.id), CLI_config=CLI_config)
        if response.status_code == 200:
            existing_files = response.json()
            all_existing_files[str(dc.id)] = (
                {f["file_location"]: f for f in existing_files} if existing_files else {}
            )
        else:
            all_existing_files[str(dc.id)] = {}
            logger.warning(f"Failed to retrieve existing files for data collection {dc.id}")

    if len(data_collections) > 1:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("({task.completed}/{task.total} collections)"),
            console=None,
        ) as progress:
            task_id = progress.add_task(
                "Loading existing files from database", total=len(data_collections)
            )

            for dc in data_collections:
                # Format data collection tag to consistent width to avoid line changes
                formatted_dc_tag = f"{dc.data_collection_tag:<25}"[
                    :25
                ]  # Left-align and pad/truncate to 25 chars
                # Total description length: 45 chars to match run scanning
                progress.update(task_id, description=f"Loading files for {formatted_dc_tag}")
                _load(dc)
                progress.advance(task_id)
    else:
        # Single data collection - no progress bar needed
        for dc in data_collections:
            _load(dc)

    return all_existing_files


def _resolve_pending_runs(
    *,
    workflow: Workflow,
    locations: list[str],
    existing_runs: dict[str, WorkflowRun],
    rescan_folders: bool,
    state: ProjectScanState | None = None,
    walk_bounds: _ScanBounds | None = None,
) -> list[_PendingLocation]:
    """Determine which runs need scanning, touching only the filesystem and the run list.

    Two levels of skipping, in increasing cost:

    1. The run is already registered and no rescan was asked for: free, no
       filesystem access at all.
    2. A rescan *was* asked for, but the cached signature says the run's tree is
       byte-for-byte what it was at the last successful scan. This costs one
       walk, which is far less than the regex pass, ``File`` construction and
       registry fetch it avoids. The walk is handed forward so the scan itself
       does not repeat it. Only the registered run of this very directory can be
       proven unchanged: one of the same name from elsewhere is replaced (see
       ``_run_to_rescan``), so it is always scanned.
    """
    pending: list[_PendingLocation] = []
    structure = workflow.data_location.structure
    runs_regex = workflow.data_location.runs_regex
    workflow_id = str(workflow.id)
    bounds = walk_bounds or _ScanBounds(None, ())

    def _consider(run_location: str, run_tag: str) -> _PendingRun | None:
        """Return the run to scan, or None when it can be skipped."""
        if run_tag in existing_runs and not rescan_folders:
            logger.debug(f"Skipping existing run {run_tag}.")
            return None

        registered = _run_to_rescan(existing_runs.get(run_tag), run_location)
        cached = state.run_state(workflow_id, run_tag) if state else None
        if cached is None or registered is None:
            # Nothing to compare against, or the server has no run of this
            # directory: either way the cache cannot authorise a skip.
            return _PendingRun(location=run_location, tag=run_tag)

        scanned = list(
            iter_run_files(run_location, max_depth=bounds.max_depth, ignore=list(bounds.ignore))
        )
        signature = run_signature(scanned)
        if signature == cached.signature and os.path.realpath(
            cached.run_location
        ) == os.path.realpath(run_location):
            logger.info(f"Run {run_tag} unchanged since last scan: skipped.")
            return None

        return _PendingRun(location=run_location, tag=run_tag, scanned=scanned, signature=signature)

    for location in locations:
        logger.info(f"Scanning location: {location}")

        if not os.path.exists(location):
            raise ValueError(f"The directory '{location}' does not exist.")
        if not os.path.isdir(location):
            raise ValueError(f"'{location}' is not a directory.")

        if structure == "sequencing-runs" and not runs_regex:
            logger.error("runs_regex is required for sequencing-runs structure but was None")
            continue

        # A flat location is itself one run; otherwise each subdirectory matching
        # the regex is. The candidates carry every subdirectory, matching or not,
        # so matching nothing can say *why*: a wrong --data-root level reads very
        # differently from everything matched but already ingested, which is a
        # legitimate no-op.
        candidates = collect_run_candidates(location, structure, runs_regex)
        if structure != "flat" and not candidates.matched:
            rich_print_checked_statement(
                describe_unmatched_run_scan(location, runs_regex, candidates.subdirectories),
                "warning",
            )

        entry = _PendingLocation(location=location, structure=structure, runs=[])
        for run_tag, run_location in candidates.matched:
            entry.present.append((run_tag, run_location))
            candidate = _consider(run_location, run_tag)
            if candidate is None:
                entry.skipped += 1
            else:
                entry.runs.append(candidate)
        pending.append(entry)

    return pending


def scan_files_for_workflow(
    workflow: Workflow,
    data_collections: list[DataCollection],
    CLI_config: CLIConfig,
    command_parameters: dict,
) -> dict:
    """
    Scan files for all data collections of a workflow in a single pass.
    This avoids rescanning the same runs multiple times.

    Args:
        workflow (Workflow): The workflow configuration object.
        data_collections (list[DataCollection]): All data collections to scan.
        CLI_config (CLIConfig): CLI configuration containing API URL and credentials.
        command_parameters (dict): Command parameters, e.g. rescan_folders, sync_files.

    Returns:
        dict: Results summary with statistics per data collection.
    """
    # Parse the command parameters
    rescan_folders = command_parameters.get("rescan_folders", False)
    update_files = command_parameters.get("sync_files", False)
    sync_changed = command_parameters.get("sync_changed", False)
    rich_tables = command_parameters.get("rich_tables", True)
    honor_scan_bounds = not command_parameters.get("legacy_scan_depth", False)
    dry_run = command_parameters.get("dry_run", False)
    use_state_cache = command_parameters.get("state_cache", True)
    project_id = command_parameters.get("project_id")
    project_hash = command_parameters.get("project_hash")
    concurrency = command_parameters.get("concurrency", 4)
    upload_chunk_size = command_parameters.get("upload_chunk_size", 1000)

    clash = flat_run_tag_clash(workflow.data_location)
    if clash:
        raise ValueError(clash)

    if honor_scan_bounds:
        _warn_enforced_scan_bounds(data_collections)

    workflow_id = workflow.id

    # Generate permissions for the files
    user_base = CLI_config.user.model_dump()
    user_base.pop("token")
    user_base = UserBase.from_mongo(user_base)
    logger.debug(f"User: {user_base}")
    permissions = Permission(owners=[user_base])
    logger.debug(f"Permissions: {permissions}")

    # Existing runs come first: the skip decision depends only on them, and
    # resolving it before touching the file registry is what lets an unchanged
    # data root cost a single API call instead of one per data collection.
    existing_runs_reformated: dict[str, WorkflowRun] = {}
    # Runs whose directory is gone, by tag: the WorkflowRun model refuses a
    # location that does not exist, so they are kept as ids only. A rescan
    # removes them like any run it no longer finds; they used to fail the scan.
    gone_run_ids: dict[str, str] = {}
    existing_runs_response = api_get_runs_by_wf_id(wf_id=str(workflow_id), CLI_config=CLI_config)
    logger.info(f"Existing Runs Response: {existing_runs_response}")
    if existing_runs_response.status_code == 200:
        for e in existing_runs_response.json() or []:
            try:
                existing_runs_reformated[e["run_tag"]] = WorkflowRun.from_mongo(e)
            except ValueError as exc:
                logger.info(f"Run {e.get('run_tag')} is no longer readable: {exc}")
                gone_run_ids[e["run_tag"]] = str(e.get("_id") or e.get("id"))

    # Get locations from the workflow config
    locations = workflow.data_location.locations
    if not locations:
        rich_print_checked_statement(
            f"No locations configured for workflow {escape(workflow.workflow_tag)}.",
            "warning",
        )
        return {"result": "error", "message": "No locations configured"}

    # The state cache can only authorise skipping a rescan; without one, the
    # existing-run check already short-circuits without touching disk.
    state: ProjectScanState | None = None
    dc_ids = [str(dc.id) for dc in data_collections]
    # Collections whose files may be registered ahead of their table: a write
    # failed after an earlier scan registered them, so this scan will find those
    # files unchanged and cannot say the table is up to date. Without the state
    # that remembers it, that holds for every collection.
    unvouched: set[str] = set(dc_ids)
    if use_state_cache and rescan_folders and project_id:
        loaded = load_state(CLI_config.api_base_url, project_id, project_hash=project_hash)
        state = loaded or ProjectScanState(
            api_base_url=CLI_config.api_base_url,
            project_id=project_id,
            project_hash=project_hash,
        )
        if loaded is not None:
            unvouched = set(loaded.unsettled_dcs) & set(dc_ids)
        if not dry_run:
            # Persisted before the first file is registered, so even a scan that
            # dies halfway leaves the mark; the process step clears it once the
            # table is written (settle_collections).
            state.mark_unsettled(dc_ids)
            save_state(state)

    walk_bounds = _walk_bounds(data_collections) if honor_scan_bounds else _ScanBounds(None, ())

    pending_locations = _resolve_pending_runs(
        workflow=workflow,
        locations=locations,
        existing_runs=existing_runs_reformated,
        rescan_folders=rescan_folders,
        state=state,
        walk_bounds=walk_bounds,
    )
    pending_total = sum(len(pending.runs) for pending in pending_locations)
    # Runs recognised but left alone. A scan that skips every run is a legitimate
    # no-op; only one that recognises nothing has a data-root problem.
    runs_skipped_as_existing = sum(pending.skipped for pending in pending_locations)

    # Only pay for the file registry when there is something to compare against.
    # ``rescan_folders`` needs it regardless, for the missing-run cleanup below.
    if pending_total or rescan_folders:
        all_existing_files = _fetch_existing_files(data_collections, CLI_config)
    else:
        logger.info("No new runs detected: skipping the existing-file fetch.")
        all_existing_files = {str(dc.id): {} for dc in data_collections}

    # Scan runs once and collect files for all data collections
    all_workflow_runs = []

    for pending in pending_locations:
        if not pending.runs:
            continue

        if workflow.config is None:
            logger.error(f"Workflow config is None for workflow {workflow_id}")
            continue

        # "flat" treats the configured location itself as one run, so a progress
        # bar over a single item is noise; "sequencing-runs" can have hundreds.
        show_bar = pending.structure != "flat"
        columns = [SpinnerColumn(), TextColumn("[progress.description]{task.description}")]
        if show_bar:
            columns += [
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("({task.completed}/{task.total} runs)"),
            ]

        with Progress(*columns, console=None) as progress:
            task_id = progress.add_task(
                f"Scanning runs in {os.path.basename(pending.location)}"
                if show_bar
                else f"Scanning single location: {pending.runs[0].tag}",
                total=len(pending.runs) if show_bar else None,
            )

            for candidate in pending.runs:
                if show_bar:
                    # Format run name to consistent width to avoid line changes
                    # Need 29 chars for run name to match total description length of 45 chars
                    formatted_run = f"{candidate.tag:<29}"[:29]
                    progress.update(task_id, description=f"Scanning run: {formatted_run}")

                workflow_run = scan_run_for_multiple_data_collections(
                    run_location=candidate.location,
                    run_tag=candidate.tag,
                    workflow_config=workflow.config,
                    data_collections=data_collections,
                    all_existing_files=all_existing_files,
                    workflow_id=workflow_id,
                    CLI_config=CLI_config,
                    permissions=permissions,
                    rescan_folders=rescan_folders,
                    update_files=update_files,
                    sync_changed=sync_changed,
                    honor_scan_bounds=honor_scan_bounds,
                    prewalked=candidate.scanned,
                    dry_run=dry_run,
                    concurrency=concurrency,
                    upload_chunk_size=upload_chunk_size,
                    existing_run=_run_to_rescan(
                        existing_runs_reformated.get(candidate.tag), candidate.location
                    ),
                )
                if workflow_run:
                    all_workflow_runs.append(workflow_run)

                if show_bar:
                    progress.advance(task_id)

            if show_bar:
                progress.update(task_id, description="Scanning completed")

    # Handle missing runs if rescanning. Runs ONCE, after every location has been
    # walked: `all_workflow_runs` accumulates across locations, so doing this inside
    # the loop made a multi-location workflow delete the runs of the locations not
    # yet scanned (they were then re-created with fresh ids, losing scan_results).
    #
    # A run is kept when it was scanned or when it is still on disk, not only when
    # it was scanned. Those differ as soon as the state cache is warm: an unchanged
    # run is deliberately not rescanned, and treating "not scanned" as "no longer
    # there" deleted it and every one of its files on the second cycle of a watch.
    missing_runs_tag: set[str] = set()
    if rescan_folders:
        run_ids = {
            run_tag: str(run.id) for run_tag, run in existing_runs_reformated.items()
        } | gone_run_ids
        # By id, not by name: a run replaced by a new one of the same name (see
        # _run_to_rescan) goes too, which also frees its name for the new one.
        kept_ids = {str(run.id) for run in all_workflow_runs if run}
        for pending in pending_locations:
            for run_tag, run_location in pending.present:
                registered = _run_to_rescan(existing_runs_reformated.get(run_tag), run_location)
                if registered is not None:
                    kept_ids.add(str(registered.id))
        missing_runs_tag = {tag for tag, run_id in run_ids.items() if run_id not in kept_ids}
        missing_runs = [run_ids[run_tag] for run_tag in sorted(missing_runs_tag)]
        removed_label = escape(", ".join(sorted(missing_runs_tag)))

        if missing_runs:
            logger.info(f"Runs to remove: {missing_runs}")
            if dry_run:
                rich_print_checked_statement(
                    f"[dry-run] Would remove {len(missing_runs)} run(s) and their files: "
                    f"{removed_label}",
                    "info",
                )
            else:
                # Index the registry by run once, rather than scanning every
                # registered file per missing run.
                files_by_run: defaultdict[str, list[str]] = defaultdict(list)
                for files in all_existing_files.values():
                    for file in files.values():
                        files_by_run[str(file["run_id"])].append(str(file["_id"]))

                orphaned_files = [
                    file_id for run_id in missing_runs for file_id in files_by_run.get(run_id, [])
                ]

                runs_deleted = api_delete_runs(missing_runs, CLI_config, concurrency=concurrency)
                files_deleted = api_delete_files(
                    orphaned_files, CLI_config, concurrency=concurrency
                )

                # The counts the server confirmed, not the ones asked for: a
                # delete that failed used to be reported as done.
                incomplete = runs_deleted < len(missing_runs) or files_deleted < len(orphaned_files)
                rich_print_checked_statement(
                    f"Removed {runs_deleted} of {len(missing_runs)} run(s) and {files_deleted} of "
                    f"{len(orphaned_files)} related file(s) from the DB: {removed_label}",
                    "warning" if incomplete else "info",
                )

    # Upsert all runs at once with progress indicator
    if all_workflow_runs:
        if dry_run:
            rich_print_checked_statement(
                f"[dry-run] Would upload {len(all_workflow_runs)} run(s) to the server", "info"
            )
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=None,
            ) as progress:
                progress.add_task(f"Uploading {len(all_workflow_runs)} run(s) to server")
                response = api_upsert_runs_batch(all_workflow_runs, CLI_config, rescan_folders)
            # Before the state below records these runs as seen: recorded, a run
            # the server never stored would be skipped as unchanged from then on.
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Registering {len(all_workflow_runs)} run(s) failed "
                    f"(HTTP {response.status_code}): {response.text[:300]}"
                )

    # Only record state for work that actually reached the server. A dry run
    # must not convince the next invocation that these runs are up to date.
    if state is not None and not dry_run:
        for run in all_workflow_runs:
            signature = getattr(run, "_scan_signature", None)
            if not signature:
                continue
            state.record_run(
                str(workflow_id),
                RunState(
                    run_tag=run.run_tag,
                    run_location=run.run_location,
                    signature=signature,
                    file_count=getattr(run, "_scan_file_count", 0),
                ),
            )
        state.forget_runs(str(workflow_id), missing_runs_tag)
        save_state(state)

    # Generate single summary table for the entire workflow
    # if all_workflow_runs:
    if rich_tables:
        rich_print_summary_scan_table_enhanced(all_workflow_runs, workflow, show_totals=True)
    else:
        rich_print_data_collection_light(all_workflow_runs, workflow)

    files_found = sum(len(run.files_id or []) for run in all_workflow_runs if run)
    empty_outcome = describe_empty_scan_outcome(
        len(all_workflow_runs), files_found, runs_skipped_as_existing
    )
    if empty_outcome:
        # Reported as a warning rather than a failed result: the caller treats
        # anything but "success" as fatal, and one empty workflow must not
        # abort the other workflows and single-file data collections that may
        # well have ingested fine. The user needs to see this now all the same,
        # instead of debugging an empty dashboard later.
        rich_print_checked_statement(empty_outcome, "warning")
    else:
        rich_print_checked_statement(
            f"Scanned {len(all_workflow_runs)} runs in workflow {escape(workflow.workflow_tag)}",
            "success",
        )

    signal = _change_signal(
        all_workflow_runs,
        data_collections,
        missing_runs_tag,
        rescan_folders=rescan_folders,
        dry_run=dry_run,
    )
    if unvouched:
        # Not covered means neither skipped nor written by changed run only:
        # the process step rebuilds these from every registered file.
        signal["covered_dcs"] = [dc_id for dc_id in signal["covered_dcs"] if dc_id not in unvouched]
    return {
        "result": "success",
        "runs_scanned": len(all_workflow_runs),
        "files_found": files_found,
        "warning": empty_outcome,
        **signal,
    }


#: Per-data-collection counters that mean "this collection's rows changed".
#:
#: ``unchanged_files`` and ``skipped_files`` deliberately do not appear: they
#: are the bulk of a steady-state scan. Neither do ``missing_files`` and
#: ``deleted_files``: both are derived from a count that compares the whole
#: collection's registry against a single run's matches, so on a multi-run
#: collection they are large and meaningless. ``vanished_files`` is the
#: run-scoped version and is the one that can be trusted.
CHANGED_STAT_KEYS = ("new_files", "changed_files", "updated_files", "vanished_files")


def _change_signal(
    workflow_runs: list,
    data_collections: list[DataCollection],
    missing_runs_tag: set[str],
    *,
    rescan_folders: bool,
    dry_run: bool,
) -> dict:
    """Which data collections actually changed, and which runs changed in them.

    The scan already computes this per run and per data collection; it just had
    nowhere to go. Returning it is what lets the process step leave an untouched
    Delta table alone instead of rebuilding every table in the project on every
    cycle.

    ``complete`` is the honesty flag. The signal is only trustworthy when every
    run on disk was either scanned or proven unchanged, which is what
    ``rescan_folders`` buys; without it, already-registered runs are skipped
    with no check at all and "nothing changed" would be a guess. A dry run
    likewise reports what *would* happen, so it cannot authorise a skip.
    """
    tag_to_id = {dc.data_collection_tag: str(dc.id) for dc in data_collections}

    changed: dict[str, list[str]] = {}
    for run in workflow_runs:
        if not run:
            continue
        for dc_tag, stats in (getattr(run, "_dc_stats_for_display", None) or {}).items():
            if not any(stats.get(key, 0) for key in CHANGED_STAT_KEYS):
                continue
            dc_id = tag_to_id.get(dc_tag)
            if dc_id is None:
                # A tag with no matching collection cannot be acted on; say so
                # rather than dropping it, since the result gates real work.
                logger.warning(f"Scan reported changes for unknown data collection '{dc_tag}'")
                continue
            changed.setdefault(dc_id, []).append(run.run_tag)

    return {
        "changed_dcs": {dc_id: sorted(set(tags)) for dc_id, tags in changed.items()},
        # Only these collections were walked here, so only these can be reported
        # as unchanged. Anything absent (single-file collections, MultiQC,
        # recipes, joins) is not covered and must always be processed.
        "covered_dcs": sorted(tag_to_id.values()),
        "removed_runs": sorted(missing_runs_tag),
        "complete": bool(rescan_folders) and not dry_run,
    }


# HEAD probes are quick metadata lookups, so they get a shorter timeout than
# the policy's download timeout regardless of context.
_PROBE_TIMEOUT_S = 10.0


def _probe_url_metadata(url: str) -> dict:
    """HEAD an http(s) URL for size/etag; s3 URLs return unknowns.

    Server context (API process, Celery worker) goes through the SSRF gateway:
    a URL the policy rejects raises ``RemoteURLRejected`` and aborts the scan,
    so a rejected location is never registered. CLI context probes directly,
    since the URL is the user's own input on the user's own machine, with the
    same redirect cap.

    A probe that fails for reachability reasons returns ``etag=None`` (and a
    logged warning) so the caller can see it: the identity hash then falls
    back to URL + size instead of silently becoming content-blind.
    """
    if urlparse(url).scheme.lower() == "s3":
        return {"size": -1, "etag": ""}

    if is_server_context():
        validate_remote_url(url)  # policy violations propagate
        # Narrow on purpose: a redirect hop the policy rejects must abort the
        # scan too, so only reachability failures degrade.
        try:
            metadata = probe_remote_url(url, timeout_s=_PROBE_TIMEOUT_S)
        except RemoteFetchFailed as exc:
            logger.warning(f"Could not probe remote URL {url}: {exc}")
            return {"size": -1, "etag": None}
    else:
        try:
            metadata = direct_probe(url, timeout_s=_PROBE_TIMEOUT_S)
        except Exception as exc:
            logger.warning(f"Could not probe remote URL {url}: {exc}")
            return {"size": -1, "etag": None}

    size = metadata["size"]
    return {"size": size if size > 0 else -1, "etag": metadata["etag"]}


def _url_identity_hash(url: str, metadata: dict) -> str:
    """Identity (not integrity) hash of a url-mode File, see the RFC.

    A successful probe hashes URL + ETag (the ETag may be empty when the server
    sends none). A failed probe (``etag`` is ``None``) hashes URL + size and
    logs it, so the weaker hash is visible and a later successful probe shows
    up as "updated" rather than hiding behind a URL-only hash for good.
    """
    etag = metadata.get("etag")
    if etag is None:
        logger.warning(
            f"No ETag for {url} (probe failed): identity hash falls back to URL + size, "
            "so content changes are not detected until a probe succeeds."
        )
        return hashlib.sha256(f"{url}|size={metadata.get('size', -1)}".encode()).hexdigest()
    return hashlib.sha256(f"{url}|{etag}".encode()).hexdigest()


def scan_url_for_data_collection(
    workflow: Workflow,
    data_collection: "DataCollection",
    CLI_config: CLIConfig,
    permissions: Permission,
    update_files: bool,
) -> dict:
    """Register a remote URL (scan mode "url") as a File record.

    The remote counterpart of the single-file scan: no filesystem walk — one
    synthesized File whose file_location is the URL. Timestamps are the
    registration time; file_hash is sha256(url + etag), an identity hash (not
    content integrity — documented in the RFC).
    """
    import time

    scan_params = data_collection.config.scan.scan_parameters  # type: ignore[union-attr]
    url = scan_params.url  # type: ignore[union-attr]

    # Existing-file lookup + stale cleanup (same semantics as single mode:
    # a DC repointed at a different URL drops the old record).
    response = api_get_files_by_dc_id(dc_id=str(data_collection.id), CLI_config=CLI_config)
    existing_files: dict[str, dict] = {}
    if response.status_code == 200:
        for existing_file in response.json() or []:
            location = existing_file["file_location"]
            if location != url:
                stale_id = existing_file.get("_id") or existing_file.get("id")
                if stale_id:
                    logger.info(f"Removing stale file {location} (expected {url})")
                    api_delete_file(str(stale_id), CLI_config)
            else:
                existing_files[location] = existing_file
    else:
        logger.warning(
            f"Failed to retrieve existing files for data collection {data_collection.id}."
        )

    metadata = _probe_url_metadata(url)
    now_iso = format_timestamp(time.time())
    file_hash = _url_identity_hash(url, metadata)

    url_basename = os.path.basename(urlparse(url).path)
    filename = url_basename or "remote-file"

    file_id = None
    scan_result = None
    if url in existing_files:
        file_id = existing_files[url]["_id"]
        if existing_files[url].get("file_hash") == file_hash and not update_files:
            scan_result = {"result": "failure", "reason": "skipped"}
        else:
            scan_result = {"result": "success", "reason": "updated"}
    if scan_result is None:
        scan_result = {"result": "success", "reason": "added"}

    workflow_config_id = (
        PyObjectId(workflow.config.id) if workflow.config and workflow.config.id else PyObjectId()
    )
    workflow_run = WorkflowRun(
        workflow_id=PyObjectId(workflow.id),
        run_tag=f"{data_collection.data_collection_tag}-url-scan",
        files_id=[],
        workflow_config_id=workflow_config_id,
        run_location=url,
        creation_time=now_iso,
        last_modification_time=now_iso,
        run_hash="",
        permissions=permissions,
    )

    file_instance = File(
        id=PyObjectId(file_id) if file_id else PyObjectId(),
        filename=filename,
        file_location=url,
        creation_time=now_iso,
        modification_time=now_iso,
        file_hash=file_hash,
        filesize=metadata["size"],
        data_collection_id=data_collection.id,
        run_id=workflow_run.id,
        run_tag=workflow_run.run_tag,
        permissions=permissions,
    )

    if scan_result["result"] == "success":
        api_create_files(
            files=[file_instance],
            CLI_config=CLI_config,
            update=scan_result["reason"] == "updated",
        )
        registered = 1
    else:
        registered = 0

    rich_print_checked_statement(
        f"Registered {registered} remote URL for data collection "
        f"{data_collection.data_collection_tag}",
        "info",
    )
    return {"result": "success"}


def _s3_read_client(CLI_config: CLIConfig, url: str | None = None):
    """boto3 client for *reading* user data buckets (scan mode ``s3_prefix``).

    A location on the administrator's public bucket allowlist gets an unsigned
    client: signing with credentials that have no relationship to someone else's
    open bucket only earns a rejection. The allowlist is configuration, so this
    is decided before the client makes any call.

    Otherwise credential precedence mirrors the read/write split in CLIConfig:
    the per-project ``remote_storage_options`` win, then the instance's own
    ``s3_storage``. Anything still missing is left to boto3's default chain
    (env vars, ~/.aws, IAM role) so real AWS deployments work without ever
    putting keys in a config file.
    """
    import boto3

    if url and is_public_s3_location(url):
        from botocore import UNSIGNED
        from botocore.config import Config

        return boto3.client(
            "s3",
            config=Config(signature_version=UNSIGNED),
            region_name=public_s3_region(urlparse(url).netloc),
        )

    remote = CLI_config.remote_storage_options or {}
    # polars storage_options spells the endpoint either way depending on version
    endpoint = remote.get("aws_endpoint_url") or remote.get("endpoint_url")
    key = remote.get("aws_access_key_id")
    secret = remote.get("aws_secret_access_key")
    # ``region`` is what storage_options_for_project (per-project storage
    # config) emits; the other two are the polars/boto3 spellings.
    region = remote.get("aws_region") or remote.get("region_name") or remote.get("region")

    if not key and CLI_config.s3_storage:
        key = CLI_config.s3_storage.aws_access_key_id
        secret = CLI_config.s3_storage.aws_secret_access_key
        endpoint = endpoint or CLI_config.s3_storage.url

    # Passing None lets botocore fall through to its own resolution chain.
    return boto3.client(
        "s3",
        aws_access_key_id=key or None,
        aws_secret_access_key=secret or None,
        endpoint_url=endpoint or None,
        region_name=region or None,
    )


# Keys examined per unit of ``max_files`` before a prefix listing stops asking
# for more pages. Listing is paged lazily, so this bounds the number of list
# calls an API thread can spend on a bucket full of non-matching keys.
S3_PREFIX_KEY_BUDGET_FACTOR = 10


def list_s3_prefix(prefix: str, pattern: str, max_files: int, CLI_config: CLIConfig) -> list[dict]:
    """List objects under an ``s3://`` prefix whose relative key matches ``pattern``.

    ``pattern`` is fnmatch, whose ``*`` also spans ``/`` — that is deliberate:
    it makes ``*.csv`` recurse into sub-prefixes, matching the semantics of the
    local ``recursive`` mode rather than a single directory listing.

    Two bounds, both reported as warnings: matches stop at ``max_files``, and
    no further page is requested once ``max_files * S3_PREFIX_KEY_BUDGET_FACTOR``
    keys have been examined, so a prefix with millions of non-matching keys
    cannot pin the calling thread. A page already fetched is always scanned in
    full, which is why the budget is checked between pages.

    Returns dicts of {url, key, size, etag, last_modified}; raises ValueError on
    a malformed prefix so the caller can surface it as a scan failure.
    """
    import fnmatch

    if not prefix.lower().startswith("s3://"):
        raise ValueError(f"s3_prefix scan needs an s3:// prefix, got '{prefix}'")

    without_scheme = prefix[len("s3://") :]
    bucket, _, key_prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"s3_prefix '{prefix}' has no bucket")

    client = _s3_read_client(CLI_config, url=prefix)
    paginator = client.get_paginator("list_objects_v2")

    key_budget = max_files * S3_PREFIX_KEY_BUDGET_FACTOR
    examined = 0
    budget_exhausted = False
    matches: list[dict] = []
    truncated = False
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []):
            examined += 1
            key = obj["Key"]
            # Console-created "folders" are zero-byte keys ending in / — never data.
            if key.endswith("/"):
                continue
            relative = key[len(key_prefix) :].lstrip("/") if key_prefix else key
            if not fnmatch.fnmatch(relative, pattern) and not fnmatch.fnmatch(
                os.path.basename(key), pattern
            ):
                continue
            if len(matches) >= max_files:
                truncated = True
                break
            matches.append(
                {
                    "url": f"s3://{bucket}/{key}",
                    "key": key,
                    "relative": relative,
                    "size": obj.get("Size", -1),
                    "etag": (obj.get("ETag") or "").strip('"'),
                    "last_modified": obj.get("LastModified"),
                }
            )
        if truncated:
            break
        # ``IsTruncated`` is set on every list_objects_v2 page; a listing that
        # ends exactly at the budget is complete and must not warn.
        if examined >= key_budget and page.get("IsTruncated", True):
            budget_exhausted = True
            break

    if truncated:
        # Never let a cap silently look like "that's all there is".
        rich_print_checked_statement(
            f"s3_prefix scan hit the max_files cap ({max_files}) under {prefix} — "
            "results are truncated. Narrow `pattern` or raise `max_files`.",
            "warning",
        )
    if budget_exhausted:
        message = (
            f"s3_prefix scan examined {examined} keys under {prefix} and stopped at the "
            f"budget of {key_budget} keys (max_files {max_files} x "
            f"{S3_PREFIX_KEY_BUDGET_FACTOR}) before the end of the listing; results are "
            f"partial ({len(matches)} matched). Narrow `prefix` or `pattern`, or raise "
            "`max_files`."
        )
        logger.warning(message)
        rich_print_checked_statement(message, "warning")
    return matches


def scan_s3_prefix_for_data_collection(
    workflow: Workflow,
    data_collection: "DataCollection",
    CLI_config: CLIConfig,
    permissions: Permission,
    update_files: bool,
) -> dict:
    """Register every object under an ``s3://`` prefix matching the DC's pattern.

    The remote counterpart of the recursive scan. Unlike manifest mode the
    listing carries real sizes and ETags, so the identity hash is content-aware:
    a re-uploaded object changes its ETag and is picked up as "updated".
    """
    import time

    scan_params = data_collection.config.scan.scan_parameters  # type: ignore[union-attr]
    prefix = scan_params.prefix  # type: ignore[union-attr]
    pattern = scan_params.pattern  # type: ignore[union-attr]
    id_regex = scan_params.id_regex  # type: ignore[union-attr]

    try:
        objects = list_s3_prefix(
            prefix=prefix,
            pattern=pattern,
            max_files=scan_params.max_files,  # type: ignore[union-attr]
            CLI_config=CLI_config,
        )
    except Exception as exc:
        message = f"S3 prefix listing failed for {prefix}: {exc}"
        logger.error(message)
        return {"result": "error", "message": message}

    if not objects:
        return {
            "result": "error",
            "message": (
                f"No object under '{prefix}' matches pattern '{pattern}' "
                f"for data collection '{data_collection.data_collection_tag}'"
            ),
        }

    compiled_id = re.compile(id_regex) if id_regex else None

    # Stale cleanup: registered locations no longer present under the prefix.
    current_urls = {obj["url"] for obj in objects}
    response = api_get_files_by_dc_id(dc_id=str(data_collection.id), CLI_config=CLI_config)
    existing_files: dict[str, dict] = {}
    if response.status_code == 200:
        for existing_file in response.json() or []:
            location = existing_file["file_location"]
            if location not in current_urls:
                stale_id = existing_file.get("_id") or existing_file.get("id")
                if stale_id:
                    logger.info(f"Removing stale file {location} (absent from {prefix})")
                    api_delete_file(str(stale_id), CLI_config)
            else:
                existing_files[location] = existing_file
    else:
        logger.warning(
            f"Failed to retrieve existing files for data collection {data_collection.id}."
        )

    now_iso = format_timestamp(time.time())
    workflow_config_id = (
        PyObjectId(workflow.config.id) if workflow.config and workflow.config.id else PyObjectId()
    )
    workflow_run = WorkflowRun(
        workflow_id=PyObjectId(workflow.id),
        run_tag=f"{data_collection.data_collection_tag}-s3-prefix-scan",
        files_id=[],
        workflow_config_id=workflow_config_id,
        run_location=prefix,
        creation_time=now_iso,
        last_modification_time=now_iso,
        run_hash="",
        permissions=permissions,
    )

    to_add: list[File] = []
    to_update: list[File] = []
    skipped = 0
    unmatched_id = 0
    for obj in objects:
        url = obj["url"]
        file_hash = hashlib.sha256(f"{url}|{obj['etag']}".encode()).hexdigest()
        existing = existing_files.get(url)
        if existing and existing.get("file_hash") == file_hash and not update_files:
            skipped += 1
            continue

        entity_id = None
        if compiled_id:
            found = compiled_id.search(obj["relative"]) or compiled_id.search(
                os.path.basename(obj["key"])
            )
            if found:
                entity_id = found.group(1)
            else:
                unmatched_id += 1

        modified = obj.get("last_modified")
        modified_iso = format_timestamp(modified.timestamp()) if modified else now_iso

        file_instance = File(
            id=PyObjectId(existing["_id"]) if existing else PyObjectId(),
            filename=os.path.basename(obj["key"]) or "remote-file",
            file_location=url,
            creation_time=modified_iso,
            modification_time=modified_iso,
            file_hash=file_hash,
            filesize=obj.get("size", -1),
            data_collection_id=data_collection.id,
            run_id=workflow_run.id,
            run_tag="remote",
            permissions=permissions,
            manifest_id=entity_id,
        )
        (to_update if existing else to_add).append(file_instance)

    if to_add:
        api_create_files(files=to_add, CLI_config=CLI_config, update=False)
    if to_update:
        api_create_files(files=to_update, CLI_config=CLI_config, update=True)

    if unmatched_id:
        # Silent None ids would break cross-DC joins at render time, not here.
        rich_print_checked_statement(
            f"{unmatched_id} object(s) under {prefix} did not match id_regex "
            f"'{id_regex}' — they carry no join id.",
            "warning",
        )

    rich_print_checked_statement(
        f"S3 prefix scan for {data_collection.data_collection_tag}: "
        f"{len(to_add)} added, {len(to_update)} updated, {skipped} unchanged",
        "info",
    )
    return {"result": "success", "added": len(to_add), "updated": len(to_update)}


def fetch_manifest(manifest_url: str, field_map: dict | None = None):
    """Load and parse a Data Manifest from a local path or an http(s) URL.

    Format is decided by extension (.json vs anything else = CSV), falling
    back to content sniffing. s3:// manifests are not supported yet (phase 2
    covers file paths and https; the RFC tracks s3 manifests).

    Remote manifests are re-fetched on every scan, including scans the API
    runs in-process, so server context goes through the SSRF gateway
    (``RemoteURLRejected`` propagates). CLI context fetches directly with the
    same redirect and size caps.
    """
    from depictio.models.models.manifest import DataManifest, is_remote_url

    if is_remote_url(manifest_url):
        if manifest_url.lower().startswith("s3://"):
            raise ValueError(
                "s3:// manifest locations are not supported yet — "
                "serve the manifest over https or use a local path."
            )
        if is_server_context():
            text = fetch_validated_text(manifest_url)
        else:
            text = direct_fetch_text(manifest_url)
    else:
        if not os.path.exists(manifest_url):
            raise ValueError(f"Manifest '{manifest_url}' does not exist.")
        with open(manifest_url) as fh:
            text = fh.read()

    stripped = text.lstrip()
    looks_json = manifest_url.endswith(".json") or stripped.startswith(("{", "["))
    if looks_json:
        return DataManifest.from_json(text, source=manifest_url, field_map=field_map)
    return DataManifest.from_csv(text, source=manifest_url, field_map=field_map)


def scan_manifest_for_data_collection(
    workflow: Workflow,
    data_collection: "DataCollection",
    CLI_config: CLIConfig,
    permissions: Permission,
    update_files: bool,
) -> dict:
    """Register the manifest entries matching this DC's manifest_type.

    One File per manifest row: file_location = the entry URL, run_tag = the
    entry's run (or "remote"), manifest_id = the entry's canonical ID — read
    back as the `depictio_manifest_id` column at aggregation time.
    """
    import time

    scan_params = data_collection.config.scan.scan_parameters  # type: ignore[union-attr]
    field_map = {
        "id": scan_params.id_field,  # type: ignore[union-attr]
        "type": scan_params.type_field,  # type: ignore[union-attr]
        "url": scan_params.url_field,  # type: ignore[union-attr]
    }
    if scan_params.run_field:  # type: ignore[union-attr]
        field_map["run"] = scan_params.run_field  # type: ignore[union-attr]
    manifest = fetch_manifest(scan_params.manifest_url, field_map=field_map)  # type: ignore[union-attr]

    entries = manifest.entries_for_type(scan_params.manifest_type)  # type: ignore[union-attr]
    if not entries:
        return {
            "result": "error",
            "message": (
                f"Manifest has no entries of type '{scan_params.manifest_type}' "  # type: ignore[union-attr]
                f"(available: {sorted(manifest.types())})"
            ),
        }

    # Existing-file lookup + stale cleanup: any registered location no longer
    # present in the manifest for this type is dropped.
    manifest_urls = {entry.url for entry in entries}
    response = api_get_files_by_dc_id(dc_id=str(data_collection.id), CLI_config=CLI_config)
    existing_files: dict[str, dict] = {}
    if response.status_code == 200:
        for existing_file in response.json() or []:
            location = existing_file["file_location"]
            if location not in manifest_urls:
                stale_id = existing_file.get("_id") or existing_file.get("id")
                if stale_id:
                    logger.info(f"Removing stale file {location} (absent from manifest)")
                    api_delete_file(str(stale_id), CLI_config)
            else:
                existing_files[location] = existing_file
    else:
        logger.warning(
            f"Failed to retrieve existing files for data collection {data_collection.id}."
        )

    now_iso = format_timestamp(time.time())
    workflow_config_id = (
        PyObjectId(workflow.config.id) if workflow.config and workflow.config.id else PyObjectId()
    )
    workflow_run = WorkflowRun(
        workflow_id=PyObjectId(workflow.id),
        run_tag=f"{data_collection.data_collection_tag}-manifest-scan",
        files_id=[],
        workflow_config_id=workflow_config_id,
        run_location=scan_params.manifest_url,  # type: ignore[union-attr]
        creation_time=now_iso,
        last_modification_time=now_iso,
        run_hash="",
        permissions=permissions,
    )

    to_add: list[File] = []
    to_update: list[File] = []
    skipped = 0
    for entry in entries:
        file_hash = hashlib.sha256(f"{entry.url}|{entry.id}".encode()).hexdigest()
        existing = existing_files.get(entry.url)
        if existing and existing.get("file_hash") == file_hash and not update_files:
            skipped += 1
            continue
        file_instance = File(
            id=PyObjectId(existing["_id"]) if existing else PyObjectId(),
            filename=os.path.basename(entry.url.split("?", 1)[0]) or "remote-file",
            file_location=entry.url,
            creation_time=now_iso,
            modification_time=now_iso,
            file_hash=file_hash,
            filesize=-1,
            data_collection_id=data_collection.id,
            run_id=workflow_run.id,
            run_tag=entry.run or "remote",
            permissions=permissions,
            manifest_id=entry.id,
        )
        (to_update if existing else to_add).append(file_instance)

    if to_add:
        api_create_files(files=to_add, CLI_config=CLI_config, update=False)
    if to_update:
        api_create_files(files=to_update, CLI_config=CLI_config, update=True)

    rich_print_checked_statement(
        f"Manifest scan for {data_collection.data_collection_tag}: "
        f"{len(to_add)} added, {len(to_update)} updated, {skipped} unchanged",
        "info",
    )
    return {"result": "success", "added": len(to_add), "updated": len(to_update)}


def scan_files_for_data_collection(
    workflow: Workflow,
    data_collection_id: str,
    CLI_config: CLIConfig,
    command_parameters: dict,
) -> dict:
    """
    Scan files for a given data collection of a workflow.
    This function now only handles single file mode. For aggregate mode, use scan_files_for_workflow.
    """
    # Parse the command parameters
    update_files = command_parameters.get("sync_files", False)
    sync_changed = command_parameters.get("sync_changed", False)
    dry_run = command_parameters.get("dry_run", False)

    workflow_id = workflow.id

    # Generate permissions for the files
    user_base = CLI_config.user.model_dump()
    user_base.pop("token")
    user_base = UserBase.from_mongo(user_base)
    permissions = Permission(owners=[user_base])

    # Retrieve workflow and data collection details
    data_collection = next(
        (dc for dc in workflow.data_collections if str(dc.id) == data_collection_id),
        None,
    )
    if data_collection is None:
        error_msg = (
            f"Data collection {data_collection_id} not found in workflow {workflow.workflow_tag}."
        )
        # Raised to the scan step, whose ✗ line prints it.
        logger.debug(error_msg)
        raise ValueError(error_msg)

    # Only handle single-file, url, s3_prefix and manifest modes here
    if not data_collection.config.scan or data_collection.config.scan.mode.lower() not in (
        "single",
        "url",
        "s3_prefix",
        "manifest",
    ):
        raise ValueError(
            "This function only handles single file mode. Use scan_files_for_workflow for aggregate mode."
        )

    if data_collection.config.scan.mode.lower() == "s3_prefix":
        return scan_s3_prefix_for_data_collection(
            workflow=workflow,
            data_collection=data_collection,
            CLI_config=CLI_config,
            permissions=permissions,
            update_files=update_files,
        )

    if data_collection.config.scan.mode.lower() == "url":
        return scan_url_for_data_collection(
            workflow=workflow,
            data_collection=data_collection,
            CLI_config=CLI_config,
            permissions=permissions,
            update_files=update_files,
        )

    if data_collection.config.scan.mode.lower() == "manifest":
        return scan_manifest_for_data_collection(
            workflow=workflow,
            data_collection=data_collection,
            CLI_config=CLI_config,
            permissions=permissions,
            update_files=update_files,
        )

    # Check for the file's existence in the DB
    response = api_get_files_by_dc_id(dc_id=str(data_collection.id), CLI_config=CLI_config)
    if response.status_code == 200:
        existing_files = response.json()
        existing_files_reformated = (
            {existing_file["file_location"]: existing_file for existing_file in existing_files}
            if existing_files
            else {}
        )

        # Clean up stale files whose paths no longer match the current scan config
        # This happens when re-running with a different template or data_root
        current_file_path = data_collection.config.scan.scan_parameters.filename
        if existing_files_reformated:
            stale_files = [
                f for loc, f in existing_files_reformated.items() if loc != current_file_path
            ]
            for stale_file in stale_files:
                stale_id = stale_file.get("_id") or stale_file.get("id")
                if stale_id:
                    logger.info(
                        f"Removing stale file {stale_file['file_location']} "
                        f"(expected {current_file_path})"
                    )
                    if not dry_run:
                        api_delete_file(str(stale_id), CLI_config)
                    del existing_files_reformated[stale_file["file_location"]]
    else:
        existing_files_reformated = {}
        logger.warning(
            f"Failed to retrieve existing files for data collection {data_collection_id}."
        )

    # Single file scan logic (unchanged)
    if not data_collection.config.scan:
        logger.error(
            f"Data collection {data_collection.data_collection_tag} has no scan configuration"
        )
        return {"result": "error", "message": "No scan configuration found"}

    file_path = data_collection.config.scan.scan_parameters.filename

    workflow_config_id = (
        PyObjectId(workflow.config.id) if workflow.config and workflow.config.id else PyObjectId()
    )

    workflow_run = WorkflowRun(
        workflow_id=PyObjectId(workflow_id),
        run_tag=f"{data_collection.data_collection_tag}-single-file-scan",
        files_id=[],
        workflow_config_id=workflow_config_id,
        run_location=os.path.dirname(file_path),
        creation_time=format_timestamp(os.path.getctime(file_path)),
        last_modification_time=format_timestamp(os.path.getmtime(file_path)),
        run_hash="",
        permissions=permissions,
    )

    scan_file_result = process_files(
        path=file_path,
        run=workflow_run,
        data_collection=data_collection,
        existing_files=existing_files_reformated,
        permissions=permissions,
        update_files=update_files,
        skip_regex=True,
        sync_changed=sync_changed,
    )

    # ``result`` already encodes whether a file should be uploaded: added
    # always, changed under --sync-changed, updated under --sync-files.
    files = [sc.file for sc in scan_file_result if sc.scan_result["result"] == "success"]

    if files:
        if dry_run:
            rich_print_checked_statement(
                f"[dry-run] Would register {len(files)} file(s) for "
                f"{escape(data_collection.data_collection_tag)}",
                "info",
            )
        else:
            api_create_files(
                files=files, CLI_config=CLI_config, update=update_files or sync_changed
            )

    rich_print_checked_statement(
        f"Scanned {len(files)} file(s) for data collection "
        f"{escape(data_collection.data_collection_tag)}",
        "info",
    )
    return {"result": "success"}


def scan_project_files(
    project_config,
    CLI_config: CLIConfig,
    workflow_name: str | None = None,
    data_collection_tag: str | None = None,
    command_parameters: dict | None = None,
) -> dict:
    """
    Unified function to scan files for a project with optional filtering.
    This function contains the main scanning logic that can be used by both
    independent commands and the integrated run command.

    Args:
        project_config: The project configuration object
        CLI_config: CLI configuration containing API URL and credentials
        workflow_name: Optional workflow name to filter by
        data_collection_tag: Optional data collection tag to filter by
        command_parameters: Command parameters dict

    Returns:
        dict: Results summary
    """
    if command_parameters is None:
        command_parameters = {}

    # The state cache is keyed on (server, project) and invalidated by the
    # project hash, so both have to reach scan_files_for_workflow. They are not
    # on Workflow, only on the project, so pass them through the parameter dict
    # rather than threading two more arguments through every call site.
    command_parameters = {
        **command_parameters,
        "project_id": str(project_config.id),
        "project_hash": getattr(project_config, "hash", None),
    }

    rich_print_checked_statement(
        f"Scanning Project: [italic]'{escape(str(project_config.name))}'[/italic]", "info"
    )

    # Filter workflows if specific workflow_name is provided
    workflows_to_scan = project_config.workflows
    if workflow_name:
        workflows_to_scan = [w for w in workflows_to_scan if w.workflow_tag == workflow_name]
        if not workflows_to_scan:
            raise Exception(f"Workflow '{workflow_name}' not found in project")
    # A tag no workflow has used to be a warning, and every collection was then
    # scanned; a workflow without it is just not the one asked for.
    if data_collection_tag:
        known = [dc.data_collection_tag for w in workflows_to_scan for dc in w.data_collections]
        if data_collection_tag not in known:
            raise Exception(
                f"Data collection '{data_collection_tag}' not found in project. "
                f"Known: {', '.join(known) or 'none'}"
            )

    total_runs_scanned = 0
    # Merged across workflows. A project-wide signal is what the process step
    # needs, since it iterates workflows itself.
    changed_dcs: dict[str, list[str]] = {}
    covered_dcs: set[str] = set()
    removed_runs: set[str] = set()
    signal_complete = True

    for workflow in workflows_to_scan:
        rich_print_checked_statement(
            f" ↪ Scanning Workflow: [italic]'{escape(workflow.workflow_tag)}'[/italic]", "info"
        )

        # Filter data collections if specific data_collection_tag is provided
        data_collections_to_scan = workflow.data_collections
        logger.info(
            f"Found {len(data_collections_to_scan)} data collections in workflow '{workflow.workflow_tag}'"
        )
        if data_collection_tag:
            data_collections_to_scan = [
                dc
                for dc in data_collections_to_scan
                if dc.data_collection_tag == data_collection_tag
            ]
            if not data_collections_to_scan:
                logger.info(
                    f"Workflow '{workflow.workflow_tag}' has no data collection "
                    f"'{data_collection_tag}': skipped"
                )
                continue

        # Group data collections by scan mode
        aggregate_data_collections = [
            dc
            for dc in data_collections_to_scan
            if dc.config.scan and dc.config.scan.mode.lower() == "recursive"
        ]
        single_data_collections = [
            dc
            for dc in data_collections_to_scan
            if dc.config.scan and dc.config.scan.mode.lower() == "single"
        ]
        # Remote acquisition modes: no filesystem walk, one synthetic File
        # record set per DC (see scan_url/scan_s3_prefix/scan_manifest_for_data_collection).
        remote_data_collections = [
            dc
            for dc in data_collections_to_scan
            if dc.config.scan and dc.config.scan.mode.lower() in ("url", "s3_prefix", "manifest")
        ]
        multiqc_data_collections = [
            dc
            for dc in data_collections_to_scan
            if dc.config.type.lower() == "multiqc" and not dc.config.scan
        ]
        # Note: Image DCs are now processed as single/aggregate (like Table DCs)
        # They have delta tables and scan configs, so no special handling needed

        if multiqc_data_collections or remote_data_collections:
            parts = [
                f"{len(aggregate_data_collections)} aggregate",
                f"{len(single_data_collections)} single",
            ]
            if remote_data_collections:
                parts.append(f"{len(remote_data_collections)} remote (url/manifest)")
            if multiqc_data_collections:
                parts.append(f"{len(multiqc_data_collections)} MultiQC")
            rich_print_checked_statement(
                f"  ↪ Found {', '.join(parts)} data collections",
                "info",
            )
        else:
            rich_print_checked_statement(
                f"  ↪ Found {len(aggregate_data_collections)} aggregate and {len(single_data_collections)} single data collections",
                "info",
            )

        # Scan aggregate data collections together (new workflow-centric approach)
        if aggregate_data_collections:
            # Print info for each data collection being scanned
            for dc in aggregate_data_collections:
                scan_mode = dc.config.scan.mode.title() if dc.config.scan else "No scan config"
                rich_print_checked_statement(
                    f"  ↪ Scanning Data Collection: [italic]'{escape(dc.data_collection_tag)}'[/italic] - type {dc.config.type} - metatype {scan_mode}",
                    "info",
                )

            # Scan all aggregate data collections in one pass
            scan_result = scan_files_for_workflow(
                workflow=workflow,
                data_collections=aggregate_data_collections,
                CLI_config=CLI_config,
                command_parameters=command_parameters,
            )

            if scan_result["result"] != "success":
                raise Exception(
                    f"Failed to scan aggregate data collections for workflow {workflow.workflow_tag}"
                )

            total_runs_scanned += scan_result.get("runs_scanned", 0)

            for dc_id, run_tags in (scan_result.get("changed_dcs") or {}).items():
                changed_dcs.setdefault(dc_id, []).extend(run_tags)
            covered_dcs.update(scan_result.get("covered_dcs") or [])
            removed_runs.update(scan_result.get("removed_runs") or [])
            signal_complete = signal_complete and bool(scan_result.get("complete"))

        # Scan single data collections individually (existing approach)
        for dc in single_data_collections:
            scan_mode = dc.config.scan.mode.title() if dc.config.scan else "No scan config"
            rich_print_checked_statement(
                f"  ↪ Scanning Data Collection: [italic]'{escape(dc.data_collection_tag)}'[/italic] - type {dc.config.type} - metatype {scan_mode}",
                "info",
            )

            scan_result = scan_files_for_data_collection(
                workflow=workflow,
                data_collection_id=str(dc.id),
                CLI_config=CLI_config,
                command_parameters=command_parameters,
            )

            if scan_result["result"] != "success":
                raise Exception(f"Failed to scan data collection {dc.data_collection_tag}")

        # Scan remote (url/manifest) data collections individually — same path
        # as single DCs; scan_files_for_data_collection dispatches on mode.
        for dc in remote_data_collections:
            scan_mode = dc.config.scan.mode.title() if dc.config.scan else "No scan config"
            rich_print_checked_statement(
                f"  ↪ Scanning Data Collection: [italic]'{dc.data_collection_tag}'[/italic] - type {dc.config.type} - metatype {scan_mode}",
                "info",
            )

            scan_result = scan_files_for_data_collection(
                workflow=workflow,
                data_collection_id=str(dc.id),
                CLI_config=CLI_config,
                command_parameters=command_parameters,
            )

            if scan_result["result"] != "success":
                raise Exception(f"Failed to scan data collection {dc.data_collection_tag}")

        # Handle MultiQC data collections (no file scanning needed)
        for dc in multiqc_data_collections:
            rich_print_checked_statement(
                f"  ↪ Scanning Data Collection: [italic]'{escape(dc.data_collection_tag)}'[/italic] - type {dc.config.type} - metatype MultiQC (no file scanning needed)",
                "info",
            )
            # MultiQC collections don't need file scanning - they work with existing parquet files
            # The actual processing happens in Step 6 (data processing)

        # Note: Image DCs are now processed in single/aggregate_data_collections
        # They have delta tables and are scanned like Table DCs

        rich_print_checked_statement(
            f"Workflow {escape(workflow.workflow_tag)} processed successfully", "success"
        )

    return {
        "result": "success",
        "total_runs_scanned": total_runs_scanned,
        "changed_dcs": {dc_id: sorted(set(tags)) for dc_id, tags in changed_dcs.items()},
        "covered_dcs": sorted(covered_dcs),
        "removed_runs": sorted(removed_runs),
        "complete": signal_complete,
    }


# Legacy functions for backwards compatibility
def scan_run(
    run_location: str,
    run_tag: str,
    workflow_config: WorkflowConfig,
    data_collection: DataCollection,
    workflow_id: ObjectId,
    existing_run: WorkflowRun | None,
    existing_files_reformated: dict,
    CLI_config: CLIConfig,
    permissions: Permission,
    rescan_folders: bool = False,
    update_files: bool = False,
) -> WorkflowRun | None:
    """
    Legacy function - kept for backwards compatibility.
    Use scan_run_for_multiple_data_collections for new code.
    """
    logger.warning(
        "Using legacy scan_run function. Consider using scan_run_for_multiple_data_collections."
    )
    return scan_run_for_multiple_data_collections(
        run_location=run_location,
        run_tag=run_tag,
        workflow_config=workflow_config,
        data_collections=[data_collection],  # Wrap single DC in list
        all_existing_files={str(data_collection.id): existing_files_reformated},
        workflow_id=workflow_id,
        existing_run=existing_run,
        CLI_config=CLI_config,
        permissions=permissions,
        rescan_folders=rescan_folders,
        update_files=update_files,
    )


def scan_parent_folder(
    parent_runs_location: str,
    workflow_config: WorkflowConfig,
    data_collection: DataCollection,
    data_location: WorkflowDataLocation,
    existing_files_reformated: dict,
    workflow_id: ObjectId,
    CLI_config: CLIConfig,
    permissions: Permission,
    structure: str = "sequencing-runs",
    rescan_folders: bool = False,
    update_files: bool = False,
) -> list[WorkflowRun | None]:
    """
    Legacy function - kept for backwards compatibility.
    Use scan_files_for_workflow for new code.
    """
    logger.warning(
        "Using legacy scan_parent_folder function. Consider using scan_files_for_workflow."
    )

    # Create a temporary workflow object to use the new function
    from depictio.models.models.base import PyObjectId
    from depictio.models.models.workflows import Workflow, WorkflowEngine

    temp_workflow = Workflow(
        id=PyObjectId(workflow_id),
        name="temp",
        engine=WorkflowEngine(name="temp"),
        data_collections=[data_collection],
        data_location=data_location,
        config=workflow_config,
    )

    command_parameters = {
        "rescan_folders": rescan_folders,
        "sync_files": update_files,
        "rich_tables": False,
    }

    scan_files_for_workflow(
        workflow=temp_workflow,
        data_collections=[data_collection],
        CLI_config=CLI_config,
        command_parameters=command_parameters,
    )

    # Return empty list for backwards compatibility
    return []
