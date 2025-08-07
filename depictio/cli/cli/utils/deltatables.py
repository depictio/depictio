from datetime import datetime

import polars as pl
from deltalake.exceptions import TableNotFoundError
from pydantic import validate_call

from depictio.cli.cli.utils.api_calls import (
    api_get_files_by_dc_id,
    api_upsert_deltatable,
)
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
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
        logger.error(error_msg)
        raise Exception(error_msg)

    files = convert_to_file_objects(files_data)

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
            lf = pl.scan_csv(file_path, **polars_kwargs)
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
        exprs = []
        for col, dtype in unified_schema.items():
            column_names = lf.collect_schema().names()
            if col in column_names:
                exprs.append(pl.col(col).cast(dtype).alias(col))
            else:
                # Create a null literal for the missing column.
                exprs.append(pl.lit(None).cast(dtype).alias(col))
        aligned_lfs.append(lf.select(exprs))
    return aligned_lfs


def aggregate_lazy_dataframes(lazy_frames: list) -> pl.DataFrame:
    """
    Concatenate LazyFrames (after aligning schemas) and add an aggregation timestamp.

    The concatenation is done lazily and the final DataFrame is materialized at the end.

    Args:
        lazy_frames (list): List of Polars LazyFrames.

    Returns:
        pl.DataFrame: The aggregated DataFrame (materialized).
    """
    logger.debug("Aligning LazyFrame schemas.")
    aligned_lfs = align_lazy_schemas(lazy_frames)
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
    try:
        df = pl.read_delta(destination_file, storage_options=storage_options.model_dump())
        logger.debug(f"Delta table read from {destination_file}.")
        return {
            "result": "success",
            "message": f"Delta table read from {destination_file}.",
            "data": df,
        }
    except Exception as e:
        error_msg = f"Issue when reading Delta table: {e}"
        logger.warning(error_msg)
        return {"result": "error", "message": error_msg}


def client_aggregate_data(
    data_collection: DataCollection,
    CLI_config: CLIConfig,
    command_parameters: dict = {},
) -> dict[str, str]:
    """
    Aggregate files from a DataCollection into a Delta Lake object.

    The function:
      - Lists files using the provided Data Collection ID.
      - Converts file dictionaries into validated File objects.
      - Reads each file into a Polars DataFrame based on the metadata.
      - Aligns the DataFrame schemas and aggregates them.
      - Writes the aggregated DataFrame as a Delta Lake table.

    Args:
        dc_id (str): The Data Collection ID.
        data_collection_config (dict): The configuration with "dc_specific_properties"
            (including format and polars_kwargs).
        CLI_config (CLIConfig): CLI configuration object containing API URL and credentials.
        destination_prefix (str, optional): A path prefix for the Delta table destination.
            If not provided, a default destination based on the Data Collection ID is used.

    Returns:
        str: A message indicating the destination of the aggregated Delta table.
    """

    if command_parameters:
        overwrite = command_parameters.get("overwrite", False)
        rich_tables = command_parameters.get("rich_tables", False)
    else:
        overwrite = False
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
        rich_print_checked_statement(
            "Destination already exists, overwrite mode is disabled", "info"
        )
        return {
            "result": "error",
            "message": f"Destination {destination_prefix} already exists and overwrite is disabled.",
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
    lazy_frames = read_files_lazy(files, file_format, polars_kwargs)

    # 4. Aggregate LazyFrames and materialize the result
    aggregated_df = aggregate_lazy_dataframes(lazy_frames)
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

    # Calculate DataFrame size before writing (more accurate than S3 file size estimation)
    logger.info(f"Aggregated DataFrame shape before size calculation: {aggregated_df.shape}")
    logger.debug(f"Aggregated DataFrame columns: {aggregated_df.columns}")
    deltatable_size_bytes = calculate_dataframe_size_bytes(aggregated_df)

    # Enhanced debugging for size calculation
    logger.info(f"🔍 DEBUG: Calculated deltatable_size_bytes = {deltatable_size_bytes}")
    logger.info(f"🔍 DEBUG: Size in MB = {deltatable_size_bytes / (1024 * 1024):.2f} MB")

    if deltatable_size_bytes == 0:
        logger.warning("DataFrame size calculated as 0 bytes - this indicates an empty DataFrame")
        logger.debug(f"DataFrame shape: {aggregated_df.shape}")
        logger.debug(
            f"DataFrame head: {aggregated_df.head(2) if aggregated_df.height > 0 else 'DataFrame is empty'}"
        )

    result = write_delta_table(
        aggregated_df=aggregated_df,
        destination_file=destination_prefix,
        storage_options=storage_options,
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
