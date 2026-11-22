"""
Tests for client-side table joining functionality.

Coverage:
- Join types (inner, left, full)
- Column handling and type normalization
- Edge cases (empty DataFrames, nulls, type mismatches)
- DC resolution and validation
- Granularity aggregation
- Persisting: Delta provenance in the registration, no commit when nothing moved
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from bson import ObjectId

from depictio.cli.cli.utils.delta_versioning import list_delta_versions, read_delta_commit_info
from depictio.cli.cli.utils.deltatables import read_delta_table, write_delta_table
from depictio.cli.cli.utils.joins import (
    JoinPersistHooks,
    apply_aggregation,
    execute_join,
    find_data_collection_by_tag,
    normalize_join_column_types,
    persist_joined_table,
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
from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

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

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_fanout_warning_attached_when_keys_duplicate(
        self, mock_read_delta, join_definition, mock_project, mock_cli_config
    ):
        """When a join produces more rows than max(left, right), the metadata
        carries a `fanout_warning` entry naming the offending input and ratio.

        Mirrors the penguin bug at #6824cb3b: per-species CSVs all reset
        ``ID_1, ID_2, ...`` so the same ``individual_id`` appears in 3 runs;
        an inner join on ``individual_id`` then triples each individual.
        """
        # Both sides have id=1 repeated 3× — inner join on `id` alone produces
        # a 9-row cartesian per match.
        left_df = pl.DataFrame({"id": [1, 1, 1, 2], "name": ["a1", "a2", "a3", "b"]})
        right_df = pl.DataFrame({"id": [1, 1, 1, 2], "value": [10, 20, 30, 40]})
        mock_read_delta.side_effect = [delta_success(left_df), delta_success(right_df)]

        result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        # 3×3 fan-out for id=1, 1×1 for id=2 → 10 rows total, > max(4,4)=4.
        assert result_df.shape[0] == 10
        assert "fanout_warning" in metadata
        warning = metadata["fanout_warning"]
        assert warning["actual_rows"] == 10
        assert warning["expected_max"] == 4
        assert warning["ratio"] == 2.5
        assert "non-unique join key" in warning["message"]

    @patch("depictio.cli.cli.utils.joins.read_delta_table")
    def test_no_fanout_warning_for_unique_keys(
        self,
        mock_read_delta,
        join_definition,
        mock_project,
        mock_cli_config,
        sample_left_df,
        sample_right_df,
    ):
        """Joins on unique keys must not flag a fan-out warning — guards against
        false positives on the happy path."""
        mock_read_delta.side_effect = [
            delta_success(sample_left_df),
            delta_success(sample_right_df),
        ]

        _result_df, metadata = execute_join(
            join_definition, mock_project, mock_cli_config, apply_granularity=False
        )

        assert "fanout_warning" not in metadata


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


# ---------------------------------------------------------------------------
# Persisting: the commit's provenance, and no commit when nothing moved
# ---------------------------------------------------------------------------


class _FakeServer:
    """The two API calls a persist makes about the joined table, kept in memory.

    ``upserts`` records every registration; ``get_deltatable`` answers from
    them, as the server answers from the aggregations the upserts appended.
    """

    def __init__(self, knows_the_table: bool = True, upsert_status: int = 200):
        self.upserts: list[dict] = []
        self.knows_the_table = knows_the_table
        self.upsert_status = upsert_status

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        return MagicMock(status_code=self.upsert_status, text="server error")

    def get_deltatable(self, dc_id, CLI_config):
        aggregations = [
            {"delta_version": (u.get("delta_provenance") or {}).get("delta_version")}
            for u in self.upserts
        ]
        if not self.knows_the_table or not aggregations:
            return MagicMock(status_code=404)
        return MagicMock(status_code=200, json=lambda: {"aggregation": aggregations})


class TestPersistJoinedTable:
    """Against a real Delta table in tmp_path: the history the stamp reads back
    is delta-rs's own output, whose shape differs between deltalake versions."""

    JOIN_ID = str(ObjectId())

    @pytest.fixture
    def setup(self, tmp_path, mock_cli_config):
        workflow = make_workflow("wf", [make_dc("left_table"), make_dc("right_table")])
        project = make_project(workflows=[workflow])
        join_def = JoinDefinition(
            id=ObjectId(self.JOIN_ID),
            name="complete",
            left_dc="left_table",
            right_dc="right_table",
            on_columns=["id"],
            how="inner",
            persist=True,
            workflow_name="wf",
        )
        return tmp_path, project, join_def, mock_cli_config

    def persist(self, setup, joined_df: pl.DataFrame, server: _FakeServer) -> dict:
        tmp_path, project, join_def, cli_config = setup

        def local(path: str) -> str:
            # s3://<bucket>/<dc_id> -> a directory of the test's own
            return str(tmp_path / path.rsplit("/", 1)[-1])

        with (
            patch(
                "depictio.cli.cli.utils.joins.read_delta_table",
                side_effect=lambda path, opts: read_delta_table(local(path), opts),
            ),
            patch(
                "depictio.cli.cli.utils.joins.write_delta_table",
                side_effect=lambda destination_file, **kw: write_delta_table(
                    destination_file=local(destination_file), **kw
                ),
            ),
            patch(
                "depictio.cli.cli.utils.joins.read_delta_commit_info",
                side_effect=lambda path, opts: read_delta_commit_info(local(path), opts),
            ),
            patch("depictio.cli.cli.utils.api_calls.api_sync_project_config_to_server"),
            patch(
                "depictio.cli.cli.utils.api_calls.api_upsert_deltatable",
                side_effect=server.upsert,
            ),
            patch(
                "depictio.cli.cli.utils.api_calls.api_get_deltatable_by_dc_id",
                side_effect=server.get_deltatable,
            ),
        ):
            return persist_joined_table(
                join_def, joined_df, project, cli_config, metadata={}, overwrite=True
            )

    @staticmethod
    def joined(values: list[int]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "id": list(range(len(values))),
                "value": values,
                "depictio_run_id": [f"run{1 + i % 2}" for i in range(len(values))],
            }
        )

    def commits(self, setup) -> list:
        tmp_path, _, _, cli_config = setup
        options = turn_S3_config_into_polars_storage_options(cli_config.s3_storage)
        return list_delta_versions(str(tmp_path / self.JOIN_ID), options)

    def history(self, setup) -> list[int]:
        return sorted(commit.version for commit in self.commits(setup))

    def test_registers_the_version_it_wrote(self, setup):
        server = _FakeServer()
        result = self.persist(setup, self.joined([10, 20, 30]), server)

        assert result["result"] == "success"
        (upsert,) = server.upserts
        provenance = upsert["delta_provenance"]
        assert provenance["delta_version"] == 0
        assert provenance["rows_total"] == 3
        assert provenance["write_mode"] == "overwrite"
        assert provenance["run_tags"] == ["run1", "run2"]
        # Sent as ISO text, which the upsert payload parses back into a datetime.
        assert datetime.fromisoformat(provenance["delta_commit_timestamp"])

    def test_a_table_the_server_did_not_register_is_a_failed_join(self, setup):
        # Written, but the server still serves the version before it: the join
        # is not done, and saying "success" would hide that.
        result = self.persist(setup, self.joined([10, 20, 30]), _FakeServer(upsert_status=500))

        assert result["result"] == "error"
        assert "registering it failed: HTTP 500" in result["message"]
        assert "Delta version 0" in result["message"]

    def test_each_change_is_a_new_registered_version(self, setup):
        server = _FakeServer()
        self.persist(setup, self.joined([10, 20, 30]), server)
        # Same row count, one value moved: the case a row count cannot tell apart.
        result = self.persist(setup, self.joined([10, 20, 31]), server)

        assert result["unchanged"] is False
        assert [u["delta_provenance"]["delta_version"] for u in server.upserts] == [0, 1]
        assert [u["delta_provenance"]["rows_total"] for u in server.upserts] == [3, 3]
        assert self.history(setup) == [0, 1]

    def test_the_commit_carries_depictio_metadata(self, setup):
        self.persist(setup, self.joined([10, 20]), _FakeServer())
        (commit,) = self.commits(setup)
        assert commit.custom_metadata["depictio.data_collection_tag"] == "joined_complete"
        assert commit.custom_metadata["depictio.row_count"] == "2"

    def test_an_emptied_join_is_a_new_version_of_no_rows(self, setup):
        server = _FakeServer()
        self.persist(setup, self.joined([10, 20]), server)
        result = self.persist(setup, self.joined([10]).clear(), server)

        assert result["result"] == "success"
        assert result["rows"] == 0
        assert self.history(setup) == [0, 1]
        assert server.upserts[-1]["delta_provenance"]["rows_total"] == 0

    def test_unchanged_rows_write_nothing(self, setup):
        server = _FakeServer()
        first = self.joined([10, 20, 30])
        self.persist(setup, first, server)
        # Same rows in another order: a join keeps no order, so this is no change.
        result = self.persist(setup, first.reverse(), server)

        assert result["result"] == "success"
        assert result["unchanged"] is True
        assert result["delta_version"] == 0
        assert self.history(setup) == [0]
        assert len(server.upserts) == 1

    def test_unchanged_rows_are_registered_again_when_the_server_lost_them(self, setup):
        server = _FakeServer()
        rows = self.joined([10, 20, 30])
        self.persist(setup, rows, server)
        server.knows_the_table = False  # a fresh database over the same object store
        result = self.persist(setup, rows, server)

        assert result["unchanged"] is False
        assert [u["delta_provenance"]["delta_version"] for u in server.upserts] == [0, 1]


class TestPersistJoinedTableWithHooks:
    """The API runs the persist in-process with its own hooks: no HTTP call is made."""

    JOIN_ID = TestPersistJoinedTable.JOIN_ID
    setup = TestPersistJoinedTable.setup
    joined = staticmethod(TestPersistJoinedTable.joined)
    commits = TestPersistJoinedTable.commits
    history = TestPersistJoinedTable.history

    @staticmethod
    def hooks(records_version: bool = False) -> JoinPersistHooks:
        return JoinPersistHooks(
            records_version=MagicMock(return_value=records_version),
            sync_project=MagicMock(),
            register=MagicMock(),
        )

    def persist_with(self, setup, joined_df: pl.DataFrame, hooks: JoinPersistHooks, **kwargs):
        tmp_path, project, join_def, cli_config = setup

        def local(path: str) -> str:
            return str(tmp_path / path.rsplit("/", 1)[-1])

        with (
            patch(
                "depictio.cli.cli.utils.joins.read_delta_table",
                side_effect=lambda path, opts: read_delta_table(local(path), opts),
            ),
            patch(
                "depictio.cli.cli.utils.joins.write_delta_table",
                side_effect=lambda destination_file, **kw: write_delta_table(
                    destination_file=local(destination_file), **kw
                ),
            ),
            patch(
                "depictio.cli.cli.utils.joins.read_delta_commit_info",
                side_effect=lambda path, opts: read_delta_commit_info(local(path), opts),
            ),
            patch("depictio.cli.cli.utils.api_calls.api_sync_project_config_to_server") as sync,
            patch("depictio.cli.cli.utils.api_calls.api_upsert_deltatable") as upsert,
            patch("depictio.cli.cli.utils.api_calls.api_get_deltatable_by_dc_id") as get,
        ):
            result = persist_joined_table(
                join_def,
                joined_df,
                project,
                cli_config,
                metadata={},
                overwrite=True,
                hooks=hooks,
                **kwargs,
            )
        # Never the HTTP API when hooks are given.
        sync.assert_not_called()
        upsert.assert_not_called()
        get.assert_not_called()
        return result

    def test_the_hooks_register_sync_and_are_asked_for_the_version(self, setup):
        _, project, join_def, _ = setup
        hooks = self.hooks()

        # Persisting twice: the second finds the rows it wrote and asks the server about them.
        first = self.persist_with(setup, self.joined([10, 20, 30]), hooks, trigger="ui")
        assert first["result"] == "success"
        assert first["unchanged"] is False
        hooks.sync_project.assert_called_once_with(project, join_def)
        hooks.register.assert_called_once()
        dc_id, location, size_bytes, provenance, frame = hooks.register.call_args.args
        assert dc_id == self.JOIN_ID == first["dc_id"]
        assert location.endswith(f"/{self.JOIN_ID}")
        assert size_bytes > 0
        assert provenance["delta_version"] == 0
        assert provenance["rows_total"] == 3
        assert provenance["write_mode"] == "overwrite"
        assert provenance["trigger"] == "ui"
        assert frame.height == 3 and "join_timestamp" in frame.columns
        # The first write had nothing stored yet: the server is not asked about a version.
        hooks.records_version.assert_not_called()

        hooks.records_version.return_value = True
        second = self.persist_with(setup, self.joined([10, 20, 30]).reverse(), hooks, trigger="ui")

        hooks.records_version.assert_called_once_with(self.JOIN_ID, 0)
        assert second["unchanged"] is True and second["delta_version"] == 0
        assert hooks.register.call_count == 1  # nothing new to register
        assert self.history(setup) == [0]

    def test_a_version_the_hooks_do_not_know_is_written_and_registered_again(self, setup):
        hooks = self.hooks(records_version=False)
        rows = self.joined([10, 20, 30])
        self.persist_with(setup, rows, hooks)
        result = self.persist_with(setup, rows, hooks)

        assert result["unchanged"] is False
        assert hooks.register.call_count == 2
        assert [c.args[3]["delta_version"] for c in hooks.register.call_args_list] == [0, 1]

    def test_the_trigger_is_stamped_on_the_commit(self, setup):
        self.persist_with(setup, self.joined([10, 20]), self.hooks(), trigger="ui")
        (commit,) = self.commits(setup)
        assert commit.custom_metadata["depictio.trigger"] == "ui"

    def test_without_a_trigger_none_is_stamped(self, setup):
        hooks = self.hooks()
        self.persist_with(setup, self.joined([10, 20]), hooks)
        (commit,) = self.commits(setup)
        assert "depictio.trigger" not in commit.custom_metadata
        assert "trigger" not in hooks.register.call_args.args[3]

    def test_a_register_that_raises_is_a_failed_join(self, setup):
        hooks = self.hooks()
        hooks.register.side_effect = RuntimeError("mongo is down")

        result = self.persist_with(setup, self.joined([10, 20, 30]), hooks)

        assert result["result"] == "error"
        assert "registering it failed: mongo is down" in result["message"]

    def test_a_sync_that_raises_is_reported_not_raised(self, setup):
        hooks = self.hooks()
        hooks.sync_project.side_effect = RuntimeError("project not saved")

        result = self.persist_with(setup, self.joined([10, 20, 30]), hooks)

        assert result["result"] == "success"
        hooks.register.assert_called_once()

    def test_the_joined_collection_is_added_to_the_projects_workflow_before_the_sync(self, setup):
        _, project, join_def, _ = setup
        seen = {}

        def sync(project_, join_def_):
            seen["dcs"] = [dc.data_collection_tag for dc in project_.workflows[0].data_collections]
            seen["result"] = (join_def_.result_dc_id, join_def_.row_count)

        hooks = self.hooks()
        hooks.sync_project.side_effect = sync
        self.persist_with(setup, self.joined([10, 20, 30]), hooks)

        assert "joined_complete" in seen["dcs"]
        assert seen["result"] == (ObjectId(self.JOIN_ID), 3)


class TestMatchRunIds:
    """``match_run_ids=False`` keeps ``depictio_run_id`` out of the join keys."""

    @pytest.fixture
    def frames(self):
        left = pl.DataFrame(
            {"id": [1, 2, 3], "name": ["A", "B", "C"], "depictio_run_id": ["left-scan"] * 3}
        )
        right = pl.DataFrame(
            {"id": [1, 2, 4], "score": [10, 20, 40], "depictio_run_id": ["right-scan"] * 3}
        )
        return left, right

    def run(self, frames, mock_project, mock_cli_config, **fields):
        join_def = JoinDefinition(
            name="j", left_dc="left_table", right_dc="right_table", on_columns=["id"], **fields
        )
        with patch("depictio.cli.cli.utils.joins.read_delta_table") as read:
            read.side_effect = [delta_success(frames[0]), delta_success(frames[1])]
            return execute_join(join_def, mock_project, mock_cli_config, apply_granularity=False)

    def test_the_default_matches_run_ids_as_before(self):
        assert (
            JoinDefinition(name="j", left_dc="a", right_dc="b", on_columns=["id"]).match_run_ids
            is True
        )

    def test_run_ids_are_added_to_the_keys_by_default(self, frames, mock_project, mock_cli_config):
        result, metadata = self.run(frames, mock_project, mock_cli_config, how="inner")
        assert metadata["join_columns"] == ["id", "depictio_run_id"]
        assert result.height == 0  # the two tables' run ids never agree

    def test_off_they_are_not(self, frames, mock_project, mock_cli_config):
        result, metadata = self.run(
            frames, mock_project, mock_cli_config, how="inner", match_run_ids=False
        )
        assert metadata["join_columns"] == ["id"]
        assert result.sort("id")["id"].to_list() == [1, 2]
        assert result.sort("id")["score"].to_list() == [10, 20]
        # The left run id stays; the right one is a duplicate column and is dropped.
        assert result["depictio_run_id"].unique().to_list() == ["left-scan"]

    def test_off_a_left_join_keeps_every_left_row_with_its_partner(
        self, frames, mock_project, mock_cli_config
    ):
        result, _ = self.run(frames, mock_project, mock_cli_config, how="left", match_run_ids=False)
        assert result.sort("id")["score"].to_list() == [10, 20, None]

    def test_off_a_key_already_naming_run_ids_is_left_as_given(
        self, frames, mock_project, mock_cli_config
    ):
        join_def = JoinDefinition(
            name="j",
            left_dc="left_table",
            right_dc="right_table",
            on_columns=["id", "depictio_run_id"],
            how="left",
            match_run_ids=False,
        )
        with patch("depictio.cli.cli.utils.joins.read_delta_table") as read:
            read.side_effect = [delta_success(frames[0]), delta_success(frames[1])]
            _, metadata = execute_join(
                join_def, mock_project, mock_cli_config, apply_granularity=False
            )
        assert metadata["join_columns"] == ["id", "depictio_run_id"]


class TestJoinFrames:
    """The joined columns, whatever the join type: one per key, nothing lost."""

    LEFT = pl.DataFrame({"id": [1, 2], "note": ["L1", "L2"], "depictio_run_id": ["run_l", "run_l"]})
    RIGHT = pl.DataFrame(
        {"id": [2, 3], "note": ["R2", "R3"], "depictio_run_id": ["run_r", "run_r"]}
    )

    @staticmethod
    def join(how: str, left: pl.DataFrame, right: pl.DataFrame, match_run_ids: bool = False):
        from depictio.cli.cli.utils.joins import join_frames

        join_def = JoinDefinition(
            name="j",
            left_dc="left_table",
            right_dc="right_table",
            on_columns=["id"],
            how=how,
            match_run_ids=match_run_ids,
        )
        return join_frames(join_def, left, right, make_dc("left_table"), make_dc("right_table"))

    @pytest.mark.parametrize("how", ["left", "inner", "outer", "right"])
    def test_one_key_column_first_and_the_right_copy_renamed(self, how):
        joined, metadata = self.join(how, self.LEFT, self.RIGHT)
        assert joined.columns == ["id", "note", "depictio_run_id", "note_right"]
        assert joined["id"].null_count() == 0
        assert metadata["renamed_right_columns"] == {"note": "note_right"}

    def test_an_outer_join_keeps_every_key_once(self):
        joined, _ = self.join("outer", self.LEFT, self.RIGHT)
        assert sorted(joined["id"].to_list()) == [1, 2, 3]

    def test_a_joined_row_carries_the_left_rows_run_only(self):
        joined, _ = self.join("outer", self.LEFT, self.RIGHT)
        assert set(joined["depictio_run_id"].to_list()) == {"run_l", None}
        # Even when the left table has no run at all.
        joined, _ = self.join("left", self.LEFT.drop("depictio_run_id"), self.RIGHT)
        assert "depictio_run_id" not in joined.columns

    def test_a_cli_join_still_takes_the_right_run_when_the_left_has_none(self):
        joined, _ = self.join(
            "left", self.LEFT.drop("depictio_run_id"), self.RIGHT, match_run_ids=True
        )
        assert joined["depictio_run_id"].to_list() == [None, "run_r"]

    def test_a_taken_suffix_is_not_overwritten(self):
        left = self.LEFT.with_columns(pl.lit("x").alias("note_right"))
        joined, metadata = self.join("left", left, self.RIGHT)
        assert metadata["renamed_right_columns"] == {"note": "note_right_right"}
        assert joined["note_right"].to_list() == ["x", "x"]


class TestJoinWithoutYamlId:
    """``depictio ingest --attach-run`` re-reads a YAML join with no ``id`` each time:
    every run must write the same joined collection, not add another."""

    @staticmethod
    def fresh_join() -> JoinDefinition:
        return JoinDefinition(
            name="complete",
            left_dc="left_table",
            right_dc="right_table",
            on_columns=["id"],
            how="inner",
            persist=True,
            workflow_name="wf",
        )

    @staticmethod
    def yaml_project() -> Project:
        workflow = make_workflow("wf", [make_dc("left_table"), make_dc("right_table")])
        project = make_project(workflows=[workflow])
        project.id = ObjectId("6a0000000000000000000001")
        return project

    def run(self, tmp_path, cli_config, project, server) -> tuple[dict, Project]:
        join_def = self.fresh_join()
        result = TestPersistJoinedTable.persist(
            None,  # type: ignore[arg-type]
            (tmp_path, project, join_def, cli_config),
            TestPersistJoinedTable.joined([1, 2]),
            server,
        )
        return result, project

    @staticmethod
    def joined_dcs(project: Project) -> list[str]:
        return [
            str(dc.id)
            for wf in project.workflows
            for dc in wf.data_collections
            if dc.data_collection_tag == "joined_complete"
        ]

    def test_each_attach_writes_the_same_collection(self, tmp_path, mock_cli_config):
        from depictio.models.models.joins import stable_join_result_id

        server = _FakeServer()
        first, p1 = self.run(tmp_path, mock_cli_config, self.yaml_project(), server)
        second, p2 = self.run(tmp_path, mock_cli_config, self.yaml_project(), server)

        expected = str(stable_join_result_id(ObjectId("6a0000000000000000000001"), "complete"))
        assert first["dc_id"] == second["dc_id"] == expected
        assert self.joined_dcs(p1) == self.joined_dcs(p2) == [expected]
        assert second["unchanged"] is True  # same rows: no second version

    def test_the_joined_collection_already_in_the_project_is_reused(
        self, tmp_path, mock_cli_config
    ):
        project = self.yaml_project()
        earlier = ObjectId()
        project.workflows[0].data_collections.append(make_dc("joined_complete", earlier))

        result, project = self.run(tmp_path, mock_cli_config, project, _FakeServer())

        assert result["dc_id"] == str(earlier)
        assert self.joined_dcs(project) == [str(earlier)]
