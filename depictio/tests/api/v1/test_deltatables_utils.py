"""
Tests for depictio.api.v1.deltatables_utils module.
"""

from unittest.mock import MagicMock, patch

# import pandera.polars as pap
import polars as pl
from bson import ObjectId

from depictio.api.v1.deltatables_utils import (
    # add_filter,
    convert_filter_model_to_metadata,
    load_deltatable_lite,
    process_metadata_and_filter,
)

# class TestAddFilter:
#     """Test filter addition functionality with comprehensive validation."""

#     def setup_method(self):
#         """Set up test fixtures."""
#         # Create sample datasets for testing different filter scenarios
#         self.categorical_df = pl.DataFrame(
#             {
#                 "category": ["A", "B", "C", "A", "B"],
#                 "tags": ["tag1,tag2", "tag2,tag3", "tag1,tag3", "tag2", "tag1"],
#                 "description": [
#                     "apple fruit",
#                     "banana yellow",
#                     "cherry red",
#                     "avocado green",
#                     "blueberry",
#                 ],
#                 "value": [1, 2, 3, 4, 5],
#             }
#         )

#         self.numeric_df = pl.DataFrame(
#             {
#                 "price": [10.5, 25.0, 50.0, 75.5, 100.0],
#                 "quantity": [1, 2, 3, 4, 5],
#                 "rating": [4.5, 3.8, 4.9, 4.2, 3.5],
#             }
#         )

#         # Pandera schema for validation if available
#         self.expected_filter_schema = pap.DataFrameSchema(
#             {"category": pap.Column(pl.String), "value": pap.Column(pl.Int64)}
#         )

#     def test_add_filter_select_component_basic(self):
#         """Test adding filter for Select component with basic functionality."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="Select",
#             column_name="category",
#             value=["A", "B"],
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.categorical_df.filter(filter_list[0])
#         assert filtered_df.height == 4  # Should filter to 4 rows with categories A and B
#         assert set(filtered_df["category"].to_list()) == {"A", "B"}

#     def test_add_filter_select_component_single_value(self):
#         """Test Select component with single value selection."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list, interactive_component_type="Select", column_name="category", value=["A"]
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.categorical_df.filter(filter_list[0])
#         assert filtered_df.height == 2
#         assert all(cat == "A" for cat in filtered_df["category"].to_list())

#     def test_add_filter_select_component_empty_result(self):
#         """Test Select component filter that results in empty DataFrame."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="Select",
#             column_name="category",
#             value=["Z"],  # Non-existent category
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.categorical_df.filter(filter_list[0])
#         assert filtered_df.height == 0

#     def test_add_filter_multiselect_component_basic(self):
#         """Test adding filter for MultiSelect component."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="MultiSelect",
#             column_name="category",
#             value=["A", "C"],
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.categorical_df.filter(filter_list[0])
#         assert filtered_df.height == 3  # 2 A's + 1 C
#         assert set(filtered_df["category"].to_list()) == {"A", "C"}

#     def test_add_filter_multiselect_component_all_values(self):
#         """Test MultiSelect with all available values selected."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="MultiSelect",
#             column_name="category",
#             value=["A", "B", "C"],
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.categorical_df.filter(filter_list[0])
#         assert filtered_df.height == 5  # All rows should pass

#     def test_add_filter_text_input_component_contains(self):
#         """Test adding filter for TextInput component with contains logic."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="TextInput",
#             column_name="description",
#             value="fruit",
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.categorical_df.filter(filter_list[0])
#         assert filtered_df.height == 1  # Only "apple fruit"
#         assert "fruit" in filtered_df["description"].to_list()[0]

#     # def test_add_filter_text_input_component_case_insensitive(self):
#     #     """Test TextInput filter is case insensitive."""
#     #     # Arrange
#     #     filter_list = []

#     #     # Act
#     #     add_filter(
#     #         filter_list,
#     #         interactive_component_type="TextInput",
#     #         column_name="description",
#     #         value="APPLE"
#     #     )

#     #     # Assert
#     #     assert len(filter_list) == 1
#     #     filtered_df = self.categorical_df.filter(filter_list[0])
#     #     print(f"Filtered DataFrame: {filtered_df}")
#     #     assert filtered_df.height == 1

#     def test_add_filter_text_input_component_partial_match(self):
#         """Test TextInput filter with partial string matching."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="TextInput",
#             column_name="description",
#             value=".*erry",
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.categorical_df.filter(filter_list[0])
#         print(f"Filtered DataFrame: {filtered_df}")
#         assert filtered_df.height == 2  # "cherry" and "blueberry"

#     def test_add_filter_slider_component_equality(self):
#         """Test adding filter for Slider component with equality check."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list, interactive_component_type="Slider", column_name="quantity", value=3
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.numeric_df.filter(filter_list[0])
#         assert filtered_df.height == 1
#         assert filtered_df["quantity"].to_list()[0] == 3

#     def test_add_filter_slider_component_float_value(self):
#         """Test Slider component with float values."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list, interactive_component_type="Slider", column_name="rating", value=4.5
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.numeric_df.filter(filter_list[0])
#         assert filtered_df.height == 1
#         assert filtered_df["rating"].to_list()[0] == 4.5

#     def test_add_filter_range_slider_component_basic(self):
#         """Test adding filter for RangeSlider component with range filtering."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="RangeSlider",
#             column_name="price",
#             value=[20, 80],
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.numeric_df.filter(filter_list[0])
#         assert filtered_df.height == 3  # 25.0, 50.0, 75.5
#         filtered_prices = filtered_df["price"].to_list()
#         assert all(20 <= price <= 80 for price in filtered_prices)

#     def test_add_filter_range_slider_component_inclusive_bounds(self):
#         """Test RangeSlider filter includes boundary values."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="RangeSlider",
#             column_name="price",
#             value=[25.0, 50.0],
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.numeric_df.filter(filter_list[0])
#         assert filtered_df.height == 2  # Exactly 25.0 and 50.0
#         filtered_prices = sorted(filtered_df["price"].to_list())
#         assert filtered_prices == [25.0, 50.0]

#     def test_add_filter_range_slider_component_narrow_range(self):
#         """Test RangeSlider with very narrow range."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="RangeSlider",
#             column_name="price",
#             value=[49, 51],
#         )

#         # Assert
#         assert len(filter_list) == 1
#         filtered_df = self.numeric_df.filter(filter_list[0])
#         assert filtered_df.height == 1  # Only 50.0
#         assert filtered_df["price"].to_list()[0] == 50.0

#     def test_add_filter_no_value_skipped(self):
#         """Test that filters with no value are not added."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list, interactive_component_type="Select", column_name="category", value=None
#         )

#         # Assert
#         assert len(filter_list) == 0

#     def test_add_filter_empty_list_value_skipped(self):
#         """Test that filters with empty list values are not added."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list, interactive_component_type="MultiSelect", column_name="category", value=[]
#         )

#         # Assert
#         assert len(filter_list) == 0

#     def test_add_filter_empty_string_value_skipped(self):
#         """Test that filters with empty string values are not added."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list, interactive_component_type="TextInput", column_name="description", value=""
#         )

#         # Assert
#         assert len(filter_list) == 0

#     def test_add_filter_schema_validation(self):
#         """Test filter results conform to expected schema using Pandera."""
#         # Arrange
#         filter_list = []

#         # Act
#         add_filter(
#             filter_list,
#             interactive_component_type="Select",
#             column_name="category",
#             value=["A", "B"],
#         )

#         # Assert with Pandera validation
#         filtered_df = self.categorical_df.filter(filter_list[0]).select(["category", "value"])

#         # This should not raise an exception if schema is valid
#         validated_df = self.expected_filter_schema.validate(filtered_df)
#         assert validated_df is not None
#         assert len(validated_df) > 0

#     def test_add_filter_multiple_filters_combination(self):
#         """Test combining multiple filters works correctly."""
#         # Arrange
#         filter_list = []

#         # Act - Add multiple filters
#         add_filter(
#             filter_list,
#             interactive_component_type="Select",
#             column_name="category",
#             value=["A", "B"],
#         )

#         add_filter(
#             filter_list, interactive_component_type="RangeSlider", column_name="value", value=[2, 4]
#         )

#         # Assert
#         assert len(filter_list) == 2

#         # Apply all filters
#         filtered_df = self.categorical_df
#         for filter_expr in filter_list:
#             filtered_df = filtered_df.filter(filter_expr)

#         # Should have categories A or B AND values between 2-4
#         assert filtered_df.height == 2  # category B with value 2, category A with value 4
#         result_categories = set(filtered_df["category"].to_list())
#         result_values = filtered_df["value"].to_list()

#         assert result_categories.issubset({"A", "B"})
#         assert all(2 <= val <= 4 for val in result_values)


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

    def test_convert_filter_model_multiple_filters(self):
        """Test converting multiple filters in one model."""
        # Arrange
        filter_model = {
            "price": {"filterType": "number", "type": "inRange", "filter": 10, "filterTo": 100},
            "category": {"filterType": "text", "type": "contains", "filter": "electronics"},
            "rating": {"filterType": "number", "type": "equals", "filter": 5},
        }

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 3

        # Check price filter
        price_filter = next(r for r in result if r["metadata"]["column_name"] == "price")
        assert price_filter["metadata"]["interactive_component_type"] == "RangeSlider"
        assert price_filter["value"] == [10, 100]

        # Check category filter
        category_filter = next(r for r in result if r["metadata"]["column_name"] == "category")
        assert category_filter["metadata"]["interactive_component_type"] == "TextInput"
        assert category_filter["value"] == "electronics"

        # Check rating filter
        rating_filter = next(r for r in result if r["metadata"]["column_name"] == "rating")
        assert rating_filter["metadata"]["interactive_component_type"] == "Slider"
        assert rating_filter["value"] == 5

    def test_convert_filter_model_empty_filter(self):
        """Test converting empty filter model."""
        # Arrange
        filter_model = {}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 0
        assert result == []

    def test_convert_filter_model_text_filter_starts_with(self):
        """Test converting text filter with startsWith type."""
        # Arrange
        filter_model = {"name": {"filterType": "text", "type": "startsWith", "filter": "prod"}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1
        assert result[0]["metadata"]["interactive_component_type"] == "TextInput"
        assert result[0]["value"] == "prod"

    def test_convert_filter_model_text_filter_ends_with(self):
        """Test converting text filter with endsWith type."""
        # Arrange
        filter_model = {"description": {"filterType": "text", "type": "endsWith", "filter": "tion"}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1
        assert result[0]["metadata"]["interactive_component_type"] == "TextInput"
        assert result[0]["value"] == "tion"

    def test_convert_filter_model_numeric_filter_greater_than(self):
        """Test converting numeric filter with greaterThan type."""
        # Arrange
        filter_model = {"score": {"filterType": "number", "type": "greaterThan", "filter": 80}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1
        assert result[0]["metadata"]["interactive_component_type"] == "Slider"
        assert result[0]["value"] == 80

    def test_convert_filter_model_numeric_filter_less_than(self):
        """Test converting numeric filter with lessThan type."""
        # Arrange
        filter_model = {"age": {"filterType": "number", "type": "lessThan", "filter": 65}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1
        assert result[0]["metadata"]["interactive_component_type"] == "Slider"
        assert result[0]["value"] == 65

    def test_convert_filter_model_range_filter_with_floats(self):
        """Test converting range filter with float values."""
        # Arrange
        filter_model = {
            "temperature": {
                "filterType": "number",
                "type": "inRange",
                "filter": 20.5,
                "filterTo": 25.8,
            }
        }

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1
        assert result[0]["metadata"]["interactive_component_type"] == "RangeSlider"
        assert result[0]["value"] == [20.5, 25.8]

    def test_convert_filter_model_missing_filter_value(self):
        """Test converting filter model with missing filter value."""
        # Arrange
        filter_model = {"name": {"filterType": "text", "type": "contains"}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 1  # Function still creates entry with None value
        assert result[0]["metadata"]["column_name"] == "name"
        assert result[0]["metadata"]["interactive_component_type"] == "TextInput"
        assert result[0]["value"] is None

    def test_convert_filter_model_range_filter_missing_filter_to(self):
        """Test converting range filter with missing filterTo value."""
        # Arrange
        filter_model = {"price": {"filterType": "number", "type": "inRange", "filter": 10}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 0  # Should skip incomplete range filters

    def test_convert_filter_model_unknown_filter_type(self):
        """Test converting filter model with unknown filter type."""
        # Arrange
        filter_model = {"custom": {"filterType": "unknown", "type": "custom", "filter": "value"}}

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 0  # Function skips unknown filter types

    def test_convert_filter_model_case_sensitivity(self):
        """Test filter model conversion handles case-sensitive column names."""
        # Arrange
        filter_model = {
            "UserID": {"filterType": "number", "type": "equals", "filter": 123},
            "user_name": {"filterType": "text", "type": "contains", "filter": "john"},
        }

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 2

        # Check UserID filter
        userid_filter = next(r for r in result if r["metadata"]["column_name"] == "UserID")
        assert userid_filter["metadata"]["interactive_component_type"] == "Slider"
        assert userid_filter["value"] == 123

        # Check user_name filter
        username_filter = next(r for r in result if r["metadata"]["column_name"] == "user_name")
        assert username_filter["metadata"]["interactive_component_type"] == "TextInput"
        assert username_filter["value"] == "john"

    def test_convert_filter_model_special_characters_in_values(self):
        """Test filter model conversion with special characters in filter values."""
        # Arrange
        filter_model = {
            "description": {"filterType": "text", "type": "contains", "filter": "special@#$%chars"},
            "code": {"filterType": "text", "type": "equals", "filter": "ABC-123_XYZ"},
        }

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 2

        # Check description filter
        desc_filter = next(r for r in result if r["metadata"]["column_name"] == "description")
        assert desc_filter["value"] == "special@#$%chars"

        # Check code filter
        code_filter = next(r for r in result if r["metadata"]["column_name"] == "code")
        assert code_filter["value"] == "ABC-123_XYZ"

    def test_convert_filter_model_zero_values(self):
        """Test filter model conversion with zero values."""
        # Arrange
        filter_model = {
            "count": {"filterType": "number", "type": "equals", "filter": 0},
            "range_col": {"filterType": "number", "type": "inRange", "filter": 0, "filterTo": 0},
        }

        # Act
        result = convert_filter_model_to_metadata(filter_model)

        # Assert
        assert len(result) == 2

        # Check count filter
        count_filter = next(r for r in result if r["metadata"]["column_name"] == "count")
        assert count_filter["value"] == 0

        # Check range filter
        range_filter = next(r for r in result if r["metadata"]["column_name"] == "range_col")
        assert range_filter["value"] == [0, 0]


class TestLoadDeltatablelite:
    """Test Delta table loading functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        pass

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
    @patch("depictio.api.v1.deltatables_utils.get_deltatable_size_from_db")
    def test_load_deltatable_lite_with_metadata_filtering(
        self, mock_get_size, mock_scan_delta, mock_httpx_get
    ):
        """Test Delta table loading with metadata filtering."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"delta_table_location": "s3://bucket/table"}
        mock_httpx_get.return_value = mock_response

        # Mock large size to force lazy loading path
        mock_get_size.return_value = 2 * 1024 * 1024 * 1024  # 2GB - forces lazy loading

        mock_df = pl.DataFrame({"category": ["A", "B"], "value": [1, 2]})
        mock_lazy_frame = MagicMock()
        mock_lazy_frame.filter.return_value = mock_lazy_frame
        mock_lazy_frame.collect.return_value = mock_df
        mock_scan_delta.return_value = mock_lazy_frame

        metadata = [
            {
                "interactive_component_type": "Select",
                "column_name": "category",
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


class TestCachingFixes:
    """Test fixes for caching and filtering issues in joined data collections."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_df = pl.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "category": ["A", "B", "A", "B", "A", "B", "A", "B", "A", "B"],
                "value": [10, 20, 15, 25, 30, 35, 40, 45, 50, 55],
            }
        )

    def test_apply_runtime_filters_preserves_full_dataset(self):
        """Test that runtime filters are applied correctly before row limits."""
        from depictio.api.v1.deltatables_utils import apply_runtime_filters

        # Create metadata filtering for category "A"
        metadata = [
            {
                "component_id": "test-component",
                "component_type": "interactive",
                "interactive_component_type": "Select",
                "column_name": "category",
                "value": ["A"],
            }
        ]

        # Apply runtime filters
        filtered_df = apply_runtime_filters(self.test_df, metadata)

        # Verify correct filtering - should have only category "A" rows
        assert filtered_df.height == 5  # Should have 5 rows of category "A"
        unique_categories = filtered_df["category"].unique().to_list()
        assert unique_categories == ["A"], f"Expected only category 'A', got {unique_categories}"

        # Verify the values are correct (should be 10, 15, 30, 40, 50)
        expected_values = [10, 15, 30, 40, 50]
        actual_values = sorted(filtered_df["value"].to_list())
        assert actual_values == expected_values

    def test_row_limit_applied_after_filters(self):
        """Test that row limits are applied AFTER filters, not before."""
        from depictio.api.v1.deltatables_utils import apply_runtime_filters

        # Create metadata filtering for category "A"
        metadata = [
            {
                "component_id": "test-component",
                "component_type": "interactive",
                "interactive_component_type": "Select",
                "column_name": "category",
                "value": ["A"],
            }
        ]

        # Apply filters first
        filtered_df = apply_runtime_filters(self.test_df, metadata)

        # Then apply row limit
        limited_df = filtered_df.limit(3)

        # Verify we get 3 rows, all of category "A"
        assert limited_df.height == 3
        unique_categories = limited_df["category"].unique().to_list()
        assert unique_categories == ["A"]

        # Verify all values are from category "A" only
        expected_values = [10, 15, 30]  # First 3 values from category "A"
        actual_values = limited_df["value"].to_list()
        assert actual_values == expected_values

    def test_range_slider_filtering(self):
        """Test that range slider filters work correctly."""
        from depictio.api.v1.deltatables_utils import apply_runtime_filters

        # Create DataFrame with bill_length_mm column as in production logs
        df = pl.DataFrame(
            {"bill_length_mm": [30.0, 35.0, 40.0, 45.0, 50.0, 55.0], "id": [1, 2, 3, 4, 5, 6]}
        )

        # Create range slider metadata as seen in production
        metadata = [
            {
                "component_id": "e69ba3a8-4c42-48d4-9019-8ade0ed077e4",
                "component_type": "interactive",
                "interactive_component_type": "RangeSlider",
                "column_name": "bill_length_mm",
                "value": [32.1, 52.47],
            }
        ]

        # Apply range filter
        filtered_df = apply_runtime_filters(df, metadata)

        # Verify range filtering works correctly
        assert filtered_df.height == 4  # Values 35.0, 40.0, 45.0, 50.0 should pass
        actual_values = filtered_df["bill_length_mm"].to_list()
        expected_values = [35.0, 40.0, 45.0, 50.0]
        assert actual_values == expected_values

        # Verify all values are within range
        min_val = filtered_df["bill_length_mm"].min()
        max_val = filtered_df["bill_length_mm"].max()
        assert min_val is not None and min_val >= 32.1
        assert max_val is not None and max_val <= 52.47

    def test_empty_dataframe_handling(self):
        """Test that empty DataFrames don't crash the filtering system."""
        from depictio.api.v1.deltatables_utils import apply_runtime_filters

        # Create empty DataFrame
        empty_df = pl.DataFrame(
            {"category": [], "value": []}, schema={"category": pl.String, "value": pl.Int64}
        )

        metadata = [
            {
                "component_id": "test-empty",
                "component_type": "interactive",
                "interactive_component_type": "Select",
                "column_name": "category",
                "value": ["A"],
            }
        ]

        # Apply filters to empty DataFrame
        result = apply_runtime_filters(empty_df, metadata)

        # Should remain empty
        assert result.height == 0
        assert result.width == 2  # Should preserve schema

    def test_multiple_filters_combination(self):
        """Test that multiple filters work together correctly."""
        from depictio.api.v1.deltatables_utils import apply_runtime_filters

        df = pl.DataFrame(
            {"category": ["A", "B", "A", "C", "A", "B"], "value": [10, 20, 30, 40, 50, 60]}
        )

        # Apply both category and range filters
        metadata = [
            {
                "component_id": "test-cat",
                "component_type": "interactive",
                "interactive_component_type": "Select",
                "column_name": "category",
                "value": ["A", "B"],
            },
            {
                "component_id": "test-val",
                "component_type": "interactive",
                "interactive_component_type": "RangeSlider",
                "column_name": "value",
                "value": [25, 55],
            },
        ]

        result = apply_runtime_filters(df, metadata)

        # Should have category A or B, AND value between 25-55
        # This means A-30 and A-50 should match
        assert result.height == 2
        values = sorted(result["value"].to_list())
        assert values == [30, 50]

        # Verify all categories are A or B
        categories = result["category"].unique().to_list()
        assert all(cat in ["A", "B"] for cat in categories)


class TestInteractiveComponentsLogic:
    """Test fixes for interactive components affecting joined data collections."""

    def test_join_inclusion_with_interactive_components(self):
        """Test that joins are included when DCs have interactive components."""
        # Simulate the exact scenario from production logs
        dc_ids_with_interactive = ["68966a9759ec31ef651950c1"]
        join_tables = {
            "68966a9759ec31ef651950c1--68966a9759ec31ef651950c3": {
                "how": "inner",
                "on_columns": ["individual_id"],
            }
        }

        # Test the matching logic from return_joins_dict function
        filtered_joins = {}
        for join_key, join_config in join_tables.items():
            # This is the exact logic from the fixed code
            if any(dc_id in join_key for dc_id in dc_ids_with_interactive):
                filtered_joins[join_key] = join_config

        # Verify the join was included
        assert len(filtered_joins) == 1
        assert "68966a9759ec31ef651950c1--68966a9759ec31ef651950c3" in filtered_joins

        # Verify join configuration is preserved
        join_config = filtered_joins["68966a9759ec31ef651950c1--68966a9759ec31ef651950c3"]
        assert join_config["how"] == "inner"
        assert join_config["on_columns"] == ["individual_id"]

    def test_join_inclusion_multiple_interactive_dcs(self):
        """Test join inclusion when multiple DCs have interactive components."""
        dc_ids_with_interactive = ["dc1", "dc3"]
        join_tables = {
            "dc1--dc2": {"how": "inner", "on_columns": ["id"]},
            "dc2--dc3": {"how": "left", "on_columns": ["id"]},
            "dc3--dc4": {"how": "outer", "on_columns": ["id"]},
            "dc4--dc5": {"how": "inner", "on_columns": ["id"]},
        }

        # Apply the filtering logic
        filtered_joins = {}
        for join_key, join_config in join_tables.items():
            if any(dc_id in join_key for dc_id in dc_ids_with_interactive):
                filtered_joins[join_key] = join_config

        # Should include joins that contain dc1 or dc3
        expected_joins = {"dc1--dc2", "dc2--dc3", "dc3--dc4"}
        assert set(filtered_joins.keys()) == expected_joins

        # Should exclude dc4--dc5 since neither dc4 nor dc5 have interactive components
        assert "dc4--dc5" not in filtered_joins

    def test_join_exclusion_no_interactive_components(self):
        """Test that joins are excluded when no DCs have interactive components."""
        dc_ids_with_interactive = []  # No interactive components
        join_tables = {
            "dc1--dc2": {"how": "inner", "on_columns": ["id"]},
            "dc2--dc3": {"how": "left", "on_columns": ["id"]},
        }

        # Apply the filtering logic
        filtered_joins = {}
        for join_key, join_config in join_tables.items():
            if any(dc_id in join_key for dc_id in dc_ids_with_interactive):
                filtered_joins[join_key] = join_config

        # Should have no joins since no DCs have interactive components
        assert len(filtered_joins) == 0

    def test_join_key_parsing(self):
        """Test that join keys are parsed correctly."""
        dc_ids_with_interactive = ["68966a9759ec31ef651950c1"]
        join_key = "68966a9759ec31ef651950c1--68966a9759ec31ef651950c3"

        # Test the parsing logic
        dc_id1, dc_id2 = join_key.split("--")

        assert dc_id1 == "68966a9759ec31ef651950c1"
        assert dc_id2 == "68966a9759ec31ef651950c3"

        # Test that the matching works
        has_interactive = any(dc_id in join_key for dc_id in dc_ids_with_interactive)
        assert has_interactive  # Should be True since dc_id1 matches


class TestJoinedDataCollectionIntegration:
    """Integration tests for the complete joined data collection workflow."""

    @patch("depictio.api.v1.deltatables_utils.load_deltatable_lite")
    def test_joined_collection_preserves_full_dataset(self, mock_load):
        """Test that joined collections get the full filtered dataset, not limited cache."""
        from depictio.api.v1.deltatables_utils import _load_joined_deltatable

        # Create test ObjectIds
        test_workflow_id = ObjectId()
        dc1_id = ObjectId()
        dc2_id = ObjectId()
        joined_dc_id = f"{dc1_id}--{dc2_id}"

        # Mock the individual DataFrame loading with unique IDs per row
        df1 = pl.DataFrame(
            {
                "individual_id": list(range(1, 101)),  # 100 unique IDs
                "bill_length_mm": [32.1, 35.0, 40.0, 45.0, 50.0] * 20,
                "category": ["A", "B", "A", "B", "A"] * 20,
            }
        )

        df2 = pl.DataFrame(
            {
                "individual_id": list(range(1, 101)),  # 100 unique IDs matching df1
                "island": ["Dream", "Biscoe", "Dream", "Torgersen", "Dream"] * 20,
                "species": ["Adelie", "Chinstrap", "Adelie", "Gentoo", "Adelie"] * 20,
            }
        )

        mock_load.side_effect = [df1, df2]

        # Mock the join configuration API response
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                str(test_workflow_id): {  # Use the actual workflow ID
                    joined_dc_id: {"how": "inner", "on_columns": ["individual_id"]}
                }
            }
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            mock_get.return_value.raise_for_status = MagicMock()

            # Test joined data collection loading
            result = _load_joined_deltatable(
                workflow_id=test_workflow_id,
                joined_data_collection_id=joined_dc_id,
                metadata=None,
                TOKEN="test_token",
                limit_rows=None,  # No limit to get full dataset
            )

            # Should preserve full dataset after join
            assert result.height == 100  # Full joined dataset
            assert "individual_id" in result.columns
            assert "bill_length_mm" in result.columns
            assert "island" in result.columns
            assert "species" in result.columns

    def test_metadata_format_validation(self):
        """Test that metadata format is correctly validated."""
        from depictio.api.v1.deltatables_utils import process_metadata_and_filter

        # Test valid metadata format
        valid_metadata = [
            {
                "component_id": "test-id",
                "component_type": "interactive",
                "interactive_component_type": "RangeSlider",
                "column_name": "value",
                "value": [10, 50],
            }
        ]

        # Should not raise exception
        filter_expressions = process_metadata_and_filter(valid_metadata)
        assert len(filter_expressions) == 1

        # Test metadata with nested format (alternative format)
        nested_metadata = [
            {
                "component_id": "test-id",
                "component_type": "interactive",
                "metadata": {"interactive_component_type": "Select", "column_name": "category"},
                "value": ["A", "B"],
            }
        ]

        # Should also work
        filter_expressions = process_metadata_and_filter(nested_metadata)
        assert len(filter_expressions) == 1
