import collections
import hashlib
import os
import re
from functools import lru_cache
from typing import Any, DefaultDict, NamedTuple

from depictio.cli.cli_logging import logger
from depictio.models.models.data_collections import Regex
from depictio.models.models.files import File
from depictio.models.models.workflows import Workflow, WorkflowRun


@lru_cache(maxsize=512)
def _compiled_normalized_regex(full_regex: str) -> re.Pattern[str]:
    """Compile (and cache) the path-normalized regex.

    Normalizes ``/`` to ``\\/`` so a pattern matches regardless of how the
    separator was escaped, then compiles once. Compilation is cached because
    the same data-collection pattern is matched against every file in a run
    (the scan hot loop), so recompiling per call is pure waste.
    """
    return re.compile(full_regex.replace("/", "\\/"))


def regex_match(file_name: str, full_regex: str):
    # Match once against the cached compiled pattern (was matching twice +
    # rebuilding the pattern on every call).
    match = _compiled_normalized_regex(full_regex).match(file_name)
    if match:
        logger.debug(f"Matched file - file-based: {file_name}")
        return True, match
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


def data_collection_full_regex(data_collection) -> str | None:
    """The regex a recursive scan matches this data collection's files against.

    ``None`` when the data collection has no regex to match with: a derived
    collection with no scan at all, or a single-file/MultiQC one whose scan
    parameters carry a filename instead of a regex.
    """
    scan = data_collection.config.scan
    if scan is None or not hasattr(scan.scan_parameters, "regex_config"):
        return None
    regex_config = scan.scan_parameters.regex_config
    return (
        construct_full_regex(regex=regex_config)
        if getattr(regex_config, "wildcards", False)
        else regex_config.pattern
    )


def file_matches_data_collection(file_location: str, run_location: str, full_regex: str) -> bool:
    """Whether a file inside a run belongs to a data collection.

    The basename is tried first. Only a pattern that contains a path separator
    (e.g. ``variants/bowtie2/...``) falls back to the run-relative path, so a
    plain filename pattern cannot accidentally match through a directory name.

    Shared with the dry-run preview on purpose: a preview that counted files by
    its own rules would eventually disagree with the scan it claims to predict.
    """
    if regex_match(os.path.basename(file_location), full_regex)[0]:
        return True
    if "/" not in full_regex:
        return False
    return regex_match(os.path.relpath(file_location, run_location), full_regex)[0]


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


# A scan finding nothing used to print "success" in green: the ingest block is
# guarded by `if valid_runs:` and the summary line reports the number of runs
# without ever asking whether that number is zero. The usual cause is a
# `--data-root` pointing one directory above or below the run layout the
# template expects, and the user's only clue was an empty dashboard much later.
# The two describe_* helpers below turn that silence into a message.

# Long enough to recognise the layout, short enough to read in a terminal.
_MAX_LISTED_ENTRIES = 10


def describe_unmatched_run_scan(
    location: str,
    runs_regex: str,
    subdirectories: list[str],
) -> str:
    """Explain why a ``sequencing-runs`` scan matched no run directory.

    Names the three things needed to fix it: where we looked, what we looked
    for, and what was actually there. The listing is what turns "0 runs" into
    "you are one level too high".
    """
    where = f"No run directory under '{location}' matched the pattern '{runs_regex}'."
    if not subdirectories:
        return f"{where} That directory contains no subdirectories at all."

    shown = ", ".join(subdirectories[:_MAX_LISTED_ENTRIES])
    remaining = len(subdirectories) - _MAX_LISTED_ENTRIES
    if remaining > 0:
        shown += f", and {remaining} more"
    noun = "subdirectory" if len(subdirectories) == 1 else "subdirectories"
    return (
        f"{where} It contains {len(subdirectories)} {noun}: {shown}. "
        "Check that --data-root points at the parent of the run directories."
    )


def describe_empty_scan_outcome(
    runs_scanned: int,
    files_found: int,
    runs_skipped_as_existing: int = 0,
) -> str | None:
    """Warning to print when a scan completed but ingested nothing.

    ``None`` means the scan needs no warning, which includes the common
    legitimate no-op: every run in the directory was recognised and skipped
    because it is already ingested. Only a scan that recognised *nothing* has
    a data-root problem worth shouting about.

    The two failing shapes are kept apart because their causes differ: no run
    at all points at the directory level, while runs without files points at
    the data collections' patterns.
    """
    if runs_scanned == 0 and runs_skipped_as_existing == 0:
        return (
            "No run was scanned, so nothing will be ingested. "
            "This usually means --data-root points at the wrong directory level."
        )
    if runs_scanned > 0 and files_found == 0:
        return (
            f"{runs_scanned} run(s) were scanned but no file matched any data collection. "
            "This usually means the data collections' patterns do not match this run's layout."
        )
    return None


class RunCandidates(NamedTuple):
    """What a location holds, from a scan's point of view.

    ``subdirectories`` is every directory entry, matching or not, which is what
    turns "0 runs" into a message the user can act on. ``matched`` is the
    ``(run_tag, run_location)`` pairs a scan would actually visit.
    """

    subdirectories: list[str]
    matched: list[tuple[str, str]]


def collect_run_candidates(
    location: str,
    structure: str,
    runs_regex: str | None = None,
) -> RunCandidates:
    """Enumerate the runs a scan would find under ``location``.

    A ``flat`` location is itself one run. A ``sequencing-runs`` location holds
    one run per subdirectory whose name matches ``runs_regex``. Shared between
    the scanner and the dry-run preview so both agree on what counts as a run.
    """
    if structure == "flat":
        return RunCandidates([], [(os.path.basename(os.path.normpath(location)), location)])

    subdirectories: list[str] = []
    matched: list[tuple[str, str]] = []
    for entry in sorted(os.listdir(location)):
        entry_path = os.path.join(location, entry)
        if not os.path.isdir(entry_path):
            continue
        subdirectories.append(entry)
        if runs_regex and re.match(runs_regex, entry):
            matched.append((entry, entry_path))
    return RunCandidates(subdirectories, matched)


class ResolvedRuns(NamedTuple):
    """Run directories a scan would walk, and why any location yielded none."""

    locations: list[str]
    warnings: list[str]


def resolve_run_locations(workflow: Workflow) -> ResolvedRuns:
    """Run directories a scan of ``workflow`` would walk, best-effort.

    A location that does not exist, or that matches no run, becomes a warning
    rather than an exception: this feeds a preview, and one bad path must not
    hide every other data collection's count behind a traceback.
    """
    structure = workflow.data_location.structure
    runs_regex = workflow.data_location.runs_regex
    run_locations: list[str] = []
    warnings: list[str] = []
    for location in workflow.data_location.locations:
        if not os.path.isdir(location):
            warnings.append(f"Configured location '{location}' does not exist.")
            continue
        candidates = collect_run_candidates(location, structure, runs_regex)
        if not candidates.matched and structure != "flat":
            warnings.append(
                describe_unmatched_run_scan(location, runs_regex or "", candidates.subdirectories)
            )
        run_locations.extend(run_location for _, run_location in candidates.matched)
    return ResolvedRuns(run_locations, warnings)


def count_data_collection_matches(data_collections, run_locations: list[str]) -> list[int | None]:
    """How many local files a scan would match, one count per data collection.

    ``None`` means there is nothing to count: a derived collection carries no
    scan config, and a preview must show that as unknown rather than as a
    misleading zero that sends the user hunting for a data-root problem.

    ``mode`` is lowercased like the scanner does, so a config spelling it
    ``Recursive`` is previewed the way it will be scanned.

    Every run directory is walked once and each pattern tested against that one
    listing, the way the scanner does it. Counting one collection at a time
    would re-walk the whole data root once per collection, which on a project
    with twenty collections is twenty times the I/O for the same answer.
    """
    counts: list[int | None] = []
    regexes: list[str | None] = []
    for data_collection in data_collections:
        scan = data_collection.config.scan
        mode = scan.mode.lower() if scan else None

        if mode == "single":
            filename = getattr(scan.scan_parameters, "filename", None)
            counts.append(int(bool(filename) and os.path.isfile(filename)))
            regexes.append(None)
            continue

        full_regex = data_collection_full_regex(data_collection) if mode == "recursive" else None
        counts.append(0 if full_regex else None)
        regexes.append(full_regex)

    if not any(regexes):
        return counts

    for run_location in run_locations:
        for root, _, files in os.walk(run_location):
            for name in files:
                file_location = os.path.join(root, name)
                for index, full_regex in enumerate(regexes):
                    if full_regex and file_matches_data_collection(
                        file_location, run_location, full_regex
                    ):
                        counts[index] += 1  # type: ignore[operator]
    return counts
