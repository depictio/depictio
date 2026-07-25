import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from bson import ObjectId
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

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
    construct_full_regex,
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
    "skipped_files",
    "other_failure_files",
)

#: File-id buckets persisted on each ``WorkflowRunScan``. Deliberately narrower
#: than SCAN_STAT_KEYS: unchanged files are the bulk of a steady-state scan and
#: listing their ids would bloat the run document for no benefit.
SCAN_FILE_ID_BUCKETS: tuple[str, ...] = (
    "updated_files",
    "new_files",
    "changed_files",
    "skipped_files",
    "other_failure_files",
)

# Supported image extensions for S3 verification
SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".tiff",
    ".tif",
}


def _verify_s3_images(s3_base_folder: str, CLI_config: CLIConfig) -> dict:
    """
    Verify images exist at the specified S3 location.

    Args:
        s3_base_folder: S3 path (e.g., s3://bucket/path/to/images/)
        CLI_config: CLI configuration with S3 credentials

    Returns:
        dict with 'count' of images found and 'sample' list of first few paths
    """
    import boto3

    try:
        # Parse S3 path
        if not s3_base_folder.startswith("s3://"):
            return {"count": 0, "sample": [], "error": "Invalid S3 path"}

        s3_parts = s3_base_folder[5:].split("/", 1)
        bucket = s3_parts[0]
        prefix = s3_parts[1] if len(s3_parts) > 1 else ""

        # Initialize S3 client
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=CLI_config.s3_storage.aws_access_key_id,
            aws_secret_access_key=CLI_config.s3_storage.aws_secret_access_key,
            endpoint_url=CLI_config.s3_storage.url,
        )

        # List objects with the prefix
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix, PaginationConfig={"MaxItems": 100})

        image_count = 0
        sample_images: list[str] = []

        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Check if it's an image file
                ext = "." + key.rsplit(".", 1)[-1].lower() if "." in key else ""
                if ext in SUPPORTED_IMAGE_EXTENSIONS:
                    image_count += 1
                    if len(sample_images) < 5:
                        sample_images.append(key)

        return {"count": image_count, "sample": sample_images}

    except Exception as e:
        logger.warning(f"Failed to verify S3 images at {s3_base_folder}: {e}")
        return {"count": 0, "sample": [], "error": str(e)}


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
        if not dc.config.scan or not hasattr(dc.config.scan.scan_parameters, "regex_config"):
            logger.warning(
                f"Data collection {dc.data_collection_tag} does not have scan config or regex_config (likely single-file scan or MultiQC)"
            )
            continue

        regex_config = dc.config.scan.scan_parameters.regex_config
        full_regex = (
            construct_full_regex(regex=regex_config)  # type: ignore[invalid-argument-type]
            if getattr(regex_config, "wildcards", False)
            else regex_config.pattern  # type: ignore[unresolved-attribute]
        )
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

            # Check regex match against basename first. ``match_name``/``rel_path``
            # are the walked names rather than the symlink-resolved ones, matching
            # what this loop compared before.
            match, _ = regex_match(scanned.match_name, full_regex)
            if not match:
                # If the pattern contains path separators (e.g., "variants/bowtie2/..."),
                # try matching against the relative path from the run directory
                if "/" in full_regex:
                    match, _ = regex_match(scanned.rel_path, full_regex)
                if not match:
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
                        f"for {dc.data_collection_tag}",
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
                    failed = [r for r in responses if r is None or r.status_code != 200]
                    if failed:
                        codes = sorted(
                            {"transport" if r is None else str(r.status_code) for r in failed}
                        )
                        raise RuntimeError(
                            f"{len(failed)} of {len(responses)} file batches failed for "
                            f"'{dc.data_collection_tag}' (HTTP {', '.join(codes)}). "
                            "Files are only partially registered — re-run the scan."
                        )

            # Handle missing files
            missing_files_location = set(existing_files_for_dc.keys()) - set(
                [str(sc.file.file_location) for sc in dc_file_scan_results]
            )
            missing_files = [
                str(existing_files_for_dc[file_location]["_id"])
                for file_location in missing_files_location
            ]

            if missing_files and update_files:
                logger.info(f"Files to remove for DC {dc.data_collection_tag}: {missing_files}")
                if dry_run:
                    rich_print_checked_statement(
                        f"[dry-run] Would remove {len(missing_files)} stale file(s) "
                        f"from {dc.data_collection_tag}",
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
        }

        # Calculate missing files count
        missing_files_count = (
            len(existing_files_for_dc) - len(dc_file_scan_results) if existing_files_for_dc else 0
        )

        # Store stats for this data collection - THIS IS KEY!
        dc_stats[dc.data_collection_tag] = {
            "total_files": len(dc_file_scan_results),
            "updated_files": len(old_updated_files),
            "new_files": len(new_files),
            "changed_files": len(files_changed),
            "unchanged_files": len(files_unchanged),
            "missing_files": missing_files_count if not update_files else 0,
            "deleted_files": missing_files_count if update_files else 0,
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

    # Combine file IDs from all data collections
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

    Resolving this up front — before any file registry is fetched — is what
    makes a no-op scan cheap: with nothing pending there is nothing to compare
    against, so the per-data-collection ``/files/list`` calls are skipped
    entirely.
    """

    location: str
    structure: str
    runs: list[_PendingRun]


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
                "📋 Loading existing files from database", total=len(data_collections)
            )

            for dc in data_collections:
                # Format data collection tag to consistent width to avoid line changes
                formatted_dc_tag = f"{dc.data_collection_tag:<25}"[
                    :25
                ]  # Left-align and pad/truncate to 25 chars
                # Total description length: 45 chars to match run scanning
                progress.update(task_id, description=f"📋 Loading files for {formatted_dc_tag}")
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

    1. The run is already registered and no rescan was asked for — free, no
       filesystem access at all.
    2. A rescan *was* asked for, but the cached signature says the run's tree is
       byte-for-byte what it was at the last successful scan. This costs one
       walk, which is far less than the regex pass, ``File`` construction and
       registry fetch it avoids. The walk is handed forward so the scan itself
       does not repeat it.
    """
    pending: list[_PendingLocation] = []
    structure = workflow.data_location.structure
    workflow_id = str(workflow.id)
    bounds = walk_bounds or _ScanBounds(None, ())

    def _consider(run_location: str, run_tag: str) -> _PendingRun | None:
        """Return the run to scan, or None when it can be skipped."""
        if run_tag in existing_runs and not rescan_folders:
            logger.debug(f"Skipping existing run {run_tag}.")
            return None

        cached = state.run_state(workflow_id, run_tag) if state else None
        if cached is None or run_tag not in existing_runs:
            # Nothing to compare against, or the server has never seen this run:
            # either way the cache cannot authorise a skip.
            return _PendingRun(location=run_location, tag=run_tag)

        scanned = list(
            iter_run_files(run_location, max_depth=bounds.max_depth, ignore=list(bounds.ignore))
        )
        signature = run_signature(scanned)
        if signature == cached.signature and cached.run_location == run_location:
            logger.info(f"Run {run_tag} unchanged since last scan — skipping.")
            return None

        return _PendingRun(location=run_location, tag=run_tag, scanned=scanned, signature=signature)

    for location in locations:
        if not os.path.exists(location):
            raise ValueError(f"The directory '{location}' does not exist.")
        if not os.path.isdir(location):
            raise ValueError(f"'{location}' is not a directory.")

        runs: list[_PendingRun] = []

        if structure == "flat":
            # Treat the provided directory as a single run
            run_tag = os.path.basename(os.path.normpath(location))
            candidate = _consider(location, run_tag)
            if candidate:
                runs.append(candidate)

        elif structure == "sequencing-runs":
            # Each subdirectory that matches the regex is a run
            runs_regex = workflow.data_location.runs_regex
            if not runs_regex:
                logger.error("runs_regex is required for sequencing-runs structure but was None")
                continue

            for run in sorted(os.listdir(location)):
                run_path = os.path.join(location, run)
                if os.path.isdir(run_path) and re.match(runs_regex, run):
                    candidate = _consider(run_path, run)
                    if candidate:
                        runs.append(candidate)

        pending.append(_PendingLocation(location=location, structure=structure, runs=runs))

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
    existing_runs_response = api_get_runs_by_wf_id(wf_id=str(workflow_id), CLI_config=CLI_config)
    logger.info(f"Existing Runs Response: {existing_runs_response}")
    if existing_runs_response.status_code == 200:
        existing_runs = existing_runs_response.json()
        if existing_runs:
            existing_runs_reformated = {
                e["run_tag"]: WorkflowRun.from_mongo(e) for e in existing_runs
            }

    # Get locations from the workflow config
    locations = workflow.data_location.locations
    if not locations:
        rich_print_checked_statement(
            f"No locations configured for workflow {workflow.workflow_tag}.",
            "warning",
        )
        return {"result": "error", "message": "No locations configured"}

    # The state cache can only authorise skipping a rescan; without one, the
    # existing-run check above already short-circuits without touching disk.
    state: ProjectScanState | None = None
    if use_state_cache and rescan_folders and project_id:
        state = load_state(
            CLI_config.api_base_url, project_id, project_hash=project_hash
        ) or ProjectScanState(
            api_base_url=CLI_config.api_base_url,
            project_id=project_id,
            project_hash=project_hash,
        )

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

    # Only pay for the file registry when there is something to compare against.
    # ``rescan_folders`` needs it regardless, for the missing-run cleanup below.
    if pending_total or rescan_folders:
        all_existing_files = _fetch_existing_files(data_collections, CLI_config)
    else:
        logger.info("No new runs detected — skipping the existing-file fetch.")
        all_existing_files = {str(dc.id): {} for dc in data_collections}

    # Scan runs once and collect files for all data collections
    all_workflow_runs = []

    for pending in pending_locations:
        if not pending.runs:
            continue

        logger.info(f"Scanning location: {pending.location}")

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
                f"🔍 Scanning runs in {os.path.basename(pending.location)}"
                if show_bar
                else f"🔍 Scanning single location: {pending.runs[0].tag}",
                total=len(pending.runs) if show_bar else None,
            )

            for candidate in pending.runs:
                if show_bar:
                    # Format run name to consistent width to avoid line changes
                    # Need 29 chars for run name to match total description length of 45 chars
                    formatted_run = f"{candidate.tag:<29}"[:29]
                    progress.update(task_id, description=f"🔍 Scanning run: {formatted_run}")

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
                    existing_run=existing_runs_reformated.get(candidate.tag, None),
                )
                if workflow_run:
                    all_workflow_runs.append(workflow_run)

                if show_bar:
                    progress.advance(task_id)

            if show_bar:
                progress.update(task_id, description="✅ Scanning completed")

    # Handle missing runs if rescanning.
    #
    # This used to sit inside the per-location loop, where it compared the DB
    # against only the runs scanned *so far*. With a single configured location
    # that is equivalent; with several it deleted every run belonging to a
    # location that had not been walked yet.
    if rescan_folders:
        missing_runs_tag = set(existing_runs_reformated.keys()) - set(
            [run.run_tag for run in all_workflow_runs if run]
        )
        missing_runs = [str(existing_runs_reformated[run_tag].id) for run_tag in missing_runs_tag]

        if missing_runs:
            logger.info(f"Runs to remove: {missing_runs}")
            if dry_run:
                rich_print_checked_statement(
                    f"[dry-run] Would remove {len(missing_runs)} run(s) and their files: "
                    f"{missing_runs_tag}",
                    "info",
                )
            else:
                # Index the registry by run once. This used to be a nested scan
                # of every registered file per missing run — O(missing x total)
                # in Python, on top of one blocking round-trip per file.
                files_by_run: defaultdict[str, list[str]] = defaultdict(list)
                for files in all_existing_files.values():
                    for file in files.values():
                        files_by_run[str(file["run_id"])].append(str(file["_id"]))

                orphaned_files = [
                    file_id for run_id in missing_runs for file_id in files_by_run.get(run_id, [])
                ]

                api_delete_runs(missing_runs, CLI_config, concurrency=concurrency)
                api_delete_files(orphaned_files, CLI_config, concurrency=concurrency)

                rich_print_checked_statement(
                    f"Removed {len(missing_runs)} runs and {len(orphaned_files)} related "
                    f"files from the DB : {missing_runs_tag}",
                    "info",
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
                progress.add_task(f"💾 Uploading {len(all_workflow_runs)} run(s) to server")
                api_upsert_runs_batch(all_workflow_runs, CLI_config, rescan_folders)

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
        if rescan_folders:
            state.forget_runs(str(workflow_id), missing_runs_tag)
        save_state(state)

    # Generate single summary table for the entire workflow
    # if all_workflow_runs:
    if rich_tables:
        rich_print_summary_scan_table_enhanced(all_workflow_runs, workflow, show_totals=True)
    else:
        rich_print_data_collection_light(all_workflow_runs, workflow)

    rich_print_checked_statement(
        f"Scanned {len(all_workflow_runs)} runs in workflow {workflow.workflow_tag}",
        "success",
    )

    return {"result": "success", "runs_scanned": len(all_workflow_runs)}


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
        logger.error(error_msg)
        rich_print_checked_statement(error_msg, "error")
        raise ValueError(error_msg)

    # Only handle single file mode here
    if not data_collection.config.scan or data_collection.config.scan.mode.lower() != "single":
        raise ValueError(
            "This function only handles single file mode. Use scan_files_for_workflow for aggregate mode."
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
                f"{data_collection.data_collection_tag}",
                "info",
            )
        else:
            api_create_files(
                files=files, CLI_config=CLI_config, update=update_files or sync_changed
            )

    rich_print_checked_statement(
        f"Scanned {len(files)} file(s) for data collection {data_collection.data_collection_tag}",
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
        f"Scanning Project: [italic]'{project_config.name}'[/italic]", "info"
    )

    # Filter workflows if specific workflow_name is provided
    workflows_to_scan = project_config.workflows
    if workflow_name:
        workflows_to_scan = [w for w in workflows_to_scan if w.workflow_tag == workflow_name]
        if not workflows_to_scan:
            raise Exception(f"Workflow '{workflow_name}' not found in project")

    total_runs_scanned = 0

    for workflow in workflows_to_scan:
        rich_print_checked_statement(
            f" ↪ Scanning Workflow: [italic]'{workflow.workflow_tag}'[/italic]", "info"
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
                rich_print_checked_statement(
                    f"Data collection '{data_collection_tag}' not found in workflow '{workflow.workflow_tag}'",
                    "warning",
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
        multiqc_data_collections = [
            dc
            for dc in data_collections_to_scan
            if dc.config.type.lower() == "multiqc" and not dc.config.scan
        ]
        # Note: Image DCs are now processed as single/aggregate (like Table DCs)
        # They have delta tables and scan configs, so no special handling needed

        if multiqc_data_collections:
            parts = [
                f"{len(aggregate_data_collections)} aggregate",
                f"{len(single_data_collections)} single",
            ]
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
                    f"  ↪ Scanning Data Collection: [italic]'{dc.data_collection_tag}'[/italic] - type {dc.config.type} - metatype {scan_mode}",
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

        # Scan single data collections individually (existing approach)
        for dc in single_data_collections:
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
                f"  ↪ Scanning Data Collection: [italic]'{dc.data_collection_tag}'[/italic] - type {dc.config.type} - metatype MultiQC (no file scanning needed)",
                "info",
            )
            # MultiQC collections don't need file scanning - they work with existing parquet files
            # The actual processing happens in Step 6 (data processing)

        # Note: Image DCs are now processed in single/aggregate_data_collections
        # They have delta tables and are scanned like Table DCs

        rich_print_checked_statement(
            f"Workflow {workflow.workflow_tag} processed successfully", "success"
        )

    return {"result": "success", "total_runs_scanned": total_runs_scanned}


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
