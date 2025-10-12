"""
Card operation executor for advanced metric computations.

Executes operation pipelines on Polars DataFrames to compute card metric values.
"""

import polars as pl

from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.card_operations import (
    AggregateOperation,
    CardPipeline,
    FilterOperation,
    GroupByOperation,
)


class CardOperationExecutor:
    """
    Execute card operation pipelines on Polars DataFrames.

    Supports sequential execution of filter, groupby, and aggregation operations
    to compute complex metrics from tabular data.

    Examples:
        >>> executor = CardOperationExecutor()
        >>> pipeline = CardPipeline(
        ...     mode="advanced",
        ...     operations=[
        ...         CardOperationStep(1, "filter", FilterOperation("quality", ">", 0.8)),
        ...         CardOperationStep(2, "groupby", GroupByOperation(["category"]))
        ...     ],
        ...     final_aggregate=AggregateOperation("count")
        ... )
        >>> result = executor.execute_pipeline(df, pipeline)
    """

    def execute_pipeline(
        self, df: pl.DataFrame, pipeline: CardPipeline
    ) -> pl.DataFrame | float | int | str:
        """
        Execute a complete operation pipeline and return the result.

        Args:
            df: Input DataFrame to process
            pipeline: Pipeline configuration with operation steps

        Returns:
            Result value(s):
            - Simple aggregations return scalar (float/int)
            - Grouped aggregations return DataFrame with results per group
            - String aggregations (mode) return string

        Raises:
            Exception: If pipeline execution fails

        Examples:
            Simple mode (backward compatible):
            >>> pipeline = CardPipeline(mode="simple", simple_column="temp", simple_aggregation="mean")
            >>> result = executor.execute_pipeline(df, pipeline)
            >>> # Returns: 25.5

            Advanced mode with filter:
            >>> pipeline = CardPipeline(
            ...     mode="advanced",
            ...     operations=[
            ...         CardOperationStep(1, "filter", FilterOperation("quality", ">", 0.8))
            ...     ],
            ...     final_aggregate=AggregateOperation("count")
            ... )
            >>> result = executor.execute_pipeline(df, pipeline)
            >>> # Returns: 123

            Advanced mode with groupby:
            >>> pipeline = CardPipeline(
            ...     mode="advanced",
            ...     operations=[
            ...         CardOperationStep(1, "groupby", GroupByOperation(["category"]))
            ...     ],
            ...     final_aggregate=AggregateOperation("mean", "temperature")
            ... )
            >>> result = executor.execute_pipeline(df, pipeline)
            >>> # Returns: DataFrame with average temperature per category
        """
        try:
            logger.info(f"🚀 Executing card pipeline: {pipeline.mode} mode")
            logger.debug(f"Input DataFrame shape: {df.shape}")

            # Handle simple mode (backward compatibility)
            if pipeline.mode == "simple":
                return self._execute_simple_mode(df, pipeline)

            # Advanced mode: Execute operation steps sequentially
            current_df = df
            groupby_columns: list[str] | None = None

            for step in pipeline.operations:
                if step.operation_type == "skip":
                    logger.debug(f"Step {step.step_number}: Skipped")
                    continue

                logger.info(f"Executing step {step.step_number}: {step.operation_type}")

                if step.operation_type == "filter":
                    if step.config is None or not isinstance(step.config, FilterOperation):
                        raise ValueError(f"Step {step.step_number}: Invalid filter config")
                    current_df = self._execute_filter(current_df, step.config)
                    logger.debug(f"After filter: {current_df.shape}")

                elif step.operation_type == "groupby":
                    if step.config is None or not isinstance(step.config, GroupByOperation):
                        raise ValueError(f"Step {step.step_number}: Invalid groupby config")
                    # Store groupby columns for later use in aggregation
                    groupby_columns = step.config.columns
                    # Validate columns exist
                    current_df = self._prepare_grouped_df(current_df, step.config)
                    logger.debug(f"Will group by: {groupby_columns}")

            # Execute final aggregation
            if pipeline.final_aggregate is None:
                raise ValueError("Pipeline must have final_aggregate")

            result = self._execute_aggregate(current_df, pipeline.final_aggregate, groupby_columns)

            logger.info(f"✅ Pipeline execution completed. Result type: {type(result)}")
            return result

        except Exception as e:
            logger.error(f"❌ Pipeline execution failed: {e}", exc_info=True)
            raise Exception(f"Failed to execute card pipeline: {str(e)}") from e

    def _execute_simple_mode(self, df: pl.DataFrame, pipeline: CardPipeline) -> float | int | str:
        """
        Execute simple mode aggregation (backward compatibility).

        Args:
            df: Input DataFrame
            pipeline: Pipeline with simple_column and simple_aggregation

        Returns:
            Scalar result value
        """
        if not pipeline.simple_column or not pipeline.simple_aggregation:
            raise ValueError("Simple mode requires simple_column and simple_aggregation")

        logger.info(f"Simple mode: {pipeline.simple_aggregation}({pipeline.simple_column})")

        # Import existing compute_value function for backward compatibility
        from depictio.dash.modules.card_component.utils import compute_value

        result = compute_value(df, pipeline.simple_column, pipeline.simple_aggregation)
        return result

    def _execute_filter(self, df: pl.DataFrame, config: FilterOperation) -> pl.DataFrame:
        """
        Apply filter operation to DataFrame.

        Supports various comparison operators and handles type conversions.

        Args:
            df: Input DataFrame
            config: Filter configuration

        Returns:
            Filtered DataFrame

        Raises:
            Exception: If filter execution fails
        """
        try:
            column = config.column
            operator = config.operator
            value = config.value

            logger.debug(f"Filter: {column} {operator} {value}")

            # Build Polars expression based on operator
            if operator == "==":
                if value is None:
                    raise ValueError("Operator '==' requires a value")
                filter_expr = pl.col(column) == value

            elif operator == "!=":
                if value is None:
                    raise ValueError("Operator '!=' requires a value")
                filter_expr = pl.col(column) != value

            elif operator == ">":
                if value is None:
                    raise ValueError("Operator '>' requires a value")
                filter_expr = pl.col(column) > value

            elif operator == "<":
                if value is None:
                    raise ValueError("Operator '<' requires a value")
                filter_expr = pl.col(column) < value

            elif operator == ">=":
                if value is None:
                    raise ValueError("Operator '>=' requires a value")
                filter_expr = pl.col(column) >= value

            elif operator == "<=":
                if value is None:
                    raise ValueError("Operator '<=' requires a value")
                filter_expr = pl.col(column) <= value

            elif operator == "in":
                if value is None or not isinstance(value, list):
                    raise ValueError("Operator 'in' requires a list value")
                # Cast both column and values to string for compatibility
                filter_expr = pl.col(column).cast(pl.String).is_in([str(v) for v in value])

            elif operator == "not_in":
                if value is None or not isinstance(value, list):
                    raise ValueError("Operator 'not_in' requires a list value")
                filter_expr = ~pl.col(column).cast(pl.String).is_in([str(v) for v in value])

            elif operator == "contains":
                if value is None:
                    raise ValueError("Operator 'contains' requires a value")
                filter_expr = pl.col(column).cast(pl.String).str.contains(str(value))

            elif operator == "not_contains":
                if value is None:
                    raise ValueError("Operator 'not_contains' requires a value")
                filter_expr = ~pl.col(column).cast(pl.String).str.contains(str(value))

            elif operator == "is_null":
                filter_expr = pl.col(column).is_null()

            elif operator == "not_null":
                filter_expr = pl.col(column).is_not_null()

            else:
                raise ValueError(f"Unsupported operator: {operator}")

            # Apply filter
            filtered_df = df.filter(filter_expr)

            logger.debug(
                f"Filter result: {filtered_df.height}/{df.height} rows ({filtered_df.height / df.height * 100:.1f}%)"
            )

            return filtered_df

        except Exception as e:
            logger.error(f"Filter execution failed: {e}")
            raise Exception(
                f"Failed to apply filter '{column} {operator} {value}': {str(e)}"
            ) from e

    def _prepare_grouped_df(self, df: pl.DataFrame, config: GroupByOperation) -> pl.DataFrame:
        """
        Prepare DataFrame for groupby operation.

        Note: This doesn't execute the groupby yet - that happens during aggregation.
        This method validates columns and returns the DataFrame with metadata.

        Args:
            df: Input DataFrame
            config: GroupBy configuration

        Returns:
            DataFrame ready for grouped aggregation (same as input for now)
        """
        # Validate that groupby columns exist
        missing_cols = [col for col in config.columns if col not in df.columns]
        if missing_cols:
            raise ValueError(f"GroupBy columns not found in DataFrame: {missing_cols}")

        logger.debug(f"Prepared DataFrame for groupby on columns: {config.columns}")

        # For now, just return the DataFrame - the actual groupby happens in aggregate
        # We could store groupby config in a custom attribute if needed
        return df

    def _execute_aggregate(
        self,
        df: pl.DataFrame,
        config: AggregateOperation,
        groupby_columns: list[str] | None = None,
    ) -> pl.DataFrame | float | int | str:
        """
        Execute aggregation operation.

        If groupby_columns is provided, aggregation is performed per group.
        Otherwise, aggregation is performed on the entire DataFrame.

        Args:
            df: Input DataFrame (may have been filtered)
            config: Aggregation configuration
            groupby_columns: Optional list of columns to group by before aggregation

        Returns:
            Aggregation result:
            - Scalar (float/int/str) for non-grouped aggregations
            - DataFrame with group columns + aggregated value for grouped aggregations
        """
        try:
            method = config.method
            column = config.column

            logger.debug(f"Aggregate: {method}({column if column else ''})")

            # Build aggregation expression
            if method == "count":
                agg_expr = pl.count().alias("value")

            elif method == "sum":
                if not column:
                    raise ValueError("Sum aggregation requires a column")
                agg_expr = pl.col(column).sum().alias("value")

            elif method == "mean":
                if not column:
                    raise ValueError("Mean aggregation requires a column")
                agg_expr = pl.col(column).mean().alias("value")

            elif method == "median":
                if not column:
                    raise ValueError("Median aggregation requires a column")
                agg_expr = pl.col(column).median().alias("value")

            elif method == "min":
                if not column:
                    raise ValueError("Min aggregation requires a column")
                agg_expr = pl.col(column).min().alias("value")

            elif method == "max":
                if not column:
                    raise ValueError("Max aggregation requires a column")
                agg_expr = pl.col(column).max().alias("value")

            elif method == "std":
                if not column:
                    raise ValueError("Std dev aggregation requires a column")
                agg_expr = pl.col(column).std().alias("value")

            elif method == "var":
                if not column:
                    raise ValueError("Variance aggregation requires a column")
                agg_expr = pl.col(column).var().alias("value")

            elif method == "nunique":
                if not column:
                    raise ValueError("Nunique aggregation requires a column")
                agg_expr = pl.col(column).n_unique().alias("value")

            else:
                raise ValueError(f"Unsupported aggregation method: {method}")

            # Execute aggregation
            if groupby_columns:
                # Grouped aggregation - return DataFrame with results per group
                logger.debug(f"Grouped aggregation by {groupby_columns}")
                result_df = df.group_by(groupby_columns).agg(agg_expr)
                logger.debug(f"Grouped result shape: {result_df.shape}")
                return result_df
            else:
                # Non-grouped aggregation - return scalar
                result_df = df.select(agg_expr)
                result_value = result_df[0, "value"]

                logger.debug(f"Aggregation result: {result_value}")
                return result_value

        except Exception as e:
            logger.error(f"Aggregation execution failed: {e}")
            raise Exception(f"Failed to execute aggregation '{method}': {str(e)}") from e
