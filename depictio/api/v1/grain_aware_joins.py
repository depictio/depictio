"""
Grain-aware join functionality using Polars.

This module provides functions to join DataFrames while automatically handling
different grain levels (row uniqueness) to prevent row explosion and ensure
correct aggregation.

Key principles:
- Base DataFrame determines output grain (no explicit target_grain parameter)
- Automatic aggregation when needed (type-based defaults)
- Sensible defaults with configuration overrides
- No row explosion (prevents accidental cartesian products)
- Bidirectional: supports both aggregation (many→one) and broadcast (one→many)

Example:
    # Aggregate cells to samples (many → one)
    >>> result = grain_aware_join(samples_df, cells_df, on='sample_id')
    >>> len(result) == len(samples_df)  # Output has sample grain
    True

    # Broadcast samples to cells (one → many)
    >>> result = grain_aware_join(cells_df, samples_df, on='sample_id')
    >>> len(result) == len(cells_df)  # Output has cell grain
    True
"""

from typing import Union

import polars as pl


def is_unique_grain(df: pl.DataFrame, columns: Union[str, list[str]]) -> bool:
    """
    Check if column(s) form a unique grain (no duplicate combinations).

    A unique grain means each combination of values in the specified column(s)
    appears at most once in the DataFrame.

    Args:
        df: DataFrame to check
        columns: Column name(s) to check for uniqueness

    Returns:
        True if the column(s) form a unique grain, False otherwise

    Examples:
        >>> df = pl.DataFrame({'id': [1, 2, 3], 'value': [10, 20, 30]})
        >>> is_unique_grain(df, 'id')
        True

        >>> df = pl.DataFrame({'id': [1, 1, 2], 'value': [10, 20, 30]})
        >>> is_unique_grain(df, 'id')
        False
    """
    # Handle empty DataFrame (vacuous truth)
    if len(df) == 0:
        return True

    # Normalize to list
    if isinstance(columns, str):
        columns = [columns]

    # Check if the number of unique combinations equals the number of rows
    n_rows = len(df)
    n_unique = df.select(columns).n_unique()

    return n_rows == n_unique


def grain_aware_join(
    df_base: pl.DataFrame,
    df_other: pl.DataFrame,
    on: Union[str, list[str]],
    how: str = "left",
    aggregations: Union[dict[str, Union[str, pl.Expr]], None] = None,
) -> pl.DataFrame:
    """
    Join DataFrames with automatic grain handling.

    The base DataFrame determines the output grain. If df_other has a non-unique
    join key (finer grain), it will be automatically aggregated to match the base
    DataFrame's grain.

    Args:
        df_base: Base DataFrame (determines output grain)
        df_other: Other DataFrame to join (may be aggregated if needed)
        on: Column(s) to join on
        how: Join type ('left', 'inner', 'outer', 'cross')
        aggregations: Optional dict mapping column names to aggregation methods.
                     Can be string names ('mean', 'sum', 'max', etc.) or Polars expressions.
                     If not provided, uses type-based defaults:
                     - Numeric: mean
                     - String: list
                     - Boolean: sum (count of True values)

    Returns:
        Joined DataFrame with base DataFrame's grain

    Raises:
        KeyError: If join column(s) don't exist in one of the DataFrames
        pl.ColumnNotFoundError: If join column(s) don't exist in one of the DataFrames

    Examples:
        # Simple join with same grain (no aggregation)
        >>> samples = pl.DataFrame({'sample_id': ['S1', 'S2'], 'tissue': ['liver', 'brain']})
        >>> qc = pl.DataFrame({'sample_id': ['S1', 'S2'], 'reads': [1000, 2000]})
        >>> result = grain_aware_join(samples, qc, on='sample_id')
        >>> len(result) == 2
        True

        # Join with aggregation (cells to samples)
        >>> samples = pl.DataFrame({'sample_id': ['S1', 'S2'], 'tissue': ['liver', 'brain']})
        >>> cells = pl.DataFrame({
        ...     'sample_id': ['S1', 'S1', 'S2'],
        ...     'quality': [0.9, 0.8, 0.95]
        ... })
        >>> result = grain_aware_join(samples, cells, on='sample_id')
        >>> len(result) == 2  # Aggregated to sample level
        True

        # Custom aggregations
        >>> result = grain_aware_join(
        ...     samples, cells, on='sample_id',
        ...     aggregations={'quality': 'max'}
        ... )
    """
    # Normalize join columns to list
    if isinstance(on, str):
        on_list = [on]
    else:
        on_list = on

    # Check if join columns exist
    for col in on_list:
        if col not in df_base.columns:
            raise KeyError(f"Join column '{col}' not found in base DataFrame")
        if col not in df_other.columns:
            raise KeyError(f"Join column '{col}' not found in other DataFrame")

    # Check if df_other needs aggregation
    if is_unique_grain(df_other, on_list):
        # Same grain or coarser grain → just join (no aggregation needed)
        result = df_base.join(df_other, on=on, how=how)
    else:
        # Finer grain → aggregate df_other first, then join
        df_other_agg = _aggregate_to_grain(
            df=df_other, grain_columns=on_list, aggregations=aggregations
        )
        result = df_base.join(df_other_agg, on=on, how=how)

    return result


def _aggregate_to_grain(
    df: pl.DataFrame,
    grain_columns: list[str],
    aggregations: Union[dict[str, Union[str, pl.Expr]], None] = None,
) -> pl.DataFrame:
    """
    Aggregate DataFrame to specified grain with type-based defaults.

    Args:
        df: DataFrame to aggregate
        grain_columns: Columns that define the target grain
        aggregations: Optional dict mapping column names to aggregation methods

    Returns:
        Aggregated DataFrame at the specified grain

    Examples:
        >>> df = pl.DataFrame({
        ...     'sample_id': ['S1', 'S1', 'S2'],
        ...     'quality': [0.9, 0.8, 0.95],
        ...     'cell_type': ['T', 'B', 'T']
        ... })
        >>> result = _aggregate_to_grain(df, ['sample_id'])
        >>> len(result) == 2  # Aggregated to sample level
        True
    """
    # Initialize aggregations dict if not provided
    if aggregations is None:
        aggregations = {}

    # Get columns to aggregate (exclude grain columns)
    columns_to_agg = [col for col in df.columns if col not in grain_columns]

    # Build aggregation expressions
    agg_exprs = []

    # Always add a count column to track number of rows aggregated
    agg_exprs.append(pl.len().alias("n_rows"))

    for col in columns_to_agg:
        if col in aggregations:
            # User-specified aggregation
            user_agg = aggregations[col]

            if isinstance(user_agg, str):
                # String aggregation name (e.g., 'mean', 'sum', 'max')
                agg_exprs.append(_build_agg_expr(col, user_agg))
            elif isinstance(user_agg, pl.Expr):
                # Polars expression
                # Check if it already has an alias, if not add one
                agg_exprs.append(user_agg)
            else:
                raise ValueError(
                    f"Invalid aggregation type for column '{col}': {type(user_agg)}. "
                    "Must be str or pl.Expr"
                )
        else:
            # Infer aggregation from column type
            agg_exprs.append(_infer_aggregation(df, col))

    # Perform aggregation
    result = df.group_by(grain_columns).agg(agg_exprs)

    return result


def _infer_aggregation(df: pl.DataFrame, column: str) -> pl.Expr:
    """
    Infer appropriate aggregation based on column dtype.

    Default aggregation strategy:
    - Numeric types (Int*, UInt*, Float*): mean
    - String/Categorical: list (collect all values)
    - Boolean: sum (count of True values)
    - Other types: first (take first value)

    Args:
        df: DataFrame containing the column
        column: Column name to infer aggregation for

    Returns:
        Polars aggregation expression with appropriate alias

    Examples:
        >>> df = pl.DataFrame({'value': [1.0, 2.0, 3.0]})
        >>> expr = _infer_aggregation(df, 'value')
        >>> # Returns: pl.col('value').mean().alias('value_mean')
    """
    dtype = df[column].dtype

    # Numeric types → mean
    if dtype in [
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
        pl.Float32,
        pl.Float64,
    ]:
        return pl.col(column).mean().alias(f"{column}_mean")

    # String/Categorical → list
    elif dtype in [pl.Utf8, pl.Categorical, pl.String]:
        return pl.col(column).implode().alias(f"{column}_list")

    # Boolean → sum (count of True)
    elif dtype == pl.Boolean:
        return pl.col(column).sum().alias(f"{column}_sum")

    # Default → first
    else:
        return pl.col(column).first().alias(f"{column}_first")


def _build_agg_expr(column: str, agg_type: str) -> pl.Expr:
    """
    Build a Polars aggregation expression from a string aggregation type.

    Args:
        column: Column name to aggregate
        agg_type: Aggregation type string ('mean', 'sum', 'max', 'min', 'first',
                 'last', 'median', 'std', 'var', 'count', etc.)

    Returns:
        Polars aggregation expression with appropriate alias

    Raises:
        ValueError: If aggregation type is not recognized

    Examples:
        >>> expr = _build_agg_expr('quality', 'max')
        >>> # Returns: pl.col('quality').max().alias('quality_max')
    """
    # Mapping of string names to Polars aggregation methods
    agg_methods = {
        "mean": lambda col: pl.col(col).mean(),
        "sum": lambda col: pl.col(col).sum(),
        "max": lambda col: pl.col(col).max(),
        "min": lambda col: pl.col(col).min(),
        "first": lambda col: pl.col(col).first(),
        "last": lambda col: pl.col(col).last(),
        "median": lambda col: pl.col(col).median(),
        "std": lambda col: pl.col(col).std(),
        "var": lambda col: pl.col(col).var(),
        "count": lambda col: pl.col(col).count(),
        "list": lambda col: pl.col(col).implode().alias(f"{col}_list"),
        "n_unique": lambda col: pl.col(col).n_unique(),
    }

    if agg_type not in agg_methods:
        raise ValueError(
            f"Unknown aggregation type '{agg_type}'. "
            f"Supported types: {', '.join(agg_methods.keys())}"
        )

    # Build expression with proper alias
    expr = agg_methods[agg_type](column)

    # Add alias if not already present
    if not hasattr(expr, "meta"):
        # If it's a simple aggregation without alias, add one
        if agg_type != "list":  # list already has alias in the lambda
            expr = expr.alias(f"{column}_{agg_type}")

    return expr
