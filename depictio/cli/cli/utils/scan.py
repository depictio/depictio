import os
import re
from datetime import datetime

from bson import ObjectId
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from depictio.cli.cli.utils.api_calls import (
    api_create_files,
    api_delete_file,
    api_delete_run,
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
from depictio.cli.cli_logging import logger
from depictio.models.models.base import PyObjectId
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.files import File, FileScanResult
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import (
    Workflow,
    WorkflowConfig,
    WorkflowDataLocation,
    WorkflowRun,
    WorkflowRunScan,
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

    Returns:
        Optional[File]: A File instance if the file is valid; otherwise, None.
    """

    file_name = os.path.basename(file_location)
    if not skip_regex:
        if full_regex is None:
            raise ValueError("full_regex must be provided unless skip_regex is True")
        match, _ = regex_match(file_name, full_regex)
        if not match:
            # logger.debug(f"File {file_name} does not match regex, skipping.")
            return None

    # Get file details.
    creation_time_float = os.path.getctime(file_location)
    modification_time_float = os.path.getmtime(file_location)
    creation_time_iso = format_timestamp(creation_time_float)
    modification_time_iso = format_timestamp(modification_time_float)
    filesize = os.path.getsize(file_location)
    file_hash = generate_file_hash(file_name, filesize, creation_time_iso, modification_time_iso)
    logger.debug(f"File Hash for {file_name}: {file_hash}")

    scan_result = None
    file_id = None

    logger.debug(f"Existing Files: {existing_files}")

    # Check if the file already exists in the database.
    if existing_files:
        # logger.debug(f"Nb of Existing Files: {len(existing_files)}")
        if any(existing == file_location for existing in list(existing_files.keys())):
            logger.debug(f"File {file_name} already exists in the database.")

            # compare hashes to check if the file has changed
            existing_file = existing_files[file_location]

            if existing_file["file_hash"] == file_hash:
                logger.debug(f"File {file_name} has not changed based on hash since last scan.")
            else:
                logger.debug(f"File {file_name} has changed based on hash since last scan.")

            file_id = existing_files[file_location]["_id"]
            if not update_files:
                logger.debug(f"Skipping existing file {file_name}.")
                scan_result = {"result": "failure", "reason": "skipped"}
            else:
                logger.debug(f"Updating existing file {file_name}.")
                scan_result = {"result": "success", "reason": "updated"}

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
        reason = "added" if file_location not in existing_files else "updated"
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
) -> list[FileScanResult]:
    """
    Scan files from a given directory or a single file path.

    If 'path' is a directory, scan using os.walk.
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
    if not skip_regex and hasattr(data_collection.config.scan.scan_parameters, "regex_config"):
        regex_config = data_collection.config.scan.scan_parameters.regex_config
        full_regex = (
            construct_full_regex(regex=regex_config)  # type: ignore[invalid-argument-type]
            if getattr(regex_config, "wildcards", False)
            else regex_config.pattern  # type: ignore[unresolved-attribute]
        )
        logger.debug(f"Full Regex: {full_regex}")

    if os.path.isdir(path):
        logger.debug(f"Scanning directory: {path}")
        for root, _, files in os.walk(path):
            for file in files:
                file_location = os.path.join(root, file)
                file_instance = scan_single_file(
                    file_location=file_location,
                    run=run,
                    data_collection=data_collection,
                    permissions=permissions,
                    existing_files=existing_files,
                    update_files=update_files,
                    full_regex=full_regex,
                    skip_regex=skip_regex,
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
) -> WorkflowRun | None:
    """
    Scan a single run for multiple data collections simultaneously.
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

    # Scan all files in the run directory
    all_files_in_run = []
    if os.path.isdir(run_location):
        for root, _, files in os.walk(run_location):
            for file in files:
                file_location = os.path.join(root, file)
                all_files_in_run.append(file_location)

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
        if not hasattr(dc.config.scan.scan_parameters, "regex_config"):
            logger.warning(
                f"Data collection {dc.data_collection_tag} does not have regex_config (likely single-file scan)"
            )
            continue

        regex_config = dc.config.scan.scan_parameters.regex_config
        full_regex = (
            construct_full_regex(regex=regex_config)  # type: ignore[invalid-argument-type]
            if getattr(regex_config, "wildcards", False)
            else regex_config.pattern  # type: ignore[unresolved-attribute]
        )
        logger.debug(f"Regex for DC {dc.data_collection_tag}: {full_regex}")

        # Process files that match this data collection's regex
        dc_file_scan_results = []
        for file_location in all_files_in_run:
            file_name = os.path.basename(file_location)

            # Check regex match
            match, _ = regex_match(file_name, full_regex)
            if not match:
                continue

            logger.debug(f"File {file_name} matches DC {dc.data_collection_tag}")

            # Create a temporary run for this DC (needed for file association)
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

            file_scan_result = scan_single_file(
                file_location=file_location,
                run=temp_run,
                data_collection=dc,
                permissions=permissions,
                existing_files=existing_files_for_dc,
                update_files=update_files,
                full_regex=full_regex,
                skip_regex=False,
            )

            if file_scan_result:
                dc_file_scan_results.append(file_scan_result)

        # Process the scan results for this data collection
        old_updated_files = []
        new_files = []
        files_skipped = []
        files_other_failure = []

        if dc_file_scan_results:
            old_updated_files = [
                sc.file.id
                for sc in dc_file_scan_results
                if sc.scan_result["result"] == "success" and sc.scan_result["reason"] == "updated"
            ]
            new_files = [
                sc.file.id
                for sc in dc_file_scan_results
                if sc.scan_result["result"] == "success" and sc.scan_result["reason"] == "added"
            ]
            files_skipped = [
                sc.file.id
                for sc in dc_file_scan_results
                if sc.scan_result["result"] == "failure" and sc.scan_result["reason"] == "skipped"
            ]
            files_other_failure = [
                sc.file.id
                for sc in dc_file_scan_results
                if sc.scan_result["result"] == "failure" and sc.scan_result["reason"] != "skipped"
            ]

            # Get files to upload
            if not update_files:
                files_to_upload = [
                    sc.file
                    for sc in dc_file_scan_results
                    if sc.scan_result["result"] == "success" and sc.scan_result["reason"] == "added"
                ]
            else:
                files_to_upload = [
                    sc.file for sc in dc_file_scan_results if sc.scan_result["result"] == "success"
                ]

            # Upload files for this data collection
            if files_to_upload:
                logger.info(f"Files to add for DC {dc.data_collection_tag}: {len(files_to_upload)}")
                api_create_files(files=files_to_upload, CLI_config=CLI_config, update=update_files)

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
                for file_id in missing_files:
                    api_delete_file(file_id=file_id, CLI_config=CLI_config)

            # Collect all files for this run
            all_processed_files.extend(files_to_upload)

        # Store file IDs for this data collection
        dc_file_ids[dc.data_collection_tag] = {
            "updated_files": old_updated_files,
            "new_files": new_files,
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

    # Generate aggregate stats for the run (sum across all data collections)
    aggregate_stats = {
        "total_files": sum(stats["total_files"] for stats in dc_stats.values()),
        "updated_files": sum(stats["updated_files"] for stats in dc_stats.values()),
        "new_files": sum(stats["new_files"] for stats in dc_stats.values()),
        "missing_files": sum(stats["missing_files"] for stats in dc_stats.values()),
        "deleted_files": sum(stats["deleted_files"] for stats in dc_stats.values()),
        "skipped_files": sum(stats["skipped_files"] for stats in dc_stats.values()),
        "other_failure_files": sum(stats["other_failure_files"] for stats in dc_stats.values()),
    }

    logger.debug(f"Aggregate Stats for run {run_tag}: {aggregate_stats}")

    # Combine file IDs from all data collections
    all_updated_files = []
    all_new_files = []
    all_skipped_files = []
    all_other_failure_files = []

    for dc_tag, file_ids in dc_file_ids.items():
        all_updated_files.extend(file_ids["updated_files"])
        all_new_files.extend(file_ids["new_files"])
        all_skipped_files.extend(file_ids["skipped_files"])
        all_other_failure_files.extend(file_ids["other_failure_files"])

    # Create the WorkflowRunScan with dc_stats
    scan_result = WorkflowRunScan(
        stats=aggregate_stats,
        files_id={
            "updated_files": all_updated_files,
            "new_files": all_new_files,
            "skipped_files": all_skipped_files,
            "other_failure_files": all_other_failure_files,
        },
        dc_stats=dc_stats,  # Make sure this is set!
        scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    logger.debug(f"Created WorkflowRunScan with dc_stats: {scan_result.dc_stats}")

    # Store dc_stats for table display (temporary storage)
    workflow_run._dc_stats_for_display = dc_stats

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
    rich_tables = command_parameters.get("rich_tables", True)

    workflow_id = workflow.id

    # Generate permissions for the files
    user_base = CLI_config.user.model_dump()
    user_base.pop("token")
    user_base = UserBase.from_mongo(user_base)
    logger.debug(f"User: {user_base}")
    permissions = Permission(owners=[user_base])
    logger.debug(f"Permissions: {permissions}")

    # Pre-fetch existing files for ALL data collections with progress indicator
    all_existing_files = {}
    if len(data_collections) > 1:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=None,
        ) as progress:
            task_id = progress.add_task(
                "📋 Loading existing files from database", total=len(data_collections)
            )

            for dc in data_collections:
                progress.update(
                    task_id, description=f"📋 Loading files for {dc.data_collection_tag}"
                )
                response = api_get_files_by_dc_id(dc_id=str(dc.id), CLI_config=CLI_config)
                if response.status_code == 200:
                    existing_files = response.json()
                    dc_files = (
                        {f["file_location"]: f for f in existing_files} if existing_files else {}
                    )
                    all_existing_files[str(dc.id)] = dc_files
                else:
                    all_existing_files[str(dc.id)] = {}
                    logger.warning(f"Failed to retrieve existing files for data collection {dc.id}")
                progress.advance(task_id)
    else:
        # Single data collection - no progress bar needed
        for dc in data_collections:
            response = api_get_files_by_dc_id(dc_id=str(dc.id), CLI_config=CLI_config)
            if response.status_code == 200:
                existing_files = response.json()
                dc_files = {f["file_location"]: f for f in existing_files} if existing_files else {}
                all_existing_files[str(dc.id)] = dc_files
            else:
                all_existing_files[str(dc.id)] = {}
                logger.warning(f"Failed to retrieve existing files for data collection {dc.id}")

    # Pre-allocation of existing runs (shared across all data collections)
    existing_runs_reformated: dict[str, dict] = {}
    existing_runs_response = api_get_runs_by_wf_id(wf_id=str(workflow_id), CLI_config=CLI_config)
    logger.info(f"Existing Runs Response: {existing_runs_response}")
    if existing_runs_response.status_code == 200:
        existing_runs = existing_runs_response.json()
        if existing_runs:
            existing_runs_reformated = {
                e["run_tag"]: WorkflowRun.from_mongo(e) for e in existing_runs
            }

    # Scan runs once and collect files for all data collections
    all_workflow_runs = []

    # Get locations from the workflow config
    locations = workflow.data_location.locations
    if not locations:
        rich_print_checked_statement(
            f"No locations configured for workflow {workflow.workflow_tag}.",
            "warning",
        )
        return {"result": "error", "message": "No locations configured"}

    for location in locations:
        logger.info(f"Scanning location: {location}")

        if not os.path.exists(location):
            raise ValueError(f"The directory '{location}' does not exist.")
        if not os.path.isdir(location):
            raise ValueError(f"'{location}' is not a directory.")

        if workflow.data_location.structure == "flat":
            # Treat the provided directory as a single run
            run_tag = os.path.basename(os.path.normpath(location))
            if run_tag in existing_runs_reformated and not rescan_folders:
                logger.debug(f"Skipping existing run {run_tag}.")
                continue

            if workflow.config is None:
                logger.error(f"Workflow config is None for workflow {workflow_id}")
                continue

            # Show simple spinner for single-location scanning
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=None,
            ) as progress:
                progress.add_task(f"🔍 Scanning single location: {run_tag}")

                workflow_run = scan_run_for_multiple_data_collections(
                    run_location=location,
                    run_tag=run_tag,
                    workflow_config=workflow.config,
                    data_collections=data_collections,
                    all_existing_files=all_existing_files,
                    workflow_id=workflow_id,
                    CLI_config=CLI_config,
                    permissions=permissions,
                    rescan_folders=rescan_folders,
                    update_files=update_files,
                    existing_run=existing_runs_reformated.get(run_tag, None),
                )
                if workflow_run:
                    all_workflow_runs.append(workflow_run)

        elif workflow.data_location.structure == "sequencing-runs":
            # Each subdirectory that matches the regex is a run
            runs_regex = workflow.data_location.runs_regex
            if not runs_regex:
                logger.error("runs_regex is required for sequencing-runs structure but was None")
                continue

            # Collect all valid runs first to show accurate progress
            valid_runs = []
            for run in sorted(os.listdir(location)):
                run_path = os.path.join(location, run)
                if os.path.isdir(run_path) and re.match(runs_regex, run):
                    if run in existing_runs_reformated and not rescan_folders:
                        logger.debug(f"Skipping existing run {run}.")
                        continue
                    valid_runs.append((run_path, run))

            # Process runs with progress bar
            if valid_runs:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    TextColumn("({task.completed}/{task.total} runs)"),
                    console=None,  # Use default console
                ) as progress:
                    task_id = progress.add_task(
                        f"🔍 Scanning runs in {os.path.basename(location)}", total=len(valid_runs)
                    )

                    for run_path, run in valid_runs:
                        if workflow.config is None:
                            logger.error(f"Workflow config is None for workflow {workflow_id}")
                            progress.advance(task_id)
                            continue

                        progress.update(task_id, description=f"🔍 Scanning run: {run}")

                        workflow_run = scan_run_for_multiple_data_collections(
                            run_location=run_path,
                            run_tag=run,
                            workflow_config=workflow.config,
                            data_collections=data_collections,
                            all_existing_files=all_existing_files,
                            workflow_id=workflow_id,
                            CLI_config=CLI_config,
                            permissions=permissions,
                            rescan_folders=rescan_folders,
                            update_files=update_files,
                            existing_run=existing_runs_reformated.get(run, None),
                        )
                        if workflow_run:
                            all_workflow_runs.append(workflow_run)

                        progress.advance(task_id)

                    progress.update(task_id, description="✅ Scanning completed")

        # Handle missing runs if rescanning
        if rescan_folders:
            missing_runs_tag = set(existing_runs_reformated.keys()) - set(
                [run.run_tag for run in all_workflow_runs if run]
            )
            missing_runs = [
                str(existing_runs_reformated[run_tag].id) for run_tag in missing_runs_tag
            ]

            if missing_runs:
                logger.info(f"Runs to remove: {missing_runs}")
                for run_id in missing_runs:
                    api_delete_run(run_id=run_id, CLI_config=CLI_config)
                    # Delete related files
                    for dc_id, files in all_existing_files.items():
                        for file in files.values():
                            if str(file["run_id"]) == run_id:
                                api_delete_file(file_id=str(file["_id"]), CLI_config=CLI_config)
                rich_print_checked_statement(
                    f"Removed {len(missing_runs)} runs and related files from the DB : {missing_runs_tag}",
                    "info",
                )

    # Upsert all runs at once with progress indicator
    if all_workflow_runs:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=None,
        ) as progress:
            progress.add_task(f"💾 Uploading {len(all_workflow_runs)} run(s) to server")
            api_upsert_runs_batch(all_workflow_runs, CLI_config, rescan_folders)

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
    if data_collection.config.scan.mode.lower() != "single":
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
    else:
        existing_files_reformated = {}
        logger.warning(
            f"Failed to retrieve existing files for data collection {data_collection_id}."
        )

    # Single file scan logic (unchanged)
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
    )

    if scan_file_result:
        if not update_files:
            files = [
                sc.file
                for sc in scan_file_result
                if sc.scan_result["result"] == "success" and sc.scan_result["reason"] == "added"
            ]
        else:
            files = [sc.file for sc in scan_file_result if sc.scan_result["result"] == "success"]
    else:
        files = []

    if files:
        api_create_files(files=files, CLI_config=CLI_config, update=update_files)

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
            dc for dc in data_collections_to_scan if dc.config.scan.mode.lower() == "recursive"
        ]
        single_data_collections = [
            dc for dc in data_collections_to_scan if dc.config.scan.mode.lower() == "single"
        ]
        rich_print_checked_statement(
            f"  ↪ Found {len(aggregate_data_collections)} aggregate and {len(single_data_collections)} single data collections",
            "info",
        )

        # Scan aggregate data collections together (new workflow-centric approach)
        if aggregate_data_collections:
            # Print info for each data collection being scanned
            for dc in aggregate_data_collections:
                rich_print_checked_statement(
                    f"  ↪ Scanning Data Collection: [italic]'{dc.data_collection_tag}'[/italic] - type {dc.config.type} - metatype {dc.config.scan.mode.title()}",
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
            rich_print_checked_statement(
                f"  ↪ Scanning Data Collection: [italic]'{dc.data_collection_tag}'[/italic] - type {dc.config.type} - metatype {dc.config.scan.mode.title()}",
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
