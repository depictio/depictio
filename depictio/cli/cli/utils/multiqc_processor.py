"""
MultiQC processing utilities for extracting metadata from parquet files.
Uses MultiQC Python module to extract samples, modules, and plots.
"""

from pathlib import Path
from typing import Any, Dict

from depictio.cli.cli.utils.api_calls import (
    api_check_duplicate_multiqc_report,
    api_create_multiqc_report,
    api_update_multiqc_report,
)
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

        # Extract MultiQC version from the installed module
        multiqc_version = None
        try:
            multiqc_version = multiqc.__version__
            logger.info(f"Detected MultiQC version: {multiqc_version}")
        except AttributeError:
            logger.warning("Could not detect MultiQC version from module")

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
        if multiqc_version:
            logger.info(f"MultiQC version: {multiqc_version}")

        return metadata

    except ImportError:
        logger.error("MultiQC module not available. Please install MultiQC: pip install multiqc")
        raise
    except Exception as e:
        logger.error(f"Failed to extract MultiQC metadata from {parquet_path}: {e}")
        raise


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

        logger.info(f"Starting to process {len(files)} MultiQC files...")
        for i, file_obj in enumerate(files, 1):
            file_path = file_obj.file_location
            if not file_path.endswith(".parquet"):
                logger.warning(f"Skipping non-parquet file: {file_path}")
                continue

            if not Path(file_path).exists():
                logger.error(f"File not found: {file_path}")
                continue

            try:
                # Extract MultiQC metadata from parquet file
                logger.info(f"Processing file {i}/{len(files)}: {file_path}")
                logger.info(f"Extracting metadata from: {file_path}")
                metadata = extract_multiqc_metadata(file_path)

                # Get file size for metadata
                file_size = Path(file_path).stat().st_size
                logger.info(f"Processing MultiQC file: {file_path} ({file_size} bytes)")

                # Store individual file metadata for creating separate reports
                individual_file_metadata.append(
                    {
                        "file_path": file_path,
                        "file_size_bytes": file_size,
                        "metadata": metadata,
                        "multiqc_version": metadata.get("multiqc_version"),
                    }
                )

                processed_files += 1

            except Exception as e:
                logger.error(f"Failed to process MultiQC file {file_path}: {e}")
                continue

        if processed_files == 0:
            return {
                "result": "error",
                "message": "No MultiQC parquet files were successfully processed",
            }

        logger.info(f"Successfully processed {processed_files} MultiQC files")

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
            from datetime import datetime

            import boto3

            from depictio.models.models.multiqc_reports import MultiQCMetadata, MultiQCReport

            # Create S3 client with storage options
            s3_client = boto3.client(
                "s3",
                endpoint_url=storage_options.endpoint_url,
                aws_access_key_id=storage_options.aws_access_key_id,
                aws_secret_access_key=storage_options.aws_secret_access_key,
                region_name=storage_options.region,
            )

            # Generate unique timestamp for this processing run
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds

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
                                s3_key = (
                                    f"{str(data_collection.id)}/{timestamp}_{i + 1}/{file_name}"
                                )
                                logger.info(f"Using new S3 key: {s3_key}")

                            logger.info(f"Uploading file to S3: {file_path} -> {s3_key}")
                            s3_client.upload_file(file_path, CLI_config.s3_storage.bucket, s3_key)
                            s3_location = f"s3://{CLI_config.s3_storage.bucket}/{s3_key}"
                            logger.info(f"Successfully uploaded {file_path} to {s3_location}")

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

                            created_reports.append(report_id)
                            continue

                    # Upload this specific file to S3
                    # Use timestamp + index to create unique path, but keep filename as multiqc.parquet
                    file_name = "multiqc.parquet"
                    s3_key = f"{str(data_collection.id)}/{timestamp}_{i + 1}/{file_name}"

                    logger.info(
                        f"Uploading file {i + 1}/{len(individual_file_metadata)}: {file_path}"
                    )
                    s3_client.upload_file(file_path, CLI_config.s3_storage.bucket, s3_key)
                    s3_location = f"s3://{CLI_config.s3_storage.bucket}/{s3_key}"
                    logger.info(f"Successfully uploaded {file_path} to {s3_location}")

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

        # Update the data collection's dc_specific_properties with extracted metadata
        try:
            # Prepare updated configuration
            updated_dc_config = data_collection.config.model_copy()

            # Update dc_specific_properties with MultiQC metadata
            if hasattr(updated_dc_config, "dc_specific_properties"):
                # Update existing dc_specific_properties with merged metadata
                updated_dc_config.dc_specific_properties.samples = unique_samples
                updated_dc_config.dc_specific_properties.modules = unique_modules
                updated_dc_config.dc_specific_properties.plots = all_plots

                # Add MultiQC-specific fields
                updated_dc_config.dc_specific_properties.processed_files = processed_files
                updated_dc_config.dc_specific_properties.file_size_bytes = sum(
                    file_meta["file_size_bytes"] for file_meta in individual_file_metadata
                )

                logger.info(
                    f"Updating data collection {data_collection.id} with extracted metadata"
                )
                logger.info(f"Samples: {len(unique_samples)}")
                logger.info(f"Modules: {len(unique_modules)}")
                logger.info(f"Individual MultiQC reports created: {len(created_reports)}")

                # TODO: Implement actual API call to update data collection
                # result = api_update_data_collection(
                #     data_collection_id=str(data_collection.id),
                #     updated_config=updated_dc_config,
                #     CLI_config=CLI_config
                # )
                logger.info("Data collection metadata update prepared (API call pending)")

            else:
                logger.warning("Data collection does not have dc_specific_properties field")

        except Exception as e:
            logger.error(f"Failed to update data collection metadata: {e}")

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
