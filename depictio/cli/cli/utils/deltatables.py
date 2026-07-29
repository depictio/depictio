import os
from datetime import datetime
from typing import Any

import polars as pl
from pydantic import validate_call

from depictio.cli.cli.utils.api_calls import (
    api_get_files_by_dc_id,
    api_upsert_deltatable,
)
from depictio.cli.cli.utils.common import cli_version as _cli_version
from depictio.cli.cli.utils.delta_versioning import (
    MAX_RUN_TAGS_IN_METADATA,
    RUN_ID_COLUMN,
    ScopedWritePlan,
    build_commit_metadata,
    plan_partitioning,
    plan_scoped_write,
    probe_delta_table,
    write_delta_table_versioned,
)
from depictio.cli.cli.utils.multiqc_processor import process_multiqc_data_collection
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
from depictio.models.content_digest import compute_file_sha256, content_key
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.files import File
from depictio.models.models.s3 import PolarsStorageOptions
from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options


def calculate_dataframe_size_bytes(df: pl.DataFrame) -> int:
    """
    Calculate the memory size of a Polars DataFrame in bytes using Polars' native estimated_size method.

    Args:
        df (pl.DataFrame): The Polars DataFrame to calculate size for

    Returns:
        int: Estimated size in bytes of the DataFrame in memory
    """
    try:
        # Use Polars' native estimated_size method (available in Polars >= 0.20.0)
        size_bytes = int(df.estimated_size("b"))  # 'b' for bytes
        logger.info(
            f"Calculated DataFrame size: {size_bytes} bytes ({size_bytes / (1024 * 1024):.2f} MB)"
        )
        return size_bytes
    except Exception as e:
        logger.warning(f"Could not calculate DataFrame size using estimated_size: {e}")
        # Simple fallback: rough estimate based on shape
        estimated_size = df.height * len(df.columns) * 8  # 8 bytes per cell average
        logger.info(f"Using fallback size estimate: {estimated_size} bytes")
        return estimated_size


class NoFilesForRunsError(Exception):
    """A run-restricted fetch found nothing left to read."""


@validate_call
def fetch_file_data(
    dc_id: str, CLI_config: CLIConfig, run_tags: set[str] | None = None
) -> list[File]:
    """
    Call the API to list files for the given DataCollection.

    Args:
        dc_id (str): Data Collection ID.
        CLI_config (CLIConfig): CLI configuration containing API URL and credentials.
        run_tags: Restrict to files belonging to these runs. Filtering happens on
            the raw documents, before ``File`` construction and before the
            existence check below — both of which cost syscalls per file.

    Returns:
        list: List of file dictionaries returned by the API.

    Raises:
        Exception: If the API call fails or returns no files.
    """
    response = api_get_files_by_dc_id(dc_id, CLI_config)
    if response.status_code != 200:
        error_msg = f"Error fetching files for Data Collection {dc_id}: {response.text}"
        logger.error(error_msg)
        raise Exception(error_msg)

    files_data = response.json()
    logger.info(f"Retrieved {len(files_data)} file(s) for Data Collection {dc_id}.")

    if run_tags is not None:
        total = len(files_data)
        files_data = [fd for fd in files_data if str(fd.get("run_tag")) in run_tags]
        logger.info(
            f"Restricted to {len(files_data)} of {total} file(s) "
            f"across {len(run_tags)} changed run(s)."
        )
        if not files_data:
            # Every file of the changed runs is gone. A scoped write cannot
            # express "these rows should no longer exist" — writing an empty
            # frame under a predicate is not the same thing — so this has to
            # become a full rebuild, which drops them naturally.
            raise NoFilesForRunsError(
                f"none of the {len(run_tags)} changed run(s) still have files"
            )

    if not files_data:
        error_msg = f"No files found for Data Collection {dc_id}."
        logger.debug(
            error_msg
        )  # Changed from ERROR to DEBUG - this is expected for some data collection types
        raise Exception(error_msg)

    # Filter out stale file records whose paths no longer exist locally
    # (happens when re-running with a different template or data_root)
    valid_files_data = []
    for fd in files_data:
        loc = fd.get("file_location", "")
        if os.path.exists(loc):
            valid_files_data.append(fd)
        else:
            logger.warning(f"Skipping stale file record (path does not exist): {loc}")
    if not valid_files_data:
        error_msg = f"No valid files found for Data Collection {dc_id} (all file paths are stale)."
        logger.error(error_msg)
        raise Exception(error_msg)
    files_data = valid_files_data

    files = convert_to_file_objects(files_data)

    # Deduplicate by file_location (guards against duplicate registrations from race conditions)
    seen: set[str] = set()
    unique_files = []
    for f in files:
        if f.file_location not in seen:
            seen.add(f.file_location)
            unique_files.append(f)
    if len(unique_files) < len(files):
        logger.warning(
            f"Deduplicated {len(files) - len(unique_files)} duplicate file(s) for DC {dc_id}"
        )
    files = unique_files

    logger.info(f"Retrieved {len(files)} file(s) for Data Collection {dc_id}.")
    return files


@validate_call
def convert_to_file_objects(files_data: list) -> list:
    """
    Convert file dictionaries to validated File objects using File.from_mongo().

    Args:
        files_data (list): List of file dictionaries.

    Returns:
        list: List of validated File objects.

    Raises:
        Exception: If conversion fails.
    """
    try:
        # Should break if any of the files is not a valid File object - including file_location validation
        files = [File.from_mongo(file_dict) for file_dict in files_data]
    except Exception as e:
        error_msg = f"Error converting file dictionaries to File objects: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    return files


def read_single_file_lazy(file_info: File, file_format: str, polars_kwargs: dict) -> pl.LazyFrame:
    """
    Lazily scan a single file into a Polars LazyFrame according to the specified format.

    Args:
        file_info (File): A validated File object.
        file_format (str): The file format (e.g. csv, parquet).
        polars_kwargs (dict): Additional keyword arguments for the Polars scanner.

    Returns:
        pl.LazyFrame: The lazy DataFrame representation of the file.

    Raises:
        Exception: If file scanning fails.
    """
    file_path = file_info.file_location
    logger.debug(f"Scanning file lazily: {file_path}")
    logger.debug(f"File format: {file_format}")
    logger.debug(f"Polars kwargs: {polars_kwargs}")

    try:
        if file_format in ["csv", "tsv", "txt"]:
            effective_kwargs = dict(polars_kwargs)
            if "separator" not in effective_kwargs:
                # Pick the delimiter from the on-disk extension first, falling
                # back to the declared format when the extension is ambiguous.
                # nf-core pipelines emit samplesheets/metadata as either .csv or
                # .tsv depending on the user's input, so a DC declared "CSV" may
                # actually point at a tab-separated file — without this a .tsv
                # lands as one comma-joined column. A `.csv` extension keeps the
                # comma default; an extensionless path uses the declared format.
                path_str = str(file_path)
                suffix = path_str.rsplit(".", 1)[-1].lower() if "." in path_str else ""
                if suffix in ("tsv", "tab"):
                    effective_kwargs["separator"] = "\t"
                elif suffix != "csv" and file_format == "tsv":
                    effective_kwargs["separator"] = "\t"
            lf = pl.scan_csv(file_path, **effective_kwargs)
        elif file_format == "parquet":
            lf = pl.scan_parquet(file_path, **polars_kwargs)
        elif file_format == "feather":
            lf = pl.scan_ipc(file_path, **polars_kwargs)
        elif file_format in ["xls", "xlsx"]:
            # Polars does not natively support lazy Excel scans.
            # In this case, read eagerly and convert to lazy.
            df = pl.read_excel(file_path, **polars_kwargs)
            lf = df.lazy()
        else:
            error_msg = f"Unsupported file format: {file_format}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Optionally, add a column from file_info if available (e.g., run_id)
        if hasattr(file_info, "run_id"):
            lf = lf.with_columns(pl.lit(str(file_info.run_tag)).alias("depictio_run_id"))
        return lf

    except Exception as e:
        error_msg = f"Error scanning file {file_path}: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)


def read_files_lazy(files: list, file_format: str, polars_kwargs: dict) -> list:
    """
    Lazily read all files into Polars LazyFrames.

    Args:
        files (list): List of validated File objects.
        file_format (str): Format of the files.
        polars_kwargs (dict): Additional keyword arguments for the Polars scanners.

    Returns:
        list: List of Polars LazyFrames.
    """
    lazy_frames = []
    for file_info in files:
        lf = read_single_file_lazy(file_info, file_format, polars_kwargs)
        lazy_frames.append(lf)
    if not lazy_frames:
        error_msg = "No LazyFrames were generated from the files."
        logger.error(error_msg)
        raise Exception(error_msg)
    return lazy_frames


class SchemaConflictError(Exception):
    """A partial frame's column type disagrees with the table it would join.

    Only raised for scoped writes. Coercing there would leave the runs that were
    *not* rewritten sitting in the old type under a schema claiming the new one
    — which delta-rs turns into an unreadable table. Rebuilding every run in one
    consistent type is the correct answer, and the caller does exactly that.
    """


def align_lazy_schemas(lazy_frames: list, target_schema: dict | None = None) -> list:
    """
    Align column types across all LazyFrames for aggregation.

    This function computes the union of all columns and their desired data types,
    then adjusts each LazyFrame by selecting (and casting) columns accordingly.

    Args:
        lazy_frames (list): List of Polars LazyFrames.
        target_schema: The existing Delta table's schema, when this batch is
            only part of that table. Columns it already has are kept at their
            existing type and order-insensitively re-added when this batch does
            not carry them; a genuine type disagreement raises rather than
            silently coercing.

    Returns:
        list: List of LazyFrames with aligned schemas.
    """
    # Compute the union of all column names and decide on a type per column.
    unified_schema = {}
    for lf in lazy_frames:
        # Use the known schema from the LazyFrame (a dict: {col: dtype})
        schema = lf.collect_schema()
        for col, dtype in schema.items():
            if col not in unified_schema:
                unified_schema[col] = dtype
            else:
                # If types differ, default to Utf8
                if unified_schema[col] != dtype:
                    unified_schema[col] = pl.Utf8

    if target_schema is not None:
        conflicts = [
            f"{col} is {unified_schema[col]} here but {dtype} in the table"
            for col, dtype in target_schema.items()
            if col in unified_schema and unified_schema[col] != dtype
        ]
        if conflicts:
            raise SchemaConflictError("; ".join(conflicts))
        # Columns this batch does not carry stay in the frame as typed nulls, so
        # the write cannot narrow the table. Matching is by name: delta-rs 0.24
        # and 1.6 order the partition column differently.
        for col, dtype in target_schema.items():
            unified_schema.setdefault(col, dtype)

    # Adjust each lazy frame: for missing columns, add a literal null; for existing columns, cast.
    aligned_lfs = []
    for lf in lazy_frames:
        # Resolve the frame's columns once (was re-collecting the schema for
        # every column in the inner loop) and use a set for O(1) membership.
        column_names = set(lf.collect_schema().names())
        exprs = []
        for col, dtype in unified_schema.items():
            if col in column_names:
                exprs.append(pl.col(col).cast(dtype).alias(col))
            else:
                # Create a null literal for the missing column.
                exprs.append(pl.lit(None).cast(dtype).alias(col))
        aligned_lfs.append(lf.select(exprs))
    return aligned_lfs


def aggregate_lazy_dataframes(lazy_frames: list, target_schema: dict | None = None) -> pl.DataFrame:
    """
    Concatenate LazyFrames (after aligning schemas) and add an aggregation timestamp.

    The concatenation is done lazily and the final DataFrame is materialized at the end.

    Args:
        lazy_frames (list): List of Polars LazyFrames.
        target_schema: Existing table schema to align against, for a partial batch.

    Returns:
        pl.DataFrame: The aggregated DataFrame (materialized).
    """
    logger.debug("Aligning LazyFrame schemas.")
    aligned_lfs = align_lazy_schemas(lazy_frames, target_schema=target_schema)
    logger.debug("Concatenating LazyFrames.")
    # Concatenate all lazy frames into one lazy frame.
    concatenated_lf = pl.concat(aligned_lfs)
    # Add an aggregation timestamp column lazily.
    concatenated_lf = concatenated_lf.with_columns(
        pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).alias("aggregation_time")
    )
    # Materialize the lazy operations.
    try:
        aggregated_df: pl.DataFrame = concatenated_lf.collect()  # type: ignore[unresolved-attribute]
        return aggregated_df

    except Exception as e:
        error_msg = f"Error collecting concatenated LazyFrame: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)


def write_delta_table(
    aggregated_df: pl.DataFrame,
    destination_file: str,
    storage_options: PolarsStorageOptions,
    *,
    write_mode: str = "overwrite",
    commit_metadata: dict[str, str] | None = None,
    partition: bool = False,
    replace_run_tags: list[str] | None = None,
    scoped: bool = False,
) -> dict:
    """
    Write the aggregated DataFrame as a Delta Lake table.

    Thin wrapper over :func:`write_delta_table_versioned` that keeps the
    historical dict return shape for the three existing call sites (standard
    aggregation, recipes, joins). The defaults reproduce the previous behaviour
    exactly — a full overwrite, no commit metadata, no partitioning — and the
    dict simply gains the commit facts observed after the write.

    Args:
        aggregated_df (pl.DataFrame): The aggregated DataFrame.
        destination_file (str): The destination path for the Delta table.
        write_mode: overwrite | append | replace-runs.
        commit_metadata: depictio provenance to stamp into the Delta commit.
        partition: Whether to partition by ``depictio_run_id``.
        replace_run_tags: Runs the overwrite is scoped to, for ``replace-runs``.
        scoped: The frame holds only some of the table's runs.

    Raises:
        Exception: If writing the Delta table fails.
    """
    logger.debug(f"Writing aggregated DataFrame to Delta table at {destination_file}.")
    logger.debug(f"Aggregated DataFrame schema: {aggregated_df.schema}")
    logger.debug(f"Storage options: {storage_options}")

    outcome = write_delta_table_versioned(
        aggregated_df,
        destination_file,
        storage_options,
        write_mode=write_mode,  # type: ignore[arg-type]
        commit_metadata=commit_metadata,
        partition=partition,
        replace_run_tags=replace_run_tags,
        scoped=scoped,
    )

    return {
        "result": outcome.result,
        "message": outcome.message,
        "delta_version": outcome.delta_version,
        "delta_commit_timestamp": outcome.delta_timestamp,
        "write_mode": outcome.write_mode,
        # A scoped write only ever saw part of the table, so it knows how many
        # rows it wrote and nothing about the total. Reporting the subset as
        # `rows_total` would publish a wrong row count to the history UI.
        "rows_total": None if scoped else outcome.rows_written,
        "rows_added": outcome.rows_written if scoped else None,
        "partitioned": outcome.partitioned,
    }


def read_delta_table(
    destination_file: str, storage_options: PolarsStorageOptions
) -> dict[str, str | pl.DataFrame]:
    """
    Read a Delta Lake table into a DataFrame.

    Args:
        destination_file (str): The path to the Delta table.

    Returns:
        pl.DataFrame: The DataFrame representation of the Delta table.

    Raises:
        Exception: If reading the Delta table fails.
    """
    opts = storage_options.model_dump()
    try:
        df = pl.read_delta(destination_file, storage_options=opts)
        logger.debug(f"Delta table read from {destination_file}.")
        return {
            "result": "success",
            "message": f"Delta table read from {destination_file}.",
            "data": df,
        }
    except Exception as e:
        # polars.read_delta is broken against deltalake>=0.24 (Schema object
        # is no longer iterable). Fall back to DeltaTable->pyarrow->polars,
        # which round-trips cleanly.
        if "Schema" in str(e) and "not iterable" in str(e):
            try:
                from deltalake import DeltaTable

                dt = DeltaTable(destination_file, storage_options=opts)
                df = pl.from_arrow(dt.to_pyarrow_table())
                logger.debug(f"Delta table read from {destination_file} via pyarrow fallback.")
                return {
                    "result": "success",
                    "message": f"Delta table read from {destination_file} (pyarrow fallback).",
                    "data": df,
                }
            except Exception as e2:
                error_msg = f"Issue when reading Delta table (pyarrow fallback): {e2}"
                logger.warning(error_msg)
                return {"result": "error", "message": error_msg}
        error_msg = f"Issue when reading Delta table: {e}"
        logger.warning(error_msg)
        return {"result": "error", "message": error_msg}


def skip_unchanged_reason(
    data_collection: DataCollection,
    probe,
    command_parameters: dict,
) -> str | None:
    """Why this data collection can be left alone this cycle, or None to process it.

    Every condition has to hold, and each of them exists because skipping on a
    wrong answer means a Delta table that silently never catches up:

    * the caller asked for skipping at all. The watcher only asks after a cycle
      that succeeded, so a failed cycle is always followed by a full one and the
      whole mechanism is self-healing;
    * the scan signal is ``complete`` — every run on disk was either scanned or
      proven unchanged. Without ``--rescan-folders`` it is a guess, not a fact;
    * this collection was actually covered by that scan. Single-file
      collections, MultiQC, recipes and joins never are, and reach this function
      only to be told to carry on;
    * no run disappeared. A removal has to be rebuilt, not skipped;
    * nothing in this collection changed;
    * the table is really there. A first ingestion, or one whose write failed
      halfway, has no version to leave alone.
    """
    if not command_parameters.get("skip_unchanged"):
        return None

    signal = command_parameters.get("scan_signal") or {}
    if not signal.get("complete"):
        return None

    dc_id = str(data_collection.id)
    if dc_id not in set(signal.get("covered_dcs") or []):
        return None
    if signal.get("removed_runs"):
        return None
    if dc_id in (signal.get("changed_dcs") or {}):
        return None
    if probe is None:
        return None

    return f"no file changed; Delta table left at version {probe.version}"


def client_aggregate_data(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    command_parameters: dict = {},
    workflow=None,  # Optional workflow for MultiQC processing
) -> dict[str, Any]:
    """
    Aggregate files from a DataCollection into a Delta Lake object or handle MultiQC files.

    For MultiQC data collections:
      - Copies parquet files directly to S3
      - Extracts metadata using MultiQC module
      - Updates data collection with extracted metadata

    For other data collections:
      - Lists files using the provided Data Collection ID.
      - Converts file dictionaries into validated File objects.
      - Reads each file into a Polars DataFrame based on the metadata.
      - Aligns the DataFrame schemas and aggregates them.
      - Writes the aggregated DataFrame as a Delta Lake table.

    Args:
        data_collection: The DataCollection object containing type and configuration.
        CLI_config (CLIConfig): CLI configuration object containing API URL and credentials.
        command_parameters: Optional command parameters including overwrite flag.

    Returns:
        dict: Result dictionary with success/error status and message.
    """

    command_parameters = command_parameters or {}
    if command_parameters:
        overwrite = command_parameters.get("overwrite", False)
        rich_tables = command_parameters.get("rich_tables", False)
        preview_recipes = command_parameters.get("preview_recipes", False)
        write_mode = command_parameters.get("write_mode", "overwrite")
    else:
        overwrite = False
        write_mode = "overwrite"
        preview_recipes = False

    # Handle MultiQC data collections specially - copy parquet files to S3 and extract metadata
    if data_collection.config.type.lower() == "multiqc":
        return process_multiqc_data_collection(data_collection, CLI_config, overwrite, workflow)

    # Handle GeoJSON data collections - upload file to S3 and store location
    if data_collection.config.type.lower() == "geojson":
        return process_geojson_data_collection(data_collection, CLI_config, overwrite)

    # Phylogeny DCs have no delta table, but the tree file now goes to object
    # storage rather than being referenced where it happened to be scanned.
    if data_collection.config.type.lower() == "phylogeny":
        return process_phylogeny_data_collection(data_collection, CLI_config, overwrite)

    # Handle transformed (recipe-based) data collections.
    # Init seeding for reference datasets pops the `transform` block while
    # keeping `source: transformed` so the React viewer can still surface the
    # recipe-derived lineage — those DCs already have a `scan` block pointing
    # at the pre-computed seed file, so fall through to the regular file-scan
    # path instead of erroring.
    if (
        data_collection.config.source == "transformed"
        and data_collection.config.transform is not None
    ):
        return process_recipe_data_collection(
            data_collection,
            CLI_config,
            overwrite,
            workflow,
            preview=preview_recipes,
            command_parameters=command_parameters,
        )

    # Generate destination prefix using the data collection id - should be a S3 path
    destination_prefix = f"s3://{CLI_config.s3_storage.bucket}/{str(data_collection.id)}"
    logger.debug(f"Destination prefix: {destination_prefix}")
    # logger.info(f"Destination prefix: {destination_prefix}")

    # Check if existing Delta table exists and is accessible
    storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)
    logger.debug(f"Storage options: {storage_options}")
    # logger.info(f"Storage options: {storage_options}")

    # if destination_prefix is not a valid S3 path, raise an error
    if not destination_prefix.startswith("s3://"):
        raise ValueError("Invalid destination prefix. It should be an S3 path.")

    # Metadata only. This used to be a full eager read of the whole table whose
    # result was logged at head(5) and thrown away — one complete download per
    # data collection per cycle to decide a boolean.
    logger.info("Checking if destination Delta table exists.")
    probe = probe_delta_table(
        destination_prefix,
        storage_options,
        # The schema is only needed to align a partial frame against the table
        # that is already there, so it is only fetched when that is on the table.
        with_schema=bool(command_parameters.get("incremental_write")),
    )
    destination_exists = probe is not None
    if probe:
        logger.debug(
            f"Existing Delta table found at version {probe.version} "
            f"(partitioned by {probe.partition_columns or 'nothing'})"
        )
    else:
        logger.info("Destination does not exist yet, will create it during processing")

    # Nothing in this collection moved: leave its table exactly where it is.
    # This is the difference between a quiet watcher cycle costing one metadata
    # read per collection and costing a full rebuild of every table in the
    # project. Said out loud rather than logged at debug, because a silent skip
    # is indistinguishable from a silent failure.
    skip_reason = skip_unchanged_reason(data_collection, probe, command_parameters)
    if skip_reason:
        rich_print_checked_statement(
            f"Skipped {data_collection.data_collection_tag}: {skip_reason}", "info"
        )
        logger.info(f"Skipping {data_collection.data_collection_tag}: {skip_reason}")
        return {
            "result": "success",
            "skipped": True,
            "message": f"Left unchanged: {skip_reason}.",
        }

    # if destination_exists:

    if destination_exists and not overwrite:
        logger.debug("Destination already exists, overwrite mode is disabled")

        from depictio.cli.cli.utils.rich_utils import console

        console.print("[yellow]⚠️  Destination already exists and overwrite is disabled[/yellow]")
        console.print(f"   [dim]Destination: {destination_prefix}[/dim]")
        console.print("   [cyan]💡 Tip: Use --overwrite flag to replace existing data[/cyan]")

        return {
            "result": "error",
            "message": f"Destination {destination_prefix} already exists and overwrite is disabled. Use --overwrite to replace.",
        }

    dc_id = data_collection.id
    data_collection_config = data_collection.config
    # logger.info(f"Data Collection ID: {dc_id}")
    logger.debug(f"Aggregating data for Data Collection {dc_id}.")
    logger.debug(f"Data Collection config: {data_collection_config}")

    # 1. Decide the scope of this write *before* fetching anything. A frame
    # restricted to the runs that changed must only ever be built once a
    # partitioned, predicate-scoped write is guaranteed — see plan_scoped_write.
    signal = command_parameters.get("scan_signal") or {}
    plan = plan_scoped_write(
        probe=probe,
        changed_runs=(signal.get("changed_dcs") or {}).get(str(data_collection.id), []),
        removed_runs=list(signal.get("removed_runs") or []),
        write_mode=write_mode,
        incremental_write=bool(command_parameters.get("incremental_write")),
        signal_complete=bool(signal.get("complete")),
        covered=str(data_collection.id) in set(signal.get("covered_dcs") or []),
    )
    if plan.declined and command_parameters.get("incremental_write"):
        logger.info(f"Rebuilding {data_collection.data_collection_tag} in full: {plan.declined}")

    # 2. Read the files this write covers, and aggregate them
    data_collection_config = convert_objectid_to_str(data_collection_config.model_dump())
    logger.debug(f"Data Collection config: {data_collection_config}")
    dc_props = data_collection_config.get("dc_specific_properties", {})
    file_format = dc_props.get("format", "csv").lower()
    polars_kwargs = dict(dc_props.get("polars_kwargs", {}))

    def _build(run_tags: set[str] | None, target_schema: dict | None):
        collected = fetch_file_data(str(dc_id), CLI_config, run_tags=run_tags)
        frames = read_files_lazy(collected, file_format, polars_kwargs)
        return collected, aggregate_lazy_dataframes(frames, target_schema=target_schema)

    if plan.scoped:
        try:
            files, aggregated_df = _build(set(plan.run_tags), probe.schema if probe else None)
        except (SchemaConflictError, NoFilesForRunsError) as exc:
            # Both are found before anything large is read — the type conflict
            # from the lazy frames' headers, the empty fetch from the file list
            # — so the retry costs one more listing, not a re-read.
            logger.warning(
                f"{data_collection.data_collection_tag}: {exc}. Rebuilding every run instead."
            )
            plan = ScopedWritePlan(scoped=False, declined=str(exc))
            files, aggregated_df = _build(None, None)
    else:
        files, aggregated_df = _build(None, None)

    logger.debug(f"Aggregated DataFrame shape: {aggregated_df.shape}")
    logger.debug(f"Aggregated DataFrame schema: {aggregated_df.schema}")
    logger.info(f"Aggregated DataFrame head: {aggregated_df.head(5)}")

    # 5. Write the aggregated DataFrame to Delta Lake
    if destination_exists:
        rich_print_checked_statement("Overwriting existing Delta table", "info")
        logger.info("Overwriting existing Delta table")
    else:
        rich_print_checked_statement(
            "S3 Destination does not exist, will create it during processing", "info"
        )
        logger.info("S3 Destination does not exist, will create it during processing")

    run_tags = (
        [str(tag) for tag in aggregated_df[RUN_ID_COLUMN].unique().to_list() if tag is not None]
        if RUN_ID_COLUMN in aggregated_df.columns
        else []
    )

    if plan.scoped:
        # Already decided, and not up for renegotiation: plan_partitioning's
        # fall-back is a full overwrite, which with this frame would delete
        # every run it does not contain.
        partition = True
        replace_run_tags = plan.run_tags
    else:
        # Decide the write strategy. plan_partitioning declines — with a reason —
        # whenever partitioning would fail or make things worse (no run column,
        # a single run, path-unsafe tags, too many partitions, or an existing table
        # with different partitioning, which delta-rs rejects outright).
        partition, decline_reason = plan_partitioning(
            aggregated_df,
            destination_prefix,
            storage_options,
            write_mode,
            repartition=bool(command_parameters.get("repartition")),
            probe=probe,
        )
        replace_run_tags = run_tags if partition else None
        if decline_reason and write_mode == "replace-runs":
            logger.warning(
                f"Falling back to a full overwrite for {data_collection.data_collection_tag}: "
                f"{decline_reason}"
            )

    # Size: from the frame for a full rewrite, since the frame *is* the table.
    # A scoped write only holds part of it, so the table's real size comes from
    # the Delta metadata instead — shrinking the stored size to the subset's
    # would be a straightforward lie.
    if plan.scoped:
        deltatable_size_bytes = probe.size_bytes if probe else None
    else:
        deltatable_size_bytes = calculate_dataframe_size_bytes(aggregated_df)
        if deltatable_size_bytes == 0:
            logger.warning(
                "DataFrame size calculated as 0 bytes - this indicates an empty DataFrame"
            )
    logger.info(f"Delta table size to report: {deltatable_size_bytes} bytes")

    commit_metadata = build_commit_metadata(
        data_collection_id=str(dc_id),
        data_collection_tag=data_collection.data_collection_tag,
        write_mode=write_mode if partition else "overwrite",
        run_tags=run_tags,
        file_count=len(files) if files else None,
        # A partial frame's height is not the table's row count.
        row_count=None if plan.scoped else aggregated_df.height,
        ingestion_run_id=command_parameters.get("ingestion_run_id"),
        project_id=command_parameters.get("project_id"),
        trigger=command_parameters.get("trigger"),
        cli_version=_cli_version(),
        user_email=getattr(CLI_config.user, "email", None),
    )

    # A dry run stops here, at the last point before anything leaves the client.
    # The guard sits at the write itself rather than in the callers because
    # everything above is pure computation — the scan diagnostics, the
    # partitioning decision and the row counts are exactly what the run is meant
    # to report, and they are only knowable by getting this far.
    if command_parameters.get("dry_run"):
        if plan.scoped:
            scope = f"{len(plan.run_tags)} changed run(s) via replace-runs"
        elif partition:
            scope = f"{len(run_tags)} run(s) via {write_mode}"
        else:
            scope = "the whole table"
        logger.info(
            f"DRY RUN: would write {aggregated_df.height} row(s) to {destination_prefix}, "
            f"replacing {scope}. Nothing was written."
        )
        return {
            "result": "success",
            "message": (
                f"DRY RUN: {aggregated_df.height} row(s) would be written to "
                f"{destination_prefix} ({scope})."
            ),
        }

    result = write_delta_table(
        aggregated_df=aggregated_df,
        destination_file=destination_prefix,
        storage_options=storage_options,
        write_mode=write_mode if partition else "overwrite",
        commit_metadata=commit_metadata,
        partition=partition,
        replace_run_tags=replace_run_tags,
        scoped=plan.scoped,
    )

    extended = True if rich_tables else False

    if rich_tables:
        aggregated_df.rich_print(  # type: ignore[unresolved-attribute]
            title="Aggregated DataFrame - {data_collection.data_collection_tag}",
            max_rows=10,
            max_cols=10,
            show_dtypes=True,
        )

        aggregated_df.rich_describe()  # type: ignore[unresolved-attribute]

    aggregated_df.rich_info(extended)  # type: ignore[unresolved-attribute]

    # 6. Upsert object in the remote DB with size information
    logger.info(
        f"🔍 DEBUG: About to call api_upsert_deltatable with deltatable_size_bytes={deltatable_size_bytes}"
    )
    api_upsert_result = api_upsert_deltatable(
        data_collection_id=str(dc_id),
        CLI_config=CLI_config,
        delta_table_location=destination_prefix,
        update=overwrite,
        deltatable_size_bytes=deltatable_size_bytes,
        delta_provenance={
            "delta_version": result.get("delta_version"),
            "delta_commit_timestamp": (
                result["delta_commit_timestamp"].isoformat()
                if result.get("delta_commit_timestamp")
                else None
            ),
            "write_mode": result.get("write_mode"),
            "rows_total": result.get("rows_total"),
            "rows_added": result.get("rows_added"),
            # The runs this commit actually touched, which for a scoped write is
            # the changed ones rather than everything in the table.
            "run_tags": (
                (plan.run_tags if plan.scoped else run_tags)[:MAX_RUN_TAGS_IN_METADATA] or None
            ),
            "ingestion_run_id": command_parameters.get("ingestion_run_id"),
            "trigger": command_parameters.get("trigger"),
        },
        async_mode=bool(command_parameters.get("async_upsert")),
    )
    logger.info(f"🔍 DEBUG: API upsert response status: {api_upsert_result.status_code}")
    if api_upsert_result.status_code != 200:
        error_msg = f"Error upserting Delta table metadata: {api_upsert_result.text}"
        logger.error(error_msg)
        return {"result": "error", "message": error_msg}
    result = api_upsert_result.json()

    if result["result"] == "error":
        assert type(result["message"]) is str
        return result

    # A job_id means the server accepted the write but deferred profiling the
    # table. No job_id means it finished inline — including on any server that
    # predates offloading, which is why this is a presence check rather than a
    # version check.
    job_outcome = _await_upsert_job(result, CLI_config)
    if job_outcome is not None and not job_outcome.ok:
        return {
            "result": "error",
            "message": f"Delta table finalization failed: {job_outcome.error}",
        }

    return {
        "result": "success",
        "message": f"Aggregated data written to {destination_prefix}.",
    }


def _await_upsert_job(response_payload: dict, CLI_config: CLIConfig):
    """Block until an offloaded upsert finishes. Returns None if none was opened.

    A polling failure is reported as a failed outcome rather than raised: the
    Delta table itself is already written and its aggregation recorded, so the
    ingestion is not lost — only the column specs are missing, and the caller
    should say so rather than crash.
    """
    from depictio.cli.cli.utils.jobs import JobOutcome, JobPollError, maybe_wait_for_job

    try:
        return maybe_wait_for_job(
            response_payload,
            api_base_url=CLI_config.api_base_url,
            token=CLI_config.user.token.access_token,
            on_update=lambda st: logger.info(
                f"  … {st.get('step') or 'working'}: {st.get('detail') or ''}"
            ),
        )
    except JobPollError as exc:
        logger.error(f"Delta table finalization could not be tracked: {exc}")
        return JobOutcome(status="failed", error=str(exc))


def process_phylogeny_data_collection(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    overwrite: bool = False,
) -> dict[str, str]:
    """Upload a phylogeny tree to S3 under a content-addressed key.

    Phylogeny used to be the only data collection type with no object-store
    presence at all: this function returned immediately, and the serving
    endpoint probed the local filesystem for a path recorded by whichever
    machine ran the scan. On a containerised backend that path usually does not
    exist, so the tree failed to load — a plain bug, quite apart from versioning.

    Uploading fixes that and makes the collection pinnable at the same time:
    ``{dc_id}/versions/{sha256}/{filename}`` is idempotent, so re-running an
    ingest over an unchanged tree writes to the same key and changes nothing,
    while a *changed* tree lands beside its predecessor rather than on top of it.

    Failure is not fatal. The local-path fallback in ``get_phylogeny_newick``
    still works, so a collection that cannot be uploaded — no S3, no
    credentials, a stale CLI — behaves exactly as it did before.
    """
    from pathlib import Path

    logger.info(f"Processing phylogeny data collection: {data_collection.data_collection_tag}")

    dc_id = str(data_collection.id)

    try:
        files = fetch_file_data(dc_id, CLI_config)
    except Exception as e:
        return {"result": "error", "message": f"No files found for phylogeny DC: {e}"}

    if not files:
        return {"result": "error", "message": "No files found for phylogeny data collection"}

    file_path = files[0].file_location
    if file_path.startswith("s3://"):
        return {
            "result": "success",
            "message": "Phylogeny DC already references an object-store location.",
        }

    if not Path(file_path).is_file():
        # The scan registered it, so this means it moved or was removed between
        # scan and process. Nothing to upload, and nothing worth failing over.
        logger.warning(f"Phylogeny file no longer readable at {file_path}; skipping upload.")
        return {
            "result": "success",
            "message": "Phylogeny DC registered; tree file not readable for upload.",
        }

    try:
        import boto3

        storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)
        s3_client = boto3.client(
            "s3",
            endpoint_url=storage_options.endpoint_url,
            aws_access_key_id=storage_options.aws_access_key_id,
            aws_secret_access_key=storage_options.aws_secret_access_key,
            region_name=storage_options.region,
        )

        digest = compute_file_sha256(file_path)
        s3_key = content_key(dc_id, digest, Path(file_path).name)
        logger.info(f"Uploading phylogeny tree to S3: {file_path} -> {s3_key}")
        s3_client.upload_file(file_path, CLI_config.s3_storage.bucket, s3_key)
        s3_location = f"s3://{CLI_config.s3_storage.bucket}/{s3_key}"
        file_size = Path(file_path).stat().st_size
        logger.info(f"Successfully uploaded phylogeny to {s3_location} (sha256 {digest[:12]})")
    except Exception as e:
        # Serving still falls back to the local path, so this degrades to the
        # previous behaviour rather than failing the ingest.
        logger.warning(f"Phylogeny upload failed for {dc_id} ({e}); serving from local path.")
        return {
            "result": "success",
            "message": f"Phylogeny DC registered; upload skipped ({e}).",
        }

    from depictio.cli.cli.utils.api_calls import api_update_dc_specific_properties

    response = api_update_dc_specific_properties(
        data_collection_id=dc_id,
        properties={
            "s3_location": s3_location,
            "file_size_bytes": file_size,
            "asset_version": {
                "digest": digest,
                "s3_location": s3_location,
                "filename": Path(file_path).name,
                "size_bytes": file_size,
                "source_path": str(file_path),
            },
        },
        CLI_config=CLI_config,
    )
    if response.status_code != 200:
        logger.warning(
            f"Phylogeny uploaded but its location could not be registered: {response.text}"
        )

    return {
        "result": "success",
        "message": f"Phylogeny DC uploaded to {s3_location}.",
    }


def process_geojson_data_collection(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    overwrite: bool = False,
) -> dict[str, str]:
    """Process a GeoJSON data collection: validate, upload to S3, store location in MongoDB.

    Follows the same pattern as MultiQC — the file is already uploaded to S3
    during the scan phase. This function validates the GeoJSON, then registers
    the S3 location as a "delta_table_location" in MongoDB.

    Args:
        data_collection: GeoJSON DataCollection object.
        CLI_config: CLI configuration with API URL and credentials.
        overwrite: Whether to overwrite existing data.

    Returns:
        Result dict with success/error status.
    """
    import json
    from pathlib import Path

    logger.info(f"Processing GeoJSON data collection: {data_collection.data_collection_tag}")

    dc_id = str(data_collection.id)

    # Fetch the file(s) already uploaded by the scan phase
    try:
        files = fetch_file_data(dc_id, CLI_config)
    except Exception as e:
        return {"result": "error", "message": f"No files found for GeoJSON DC: {e}"}

    if not files:
        return {"result": "error", "message": "No files found for GeoJSON data collection"}

    file_obj = files[0]
    file_path = file_obj.file_location
    logger.info(f"GeoJSON file location: {file_path}")

    # Validate the GeoJSON content
    # If it's a local path, read and validate; if it's S3, we trust the scan
    if not file_path.startswith("s3://"):
        try:
            with open(file_path) as f:
                geojson = json.load(f)
            if geojson.get("type") != "FeatureCollection":
                return {
                    "result": "error",
                    "message": f"GeoJSON file must be a FeatureCollection, got: {geojson.get('type')}",
                }
            feature_count = len(geojson.get("features", []))
            logger.info(f"Valid GeoJSON FeatureCollection with {feature_count} features")
            file_size = Path(file_path).stat().st_size
        except json.JSONDecodeError as e:
            return {"result": "error", "message": f"Invalid JSON in GeoJSON file: {e}"}
    else:
        # File is already on S3 (uploaded by scan), estimate size
        file_size = 0

    # Check if destination already exists
    if not overwrite:
        storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)
        try:
            import s3fs

            fs = s3fs.S3FileSystem(
                endpoint_url=storage_options.endpoint_url,
                key=storage_options.aws_access_key_id,
                secret=storage_options.aws_secret_access_key,
            )
            bucket_prefix = f"{CLI_config.s3_storage.bucket}/{dc_id}"
            existing_files = fs.ls(bucket_prefix)
            if existing_files:
                rich_print_checked_statement(
                    "GeoJSON already uploaded, skipping (use --overwrite to replace)", "info"
                )
                # Still upsert the location metadata
        except Exception:
            pass  # If we can't check, proceed with upload

    # Upload the GeoJSON file to S3 if it's local
    if not file_path.startswith("s3://"):
        try:
            import boto3

            storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)
            s3_client = boto3.client(
                "s3",
                endpoint_url=storage_options.endpoint_url,
                aws_access_key_id=storage_options.aws_access_key_id,
                aws_secret_access_key=storage_options.aws_secret_access_key,
                region_name=storage_options.region,
            )

            # Content-addressed, so a re-upload of different geometry cannot
            # destroy the old. This used to write to one fixed key,
            # `{dc_id}/geojson_data.geojson`, and overwrite it in place — which
            # made the previous content unrecoverable and left any dashboard
            # version referencing it silently pointing at different data.
            #
            # `{dc_id}/versions/{sha256}/{filename}` keeps the object under the
            # collection's own prefix, so the migrate sweep and the
            # project-delete cleanup — both of which treat a returned path as a
            # prefix — keep working with no change.
            digest = compute_file_sha256(file_path)
            s3_key = content_key(dc_id, digest, Path(file_path).name or "geojson_data.geojson")
            logger.info(f"Uploading GeoJSON to S3: {file_path} -> {s3_key}")
            # A PUT to a content key is idempotent: identical bytes produce the
            # same key, so re-running an ingest costs a transfer and changes
            # nothing.
            s3_client.upload_file(file_path, CLI_config.s3_storage.bucket, s3_key)
            s3_location = f"s3://{CLI_config.s3_storage.bucket}/{s3_key}"
            logger.info(f"Successfully uploaded GeoJSON to {s3_location} (sha256 {digest[:12]})")

        except Exception as e:
            return {"result": "error", "message": f"Failed to upload GeoJSON to S3: {e}"}
    else:
        s3_location = file_path

    # Register the S3 location in MongoDB via the deltatable upsert endpoint
    api_upsert_result = api_upsert_deltatable(
        data_collection_id=dc_id,
        CLI_config=CLI_config,
        delta_table_location=s3_location,
        update=overwrite,
        deltatable_size_bytes=file_size,
    )

    if api_upsert_result.status_code != 200:
        return {
            "result": "error",
            "message": f"Failed to register GeoJSON location: {api_upsert_result.text}",
        }

    # Record the generation on the DC config as well. The deltatable upsert
    # above tracks the *current* location, which is what every existing reader
    # uses; this is the history a dashboard version pins into. Best-effort —
    # losing it costs the ability to replay one version, not the ingest.
    if not file_path.startswith("s3://"):
        try:
            from pathlib import Path

            from depictio.cli.cli.utils.api_calls import api_update_dc_specific_properties

            api_update_dc_specific_properties(
                data_collection_id=dc_id,
                properties={
                    "s3_location": s3_location,
                    "file_size_bytes": file_size,
                    "asset_version": {
                        "digest": digest,
                        "s3_location": s3_location,
                        "filename": Path(file_path).name,
                        "size_bytes": file_size,
                        "source_path": str(file_path),
                    },
                },
                CLI_config=CLI_config,
            )
        except Exception as exc:
            logger.warning(f"GeoJSON asset version not recorded for {dc_id}: {exc}")

    result = api_upsert_result.json()
    if result.get("result") == "error":
        return result

    rich_print_checked_statement(
        f"GeoJSON data collection processed: {data_collection.data_collection_tag}", "success"
    )

    return {
        "result": "success",
        "message": f"GeoJSON uploaded to {s3_location}",
    }


def _print_recipe_preview(
    recipe_name: str,
    sources: dict[str, pl.DataFrame],
    result_df: pl.DataFrame,
) -> None:
    """Print before/after tables for recipe preview mode."""
    from rich.panel import Panel
    from rich.table import Table

    from depictio.cli.cli.utils.rich_utils import console

    # --- Input sources ---
    console.print()
    console.print(Panel(f"[bold]Recipe Preview: {recipe_name}[/bold]", style="cyan", expand=False))

    MAX_PREVIEW_COLS = 15

    for ref, df in sources.items():
        console.print(
            f"\n[bold cyan]Input source '{ref}'[/bold cyan]  ({df.height} rows x {df.width} cols)"
        )
        # Limit columns displayed
        display_cols = df.columns[:MAX_PREVIEW_COLS]
        extra_cols = df.width - len(display_cols)
        df_display = df.select(display_cols).head(5)
        t = Table(show_header=True, header_style="bold", show_lines=True)
        for col in display_cols:
            t.add_column(col, style="dim" if col.startswith("_") else "")
        if extra_cols > 0:
            t.add_column(f"... +{extra_cols} cols", style="dim italic")
        for row in df_display.iter_rows():
            values = [str(v) for v in row]
            if extra_cols > 0:
                values.append("…")
            t.add_row(*values)
        console.print(t)
        if df.height > 5:
            console.print(f"  [dim]... and {df.height - 5} more rows[/dim]")

    # --- Output ---
    console.print(
        f"\n[bold green]Output after transform[/bold green]  "
        f"({result_df.height} rows x {result_df.width} cols)"
    )
    display_cols = result_df.columns[:MAX_PREVIEW_COLS]
    extra_cols = result_df.width - len(display_cols)
    result_display = result_df.select(display_cols).head(10)
    t = Table(show_header=True, header_style="bold green", show_lines=True)
    for col in display_cols:
        t.add_column(col)
    if extra_cols > 0:
        t.add_column(f"... +{extra_cols} cols", style="dim italic")
    for row in result_display.iter_rows():
        values = [str(v) for v in row]
        if extra_cols > 0:
            values.append("…")
        t.add_row(*values)
    console.print(t)
    if result_df.height > 10:
        console.print(f"  [dim]... and {result_df.height - 10} more rows[/dim]")

    # Schema summary
    console.print(
        "\n[bold]Schema:[/bold] "
        + ", ".join(f"{c}({result_df[c].dtype})" for c in result_df.columns)
    )
    console.print()


def process_recipe_data_collection(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    overwrite: bool = False,
    workflow=None,
    preview: bool = False,
    command_parameters: dict | None = None,
) -> dict[str, str]:
    """Process a transformed (recipe-based) data collection.

    Loads the recipe, resolves sources from the workflow data directory,
    executes the transform, and writes the result to Delta Lake.

    Args:
        data_collection: DataCollection with source="transformed" and transform config.
        CLI_config: CLI configuration with API URL and credentials.
        overwrite: Whether to overwrite existing data.
        workflow: Optional Workflow object to resolve data_dir from data_location.
        preview: If True, display input/output tables and skip Delta Lake write.
        command_parameters: Ingestion context (run id, project, trigger) stamped
            into the Delta commit so a recipe-derived table is attributable like
            any other.

    Returns:
        Result dict with success/error status.
    """
    command_parameters = command_parameters or {}
    try:
        from depictio.recipes import RecipeError, execute_recipe
        from depictio.recipes import load_recipe as _load_recipe
        from depictio.recipes import resolve_sources as _resolve_sources
        from depictio.recipes import validate_schema as _validate_schema
    except ModuleNotFoundError:
        # Fallback: import from source tree when package isn't installed with sub-packages
        import importlib.util
        import pathlib

        _recipes_init = pathlib.Path(__file__).resolve().parents[3] / "recipes" / "__init__.py"
        _spec = importlib.util.spec_from_file_location("depictio.recipes", _recipes_init)
        if _spec is None or _spec.loader is None:
            raise ImportError(f"Could not load depictio.recipes from {_recipes_init}")
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        RecipeError = _mod.RecipeError
        execute_recipe = _mod.execute_recipe
        _load_recipe = _mod.load_recipe
        _resolve_sources = _mod.resolve_sources
        _validate_schema = _mod.validate_schema

    transform_config = data_collection.config.transform
    if transform_config is None:
        return {
            "result": "error",
            "message": f"Transformed DC '{data_collection.data_collection_tag}' has no transform config.",
        }

    recipe_name = transform_config.recipe
    pipeline_version: str | None = getattr(workflow, "version", None)
    rich_print_checked_statement(f"Running recipe: {recipe_name}", "info")

    # Build source overrides dict. A SourceOverride carries either a single-file
    # 'path' or a multi-file 'glob_pattern'; resolve_sources interprets the value
    # by source type, so collapse to whichever was provided.
    overrides = None
    if transform_config.source_overrides:
        overrides = {
            ref: (so.path if so.path is not None else so.glob_pattern)
            for ref, so in transform_config.source_overrides.items()
        }

    # Resolve data directory from workflow's data_location
    # For sequencing-runs structure, collect all run directories
    data_dir = "."
    run_data_dirs: list[str] = []
    if workflow is not None and hasattr(workflow, "data_location") and workflow.data_location:
        locations = getattr(workflow.data_location, "locations", None)
        structure = getattr(workflow.data_location, "structure", None)
        runs_regex = getattr(workflow.data_location, "runs_regex", None)

        if locations and len(locations) > 0:
            base_location = str(locations[0])

            if structure == "sequencing-runs" and runs_regex:
                import re as _re

                for entry in sorted(os.listdir(base_location)):
                    entry_path = os.path.join(base_location, entry)
                    if os.path.isdir(entry_path) and _re.match(runs_regex, entry):
                        run_data_dirs.append(entry_path)
                if run_data_dirs:
                    data_dir = run_data_dirs[0]
                    rich_print_checked_statement(
                        f"Recipe data dir: {base_location} ({len(run_data_dirs)} run(s))", "info"
                    )
                else:
                    data_dir = base_location
                    rich_print_checked_statement(f"Recipe data dir: {data_dir}", "info")
            else:
                data_dir = base_location
                rich_print_checked_statement(f"Recipe data dir: {data_dir}", "info")

    # Resolve dc_ref sources: load referenced DCs from their Delta tables
    extra_sources: dict[str, pl.DataFrame] | None = None
    try:
        recipe_module = _load_recipe(recipe_name, pipeline_version)
        dc_ref_sources = [s for s in recipe_module.SOURCES if s.dc_ref is not None]

        if dc_ref_sources and workflow is not None:
            storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)
            extra_sources = {}
            for src in dc_ref_sources:
                # Find the referenced DC in the workflow by tag
                ref_dc = next(
                    (
                        dc
                        for dc in getattr(workflow, "data_collections", [])
                        if dc.data_collection_tag == src.dc_ref
                    ),
                    None,
                )
                if ref_dc is None:
                    if src.optional:
                        # Optional dc_ref: pass None so transform() can handle absence
                        extra_sources[src.ref] = None  # type: ignore[assignment]
                        continue
                    return {
                        "result": "error",
                        "message": (
                            f"dc_ref '{src.dc_ref}' not found in workflow. "
                            f"Ensure the referenced data collection is processed first."
                        ),
                    }
                ref_s3_path = f"s3://{CLI_config.s3_storage.bucket}/{ref_dc.id!s}"
                read_result = read_delta_table(ref_s3_path, storage_options)
                if read_result.get("result") != "success":
                    if src.optional:
                        extra_sources[src.ref] = None  # type: ignore[assignment]
                        continue
                    return {
                        "result": "error",
                        "message": (
                            f"Failed to read dc_ref '{src.dc_ref}' from Delta Lake: "
                            f"{read_result.get('message')}"
                        ),
                    }
                extra_sources[src.ref] = read_result["data"]
    except RecipeError:
        pass  # Will be caught below during execute_recipe

    if preview:
        # Preview mode: run recipe steps individually and display before/after
        try:
            recipe_module = _load_recipe(recipe_name, pipeline_version)
            sources = _resolve_sources(recipe_module, data_dir, overrides)
            if extra_sources:
                sources.update(extra_sources)
            result_df = recipe_module.transform(sources)
            if not isinstance(result_df, pl.DataFrame):
                return {"result": "error", "message": "transform() did not return a DataFrame"}
            _validate_schema(result_df, recipe_module.EXPECTED_SCHEMA, recipe_name)
            _print_recipe_preview(recipe_name, sources, result_df)
        except RecipeError as e:
            return {"result": "error", "message": f"Recipe failed: {e}"}

    try:
        if run_data_dirs and len(run_data_dirs) > 1:
            # Multi-run: execute recipe per run and concatenate
            all_dfs = []
            for run_dir in run_data_dirs:
                run_tag = os.path.basename(run_dir)
                try:
                    run_df = execute_recipe(
                        recipe_name,
                        run_dir,
                        overrides,
                        extra_sources=extra_sources,
                        pipeline_version=pipeline_version,
                    )
                    run_df = run_df.with_columns(pl.lit(run_tag).alias("depictio_run_id"))
                    all_dfs.append(run_df)
                except RecipeError as e:
                    logger.warning(f"Recipe failed for run {run_tag}: {e}")
            if not all_dfs:
                return {"result": "error", "message": "Recipe failed for all runs"}
            result_df = pl.concat(all_dfs, how="diagonal_relaxed")
        else:
            result_df = execute_recipe(
                recipe_name,
                data_dir,
                overrides,
                extra_sources=extra_sources,
                pipeline_version=pipeline_version,
            )
    except RecipeError as e:
        return {"result": "error", "message": f"Recipe failed: {e}"}

    # Write to Delta Lake (same path as standard aggregation)
    destination_prefix = f"s3://{CLI_config.s3_storage.bucket}/{data_collection.id!s}"
    storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)

    deltatable_size_bytes = calculate_dataframe_size_bytes(result_df)

    # Recipe collections are written like any other: a full overwrite, but with
    # the same provenance. Without it their commits carry no depictio metadata
    # and their aggregations land with delta_version=None, which drops them out
    # of the joined view in /history and leaves a recipe-derived table looking
    # like it was never ingested by anyone.
    run_tags = (
        [str(tag) for tag in result_df[RUN_ID_COLUMN].unique().to_list() if tag is not None]
        if RUN_ID_COLUMN in result_df.columns
        else []
    )
    commit_metadata = build_commit_metadata(
        data_collection_id=str(data_collection.id),
        data_collection_tag=data_collection.data_collection_tag,
        write_mode="overwrite",
        run_tags=run_tags,
        row_count=result_df.height,
        ingestion_run_id=command_parameters.get("ingestion_run_id"),
        project_id=command_parameters.get("project_id"),
        trigger=command_parameters.get("trigger"),
        cli_version=_cli_version(),
        user_email=getattr(CLI_config.user, "email", None),
    )
    write_result = write_delta_table(
        aggregated_df=result_df,
        destination_file=destination_prefix,
        storage_options=storage_options,
        commit_metadata=commit_metadata,
    )

    if write_result.get("result") == "error":
        return write_result

    # Upsert metadata
    api_upsert_result = api_upsert_deltatable(
        data_collection_id=str(data_collection.id),
        CLI_config=CLI_config,
        delta_table_location=destination_prefix,
        update=overwrite,
        deltatable_size_bytes=deltatable_size_bytes,
        delta_provenance={
            "delta_version": write_result.get("delta_version"),
            "delta_commit_timestamp": (
                write_result["delta_commit_timestamp"].isoformat()
                if write_result.get("delta_commit_timestamp")
                else None
            ),
            "write_mode": write_result.get("write_mode"),
            "rows_total": write_result.get("rows_total"),
            "run_tags": run_tags[:MAX_RUN_TAGS_IN_METADATA] or None,
            "ingestion_run_id": command_parameters.get("ingestion_run_id"),
            "trigger": command_parameters.get("trigger"),
        },
    )
    if api_upsert_result.status_code != 200:
        return {"result": "error", "message": f"API upsert failed: {api_upsert_result.text}"}

    api_result = api_upsert_result.json()
    if api_result.get("result") == "error":
        return api_result

    rich_print_checked_statement(
        f"Recipe '{recipe_name}' produced {result_df.height} rows, written to Delta Lake",
        "success",
    )

    return {
        "result": "success",
        "message": f"Recipe '{recipe_name}' result written to {destination_prefix}.",
    }
