"""
Tests for client-side table joining functionality.

Coverage:
- Join types (inner, left, full)
- Column handling and type normalization
- Edge cases (empty DataFrames, nulls, type mismatches)
- DC resolution and validation
- Granularity aggregation
"""

from unittest.mock import patch

import polars as pl
import pytest
from bson import ObjectId

from depictio.cli.cli.utils.joins import (
    apply_aggregation,
    execute_join,
    find_data_collection_by_tag,
    normalize_join_column_types,
    validate_join_definition,
)
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.joins import (
    AggregationFunction,
    ColumnAggregation,
    GranularityConfig,
    JoinDefinition,
)
from depictio.models.models.projects import Project
from depictio.models.models.workflows import Workflow

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def make_dc(tag: str, dc_id: ObjectId | None = None) -> DataCollection:
    """Create a test DataCollection with minimal required fields.

    Uses source='joined' to skip scan validation requirement.
    """
    return DataCollection(
        id=dc_id or ObjectId(),
        data_collection_tag=tag,
        config={
            "type": "table",
            "source": "joined",
            "dc_specific_properties": {"format": "parquet"},
        },
    )


def make_workflow(name: str, dcs: list[DataCollection]) -> Workflow:
    """Create a test Workflow with given data collections."""
    return Workflow(
        name=name,
        data_collections=dcs,
        engine={"name": "snakemake"},
        data_location={"structure": "flat", "locations": ["/tmp/test"]},
    )


def make_project(
    name: str = "test_project",
    workflows: list[Workflow] | None = None,
    data_collections: list[DataCollection] | None = None,
) -> Project:
    """Create a test Project with given workflows and data collections."""
    return Project(
        name=name,
        workflows=workflows or [],
        data_collections=data_collections or [],
        joins=[],
        permissions={"owners": [], "editors": [], "viewers": []},
    )


def delta_success(df: pl.DataFrame) -> dict:
    """Create a successful delta table read response."""
    return {"result": "success", "data": df}


def delta_error(message: str = "Table not found") -> dict:
    """Create a failed delta table read response."""
    return {"result": "error", "message": message}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_left_df() -> pl.DataFrame:
    """Left DataFrame with 3 rows for join testing."""
    return pl.DataFrame(
        {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
            "value": [10, 20, 30],
            "depictio_run_id": ["run1", "run1", "run1"],
        }
    )


@pytest.fixture
def sample_right_df() -> pl.DataFrame:
    """Right DataFrame with overlapping and new rows."""
    return pl.DataFrame(
        {
            "id": [2, 3, 4],
            "age": [25, 30, 35],
            "score": [100, 200, 300],
            "depictio_run_id": ["run1", "run1", "run1"],
        }
    )


@pytest.fixture
def sample_left_df_with_nulls() -> pl.DataFrame:
    """Left DataFrame with NULL values in join columns."""
    return pl.DataFrame(
        {
            "id": [1, 2, None],
            "name": ["Alice", "Bob", None],
            "value": [10, 20, 30],
        }
    )


@pytest.fixture
def sample_right_df_with_nulls() -> pl.DataFrame:
    """Right DataFrame with NULL values."""
    return pl.DataFrame(
        {
            "id": [2, None, 4],
            "age": [25, 30, 35],
            "score": [100, 200, 300],
        }
    )


@pytest.fixture
def join_definition() -> JoinDefinition:
    """Basic join definition for testing."""
    return JoinDefinition(
        name="test_join",
        left_dc="left_table",
        right_dc="right_table",
        on_columns=["id"],
        how="inner",
        persist=False,
    )


@pytest.fixture
def mock_cli_config() -> CLIConfig:
    """Mock CLI configuration with S3 storage."""
    return CLIConfig(  # type: ignore[call-arg]
        user={
            "email": "test@example.com",
            "is_admin": False,
            "id": "507f1f77bcf86cd799439011",
            "token": {
                "user_id": "507f1f77bcf86cd799439011",
                "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test",
                "refresh_token": "refresh-token-example",
                "token_type": "bearer",
                "token_lifetime": "short-lived",
                "expire_datetime": "2025-12-31 23:59:59",
                "refresh_expire_datetime": "2025-12-31 23:59:59",
                "name": "test_token",
                "created_at": "2025-06-30 18:00:00",
                "logged_in": False,
            },
        },
        api_base_url="https://api.test.com",
        s3_storage={
            "service_name": "minio",
            "service_port": 9000,
            "external_host": "localhost",
            "external_port": 9000,
            "external_protocol": "http",
            "root_user": "minio",
            "root_password": "minio123",
            "bucket": "test-bucket",
        },
    )


@pytest.fixture
def mock_project() -> Project:
    """Mock project with two data collections in one workflow."""
    dc1 = make_dc("left_table")
    dc2 = make_dc("right_table")
    workflow = make_workflow("test_workflow", [dc1, dc2])
    return make_project(workflows=[workflow])


class TestFindDataCollectionByTag:
    """Test data collection resolution logic."""

    def test_simple_tag_in_workflow(self, mock_project):
        """Resolve DC by simple tag within a specified workflow."""
        result_dc, result_workflow = find_data_collection_by_tag(
            mock_project, "left_table", "test_workflow"
        )

        assert result_dc is not None
        assert result_dc.data_collection_tag == "left_table"
        assert result_workflow == "test_workflow"

    def test_workflow_scoped_syntax(self):
        """Resolve DC using 'workflow.tag' syntax when tag exists in multiple workflows."""
        dc1 = make_dc("data")
        dc2 = make_dc("data")
        project = make_project(
            workflows=[
                make_workflow("workflow1", [dc1]),
                make_workflow("workflow2", [dc2]),
            ]
        )

        result_dc, result_workflow = find_data_collection_by_tag(project, "workflow1.data", None)

        assert result_dc is not None
        assert result_dc.id == dc1.id
        assert result_workflow == "workflow1"

    def test_not_found_returns_none(self, mock_project):
        """Return None for non-existent DC tag."""
        result_dc, result_workflow = find_data_collection_by_tag(mock_project, "nonexistent", None)

        assert result_dc is None
        assert result_workflow is None

    def test_project_level_dc(self):
        """Resolve DC at project level (not inside any workflow)."""
        dc = make_dc("project_level_dc")
        project = make_project(data_collections=[dc])

        result_dc, result_workflow = find_data_collection_by_tag(project, "project_level_dc", None)

        assert result_dc is not None
        assert result_dc.data_collection_tag == "project_level_dc"
        assert result_workflow is None


class TestNormalizeJoinColumnTypes:
    """Test join column type normalization."""

    def test_matching_types_unchanged(self):
        """Matching types remain unchanged (both Int64)."""
        left_df = pl.DataFrame({"id": [1, 2, 3]})
        right_df = pl.DataFrame({"id": [2, 3, 4]})

        result_left, result_right = normalize_join_column_types(left_df, right_df, ["id"])

        assert result_left["id"].dtype == pl.Int64
        assert result_right["id"].dtype == pl.Int64

    def test_mismatched_types_cast_to_string(self):
        """Mismatched types (Int vs String) are cast to String."""
        left_df = pl.DataFrame({"id": [1, 2, 3]})
        right_df = pl.DataFrame({"id": ["2", "3", "4"]})

        result_left, result_right = normalize_join_column_types(left_df, right_df, ["id"])

        assert result_left["id"].dtype == pl.String
        assert result_right["id"].dtype == pl.String

    def test_multiple_columns(self):
        """Normalize multiple join columns independently."""
        left_df = pl.DataFrame({"id": [1, 2], "key": ["a", "b"]})
        right_df = pl.DataFrame({"id": [2, 3], "key": [100, 200]})

        result_left, result_right = normalize_join_column_types(left_df, right_df, ["id", "key"])

        assert result_left["id"].dtype == result_right["id"].dtype
        assert result_left["key"].dtype == pl.String
        assert result_right["key"].dtype == pl.String

    def test_missing_column_skipped(self):
        """Missing columns are skipped without error."""
        left_df = pl.DataFrame({"id": [1, 2, 3]})
        right_df = pl.DataFrame({"other_id": [2, 3, 4]})

        result_left, result_right = normalize_join_column_types(left_df, right_df, ["id"])

        assert result_left["id"].dtype == pl.Int64


class TestApplyAggregation:
    """Test granularity mismatch handling via aggregation."""

    @pytest.fixture
    def grouped_df(self) -> pl.DataFrame:
        """DataFrame with 2 rows per group for aggregation testing."""
        return pl.DataFrame({"id": [1, 1, 2, 2], "value": [10.0, 20.0, 30.0, 40.0]})

    def test_mean_aggregation(self, grouped_df):
        """Mean aggregation computes average per group."""
        config = GranularityConfig(
            aggregate_to="id",
            numeric_default=AggregationFunction.MEAN,
            categorical_default=AggregationFunction.FIRST,
        )

        result = apply_aggregation(grouped_df, ["id"], config)

        assert result.shape[0] == 2
        assert result.filter(pl.col("id") == 1)["value"][0] == 15.0
        assert result.filter(pl.col("id") == 2)["value"][0] == 35.0

    def test_sum_aggregation(self):
        """Sum aggregation adds values per group."""
        df = pl.DataFrame({"id": [1, 1, 2, 2], "value": [10, 20, 30, 40]})
        config = GranularityConfig(
            aggregate_to="id",
            numeric_default=AggregationFunction.SUM,
            categorical_default=AggregationFunction.FIRST,
        )

        result = apply_aggregation(df, ["id"], config)

        assert result.filter(pl.col("id") == 1)["value"][0] == 30
        assert result.filter(pl.col("id") == 2)["value"][0] == 70

    def test_categorical_first(self):
        """Categorical columns use first value per group."""
        df = pl.DataFrame(
            {
                "id": [1, 1, 2, 2],
                "category": ["A", "B", "C", "D"],
                "value": [10, 20, 30, 40],
            }
        )
        config = GranularityConfig(
            aggregate_to="id",
            numeric_default=AggregationFunction.MEAN,
            categorical_default=AggregationFunction.FIRST,
        )

        result = apply_aggregation(df, ["id"], config)

        assert result.filter(pl.col("id") == 1)["category"][0] == "A"
        assert result.filter(pl.col("id") == 2)["category"][0] == "C"

    def test_column_override(self):
        """Column-specific override takes precedence over default."""
        df = pl.DataFrame({"id": [1, 1, 2, 2], "value": [10, 20, 30, 40]})
        config = GranularityConfig(
            aggregate_to="id",
            numeric_default=AggregationFunction.MEAN,
            categorical_default=AggregationFunction.FIRST,
            column_overrides=[ColumnAggregation(column="value", function=AggregationFunction.MAX)],
        )

        result = apply_aggregation(df, ["id"], config)

        assert result.filter(pl.col("id") == 1)["value"][0] == 20
        assert result.filter(pl.col("id") == 2)["value"][0] == 40


class TestValidateJoinDefinition:
    """Test join validation logic."""

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_valid_configuration(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Valid join configuration passes all checks."""
        mock_read_delta.side_effect = [
            delta_success(pl.DataFrame({"id": [1, 2], "name": ["A", "B"]})),
            delta_success(pl.DataFrame({"id": [2, 3], "age": [25, 30]})),
        ]

        result = validate_join_definition(join_definition, mock_project, mock_cli_config)

        assert result.is_valid is True
        assert result.left_dc_exists is True
        assert result.right_dc_exists is True
        assert result.left_dc_processed is True
        assert result.right_dc_processed is True
        assert len(result.errors) == 0

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_missing_join_column_in_left(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Validation fails when join column is missing in left DC."""
        mock_read_delta.side_effect = [
            delta_success(pl.DataFrame({"other_id": [1, 2], "name": ["A", "B"]})),
            delta_success(pl.DataFrame({"id": [2, 3], "age": [25, 30]})),
        ]

        result = validate_join_definition(join_definition, mock_project, mock_cli_config)

        assert result.is_valid is False
        assert "id" in result.missing_join_columns_left
        assert len(result.errors) > 0

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_dc_not_processed(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Validation warns when DC exists but Delta table is not created."""
        mock_read_delta.side_effect = [
            delta_error(),
            delta_success(pl.DataFrame({"id": [2, 3], "age": [25, 30]})),
        ]

        result = validate_join_definition(join_definition, mock_project, mock_cli_config)

        assert result.left_dc_processed is False
        assert len(result.warnings) > 0

    def test_dc_not_found(self, join_definition, mock_cli_config):
        """Validation fails when referenced DCs do not exist."""
        empty_project = make_project("empty")

        result = validate_join_definition(join_definition, empty_project, mock_cli_config)

        assert result.is_valid is False
        assert result.left_dc_exists is False
        assert result.right_dc_exists is False
        assert len(result.errors) == 2


class TestExecuteJoinBasic:
    """Test basic join operations with different join types."""

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_inner_join(
        self,
        mock_read_delta,
        join_definition,
        mock_project,
        mock_cli_config,
        sample_left_df,
        sample_right_df,
    ):
        """Inner join preserves only matching rows."""
        join_definition.how = "inner"
        mock_read_delta.side_effect = [
            delta_success(sample_left_df),
            delta_success(sample_right_df),
        ]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert result_df.shape[0] == 2
        assert "name" in result_df.columns
        assert "age" in result_df.columns
        assert metadata["joined_rows"] == 2
        assert metadata["join_type"] == "inner"

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_left_join(
        self,
        mock_read_delta,
        join_definition,
        mock_project,
        mock_cli_config,
        sample_left_df,
        sample_right_df,
    ):
        """Left join preserves all left rows with nulls for unmatched."""
        join_definition.how = "left"
        mock_read_delta.side_effect = [
            delta_success(sample_left_df),
            delta_success(sample_right_df),
        ]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert result_df.shape[0] == 3
        assert metadata["join_type"] == "left"

        # Unmatched left row has null for right columns
        row_1 = result_df.filter(pl.col("id") == 1)
        assert row_1["name"][0] == "Alice"
        assert row_1["age"][0] is None

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_full_join(
        self,
        mock_read_delta,
        join_definition,
        mock_project,
        mock_cli_config,
        sample_left_df,
        sample_right_df,
    ):
        """Full join preserves all rows from both sides."""
        join_definition.how = "full"
        mock_read_delta.side_effect = [
            delta_success(sample_left_df),
            delta_success(sample_right_df),
        ]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert result_df.shape[0] == 4
        assert metadata["joined_rows"] == 4
        assert metadata["join_type"] == "full"


class TestExecuteJoinEdgeCases:
    """Test edge cases in join execution."""

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_empty_left_dataframe(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config, sample_right_df
    ):
        """Inner join with empty left DataFrame yields empty result."""
        empty_df = pl.DataFrame({"id": [], "name": [], "value": []})
        mock_read_delta.side_effect = [
            delta_success(empty_df),
            delta_success(sample_right_df),
        ]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert result_df.shape[0] == 0
        assert metadata["joined_rows"] == 0

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_null_values_do_not_match(
        self,
        mock_read_delta,
        join_definition,
        mock_project,
        mock_cli_config,
        sample_left_df_with_nulls,
        sample_right_df_with_nulls,
    ):
        """NULL values in join columns do not match."""
        mock_read_delta.side_effect = [
            delta_success(sample_left_df_with_nulls),
            delta_success(sample_right_df_with_nulls),
        ]

        result_df, _ = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert result_df.shape[0] == 1

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_multiple_join_columns(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Join on multiple columns requires all to match."""
        left_df = pl.DataFrame(
            {
                "id": [1, 2, 3],
                "category": ["A", "B", "C"],
                "value": [10, 20, 30],
            }
        )
        right_df = pl.DataFrame(
            {
                "id": [2, 3, 4],
                "category": ["B", "X", "D"],
                "score": [100, 200, 300],
            }
        )
        join_definition.on_columns = ["id", "category"]
        mock_read_delta.side_effect = [delta_success(left_df), delta_success(right_df)]

        result_df, _ = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert result_df.shape[0] == 1
        assert result_df["id"][0] == 2
        assert result_df["category"][0] == "B"

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_no_matching_keys(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Inner join with no overlapping keys yields empty result."""
        left_df = pl.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        right_df = pl.DataFrame({"id": [4, 5, 6], "age": [25, 30, 35]})
        mock_read_delta.side_effect = [delta_success(left_df), delta_success(right_df)]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert result_df.shape[0] == 0
        assert metadata["joined_rows"] == 0

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_duplicate_columns_use_left_values(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Duplicate non-join columns are resolved by keeping left values."""
        left_df = pl.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"], "value": [10, 20, 30]})
        right_df = pl.DataFrame(
            {"id": [2, 3, 4], "name": ["X", "Y", "Z"], "value": [100, 200, 300]}
        )
        mock_read_delta.side_effect = [delta_success(left_df), delta_success(right_df)]

        result_df, _ = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        row_2 = result_df.filter(pl.col("id") == 2)
        assert row_2["name"][0] == "B"
        assert row_2["value"][0] == 20

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_type_mismatch_auto_normalized(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Mismatched join column types are normalized to String."""
        left_df = pl.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        right_df = pl.DataFrame({"id": ["2", "3", "4"], "age": [25, 30, 35]})
        mock_read_delta.side_effect = [delta_success(left_df), delta_success(right_df)]

        result_df, _ = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert result_df.shape[0] == 2
        assert result_df["id"].dtype == pl.String

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_auto_adds_depictio_run_id(
        self,
        mock_read_delta,
        join_definition,
        mock_project,
        mock_cli_config,
        sample_left_df,
        sample_right_df,
    ):
        """depictio_run_id is automatically added to join columns."""
        mock_read_delta.side_effect = [
            delta_success(sample_left_df),
            delta_success(sample_right_df),
        ]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert "depictio_run_id" in metadata["join_columns"]
        assert all(result_df["depictio_run_id"] == "run1")


class TestExecuteJoinErrors:
    """Test error handling in join execution."""

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_left_dc_not_found(self, mock_read_delta, join_definition, mock_cli_config):
        """Raises ValueError when left DC does not exist."""
        empty_project = make_project("empty")

        with pytest.raises(ValueError, match="Left data collection"):
            execute_join(join_definition, empty_project, mock_cli_config, apply_granularity=False)

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_right_dc_not_found(self, mock_read_delta, mock_cli_config):
        """Raises ValueError when right DC does not exist."""
        dc = make_dc("left_table")
        project = make_project(workflows=[make_workflow("wf", [dc])])
        join_def = JoinDefinition(
            name="test_join",
            left_dc="left_table",
            right_dc="nonexistent",
            on_columns=["id"],
            how="inner",
        )

        with pytest.raises(ValueError, match="Right data collection"):
            execute_join(join_def, project, mock_cli_config, apply_granularity=False)

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_failed_to_load_left(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Raises ValueError when loading left Delta table fails."""
        mock_read_delta.return_value = delta_error("Failed to read Delta table")

        with pytest.raises(ValueError, match="Failed to load left data collection"):
            execute_join(join_definition, mock_project, mock_cli_config, apply_granularity=False)

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_failed_to_load_right(
        self,
        mock_read_delta,
        join_definition,
        mock_project,
        mock_cli_config,
        sample_left_df,
    ):
        """Raises ValueError when loading right Delta table fails."""
        mock_read_delta.side_effect = [
            delta_success(sample_left_df),
            delta_error("Failed to read Delta table"),
        ]

        with pytest.raises(ValueError, match="Failed to load right data collection"):
            execute_join(join_definition, mock_project, mock_cli_config, apply_granularity=False)


class TestExecuteJoinGranularity:
    """Test granularity aggregation in joins."""

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_aggregates_right_side(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Right side is aggregated when it has finer granularity."""
        left_df = pl.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        right_df = pl.DataFrame({"id": [2, 2, 3, 3], "score": [100, 150, 200, 250]})
        join_definition.granularity = GranularityConfig(
            aggregate_to="id",
            numeric_default=AggregationFunction.MEAN,
            categorical_default=AggregationFunction.FIRST,
        )
        mock_read_delta.side_effect = [delta_success(left_df), delta_success(right_df)]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=True
        )

        assert metadata["aggregation_applied"] is True
        assert metadata["aggregated_side"] == "right"
        assert result_df.shape[0] == 2
        assert result_df.filter(pl.col("id") == 2)["score"][0] == 125.0

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_aggregates_left_side(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """Left side is aggregated when it has finer granularity."""
        left_df = pl.DataFrame({"id": [2, 2, 3, 3], "value": [10, 20, 30, 40]})
        right_df = pl.DataFrame({"id": [2, 3, 4], "score": [100, 200, 300]})
        join_definition.granularity = GranularityConfig(
            aggregate_to="id",
            numeric_default=AggregationFunction.SUM,
            categorical_default=AggregationFunction.FIRST,
        )
        mock_read_delta.side_effect = [delta_success(left_df), delta_success(right_df)]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=True
        )

        assert metadata["aggregation_applied"] is True
        assert metadata["aggregated_side"] == "left"
        assert result_df.shape[0] == 2
        assert result_df.filter(pl.col("id") == 2)["value"][0] == 30
