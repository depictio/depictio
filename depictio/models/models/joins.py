"""
Models for client-side table joining configuration.

This module defines the data models for configuring table joins in the project YAML.
Joins are defined at the project level (top-level `joins:` key) and specify how
data collections should be combined, including handling granularity mismatches.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from depictio.models.models.base import MongoModel, PyObjectId


class JoinType(str, Enum):
    """Supported join types."""

    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    OUTER = "outer"


class AggregationFunction(str, Enum):
    """Supported aggregation functions for granularity mismatches."""

    MEAN = "mean"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    FIRST = "first"
    LAST = "last"
    COUNT = "count"
    MEDIAN = "median"


class ColumnAggregation(BaseModel):
    """
    Aggregation configuration for a specific column.

    Allows fine-grained control over how individual columns are aggregated
    when joining tables with different granularities.
    """

    column: str = Field(..., description="Column name to apply aggregation to")
    function: AggregationFunction = Field(..., description="Aggregation function to apply")

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class GranularityConfig(BaseModel):
    """
    Configuration for handling granularity mismatches between joined tables.

    When joining tables at different levels (e.g., samples vs cells), this
    configuration specifies how to aggregate data to the target granularity.

    Example:
        DC A (samples): one row per sample
        DC B (cells): multiple rows per sample (cells within samples)

        When joining with granularity="sample", DC B data will be aggregated
        per sample using the specified aggregation functions.
    """

    # The target granularity level for the join
    # This corresponds to the column(s) that define the granularity
    aggregate_to: str = Field(
        ...,
        description="Target granularity level - column name that defines the aggregation key",
    )

    # Default aggregation for numeric columns
    numeric_default: AggregationFunction = Field(
        default=AggregationFunction.MEAN,
        description="Default aggregation function for numeric columns",
    )

    # Default aggregation for categorical/string columns
    categorical_default: AggregationFunction = Field(
        default=AggregationFunction.FIRST,
        description="Default aggregation function for categorical/string columns",
    )

    # Per-column overrides for aggregation functions
    column_overrides: list[ColumnAggregation] | None = Field(
        default=None,
        description="Custom aggregation functions for specific columns",
    )

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class JoinDefinition(BaseModel):
    """
    Definition of a single join operation between data collections.

    This is the primary configuration for specifying how tables should be joined.
    Defined at the project level in the YAML configuration.

    DC References Support:
    - Simple tag: "physical_features" (searches within workflow_name)
    - Scoped tag: "workflow_a.physical_features" (explicit workflow reference)
    - Cross-workflow: Use scoped tags when joining DCs from different workflows

    Example YAML (same-workflow join):
        joins:
          - name: "gene_expression_with_metadata"
            left_dc: "gene_tpm"
            right_dc: "sample_metadata"
            on_columns:
              - "sample"
            how: "inner"
            workflow_name: "genomics_workflow"
            description: "Join gene TPM with sample metadata"

    Example YAML (cross-workflow join):
        joins:
          - name: "multi_workflow_analysis"
            left_dc: "workflow_a.sample_metadata"
            right_dc: "workflow_b.results"
            on_columns:
              - "sample_id"
            how: "inner"
            description: "Join sample data from workflow A with results from workflow B"
    """

    # Optional stable ID for the join (can be specified in YAML to maintain stable DC IDs)
    id: PyObjectId | None = Field(
        default=None,
        description="Stable DataCollection ID for the joined table (optional, specified in YAML)",
    )

    # Human-readable name for the join (used as identifier)
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique name for this join definition",
    )

    # Source data collections
    left_dc: str = Field(
        ...,
        description="Data collection tag for the left side of the join",
    )
    right_dc: str = Field(
        ...,
        description="Data collection tag for the right side of the join",
    )

    # Join configuration
    on_columns: list[str] = Field(
        ...,
        min_length=1,
        description="Column(s) to join on - must exist in both data collections",
    )

    how: JoinType = Field(
        default=JoinType.INNER,
        description="Type of join: inner, left, right, or outer",
    )

    # Optional description
    description: str | None = Field(
        default=None,
        description="Human-readable description of the join purpose",
    )

    # Granularity configuration for handling mismatches
    granularity: GranularityConfig | None = Field(
        default=None,
        description="Configuration for handling granularity mismatches",
    )

    # Whether to persist the joined result as a Delta table
    persist: bool = Field(
        default=True,
        description="Whether to persist the joined result as a Delta table",
    )

    # Workflow scope - if specified, restricts join to this workflow
    workflow_name: str | None = Field(
        default=None,
        description="Workflow name to scope this join to (optional)",
    )

    # ===== Join Execution Results (populated after join is executed) =====
    result_dc_id: PyObjectId | None = Field(
        default=None,
        description="DataCollection ID for the joined table (used in S3 path)",
    )
    result_dc_tag: str | None = Field(
        default=None,
        description="DataCollection tag for the joined table (e.g., 'joined_penguins_complete')",
    )
    delta_location: str | None = Field(
        default=None,
        description="S3 path to the persisted Delta table",
    )
    executed_at: str | None = Field(
        default=None,
        description="Timestamp when the join was last executed",
    )
    row_count: int | None = Field(
        default=None,
        description="Number of rows in the joined table",
    )
    column_count: int | None = Field(
        default=None,
        description="Number of columns in the joined table",
    )
    size_bytes: int | None = Field(
        default=None,
        description="Size of the Delta table in bytes",
    )

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate join name contains only valid characters."""
        import re

        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "Join name must contain only alphanumeric characters, underscores, and hyphens"
            )
        return v

    @field_validator("on_columns")
    @classmethod
    def validate_on_columns(cls, v: list[str]) -> list[str]:
        """Ensure on_columns is not empty and has unique values."""
        if not v:
            raise ValueError("on_columns must contain at least one column")
        if len(v) != len(set(v)):
            raise ValueError("on_columns must not contain duplicates")
        return v

    @model_validator(mode="after")
    def validate_left_right_different(self) -> "JoinDefinition":
        """Ensure left and right data collections are different."""
        if self.left_dc == self.right_dc:
            raise ValueError("left_dc and right_dc must be different data collections")
        return self


class JoinedTableMetadata(MongoModel):
    """
    Metadata for a persisted joined Delta table.

    Stores lineage information about how the joined table was created,
    including source data collections and join configuration.
    """

    # Reference to the join definition
    join_name: str = Field(..., description="Name of the join definition")

    # Source data collection IDs
    left_dc_id: PyObjectId = Field(..., description="ID of the left data collection")
    right_dc_id: PyObjectId = Field(..., description="ID of the right data collection")

    # Delta table location
    delta_table_location: str = Field(..., description="S3 path to the joined Delta table")

    # Join statistics
    row_count: int = Field(default=0, description="Number of rows in joined table")
    column_count: int = Field(default=0, description="Number of columns in joined table")
    size_bytes: int = Field(default=0, description="Size of the Delta table in bytes")

    # Lineage information
    left_dc_row_count: int = Field(default=0, description="Row count of left DC at join time")
    right_dc_row_count: int = Field(default=0, description="Row count of right DC at join time")

    # Join configuration snapshot (for reproducibility)
    join_config_snapshot: dict = Field(
        default_factory=dict, description="Snapshot of join configuration at creation time"
    )

    # Timestamps
    created_at: str | None = Field(default=None, description="Creation timestamp")
    updated_at: str | None = Field(default=None, description="Last update timestamp")

    model_config = ConfigDict(extra="allow")


class JoinPreviewResult(BaseModel):
    """
    Result of a join preview operation.

    Contains statistics and sample data to help users validate
    their join configuration before committing.
    """

    # Basic statistics
    left_dc_rows: int
    right_dc_rows: int
    joined_rows: int

    # Column information
    left_dc_columns: list[str]
    right_dc_columns: list[str]
    joined_columns: list[str]

    # Join key statistics
    left_unique_keys: int
    right_unique_keys: int
    matched_keys: int

    # Sample data (as list of dicts for easy display)
    sample_rows: list[dict]

    # Warnings or issues
    warnings: list[str] = Field(default_factory=list)

    # Granularity info
    aggregation_applied: bool = False
    aggregation_summary: str | None = None

    model_config = ConfigDict(extra="forbid")


class JoinValidationResult(BaseModel):
    """
    Result of validating a join configuration.

    Used to check if a join can be executed before actually running it.
    """

    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # Data collection status
    left_dc_exists: bool = False
    right_dc_exists: bool = False
    left_dc_processed: bool = False
    right_dc_processed: bool = False

    # Column validation
    missing_join_columns_left: list[str] = Field(default_factory=list)
    missing_join_columns_right: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")
