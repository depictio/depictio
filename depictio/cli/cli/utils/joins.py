"""
Client-side table joining utilities for the Depictio CLI.

This module provides functionality for:
- Validating join configurations
- Executing joins locally on the client machine
- Previewing join results before committing
- Handling granularity mismatches with aggregation
- Persisting joined tables to S3 as Delta tables
"""

from datetime import datetime

import polars as pl

from depictio.cli.cli.utils.deltatables import (
    calculate_dataframe_size_bytes,
    read_delta_table,
    write_delta_table,
)
from depictio.cli.cli.utils.rich_utils import (
    console,
    rich_print_checked_statement,
)
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections import DataCollection, DataCollectionSource
from depictio.models.models.joins import (
    AggregationFunction,
    GranularityConfig,
    JoinDefinition,
    JoinPreviewResult,
    JoinValidationResult,
)
from depictio.models.models.projects import Project
from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options


def find_data_collection_by_tag(
    project: Project,
    dc_ref: str,
    default_workflow: str | None = None,
) -> tuple[DataCollection | None, str | None]:
    """
    Find a data collection by tag, supporting workflow-scoped references.

    Args:
        project: Project containing workflows and data collections
        dc_ref: DC reference - either "tag" or "workflow.tag"
        default_workflow: Default workflow name for unscoped tags

    Returns:
        Tuple of (DataCollection, workflow_name) or (None, None)

    Examples:
        find_data_collection_by_tag(proj, "physical_features", "penguin_workflow")
        find_data_collection_by_tag(proj, "workflow_a.sample_metadata", None)
    """
    # Check if dc_ref uses workflow-scoped syntax
    if "." in dc_ref:
        workflow_name, dc_tag = dc_ref.split(".", 1)
        logger.debug(f"Resolving scoped reference: {workflow_name}.{dc_tag}")

        # Search only in specified workflow
        for workflow in project.workflows:
            if workflow.name == workflow_name:
                for dc in workflow.data_collections:
                    if dc.data_collection_tag == dc_tag:
                        logger.info(f"Found DC '{dc_tag}' in workflow '{workflow_name}'")
                        return dc, workflow_name

        logger.warning(f"DC not found: {dc_ref}")
        return None, None

    else:
        # Original logic: search within default_workflow or all workflows
        dc_tag = dc_ref

        # If default_workflow provided, search there first
        if default_workflow:
            for workflow in project.workflows:
                if workflow.name == default_workflow:
                    for dc in workflow.data_collections:
                        if dc.data_collection_tag == dc_tag:
                            logger.info(
                                f"Found DC '{dc_tag}' in default workflow '{default_workflow}'"
                            )
                            return dc, default_workflow

        # Fall back to searching all workflows
        for workflow in project.workflows:
            for dc in workflow.data_collections:
                if dc.data_collection_tag == dc_tag:
                    logger.info(f"Found DC '{dc_tag}' in workflow '{workflow.name}'")
                    return dc, workflow.name

        # Check project-level data collections
        for dc in project.data_collections:
            if dc.data_collection_tag == dc_tag:
                logger.info(f"Found DC '{dc_tag}' at project level")
                return dc, None

        logger.warning(f"DC not found: {dc_tag}")
        return None, None


def validate_join_definition(
    join_def: JoinDefinition,
    project: Project,
    CLI_config: CLIConfig,
) -> JoinValidationResult:
    """
    Validate a join definition against the project configuration.

    Checks:
    - Both data collections exist
    - Both data collections have been processed (Delta tables exist)
    - Join columns exist in both data collections

    Args:
        join_def: The join definition to validate
        project: The project configuration
        CLI_config: CLI configuration for API/S3 access

    Returns:
        JoinValidationResult with validation status and details
    """
    result = JoinValidationResult(is_valid=True)
    storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)

    # Find left data collection
    left_dc, left_workflow_id = find_data_collection_by_tag(
        project, join_def.left_dc, join_def.workflow_name
    )
    if left_dc:
        result.left_dc_exists = True
    else:
        result.is_valid = False
        result.errors.append(f"Left data collection '{join_def.left_dc}' not found in project")

    # Find right data collection
    right_dc, right_workflow_id = find_data_collection_by_tag(
        project, join_def.right_dc, join_def.workflow_name
    )
    if right_dc:
        result.right_dc_exists = True
    else:
        result.is_valid = False
        result.errors.append(f"Right data collection '{join_def.right_dc}' not found in project")

    # Check if Delta tables exist
    if result.left_dc_exists and left_dc and left_dc.id:
        left_delta_path = f"s3://{CLI_config.s3_storage.bucket}/{str(left_dc.id)}"
        left_read_result = read_delta_table(left_delta_path, storage_options)
        if left_read_result["result"] == "success":
            result.left_dc_processed = True
            # Check join columns
            if "data" in left_read_result:
                left_df = left_read_result["data"]
                assert isinstance(left_df, pl.DataFrame)
                left_columns = left_df.columns
                for col in join_def.on_columns:
                    if col not in left_columns:
                        result.missing_join_columns_left.append(col)
        else:
            result.warnings.append(
                f"Left data collection '{join_def.left_dc}' has not been processed yet"
            )

    if result.right_dc_exists and right_dc and right_dc.id:
        right_delta_path = f"s3://{CLI_config.s3_storage.bucket}/{str(right_dc.id)}"
        right_read_result = read_delta_table(right_delta_path, storage_options)
        if right_read_result["result"] == "success":
            result.right_dc_processed = True
            # Check join columns
            if "data" in right_read_result:
                right_df = right_read_result["data"]
                assert isinstance(right_df, pl.DataFrame)
                right_columns = right_df.columns
                for col in join_def.on_columns:
                    if col not in right_columns:
                        result.missing_join_columns_right.append(col)
        else:
            result.warnings.append(
                f"Right data collection '{join_def.right_dc}' has not been processed yet"
            )

    # Add errors for missing columns
    if result.missing_join_columns_left:
        result.is_valid = False
        result.errors.append(
            f"Join columns {result.missing_join_columns_left} not found in left DC '{join_def.left_dc}'"
        )

    if result.missing_join_columns_right:
        result.is_valid = False
        result.errors.append(
            f"Join columns {result.missing_join_columns_right} not found in right DC '{join_def.right_dc}'"
        )

    return result


def apply_aggregation(
    df: pl.DataFrame,
    group_by_columns: list[str],
    granularity_config: GranularityConfig,
) -> pl.DataFrame:
    """
    Apply aggregation to a DataFrame based on granularity configuration.

    Handles granularity mismatches by aggregating data to the target level.

    Args:
        df: The DataFrame to aggregate
        group_by_columns: Columns to group by (typically the join columns)
        granularity_config: Configuration specifying aggregation functions

    Returns:
        Aggregated DataFrame
    """
    logger.info(f"Applying aggregation grouped by: {group_by_columns}")

    # Build aggregation expressions
    agg_exprs = []

    # Get column overrides as a dict for quick lookup
    overrides: dict[str, AggregationFunction] = {}
    if granularity_config.column_overrides:
        for override in granularity_config.column_overrides:
            overrides[override.column] = override.function

    for col in df.columns:
        if col in group_by_columns:
            continue  # Skip group-by columns

        col_dtype = df[col].dtype

        # Determine aggregation function
        if col in overrides:
            agg_func = overrides[col]
        elif col_dtype.is_numeric():
            agg_func = granularity_config.numeric_default
        else:
            agg_func = granularity_config.categorical_default

        # Build Polars expression
        expr = _build_agg_expression(col, agg_func)
        if expr is not None:
            agg_exprs.append(expr)

    if not agg_exprs:
        logger.warning("No aggregation expressions generated, returning original DataFrame")
        return df

    # Apply aggregation
    aggregated_df = df.group_by(group_by_columns).agg(agg_exprs)

    logger.info(f"Aggregation complete: {df.shape[0]} rows -> {aggregated_df.shape[0]} rows")
    return aggregated_df


def _build_agg_expression(col: str, agg_func: str) -> pl.Expr | None:
    """Build a Polars aggregation expression for a column."""
    agg_methods = {
        "mean": pl.Expr.mean,
        "sum": pl.Expr.sum,
        "min": pl.Expr.min,
        "max": pl.Expr.max,
        "first": pl.Expr.first,
        "last": pl.Expr.last,
        "count": pl.Expr.count,
        "median": pl.Expr.median,
    }

    method = agg_methods.get(agg_func)
    if method is None:
        logger.warning(f"Unknown aggregation function: {agg_func}")
        return None

    return method(pl.col(col)).alias(col)


def normalize_join_column_types(
    df1: pl.DataFrame, df2: pl.DataFrame, join_columns: list[str]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """
    Normalize the data types of join columns between two DataFrames.

    If types differ, cast both to String for compatibility.

    Args:
        df1: First DataFrame
        df2: Second DataFrame
        join_columns: List of column names to normalize

    Returns:
        Tuple of normalized DataFrames
    """
    for col in join_columns:
        if col in df1.columns and col in df2.columns:
            dtype1 = df1[col].dtype
            dtype2 = df2[col].dtype

            if dtype1 != dtype2:
                logger.debug(
                    f"Type mismatch in join column '{col}': {dtype1} vs {dtype2}. "
                    "Converting both to String."
                )
                df1 = df1.with_columns(pl.col(col).cast(pl.String))
                df2 = df2.with_columns(pl.col(col).cast(pl.String))

    return df1, df2


def execute_join(
    join_def: JoinDefinition,
    project: Project,
    CLI_config: CLIConfig,
    apply_granularity: bool = True,
) -> tuple[pl.DataFrame, dict]:
    """
    Execute a join operation between two data collections.

    Args:
        join_def: The join definition to execute
        project: The project configuration
        CLI_config: CLI configuration for API/S3 access
        apply_granularity: Whether to apply granularity aggregation

    Returns:
        Tuple of (joined DataFrame, metadata dict)
    """
    storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)

    # Find data collections
    left_dc, _ = find_data_collection_by_tag(project, join_def.left_dc, join_def.workflow_name)
    right_dc, _ = find_data_collection_by_tag(project, join_def.right_dc, join_def.workflow_name)

    if not left_dc or not left_dc.id:
        raise ValueError(f"Left data collection '{join_def.left_dc}' not found or has no ID")
    if not right_dc or not right_dc.id:
        raise ValueError(f"Right data collection '{join_def.right_dc}' not found or has no ID")

    # Load DataFrames
    left_delta_path = f"s3://{CLI_config.s3_storage.bucket}/{str(left_dc.id)}"
    right_delta_path = f"s3://{CLI_config.s3_storage.bucket}/{str(right_dc.id)}"

    logger.info(f"Loading left DataFrame from: {left_delta_path}")
    left_result = read_delta_table(left_delta_path, storage_options)
    if left_result["result"] != "success" or "data" not in left_result:
        raise ValueError(
            f"Failed to load left data collection: {left_result.get('message', 'Unknown error')}"
        )
    left_df = left_result["data"]
    assert isinstance(left_df, pl.DataFrame)

    logger.info(f"Loading right DataFrame from: {right_delta_path}")
    right_result = read_delta_table(right_delta_path, storage_options)
    if right_result["result"] != "success" or "data" not in right_result:
        raise ValueError(
            f"Failed to load right data collection: {right_result.get('message', 'Unknown error')}"
        )
    right_df = right_result["data"]
    assert isinstance(right_df, pl.DataFrame)

    logger.info(f"Left DataFrame shape: {left_df.shape}")
    logger.info(f"Right DataFrame shape: {right_df.shape}")

    # Auto-add depictio_run_id if present in both DataFrames
    # BUT skip if either table is a Metadata table (not aggregated data)
    join_columns = join_def.on_columns.copy()

    left_metatype = left_dc.config.metatype if left_dc.config else None
    right_metatype = right_dc.config.metatype if right_dc.config else None

    if "depictio_run_id" in left_df.columns and "depictio_run_id" in right_df.columns:
        # Skip auto-add if either side is a Metadata table
        if left_metatype == "Metadata" or right_metatype == "Metadata":
            logger.info(
                f"Skipping depictio_run_id auto-add (left_metatype={left_metatype}, "
                f"right_metatype={right_metatype})"
            )
            console.print(
                "  [cyan]ℹ Skipping depictio_run_id auto-add (Metadata table detected)[/cyan]"
            )
        elif "depictio_run_id" not in join_columns:
            join_columns.append("depictio_run_id")
            console.print("  [cyan]ℹ Auto-added depictio_run_id to join keys[/cyan]")
            logger.info("Auto-added depictio_run_id to join columns")

    # Build metadata
    metadata = {
        "left_dc_id": str(left_dc.id),
        "right_dc_id": str(right_dc.id),
        "left_dc_tag": join_def.left_dc,
        "right_dc_tag": join_def.right_dc,
        "left_rows": left_df.shape[0],
        "right_rows": right_df.shape[0],
        "join_columns": join_columns,  # Use updated join_columns
        "join_type": join_def.how,  # Already a string with use_enum_values=True
        "aggregation_applied": False,
    }

    # Apply granularity aggregation if configured
    if apply_granularity and join_def.granularity:
        # Determine which DataFrame needs aggregation
        # The DataFrame with finer granularity (more rows per key) should be aggregated
        left_key_counts = left_df.group_by(join_columns).len()
        right_key_counts = right_df.group_by(join_columns).len()

        left_avg_per_key = left_key_counts["len"].mean() if left_key_counts.height > 0 else 1
        right_avg_per_key = right_key_counts["len"].mean() if right_key_counts.height > 0 else 1

        logger.info(f"Average rows per key - Left: {left_avg_per_key}, Right: {right_avg_per_key}")

        # Aggregate the finer-grained DataFrame
        if right_avg_per_key is not None and left_avg_per_key is not None:
            if right_avg_per_key > left_avg_per_key:
                logger.info("Aggregating right DataFrame to match left granularity")
                right_df = apply_aggregation(right_df, join_columns, join_def.granularity)
                metadata["aggregation_applied"] = True
                metadata["aggregated_side"] = "right"
            elif left_avg_per_key > right_avg_per_key:
                logger.info("Aggregating left DataFrame to match right granularity")
                left_df = apply_aggregation(left_df, join_columns, join_def.granularity)
                metadata["aggregation_applied"] = True
                metadata["aggregated_side"] = "left"

    # Normalize join column types
    left_df, right_df = normalize_join_column_types(left_df, right_df, join_columns)

    # Remove duplicated columns (except join columns) from right DataFrame
    # to avoid suffix issues
    right_cols_to_keep = [
        col for col in right_df.columns if col not in left_df.columns or col in join_columns
    ]
    right_df = right_df.select(right_cols_to_keep)

    # Execute the join
    logger.info(f"Executing {join_def.how} join on columns: {join_columns}")
    joined_df = left_df.join(
        right_df,
        on=join_columns,
        how=join_def.how,  # Already a string with use_enum_values=True
    )

    logger.info(f"Joined DataFrame shape: {joined_df.shape}")
    metadata["joined_rows"] = joined_df.shape[0]
    metadata["joined_columns"] = joined_df.columns

    return joined_df, metadata


def preview_join(
    join_def: JoinDefinition,
    project: Project,
    CLI_config: CLIConfig,
    sample_rows: int = 10,
) -> JoinPreviewResult:
    """
    Generate a preview of a join operation without persisting the result.

    Args:
        join_def: The join definition to preview
        project: The project configuration
        CLI_config: CLI configuration
        sample_rows: Number of sample rows to include in preview

    Returns:
        JoinPreviewResult with statistics and sample data
    """
    storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)

    # Find data collections
    left_dc, _ = find_data_collection_by_tag(project, join_def.left_dc, join_def.workflow_name)
    right_dc, _ = find_data_collection_by_tag(project, join_def.right_dc, join_def.workflow_name)

    if not left_dc or not left_dc.id:
        raise ValueError(f"Left data collection '{join_def.left_dc}' not found")
    if not right_dc or not right_dc.id:
        raise ValueError(f"Right data collection '{join_def.right_dc}' not found")

    # Load DataFrames
    left_delta_path = f"s3://{CLI_config.s3_storage.bucket}/{str(left_dc.id)}"
    right_delta_path = f"s3://{CLI_config.s3_storage.bucket}/{str(right_dc.id)}"

    left_result = read_delta_table(left_delta_path, storage_options)
    right_result = read_delta_table(right_delta_path, storage_options)

    if left_result["result"] != "success" or "data" not in left_result:
        raise ValueError("Failed to load left data collection")
    if right_result["result"] != "success" or "data" not in right_result:
        raise ValueError("Failed to load right data collection")

    left_df = left_result["data"]
    right_df = right_result["data"]
    assert isinstance(left_df, pl.DataFrame)
    assert isinstance(right_df, pl.DataFrame)

    # Calculate key statistics
    left_unique_keys = left_df.select(join_def.on_columns).unique().height
    right_unique_keys = right_df.select(join_def.on_columns).unique().height

    # Find matching keys
    left_keys = set(left_df.select(join_def.on_columns).unique().iter_rows())
    right_keys = set(right_df.select(join_def.on_columns).unique().iter_rows())
    matched_keys = len(left_keys.intersection(right_keys))

    # Execute join
    joined_df, metadata = execute_join(join_def, project, CLI_config)

    # Generate warnings
    warnings = []
    if matched_keys == 0:
        warnings.append("WARNING: No matching keys found between data collections!")
    if matched_keys < min(left_unique_keys, right_unique_keys) * 0.5:
        warnings.append(
            f"WARNING: Only {matched_keys} of {min(left_unique_keys, right_unique_keys)} "
            "keys matched (less than 50%)"
        )

    # Prepare sample rows
    sample_data = joined_df.head(sample_rows).to_dicts()

    # Build aggregation summary
    aggregation_summary = None
    if metadata.get("aggregation_applied"):
        side = metadata.get("aggregated_side", "unknown")
        aggregation_summary = f"Aggregation applied to {side} DataFrame"

    return JoinPreviewResult(
        left_dc_rows=left_df.height,
        right_dc_rows=right_df.height,
        joined_rows=joined_df.height,
        left_dc_columns=left_df.columns,
        right_dc_columns=right_df.columns,
        joined_columns=joined_df.columns,
        left_unique_keys=left_unique_keys,
        right_unique_keys=right_unique_keys,
        matched_keys=matched_keys,
        sample_rows=sample_data,
        warnings=warnings,
        aggregation_applied=metadata.get("aggregation_applied", False),
        aggregation_summary=aggregation_summary,
    )


def persist_joined_table(
    join_def: JoinDefinition,
    joined_df: pl.DataFrame,
    project: Project,
    CLI_config: CLIConfig,
    metadata: dict,
    overwrite: bool = False,
) -> dict:
    """
    Persist a joined DataFrame as a Delta table and update join definition with results.

    This function:
    1. Generates a DataCollection ID for the joined table
    2. Writes the Delta table to S3
    3. Updates the join_def with result metadata
    4. Syncs the updated project to MongoDB
    5. Registers the Delta table location in MongoDB

    Args:
        join_def: The join definition (modified in-place with results)
        joined_df: The joined DataFrame to persist
        project: The project configuration
        CLI_config: CLI configuration
        metadata: Join metadata from execute_join
        overwrite: Whether to overwrite existing table

    Returns:
        Result dict with success/error status
    """
    from depictio.cli.cli.utils.api_calls import (
        api_sync_project_config_to_server,
        api_upsert_deltatable,
    )
    from depictio.models.models.base import PyObjectId
    from depictio.models.utils import convert_model_to_dict

    storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)

    # Step 1: Determine DC ID - prioritize YAML id, then result_dc_id, then generate new
    if join_def.id:
        # Use stable ID from YAML configuration (preferred)
        dc_id = join_def.id
        logger.info(f"Using YAML-specified DC ID for join '{join_def.name}': {dc_id}")
        console.print(f"  [cyan]→ Using YAML-specified DataCollection ID: {dc_id}[/cyan]")
    elif join_def.result_dc_id:
        # Reuse existing ID from previous execution (backward compatibility)
        dc_id = join_def.result_dc_id
        logger.info(f"Reusing existing DC ID for join '{join_def.name}': {dc_id}")
        console.print(f"  [cyan]→ Reusing existing DataCollection ID: {dc_id}[/cyan]")
    else:
        # Generate new ID (first execution without YAML id)
        dc_id = PyObjectId()
        logger.info(f"Generated new DC ID for join '{join_def.name}': {dc_id}")
        console.print(f"  [yellow]⚠ Generated new DataCollection ID: {dc_id}[/yellow]")
        console.print(
            f"  [yellow]  Consider adding 'id: \"{dc_id}\"' to the join definition in your YAML[/yellow]"
        )

    dc_tag = f"joined_{join_def.name}"
    destination_prefix = f"s3://{CLI_config.s3_storage.bucket}/{str(dc_id)}"

    logger.info(f"Persisting joined table to: {destination_prefix}")

    # Step 2: Check if exists
    existing_result = read_delta_table(destination_prefix, storage_options)
    if existing_result["result"] == "success" and not overwrite:
        return {
            "result": "error",
            "message": f"Joined table already exists at {destination_prefix}. Use --overwrite to replace.",
        }

    # Step 3: Add join timestamp
    execution_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    joined_df = joined_df.with_columns(pl.lit(execution_timestamp).alias("join_timestamp"))

    # Step 4: Calculate size
    size_bytes = calculate_dataframe_size_bytes(joined_df)

    # Step 5: Write Delta table to ID-based path
    console.print(f"  [cyan]→ Writing Delta table to: {destination_prefix}[/cyan]")
    write_result = write_delta_table(
        aggregated_df=joined_df,
        destination_file=destination_prefix,
        storage_options=storage_options,
    )

    if write_result["result"] != "success":
        return write_result

    logger.info(f"Successfully persisted joined table with {joined_df.height} rows")

    # Step 6: Update join_def with result metadata
    join_def.result_dc_id = dc_id
    join_def.result_dc_tag = dc_tag
    join_def.delta_location = destination_prefix
    join_def.executed_at = execution_timestamp
    join_def.row_count = joined_df.height
    join_def.column_count = len(joined_df.columns)
    join_def.size_bytes = size_bytes

    console.print("  [green]✓ Updated join definition with execution results[/green]")
    logger.info(f"Updated join '{join_def.name}' with result metadata")

    # Step 6b: Also add a minimal DataCollection entry for UI compatibility
    # This allows the dashboard DC picker to show joins as available data sources
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        DCTableConfig,
    )

    # Check if DC already exists in workflow
    target_workflow = None
    dc_already_exists = False

    for workflow in project.workflows:
        if join_def.workflow_name and workflow.name == join_def.workflow_name:
            target_workflow = workflow
            # Check if DC with this ID already exists
            for dc in workflow.data_collections:
                if str(dc.id) == str(dc_id):
                    dc_already_exists = True
                    break
            break

    if target_workflow and not dc_already_exists:
        # Create minimal DataCollection entry (no scan needed since it's a derived table)
        joined_dc = DataCollection(
            data_collection_tag=dc_tag,
            config=DataCollectionConfig(
                type="table",
                source=DataCollectionSource.JOINED,  # Mark as joined/derived, allows scan=None
                metatype="Aggregate",
                scan=None,  # No scan - this is a derived/joined table
                dc_specific_properties=DCTableConfig(
                    format="parquet",  # Delta tables use Parquet format
                    polars_kwargs={},
                    columns_description={
                        col: f"From join: {join_def.name}" for col in joined_df.columns
                    },
                ),
            ),
            description=join_def.description or f"Joined: {join_def.left_dc} + {join_def.right_dc}",
        )
        joined_dc.id = dc_id

        target_workflow.data_collections.append(joined_dc)
        console.print("  [green]✓ Added DataCollection entry for dashboard UI[/green]")
        logger.info(f"Added DC entry '{dc_tag}' to workflow for UI compatibility")

    # Step 7: Sync updated project to MongoDB (with updated join_def)
    try:
        console.print("  [cyan]→ Syncing project with updated join results to MongoDB[/cyan]")
        project_dict = convert_model_to_dict(project)
        api_sync_project_config_to_server(
            CLI_config=CLI_config, ProjectConfig=project_dict, update=True
        )
        console.print("  [green]✓ Project updated in MongoDB with join results[/green]")
        logger.info(f"Successfully synced project with updated join '{join_def.name}'")
    except Exception as e:
        logger.warning(f"Failed to sync project to MongoDB: {e}")
        console.print(f"  [yellow]⚠ Project sync failed: {e}[/yellow]")

    # Step 8: Register Delta location in MongoDB
    try:
        console.print("  [cyan]→ Registering Delta table location in MongoDB[/cyan]")
        api_upsert_deltatable(
            data_collection_id=str(dc_id),
            delta_table_location=destination_prefix,
            CLI_config=CLI_config,
            update=True,
            deltatable_size_bytes=size_bytes,
        )
        console.print("  [green]✓ Delta table location registered in MongoDB[/green]")
        logger.info(f"Successfully registered Delta location for join '{join_def.name}'")
    except Exception as e:
        logger.warning(f"Failed to register Delta location in MongoDB: {e}")
        console.print(f"  [yellow]⚠ Delta location registration failed: {e}[/yellow]")

    return {
        "result": "success",
        "message": f"Joined table persisted to {destination_prefix}",
        "location": destination_prefix,
        "rows": joined_df.height,
        "columns": len(joined_df.columns),
        "size_bytes": size_bytes,
        "dc_tag": dc_tag,
        "dc_id": str(dc_id),
    }


def process_project_joins(
    project: Project,
    CLI_config: CLIConfig,
    join_name: str | None = None,
    preview_only: bool = False,
    overwrite: bool = False,
    auto_process_dependencies: bool = True,
) -> dict:
    """
    Process all joins defined in a project configuration.

    Args:
        project: The project configuration
        CLI_config: CLI configuration
        join_name: Optional specific join to process (processes all if None)
        preview_only: If True, only generate previews without persisting
        overwrite: Whether to overwrite existing joined tables
        auto_process_dependencies: Whether to auto-process missing source DCs

    Returns:
        Result dict with processing summary
    """
    from depictio.cli.cli.utils.deltatables import client_aggregate_data

    results = {
        "processed": [],
        "skipped": [],
        "errors": [],
    }

    joins_to_process = project.joins
    if join_name:
        joins_to_process = [j for j in project.joins if j.name == join_name]
        if not joins_to_process:
            return {
                "result": "error",
                "message": f"Join '{join_name}' not found in project",
            }

    for join_def in joins_to_process:
        console.print(f"\n[bold blue]Processing join: {join_def.name}[/bold blue]")

        # Validate join
        validation = validate_join_definition(join_def, project, CLI_config)

        if not validation.is_valid:
            for error in validation.errors:
                console.print(f"  [red]Error: {error}[/red]")
            results["errors"].append(
                {
                    "join": join_def.name,
                    "errors": validation.errors,
                }
            )
            continue

        # Handle unprocessed dependencies
        if not validation.left_dc_processed or not validation.right_dc_processed:
            if auto_process_dependencies:
                console.print("  [yellow]Processing missing dependencies...[/yellow]")

                # Process left DC if needed
                if not validation.left_dc_processed:
                    left_dc, _ = find_data_collection_by_tag(
                        project, join_def.left_dc, join_def.workflow_name
                    )
                    if left_dc:
                        console.print(f"    Processing '{join_def.left_dc}'...")
                        try:
                            client_aggregate_data(left_dc, CLI_config, {"overwrite": overwrite})
                        except Exception as e:
                            console.print(f"    [red]Failed: {e}[/red]")
                            results["errors"].append(
                                {
                                    "join": join_def.name,
                                    "errors": [f"Failed to process left DC: {e}"],
                                }
                            )
                            continue

                # Process right DC if needed
                if not validation.right_dc_processed:
                    right_dc, _ = find_data_collection_by_tag(
                        project, join_def.right_dc, join_def.workflow_name
                    )
                    if right_dc:
                        console.print(f"    Processing '{join_def.right_dc}'...")
                        try:
                            client_aggregate_data(right_dc, CLI_config, {"overwrite": overwrite})
                        except Exception as e:
                            console.print(f"    [red]Failed: {e}[/red]")
                            results["errors"].append(
                                {
                                    "join": join_def.name,
                                    "errors": [f"Failed to process right DC: {e}"],
                                }
                            )
                            continue
            else:
                for warning in validation.warnings:
                    console.print(f"  [yellow]Warning: {warning}[/yellow]")
                results["skipped"].append(
                    {
                        "join": join_def.name,
                        "reason": "Source data collections not processed",
                    }
                )
                continue

        # Preview or execute
        if preview_only:
            try:
                preview = preview_join(join_def, project, CLI_config)
                display_join_preview(join_def.name, preview)
                results["processed"].append(
                    {
                        "join": join_def.name,
                        "mode": "preview",
                        "rows": preview.joined_rows,
                    }
                )
            except Exception as e:
                console.print(f"  [red]Preview failed: {e}[/red]")
                results["errors"].append(
                    {
                        "join": join_def.name,
                        "errors": [str(e)],
                    }
                )
        else:
            try:
                # First show preview
                preview = preview_join(join_def, project, CLI_config)
                display_join_preview(join_def.name, preview)

                # Then persist if configured
                if join_def.persist:
                    joined_df, metadata = execute_join(join_def, project, CLI_config)
                    persist_result = persist_joined_table(
                        join_def, joined_df, project, CLI_config, metadata, overwrite
                    )

                    if persist_result["result"] == "success":
                        rich_print_checked_statement(
                            f"Joined table persisted: {persist_result.get('location', 'unknown')}",
                            "success",
                        )
                        results["processed"].append(
                            {
                                "join": join_def.name,
                                "mode": "persisted",
                                "rows": persist_result.get("rows", 0),
                                "location": persist_result.get("location", ""),
                            }
                        )
                    else:
                        console.print(
                            f"  [red]Persist failed: {persist_result.get('message', 'Unknown error')}[/red]"
                        )
                        results["errors"].append(
                            {
                                "join": join_def.name,
                                "errors": [persist_result.get("message", "Unknown error")],
                            }
                        )
                else:
                    results["processed"].append(
                        {
                            "join": join_def.name,
                            "mode": "preview_only",
                            "rows": preview.joined_rows,
                        }
                    )

            except Exception as e:
                console.print(f"  [red]Join failed: {e}[/red]")
                logger.exception(f"Join {join_def.name} failed")
                results["errors"].append(
                    {
                        "join": join_def.name,
                        "errors": [str(e)],
                    }
                )

    return {
        "result": "success" if not results["errors"] else "partial",
        **results,
    }


def display_join_preview(join_name: str, preview: JoinPreviewResult) -> None:
    """Display a join preview in the terminal with rich formatting."""
    from rich.table import Table

    # Build summary table
    summary_table = Table(title=f"Join Preview: {join_name}", show_header=True)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Left DC", style="green")
    summary_table.add_column("Right DC", style="blue")
    summary_table.add_column("Joined", style="magenta")

    summary_table.add_row(
        "Rows",
        str(preview.left_dc_rows),
        str(preview.right_dc_rows),
        str(preview.joined_rows),
    )
    summary_table.add_row(
        "Columns",
        str(len(preview.left_dc_columns)),
        str(len(preview.right_dc_columns)),
        str(len(preview.joined_columns)),
    )
    summary_table.add_row(
        "Unique Keys",
        str(preview.left_unique_keys),
        str(preview.right_unique_keys),
        str(preview.matched_keys),
    )

    console.print(summary_table)

    # Show warnings
    if preview.warnings:
        for warning in preview.warnings:
            console.print(f"  [yellow]{warning}[/yellow]")

    # Show aggregation info
    if preview.aggregation_applied and preview.aggregation_summary:
        console.print(f"  [cyan]Aggregation: {preview.aggregation_summary}[/cyan]")

    # Show sample rows
    if preview.sample_rows:
        sample_table = Table(title="Sample Rows", show_header=True, show_lines=True)

        # Add all columns
        for col in preview.joined_columns:
            sample_table.add_column(col, overflow="fold", max_width=30)

        # Add rows
        for row in preview.sample_rows[:5]:
            values = [str(row.get(col, "")) for col in preview.joined_columns]
            sample_table.add_row(*values)

        console.print(sample_table)
