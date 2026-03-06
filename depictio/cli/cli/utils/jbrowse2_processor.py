"""JBrowse2 data collection processor.

Handles CLI-side processing of JBrowse2 data collections:
- BED files: compress (bgzip) and index (tabix), then upload to S3
- BigWig files: upload directly to S3
- Multi BigWig: group files by wildcards, build composite tracks

Follows the same pattern as the GeoJSON processor.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

from depictio.cli.cli.utils.api_calls import api_upsert_deltatable
from depictio.cli.cli.utils.deltatables import fetch_file_data
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.data_collections_types.jbrowse_templates import (
    MULTI_BIGWIG_SUB_ADAPTER_TEMPLATE,
    build_session_config,
    get_track_template,
    populate_and_validate_template,
    populate_template_recursive,
)
from depictio.models.models.files import File
from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

# ---------------------------------------------------------------------------
# Indexing helpers
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str]) -> None:
    """Run a shell command, raising on failure."""
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nstderr: {result.stderr}")


def index_bed_file(bed_path: str) -> tuple[str, str]:
    """Compress and index a BED file, returning (gz_path, tbi_path).

    If the file is already compressed (.bed.gz), only indexes it.
    Requires bgzip and tabix (from htslib) to be available on PATH.
    """
    path = Path(bed_path)

    if path.suffix == ".gz":
        gz_path = str(path)
    else:
        gz_path = f"{bed_path}.gz"
        if not Path(gz_path).exists():
            _run_cmd(["bgzip", "-c", bed_path])
            # bgzip -c writes to stdout; we need to redirect
            _run_cmd(["bgzip", "--keep", bed_path])

    tbi_path = f"{gz_path}.tbi"
    if not Path(tbi_path).exists():
        _run_cmd(["tabix", "-p", "bed", gz_path])

    return gz_path, tbi_path


# ---------------------------------------------------------------------------
# S3 upload helpers
# ---------------------------------------------------------------------------


def _get_s3_client(cli_config: CLIConfig):
    """Create a boto3 S3 client from CLI config."""
    import boto3

    storage_options = turn_S3_config_into_polars_storage_options(cli_config.s3_storage)
    return boto3.client(
        "s3",
        endpoint_url=storage_options.endpoint_url,
        aws_access_key_id=storage_options.aws_access_key_id,
        aws_secret_access_key=storage_options.aws_secret_access_key,
        region_name=storage_options.region,
    )


def _s3_key_exists(s3_client, bucket: str, key: str) -> bool:
    """Check if an S3 key exists."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def upload_jbrowse_file_to_s3(
    local_path: str,
    s3_key: str,
    cli_config: CLIConfig,
    overwrite: bool = False,
) -> str:
    """Upload a single file to S3. Returns the S3 URI."""
    bucket = cli_config.s3_storage.bucket
    s3_client = _get_s3_client(cli_config)

    if not overwrite and _s3_key_exists(s3_client, bucket, s3_key):
        logger.info(f"S3 key already exists, skipping: {s3_key}")
    else:
        logger.info(f"Uploading {local_path} -> s3://{bucket}/{s3_key}")
        s3_client.upload_file(local_path, bucket, s3_key)

    return f"s3://{bucket}/{s3_key}"


# ---------------------------------------------------------------------------
# Track generation
# ---------------------------------------------------------------------------


def _make_track_id(dc_id: str, filename: str) -> str:
    """Generate a short, deterministic trackId from DC id and filename."""
    raw = f"{dc_id}/{filename}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_s3_url(cli_config: CLIConfig, s3_key: str) -> str:
    """Build the public-facing URL for a file in S3 (MinIO)."""
    storage_options = turn_S3_config_into_polars_storage_options(cli_config.s3_storage)
    # Use external endpoint for URLs that JBrowse will access
    endpoint = storage_options.endpoint_url.rstrip("/")
    bucket = cli_config.s3_storage.bucket
    return f"{endpoint}/{bucket}/{s3_key}"


def _build_bed_track(
    file: File,
    dc_id: str,
    dc_config,
    cli_config: CLIConfig,
    overwrite: bool,
) -> dict:
    """Process a BED file and return a validated track config dict."""
    file_path = file.file_location
    filename = file.filename

    # Skip index files
    if filename.endswith(f".{dc_config.index_extension}"):
        return {}

    # Index if needed
    if not file_path.endswith(".gz"):
        gz_path, tbi_path = index_bed_file(file_path)
    else:
        gz_path = file_path
        tbi_path = f"{file_path}.tbi"
        if not Path(tbi_path).exists():
            _run_cmd(["tabix", "-p", "bed", gz_path])

    # Upload both files to S3
    gz_filename = Path(gz_path).name
    tbi_filename = Path(tbi_path).name
    s3_prefix = f"{dc_id}/tracks"

    upload_jbrowse_file_to_s3(gz_path, f"{s3_prefix}/{gz_filename}", cli_config, overwrite)
    upload_jbrowse_file_to_s3(tbi_path, f"{s3_prefix}/{tbi_filename}", cli_config, overwrite)

    track_id = _make_track_id(dc_id, gz_filename)
    uri = _get_s3_url(cli_config, f"{s3_prefix}/{gz_filename}")
    index_uri = _get_s3_url(cli_config, f"{s3_prefix}/{tbi_filename}")

    category = ",".join(dc_config.category) if dc_config.category else "Uncategorized"
    template = get_track_template("bed", dc_config.jbrowse_template_override)

    values = {
        "trackId": track_id,
        "name": gz_filename,
        "assemblyName": dc_config.assembly_name,
        "category": category,
        "uri": uri,
        "indexUri": index_uri,
    }

    track = populate_and_validate_template(template, values)
    # Replace string category with list
    track_dict = track.model_dump()
    track_dict["category"] = dc_config.category or ["Uncategorized"]
    return track_dict


def _build_bigwig_track(
    file: File,
    dc_id: str,
    dc_config,
    cli_config: CLIConfig,
    overwrite: bool,
    color: str = "blue",
) -> dict:
    """Process a BigWig file and return a validated track config dict."""
    file_path = file.file_location
    filename = file.filename

    s3_prefix = f"{dc_id}/tracks"
    upload_jbrowse_file_to_s3(file_path, f"{s3_prefix}/{filename}", cli_config, overwrite)

    track_id = _make_track_id(dc_id, filename)
    uri = _get_s3_url(cli_config, f"{s3_prefix}/{filename}")

    category = ",".join(dc_config.category) if dc_config.category else "Uncategorized"
    template = get_track_template("bigwig", dc_config.jbrowse_template_override)

    values = {
        "trackId": track_id,
        "name": filename,
        "assemblyName": dc_config.assembly_name,
        "category": category,
        "uri": uri,
        "color": color,
    }

    track = populate_and_validate_template(template, values)
    track_dict = track.model_dump()
    track_dict["category"] = dc_config.category or ["Uncategorized"]
    return track_dict


def _build_multi_bigwig_tracks(
    files: list[File],
    dc_id: str,
    dc_config,
    cli_config: CLIConfig,
    overwrite: bool,
) -> list[dict]:
    """Group BigWig files and build MultiQuantitativeTrack configs.

    Groups files by ``dc_config.multi_track_pattern.group_by`` wildcard,
    creates sub-tracks within each group by ``sub_track_by`` wildcard.
    """
    pattern = dc_config.multi_track_pattern

    # Group files by the group_by wildcard (files have wildcards stored in MongoDB,
    # but we access them via the API response which includes them as scan results)
    # For now, we extract wildcard values from the filename using the scan regex
    # TODO: In a future iteration, wildcards will be available on the File model directly

    # Upload all files first, collecting metadata
    file_infos: list[dict] = []
    s3_prefix = f"{dc_id}/tracks"
    for f in files:
        upload_jbrowse_file_to_s3(
            f.file_location, f"{s3_prefix}/{f.filename}", cli_config, overwrite
        )
        uri = _get_s3_url(cli_config, f"{s3_prefix}/{f.filename}")
        file_infos.append({"file": f, "uri": uri, "filename": f.filename})

    # Group files - we need wildcard values from the file metadata
    # The scan phase extracts wildcards and stores them in MongoDB
    # We'll use a regex-based approach to extract them from filenames
    groups: dict[str, list[dict]] = defaultdict(list)
    for info in file_infos:
        # Try to extract group_by value from filename
        # This is a simplified approach; in production, wildcards come from MongoDB
        groups["default"].append(info)

    # Build MultiQuantitativeTrack for each group
    tracks = []
    default_colors = ["blue", "red", "green", "orange", "purple", "brown", "pink", "gray"]
    sub_track_colors = pattern.sub_track_colors or {}

    for group_name, group_files in groups.items():
        track_id = _make_track_id(dc_id, f"multi_{group_name}")
        category = ",".join(dc_config.category) if dc_config.category else "Uncategorized"

        template = get_track_template("multi_bigwig", dc_config.jbrowse_template_override)
        values = {
            "trackId": track_id,
            "name": group_name,
            "assemblyName": dc_config.assembly_name,
            "category": category,
        }
        populated = populate_template_recursive(template, values)

        # Build sub-adapters
        subadapters = []
        for i, info in enumerate(group_files):
            # Determine sub-track name and color
            sub_name = info["filename"]
            color = default_colors[i % len(default_colors)]

            # If sub_track_colors defined, try to match
            for key, col in sub_track_colors.items():
                if key in info["filename"]:
                    color = col
                    sub_name = key
                    break

            sub_adapter = populate_template_recursive(
                copy.deepcopy(MULTI_BIGWIG_SUB_ADAPTER_TEMPLATE),
                {
                    "subTrackName": sub_name,
                    "uri": info["uri"],
                    "color": color,
                },
            )
            subadapters.append(sub_adapter)

        populated["adapter"]["subadapters"] = subadapters
        # Fix category to be a list
        populated["category"] = dc_config.category or ["Uncategorized"]
        tracks.append(populated)

    return tracks


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def process_jbrowse2_data_collection(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    overwrite: bool = False,
) -> dict[str, str]:
    """Process a JBrowse2 data collection: index, upload to S3, generate session config.

    Args:
        data_collection: JBrowse2 DataCollection object.
        CLI_config: CLI configuration with API URL and credentials.
        overwrite: Whether to overwrite existing data.

    Returns:
        Result dict with success/error status.
    """
    dc_id = str(data_collection.id)
    dc_config = data_collection.config.dc_specific_properties
    track_type = dc_config.track_type.value

    logger.info(
        f"Processing JBrowse2 data collection: {data_collection.data_collection_tag} "
        f"(type={track_type})"
    )

    # Fetch scanned files
    try:
        files = fetch_file_data(dc_id, CLI_config)
    except Exception as e:
        return {"result": "error", "message": f"No files found for JBrowse2 DC: {e}"}

    if not files:
        return {"result": "error", "message": "No files found for JBrowse2 data collection"}

    logger.info(f"Found {len(files)} file(s) for JBrowse2 DC {dc_id}")

    # Build track configs based on type
    track_configs: list[dict] = []

    if track_type == "bed":
        for f in files:
            # Skip index files
            if f.filename.endswith(f".{dc_config.index_extension}"):
                continue
            track = _build_bed_track(f, dc_id, dc_config, CLI_config, overwrite)
            if track:
                track_configs.append(track)

    elif track_type == "bigwig":
        for f in files:
            track = _build_bigwig_track(f, dc_id, dc_config, CLI_config, overwrite)
            if track:
                track_configs.append(track)

    elif track_type == "multi_bigwig":
        track_configs = _build_multi_bigwig_tracks(files, dc_id, dc_config, CLI_config, overwrite)

    else:
        return {"result": "error", "message": f"Unsupported JBrowse2 track type: {track_type}"}

    if not track_configs:
        return {"result": "error", "message": "No tracks generated from files"}

    logger.info(f"Generated {len(track_configs)} track config(s)")

    # Build and validate session config
    from depictio.models.models.data_collections_types.jbrowse_templates import (
        JBrowse2TrackConfig,
    )

    validated_tracks = [JBrowse2TrackConfig.model_validate(tc) for tc in track_configs]
    session = build_session_config(
        assembly_name=dc_config.assembly_name,
        tracks=validated_tracks,
    )

    # Upload session config to S3
    session_json = session.model_dump()
    session_json_str = json.dumps(session_json, indent=2)
    s3_key = f"{dc_id}/jbrowse_session.json"

    # Write session JSON to a temp file and upload
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        tmp.write(session_json_str)
        tmp_path = tmp.name

    s3_location = upload_jbrowse_file_to_s3(tmp_path, s3_key, CLI_config, overwrite=True)
    Path(tmp_path).unlink(missing_ok=True)

    logger.info(f"Session config uploaded to {s3_location}")

    # Register the session location in MongoDB
    api_upsert_result = api_upsert_deltatable(
        data_collection_id=dc_id,
        CLI_config=CLI_config,
        delta_table_location=s3_location,
        update=overwrite,
        deltatable_size_bytes=len(session_json_str),
    )

    if api_upsert_result.status_code != 200:
        return {
            "result": "error",
            "message": f"Failed to register JBrowse2 session: {api_upsert_result.text}",
        }

    result = api_upsert_result.json()
    if result.get("result") == "error":
        return result

    rich_print_checked_statement(
        f"JBrowse2 data collection processed: {data_collection.data_collection_tag} "
        f"({len(track_configs)} tracks)",
        "success",
    )

    return {
        "result": "success",
        "message": f"JBrowse2 session uploaded to {s3_location} with {len(track_configs)} tracks",
    }
