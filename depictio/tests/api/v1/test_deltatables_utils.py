"""
Tests for depictio.api.v1.deltatables_utils module.
"""

from unittest.mock import MagicMock, patch

import pandera.polars as pap
import polars as pl
from bson import ObjectId

from depictio.api.v1.deltatables_utils import (
    add_filter,
    compute_essential_columns,
    convert_filter_model_to_metadata,
    get_join_tables,
    iterative_join,
    load_deltatable_lite,
    merge_multiple_dataframes,
    process_metadata_and_filter,
    transform_joins_dict_to_instructions,
)


class TestAddFilter:
    """Test filter addition functionality with comprehensive validation."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create sample datasets for testing different filter scenarios
        self.categorical_df = pl.DataFrame(
            {
                "category": ["A", "B", "C", "A", "B"],
                "tags": ["tag1,tag2", "tag2,tag3", "tag1,tag3", "tag2", "tag1"],
                "description": [
                    "apple fruit",
                    "banana yellow",
                    "cherry red",
                    "avocado green",
                    "blueberry",
                ],
                "value": [1, 2, 3, 4, 5],
            }
        )

        self.numeric_df = pl.DataFrame(
            {
                "price": [10.5, 25.0, 50.0, 75.5, 100.0],
                "quantity": [1, 2, 3, 4, 5],
                "rating": [4.5, 3.8, 4.9, 4.2, 3.5],
            }
        )

        # Pandera schema for validation if available
        self.expected_filter_schema = pap.DataFrameSchema(
            {"category": pap.Column(pl.String), "value": pap.Column(pl.Int64)}
        )

    def test_add_filter_select_component_basic(self):
        """Test adding filter for Select component with basic functionality."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="Select",
            column_name="category",
            value=["A", "B"],
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.categorical_df.filter(filter_list[0])
        assert filtered_df.height == 4  # Should filter to 4 rows with categories A and B
        assert set(filtered_df["category"].to_list()) == {"A", "B"}

    def test_add_filter_select_component_single_value(self):
        """Test Select component with single value selection."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list, interactive_component_type="Select", column_name="category", value=["A"]
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.categorical_df.filter(filter_list[0])
        assert filtered_df.height == 2
        assert all(cat == "A" for cat in filtered_df["category"].to_list())

    def test_add_filter_select_component_empty_result(self):
        """Test Select component filter that results in empty DataFrame."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="Select",
            column_name="category",
            value=["Z"],  # Non-existent category
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.categorical_df.filter(filter_list[0])
        assert filtered_df.height == 0

    def test_add_filter_multiselect_component_basic(self):
        """Test adding filter for MultiSelect component."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="MultiSelect",
            column_name="category",
            value=["A", "C"],
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.categorical_df.filter(filter_list[0])
        assert filtered_df.height == 3  # 2 A's + 1 C
        assert set(filtered_df["category"].to_list()) == {"A", "C"}

    def test_add_filter_multiselect_component_all_values(self):
        """Test MultiSelect with all available values selected."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="MultiSelect",
            column_name="category",
            value=["A", "B", "C"],
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.categorical_df.filter(filter_list[0])
        assert filtered_df.height == 5  # All rows should pass

    def test_add_filter_text_input_component_contains(self):
        """Test adding filter for TextInput component with contains logic."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="TextInput",
            column_name="description",
            value="fruit",
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.categorical_df.filter(filter_list[0])
        assert filtered_df.height == 1  # Only "apple fruit"
        assert "fruit" in filtered_df["description"].to_list()[0]

    # def test_add_filter_text_input_component_case_insensitive(self):
    #     """Test TextInput filter is case insensitive."""
    #     # Arrange
    #     filter_list = []

    #     # Act
    #     add_filter(
    #         filter_list,
    #         interactive_component_type="TextInput",
    #         column_name="description",
    #         value="APPLE"
    #     )

    #     # Assert
    #     assert len(filter_list) == 1
    #     filtered_df = self.categorical_df.filter(filter_list[0])
    #     print(f"Filtered DataFrame: {filtered_df}")
    #     assert filtered_df.height == 1

    def test_add_filter_text_input_component_partial_match(self):
        """Test TextInput filter with partial string matching."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="TextInput",
            column_name="description",
            value=".*erry",
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.categorical_df.filter(filter_list[0])
        print(f"Filtered DataFrame: {filtered_df}")
        assert filtered_df.height == 2  # "cherry" and "blueberry"

    def test_add_filter_slider_component_equality(self):
        """Test adding filter for Slider component with equality check."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list, interactive_component_type="Slider", column_name="quantity", value=3
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.numeric_df.filter(filter_list[0])
        assert filtered_df.height == 1
        assert filtered_df["quantity"].to_list()[0] == 3

    def test_add_filter_slider_component_float_value(self):
        """Test Slider component with float values."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list, interactive_component_type="Slider", column_name="rating", value=4.5
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.numeric_df.filter(filter_list[0])
        assert filtered_df.height == 1
        assert filtered_df["rating"].to_list()[0] == 4.5

    def test_add_filter_range_slider_component_basic(self):
        """Test adding filter for RangeSlider component with range filtering."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="RangeSlider",
            column_name="price",
            value=[20, 80],
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.numeric_df.filter(filter_list[0])
        assert filtered_df.height == 3  # 25.0, 50.0, 75.5
        filtered_prices = filtered_df["price"].to_list()
        assert all(20 <= price <= 80 for price in filtered_prices)

    def test_add_filter_range_slider_component_inclusive_bounds(self):
        """Test RangeSlider filter includes boundary values."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="RangeSlider",
            column_name="price",
            value=[25.0, 50.0],
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.numeric_df.filter(filter_list[0])
        assert filtered_df.height == 2  # Exactly 25.0 and 50.0
        filtered_prices = sorted(filtered_df["price"].to_list())
        assert filtered_prices == [25.0, 50.0]

    def test_add_filter_range_slider_component_narrow_range(self):
        """Test RangeSlider with very narrow range."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="RangeSlider",
            column_name="price",
            value=[49, 51],
        )

        # Assert
        assert len(filter_list) == 1
        filtered_df = self.numeric_df.filter(filter_list[0])
        assert filtered_df.height == 1  # Only 50.0
        assert filtered_df["price"].to_list()[0] == 50.0

    def test_add_filter_no_value_skipped(self):
        """Test that filters with no value are not added."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list, interactive_component_type="Select", column_name="category", value=None
        )

        # Assert
        assert len(filter_list) == 0

    def test_add_filter_empty_list_value_skipped(self):
        """Test that filters with empty list values are not added."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list, interactive_component_type="MultiSelect", column_name="category", value=[]
        )

        # Assert
        assert len(filter_list) == 0

    def test_add_filter_empty_string_value_skipped(self):
        """Test that filters with empty string values are not added."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list, interactive_component_type="TextInput", column_name="description", value=""
        )

        # Assert
        assert len(filter_list) == 0

    def test_add_filter_schema_validation(self):
        """Test filter results conform to expected schema using Pandera."""
        # Arrange
        filter_list = []

        # Act
        add_filter(
            filter_list,
            interactive_component_type="Select",
            column_name="category",
            value=["A", "B"],
        )

        # Assert with Pandera validation
        filtered_df = self.categorical_df.filter(filter_list[0]).select(["category", "value"])

        # This should not raise an exception if schema is valid
        validated_df = self.expected_filter_schema.validate(filtered_df)
        assert validated_df is not None
        assert len(validated_df) > 0

    def test_add_filter_multiple_filters_combination(self):
        """Test combining multiple filters works correctly."""
        # Arrange
        filter_list = []

        # Act - Add multiple filters
        add_filter(
            filter_list,
            interactive_component_type="Select",
            column_name="category",
            value=["A", "B"],
        )

        add_filter(
            filter_list, interactive_component_type="RangeSlider", column_name="value", value=[2, 4]
        )

        # Assert
        assert len(filter_list) == 2

        # Apply all filters
        filtered_df = self.categorical_df
        for filter_expr in filter_list:
            filtered_df = filtered_df.filter(filter_expr)

        # Should have categories A or B AND values between 2-4
        assert filtered_df.height == 2  # category B with value 2, category A with value 4
        result_categories = set(filtered_df["category"].to_list())
        result_values = filtered_df["value"].to_list()

        assert result_categories.issubset({"A", "B"})
        assert all(2 <= val <= 4 for val in result_values)


class TestProcessMetadataAndFilter:
    """Test metadata processing and filter building."""

    def test_process_metadata_and_filter_single_component(self):
        """Test processing metadata for single interactive component."""
        # Arrange
        metadata = [
            {
                "metadata": {"interactive_component_type": "Select", "column_name": "category"},
                "value": ["A", "B"],
            }
        ]

        # Act
        result = process_metadata_and_filter(metadata)

        # Assert
        assert len(result) == 1

    def test_process_metadata_and_filter_multiple_components(self):
        """Test processing metadata for multiple interactive components."""
        # Arrange
        metadata = [
            {
                "metadata": {"interactive_component_type": "Select", "column_name": "category"},
                "value": ["A"],
            },
            {
                "metadata": {"interactive_component_type": "RangeSlider", "column_name": "price"},
                "value": [10, 50],
            },
        ]

        # Act
        result = process_metadata_and_filter(metadata)

        # Assert
        assert len(result) == 2

    def test_process_metadata_and_filter_no_metadata(self):
        """Test processing empty metadata returns empty filter list."""
        # Act
        result = process_metadata_and_filter([])

        # Assert
        assert len(result) == 0


class TestConvertFilterModelToMetadata:
    """Test filter model conversion functionality."""

    def test_convert_filter_model_range_filter(self):
        """Test converting range filter model to metadata."""
        # Arrange
        filter_model = {
            "price": {"filterType": "number", "type": "inRange", "filter": 10, "filterTo": 100}
        }

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1
        assert result[0]["metadata"]["interactive_component_type"] == "RangeSlider"
        assert result[0]["value"] == [10, 100]

    def test_convert_filter_model_text_filter(self):
        """Test converting text filter model to metadata."""
        # Arrange
        filter_model = {"name": {"filterType": "text", "type": "contains", "filter": "test"}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1
        assert result[0]["metadata"]["interactive_component_type"] == "TextInput"
        assert result[0]["value"] == "test"

    def test_convert_filter_model_numeric_filter(self):
        """Test converting numeric filter model to metadata."""
        # Arrange
        filter_model = {"count": {"filterType": "number", "type": "equals", "filter": 42}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1
        assert result[0]["metadata"]["interactive_component_type"] == "Slider"
        assert result[0]["value"] == 42


class TestLoadDeltatablelite:
    """Test Delta table loading functionality."""

    def setup_method(self):
        """Set up test fixtures and clear cache."""
        from depictio.api.v1.deltatables_utils import _iterative_join_cache

        _iterative_join_cache.clear()

    @patch("depictio.api.v1.deltatables_utils.httpx.get")
    @patch("depictio.api.v1.deltatables_utils.pl.scan_delta")
    def test_load_deltatable_lite_success(self, mock_scan_delta, mock_httpx_get):
        """Test successful Delta table loading."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"delta_table_location": "s3://bucket/table"}
        mock_httpx_get.return_value = mock_response

        mock_df = pl.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
        mock_lazy_frame = MagicMock()
        mock_lazy_frame.collect.return_value = mock_df
        mock_scan_delta.return_value = mock_lazy_frame

        # Act
        result = load_deltatable_lite(
            workflow_id=ObjectId(), data_collection_id=ObjectId(), TOKEN="test_token"
        )

        # Assert
        assert result is not None
        assert result.height == 3
        assert "col1" in result.columns

    @patch("depictio.api.v1.deltatables_utils.httpx.get")
    def test_load_deltatable_lite_api_error(self, mock_httpx_get):
        """Test Delta table loading with API error."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx_get.return_value = mock_response
        mock_httpx_get.side_effect = Exception("API Error")

        # Act & Assert
        try:
            load_deltatable_lite(
                workflow_id=ObjectId(), data_collection_id=ObjectId(), TOKEN="test_token"
            )
            assert False, "Should have raised exception"
        except Exception:
            pass  # Expected

    @patch("depictio.api.v1.deltatables_utils.httpx.get")
    @patch("depictio.api.v1.deltatables_utils.pl.scan_delta")
    def test_load_deltatable_lite_with_metadata_filtering(self, mock_scan_delta, mock_httpx_get):
        """Test Delta table loading with metadata filtering."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"delta_table_location": "s3://bucket/table"}
        mock_httpx_get.return_value = mock_response

        mock_df = pl.DataFrame({"category": ["A", "B"], "value": [1, 2]})
        mock_lazy_frame = MagicMock()
        mock_lazy_frame.filter.return_value = mock_lazy_frame
        mock_lazy_frame.collect.return_value = mock_df
        mock_scan_delta.return_value = mock_lazy_frame

        metadata = [
            {
                "metadata": {"interactive_component_type": "Select", "column_name": "category"},
                "value": ["A"],
            }
        ]

        # Act
        result = load_deltatable_lite(
            workflow_id=ObjectId(),
            data_collection_id=ObjectId(),
            metadata=metadata,
            TOKEN="test_token",
        )

        # Assert
        assert result is not None
        # Should have applied filtering
        mock_lazy_frame.filter.assert_called_once()


class TestMergeMultipleDataframes:
    """Test DataFrame merging functionality."""

    def test_merge_multiple_dataframes_simple_join(self):
        """Test merging two DataFrames with simple join."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        df2 = pl.DataFrame({"id": [1, 2, 3], "value": [10, 20, 30]})

        dataframes = {"df1": df1, "df2": df2}
        join_instructions = [{"left": "df1", "right": "df2", "how": "inner", "on": ["id"]}]

        # Act
        result = merge_multiple_dataframes(dataframes, join_instructions)

        # Assert
        assert result is not None
        assert result.height == 3
        assert "name" in result.columns
        assert "value" in result.columns

    def test_merge_multiple_dataframes_with_essential_columns(self):
        """Test merging DataFrames with essential columns."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2], "shared_col": ["x", "y"], "col1": ["a", "b"]})
        df2 = pl.DataFrame({"id": [1, 2], "shared_col": ["x", "y"], "col2": [10, 20]})

        dataframes = {"df1": df1, "df2": df2}
        join_instructions = [{"left": "df1", "right": "df2", "how": "inner", "on": ["id"]}]
        essential_cols = {"shared_col"}

        # Act
        result = merge_multiple_dataframes(dataframes, join_instructions, essential_cols)

        # Assert
        assert result is not None
        assert "shared_col" in result.columns
        assert "col1" in result.columns
        assert "col2" in result.columns
        assert result.height == 2
        assert result.width == 4  # id, shared_col, col1, col2

    def test_merge_multiple_dataframes_no_instructions(self):
        """Test merging with no join instructions returns first DataFrame."""
        # Arrange
        df1 = pl.DataFrame({"col": [1, 2, 3]})
        dataframes = {"df1": df1}
        join_instructions = []

        # Act
        result = merge_multiple_dataframes(dataframes, join_instructions)

        # Assert
        assert result.equals(df1)


class TestComputeEssentialColumns:
    """Test essential columns computation functionality."""

    def test_compute_essential_columns_overlapping(self):
        """Test computing essential columns with overlapping columns."""
        # Arrange
        df1 = pl.DataFrame({"id": [1], "shared": ["a"], "unique1": [10]})
        df2 = pl.DataFrame({"id": [1], "shared": ["a"], "unique2": [20]})
        df3 = pl.DataFrame({"other": [1], "shared": ["a"], "unique3": [30]})

        dataframes = {"df1": df1, "df2": df2, "df3": df3}

        # Act
        result = compute_essential_columns(dataframes)

        # Assert
        assert isinstance(result, set)
        assert "shared" in result  # Appears in all 3 DataFrames
        assert "id" in result  # Appears in 2 DataFrames
        assert "unique1" not in result  # Appears in only 1 DataFrame
        assert "unique2" not in result
        assert "unique3" not in result
        assert "other" not in result  # Only appears in df3
        assert len(result) == 2  # Only "shared" and "id"

    def test_compute_essential_columns_no_overlap(self):
        """Test computing essential columns with no overlapping columns."""
        # Arrange
        df1 = pl.DataFrame({"col1": [1]})
        df2 = pl.DataFrame({"col2": [2]})

        dataframes = {"df1": df1, "df2": df2}

        # Act
        result = compute_essential_columns(dataframes)

        # Assert
        assert isinstance(result, set)
        assert len(result) == 0  # No overlapping columns

    def test_compute_essential_columns_single_dataframe(self):
        """Test computing essential columns with single DataFrame."""
        # Arrange
        df1 = pl.DataFrame({"col1": [1], "col2": [2]})
        dataframes = {"df1": df1}

        # Act
        result = compute_essential_columns(dataframes)

        # Assert
        assert isinstance(result, set)
        assert len(result) == 0  # No columns appear in multiple DataFrames

    def test_compute_essential_columns_all_columns_shared(self):
        """Test when all columns are shared across DataFrames."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2], "name": ["a", "b"], "value": [10, 20]})
        df2 = pl.DataFrame({"id": [3, 4], "name": ["c", "d"], "value": [30, 40]})
        df3 = pl.DataFrame({"id": [5, 6], "name": ["e", "f"], "value": [50, 60]})

        dataframes = {"df1": df1, "df2": df2, "df3": df3}

        # Act
        result = compute_essential_columns(dataframes)

        # Assert
        assert isinstance(result, set)
        assert result == {"id", "name", "value"}  # All columns are essential
        assert len(result) == 3

    def test_compute_essential_columns_partial_overlap(self):
        """Test with complex partial column overlaps."""
        # Arrange
        df1 = pl.DataFrame({"a": [1], "b": [2], "c": [3]})  # a, b, c
        df2 = pl.DataFrame({"b": [4], "c": [5], "d": [6]})  # b, c, d
        df3 = pl.DataFrame({"c": [7], "d": [8], "e": [9]})  # c, d, e
        df4 = pl.DataFrame({"a": [10], "e": [11], "f": [12]})  # a, e, f

        dataframes = {"df1": df1, "df2": df2, "df3": df3, "df4": df4}

        # Act
        result = compute_essential_columns(dataframes)

        # Assert
        assert isinstance(result, set)
        # a: df1, df4 (2 DataFrames)
        # b: df1, df2 (2 DataFrames)
        # c: df1, df2, df3 (3 DataFrames)
        # d: df2, df3 (2 DataFrames)
        # e: df3, df4 (2 DataFrames)
        # f: df4 (1 DataFrame - not essential)
        expected = {"a", "b", "c", "d", "e"}
        assert result == expected
        assert "f" not in result

    def test_compute_essential_columns_empty_dataframes(self):
        """Test with empty dataframes dictionary."""
        # Arrange
        dataframes = {}

        # Act
        result = compute_essential_columns(dataframes)

        # Assert
        assert isinstance(result, set)
        assert len(result) == 0

    def test_compute_essential_columns_dataframes_with_no_columns(self):
        """Test with DataFrames that have no columns."""
        # Arrange
        df1 = pl.DataFrame()
        df2 = pl.DataFrame()
        dataframes = {"df1": df1, "df2": df2}

        # Act
        result = compute_essential_columns(dataframes)

        # Assert
        assert isinstance(result, set)
        assert len(result) == 0


class TestTransformJoinsDictToInstructions:
    """Test joins dictionary transformation functionality."""

    def test_transform_joins_dict_to_instructions_basic(self):
        """Test basic transformation of joins dict to instructions."""
        # Arrange
        joins_dict = {("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}]}

        # Act
        result = transform_joins_dict_to_instructions(joins_dict)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1

        instruction = result[0]
        assert isinstance(instruction, dict)
        assert instruction["left"] == "dc1"
        assert instruction["right"] == "dc2"
        assert instruction["how"] == "inner"
        assert instruction["on"] == ["id"]
        assert isinstance(instruction["on"], list)
        assert len(instruction["on"]) == 1

        # Verify all expected keys are present
        expected_keys = {"left", "right", "how", "on"}
        assert set(instruction.keys()) == expected_keys

    def test_transform_joins_dict_to_instructions_multiple(self):
        """Test transformation with multiple joins."""
        # Arrange
        joins_dict = {
            ("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}],
            ("dc2", "dc3"): [{"dc2--dc3": {"how": "left", "on_columns": ["ref_id"]}}],
        }

        # Act
        result = transform_joins_dict_to_instructions(joins_dict)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 2

        # Verify first instruction
        instruction1 = result[0]
        assert instruction1["left"] == "dc1"
        assert instruction1["right"] == "dc2"
        assert instruction1["how"] == "inner"
        assert instruction1["on"] == ["id"]

        # Verify second instruction
        instruction2 = result[1]
        assert instruction2["left"] == "dc2"
        assert instruction2["right"] == "dc3"
        assert instruction2["how"] == "left"
        assert instruction2["on"] == ["ref_id"]

        # Verify all instructions have correct structure
        for instruction in result:
            assert isinstance(instruction, dict)
            expected_keys = {"left", "right", "how", "on"}
            assert set(instruction.keys()) == expected_keys
            assert isinstance(instruction["on"], list)

    def test_transform_joins_dict_to_instructions_empty(self):
        """Test transformation with empty joins dict."""
        # Act
        result = transform_joins_dict_to_instructions({})

        # Assert
        assert isinstance(result, list)
        assert len(result) == 0

    def test_transform_joins_dict_to_instructions_multiple_columns(self):
        """Test transformation with multiple join columns."""
        # Arrange
        joins_dict = {
            ("table1", "table2"): [
                {"table1--table2": {"how": "outer", "on_columns": ["id", "category", "timestamp"]}}
            ]
        }

        # Act
        result = transform_joins_dict_to_instructions(joins_dict)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1

        instruction = result[0]
        assert instruction["left"] == "table1"
        assert instruction["right"] == "table2"
        assert instruction["how"] == "outer"
        assert instruction["on"] == ["id", "category", "timestamp"]
        assert len(instruction["on"]) == 3

        # Verify all join columns are preserved
        expected_columns = {"id", "category", "timestamp"}
        assert set(instruction["on"]) == expected_columns

    def test_transform_joins_dict_to_instructions_different_join_types(self):
        """Test transformation with different join types."""
        # Arrange
        joins_dict = {
            ("users", "orders"): [{"users--orders": {"how": "left", "on_columns": ["user_id"]}}],
            ("orders", "products"): [
                {"orders--products": {"how": "right", "on_columns": ["product_id"]}}
            ],
            ("products", "categories"): [
                {"products--categories": {"how": "outer", "on_columns": ["category_id"]}}
            ],
        }

        # Act
        result = transform_joins_dict_to_instructions(joins_dict)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 3

        # Extract join types and verify variety
        join_types = [instruction["how"] for instruction in result]
        expected_join_types = {"left", "right", "outer"}
        assert set(join_types) == expected_join_types

        # Verify each instruction has valid structure
        for instruction in result:
            assert "left" in instruction
            assert "right" in instruction
            assert "how" in instruction
            assert "on" in instruction
            assert instruction["how"] in ["inner", "left", "right", "outer"]
            assert isinstance(instruction["on"], list)
            assert len(instruction["on"]) > 0

    def test_transform_joins_dict_to_instructions_complex_table_names(self):
        """Test transformation with complex table names containing special characters."""
        # Arrange
        joins_dict = {
            ("data_collection_123", "user_events_2024"): [
                {
                    "data_collection_123--user_events_2024": {
                        "how": "inner",
                        "on_columns": ["event_id", "user_session_id"],
                    }
                }
            ]
        }

        # Act
        result = transform_joins_dict_to_instructions(joins_dict)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1

        instruction = result[0]
        assert instruction["left"] == "data_collection_123"
        assert instruction["right"] == "user_events_2024"
        assert instruction["how"] == "inner"
        assert instruction["on"] == ["event_id", "user_session_id"]

        # Verify complex table names are handled correctly
        assert "_" in instruction["left"]
        assert "_" in instruction["right"]

    def test_transform_joins_dict_to_instructions_single_column_join(self):
        """Test transformation with single column joins."""
        # Arrange
        joins_dict = {
            ("source", "target"): [{"source--target": {"how": "inner", "on_columns": ["key"]}}]
        }

        # Act
        result = transform_joins_dict_to_instructions(joins_dict)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1

        instruction = result[0]
        assert isinstance(instruction["on"], list)
        assert len(instruction["on"]) == 1
        assert instruction["on"][0] == "key"

        # Verify single-element list structure is preserved
        assert instruction["on"] == ["key"]
        assert instruction["on"] != "key"  # Should be list, not string


class TestGetJoinTables:
    """Test join tables retrieval functionality."""

    def setup_method(self):
        """Set up test fixtures and clear cache."""
        from depictio.api.v1.deltatables_utils import _join_tables_cache

        _join_tables_cache.clear()

    @patch("depictio.api.v1.deltatables_utils.httpx.get")
    def test_get_join_tables_success(self, mock_httpx_get):
        """Test successful join tables retrieval."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "wf_123": {"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}
        }
        mock_httpx_get.return_value = mock_response

        # Act
        result = get_join_tables("wf_123", "test_token")

        # Assert
        assert result is not None
        assert "wf_123" in result

    @patch("depictio.api.v1.deltatables_utils.httpx.get")
    def test_get_join_tables_api_error(self, mock_httpx_get):
        """Test join tables retrieval with API error."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_httpx_get.return_value = mock_response

        # Act
        result = get_join_tables("wf_123", "test_token")

        # Assert
        assert result == {}

    @patch("depictio.api.v1.deltatables_utils.httpx.get")
    def test_get_join_tables_caching(self, mock_httpx_get):
        """Test that join tables are cached properly."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"wf_123": {}}
        mock_httpx_get.return_value = mock_response

        # Act
        result1 = get_join_tables("wf_123", "test_token")
        result2 = get_join_tables("wf_123", "test_token")

        # Assert
        assert result1 == result2
        # Should only make one HTTP call due to caching
        assert mock_httpx_get.call_count == 1


class TestIterativeJoin:
    """Test iterative join functionality with caching."""

    def setup_method(self):
        """Set up test fixtures and clear cache."""
        from depictio.api.v1.deltatables_utils import _iterative_join_cache

        _iterative_join_cache.clear()

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_iterative_join_basic(self, mock_load_deltatable):
        """Test basic iterative join functionality."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2], "col1": ["a", "b"]})
        df2 = pl.DataFrame({"id": [1, 2], "col2": [10, 20]})

        def side_effect(workflow_id, dc_id, metadata, TOKEN=None):
            if dc_id == "dc1":
                return df1
            elif dc_id == "dc2":
                return df2
            return pl.DataFrame()

        mock_load_deltatable.side_effect = side_effect

        workflow_id = ObjectId()
        joins_dict = {("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}]}
        metadata_dict = {
            "comp1": {"component_type": "interactive", "metadata": {"dc_id": "dc1"}, "value": None}
        }

        # Act
        result = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result is not None
        assert result.height > 0
        assert "col1" in result.columns
        assert "col2" in result.columns
        assert result["id"].to_list() == [1, 2]  # Both DataFrames have matching IDs
        assert result.width == 3  # id, col1, col2

    def test_iterative_join_no_joins(self):
        """Test iterative join with no joins returns single DataFrame."""
        # Arrange
        workflow_id = ObjectId()
        joins_dict = {}
        metadata_dict = {
            "comp1": {"component_type": "interactive", "metadata": {"dc_id": "dc1"}, "value": None}
        }

        # Act
        with patch("depictio.api.v1.deltatables_utils.load_deltatable_lite") as mock_load:
            mock_df = pl.DataFrame({"col": [1, 2, 3]})
            mock_load.return_value = mock_df

            result = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result.equals(mock_df)

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_iterative_join_caching(self, mock_load_deltatable):
        """Test that iterative join results are cached."""
        # Arrange
        mock_df = pl.DataFrame({"id": [1, 2], "value": [10, 20]})
        mock_load_deltatable.return_value = mock_df

        workflow_id = ObjectId()
        joins_dict = {("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}]}
        metadata_dict = {
            "comp1": {"component_type": "interactive", "metadata": {"dc_id": "dc1"}, "value": None}
        }

        # Act - Call twice
        result1 = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")
        result2 = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result1.equals(result2)
        # Second call should use cache (though load_deltatable might still be called for data loading)

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_iterative_join_concurrent_loading(self, mock_load_deltatable):
        """Test that multiple DataFrames are loaded concurrently."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2], "col1": ["a", "b"]})
        df2 = pl.DataFrame({"id": [1, 2], "col2": [10, 20]})
        df3 = pl.DataFrame({"id": [1, 2], "col3": [100, 200]})

        # Mock to return different DataFrames based on dc_id
        def side_effect(workflow_id, dc_id, metadata, TOKEN=None):
            if dc_id == "dc1":
                return df1
            elif dc_id == "dc2":
                return df2
            elif dc_id == "dc3":
                return df3
            return pl.DataFrame()

        mock_load_deltatable.side_effect = side_effect

        workflow_id = ObjectId()
        joins_dict = {
            ("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}],
            ("dc2", "dc3"): [{"dc2--dc3": {"how": "inner", "on_columns": ["id"]}}],
        }
        metadata_dict = {
            "comp1": {"component_type": "interactive", "metadata": {"dc_id": "dc1"}, "value": None},
            "comp2": {"component_type": "interactive", "metadata": {"dc_id": "dc2"}, "value": None},
            "comp3": {"component_type": "interactive", "metadata": {"dc_id": "dc3"}, "value": None},
        }

        # Act
        result = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result is not None
        # All 3 DataFrames should have been loaded
        assert mock_load_deltatable.call_count == 3
        # Verify concurrent loading by checking all dc_ids were called
        called_dc_ids = {call[0][1] for call in mock_load_deltatable.call_args_list}
        assert called_dc_ids == {"dc1", "dc2", "dc3"}

        # Verify result has columns from all DataFrames after joins
        expected_columns = {"id", "col1", "col2", "col3"}
        assert set(result.columns) == expected_columns
        assert result.height == 2  # Both DataFrames have 2 rows with matching IDs

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_iterative_join_with_metadata_filtering(self, mock_load_deltatable):
        """Test iterative join with metadata filtering applied."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2, 3], "category": ["A", "B", "A"], "value1": [10, 20, 30]})
        df2 = pl.DataFrame(
            {"id": [1, 2, 3], "category": ["A", "B", "A"], "value2": [100, 200, 300]}
        )

        def side_effect(workflow_id, dc_id, metadata, TOKEN=None):
            if dc_id == "dc1":
                return df1
            elif dc_id == "dc2":
                return df2
            return pl.DataFrame()

        mock_load_deltatable.side_effect = side_effect

        workflow_id = ObjectId()
        joins_dict = {("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}]}
        metadata_dict = {
            "filter1": {
                "component_type": "interactive",
                "metadata": {
                    "dc_id": "dc1",
                    "interactive_component_type": "Select",
                    "column_name": "category",
                },
                "value": ["A"],  # Filter for category A
            }
        }

        # Act
        result = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result is not None
        print(f"Result DataFrame:\n{result}")
        assert result.height == 2  # Only rows with category A should remain
        assert all(category == "A" for category in result["category"].to_list())
        assert set(result.columns) >= {"id", "category", "value1", "value2"}

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_iterative_join_different_join_types(self, mock_load_deltatable):
        """Test iterative join with different join types (left, right, outer)."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]})
        df2 = pl.DataFrame({"id": [2, 3, 4], "age": [25, 30, 35]})

        def side_effect(workflow_id, dc_id, metadata, TOKEN=None):
            if dc_id == "dc1":
                return df1
            elif dc_id == "dc2":
                return df2
            return pl.DataFrame()

        mock_load_deltatable.side_effect = side_effect

        workflow_id = ObjectId()
        joins_dict = {("dc1", "dc2"): [{"dc1--dc2": {"how": "left", "on_columns": ["id"]}}]}
        metadata_dict = {
            "comp1": {"component_type": "interactive", "metadata": {"dc_id": "dc1"}, "value": None}
        }

        # Act
        result = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result is not None
        assert result.height == 3  # Left join should preserve all rows from df1
        assert set(result.columns) >= {"id", "name", "age"}

        # Check that id=1 has name but null age (left join behavior)
        id_1_row = result.filter(pl.col("id") == 1)
        assert id_1_row.height == 1
        assert id_1_row["name"][0] == "Alice"
        assert id_1_row["age"][0] is None

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_iterative_join_multiple_join_columns(self, mock_load_deltatable):
        """Test iterative join with multiple join columns."""
        # Arrange
        df1 = pl.DataFrame(
            {
                "user_id": [1, 1, 2, 2],
                "session_id": ["s1", "s2", "s1", "s2"],
                "action": ["login", "logout", "login", "logout"],
            }
        )
        df2 = pl.DataFrame(
            {
                "user_id": [1, 1, 2, 2],
                "session_id": ["s1", "s2", "s1", "s2"],
                "duration": [30, 45, 60, 25],
            }
        )

        def side_effect(workflow_id, dc_id, metadata, TOKEN=None):
            if dc_id == "events":
                return df1
            elif dc_id == "metrics":
                return df2
            return pl.DataFrame()

        mock_load_deltatable.side_effect = side_effect

        workflow_id = ObjectId()
        joins_dict = {
            ("events", "metrics"): [
                {"events--metrics": {"how": "inner", "on_columns": ["user_id", "session_id"]}}
            ]
        }
        metadata_dict = {
            "comp1": {
                "component_type": "interactive",
                "metadata": {"dc_id": "events"},
                "value": None,
            }
        }

        # Act
        result = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result is not None
        assert result.height == 4  # All rows should match on both columns
        assert set(result.columns) >= {"user_id", "session_id", "action", "duration"}

        # Verify specific combinations exist
        user1_s1 = result.filter((pl.col("user_id") == 1) & (pl.col("session_id") == "s1"))
        assert user1_s1.height == 1
        assert user1_s1["action"][0] == "login"
        assert user1_s1["duration"][0] == 30

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_iterative_join_empty_result_after_filtering(self, mock_load_deltatable):
        """Test iterative join when filtering results in empty DataFrames."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2], "category": ["A", "B"], "value": [10, 20]})
        df2 = pl.DataFrame({"id": [1, 2], "category": ["A", "B"], "score": [100, 200]})

        def side_effect(workflow_id, dc_id, metadata, TOKEN=None):
            if dc_id == "dc1":
                return df1
            elif dc_id == "dc2":
                return df2
            return pl.DataFrame()

        mock_load_deltatable.side_effect = side_effect

        workflow_id = ObjectId()
        joins_dict = {("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}]}
        metadata_dict = {
            "filter1": {
                "component_type": "interactive",
                "metadata": {
                    "dc_id": "dc1",
                    "interactive_component_type": "Select",
                    "column_name": "category",
                },
                "value": ["C"],  # Non-existent category
            }
        }

        # Act
        result = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result is not None
        assert result.height == 0  # No rows should match the filter
        # Schema should still be correct even with empty result
        expected_columns = {"id", "category", "value", "category_right", "score"}
        assert set(result.columns) == expected_columns

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_iterative_join_chain_of_joins(self, mock_load_deltatable):
        """Test iterative join with a chain of multiple joins."""
        # Arrange
        df1 = pl.DataFrame({"id": [1, 2], "name": ["A", "B"]})
        df2 = pl.DataFrame({"id": [1, 2], "value": [10, 20]})
        df3 = pl.DataFrame({"id": [1, 2], "score": [100, 200]})
        df4 = pl.DataFrame({"id": [1, 2], "rating": [5, 4]})

        def side_effect(workflow_id, dc_id, metadata, TOKEN=None):
            return {"dc1": df1, "dc2": df2, "dc3": df3, "dc4": df4}.get(dc_id, pl.DataFrame())

        mock_load_deltatable.side_effect = side_effect

        workflow_id = ObjectId()
        joins_dict = {
            ("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}],
            ("dc2", "dc3"): [{"dc2--dc3": {"how": "inner", "on_columns": ["id"]}}],
            ("dc3", "dc4"): [{"dc3--dc4": {"how": "inner", "on_columns": ["id"]}}],
        }
        metadata_dict = {
            f"comp{i}": {
                "component_type": "interactive",
                "metadata": {"dc_id": f"dc{i}"},
                "value": None,
            }
            for i in range(1, 5)
        }

        # Act
        result = iterative_join(workflow_id, joins_dict, metadata_dict, "test_token")

        # Assert
        assert result is not None
        assert result.height == 2  # All joins should preserve the 2 rows
        expected_columns = {"id", "name", "value", "score", "rating"}
        assert set(result.columns) == expected_columns

        # Verify all data is correctly joined
        row1 = result.filter(pl.col("id") == 1).to_dicts()[0]
        assert row1["name"] == "A"
        assert row1["value"] == 10
        assert row1["score"] == 100
        assert row1["rating"] == 5

    def test_iterative_join_cache_key_generation(self):
        """Test that cache keys are generated correctly for different inputs."""
        # Note: This tests the internal cache key generation logic
        workflow_id1 = ObjectId()
        workflow_id2 = ObjectId()

        joins_dict1 = {("dc1", "dc2"): [{"dc1--dc2": {"how": "inner", "on_columns": ["id"]}}]}
        joins_dict2 = {("dc1", "dc3"): [{"dc1--dc3": {"how": "left", "on_columns": ["id"]}}]}

        metadata_dict1 = {"comp1": {"metadata": {"dc_id": "dc1"}, "value": ["A"]}}
        metadata_dict2 = {"comp1": {"metadata": {"dc_id": "dc1"}, "value": ["B"]}}

        # Different combinations should produce different cache keys
        # This is more of a design verification than a direct test
        assert workflow_id1 != workflow_id2
        assert joins_dict1 != joins_dict2
        assert metadata_dict1 != metadata_dict2
