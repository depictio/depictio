import collections
import hashlib
import os
import re
from datetime import datetime
from typing import Any, DefaultDict, cast

from bson import ObjectId
from pydantic import validate_call

from depictio.cli.cli.utils.api_calls import (
    api_create_files,
    api_delete_file,
    api_delete_run,
    api_get_files_by_dc_id,
    api_get_runs_by_wf_id,
    api_upsert_runs_batch,
)
from depictio.cli.cli.utils.common import format_timestamp
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
from depictio.models.models.data_collections import DataCollection, Regex
from depictio.models.models.files import File, FileScanResult
from depictio.models.models.users import CLIConfig, Permission, UserBase
from depictio.models.models.workflows import (
    Workflow,
    WorkflowConfig,
    WorkflowDataLocation,
    WorkflowRun,
    WorkflowRunScan,
)


def regex_match(file: File, full_regex: str):
    # Normalize the regex pattern to match both types of path separators
    normalized_regex = full_regex.replace("/", "\\/")
    # logger.debug(f"File: {file}, Full Regex: {full_regex}")
    if re.match(normalized_regex, file):
        logger.debug(f"Matched file - file-based: {file}")
        return True, re.match(normalized_regex, file)
    return False, None


def construct_full_regex(regex=Regex):
    """
    Construct the full regex using the wildcards defined in the config.

    Args:
        regex (Regex): The regex configuration object.
    """
    for wildcard in regex.wildcards:
        logger.debug(f"Wildcard: {wildcard}")
        placeholder = f"{{{wildcard.name}}}"  # e.g. {date}
        regex_pattern = wildcard.wildcard_regex
        files_regex = regex.replace(placeholder, f"({regex_pattern})")
        logger.debug(f"Files Regex: {files_regex}")
    return files_regex


def generate_file_hash(
    filename: str, filesize: int, creation_time: str, modification_time: str
) -> str:
    """
    Generates a hash for the file based on its filename, size, creation time, and modification time.

    Args:
        filename (str): The name of the file.
        filesize (int): The size of the file in bytes.
        creation_time (str): The creation time in ISO format.
        modification_time (str): The modification time in ISO format.
        hash_algo (str): The hashing algorithm to use (default is 'sha256').

    Returns:
        str: The hexadecimal digest of the hash.
    """
    logger.debug(
        f"Generating hash for file {filename} with attributes {filesize}, {creation_time}, {modification_time}"
    )
    # Concatenate the attributes into a single string
    hash_input = f"{filename}{filesize}{creation_time}{modification_time}".encode()
    # Generate the hash using SHA-256
    file_hash = hashlib.sha256(hash_input).hexdigest()

    return file_hash


def generate_run_hash(
    run_location: str,
    creation_time: str,
    last_modification_time: str,
    files: list[File],
) -> str:
    """
    Generates a hash for the run based on its location, creation time, and last modification time, and the files it contains.

    Args:
        run_location (str): The location of the run.
        creation_time (str): The creation time in ISO format.
        last_modification_time (str): The last modification time in ISO format.

    Returns:
        str: The hexadecimal digest of the hash.
    """
    # Create a list of file hashes, sorted by filename
    file_hashes = sorted([file.file_hash for file in files])
    # Turn the list into a hashable string
    file_hashes_str = "".join(file_hashes)
    # Hash the file hashes
    files_hash = hashlib.sha256(file_hashes_str.encode("utf-8")).hexdigest()

    # Concatenate the attributes into a single string
    hash_input = f"{run_location}{creation_time}{last_modification_time}{files_hash}".encode()

    # Generate the hash using SHA-256
    run_hash = hashlib.sha256(hash_input).hexdigest()

    return run_hash


def check_run_differences(
    previous_run_entry: WorkflowRun,
    run_location: str,
    creation_time: str,
    last_modification_time: str,
    files: list[File],
) -> dict:
    """_summary_

    Args:
        previous_run_entry (WorkflowRun): _description_
        run_location (str): _description_
        creation_time (str): _description_
        last_modification_time (str): _description_
        files (List[File]): _description_

    Returns:
        list: _description_
    """
    # Check if the run hash has changed
    run_hash = generate_run_hash(run_location, creation_time, last_modification_time, files)
    if previous_run_entry.run_hash != run_hash:
        differences: DefaultDict[Any, dict[Any, Any]] = collections.defaultdict(dict)
        logger.warning(f"Hash mismatch for run {run_location}.")
        # Deconvolute the hash to identify what changed
        # Check what changed
        if run_location != previous_run_entry.run_location:
            logger.warning(f"Run location changed for run {run_location}.")
            differences["run_location"] = {
                "previous": previous_run_entry.run_location,
                "current": run_location,
            }

        if creation_time != previous_run_entry.creation_time:
            logger.warning(f"Creation time changed for run {run_location}.")
            differences["creation_time"] = {
                "previous": previous_run_entry.creation_time,
                "current": creation_time,
            }

        if last_modification_time != previous_run_entry.last_modification_time:
            logger.warning(f"Last modification time changed for run {run_location}.")
            differences["last_modification_time"] = {
                "previous": previous_run_entry.last_modification_time,
                "current": last_modification_time,
            }

        # if differences is empty, then files have changed
        if not differences:
            logger.warning(f"Files changed for run {run_location}.")
            differences["files"] = {
                "previous": previous_run_entry.files_id,
                "current": [file.id for file in files],
            }

        return differences
    return {}


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
        id=file_id if file_id else ObjectId(),
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
    if not skip_regex:
        regex_config = data_collection.config.scan.scan_parameters.regex_config
        full_regex = (
            construct_full_regex(regex=regex_config)
            if getattr(regex_config, "wildcards", False)
            else regex_config.pattern
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


# @typechecked
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
    Scan a single run folder (a directory containing result files and/or subfolders)
    and update the local TinyDB.

    Args:
        run_location (str): The directory of the run.
        run_tag (str): A tag/name for this run.
        workflow_config (WorkflowConfig): The workflow configuration object.
        data_collection (DataCollection): The data collection configuration object.
        workflow_id (ObjectId): The ID of the workflow.
        rescan_folders (bool): Whether to reprocess the runs.
        update_files (bool): Whether to update file information.

    Returns:
        WorkflowRun: The scanned workflow run.
    """
    if not os.path.exists(run_location):
        raise ValueError(f"The directory '{run_location}' does not exist.")
    if not os.path.isdir(run_location):
        raise ValueError(f"'{run_location}' is not a directory.")

    creation_time = format_timestamp(os.path.getctime(run_location))
    last_modification_time = format_timestamp(os.path.getmtime(run_location))

    if existing_run:
        logger.debug(f"Run {run_tag} already exists in the database.")
        logger.debug(f"Existing Run: {existing_run}")
        if rescan_folders:
            logger.info(f"Reprocessing run {run_tag}...")
            workflow_run = existing_run

        else:
            logger.info(f"Skipping existing run {run_tag}.")
            return None
    else:
        workflow_run = WorkflowRun(
            workflow_id=workflow_id,
            run_tag=run_tag,
            files_id=[],
            workflow_config_id=workflow_config.id,
            run_location=run_location,
            creation_time=creation_time,
            last_modification_time=last_modification_time,
            run_hash="",
            permissions=permissions,
        )

    # Scan files in this run folder
    file_scan_results = process_files(
        path=run_location,
        run=workflow_run,
        data_collection=data_collection,
        permissions=permissions,
        existing_files=existing_files_reformated,
        update_files=update_files,
    )

    logger.debug(f"File Scan Results: {file_scan_results}")
    old_updated_files = [
        sc.file.id
        for sc in file_scan_results
        if sc.scan_result["result"] == "success" and sc.scan_result["reason"] == "updated"
    ]
    # old_updated_files = [file for file in files if str(file.file_location) in existing_files_reformated]

    new_files = [
        sc.file.id
        for sc in file_scan_results
        if sc.scan_result["result"] == "success" and sc.scan_result["reason"] == "added"
    ]
    # new_files = [file for file in files if str(file.file_location) not in existing_files_reformated]

    files_skipped = [
        sc.file.id
        for sc in file_scan_results
        if sc.scan_result["result"] == "failure" and sc.scan_result["reason"] == "skipped"
    ]

    missing_files_location = set(existing_files_reformated.keys()) - set(
        [str(sc.file.file_location) for sc in file_scan_results]
    )
    logger.debug(f"Existing Files: {(existing_files_reformated.keys())}")
    logger.debug(f"Scanned Files: {[str(sc.file.file_location) for sc in file_scan_results]}")
    logger.debug(f"Missing Files Location: {missing_files_location}")

    missing_files = [
        existing_files_reformated[file_location]["_id"] for file_location in missing_files_location
    ]

    files_other_failure = [
        sc.file.id
        for sc in file_scan_results
        if sc.scan_result["result"] == "failure" and sc.scan_result["reason"] != "skipped"
    ]

    if not update_files:
        files = [
            sc.file
            for sc in file_scan_results
            if sc.scan_result["result"] == "success" and sc.scan_result["reason"] == "added"
        ]
    else:
        files = [sc.file for sc in file_scan_results if sc.scan_result["result"] == "success"]

    stats = {
        "total_files": len(file_scan_results),
        "updated_files": len(old_updated_files),
        "new_files": len(new_files),
        "missing_files": len(missing_files) if not update_files else 0,
        "deleted_files": len(missing_files) if update_files else 0,
        "skipped_files": len(files_skipped),
        "other_failure_files": len(files_other_failure),
    }
    scan_results_files_id = {
        "updated_files": old_updated_files,
        "new_files": new_files,
        "skipped_files": files_skipped,
        "other_failure_files": files_other_failure,
    }

    # Upsert the files into the database
    if files:
        logger.info(f"Files to add: {files}")
        api_create_files(files=files, CLI_config=CLI_config, update=update_files)
    if missing_files and update_files:
        logger.info(f"Files to remove: {missing_files}")
        for file_id in missing_files:
            api_delete_file(file_id=file_id, CLI_config=CLI_config)
    # else:
    # rich_print_checked_statement(f"No files found to add in the DB in run {run_tag}.", "warning")

    workflow_run.files_id = [file.id for file in files]
    workflow_run.scan_results.append(
        WorkflowRunScan(
            stats=stats,
            files_id=scan_results_files_id,
            scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    )

    if not update_files and existing_run:
        files = [File.from_mongo(v) for k, v in existing_files_reformated.items()]

    # Generate the hash for the run
    run_hash = generate_run_hash(run_location, creation_time, last_modification_time, files)
    logger.debug(f"Run hash: {run_hash}")

    if workflow_run.run_hash:
        logger.debug(f"Existing run hash: {workflow_run.run_hash}")

        if rescan_folders or workflow_run.run_hash != run_hash:
            differences = check_run_differences(
                workflow_run, run_location, creation_time, last_modification_time, files
            )
            logger.debug(f"Differences: {differences}")

        if not rescan_folders and workflow_run.run_hash != run_hash:
            logger.warning(f"Hash mismatch for run {run_tag}.")
            rich_print_checked_statement(
                f"Hash mismatch for run {run_tag}. The run content has changed since the last scan. Please use --rescan-folders to update the run content or check the logs for more details.",
                "error",
                exit=True,
            )
        elif workflow_run.run_hash == run_hash:
            logger.debug(f"Hash match for run {run_tag}.")

    workflow_run.run_hash = run_hash

    logger.debug(f"DEBUG - Workflow Run: {workflow_run}")

    return workflow_run


# @typechecked
def scan_parent_folder(
    parent_runs_location: str,
    workflow_config: WorkflowConfig,
    data_collection: DataCollection,
    data_location: WorkflowDataLocation,
    existing_files_reformated: dict,
    workflow_id: ObjectId,
    CLI_config: CLIConfig,
    permissions: Permission,
    structure: str = "sequencing-runs",  # or "direct-folder"
    rescan_folders: bool = False,
    update_files: bool = False,
) -> list[WorkflowRun | None]:
    """
    Scan a parent folder either as multiple runs (each subdirectory is a run) or as a direct folder (the
    provided directory is a single run).

    Args:
        parent_runs_location (str): The parent directory containing the runs or files.
        workflow_config (WorkflowConfig): The workflow configuration object.
        data_collection (DataCollection): The data collection configuration object.
        data_location (WorkflowDataLocation): The data location configuration object.
        workflow_id (ObjectId): The ID of the workflow.
        structure (str): "sequencing-runs" to scan subdirectories, "direct-folder" to scan the folder itself.
        rescan_folders (bool): Whether to reprocess the runs.
        update_files (bool): Whether to update file information.

    Returns:
        List[WorkflowRun]: A list of scanned WorkflowRun objects.
    """
    runs = list()

    if not os.path.exists(parent_runs_location):
        raise ValueError(f"The directory '{parent_runs_location}' does not exist.")
    if not os.path.isdir(parent_runs_location):
        raise ValueError(f"'{parent_runs_location}' is not a directory.")

    # Pre-allocation of existing runs
    existing_runs_reformated: dict[str, dict] = {}
    existing_files_reformated_run: dict[str, dict] = {}

    existing_runs_response = api_get_runs_by_wf_id(wf_id=str(workflow_id), CLI_config=CLI_config)
    logger.info(f"Existing Runs Response: {existing_runs_response}")
    if existing_runs_response.status_code == 200:
        existing_runs = existing_runs_response.json()
        logger.debug(f"Existing Runs: {existing_runs}")
        if existing_runs:
            # existing_runs_reformated = {e["run_tag"]: e for e in existing_runs}
            existing_runs_reformated = {
                e["run_tag"]: WorkflowRun.from_mongo(e) for e in existing_runs
            }
            logger.debug(f"Existing Runs Reformated: {existing_runs_reformated}")

    if structure == "direct-folder":
        # Treat the provided directory as a single run
        run_tag = os.path.basename(os.path.normpath(parent_runs_location))
        if run_tag in existing_runs_reformated:
            logger.debug(f"Run {run_tag} already exists in the database.")
            if not rescan_folders:
                logger.debug(f"Skipping existing run {run_tag}.")
                return []
        workflow_run = scan_run(
            run_location=parent_runs_location,
            run_tag=run_tag,
            workflow_config=workflow_config,
            data_collection=data_collection,
            workflow_id=workflow_id,
            CLI_config=CLI_config,
            permissions=permissions,
            rescan_folders=rescan_folders,
            update_files=update_files,
            existing_files_reformated=existing_files_reformated_run,
            existing_run=existing_runs_reformated.get(run_tag, None),
        )
        runs.append(workflow_run)
    elif structure == "sequencing-runs":
        # Each subdirectory that matches the regex is a run
        for run in sorted(os.listdir(parent_runs_location)):
            logger.debug(f"Scanning run: {run} - Existing Runs: {existing_runs_reformated}")
            if run in existing_runs_reformated:
                logger.debug(f"Run {run} already exists in the database.")
                logger.debug(f"Existing Run: {existing_runs_reformated[run]}")
                if not rescan_folders:
                    logger.debug(f"Skipping existing run {run}.")
                    continue
            run_path = os.path.join(parent_runs_location, run)
            if os.path.isdir(run_path) and re.match(data_location.runs_regex, run):
                existing_run = existing_runs_reformated.get(run, None)
                if existing_run is not None:
                    # Optionally cast to WorkflowRun if needed:
                    non_null_run = cast(WorkflowRun, existing_run)
                    existing_files_reformated_run = {
                        k: v
                        for k, v in existing_files_reformated.items()
                        if str(v["run_id"]) == str(non_null_run.id)
                    }
                else:
                    existing_files_reformated_run = {}

                workflow_run = scan_run(
                    run_location=run_path,
                    run_tag=run,
                    workflow_config=workflow_config,
                    data_collection=data_collection,
                    workflow_id=workflow_id,
                    existing_run=existing_run,
                    existing_files_reformated=existing_files_reformated_run,
                    CLI_config=CLI_config,
                    permissions=permissions,
                    rescan_folders=rescan_folders,
                    update_files=update_files,
                )
                runs.append(workflow_run)
        missing_runs_tag = set(existing_runs_reformated.keys()) - set(
            [run.run_tag for run in runs if run]
        )
        missing_runs = [existing_runs_reformated[run_tag].id for run_tag in missing_runs_tag]

        if rescan_folders:
            if missing_runs:
                logger.info(f"Runs to remove: {missing_runs}")
                for run_id in missing_runs:
                    api_delete_run(run_id=run_id, CLI_config=CLI_config)
                    # delete related files
                    for file in existing_files_reformated.values():
                        if file["run_id"] == run_id:
                            api_delete_file(file_id=file["_id"], CLI_config=CLI_config)
                rich_print_checked_statement(
                    f"Removed {len(missing_runs)} runs and related files from the DB : {missing_runs_tag}",
                    "info",
                )
            # else:
            #     rich_print_checked_statement("No runs found to remove in the DB.", "warning")
    else:
        raise ValueError(
            f"Unknown structure '{structure}'. Valid options are 'sequencing-runs' and 'direct-folder'."
        )

    return runs


def rich_print_summary_scan_table(runs: list[WorkflowRun]) -> None:
    from rich.console import Console
    from rich.table import Table

    print("\n")

    # Create the table with headers for each stat
    table = Table(title="Workflow Runs Files Scan Results Stats Summary")

    # Define columns with improved justification and dynamic width handling
    table.add_column("Run Tag", style="cyan", justify="left")
    table.add_column("Total", justify="center")
    table.add_column("Updated", justify="center")
    table.add_column("New", justify="center")
    table.add_column("Missing", justify="center")
    table.add_column("Deleted", justify="center")
    table.add_column("Skipped", justify="center")
    table.add_column("Other", justify="center")

    # Assuming you have a variable (e.g., run.scan_results) with all WorkflowRunScan objects
    for run in runs:
        scan_results = run.scan_results[-1]  # get the last scan results
        stats = (
            scan_results.stats
        )  # the stats dict, e.g. {'total_files': 3, 'updated_files': 0, ...}
        table.add_row(
            run.run_tag,
            str(stats.get("total_files", "")),
            str(stats.get("updated_files", "")),
            str(stats.get("new_files", "")),
            str(stats.get("missing_files", "")),
            str(stats.get("deleted_files", "")),
            str(stats.get("skipped_files", "")),
            str(stats.get("other_failure_files", "")),
        )

    console = Console()
    console.print(table)


@validate_call
def scan_files_for_data_collection(
    workflow: Workflow,
    data_collection_id: str,
    CLI_config: CLIConfig,
    command_parameters: dict,
) -> None:
    """
    Scan files for a given data collection of a workflow and track progress in the local TinyDB.

    Args:
        workflow (Workflow): The workflow configuration object.
        data_collection_id (str): The ID of the data collection to scan.
        CLI_config (CLIConfig): CLI configuration containing API URL and credentials.
        command_parameters (dict): Command parameters, e.g. rescan_folders, sync_files.
    """
    # Parse the command parameters
    rescan_folders = command_parameters.get("rescan_folders", False)
    update_files = command_parameters.get("sync_files", False)

    workflow_id = workflow.id

    # Generate permissions for the files
    user_base = CLI_config.user.model_dump()
    user_base.pop("token")
    user_base = UserBase.from_mongo(user_base)
    logger.debug(f"User: {user_base}")
    permissions = Permission(owners=[user_base])
    logger.debug(f"Permissions: {permissions}")

    # Retrieve workflow and data collection details
    logger.debug("Fetching workflow and data collection details from local configurations...")
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
        raise ValueError(error_msg)  # Abort execution if data_collection is not found

    # Retrieve locations from the workflow config
    locations = workflow.data_location.locations

    # Check for the file's existence in the DB
    response = api_get_files_by_dc_id(dc_id=str(data_collection.id), CLI_config=CLI_config)
    print(f"Response: {response}")
    print(f"Response Status Code: {response.status_code}")
    print(f"Response Content: {response.content}")
    print(f"Response json: {response.json()}")
    if response.status_code == 200:
        existing_files = response.json()
        # existing_files = [f for f in existing_files]
        # existing_files = [File.from_mongo(f) for f in existing_files]
        logger.debug(f"Existing Files: {existing_files}")
        print(f"Existing Files: {existing_files}")
    else:
        existing_files = None
        logger.warning(
            f"Failed to retrieve existing files for data collection {data_collection_id}."
        )
        rich_print_checked_statement(
            f"Failed to retrieve existing files for data collection {data_collection_id}.",
            "warning",
        )
        logger.info(f"Response: {response.status_code} - {response.text}")

    # Convert existing_files from a dict to a list of file dictionaries if needed.
    existing_files_reformated = (
        {existing_file["file_location"]: existing_file for existing_file in existing_files}
        if existing_files
        else {}
    )

    logger.debug(f"Existing Files list: {existing_files_reformated}")

    # For a single-file scan (e.g. metadata), use the provided filename.
    if data_collection.config.scan.mode.lower() == "single":
        logger.debug(
            f"Scanning single file for data collection {data_collection.data_collection_tag}"
        )
        file_path = data_collection.config.scan.scan_parameters.filename
        logger.debug(f"File Path: {file_path}")

        assert len(existing_files_reformated) <= 1, (
            f"Multiple files found for data collection {data_collection.data_collection_tag} with file location {file_path}"
        )

        # Create a WorkflowRun instance for the single file scan.
        workflow_run = WorkflowRun(
            workflow_id=workflow_id,
            run_tag=f"{data_collection.data_collection_tag}-single-file-scan",
            files_id=[],
            workflow_config_id=workflow.config.id,
            run_location=os.path.dirname(file_path),
            creation_time=format_timestamp(os.path.getctime(file_path)),
            last_modification_time=format_timestamp(os.path.getmtime(file_path)),
            run_hash="",
            permissions=permissions,
        )

        # For single file mode, bypass regex matching.
        scan_file_result = process_files(
            path=file_path,
            run=workflow_run,
            data_collection=data_collection,
            existing_files=existing_files_reformated,
            permissions=permissions,
            update_files=update_files,
            skip_regex=True,
        )

        logger.debug(f"Scan File Result: {scan_file_result}")

        if scan_file_result:
            if not update_files:
                files = [
                    sc.file
                    for sc in scan_file_result
                    if sc.scan_result["result"] == "success" and sc.scan_result["reason"] == "added"
                ]
            else:
                files = [
                    sc.file for sc in scan_file_result if sc.scan_result["result"] == "success"
                ]
        else:
            files = []

        logger.debug(f"Scanned file(s): {files}")

        if files:
            api_create_files(files=files, CLI_config=CLI_config, update=update_files)
        rich_print_checked_statement(
            f"Scanned {len(files)} file(s) for data collection {data_collection.data_collection_tag}",
            "info",
        )
        return {
            "result": "success",
        }
    else:
        # For aggregate mode, use the existing parent folder scanning.
        locations = workflow.data_location.locations
        if not locations:
            rich_print_checked_statement(
                f"No locations configured for workflow {workflow.workflow_tag}.",
                "warning",
            )
            return

        runs_stats = []
        for location in locations:
            logger.info(f"Scanning location: {location}")
            runs_and_content = scan_parent_folder(
                parent_runs_location=location,
                workflow_config=workflow.config,
                data_location=workflow.data_location,
                data_collection=data_collection,
                existing_files_reformated=existing_files_reformated,
                workflow_id=workflow_id,
                CLI_config=CLI_config,
                permissions=permissions,
                structure=workflow.data_location.structure,
                rescan_folders=rescan_folders,
                update_files=update_files,
            )
            logger.debug(f"Runs and content: {runs_and_content[:2]}")
            if runs_and_content:
                api_upsert_runs_batch(runs_and_content, CLI_config, rescan_folders)
                runs_stats.extend(runs_and_content)
            rich_print_summary_scan_table(runs_stats)
            rich_print_checked_statement(
                f"Scanned {len(runs_and_content)} runs in location {location}",
                "success",
            )
            return {
                "result": "success",
            }
