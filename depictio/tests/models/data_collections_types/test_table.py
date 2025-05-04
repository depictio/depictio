
import pytest
from pydantic import ValidationError

from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.models.models.data_collections_types.table import DCTableConfig


class TestDCTableConfig:
    """Test suite for DCTableConfig model."""

    def test_valid_config_all_fields(self):
        """Test creating a valid DCTableConfig instance with all fields."""
        config = DCTableConfig(
            format="csv",
            polars_kwargs={"delimiter": ","},
            keep_columns=["col1", "col2"],
            columns_description={"col1": "Description of column 1"},
        )
        assert config.format == "csv"
        assert config.polars_kwargs == {"delimiter": ","}
        assert config.keep_columns == ["col1", "col2"]
        assert config.columns_description == {"col1": "Description of column 1"}

    def test_valid_config_minimal(self):
        """Test creating a valid DCTableConfig instance with minimal fields."""
        config = DCTableConfig(format="csv")
        print(format_pydantic(config))
        assert config.format == "csv"
        assert config.polars_kwargs == {}
        assert config.keep_columns == []
        assert config.columns_description == {}

    def test_format_validation_valid_formats(self):
        """Test format field validation with valid formats."""
        for fmt in ["csv", "tsv", "parquet", "feather", "xls", "xlsx"]:
            config = DCTableConfig(format=fmt)
            assert config.format == fmt

    def test_format_validation_invalid_format(self):
        """Test format field validation with invalid format."""
        with pytest.raises(ValidationError) as exc_info:
            DCTableConfig(format="json")
        assert "format must be one of" in str(exc_info.value)

    def test_format_validation_case_sensitivity(self):
        """Test that format validation is case sensitive."""
        config = DCTableConfig(format="CSV")
        assert config.format == "csv"

    def test_polars_kwargs_valid_dictionary(self):
        """Test polars_kwargs field validation with valid dictionary."""
        config = DCTableConfig(format="csv", polars_kwargs={"delimiter": ","})
        assert config.polars_kwargs == {"delimiter": ","}

    def test_polars_kwargs_empty_dictionary(self):
        """Test polars_kwargs field validation with empty dictionary."""
        config = DCTableConfig(format="csv", polars_kwargs={})
        assert config.polars_kwargs == {}

    def test_polars_kwargs_invalid_value(self):
        """Test polars_kwargs field validation with invalid value."""
        with pytest.raises(Exception, match="Input should be a valid dictionary"):
            DCTableConfig(format="csv", polars_kwargs="not a dict")

    def test_keep_columns_valid_list(self):
        """Test keep_columns field validation with valid list."""
        config = DCTableConfig(format="csv", keep_columns=["col1", "col2"])
        assert config.keep_columns == ["col1", "col2"]

    def test_keep_columns_empty_list(self):
        """Test keep_columns field validation with empty list."""
        config = DCTableConfig(format="csv", keep_columns=[])
        assert config.keep_columns == []

    def test_keep_columns_invalid_value(self):
        """Test keep_columns field validation with invalid value."""
        with pytest.raises(Exception, match="Input should be a valid list"):
            DCTableConfig(format="csv", keep_columns="not a list")

    def test_columns_description_valid_dictionary(self):
        """Test columns_description field with valid dictionary."""
        config = DCTableConfig(
            format="csv",
            columns_description={"col1": "description", "col2": "another description"},
        )
        assert config.columns_description == {
            "col1": "description",
            "col2": "another description",
        }

    def test_columns_description_none_value(self):
        """Test columns_description field with None value."""
        config = DCTableConfig(format="csv")
        assert config.columns_description == {}

    def test_columns_description_empty_dictionary(self):
        """Test columns_description field with empty dictionary."""
        config = DCTableConfig(format="csv", columns_description={})
        assert config.columns_description == {}

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            DCTableConfig(format="csv", extra_field="should not work")
        assert "extra" in str(exc_info.value) or "unexpected" in str(exc_info.value)

    def test_optional_fields_default_values(self):
        """Test that optional fields use default values."""
        config = DCTableConfig(format="csv")
        assert config.polars_kwargs == {}
        assert config.keep_columns == []
        assert config.columns_description == {}
