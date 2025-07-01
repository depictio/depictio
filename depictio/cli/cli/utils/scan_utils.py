import collections
import hashlib
import re
from typing import Any, DefaultDict

from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.data_collections import Regex
from depictio.models.models.files import File
from depictio.models.models.workflows import WorkflowRun


def regex_match(file_name: str, full_regex: str):
    # Normalize the regex pattern to match both types of path separators
    normalized_regex = full_regex.replace("/", "\\/")
    # logger.debug(f"File: {file_name}, Full Regex: {full_regex}")
    if re.match(normalized_regex, file_name):
        logger.debug(f"Matched file - file-based: {file_name}")
        return True, re.match(normalized_regex, file_name)
    return False, None


def construct_full_regex(regex: Regex) -> str:
    """
    Construct the full regex using the wildcards defined in the config.

    Args:
        regex (Regex): The regex configuration object.

    Returns:
        str: The constructed regex pattern with wildcards replaced.
    """
    # Start with the original pattern
    files_regex = regex.pattern

    # Handle case where wildcards is None or empty
    if not regex.wildcards:
        return files_regex

    # Check if duplicate wildcards exist
    wildcard_names = [wildcard.name for wildcard in regex.wildcards]
    if len(wildcard_names) != len(set(wildcard_names)):
        raise ValueError("Duplicate wildcard names found in regex configuration.")

    # Replace each wildcard placeholder with its regex pattern
    for wildcard in regex.wildcards:
        logger.debug(f"Wildcard: {wildcard}")
        placeholder = f"{{{wildcard.name}}}"  # e.g. {date}
        regex_pattern = wildcard.wildcard_regex
        files_regex = files_regex.replace(placeholder, f"({regex_pattern})")
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
