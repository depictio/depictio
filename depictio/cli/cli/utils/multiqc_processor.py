"""
MultiQC processing utilities for extracting metadata from parquet files.
Uses MultiQC Python module to extract samples, modules, and plots.
"""

import os
from pathlib import Path
from typing import Any, Dict

from depictio.cli.cli.utils.api_calls import (
    api_check_duplicate_multiqc_report,
    api_create_multiqc_report,
    api_get_multiqc_s3_locations,
    api_update_multiqc_report,
)
from depictio.cli.cli.utils.file_utils import compute_file_hash
from depictio.cli.cli.utils.ingest_timing import record, timed
from depictio.cli.cli.utils.rich_utils import rich_print_multiqc_processing_summary
from depictio.cli.cli_logging import logger


def extract_multiqc_metadata(parquet_path: str) -> Dict[str, Any]:
    """
    Extract metadata from MultiQC parquet file using MultiQC module.

    This follows the exact pattern from the notebook exploration:
    1. multiqc.reset() to clear state
    2. multiqc.parse_logs(parquet_path) to load parquet file
    3. Use list_samples(), list_modules(), list_plots() to extract metadata
    4. Build sample mappings for canonical ID to variants

    Args:
        parquet_path: Path to the MultiQC parquet file

    Returns:
        Dict containing samples, modules, plots, sample_mappings, and canonical_samples
    """
    try:
        # Import multiqc here to avoid dependency issues if not installed
        import multiqc

        # Import sample mapping utility from CLI utils (no FastAPI dependency)
        from depictio.cli.cli.utils.sample_mapping import build_sample_mapping

        logger.info(f"Extracting MultiQC metadata from: {parquet_path}")

        # Source the writer's MultiQC version from the parquet's own
        # `multiqc_version` column. That column is what the validator's
        # uniformity check needs to surface mismatches between reports
        # produced by different MultiQC releases — using the reader's
        # installed package version would stamp every report with the
        # same value and silently bypass the check.
        multiqc_version: str | None = None
        try:
            import polars as pl

            version_series = (
                pl.read_parquet(parquet_path, columns=["multiqc_version"])
                .get_column("multiqc_version")
                .drop_nulls()
                .unique()
            )
            if version_series.len() > 0:
                multiqc_version = str(version_series.item(0))
                logger.info(f"MultiQC version (from parquet): {multiqc_version}")
        except Exception as e:
            logger.debug(f"Could not read multiqc_version column from parquet: {e}")

        if multiqc_version is None:
            try:
                multiqc_version = multiqc.__version__
                logger.info(f"MultiQC version (fallback from installed pkg): {multiqc_version}")
            except AttributeError:
                logger.warning("Could not detect MultiQC version")

        # Reset MultiQC state and parse the parquet file
        multiqc.reset()
        multiqc.parse_logs(parquet_path)

        # Extract metadata using MultiQC module functions
        samples = multiqc.list_samples()
        modules = multiqc.list_modules()

        # Try to get plots, but handle errors gracefully
        try:
            plots = multiqc.list_plots()
        except Exception as e:
            logger.warning(f"Could not extract plots from MultiQC parquet: {e}")
            plots = {}

        # Build sample mappings from canonical IDs to variants
        sample_mappings = build_sample_mapping(samples)
        canonical_samples = list(sample_mappings.keys())

        metadata = {
            "samples": samples,
            "modules": modules,
            "plots": plots,
            "sample_mappings": sample_mappings,
            "canonical_samples": canonical_samples,
            "multiqc_version": multiqc_version,
        }

        logger.info(
            f"Extracted metadata: {len(samples)} samples, {len(canonical_samples)} canonical IDs, "
            f"{len(modules)} modules, {len(plots)} plot groups"
        )

        return metadata

    except ImportError:
        logger.error("MultiQC module not available. Please install MultiQC: pip install multiqc")
        raise
    except Exception as e:
        logger.error(f"Failed to extract MultiQC metadata from {parquet_path}: {e}")
        raise


def _is_parseable_multiqc_file(file_path: str) -> bool:
    """Whether a registered file is a MultiQC parquet that still exists on disk."""
    if not file_path.endswith(".parquet"):
        logger.warning(f"Skipping non-parquet file: {file_path}")
        return False
    if not Path(file_path).exists():
        logger.error(f"File not found: {file_path}")
        return False
    return True


def _parse_multiqc_worker(file_path: str) -> Dict[str, Any]:
    """Parse one report in a worker process — module-level so it stays picklable."""
    return extract_multiqc_metadata(file_path)


def multiqc_parse_workers() -> int:
    """Number of processes to parse MultiQC reports with (1 = serial, the default).

    ``multiqc.parse_logs`` dominates MultiQC ingestion (≈90-99% of the wall) and
    is independent per file, so parsing several at once is the only real lever —
    but MultiQC keeps *module-global* state, so it must be processes, not threads.

    Opt-in via ``DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS`` because each worker holds a
    fully parsed report in memory; on a large report set that multiplies peak RSS,
    which is not a trade a memory-capped deployment should make unasked.
    """
    raw = os.getenv("DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS", "").strip()
    if not raw:
        return 1
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(f"Invalid DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS={raw!r}; parsing serially.")
        return 1


def _parse_multiqc_files(file_paths: list[str]) -> list[tuple[str, Dict[str, Any] | None]]:
    """Parse each report, returning ``(path, metadata|None)`` in input order.

    A file that fails to parse yields ``None`` rather than aborting the batch, so
    one corrupt report cannot lose the whole data collection.
    """
    workers = min(multiqc_parse_workers(), len(file_paths))

    if workers <= 1 or len(file_paths) <= 1:
        return _parse_multiqc_files_serial(file_paths)

    logger.info(f"Parsing {len(file_paths)} MultiQC files across {workers} processes")
    try:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_parse_multiqc_worker, p) for p in file_paths]
            out: list[tuple[str, Dict[str, Any] | None]] = []
            for path, future in zip(file_paths, futures):
                try:
                    out.append((path, future.result()))
                except Exception as e:
                    logger.error(f"Failed to process MultiQC file {path}: {e}")
                    out.append((path, None))
            return out
    except Exception as e:
        # Process pools can be unavailable (sandboxes, restricted containers) —
        # never fail an ingest over a parallelism optimisation.
        logger.warning(f"Parallel MultiQC parse unavailable ({e}); falling back to serial.")
        return _parse_multiqc_files_serial(file_paths)


def _parse_multiqc_files_serial(
    file_paths: list[str],
) -> list[tuple[str, Dict[str, Any] | None]]:
    """Parse reports one at a time, isolating per-file failures."""
    results: list[tuple[str, Dict[str, Any] | None]] = []
    for i, path in enumerate(file_paths, 1):
        logger.info(f"Processing file {i}/{len(file_paths)}: {path}")
        try:
            results.append((path, _parse_multiqc_worker(path)))
        except Exception as e:
            logger.error(f"Failed to process MultiQC file {path}: {e}")
            results.append((path, None))
    return results


def multiqc_prerender_enabled() -> bool:
    """Whether to build MultiQC figures offline at ingest and upload them to S3.

    Opt-in via ``DEPICTIO_INGEST_MULTIQC_PRERENDER`` (``1``/``true``/``yes``). When on,
    the CLI reuses the parse it already pays for metadata to also render every
    present plot's Plotly JSON and ship it to ``s3://{bucket}/{dc_id}/prerender/``.
    The API render path then serves those figures directly, skipping the
    ~30-75 s cold ``parse_logs``/``get_plot`` build entirely. Off by default so
    ingestion behaviour is unchanged unless explicitly requested.
    """
    return os.getenv("DEPICTIO_INGEST_MULTIQC_PRERENDER", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _iter_module_plots(entries: Any):
    """Yield ``(plot_name, [dataset_ids])`` from a module's ``list_plots`` entry.

    MultiQC's ``list_plots()[module]`` is a list whose items are either a plain
    plot name (``str``) or a ``{plot_name: [dataset_id, ...]}`` dict for plots
    that expose sub-datasets (e.g. ``{"Per Sequence GC Content": ["Percentages",
    "Counts"]}``). This normalises both shapes.
    """
    for entry in entries or []:
        if isinstance(entry, str):
            yield entry, []
        elif isinstance(entry, dict):
            for plot_name, datasets in entry.items():
                yield plot_name, (datasets if isinstance(datasets, list) else [])


def _make_s3_client(storage_options):
    """boto3 S3 client configured for MinIO (path-style addressing + s3v4).

    Shared by the report-upload loop and the offline figure prerender so the
    MinIO-compat config lives in one place.
    """
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=storage_options.endpoint_url,
        aws_access_key_id=storage_options.aws_access_key_id,
        aws_secret_access_key=storage_options.aws_secret_access_key,
        region_name=storage_options.region,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _prerender_multiqc_figures(
    data_collection,
    CLI_config,
    prerender_inputs: list[tuple[str, str]],
    storage_options,
) -> None:
    """Build the DC's aggregated Plotly figures locally and upload them to S3.

    Only runs on a *fresh ingest* — where the set of reports this run uploaded
    equals the DC's full report set (queried from the API). On an append (the DC
    already has reports this run didn't touch), the local files can't reproduce
    the full aggregation, so we skip and let the Celery prerender fallback build
    against the complete set. Figures are keyed by the exact same
    ``multiqc_figure_cache_key`` the API render path uses, so the server resolves
    them from S3 without re-parsing.
    """
    import gzip
    import io
    import json

    from depictio.cli.cli.utils.mantine_templates import get_theme_template
    from depictio.cli.cli.utils.multiqc_figures import (
        build_multiqc_figure,
        figure_cache_key_sha,
        multiqc_figure_cache_key,
    )

    dc_id = str(data_collection.id)
    if not prerender_inputs:
        logger.info("Prerender: no local parquet inputs this run; skipping")
        return

    # Authoritative full report set for the DC, in the API's own order (the
    # endpoint mirrors ``fetch_s3_locations_from_dc`` — insertion / _id-ascending).
    # Only prerender when it matches exactly what we have locally (fresh ingest);
    # otherwise the keys built here would never be looked up by the server (which
    # keys over the full set).
    full_locations = api_get_multiqc_s3_locations(dc_id, CLI_config)
    local_by_loc = {loc: path for path, loc in prerender_inputs}
    if not full_locations or set(full_locations) != set(local_by_loc):
        logger.info(
            f"Prerender: DC {dc_id} report set ({len(full_locations)}) differs from this "
            f"run's local files ({len(local_by_loc)}); skipping (Celery fallback will build)"
        )
        return

    # Parse in the SAME order the API build paths do (the order the endpoint
    # returned). MultiQC's report merge is order-sensitive, so parsing in a
    # different order (e.g. sorted) would build a figure whose sample/trace
    # ordering differs from a later Celery rebuild under the *identical* cache
    # key. ``multiqc_figure_cache_key`` sorts internally, so the key stays
    # order-independent — no CLI-side sort of the parse order is wanted.
    import multiqc

    multiqc.reset()
    parsed = 0
    for loc in full_locations:
        try:
            multiqc.parse_logs(local_by_loc[loc])
            parsed += 1
        except Exception as e:
            logger.warning(f"Prerender: parse failed for {loc}: {e}")
    if parsed == 0:
        logger.warning("Prerender: no files parsed; skipping")
        return

    modules = multiqc.list_modules()
    plots = multiqc.list_plots()

    s3_client = _make_s3_client(storage_options)
    bucket = CLI_config.s3_storage.bucket

    def _upload(cache_key: str, fig_dict: dict) -> None:
        # Filename mirrors the API stores: the trailing hash of the bare key.
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(json.dumps(fig_dict, separators=(",", ":")).encode("utf-8"))
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{dc_id}/prerender/{figure_cache_key_sha(cache_key)}.json.gz",
            Body=buf.getvalue(),
            ContentType="application/gzip",
        )

    built = 0
    for module in modules:
        for plot, datasets in _iter_module_plots(plots.get(module, [])):
            # Always build the ``None`` variant (get_figure(dataset_id=0), i.e.
            # the default dataset) in addition to each named dataset. A dashboard
            # component with no dataset selected renders with ``selected_dataset=
            # None`` — a DISTINCT cache key from the named datasets — so without
            # the None variant those plots miss the prerender and fall back to the
            # 120s-timeout on-demand build. ``dict.fromkeys`` de-dups if a caller
            # ever lists None explicitly.
            for dataset in dict.fromkeys([None, *datasets]):
                try:
                    fig = build_multiqc_figure(module, plot, dataset, "light")
                except Exception as e:
                    logger.debug(f"Prerender: build failed for {module}/{plot}/{dataset}: {e}")
                    continue
                light_dict = fig.to_dict()
                light_key = multiqc_figure_cache_key(
                    full_locations, module, plot, dataset, "light", dc_id=dc_id
                )
                # Dark theme differs only by layout template — swap it rather than
                # rebuild the figure (the get_figure call is the expensive part).
                fig.update_layout(template=get_theme_template("dark"))
                dark_dict = fig.to_dict()
                dark_key = multiqc_figure_cache_key(
                    full_locations, module, plot, dataset, "dark", dc_id=dc_id
                )
                try:
                    _upload(light_key, light_dict)
                    _upload(dark_key, dark_dict)
                except Exception as e:
                    logger.warning(f"Prerender: S3 upload failed for {module}/{plot}: {e}")
                    continue
                built += 2

    record("prerendered_figures", built)
    logger.info(
        f"Prerender: uploaded {built} figure(s) for DC {dc_id} "
        f"({len(modules)} modules) to s3://{bucket}/{dc_id}/prerender/"
    )


def validate_multiqc_parquet(parquet_path: str) -> bool:
    """
    Validate that the parquet file is a valid MultiQC report.

    Args:
        parquet_path: Path to the parquet file to validate

    Returns:
        True if valid MultiQC parquet, False otherwise
    """
    try:
        import multiqc

        # Try to parse and extract basic metadata
        multiqc.reset()
        multiqc.parse_logs(parquet_path)

        # Check if we can extract basic information
        samples = multiqc.list_samples()
        modules = multiqc.list_modules()

        # Basic validation: should have at least some samples or modules
        if not samples and not modules:
            logger.warning(f"No samples or modules found in parquet file: {parquet_path}")
            return False

        logger.info(f"Valid MultiQC parquet: {len(samples)} samples, {len(modules)} modules")
        return True

    except Exception as e:
        logger.error(f"Invalid MultiQC parquet file {parquet_path}: {e}")
        return False


def process_multiqc_data_collection(
    data_collection,  # DataCollection type hint avoided to prevent circular imports
    CLI_config,  # CLIConfig type hint avoided to prevent circular imports
    overwrite: bool = False,
    workflow=None,  # Workflow object for accessing data locations
) -> Dict[str, str]:
    """
    Process MultiQC data collection by copying parquet files to S3 and extracting metadata.

    Args:
        data_collection: The MultiQC data collection object
        CLI_config: CLI configuration object containing API URL and credentials
        overwrite: Whether to overwrite existing files in S3

    Returns:
        dict: Result dictionary with success/error status and message
    """
    try:
        logger.info(f"Processing MultiQC data collection: {data_collection.data_collection_tag}")

        # Import here to avoid circular imports
        from depictio.cli.cli.utils.deltatables import fetch_file_data
        from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

        # Get the files for this data collection
        files = []
        try:
            files = fetch_file_data(str(data_collection.id), CLI_config)
        except Exception as e:
            logger.info(f"No files found in database: {e}")

        # If no files found in database, try to discover MultiQC parquet files directly
        if not files:
            logger.info(
                "No files found in database, attempting to discover MultiQC parquet files..."
            )

            # Try to find multiqc.parquet in common locations
            possible_paths = [
                "multiqc.parquet",
                "./multiqc.parquet",
                "multiqc_data.parquet",
                "multiqc_report.parquet",
            ]

            # Also check in configured data locations for the standard MultiQC structure
            if workflow and hasattr(workflow, "data_location") and workflow.data_location:
                from glob import glob

                for location in workflow.data_location.locations:
                    # Search for MultiQC parquet files with multiple patterns
                    # Pattern 1: */multiqc_data/multiqc.parquet (direct)
                    # Pattern 2: */multiqc/multiqc_data/multiqc.parquet (with intermediate multiqc folder)
                    # Pattern 3: */*/multiqc_data/multiqc.parquet (any two-level nesting)

                    patterns = [
                        str(Path(location) / "*" / "multiqc_data" / "multiqc.parquet"),
                        str(Path(location) / "*" / "multiqc" / "multiqc_data" / "multiqc.parquet"),
                        str(Path(location) / "*" / "*" / "multiqc_data" / "multiqc.parquet"),
                    ]

                    for pattern in patterns:
                        logger.debug(f"Searching for MultiQC files with pattern: {pattern}")
                        matches = glob(pattern)
                        logger.debug(f"Glob matches found: {matches}")
                        if matches:
                            possible_paths.extend(matches)
                            logger.info(f"Found MultiQC files in data locations: {matches}")
                            # Continue to check other patterns to find all possible files

            # Deduplicate paths before processing
            unique_paths = list(set(possible_paths))
            logger.info(
                f"Found {len(possible_paths)} total paths, {len(unique_paths)} unique paths after deduplication"
            )

            discovered_files = []
            for path in unique_paths:
                logger.debug(f"Checking for MultiQC parquet file at: {path}")
                if Path(path).exists():
                    logger.info(f"Found MultiQC parquet file: {path}")
                    # Create a minimal file object for processing
                    discovered_files.append(
                        type("File", (), {"file_location": str(Path(path).absolute())})()
                    )
                    # Continue to find ALL available files instead of stopping at first
                else:
                    logger.debug(f"MultiQC parquet file not found at: {path}")

            if not discovered_files:
                logger.warning("No MultiQC parquet files found in expected locations")
                logger.info(f"Current working directory: {Path.cwd()}")
                logger.info(f"Directory contents: {list(Path.cwd().iterdir())}")
                return {
                    "result": "error",
                    "message": "No MultiQC parquet files found. Please ensure multiqc.parquet exists in the current directory.",
                }

            files = discovered_files
            logger.info(f"Using discovered MultiQC files: {[f.file_location for f in files]}")
            logger.info(f"Total MultiQC files discovered: {len(files)}")

        # S3 storage setup
        storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)

        # Process each MultiQC parquet file and collect individual metadata
        individual_file_metadata = []
        processed_files = 0
        first_s3_location = None  # Track first S3 location for dc_specific_properties
        # (local_parquet_path, s3_location) for every file this run touched —
        # feeds the optional offline figure prerender so it can parse locally
        # and key figures by the same S3 locations the API render path uses.
        prerender_inputs: list[tuple[str, str]] = []

        logger.info(f"Starting to process {len(files)} MultiQC files...")
        parseable = [f.file_location for f in files if _is_parseable_multiqc_file(f.file_location)]

        with timed("parse"):
            parsed = _parse_multiqc_files(parseable)

        for file_path, metadata in parsed:
            if metadata is None:
                continue  # already logged by the parser
            file_size = Path(file_path).stat().st_size
            logger.info(f"Processing MultiQC file: {file_path} ({file_size} bytes)")
            individual_file_metadata.append(
                {
                    "file_path": file_path,
                    "file_size_bytes": file_size,
                    "metadata": metadata,
                    "multiqc_version": metadata.get("multiqc_version"),
                }
            )
            processed_files += 1

        if processed_files == 0:
            return {
                "result": "error",
                "message": "No MultiQC parquet files were successfully processed",
            }

        logger.info(f"Successfully processed {processed_files} MultiQC files")
        record("n_files", processed_files)

        # Calculate merged metadata for summary (but don't use for DB storage)
        all_samples = []
        all_modules = []
        all_plots = {}
        for file_meta in individual_file_metadata:
            metadata = file_meta["metadata"]
            all_samples.extend(metadata.get("samples", []))
            all_modules.extend(metadata.get("modules", []))
            all_plots.update(metadata.get("plots", {}))

        # Remove duplicates
        unique_samples = list(set(all_samples))
        unique_modules = list(set(all_modules))

        logger.info(
            f"Extracted metadata across all files: {len(unique_samples)} samples, "
            f"{len(unique_modules)} modules"
        )

        # Upload files to S3 and create individual MultiQC reports
        created_reports = []
        try:
            from depictio.models.models.multiqc_reports import MultiQCMetadata, MultiQCReport

            # S3 client (MinIO-compatible: s3v4 + path-style addressing). Raises
            # ImportError if boto3 is unavailable — caught below like before.
            s3_client = _make_s3_client(storage_options)

            logger.info(f"Processing {len(individual_file_metadata)} files individually...")

            for i, file_meta in enumerate(individual_file_metadata):
                file_path = file_meta["file_path"]
                file_size_bytes = file_meta["file_size_bytes"]
                metadata = file_meta["metadata"]
                multiqc_version = file_meta["multiqc_version"]

                try:
                    # Check if this report already exists
                    logger.info(
                        f"Checking for duplicate report {i + 1}/{len(individual_file_metadata)}"
                    )
                    logger.info(f"  Data collection ID: {data_collection.id}")
                    logger.info(f"  File path for duplicate check: {file_path}")
                    existing_report = api_check_duplicate_multiqc_report(
                        str(data_collection.id), file_path, CLI_config
                    )

                    if existing_report:
                        report_id = existing_report.get("id")
                        existing_s3_location = existing_report.get("s3_location")

                        if overwrite:
                            logger.info(
                                f"🔄 Overwrite enabled - updating existing report with ID: {report_id}"
                            )
                            logger.info(f"   Original path: {file_path}")
                            logger.info(f"   Existing S3 location: {existing_s3_location}")

                            # Rich print for non-verbose users
                            from depictio.cli.cli.utils.rich_utils import console

                            # Extract run name from file path
                            # For sequencing-runs structure: /path/to/run_id/multiqc/multiqc_data/multiqc.parquet
                            # Find the parent directory that contains 'multiqc/' subdirectory
                            file_path_obj = Path(file_path)
                            run_name = "unknown"

                            # Look for 'multiqc' in the path parts and get its parent
                            path_parts = file_path_obj.parts
                            for idx, part in enumerate(path_parts):
                                if part == "multiqc" and idx > 0:
                                    run_name = path_parts[idx - 1]
                                    break

                            # Format as run_id/filename for display
                            display_path = (
                                f"{run_name}/{file_path_obj.name}"
                                if run_name != "unknown"
                                else file_path_obj.name
                            )

                            console.print(
                                f"[yellow]🔄 Overwriting existing report:[/yellow] [cyan]{report_id}[/cyan] [dim]({display_path})[/dim]"
                            )

                            # Extract S3 key from existing S3 location to preserve path
                            # Format: s3://bucket/data_collection_id/timestamp_id/multiqc.parquet
                            if existing_s3_location:
                                try:
                                    s3_path = existing_s3_location.replace("s3://", "")
                                    if "/" in s3_path:
                                        # Skip bucket name, get the rest as s3_key
                                        s3_key = s3_path.split("/", 1)[1]
                                        logger.info(f"Preserving S3 key: {s3_key}")
                                    else:
                                        # Fallback: generate new key if parsing fails
                                        logger.warning(
                                            "Failed to parse S3 location, generating new key"
                                        )
                                        s3_key = None
                                except Exception as parse_error:
                                    logger.warning(
                                        f"Error parsing S3 location: {parse_error}, generating new key"
                                    )
                                    s3_key = None
                            else:
                                logger.warning("No existing S3 location found, generating new key")
                                s3_key = None

                            # Upload to the SAME S3 location (overwrite in S3) or create new if parsing failed
                            if not s3_key:
                                file_name = "multiqc.parquet"
                                content_hash = compute_file_hash(file_path, truncate=12)
                                s3_key = f"{str(data_collection.id)}/{content_hash}/{file_name}"
                                logger.info(f"Using new S3 key (hash-based): {s3_key}")

                            logger.info(f"Uploading file to S3: {file_path} -> {s3_key}")
                            # Use put_object to avoid multipart upload issues with MinIO
                            with open(file_path, "rb") as f, timed("upload"):
                                s3_client.put_object(
                                    Bucket=CLI_config.s3_storage.bucket,
                                    Key=s3_key,
                                    Body=f,
                                )
                            s3_location = f"s3://{CLI_config.s3_storage.bucket}/{s3_key}"
                            logger.info(f"Successfully uploaded {file_path} to {s3_location}")
                            prerender_inputs.append((file_path, s3_location))

                            # Prepare updated report data
                            metadata_for_report = {
                                k: v for k, v in metadata.items() if k != "multiqc_version"
                            }

                            multiqc_report = MultiQCReport(
                                data_collection_id=str(data_collection.id),
                                metadata=MultiQCMetadata(**metadata_for_report),
                                s3_location=s3_location,
                                original_file_path=file_path,
                                file_size_bytes=file_size_bytes,
                                multiqc_version=multiqc_version,
                                report_name=f"MultiQC Report {i + 1} - {data_collection.data_collection_tag}",
                            )

                            # UPDATE existing report instead of creating new one
                            try:
                                report_data = multiqc_report.model_dump(exclude={"id"}, mode="json")
                                logger.info(f"Updating MultiQC report {report_id}...")
                                response = api_update_multiqc_report(
                                    report_id, report_data, CLI_config
                                )

                                if response.status_code == 200:
                                    logger.info(
                                        f"✅ Successfully updated MultiQC report {report_id}"
                                    )
                                    console.print("[green]✅ Updated existing report[/green]")
                                    created_reports.append(report_id)
                                else:
                                    logger.error(
                                        f"Failed to update report: {response.status_code} - {response.text}"
                                    )
                                    console.print(
                                        "[yellow]⚠️  Warning: Failed to update report[/yellow]"
                                    )
                            except Exception as update_error:
                                logger.error(f"Error updating report: {update_error}")
                                console.print("[yellow]⚠️  Warning: Error updating report[/yellow]")

                            # Skip the normal upload and create flow (continue to next file)
                            continue
                        else:
                            logger.info(
                                f"⏭️  Skipping file {i + 1} - report already exists with ID: {report_id}"
                            )
                            logger.info(f"   Original path: {file_path}")
                            logger.info(
                                f"   Existing S3 location: {existing_report.get('s3_location', 'N/A')}"
                            )
                            logger.info("   Use --overwrite to replace this report")

                            # Rich print for non-verbose users
                            from depictio.cli.cli.utils.rich_utils import console

                            # Extract run name from file path
                            # For sequencing-runs structure: /path/to/run_id/multiqc/multiqc_data/multiqc.parquet
                            # Find the parent directory that contains 'multiqc/' subdirectory
                            file_path_obj = Path(file_path)
                            run_name = "unknown"

                            # Look for 'multiqc' in the path parts and get its parent
                            path_parts = file_path_obj.parts
                            for idx, part in enumerate(path_parts):
                                if part == "multiqc" and idx > 0:
                                    run_name = path_parts[idx - 1]
                                    break

                            # Format as run_id/filename for display
                            display_path = (
                                f"{run_name}/{file_path_obj.name}"
                                if run_name != "unknown"
                                else file_path_obj.name
                            )

                            console.print(
                                f"[cyan]⏭️  Skipping duplicate report:[/cyan] [dim]{display_path}[/dim]"
                            )
                            console.print(f"   [dim]Existing report ID: {report_id}[/dim]")
                            console.print(
                                "   [yellow]💡 Tip: Use --overwrite to replace this report[/yellow]"
                            )

                            # The skipped file's content is identical to the
                            # already-stored report (same content hash), so its
                            # local path maps to the existing S3 location — record
                            # it so a fresh-ingest prerender can still parse it.
                            if existing_s3_location:
                                prerender_inputs.append((file_path, existing_s3_location))
                            created_reports.append(report_id)
                            continue

                    # Upload this specific file to S3
                    # Use content hash to create consistent, idempotent path
                    file_name = "multiqc.parquet"
                    content_hash = compute_file_hash(file_path, truncate=12)
                    s3_key = f"{str(data_collection.id)}/{content_hash}/{file_name}"

                    logger.info(
                        f"Uploading file {i + 1}/{len(individual_file_metadata)}: {file_path}"
                    )
                    # Force single-part PUT: MinIO + path-style addressing
                    # rejects boto3 multipart CompleteMultipartUpload with
                    # AccessDenied (signature drift on the manifest XML).
                    # MultiQC parquet files are bounded (~25-50 MB), so a
                    # 5 GB threshold keeps every realistic upload single-part.
                    from boto3.s3.transfer import TransferConfig

                    _single_part_cfg = TransferConfig(multipart_threshold=5 * 1024**3)
                    with timed("upload"):
                        s3_client.upload_file(
                            file_path,
                            CLI_config.s3_storage.bucket,
                            s3_key,
                            Config=_single_part_cfg,
                        )
                    s3_location = f"s3://{CLI_config.s3_storage.bucket}/{s3_key}"
                    logger.info(f"Successfully uploaded {file_path} to {s3_location}")
                    prerender_inputs.append((file_path, s3_location))

                    # Capture first S3 location for dc_specific_properties
                    if first_s3_location is None:
                        first_s3_location = s3_location

                    # Create individual MultiQC report for this file
                    # Extract metadata dict (removing multiqc_version for separate field)
                    metadata_for_report = {
                        k: v for k, v in metadata.items() if k != "multiqc_version"
                    }

                    multiqc_report = MultiQCReport(
                        data_collection_id=str(data_collection.id),
                        metadata=MultiQCMetadata(**metadata_for_report),
                        s3_location=s3_location,
                        original_file_path=file_path,
                        file_size_bytes=file_size_bytes,
                        multiqc_version=multiqc_version,
                        report_name=f"MultiQC Report {i + 1} - {data_collection.data_collection_tag}",
                    )

                    # Save individual MultiQC report to MongoDB via API call
                    try:
                        # Convert MultiQC report to dictionary for API call
                        report_data = multiqc_report.model_dump(exclude={"id"}, mode="json")

                        logger.info(f"Saving MultiQC report {i + 1} to database via API...")
                        logger.debug(f"Report data being sent: {report_data}")

                        response = api_create_multiqc_report(report_data, CLI_config)

                        logger.info(f"API Response: status={response.status_code}")
                        logger.debug(f"API Response headers: {dict(response.headers)}")
                        logger.debug(f"API Response text: {response.text}")

                        if response.status_code == 200:
                            try:
                                saved_report = response.json()
                                report_id = saved_report.get("report", {}).get("id")
                                logger.info(
                                    f"✅ MultiQC report {i + 1} saved successfully with ID: {report_id}"
                                )
                                created_reports.append(report_id)

                                logger.info(
                                    f"Report {i + 1} metadata: {len(metadata.get('samples', []))} samples, {len(metadata.get('modules', []))} modules"
                                )

                            except Exception as json_error:
                                logger.error(
                                    f"Failed to parse API response JSON for report {i + 1}: {json_error}"
                                )
                                logger.debug(f"Raw response: {response.text}")
                        else:
                            logger.error(
                                f"❌ Failed to save MultiQC report {i + 1}: HTTP {response.status_code}"
                            )
                            logger.error(f"Response body: {response.text}")
                            try:
                                error_detail = response.json()
                                logger.error(f"Error details: {error_detail}")
                            except Exception:
                                logger.error("Could not parse error response as JSON")

                    except Exception as e:
                        logger.warning(f"Failed to save MultiQC report {i + 1} to database: {e}")

                except Exception as e:
                    logger.error(f"Failed to process file {i + 1} ({file_path}): {e}")
                    continue

        except ImportError:
            logger.error("boto3 not available. Please install boto3: pip install boto3")
        except Exception as e:
            logger.error(f"Unexpected error during file processing: {e}")

        logger.info(f"Created {len(created_reports)} MultiQC reports in database")

        # Update the data collection's dc_specific_properties with extracted metadata via API
        try:
            from depictio.cli.cli.utils.api_calls import api_update_dc_specific_properties

            logger.info(f"Updating data collection {data_collection.id} with extracted metadata")
            logger.info(f"Samples: {len(unique_samples)}")
            logger.info(f"Modules: {len(unique_modules)}")
            logger.info(f"Plots: {len(all_plots)} plot groups")
            logger.info(f"S3 location: {first_s3_location}")
            logger.info(f"Individual MultiQC reports created: {len(created_reports)}")

            properties = {
                "samples": unique_samples,
                "modules": unique_modules,
                "plots": all_plots,
                "s3_location": first_s3_location,
                "processed_files": processed_files,
                "file_size_bytes": sum(f["file_size_bytes"] for f in individual_file_metadata),
            }

            response = api_update_dc_specific_properties(
                data_collection_id=str(data_collection.id),
                properties=properties,
                CLI_config=CLI_config,
            )

            if response.status_code == 200:
                logger.info("Updated dc_specific_properties with MultiQC metadata")
            else:
                logger.warning(
                    f"Failed to update dc_specific_properties: HTTP {response.status_code} - {response.text}"
                )

        except Exception as e:
            logger.error(f"Failed to update dc_specific_properties: {e}")

        # Optional offline figure prerender: build the aggregated Plotly figures
        # here (the reports are already parsed) and ship them to S3 so the viewer
        # serves them without the API ever calling multiqc.parse_logs/get_plot.
        # Opt-in, best-effort — a failure never fails the ingest.
        if multiqc_prerender_enabled():
            try:
                with timed("prerender"):
                    _prerender_multiqc_figures(
                        data_collection, CLI_config, prerender_inputs, storage_options
                    )
            except Exception as e:
                logger.warning(
                    f"MultiQC figure prerender skipped ({e}); Celery fallback will build"
                )

        # Display rich summary table
        try:
            # Create list of processed file paths for summary
            processed_file_paths = [
                file_meta["file_path"] for file_meta in individual_file_metadata
            ]

            rich_print_multiqc_processing_summary(
                processed_files=processed_files,
                total_samples=len(unique_samples),
                total_modules=len(unique_modules),
                plots_info=all_plots,
                file_paths=processed_file_paths,
                data_collection_tag=data_collection.data_collection_tag,
            )
        except Exception as e:
            logger.warning(f"Failed to display rich summary table: {e}")

        return {
            "result": "success",
            "message": f"Processed {processed_files} MultiQC files and created {len(created_reports)} individual reports",
            "metadata": {
                "samples": unique_samples,
                "modules": unique_modules,
                "plots": all_plots,
                "processed_files": processed_file_paths,
                "created_reports": created_reports,
            },
        }

    except Exception as e:
        logger.error(f"Failed to process MultiQC data collection: {e}")
        return {"result": "error", "message": f"Failed to process MultiQC data collection: {e}"}
