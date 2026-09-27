import json
import os
from collections.abc import Iterable
from datetime import datetime

import polars as pl
from deltalake.exceptions import TableNotFoundError
from pydantic import validate_call

from depictio.cli.cli.utils.api_calls import (
    api_get_files_by_dc_id,
    api_upsert_deltatable,
)
from depictio.cli.cli.utils.ingest_timing import record, timed
from depictio.cli.cli.utils.multiqc_processor import process_multiqc_data_collection
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.data_collections_types.bioimage import (
    DCBioimageConfig,
    bioimage_s3_object_key,
    bioimage_s3_prefix,
    is_single_file_format,
    remote_store_name,
)
from depictio.models.models.data_collections_types.phylogeny import phylogeny_s3_key
from depictio.models.models.data_collections_types.table import SpatialDataTableSource
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


@validate_call
def fetch_file_data(dc_id: str, CLI_config: CLIConfig) -> list[File]:
    """
    Call the API to list files for the given DataCollection.

    Args:
        dc_id (str): Data Collection ID.
        CLI_config (CLIConfig): CLI configuration containing API URL and credentials.

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


def read_single_file_lazy(
    file_info: File,
    file_format: str,
    polars_kwargs: dict,
    spatialdata: SpatialDataTableSource | dict | None = None,
) -> pl.LazyFrame:
    """
    Lazily scan a single file into a Polars LazyFrame according to the specified format.

    Args:
        file_info (File): A validated File object.
        file_format (str): The file format (e.g. csv, parquet).
        polars_kwargs (dict): Additional keyword arguments for the Polars scanner.
        spatialdata: format "spatialdata" only: which table to read from the store.

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
        elif file_format == "spatialdata":
            # The File is a SpatialData store; its AnnData table is extracted eagerly.
            from depictio.cli.cli.utils.spatialdata_table import read_spatialdata_table

            if spatialdata is None:
                raise ValueError("format 'spatialdata' needs a spatialdata block")
            lf = read_spatialdata_table(file_path, spatialdata).lazy()
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


def read_files_lazy(
    files: list,
    file_format: str,
    polars_kwargs: dict,
    spatialdata: SpatialDataTableSource | dict | None = None,
) -> list:
    """
    Lazily read all files into Polars LazyFrames.

    Args:
        files (list): List of validated File objects.
        file_format (str): Format of the files.
        polars_kwargs (dict): Additional keyword arguments for the Polars scanners.
        spatialdata: format "spatialdata" only: which table to read from each store.

    Returns:
        list: List of Polars LazyFrames.
    """
    lazy_frames = []
    for file_info in files:
        lf = read_single_file_lazy(file_info, file_format, polars_kwargs, spatialdata)
        lazy_frames.append(lf)
    if not lazy_frames:
        error_msg = "No LazyFrames were generated from the files."
        logger.error(error_msg)
        raise Exception(error_msg)
    return lazy_frames


def align_lazy_schemas(lazy_frames: list) -> list:
    """
    Align column types across all LazyFrames for aggregation.

    This function computes the union of all columns and their desired data types,
    then adjusts each LazyFrame by selecting (and casting) columns accordingly.

    Args:
        lazy_frames (list): List of Polars LazyFrames.

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


def build_aggregated_lazyframe(lazy_frames: list) -> pl.LazyFrame:
    """Align schemas, concatenate, and stamp an aggregation timestamp — lazily.

    Deliberately returns the un-collected LazyFrame so callers can either
    materialize it (:func:`aggregate_lazy_dataframes`) or stream it straight to
    storage (:func:`sink_delta_table`). The "aggregation" here is a *vertical
    concat plus a literal column* — there is no groupby — so streaming it is
    semantically identical to collecting and writing.
    """
    logger.debug("Aligning LazyFrame schemas.")
    aligned_lfs = align_lazy_schemas(lazy_frames)
    logger.debug("Concatenating LazyFrames.")
    concatenated_lf = pl.concat(aligned_lfs)
    return concatenated_lf.with_columns(
        pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).alias("aggregation_time")
    )


def aggregate_lazy_dataframes(lazy_frames: list) -> pl.DataFrame:
    """
    Concatenate LazyFrames (after aligning schemas) and add an aggregation timestamp.

    The concatenation is done lazily and the final DataFrame is materialized at the end.

    Args:
        lazy_frames (list): List of Polars LazyFrames.

    Returns:
        pl.DataFrame: The aggregated DataFrame (materialized).
    """
    concatenated_lf = build_aggregated_lazyframe(lazy_frames)
    # Materialize the lazy operations.
    try:
        aggregated_df: pl.DataFrame = concatenated_lf.collect()  # type: ignore[unresolved-attribute]
        return aggregated_df

    except Exception as e:
        error_msg = f"Error collecting concatenated LazyFrame: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)


def streaming_write_enabled(command_parameters: dict | None = None) -> bool:
    """Whether to stream the Delta write instead of materializing the frame.

    Opt-in (default off) because ``LazyFrame.sink_delta`` is marked unstable in
    polars 1.41.x. Enabled by ``depictio run --streaming`` or by exporting
    ``DEPICTIO_INGEST_STREAMING_WRITE=true`` (the benchmark toggles the env var
    to measure both paths of the same cell).
    """
    if command_parameters and command_parameters.get("streaming"):
        return True
    return os.getenv("DEPICTIO_INGEST_STREAMING_WRITE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def link_columns_by_dc(project_config) -> dict[str, list[str]]:
    """Per-DC join-key columns implied by the project's cross-DC links.

    Links are declared on the *project* (``Project.links``), not on the data
    collection, so a DC config alone cannot tell you it participates in one.

    The two ends are not always searched by the same column name. The source is
    filtered on ``source_column``; the target is filtered on whatever
    ``filter_links._link_target_column`` resolves to, which prefers
    ``link_config.target_field`` when the resolver renames across DCs (the
    MultiQC ``sample_mapping`` case) and only then falls back to
    ``source_column``. Clustering the target on ``source_column`` regardless
    would sort it on a column it is never searched by — harmless, but the
    speedup would silently not happen.

    Returns ``{data_collection_id: [column, ...]}`` covering both ends of every
    enabled link, so either side is clustered on the key it is searched by.

    Note this keys on DC *ids*. A link written with ``source_dc_tag`` /
    ``target_dc_tag`` and no id (template mode) contributes nothing — it would
    need tag→id resolution that isn't available here. Such a DC is written
    unsorted, which is the previous behaviour, not a new failure.
    """
    mapping: dict[str, list[str]] = {}
    # ``links`` only exists on a full ``Project``; other config shapes reach the
    # ingest path too, and they simply have nothing to cluster on.
    for link in getattr(project_config, "links", None) or []:
        if not link.enabled:
            continue
        link_config = link.link_config
        target_field = getattr(link_config, "target_field", None) if link_config else None
        ends = (
            (link.source_dc_id, link.source_column),
            (link.target_dc_id, target_field or link.source_column),
        )
        for dc_id, column in ends:
            if not dc_id or not column:
                continue
            bucket = mapping.setdefault(str(dc_id), [])
            if column not in bucket:
                bucket.append(column)
    return mapping


def clustering_columns(
    data_collection_config: dict,
    available: Iterable[str],
    link_columns: Iterable[str] | None = None,
) -> list[str]:
    """Columns to sort a Delta table by before writing it.

    Parquet keeps min/max statistics per row group, so a scan can skip a whole
    row group whose range excludes the predicate. Those statistics are only
    *selective* if related rows sit together — on an unsorted table every row
    group spans nearly the full value range and nothing can be skipped.

    The keys a filtered render actually searches by are the cross-DC join keys,
    which reach a DC two different ways:

    - ``TableJoinConfig.on_columns`` for DCs joined at ingest, and
    - the project's ``links`` for DCs wired for cross-DC filtering, passed in
      as ``link_columns`` (see :func:`link_columns_by_dc`). This is the case the
      benchmark's ``links`` topology exercises, and it declares no ``join`` at
      all — keying only on ``join`` silently clusters nothing there.

    Sorting takes a filtered read from ~18 ms to ~2 ms on 8 M rows, and that
    multiplies with the typed filter predicate, which is what makes the
    statistics reachable in the first place.

    Returns ``[]`` when the DC has no join key or none of them are present, in
    which case the caller writes unsorted as before.
    """
    join_cfg = (data_collection_config or {}).get("join") or {}
    candidates = list(join_cfg.get("on_columns") or [])
    for column in link_columns or []:
        if column not in candidates:
            candidates.append(column)
    present = set(available)
    return [c for c in candidates if c in present]


def delta_table_stats(
    destination_file: str, storage_options: PolarsStorageOptions
) -> tuple[int, int]:
    """Return ``(size_bytes, num_records)`` of a written Delta table.

    Read from the transaction log's add-actions, so it reports the *real* on-disk
    footprint rather than an in-memory estimate — and needs no materialized frame,
    which is the point on the streaming path. Returns ``(0, 0)`` on any failure.
    """
    try:
        from deltalake import DeltaTable

        actions = DeltaTable(
            destination_file, storage_options=storage_options.model_dump()
        ).get_add_actions(flatten=True)
        cols = actions.column_names
        size = sum(actions.column("size_bytes").to_pylist()) if "size_bytes" in cols else 0
        rows = sum(actions.column("num_records").to_pylist()) if "num_records" in cols else 0
        return int(size), int(rows)
    except Exception as e:
        logger.warning(f"Could not read Delta stats for {destination_file}: {e}")
        return 0, 0


def sink_delta_table(
    concatenated_lf: pl.LazyFrame,
    destination_file: str,
    storage_options: PolarsStorageOptions,
) -> dict:
    """Stream a LazyFrame straight to Delta, never materializing the full frame.

    This is the memory fix for large ingests: the default path collects the whole
    concatenated dataset into RAM before writing, which is what OOMs at scale.
    """
    logger.debug(f"Streaming (sink_delta) aggregated LazyFrame to {destination_file}.")
    # Looked up dynamically: sink_delta is absent on older polars builds, and the
    # resulting AttributeError is exactly what triggers the caller's fallback.
    sink_delta = getattr(concatenated_lf, "sink_delta", None)
    if sink_delta is None:
        raise AttributeError("This polars build has no LazyFrame.sink_delta")
    sink_delta(
        destination_file,
        storage_options=storage_options.model_dump(),
        delta_write_options={"schema_mode": "overwrite"},
        mode="overwrite",
    )
    logger.info(f"Aggregated Delta table streamed to {destination_file}.")
    return {
        "result": "success",
        "message": f"Aggregated Delta table streamed to {destination_file}.",
    }


def write_delta_table(
    aggregated_df: pl.DataFrame,
    destination_file: str,
    storage_options: PolarsStorageOptions,
) -> dict:
    """
    Write the aggregated DataFrame as a Delta Lake table.

    Args:
        aggregated_df (pl.DataFrame): The aggregated DataFrame.
        destination_file (str): The destination path for the Delta table.

    Raises:
        Exception: If writing the Delta table fails.
    """
    # try:
    logger.debug(f"Writing aggregated DataFrame to Delta table at {destination_file}.")
    logger.debug(f"Aggregated DataFrame schema: {aggregated_df.schema}")
    logger.debug(f"Aggregated DataFrame head: {aggregated_df.head(5)}")
    logger.debug(f"Storage options: {storage_options}")

    aggregated_df.write_delta(
        destination_file,
        storage_options=storage_options.model_dump(),
        delta_write_options={"schema_mode": "overwrite"},
        mode="overwrite",
    )

    logger.info(f"Aggregated Delta table written to {destination_file}.")

    return {
        "result": "success",
        "message": f"Aggregated Delta table written to {destination_file}.",
    }
    # except Exception as e:
    #     error_msg = f"Error writing aggregated Delta table: {e}"
    #     logger.error(error_msg)

    #     return {"result": "error", "message": error_msg}


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


def client_aggregate_data(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    command_parameters: dict = {},
    workflow=None,  # Optional workflow for MultiQC processing
) -> dict[str, str]:
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

    if command_parameters:
        overwrite = command_parameters.get("overwrite", False)
        rich_tables = command_parameters.get("rich_tables", False)
        preview_recipes = command_parameters.get("preview_recipes", False)
    else:
        overwrite = False
        rich_tables = False
        preview_recipes = False

    # Handle MultiQC data collections specially - copy parquet files to S3 and extract metadata
    if data_collection.config.type.lower() == "multiqc":
        return process_multiqc_data_collection(data_collection, CLI_config, overwrite, workflow)

    # Handle GeoJSON data collections - upload file to S3 and store location
    if data_collection.config.type.lower() == "geojson":
        return process_geojson_data_collection(data_collection, CLI_config, overwrite)

    # Phylogeny DCs have no delta table; the tree is copied to S3 for the Newick endpoint.
    if data_collection.config.type.lower() == "phylogeny":
        return process_phylogeny_data_collection(data_collection, CLI_config, overwrite)

    # Bioimage DCs have no delta table; each store is copied to S3 for the chunk endpoint.
    if data_collection.config.type.lower() == "bioimage":
        return process_bioimage_data_collection(data_collection, CLI_config, overwrite)

    # Handle transformed (recipe-based) data collections. A `materialized`
    # transform keeps the recipe for lineage but ships a pre-computed seed file,
    # so it falls through to the file-scan path instead of re-running the recipe.
    if (
        data_collection.config.source == "transformed"
        and data_collection.config.transform is not None
        and not data_collection.config.transform.materialized
    ):
        return process_recipe_data_collection(
            data_collection, CLI_config, overwrite, workflow, preview=preview_recipes
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

    destination_exists = False
    logger.info("Checking if destination Delta table exists.")
    # logger.info(f"Destination prefix: {destination_prefix}")
    # logger.info(f"Storage options: {storage_options}")
    try:
        response_read_table = read_delta_table(destination_prefix, storage_options=storage_options)
        # logger.info(f"Response read table: {response_read_table}")

        if response_read_table["result"] == "success" and "data" in response_read_table:
            existing_df = response_read_table["data"]
            destination_exists = True
            logger.debug("Existing Delta table found, using it as base")
            assert type(existing_df) is pl.DataFrame
            logger.debug(f"Existing Delta table head: {existing_df.head(5)}")
        else:
            logger.debug("No data returned from read_delta_table, will create it during processing")
            destination_exists = False
            logger.warning("No data returned, will create it during processing")
    except TableNotFoundError:
        destination_exists = False
        logger.warning("Destination prefix does not exist yet, will create it during processing")
    # logger.info(f"Destination exists: {destination_exists}")

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

    # 1. Fetch file data from the server
    files = fetch_file_data(str(dc_id), CLI_config)
    logger.debug(f"Files data: {files}")
    # logger.info(f"Files data: {files}")

    # 3. Read files using Polars
    data_collection_config = convert_objectid_to_str(data_collection_config.model_dump())
    # logger.info(f"Data Collection config: {data_collection_config}")
    logger.debug(f"Data Collection config: {data_collection_config}")
    dc_props = data_collection_config.get("dc_specific_properties", {})
    file_format = dc_props.get("format", "csv").lower()
    polars_kwargs = dict(dc_props.get("polars_kwargs", {}))
    with timed("parse"):
        lazy_frames = read_files_lazy(
            files, file_format, polars_kwargs, dc_props.get("spatialdata")
        )
    record("n_files", len(files) if files else 0)

    # 4/5. Aggregate + write to Delta Lake.
    if destination_exists:
        rich_print_checked_statement("Overwriting existing Delta table", "info")
        logger.info("Overwriting existing Delta table")
    else:
        rich_print_checked_statement(
            "S3 Destination does not exist, will create it during processing", "info"
        )
        logger.info("S3 Destination does not exist, will create it during processing")

    use_streaming = streaming_write_enabled(command_parameters)
    aggregated_df: pl.DataFrame | None = None
    result: dict = {}
    deltatable_size_bytes = 0

    if use_streaming:
        # Stream the concat straight to Delta — never materializes the full
        # dataset, which is what OOMs on large ingests.
        #
        # Deliberately NOT clustered on the join keys: a sort is a blocking,
        # whole-dataset operation, so applying it here would materialize
        # exactly what this path exists to avoid. Streamed tables therefore
        # keep unselective row-group statistics and read back slower under a
        # filter — the trade is memory for filtered-read speed, and it is why
        # this path stays opt-in.
        try:
            with timed("write"):
                result = sink_delta_table(
                    build_aggregated_lazyframe(lazy_frames),
                    destination_file=destination_prefix,
                    storage_options=storage_options,
                )
            deltatable_size_bytes, n_rows = delta_table_stats(destination_prefix, storage_options)
            record("n_rows", n_rows)
        except Exception as e:
            # sink_delta is unstable in polars 1.41.x — never let it break an
            # ingest; fall back to the proven collect-then-write path.
            logger.warning(f"Streaming Delta write failed ({e}); falling back to collect+write.")
            record("streaming_fallback", True)
            use_streaming = False

    record("streaming", use_streaming)

    if not use_streaming:
        with timed("collect"):
            aggregated_df = aggregate_lazy_dataframes(lazy_frames)
        record("n_rows", aggregated_df.height)
        logger.debug(f"Aggregated DataFrame shape: {aggregated_df.shape}")
        logger.debug(f"Aggregated DataFrame schema: {aggregated_df.schema}")
        logger.info(f"Aggregated DataFrame head: {aggregated_df.head(5)}")

        # Cluster on the join keys so parquet row-group statistics become
        # selective for the filters a dashboard actually issues. Timed as its
        # own phase: it is a real cost paid once at ingest to buy it back on
        # every filtered render, and that trade has to be visible.
        #
        # Two caveats worth knowing before reading a benchmark number:
        #  - ``link_columns_by_dc`` is injected by ``process_project_data_collections``,
        #    so entry points that build their own ``command_parameters`` (join
        #    repair in ``joins.py``, recipe/``transformed`` DCs, the API-side
        #    ``table_manage`` write) get join-config clustering only. A project
        #    can therefore hold both clustered and unclustered tables.
        #  - the sort is not in-place, so it adds a frame copy to the peak of
        #    the collect-then-write path, which is what sets the memory ceiling
        #    for that path. The streaming path skips it.
        sort_cols = clustering_columns(
            data_collection_config,
            aggregated_df.columns,
            (command_parameters or {}).get("link_columns_by_dc", {}).get(str(dc_id)),
        )
        if sort_cols:
            try:
                with timed("sort"):
                    aggregated_df = aggregated_df.sort(sort_cols)
                record("sorted_by", ",".join(sort_cols))
                logger.info(f"Clustered Delta table on join columns {sort_cols}")
            except Exception as e:
                # Clustering is an optimisation, never a correctness
                # requirement — an unsortable key (nested List/Struct dtype)
                # must not fail an otherwise valid ingest.
                logger.warning(f"Could not cluster on {sort_cols} ({e}); writing unsorted.")

        # Calculate DataFrame size before writing (more accurate than S3 file size estimation)
        deltatable_size_bytes = calculate_dataframe_size_bytes(aggregated_df)
        if deltatable_size_bytes == 0:
            logger.warning(
                "DataFrame size calculated as 0 bytes - this indicates an empty DataFrame"
            )

        with timed("write"):
            result = write_delta_table(
                aggregated_df=aggregated_df,
                destination_file=destination_prefix,
                storage_options=storage_options,
            )

    record("delta_bytes", deltatable_size_bytes)
    logger.info(f"🔍 DEBUG: Calculated deltatable_size_bytes = {deltatable_size_bytes}")
    logger.info(f"🔍 DEBUG: Size in MB = {deltatable_size_bytes / (1024 * 1024):.2f} MB")

    # Rich summaries need a materialized frame — unavailable on the streaming path.
    if aggregated_df is not None:
        if rich_tables:
            aggregated_df.rich_print(  # type: ignore[unresolved-attribute]
                title="Aggregated DataFrame - {data_collection.data_collection_tag}",
                max_rows=10,
                max_cols=10,
                show_dtypes=True,
            )

            aggregated_df.rich_describe()  # type: ignore[unresolved-attribute]

        aggregated_df.rich_info(bool(rich_tables))  # type: ignore[unresolved-attribute]

    # 6. Upsert object in the remote DB with size information
    logger.info(
        f"🔍 DEBUG: About to call api_upsert_deltatable with deltatable_size_bytes={deltatable_size_bytes}"
    )
    with timed("upsert"):
        api_upsert_result = api_upsert_deltatable(
            data_collection_id=str(dc_id),
            CLI_config=CLI_config,
            delta_table_location=destination_prefix,
            update=overwrite,
            deltatable_size_bytes=deltatable_size_bytes,
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

    return {
        "result": "success",
        "message": f"Aggregated data written to {destination_prefix}.",
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
            s3_client = _s3_client(CLI_config)

            # Upload to S3 under the DC ID
            s3_key = f"{dc_id}/geojson_data.geojson"
            logger.info(f"Uploading GeoJSON to S3: {file_path} -> {s3_key}")
            s3_client.upload_file(file_path, CLI_config.s3_storage.bucket, s3_key)
            s3_location = f"s3://{CLI_config.s3_storage.bucket}/{s3_key}"
            logger.info(f"Successfully uploaded GeoJSON to {s3_location}")

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


def _s3_client(CLI_config: CLIConfig, max_pool_connections: int | None = None):
    """boto3 S3 client for the CLI's configured storage (GeoJSON, phylogeny, OME-Zarr uploads).

    ``max_pool_connections`` raises botocore's HTTP pool (10 by default) for a
    client shared across upload threads, so workers do not queue on a socket.
    """
    import boto3
    from botocore.config import Config

    storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)
    return boto3.client(
        "s3",
        endpoint_url=storage_options.endpoint_url,
        aws_access_key_id=storage_options.aws_access_key_id,
        aws_secret_access_key=storage_options.aws_secret_access_key,
        region_name=storage_options.region,
        config=Config(max_pool_connections=max_pool_connections) if max_pool_connections else None,
    )


def process_phylogeny_data_collection(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    overwrite: bool = False,
) -> dict[str, str]:
    """Upload a phylogeny DC's Newick file to S3 so any backend can serve it.

    The scan registers the tree under the path the CLI saw, which a containerised
    or remote backend cannot read. The copy lands at ``phylogeny_s3_key``, where
    the Newick endpoint looks first. The location is not registered through
    /deltatables/upsert, which would try to scan the file as a delta table.

    Args:
        data_collection: Phylogeny DataCollection object.
        CLI_config: CLI configuration with API URL, credentials and S3 storage.
        overwrite: Accepted for parity with the other processors. The upload
            always replaces the stored tree, since the scan decides which file
            is current.

    Returns:
        Result dict with success/error status.
    """
    logger.info(f"Processing phylogeny data collection: {data_collection.data_collection_tag}")

    dc_id = str(data_collection.id)

    try:
        files = fetch_file_data(dc_id, CLI_config)
    except Exception as e:
        return {"result": "error", "message": f"No files found for phylogeny DC: {e}"}

    if not files:
        return {"result": "error", "message": "No files found for phylogeny data collection"}

    file_path = files[0].file_location
    logger.info(f"Phylogeny tree location: {file_path}")

    if file_path.startswith("s3://"):
        s3_location = file_path
    else:
        bucket = CLI_config.s3_storage.bucket
        s3_key = phylogeny_s3_key(dc_id)
        try:
            logger.info(f"Uploading phylogeny tree to S3: {file_path} -> {s3_key}")
            _s3_client(CLI_config).upload_file(file_path, bucket, s3_key)
        except Exception as e:
            return {"result": "error", "message": f"Failed to upload phylogeny tree to S3: {e}"}
        s3_location = f"s3://{bucket}/{s3_key}"

    rich_print_checked_statement(
        f"Phylogeny data collection processed: {data_collection.data_collection_tag}", "success"
    )

    return {
        "result": "success",
        "message": f"Phylogeny tree available at {s3_location}",
    }


# NGFF version of each zarr layout: 0.4 is zarr v2 (``.zattrs``), 0.5 is
# zarr v3 (``zarr.json``, OME metadata under ``attributes.ome``).
_NGFF_LAYOUTS = {"0.4": "zarr v2, .zattrs", "0.5": "zarr v3, zarr.json"}


def _read_json_object(path: str) -> dict:
    """The JSON object stored at ``path``, or a ValueError naming the file."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _check_ngff_version(path: str, found: str, expected: str | None) -> None:
    if expected is not None and found != expected:
        raise ValueError(
            f"{path} is NGFF {found} ({_NGFF_LAYOUTS[found]}) but the data collection "
            f"requires ngff_version {expected} ({_NGFF_LAYOUTS[expected]})"
        )


def _require_multiscales(multiscales: object, where: str) -> list:
    if not isinstance(multiscales, list) or not multiscales:
        raise ValueError(
            f"{where} has no 'multiscales' entry: not an OME-NGFF image "
            "(plates and label-only stores are not supported)"
        )
    return multiscales


def validate_ome_zarr_store(store_path: str, ngff_version: str | None = None) -> str:
    """Raise ValueError unless ``store_path`` is an NGFF 0.4 or 0.5 image store.

    NGFF 0.4 (zarr v2): the root ``.zattrs`` must be a JSON object carrying a
    non-empty ``multiscales`` list, which is what the viewer reads first.
    NGFF 0.5 (zarr v3): the root ``zarr.json`` must be a group whose
    ``attributes.ome.multiscales`` is non-empty, and every dataset path must
    hold an array ``zarr.json`` (sharded or not: chunks are never read).
    With ``ngff_version`` set, a store of the other version is rejected.

    Returns:
        The store's NGFF version, ``"0.4"`` or ``"0.5"``.
    """
    zattrs_path = os.path.join(store_path, ".zattrs")
    zarr_json_path = os.path.join(store_path, "zarr.json")
    if os.path.isfile(zattrs_path):
        _check_ngff_version(store_path, "0.4", ngff_version)
        _require_multiscales(_read_json_object(zattrs_path).get("multiscales"), zattrs_path)
        return "0.4"
    if not os.path.isfile(zarr_json_path):
        raise ValueError(
            f"{store_path} is not an OME-Zarr store: no root .zattrs (NGFF 0.4) "
            "or zarr.json (NGFF 0.5)"
        )

    _check_ngff_version(store_path, "0.5", ngff_version)
    meta = _read_json_object(zarr_json_path)
    if meta.get("zarr_format") != 3 or meta.get("node_type") != "group":
        raise ValueError(
            f"{zarr_json_path} is not a zarr v3 group (zarr_format 3, node_type group)"
        )
    attributes = meta.get("attributes")
    ome = attributes.get("ome") if isinstance(attributes, dict) else None
    if not isinstance(ome, dict):
        raise ValueError(f"{zarr_json_path} has no 'attributes.ome' entry: not an NGFF 0.5 image")
    where = f"{zarr_json_path} attributes.ome"
    for multiscale in _require_multiscales(ome.get("multiscales"), where):
        datasets = multiscale.get("datasets") if isinstance(multiscale, dict) else None
        if not isinstance(datasets, list) or not datasets:
            raise ValueError(f"{where} has a multiscale without datasets")
        for dataset in datasets:
            path = dataset.get("path") if isinstance(dataset, dict) else None
            parts = path.split("/") if isinstance(path, str) else []
            if not path or path.startswith("/") or ".." in parts:
                raise ValueError(f"{where} has an invalid dataset path {path!r}")
            array_json = os.path.join(store_path, *parts, "zarr.json")
            if not os.path.isfile(array_json):
                raise ValueError(
                    f"{store_path} has no array at dataset path {path!r} (no zarr.json)"
                )
            if _read_json_object(array_json).get("node_type") != "array":
                raise ValueError(f"{array_json} is not a zarr v3 array")
    return "0.5"


def validate_spatialdata_store(
    store_path: str, image_path: str, ngff_version: str | None = None
) -> str:
    """Raise ValueError unless ``store_path`` is a SpatialData store whose
    ``image_path`` element is an NGFF multiscales image.

    The root may be zarr v2 (``.zgroup`` / ``.zattrs``) or zarr v3
    (``zarr.json``); ``ngff_version`` is enforced on the image element, which
    is what the viewer reads. Returns the image's NGFF version.
    """
    markers = (".zattrs", ".zgroup", "zarr.json")
    if not any(os.path.isfile(os.path.join(store_path, m)) for m in markers):
        raise ValueError(
            f"{store_path} is not a SpatialData store: no root .zgroup, .zattrs "
            "(zarr v2) or zarr.json (zarr v3)"
        )
    image_dir = os.path.join(store_path, *image_path.split("/"))
    if not os.path.isdir(image_dir):
        raise ValueError(f"{store_path} has no image element at image_path {image_path!r}")
    return validate_ome_zarr_store(image_dir, ngff_version)


# TIFF ImageDescription tag, which holds the OME-XML in an OME-TIFF's first IFD.
_TIFF_IMAGE_DESCRIPTION = 270
# Only the head of the description is read: the <OME root element opens it.
_OME_XML_PROBE_BYTES = 1 << 20


def _read_exact(fh, offset: int, size: int, path: str) -> bytes:
    fh.seek(offset)
    data = fh.read(size)
    if len(data) != size:
        raise ValueError(f"{path} is a truncated TIFF file")
    return data


def validate_ome_tiff(path: str) -> None:
    """Raise ValueError unless ``path`` is a TIFF / BigTIFF whose first IFD's
    ImageDescription (tag 270) carries OME-XML.

    Only the header and the first IFD are parsed; pixel data is never read.
    """
    import struct

    with open(path, "rb") as fh:
        head = fh.read(16)
        order = {b"II": "<", b"MM": ">"}.get(head[:2])
        if order is None or len(head) < 8:
            raise ValueError(f"{path} is not a TIFF file (bad byte-order mark)")
        (magic,) = struct.unpack(order + "H", head[2:4])
        if magic == 42:
            (ifd_offset,) = struct.unpack(order + "I", head[4:8])
            count_fmt, entry_size, entry_fmt, inline_size = "H", 12, "HHI4s", 4
        elif magic == 43 and len(head) == 16:
            (ifd_offset,) = struct.unpack(order + "Q", head[8:16])
            count_fmt, entry_size, entry_fmt, inline_size = "Q", 20, "HHQ8s", 8
        else:
            raise ValueError(f"{path} is not a TIFF or BigTIFF file (magic {magic})")

        count_size = struct.calcsize(count_fmt)
        (n_entries,) = struct.unpack(
            order + count_fmt, _read_exact(fh, ifd_offset, count_size, path)
        )
        entries = _read_exact(fh, ifd_offset + count_size, n_entries * entry_size, path)
        description = None
        for i in range(n_entries):
            tag, _type, count, value = struct.unpack(
                order + entry_fmt, entries[i * entry_size : (i + 1) * entry_size]
            )
            if tag != _TIFF_IMAGE_DESCRIPTION:
                continue
            # ASCII / BYTE / UNDEFINED: one byte per value.
            if count <= inline_size:
                description = value[:count]
            else:
                (offset,) = struct.unpack(order + ("I" if inline_size == 4 else "Q"), value)
                size = min(count, _OME_XML_PROBE_BYTES)
                description = _read_exact(fh, offset, size, path)
            break

    if description is None:
        raise ValueError(f"{path} has no ImageDescription in its first IFD: not an OME-TIFF")
    if b"<OME" not in description:
        raise ValueError(f"{path} ImageDescription carries no OME-XML: not an OME-TIFF")


# Parallel uploads per store: a store is thousands of small chunk files, so a
# serial loop is bound by per-request latency, not bandwidth.
BIOIMAGE_UPLOAD_WORKERS_DEFAULT = 16
# S3 DeleteObjects accepts at most 1000 keys per request.
_S3_DELETE_BATCH = 1000


def bioimage_upload_workers() -> int:
    """Upload threads per store: ``DEPICTIO_INGEST_BIOIMAGE_UPLOAD_WORKERS`` or 16."""
    raw = os.getenv("DEPICTIO_INGEST_BIOIMAGE_UPLOAD_WORKERS", "").strip()
    try:
        workers = int(raw) if raw else BIOIMAGE_UPLOAD_WORKERS_DEFAULT
    except ValueError:
        logger.warning(f"Ignoring non-integer DEPICTIO_INGEST_BIOIMAGE_UPLOAD_WORKERS={raw!r}")
        workers = BIOIMAGE_UPLOAD_WORKERS_DEFAULT
    return max(1, workers)


def bioimage_upload_marker_key(dc_id: str, store_name: str) -> str:
    """S3 key of the marker recording the last complete upload of a store.

    It sits under ``bioimage/{dc_id}/.uploads/``, outside every store prefix,
    so the chunk endpoint can never serve it as a zarr key and the backend's
    store listing (which keeps only ``*.zarr`` prefixes) never reports it.
    """
    return f"{bioimage_s3_prefix(dc_id)}.uploads/{store_name}.json"


def zarr_store_hash(store_path: str, image_path: str | None = None) -> str:
    """Change-detection hash of a local store, computed like the scan's File hash.

    With ``image_path`` (SpatialData) only that subtree is hashed, and the path
    joins the name, so pointing the DC at another element re-uploads.
    """
    from depictio.cli.cli.utils.common import format_timestamp
    from depictio.cli.cli.utils.scan import generate_zarr_store_hash, zarr_store_stats

    store_name = os.path.basename(store_path.rstrip("/"))
    source = os.path.join(store_path, *image_path.split("/")) if image_path else store_path
    name = f"{store_name}/{image_path}" if image_path else store_name
    total_size, max_mtime, root_meta = zarr_store_stats(source)
    return generate_zarr_store_hash(name, total_size, format_timestamp(max_mtime), root_meta)


def single_file_store_hash(path: str) -> str:
    """Change-detection hash of a single-file store (OME-TIFF): name, size, mtime."""
    import hashlib

    from depictio.cli.cli.utils.common import format_timestamp

    st = os.stat(path)
    name = os.path.basename(path)
    return hashlib.sha256(f"{name}{st.st_size}{format_timestamp(st.st_mtime)}".encode()).hexdigest()


def _read_bioimage_upload_marker(s3_client, bucket: str, key: str) -> dict | None:
    """The marker's JSON content, or None when absent or unreadable."""
    try:
        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            data = json.loads(body.read())
        finally:
            body.close()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _list_s3_keys(s3_client, bucket: str, prefix: str) -> set[str]:
    keys: set[str] = set()
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            keys.add(obj["Key"])
    return keys


def _delete_s3_keys(s3_client, bucket: str, keys: list[str]) -> None:
    """Batch-delete ``keys``, raising if S3 reports any per-key error."""
    for i in range(0, len(keys), _S3_DELETE_BATCH):
        batch = keys[i : i + _S3_DELETE_BATCH]
        resp = s3_client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
        errors = (resp or {}).get("Errors") or []
        if errors:
            first = errors[0]
            raise RuntimeError(
                f"Failed to delete {len(errors)} stale object(s), e.g. "
                f"{first.get('Key')}: {first.get('Code')} {first.get('Message')}"
            )


def upload_zarr_store(
    s3_client,
    bucket: str,
    dc_id: str,
    store_path: str,
    *,
    workers: int | None = None,
    force: bool = False,
    image_path: str | None = None,
) -> int:
    """Mirror a local store under ``bioimage_s3_prefix(dc_id, store_name)``.

    Keys keep the store-relative path with ``/`` separators, so chunk keys like
    ``0/0.0.0.0.0``, nested ``0/0/0/0/0/0`` or zarr v3 ``0/c/0/0/0`` resolve
    unchanged; a large zarr v3 shard goes through boto3's managed (multipart)
    transfer like any other file. With
    ``image_path`` (SpatialData) only ``<store>/<image_path>`` is uploaded, with
    keys relative to it, so the prefix reads like a plain OME-Zarr store. Files are
    uploaded in parallel over the shared ``s3_client`` (boto3 clients are
    thread-safe). Objects left under the prefix by an earlier upload that the
    local store no longer holds are then deleted, so a re-chunked store never
    serves stale chunks.

    The store's change-detection hash is written last to
    ``bioimage_upload_marker_key``. When that marker already matches the local
    store (and ``force`` is False) nothing is uploaded. The marker is removed
    before a re-upload starts, so an interrupted upload never looks complete.

    Returns:
        Number of objects uploaded (0 when the marker matched).
    """
    from concurrent.futures import ThreadPoolExecutor

    store_name = os.path.basename(store_path.rstrip("/"))
    prefix = bioimage_s3_prefix(dc_id, store_name)
    marker_key = bioimage_upload_marker_key(dc_id, store_name)
    store_hash = zarr_store_hash(store_path, image_path)
    source = os.path.join(store_path, *image_path.split("/")) if image_path else store_path

    marker = _read_bioimage_upload_marker(s3_client, bucket, marker_key)
    if not force and marker is not None and marker.get("hash") == store_hash:
        logger.info(f"Bioimage store unchanged since last upload, skipping: {store_path}")
        return 0
    if marker is not None:
        s3_client.delete_object(Bucket=bucket, Key=marker_key)

    uploads: list[tuple[str, str]] = []
    for root, _, names in os.walk(source):
        for name in sorted(names):
            local = os.path.join(root, name)
            rel = os.path.relpath(local, source).replace(os.sep, "/")
            uploads.append((local, prefix + rel))

    n_workers = workers or bioimage_upload_workers()
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        # list() drains the iterator so the first failed upload re-raises here.
        list(pool.map(lambda item: s3_client.upload_file(item[0], bucket, item[1]), uploads))

    local_keys = {key for _, key in uploads}
    stale = sorted(_list_s3_keys(s3_client, bucket, prefix) - local_keys)
    if stale:
        logger.info(f"Deleting {len(stale)} stale object(s) under {prefix}")
        _delete_s3_keys(s3_client, bucket, stale)

    s3_client.put_object(
        Bucket=bucket,
        Key=marker_key,
        Body=json.dumps({"hash": store_hash, "objects": len(uploads)}).encode(),
        ContentType="application/json",
    )
    return len(uploads)


def upload_ome_tiff(
    s3_client,
    bucket: str,
    dc_id: str,
    file_path: str,
    *,
    force: bool = False,
) -> int:
    """Copy one OME-TIFF to ``bioimage_s3_object_key(dc_id, name)``.

    boto3's managed transfer splits a large file into a multipart upload. The
    marker scheme matches ``upload_zarr_store``: skipped when the marker's
    hash matches, marker removed before a re-upload and written last.

    Returns:
        Number of objects uploaded (0 when the marker matched, else 1).
    """
    name = os.path.basename(file_path)
    key = bioimage_s3_object_key(dc_id, name)
    marker_key = bioimage_upload_marker_key(dc_id, name)
    file_hash = single_file_store_hash(file_path)

    marker = _read_bioimage_upload_marker(s3_client, bucket, marker_key)
    if not force and marker is not None and marker.get("hash") == file_hash:
        logger.info(f"OME-TIFF unchanged since last upload, skipping: {file_path}")
        return 0
    if marker is not None:
        s3_client.delete_object(Bucket=bucket, Key=marker_key)

    s3_client.upload_file(file_path, bucket, key)
    s3_client.put_object(
        Bucket=bucket,
        Key=marker_key,
        Body=json.dumps({"hash": file_hash, "objects": [key]}).encode(),
        ContentType="application/json",
    )
    return 1


def _duplicate_store_names(store_paths: Iterable[str]) -> dict[str, list[str]]:
    """Store names shared by more than one path or remote URL, with the clashes."""
    by_name: dict[str, list[str]] = {}
    for path in store_paths:
        name = remote_store_name(path) if "://" in path else os.path.basename(path.rstrip("/"))
        by_name.setdefault(name, []).append(path)
    return {name: paths for name, paths in by_name.items() if len(paths) > 1}


_FORMAT_LABELS = {"ome-zarr": "OME-Zarr", "spatialdata": "SpatialData", "ome-tiff": "OME-TIFF"}


def _validate_bioimage_store(store_path: str, props: DCBioimageConfig) -> None:
    if props.format == "ome-tiff":
        validate_ome_tiff(store_path)
    elif props.format == "spatialdata":
        validate_spatialdata_store(store_path, props.image_path or "", props.ngff_version)
    else:
        validate_ome_zarr_store(store_path, props.ngff_version)


def process_bioimage_data_collection(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    overwrite: bool = False,
) -> dict[str, str]:
    """Validate a bioimage DC's local stores and upload them to S3.

    Every registered File is one store of the DC's ``format``: a ``*.zarr``
    directory (OME-Zarr, SpatialData) or an ``*.ome.tif(f)`` file (OME-TIFF).
    Stores are keyed by their name (S3 prefix, stores listing, viewer), so two
    stores sharing a name, local or remote, are rejected before anything is
    uploaded. Each store is validated for its format; unless the DC is
    reference-only (``upload: false``), a key-tree store is then mirrored under
    ``bioimage_s3_prefix(dc_id, store_name)`` (a SpatialData store: its
    ``image_path`` subtree only) and an OME-TIFF copied to
    ``bioimage_s3_object_key(dc_id, store_name)``. ``remote_stores`` are read in
    place by the API and never touched here. No delta table is registered.

    Args:
        data_collection: Bioimage DataCollection object.
        CLI_config: CLI configuration with API URL, credentials and S3 storage.
        overwrite: Re-upload every store even when its upload marker matches
            the local content.

    Returns:
        Result dict with success/error status.
    """
    logger.info(f"Processing bioimage data collection: {data_collection.data_collection_tag}")

    dc_id = str(data_collection.id)
    props = getattr(data_collection.config, "dc_specific_properties", None)
    if not isinstance(props, DCBioimageConfig):
        props = DCBioimageConfig()
    label = _FORMAT_LABELS.get(props.format, props.format)
    remote = list(props.remote_stores)
    remote_note = f"{len(remote)} remote store(s), read in place"

    if remote and not getattr(data_collection.config, "scan", None):
        # Remote-only DC: nothing was scanned, so there is nothing to validate or upload.
        return _bioimage_success(data_collection, len(remote), remote_note)

    try:
        files = fetch_file_data(dc_id, CLI_config)
    except Exception as e:
        if remote:
            return _bioimage_success(data_collection, len(remote), remote_note)
        return {"result": "error", "message": f"No stores found for bioimage DC: {e}"}

    if not files:
        if remote:
            return _bioimage_success(data_collection, len(remote), remote_note)
        return {"result": "error", "message": "No stores found for bioimage data collection"}

    store_paths = sorted({f.file_location for f in files})
    duplicates = _duplicate_store_names([*store_paths, *remote])
    if duplicates:
        clashes = "; ".join(
            f"{name}: {', '.join(paths)}" for name, paths in sorted(duplicates.items())
        )
        return {
            "result": "error",
            "message": (
                f"{label} store names must be unique within a data collection "
                f"(stores are addressed by name): {clashes}"
            ),
        }

    for store_path in store_paths:
        try:
            _validate_bioimage_store(store_path, props)
        except ValueError as e:
            return {"result": "error", "message": f"Invalid {label} store: {e}"}

    if props.upload:
        bucket = CLI_config.s3_storage.bucket
        workers = bioimage_upload_workers()
        s3_client = _s3_client(CLI_config, max_pool_connections=workers)
        for store_path in store_paths:
            try:
                logger.info(f"Uploading {label} store to S3: {store_path}")
                if is_single_file_format(props.format):
                    count = upload_ome_tiff(s3_client, bucket, dc_id, store_path, force=overwrite)
                else:
                    count = upload_zarr_store(
                        s3_client,
                        bucket,
                        dc_id,
                        store_path,
                        workers=workers,
                        force=overwrite,
                        image_path=props.image_path,
                    )
            except Exception as e:
                return {
                    "result": "error",
                    "message": f"Failed to upload {label} store {store_path} to S3: {e}",
                }
            logger.info(f"Uploaded {count} object(s) from {store_path}")
        location = f"s3://{bucket}/{bioimage_s3_prefix(dc_id)}"
    else:
        location = "the registered paths on disk (upload disabled)"

    message = f"{len(store_paths)} {label} store(s) available at {location}"
    if remote:
        message += f"; {remote_note}"
    return _bioimage_success(data_collection, len(store_paths) + len(remote), message)


def _bioimage_success(
    data_collection: DataCollection, n_stores: int, message: str
) -> dict[str, str]:
    rich_print_checked_statement(
        f"Bioimage data collection processed: {data_collection.data_collection_tag} "
        f"({n_stores} store(s))",
        "success",
    )
    return {"result": "success", "message": message}


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

    Returns:
        Result dict with success/error status.
    """
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
    write_result = write_delta_table(
        aggregated_df=result_df,
        destination_file=destination_prefix,
        storage_options=storage_options,
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
