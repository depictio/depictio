from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from depictio.models.models.data_collections import (
    DataCollection,
    DataCollectionConfig,
    Regex,
    Scan,
    ScanRecursive,
    ScanSingle,
    TableJoinConfig,
    WildcardRegexBase,
)
from depictio.models.models.data_collections_types.jbrowse import DCJBrowse2Config
from depictio.models.models.data_collections_types.table import DCTableConfig


class TestWildcardRegexBase:
    """Test suite for WildcardRegexBase model."""

    def test_valid_config(self):
        """Test creating a valid WildcardRegexBase instance."""
        config = WildcardRegexBase(name="test_wildcard", wildcard_regex="^test.*$")
        assert config.name == "test_wildcard"
        assert config.wildcard_regex == "^test.*$"

    def test_invalid_regex_pattern(self):
        """Test validation with invalid regex pattern."""
        with pytest.raises(ValidationError) as exc_info:
            WildcardRegexBase(name="test", wildcard_regex="[invalid")
        assert "Invalid regex pattern" in str(exc_info.value)

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            WildcardRegexBase(
                name="test", wildcard_regex="^test$", extra_field="should not work"
            )
        assert "extra" in str(exc_info.value) or "unexpected" in str(exc_info.value)


class TestRegex:
    """Test suite for Regex model."""

    def test_valid_config_minimal(self):
        """Test creating a valid Regex instance with minimal fields."""
        config = Regex(pattern="^test.*$")
        assert config.pattern == "^test.*$"
        assert config.wildcards is None

    def test_valid_config_with_wildcards(self):
        """Test creating a valid Regex instance with wildcards."""
        wildcards = [
            WildcardRegexBase(name="w1", wildcard_regex="^.*\\.txt$"),
            WildcardRegexBase(name="w2", wildcard_regex="^.*\\.csv$"),
        ]
        config = Regex(pattern="^test.*$", wildcards=wildcards)
        assert config.pattern == "^test.*$"
        assert len(config.wildcards) == 2
        assert config.wildcards[0].name == "w1"
        assert config.wildcards[1].wildcard_regex == "^.*\\.csv$"

    def test_invalid_regex_pattern(self):
        """Test validation with invalid regex pattern."""
        with pytest.raises(ValidationError) as exc_info:
            Regex(pattern="[invalid")
        assert "Invalid regex pattern" in str(exc_info.value)

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            Regex(pattern="^test$", extra_field="should not work")
        assert "extra" in str(exc_info.value) or "unexpected" in str(exc_info.value)


class TestScanRecursive:
    """Test suite for ScanRecursive model."""

    def test_valid_config_minimal(self):
        """Test creating a valid ScanRecursive instance with minimal fields."""
        regex_config = Regex(pattern="^test.*$")
        config = ScanRecursive(regex_config=regex_config)
        assert config.regex_config == regex_config
        assert config.max_depth is None
        assert config.ignore is None

    def test_valid_config_all_fields(self):
        """Test creating a valid ScanRecursive instance with all fields."""
        regex_config = Regex(pattern="^test.*$")
        config = ScanRecursive(
            regex_config=regex_config, max_depth=5, ignore=["__pycache__", ".git"]
        )
        assert config.regex_config == regex_config
        assert config.max_depth == 5
        assert config.ignore == ["__pycache__", ".git"]

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        regex_config = Regex(pattern="^test.*$")
        with pytest.raises(ValidationError) as exc_info:
            ScanRecursive(regex_config=regex_config, extra_field="should not work")
        assert "extra" in str(exc_info.value) or "unexpected" in str(exc_info.value)


class TestScanSingle:
    """Test suite for ScanSingle model."""

    @patch("depictio.models.utils.get_depictio_context")
    @patch("pathlib.Path.exists")
    def test_valid_config_cli_context(self, mock_exists, mock_context):
        """Test creating a valid ScanSingle instance in CLI context."""
        mock_context.return_value = "cli"
        mock_exists.return_value = True

        config = ScanSingle(filename="/path/to/file.txt")
        assert config.filename == "/path/to/file.txt"

    @patch("depictio.models.models.data_collections.get_depictio_context")
    @patch("pathlib.Path.exists")
    def test_invalid_file_cli_context(self, mock_exists, mock_context):
        """Test validation with non-existent file in CLI context."""
        mock_context.return_value = "cli"
        mock_exists.return_value = False

        with pytest.raises(ValidationError) as exc_info:
            ScanSingle(filename="/path/to/nonexistent.txt")
        assert "does not exist" in str(exc_info.value)

    @patch("depictio.models.utils.get_depictio_context")
    def test_valid_config_non_cli_context(self, mock_context):
        """Test creating a valid ScanSingle instance in non-CLI context."""
        mock_context.return_value = "server"

        config = ScanSingle(filename="file.txt")
        assert config.filename == "file.txt"

    @patch("depictio.models.utils.get_depictio_context")
    def test_empty_filename_non_cli_context(self, mock_context):
        """Test validation with empty filename in non-CLI context."""
        mock_context.return_value = "server"

        with pytest.raises(ValidationError) as exc_info:
            ScanSingle(filename="")
        assert "cannot be empty" in str(exc_info.value)

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            ScanSingle(filename="test.txt", extra_field="should not work")
        assert "extra" in str(exc_info.value) or "unexpected" in str(exc_info.value)


class TestScan:
    """Test suite for Scan model."""

    def test_valid_recursive_mode(self):
        """Test creating a valid Scan instance with recursive mode."""
        scan_params = {"regex_config": {"pattern": "^test.*$"}, "max_depth": 3}
        config = Scan(mode="recursive", scan_parameters=scan_params)
        assert config.mode == "recursive"
        assert isinstance(config.scan_parameters, ScanRecursive)
        assert config.scan_parameters.max_depth == 3

    def test_valid_single_mode(self):
        """Test creating a valid Scan instance with single mode."""
        scan_params = {"filename": "test.txt"}
        config = Scan(mode="single", scan_parameters=scan_params)
        assert config.mode == "single"
        assert isinstance(config.scan_parameters, ScanSingle)
        assert config.scan_parameters.filename == "test.txt"

    def test_invalid_mode(self):
        """Test validation with invalid mode."""
        with pytest.raises(ValidationError) as exc_info:
            Scan(mode="invalid", scan_parameters={})
        assert "mode must be one of" in str(exc_info.value)

    def test_mode_case_insensitive(self):
        """Test that mode validation is case insensitive."""
        scan_params = {"filename": "test.txt"}
        config = Scan(mode="SINGLE", scan_parameters=scan_params)
        assert config.mode == "SINGLE"  # maintains original case


class TestTableJoinConfig:
    """Test suite for TableJoinConfig model."""

    def test_valid_config_all_fields(self):
        """Test creating a valid TableJoinConfig instance with all fields."""
        config = TableJoinConfig(
            on_columns=["col1", "col2"], how="inner", with_dc=["dc1", "dc2"]
        )
        assert config.on_columns == ["col1", "col2"]
        assert config.how == "inner"
        assert config.with_dc == ["dc1", "dc2"]

    def test_valid_config_without_how(self):
        """Test creating a valid TableJoinConfig instance without how field."""
        config = TableJoinConfig(on_columns=["col1"], with_dc=["dc1"])
        assert config.on_columns == ["col1"]
        assert config.how == "inner"  # default value
        assert config.with_dc == ["dc1"]

    def test_join_how_validation_valid_values(self):
        """Test join_how validation with valid values."""
        for how in ["inner", "outer", "left", "right"]:
            config = TableJoinConfig(on_columns=["col1"], how=how, with_dc=["dc1"])
            assert config.how == how

    def test_join_how_validation_invalid_value(self):
        """Test join_how validation with invalid value."""
        with pytest.raises(ValidationError) as exc_info:
            TableJoinConfig(on_columns=["col1"], how="invalid", with_dc=["dc1"])
        assert "join_how must be one of" in str(exc_info.value)

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            TableJoinConfig(
                on_columns=["col1"], with_dc=["dc1"], extra_field="should not work"
            )
        assert "extra" in str(exc_info.value) or "unexpected" in str(exc_info.value)


class TestDataCollectionConfig:
    """Test suite for DataCollectionConfig model."""

    def test_valid_table_config(self):
        """Test creating a valid DataCollectionConfig instance with table type."""
        dc_specific = {"format": "csv"}
        scan_config = {"mode": "single", "scan_parameters": {"filename": "test.txt"}}

        config = DataCollectionConfig(
            type="table",
            metatype="test_meta",
            scan=scan_config,
            dc_specific_properties=dc_specific,
        )
        assert config.type == "table"
        assert config.metatype == "test_meta"
        assert isinstance(config.scan, Scan)
        assert isinstance(config.dc_specific_properties, DCTableConfig)
        assert config.dc_specific_properties.format == "csv"

    def test_valid_jbrowse2_config(self):
        """Test creating a valid DataCollectionConfig instance with jbrowse2 type."""
        # Assuming DCJBrowse2Config has specific required fields
        dc_specific = {}  # Add required fields based on DCJBrowse2Config
        scan_config = {"mode": "single", "scan_parameters": {"filename": "test.txt"}}

        config = DataCollectionConfig(
            type="jbrowse2", scan=scan_config, dc_specific_properties=dc_specific
        )
        assert config.type == "jbrowse2"
        assert isinstance(config.dc_specific_properties, DCJBrowse2Config)

    def test_type_validation_case_insensitive(self):
        """Test that type validation is case insensitive."""
        dc_specific = {"format": "csv"}
        scan_config = {"mode": "single", "scan_parameters": {"filename": "test.txt"}}

        config = DataCollectionConfig(
            type="TABLE", scan=scan_config, dc_specific_properties=dc_specific
        )
        assert config.type == "table"  # returns lowercase

    def test_invalid_type(self):
        """Test validation with invalid type."""
        with pytest.raises(ValidationError) as exc_info:
            DataCollectionConfig(
                type="invalid",
                scan={"mode": "single", "scan_parameters": {"filename": "test.txt"}},
                dc_specific_properties={},
            )
        assert "type must be one of" in str(exc_info.value)

    def test_with_join_config(self):
        """Test creating a DataCollectionConfig instance with join configuration."""
        dc_specific = {"format": "csv"}
        scan_config = {"mode": "single", "scan_parameters": {"filename": "test.txt"}}
        join_config = {"on_columns": ["col1"], "how": "inner", "with_dc": ["dc1"]}

        config = DataCollectionConfig(
            type="table",
            scan=scan_config,
            dc_specific_properties=dc_specific,
            join=join_config,
        )
        assert isinstance(config.join, TableJoinConfig)
        assert config.join.on_columns == ["col1"]


class TestDataCollection:
    """Test suite for DataCollection model."""

    def test_valid_data_collection(self):
        """Test creating a valid DataCollection instance."""
        config_dict = {
            "type": "table",
            "scan": {"mode": "single", "scan_parameters": {"filename": "test.txt"}},
            "dc_specific_properties": {"format": "csv"},
        }

        data_collection = DataCollection(
            data_collection_tag="test_collection", config=config_dict
        )
        assert data_collection.data_collection_tag == "test_collection"
        assert isinstance(data_collection.config, DataCollectionConfig)
        assert data_collection.config.type == "table"

    def test_equality_comparison(self):
        """Test __eq__ method for DataCollection."""
        config_dict = {
            "type": "table",
            "scan": {"mode": "single", "scan_parameters": {"filename": "test.txt"}},
            "dc_specific_properties": {"format": "csv"},
        }

        data_collection1 = DataCollection(
            data_collection_tag="test_collection", config=config_dict
        )
        data_collection2 = DataCollection(
            data_collection_tag="test_collection", config=config_dict
        )
        data_collection3 = DataCollection(
            data_collection_tag="different_tag", config=config_dict
        )

        assert data_collection1 == data_collection2
        assert data_collection1 != data_collection3

        # Test equality with different type
        # assert (data_collection1 == "not_a_data_collection") == NotImplemented


class TestDataCollectionIntegration:
    """Integration tests for DataCollection using real YAML configurations."""

    @patch("depictio.models.models.data_collections.get_depictio_context")
    @patch("pathlib.Path.exists")
    def test_load_iris_yaml_config(self, mock_exists, mock_context):
        """Test loading and validating the Iris dataset YAML configuration."""
        mock_context.return_value = "cli"
        mock_exists.return_value = True  # Simulate file exists

        # Path to the actual YAML file
        yaml_file_path = "depictio/api/v1/configs/iris_dataset/initial_project.yaml"

        # Parse YAML
        with open(yaml_file_path, "r") as file:
            project_config = yaml.safe_load(file)

        # Extract data collection config
        workflow = project_config["workflows"][0]
        dc_data = workflow["data_collections"][0]

        # Validate DataCollection
        data_collection = DataCollection(**dc_data)

        # Assert main properties
        assert data_collection.data_collection_tag == "iris_table"
        assert data_collection.config.type == "table"
        assert data_collection.config.metatype == "Metadata"

        # Assert scan configuration
        assert isinstance(data_collection.config.scan, Scan)
        assert data_collection.config.scan.mode == "single"
        assert isinstance(data_collection.config.scan.scan_parameters, ScanSingle)
        assert (
            data_collection.config.scan.scan_parameters.filename
            == "/app/depictio/api/v1/configs/iris_dataset/iris.csv"
        )

        # Assert DC specific properties
        assert isinstance(data_collection.config.dc_specific_properties, DCTableConfig)
        assert data_collection.config.dc_specific_properties.format == "csv"
        assert data_collection.config.dc_specific_properties.polars_kwargs == {
            "separator": ","
        }

    @patch("depictio.models.models.data_collections.get_depictio_context")
    @patch("pathlib.Path.exists")
    def test_load_iris_yaml_with_file_validation(self, mock_exists, mock_context):
        """Test loading Iris YAML config with file validation in CLI context."""
        mock_context.return_value = "cli"
        mock_exists.return_value = True  # Simulate file exists

        # Load the actual YAML file
        yaml_file_path = "depictio/api/v1/configs/iris_dataset/initial_project.yaml"

        with open(yaml_file_path, "r") as file:
            project_config = yaml.safe_load(file)
        dc_data = project_config["workflows"][0]["data_collections"][0]
        dc_data["config"]["scan"]["scan_parameters"]["filename"] = (
            "/invalid/path/to/file.csv"  # Simulate non-existent file
        )

        # Test with non-existent file
        mock_exists.return_value = False
        with pytest.raises(ValidationError) as exc_info:
            DataCollection(**dc_data)

        # Note: The validation error will be caught for the actual file path
        assert "does not exist" in str(exc_info.value)

    @patch("depictio.models.utils.get_depictio_context")
    def test_load_iris_yaml_in_server_context(self, mock_context):
        """Test loading Iris YAML config in server context (no file validation)."""
        mock_context.return_value = "server"

        # Load the actual YAML file
        yaml_file_path = "depictio/api/v1/configs/iris_dataset/initial_project.yaml"

        with open(yaml_file_path, "r") as file:
            project_config = yaml.safe_load(file)

        # Extract data collection config
        workflow = project_config["workflows"][0]
        dc_data = workflow["data_collections"][0]

        # Should validate without checking file existence in server context
        data_collection = DataCollection(**dc_data)

        # Assert main properties
        assert data_collection.data_collection_tag == "iris_table"
        assert data_collection.config.type == "table"
        assert (
            data_collection.config.scan.scan_parameters.filename
            == "/app/depictio/api/v1/configs/iris_dataset/iris.csv"
        )
