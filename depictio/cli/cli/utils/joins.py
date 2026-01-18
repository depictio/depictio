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
from depictio.models.models.data_collections import DataCollection
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
    project: Project, dc_tag: str, workflow_name: str | None = None
) -> tuple[DataCollection | None, str | None]:
    """
    Find a data collection by its tag within a project.

    Args:
        project: The project to search in
        dc_tag: The data collection tag to find
        workflow_name: Optional workflow name to scope the search

    Returns:
        Tuple of (DataCollection, workflow_id) or (None, None) if not found
    """
    # Search in workflows
    for workflow in project.workflows:
        if workflow_name and workflow.name != workflow_name:
            continue

        if hasattr(workflow, "config") and workflow.config:
            for dc in workflow.config.data_collections:
                if dc.data_collection_tag == dc_tag:
                    return dc, str(workflow.id) if workflow.id else None

    # Search in direct data collections (basic projects)
    for dc in project.data_collections:
        if dc.data_collection_tag == dc_tag:
            return dc, None

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


def _build_agg_expression(col: str, agg_func: AggregationFunction) -> pl.Expr | None:
    """Build a Polars aggregation expression for a column."""
    if agg_func == AggregationFunction.MEAN:
        return pl.col(col).mean().alias(col)
    elif agg_func == AggregationFunction.SUM:
        return pl.col(col).sum().alias(col)
    elif agg_func == AggregationFunction.MIN:
        return pl.col(col).min().alias(col)
    elif agg_func == AggregationFunction.MAX:
        return pl.col(col).max().alias(col)
    elif agg_func == AggregationFunction.FIRST:
        return pl.col(col).first().alias(col)
    elif agg_func == AggregationFunction.LAST:
        return pl.col(col).last().alias(col)
    elif agg_func == AggregationFunction.COUNT:
        return pl.col(col).count().alias(col)
    elif agg_func == AggregationFunction.MEDIAN:
        return pl.col(col).median().alias(col)
    else:
        logger.warning(f"Unknown aggregation function: {agg_func}")
        return None


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

    # Build metadata
    metadata = {
        "left_dc_id": str(left_dc.id),
        "right_dc_id": str(right_dc.id),
        "left_dc_tag": join_def.left_dc,
        "right_dc_tag": join_def.right_dc,
        "left_rows": left_df.shape[0],
        "right_rows": right_df.shape[0],
        "join_columns": join_def.on_columns,
        "join_type": join_def.how.value,
        "aggregation_applied": False,
    }

    # Apply granularity aggregation if configured
    if apply_granularity and join_def.granularity:
        # Determine which DataFrame needs aggregation
        # The DataFrame with finer granularity (more rows per key) should be aggregated
        left_key_counts = left_df.group_by(join_def.on_columns).len()
        right_key_counts = right_df.group_by(join_def.on_columns).len()

        left_avg_per_key = left_key_counts["len"].mean() if left_key_counts.height > 0 else 1
        right_avg_per_key = right_key_counts["len"].mean() if right_key_counts.height > 0 else 1

        logger.info(f"Average rows per key - Left: {left_avg_per_key}, Right: {right_avg_per_key}")

        # Aggregate the finer-grained DataFrame
        if right_avg_per_key is not None and left_avg_per_key is not None:
            if right_avg_per_key > left_avg_per_key:
                logger.info("Aggregating right DataFrame to match left granularity")
                right_df = apply_aggregation(right_df, join_def.on_columns, join_def.granularity)
                metadata["aggregation_applied"] = True
                metadata["aggregated_side"] = "right"
            elif left_avg_per_key > right_avg_per_key:
                logger.info("Aggregating left DataFrame to match right granularity")
                left_df = apply_aggregation(left_df, join_def.on_columns, join_def.granularity)
                metadata["aggregation_applied"] = True
                metadata["aggregated_side"] = "left"

    # Normalize join column types
    left_df, right_df = normalize_join_column_types(left_df, right_df, join_def.on_columns)

    # Remove duplicated columns (except join columns) from right DataFrame
    # to avoid suffix issues
    right_cols_to_keep = [
        col for col in right_df.columns if col not in left_df.columns or col in join_def.on_columns
    ]
    right_df = right_df.select(right_cols_to_keep)

    # Execute the join
    logger.info(f"Executing {join_def.how.value} join on columns: {join_def.on_columns}")
    joined_df = left_df.join(
        right_df,
        on=join_def.on_columns,
        how=join_def.how.value,
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
    Persist a joined DataFrame as a Delta table.

    Args:
        join_def: The join definition
        joined_df: The joined DataFrame to persist
        project: The project configuration
        CLI_config: CLI configuration
        metadata: Join metadata from execute_join
        overwrite: Whether to overwrite existing table

    Returns:
        Result dict with success/error status
    """
    storage_options = turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)

    # Generate destination path using join name
    # Format: s3://bucket/joined_<join_name>_<left_dc_id>_<right_dc_id>
    destination_prefix = f"s3://{CLI_config.s3_storage.bucket}/joined_{join_def.name}"

    logger.info(f"Persisting joined table to: {destination_prefix}")

    # Check if exists
    existing_result = read_delta_table(destination_prefix, storage_options)
    if existing_result["result"] == "success" and not overwrite:
        return {
            "result": "error",
            "message": f"Joined table already exists at {destination_prefix}. Use --overwrite to replace.",
        }

    # Add join timestamp
    joined_df = joined_df.with_columns(
        pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).alias("join_timestamp")
    )

    # Calculate size
    size_bytes = calculate_dataframe_size_bytes(joined_df)

    # Write Delta table
    write_result = write_delta_table(
        aggregated_df=joined_df,
        destination_file=destination_prefix,
        storage_options=storage_options,
    )

    if write_result["result"] != "success":
        return write_result

    logger.info(f"Successfully persisted joined table with {joined_df.height} rows")

    return {
        "result": "success",
        "message": f"Joined table persisted to {destination_prefix}",
        "location": destination_prefix,
        "rows": joined_df.height,
        "columns": len(joined_df.columns),
        "size_bytes": size_bytes,
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

        # Add columns (limit to first 8 for readability)
        display_cols = preview.joined_columns[:8]
        for col in display_cols:
            sample_table.add_column(col, overflow="fold")

        if len(preview.joined_columns) > 8:
            sample_table.add_column(f"... +{len(preview.joined_columns) - 8} more")

        # Add rows
        for row in preview.sample_rows[:5]:
            values = [str(row.get(col, ""))[:30] for col in display_cols]
            if len(preview.joined_columns) > 8:
                values.append("...")
            sample_table.add_row(*values)

        console.print(sample_table)
