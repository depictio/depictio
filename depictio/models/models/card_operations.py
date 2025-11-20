"""
Data models for advanced card metric operations.

Supports building complex metric computation pipelines with multiple steps:
- Filtering data based on conditions
- Grouping data by columns
- Aggregating with various methods
"""

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class FilterOperation(BaseModel):
    """
    Filter operation configuration.

    Supports various comparison operators and value types.

    Examples:
        >>> FilterOperation(column="quality_score", operator=">", value=0.8)
        >>> FilterOperation(column="category", operator="in", value=["A", "B", "C"])
        >>> FilterOperation(column="description", operator="contains", value="high")
    """

    column: str
    operator: Literal[
        "==",
        "!=",
        ">",
        "<",
        ">=",
        "<=",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "is_null",
        "not_null",
    ]
    value: str | int | float | list[str | int | float] | None = None

    @field_validator("value")
    @classmethod
    def validate_value(cls, v, info):
        """Validate that value is provided when required by operator."""
        operator = info.data.get("operator")
        requires_value = operator not in ["is_null", "not_null"]

        if requires_value and v is None:
            raise ValueError(f"Operator '{operator}' requires a value")

        return v

    @model_validator(mode="after")
    def validate_list_operators(self):
        """Validate that list operators have list values."""
        list_operators = ["in", "not_in"]
        if self.operator in list_operators and self.value is not None:
            if not isinstance(self.value, list):
                raise ValueError(f"Operator '{self.operator}' requires a list value")

        return self


class GroupByOperation(BaseModel):
    """
    GroupBy operation configuration.

    Groups data by one or more columns before aggregation.

    Examples:
        >>> GroupByOperation(columns=["category"])
        >>> GroupByOperation(columns=["region", "category"])
    """

    columns: list[str]

    @field_validator("columns")
    @classmethod
    def validate_columns_not_empty(cls, v):
        """Ensure at least one column is specified."""
        if not v or len(v) == 0:
            raise ValueError("At least one column must be specified for groupby")
        return v


class AggregateOperation(BaseModel):
    """
    Aggregation operation configuration.

    Specifies the final aggregation method to compute the metric value.

    Examples:
        >>> AggregateOperation(method="count")  # Count all rows
        >>> AggregateOperation(method="mean", column="temperature")  # Average temperature
        >>> AggregateOperation(method="sum", column="total_reads")  # Sum of reads
    """

    method: Literal["count", "sum", "mean", "median", "min", "max", "std", "var", "nunique"]
    column: str | None = None  # None for count(), required for other methods

    @model_validator(mode="after")
    def validate_column_for_method(self):
        """Validate that column is provided when required by aggregation method."""
        requires_column = self.method != "count"

        if requires_column and not self.column:
            raise ValueError(f"Aggregation method '{self.method}' requires a column")

        return self


class CardOperationStep(BaseModel):
    """
    Single step in an operation pipeline.

    Represents one transformation applied to the data before final aggregation.

    Examples:
        >>> CardOperationStep(
        ...     step_number=1,
        ...     operation_type="filter",
        ...     config=FilterOperation(column="quality", operator=">", value=0.8)
        ... )
        >>> CardOperationStep(
        ...     step_number=2,
        ...     operation_type="groupby",
        ...     config=GroupByOperation(columns=["category"])
        ... )
        >>> CardOperationStep(step_number=3, operation_type="skip")  # No-op step
    """

    step_number: int
    operation_type: Literal["filter", "groupby", "skip"]
    config: FilterOperation | GroupByOperation | None = None

    @model_validator(mode="after")
    def validate_config_for_operation(self):
        """Validate that config is provided for non-skip operations."""
        if self.operation_type != "skip" and not self.config:
            raise ValueError(f"Operation type '{self.operation_type}' requires config")

        if self.operation_type == "skip" and self.config:
            raise ValueError("Skip operation should not have config")

        if self.operation_type == "filter" and not isinstance(self.config, FilterOperation):
            raise ValueError("Filter operation requires FilterOperation config")

        if self.operation_type == "groupby" and not isinstance(self.config, GroupByOperation):
            raise ValueError("GroupBy operation requires GroupByOperation config")

        return self


class CardPipeline(BaseModel):
    """
    Complete card metric computation pipeline.

    Supports both simple mode (backward compatible) and advanced mode with multi-step operations.

    Simple Mode Example:
        >>> CardPipeline(
        ...     mode="simple",
        ...     simple_column="temperature",
        ...     simple_aggregation="mean"
        ... )

    Advanced Mode Example:
        >>> CardPipeline(
        ...     mode="advanced",
        ...     operations=[
        ...         CardOperationStep(
        ...             step_number=1,
        ...             operation_type="filter",
        ...             config=FilterOperation(column="quality_score", operator=">", value=0.8)
        ...         ),
        ...         CardOperationStep(
        ...             step_number=2,
        ...             operation_type="groupby",
        ...             config=GroupByOperation(columns=["category"])
        ...         )
        ...     ],
        ...     final_aggregate=AggregateOperation(method="count")
        ... )
    """

    mode: Literal["simple", "advanced"] = "simple"

    # Simple mode (backward compatible)
    simple_column: str | None = None
    simple_aggregation: str | None = None

    # Advanced mode
    operations: list[CardOperationStep] = []
    final_aggregate: AggregateOperation | None = None

    @model_validator(mode="after")
    def validate_mode_config(self):
        """Validate configuration based on mode."""
        if self.mode == "simple":
            # Simple mode requires column and aggregation
            if not self.simple_column or not self.simple_aggregation:
                raise ValueError("Simple mode requires simple_column and simple_aggregation")

            # Advanced mode fields should be empty
            if self.operations or self.final_aggregate:
                raise ValueError("Simple mode should not have advanced mode fields")

        elif self.mode == "advanced":
            # Advanced mode requires final_aggregate
            if not self.final_aggregate:
                raise ValueError("Advanced mode requires final_aggregate")

            # Simple mode fields should be empty
            if self.simple_column or self.simple_aggregation:
                raise ValueError("Advanced mode should not have simple mode fields")

            # Validate step numbers are sequential
            if self.operations:
                step_numbers = [op.step_number for op in self.operations]
                expected = list(range(1, len(self.operations) + 1))
                if step_numbers != expected:
                    raise ValueError(
                        f"Step numbers must be sequential starting from 1. Got: {step_numbers}"
                    )

        return self

    def get_display_summary(self) -> str:
        """
        Get a human-readable summary of the pipeline.

        Returns:
            str: Pipeline summary text

        Examples:
            >>> pipeline = CardPipeline(mode="simple", simple_column="temp", simple_aggregation="mean")
            >>> pipeline.get_display_summary()
            'Average of temp'

            >>> pipeline = CardPipeline(
            ...     mode="advanced",
            ...     operations=[
            ...         CardOperationStep(1, "filter", FilterOperation("quality", ">", 0.8)),
            ...         CardOperationStep(2, "groupby", GroupByOperation(["category"]))
            ...     ],
            ...     final_aggregate=AggregateOperation("count")
            ... )
            >>> pipeline.get_display_summary()
            'Filter (quality > 0.8) → Group by category → Count'
        """
        if self.mode == "simple":
            agg_display = self.simple_aggregation.title()  # type: ignore[union-attr]
            return f"{agg_display} of {self.simple_column}"

        # Advanced mode
        steps = []

        for op in self.operations:
            if op.operation_type == "filter" and isinstance(op.config, FilterOperation):
                steps.append(f"Filter ({op.config.column} {op.config.operator} {op.config.value})")
            elif op.operation_type == "groupby" and isinstance(op.config, GroupByOperation):
                cols = ", ".join(op.config.columns)
                steps.append(f"Group by {cols}")
            # Skip operations are not shown

        # Add final aggregation
        if self.final_aggregate:
            agg_text = self.final_aggregate.method.title()
            if self.final_aggregate.column:
                agg_text += f" of {self.final_aggregate.column}"
            steps.append(agg_text)

        return " → ".join(steps) if steps else "Empty pipeline"
